#!/usr/bin/env python3
import argparse
import asyncio
import json
from collections import Counter
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

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
RELEVANT_QUEUE_CATEGORIES = {"issue-report", "dispatch-escalate", "follow-up", "request-info"}


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
    return parser.parse_args()


class LiveDispatchState:
    def __init__(self, profile, root, reply_bank):
        self.profile = profile
        self.root = root
        self.reply_bank = reply_bank
        self.runtime_dir = root / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.suggestions_path = self.runtime_dir / "live_suggestions.jsonl"
        self.queue_path = self.runtime_dir / "live_task_queue.json"
        self.summary_path = self.runtime_dir / "live_task_queue_summary.md"
        self.tasks = {}
        self.suggestions = []

    def process_row(self, row):
        category = classify_message(row.get("text", ""))
        suggestion = {
            "profile": self.profile,
            "chat_title": row.get("chat_title"),
            "message_id": row.get("message_id"),
            "date": row.get("date"),
            "message_text": row.get("text"),
            "operation_category": category,
            "confidence": confidence_for(category, row.get("text", "")),
            "suggested_action": suggested_action(category, row.get("text", "")),
            "suggested_reply": suggest_reply(category, row.get("text", ""), self.reply_bank),
            "ports": find_ports(row.get("text", "")),
            "regions": find_regions(row.get("text", "")),
            "workers": find_mentions(row.get("text", "")),
        }
        self.suggestions.append(suggestion)
        if category in RELEVANT_QUEUE_CATEGORIES:
            self._update_task(row, category, suggestion)
        self._save()
        return suggestion

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
                "evidence": [],
            }
            self.tasks[task_key] = task

        task["state"] = merge_state(task["state"], message_state(row, category))
        task["priority"] = priority_for(category, row)
        task["latest_message_id"] = row["message_id"]
        task["latest_message_date"] = row["date"]
        task["suggested_action"] = suggestion["suggested_action"]
        task["suggested_reply"] = suggestion["suggested_reply"]
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
        self.queue_path.write_text(json.dumps(task_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        state_counts = Counter(item["state"] for item in task_list)
        lines = [
            "# Live Telegram Task Queue",
            "",
            f"- Profile: {self.profile}",
            f"- Suggestions processed: {len(self.suggestions)}",
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


async def process_recent_messages(client, dialogs, state, recent_per_chat):
    count = 0
    for dialog_id, dialog_meta in dialogs.items():
        rows = []
        async for message in client.iter_messages(dialog_id, limit=recent_per_chat):
            if message.out or not normalize(message.message):
                continue
            rows.append(row_from_message(dialog_meta, message))
        for row in reversed(rows):
            state.process_row(row)
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
        suggestion = state.process_row(row_from_message(dialog_meta, event.message))
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


async def main_async():
    args = parse_args()
    profile, root, session_path = profile_paths(args)
    api_id = int(env_required("TG_API_ID"))
    api_hash = env_required("TG_API_HASH")

    operation_labels = load_jsonl(root / "derived" / "operation_labels.jsonl")
    reply_bank = build_reply_bank(operation_labels)
    state = LiveDispatchState(profile, root, reply_bank)

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Session is not authorized. Log in with collect_telegram_work.py first.")

    dialogs = await resolve_dialogs(client, args)
    if not dialogs:
        raise SystemExit("No dialogs matched. Add --chat filters or widen --scope.")

    recent_count = await process_recent_messages(client, dialogs, state, args.recent_per_chat)
    print(f"Processed {recent_count} recent inbound messages across {len(dialogs)} chats.")
    print(f"Live suggestions: {state.suggestions_path}")
    print(f"Live queue: {state.queue_path}")

    if args.watch:
        await watch_messages(client, dialogs, state, args.watch_seconds)

    await client.disconnect()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
