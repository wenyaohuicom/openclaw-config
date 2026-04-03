#!/usr/bin/env python3
import argparse
import asyncio
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, events

from collect_telegram_work import (
    default_output_dir,
    default_session_path,
    dialog_in_scope,
    dialog_matches,
    dialog_scope_name,
    env_required,
    normalize,
    parse_scope,
    resolve_profile,
)
from suggest_telegram_actions import (
    build_reply_bank,
    classify_message,
    confidence_for,
    find_mentions,
    find_ports,
    find_regions,
    load_jsonl,
    suggest_reply,
    suggested_action,
)
from build_telegram_task_queue import merge_state, message_state, priority_for, subject_key
from hongyun_takeover import TARGET_CHAT as HONGYUN_CHAT, choose_reply as choose_hongyun_reply, load_rules as load_hongyun_rules

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
RELEVANT_QUEUE_CATEGORIES = {"issue-report", "dispatch-escalate", "follow-up", "request-info"}
CATEGORY_ALIAS = {
    "dispatch-escalate": "dispatch",
    "request-info": "request-info",
    "follow-up": "follow-up",
    "acknowledge": "ack",
    "issue-report": "issue-report",
    "other": "other",
}
SAFE_DEFAULT_ALLOW = {"acknowledge", "dispatch-escalate", "follow-up", "request-info"}
HIGH_RISK_TERMS = ["账单", "半价", "多少钱", "价格", "USDT", "主体", "拉主体", "不接粉", "回访半价"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Watch Telegram work chats, classify new messages, and update a live task queue."
    )
    parser.add_argument("--profile", default="default")
    parser.add_argument("--output-root")
    parser.add_argument("--session")
    parser.add_argument("--scope", default="users,groups")
    parser.add_argument("--chat", action="append", default=[], help="Chat title filter; repeatable")
    parser.add_argument("--dialog-limit", type=int, default=100)
    parser.add_argument("--recent-per-chat", type=int, default=5)
    parser.add_argument("--watch", action="store_true", help="Keep listening for new messages")
    parser.add_argument(
        "--watch-seconds",
        type=int,
        default=0,
        help="Optional timeout for watch mode; 0 means run until interrupted",
    )
    parser.add_argument(
        "--send-mode",
        choices=["shadow", "whitelist"],
        default="shadow",
        help="shadow only logs拟人回复; whitelist may auto-send only approved categories",
    )
    parser.add_argument(
        "--allow-category",
        action="append",
        default=[],
        help="Auto-send allowlist category; repeatable. Examples: acknowledge, dispatch-escalate",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=int,
        default=180,
        help="Minimum seconds between auto-sends in the same chat",
    )
    parser.add_argument(
        "--reply-style",
        choices=["mimic", "generic"],
        default="mimic",
        help="mimic uses per-chat human playbook when possible",
    )
    return parser.parse_args()


class LiveDispatchState:
    def __init__(self, profile, root, reply_bank, playbook, args):
        self.profile = profile
        self.root = root
        self.reply_bank = reply_bank
        self.playbook = playbook
        self.args = args
        self.runtime_dir = root / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.suggestions_path = self.runtime_dir / "live_suggestions.jsonl"
        self.queue_path = self.runtime_dir / "live_task_queue.json"
        self.summary_path = self.runtime_dir / "live_task_queue_summary.md"
        self.sent_log_path = self.runtime_dir / "live_sent_log.jsonl"
        self.tasks = {}
        self.suggestions = []
        self.sent_log = []
        self.last_sent_at = {}
        self.allowed_categories = set(args.allow_category or SAFE_DEFAULT_ALLOW)
        self.chat_context = defaultdict(list)
        self.hongyun_rules = load_hongyun_rules()

    def process_row(self, row):
        category = classify_message(row.get("text", ""))
        suggestion = {
            "profile": self.profile,
            "chat_id": row.get("chat_id"),
            "chat_title": row.get("chat_title"),
            "message_id": row.get("message_id"),
            "date": row.get("date"),
            "message_text": row.get("text"),
            "operation_category": category,
            "confidence": confidence_for(category, row.get("text", "")),
            "suggested_action": suggested_action(category, row.get("text", "")),
            "suggested_reply": self.render_reply(row, category),
            "ports": find_ports(row.get("text", "")),
            "regions": find_regions(row.get("text", "")),
            "workers": find_mentions(row.get("text", "")),
            "send_mode": self.args.send_mode,
            "auto_send_eligible": self.is_auto_send_eligible(row, category),
            "auto_sent": False,
        }
        self.suggestions.append(suggestion)
        if category in RELEVANT_QUEUE_CATEGORIES:
            self._update_task(row, category, suggestion)
        self.chat_context[row["chat_id"]].append({"role": "other", "text": row.get("text", "")})
        self.chat_context[row["chat_id"]] = self.chat_context[row["chat_id"]][-8:]
        self._save()
        return suggestion

    def render_reply(self, row, category):
        if self.args.reply_style != "mimic":
            return suggest_reply(category, row.get("text", ""), self.reply_bank)

        # Per-chat takeover override for the first production target group.
        if row.get("chat_title") == HONGYUN_CHAT:
            context_items = self.chat_context.get(row["chat_id"], [])
            predicted, predicted_family, _reason = choose_hongyun_reply(
                row.get("text", ""), context_items, self.hongyun_rules
            )
            if predicted:
                return predicted

        # Only mimic per-chat phrasing for categories with stable, low-risk short replies.
        if category not in {"acknowledge", "dispatch-escalate", "follow-up", "request-info"}:
            return suggest_reply(category, row.get("text", ""), self.reply_bank)

        chat_playbook = self.playbook.get(row.get("chat_title"), {})
        top_replies = chat_playbook.get("top_replies", {})
        alias = CATEGORY_ALIAS.get(category, category)
        counter = top_replies.get(alias, {})
        for reply, _count in counter.items():
            if self.reply_is_safe(reply, category):
                return reply
        return suggest_reply(category, row.get("text", ""), self.reply_bank)

    def reply_is_safe(self, reply, category):
        if not reply:
            return False
        if any(term in reply for term in HIGH_RISK_TERMS):
            return False
        if category == "issue-report":
            return False
        return True

    def is_auto_send_eligible(self, row, category):
        if self.args.send_mode != "whitelist":
            return False
        if category not in self.allowed_categories:
            return False
        if category == "other":
            return False
        if any(term in row.get("text", "") for term in HIGH_RISK_TERMS):
            return False
        last = self.last_sent_at.get(row["chat_id"])
        current_ts = datetime.fromisoformat(row["date"]).timestamp()
        if last and current_ts - last < self.args.cooldown_seconds:
            return False
        return True

    def mark_sent(self, row, suggestion, sent_message_id):
        ts = datetime.fromisoformat(row["date"]).timestamp()
        self.last_sent_at[row["chat_id"]] = ts
        suggestion["auto_sent"] = True
        suggestion["sent_message_id"] = sent_message_id
        event = {
            "profile": self.profile,
            "chat_id": row["chat_id"],
            "chat_title": row["chat_title"],
            "source_message_id": row["message_id"],
            "sent_message_id": sent_message_id,
            "date": datetime.now(timezone.utc).isoformat(),
            "reply": suggestion["suggested_reply"],
            "category": suggestion["operation_category"],
        }
        self.sent_log.append(event)
        self.chat_context[row["chat_id"]].append({"role": "assistant", "text": suggestion["suggested_reply"]})
        self.chat_context[row["chat_id"]] = self.chat_context[row["chat_id"]][-8:]
        self._save()

    def _update_task(self, row, category, suggestion):
        task_key = (row["chat_title"], subject_key(row))
        task_id = f"{self.profile}-{len(self.tasks) + 1:04d}"
        task = self.tasks.get(task_key)
        if not task:
            task = {
                "task_id": task_id,
                "profile": self.profile,
                "chat_title": row["chat_title"],
                "subject_key": task_key[1],
                "state": "new",
                "priority": priority_for(category, row),
                "primary_category": category,
                "assigned_workers": [],
                "ports": [],
                "regions": [],
                "message_count": 0,
                "latest_message_id": row["message_id"],
                "latest_message_date": row["date"],
                "suggested_action": suggestion["suggested_action"],
                "suggested_reply": suggestion["suggested_reply"],
                "auto_send_eligible": suggestion["auto_send_eligible"],
                "evidence": [],
            }
            self.tasks[task_key] = task

        task["state"] = merge_state(task["state"], message_state(row, category))
        task["priority"] = priority_for(category, row)
        task["latest_message_id"] = row["message_id"]
        task["latest_message_date"] = row["date"]
        task["suggested_action"] = suggestion["suggested_action"]
        task["suggested_reply"] = suggestion["suggested_reply"]
        task["auto_send_eligible"] = suggestion["auto_send_eligible"]
        task["message_count"] += 1
        task["primary_category"] = category if task["message_count"] == 1 else task["primary_category"]
        task["assigned_workers"] = sorted(set(task["assigned_workers"]) | set(suggestion["workers"]))
        task["ports"] = sorted(set(task["ports"]) | set(suggestion["ports"]))
        task["regions"] = sorted(set(task["regions"]) | set(suggestion["regions"]))
        task["evidence"].append(
            {
                "message_id": row["message_id"],
                "date": row["date"],
                "category": category,
                "text": row.get("text", ""),
            }
        )
        task["evidence"] = task["evidence"][-8:]

    def _save(self):
        with self.suggestions_path.open("w", encoding="utf-8") as fh:
            for item in self.suggestions[-500:]:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

        task_list = sorted(
            self.tasks.values(),
            key=lambda item: (
                item["priority"] != "high",
                item["state"] in {"done", "cancelled"},
                item["chat_title"],
                item["latest_message_id"],
            ),
        )
        self.queue_path.write_text(
            json.dumps(task_list, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        with self.sent_log_path.open("w", encoding="utf-8") as fh:
            for item in self.sent_log[-500:]:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

        state_counts = Counter(item["state"] for item in task_list)
        lines = [
            "# Live Telegram Task Queue",
            "",
            f"- Profile: {self.profile}",
            f"- Send mode: {self.args.send_mode}",
            f"- Suggestions processed: {len(self.suggestions)}",
            f"- Auto-sent replies: {len(self.sent_log)}",
            f"- Active tasks: {len(task_list)}",
            "",
            "## State Counts",
            "",
        ]
        for name, count in state_counts.most_common():
            lines.append(f"- {name}: {count}")
        lines.extend(["", "## Active Tasks", ""])
        for task in task_list[:20]:
            evidence = task["evidence"][-1]["text"] if task["evidence"] else ""
            lines.append(f"### {task['task_id']} | {task['chat_title']}")
            lines.append("")
            lines.append(f"- Subject: {task['subject_key']}")
            lines.append(f"- State: {task['state']}")
            lines.append(f"- Priority: {task['priority']}")
            lines.append(f"- Auto-send eligible: {'yes' if task.get('auto_send_eligible') else 'no'}")
            lines.append(f"- Suggested action: {task['suggested_action']}")
            lines.append(f"- Suggested reply: {task['suggested_reply']}")
            lines.append(f"- Latest evidence: {evidence}")
            lines.append("")
        self.summary_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def row_from_message(dialog_meta, message):
    dt = message.date.astimezone(timezone.utc)
    return {
        "chat_id": dialog_meta["id"],
        "chat_title": dialog_meta["name"],
        "message_id": message.id,
        "date": dt.isoformat(),
        "sender_id": getattr(message, "sender_id", None),
        "out": bool(message.out),
        "reply_to_msg_id": getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None),
        "text": normalize(message.message),
        "media": bool(message.media),
        "scope": dialog_meta["scope"],
        "username": dialog_meta.get("username"),
    }


async def resolve_dialogs(client, args):
    include_filters = [item.lower() for item in args.chat]
    scopes = parse_scope(args.scope)
    dialogs = {}
    async for dialog in client.iter_dialogs(limit=args.dialog_limit):
        if not dialog_in_scope(dialog, scopes):
            continue
        if include_filters and not dialog_matches(dialog, include_filters, []):
            continue
        dialogs[dialog.id] = {
            "id": dialog.id,
            "name": dialog.name,
            "scope": dialog_scope_name(dialog),
            "username": getattr(dialog.entity, "username", None),
        }
    return dialogs


async def maybe_send_reply(client, row, suggestion, state):
    if not suggestion.get("auto_send_eligible"):
        return None
    sent = await client.send_message(row["chat_id"], suggestion["suggested_reply"])
    state.mark_sent(row, suggestion, sent.id)
    return sent.id


async def process_recent_messages(client, dialogs, state, recent_per_chat):
    count = 0
    for dialog_id, dialog_meta in dialogs.items():
        rows = []
        async for message in client.iter_messages(dialog_id, limit=recent_per_chat):
            if message.out or not normalize(message.message):
                continue
            rows.append(row_from_message(dialog_meta, message))
        for row in reversed(rows):
            suggestion = state.process_row(row)
            await maybe_send_reply(client, row, suggestion, state)
            count += 1
    return count


async def watch_messages(client, dialogs, state, watch_seconds):
    chat_ids = list(dialogs.keys())

    @client.on(events.NewMessage(chats=chat_ids))
    async def handler(event):
        if event.message.out or not normalize(event.message.message):
            return
        dialog_meta = dialogs.get(event.chat_id)
        if not dialog_meta:
            return
        row = row_from_message(dialog_meta, event.message)
        suggestion = state.process_row(row)
        await maybe_send_reply(client, row, suggestion, state)
        print(json.dumps(suggestion, ensure_ascii=False))

    if watch_seconds and watch_seconds > 0:
        await asyncio.sleep(watch_seconds)
    else:
        await client.run_until_disconnected()


def profile_paths(args):
    profile = resolve_profile(args.profile)
    root = Path(args.output_root) if args.output_root else default_output_dir(profile)
    session_path = Path(args.session) if args.session else default_session_path(profile)
    return profile, root, session_path


def load_human_playbook(root):
    path = root / "derived" / "human_playbook.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


async def main_async():
    args = parse_args()
    profile, root, session_path = profile_paths(args)
    api_id = int(env_required("TG_API_ID"))
    api_hash = env_required("TG_API_HASH")

    operation_labels = load_jsonl(root / "derived" / "operation_labels.jsonl")
    reply_bank = build_reply_bank(operation_labels)
    playbook = load_human_playbook(root)
    state = LiveDispatchState(profile, root, reply_bank, playbook, args)

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Session is not authorized. Log in with collect_telegram_work.py first.")

    dialogs = await resolve_dialogs(client, args)
    if not dialogs:
        raise SystemExit("No dialogs matched. Add --chat filters or widen --scope.")

    recent_count = await process_recent_messages(client, dialogs, state, args.recent_per_chat)
    print(f"Processed {recent_count} recent inbound messages across {len(dialogs)} chats.")
    print(f"Send mode: {args.send_mode}")
    print(f"Live suggestions: {state.suggestions_path}")
    print(f"Live queue: {state.queue_path}")
    print(f"Sent log: {state.sent_log_path}")

    if args.watch:
        await watch_messages(client, dialogs, state, args.watch_seconds)

    await client.disconnect()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
