#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from suggest_telegram_actions import (
    classify_message,
    find_mentions,
    find_ports,
    find_regions,
    normalize,
    output_root,
    suggested_action,
    suggest_reply,
    build_reply_bank,
    load_jsonl,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent

DONE_TERMS = ["好了", "好了老板", "已处理", "可以了", "正常了", "修复好了", "登了", "好了哥"]
CANCEL_TERMS = ["不用了", "先不续了", "退了", "不接"]
WAITING_TERMS = ["稍等", "处理中", "安排", "联系", "催", "加急", "在修复"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a task queue from exported Telegram work messages."
    )
    parser.add_argument("--profile", default="default")
    parser.add_argument("--input-root")
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Only use messages from the most recent N days within the export",
    )
    parser.add_argument(
        "--chat",
        action="append",
        default=[],
        help="Limit to chat titles containing this text; repeatable",
    )
    return parser.parse_args()


def recent_messages(messages, days, chat_filters):
    if not messages:
        return []
    latest = max(datetime.fromisoformat(row["date"]) for row in messages)
    since = latest - timedelta(days=days)
    rows = []
    for row in messages:
        if chat_filters and not any(f.lower() in row.get("chat_title", "").lower() for f in chat_filters):
            continue
        dt = datetime.fromisoformat(row["date"])
        if dt >= since:
            rows.append(row)
    rows.sort(key=lambda row: (row["date"], row["message_id"]))
    return rows


def subject_key(row):
    text = row.get("text", "")
    ports = find_ports(text)
    mentions = find_mentions(text)
    regions = find_regions(text)
    if ports:
        return f"port:{ports[0]}"
    if mentions:
        return f"worker:{mentions[0]}"
    if regions:
        return f"region:{regions[0]}"
    compact = normalize(text)[:24] or f"message:{row['message_id']}"
    return compact.lower()


def message_state(row, category):
    text = row.get("text", "")
    if any(term in text for term in DONE_TERMS):
        return "done"
    if any(term in text for term in CANCEL_TERMS):
        return "cancelled"
    if category == "issue-report":
        return "new"
    if category == "dispatch-escalate":
        return "processing"
    if category == "follow-up":
        return "waiting"
    if category == "request-info":
        return "waiting-info"
    if any(term in text for term in WAITING_TERMS):
        return "processing"
    return "watch"


def priority_for(category, row):
    if category == "issue-report":
        if find_ports(row.get("text", "")) or find_regions(row.get("text", "")):
            return "high"
        return "medium"
    if category in {"dispatch-escalate", "follow-up", "request-info"}:
        return "medium"
    return "low"


def merge_state(current, incoming):
    order = {
        "new": 1,
        "processing": 2,
        "waiting": 3,
        "waiting-info": 3,
        "watch": 0,
        "done": 4,
        "cancelled": 4,
    }
    if current in {"done", "cancelled"}:
        return current
    if incoming in {"done", "cancelled"}:
        return incoming
    return incoming if order.get(incoming, 0) >= order.get(current, 0) else current


def main():
    args = parse_args()
    root = output_root(args.profile, args.input_root)
    messages = load_jsonl(root / "raw" / "messages.jsonl")
    operation_labels = load_jsonl(root / "derived" / "operation_labels.jsonl")
    reply_bank = build_reply_bank(operation_labels)

    rows = recent_messages(messages, args.days, args.chat)
    grouped = defaultdict(list)
    tasks = {}

    for row in rows:
        category = classify_message(row.get("text", ""))
        if category not in {"issue-report", "dispatch-escalate", "follow-up", "request-info"}:
            continue
        key = (row["chat_title"], subject_key(row))
        grouped[key].append((row, category))

    for index, ((chat_title, subj), items) in enumerate(grouped.items(), start=1):
        items.sort(key=lambda pair: (pair[0]["date"], pair[0]["message_id"]))
        first_row, first_category = items[0]
        latest_row, latest_category = items[-1]
        state = "new"
        category_counts = Counter()
        workers = set()
        ports = set()
        regions = set()
        evidence = []

        for row, category in items:
            category_counts[category] += 1
            state = merge_state(state, message_state(row, category))
            workers.update(find_mentions(row.get("text", "")))
            ports.update(find_ports(row.get("text", "")))
            regions.update(find_regions(row.get("text", "")))
            evidence.append({
                "message_id": row["message_id"],
                "date": row["date"],
                "out": row.get("out", False),
                "category": category,
                "text": row.get("text", ""),
            })

        primary_category = category_counts.most_common(1)[0][0]
        synthetic_message = latest_row.get("text", "")
        task = {
            "task_id": f"{args.profile}-{index:04d}",
            "profile": args.profile,
            "chat_title": chat_title,
            "subject_key": subj,
            "primary_category": primary_category,
            "state": state,
            "priority": priority_for(primary_category, latest_row),
            "message_count": len(items),
            "latest_message_id": latest_row["message_id"],
            "latest_message_date": latest_row["date"],
            "assigned_workers": sorted(workers),
            "ports": sorted(ports),
            "regions": sorted(regions),
            "suggested_action": suggested_action(primary_category, synthetic_message),
            "suggested_reply": suggest_reply(primary_category, synthetic_message, reply_bank),
            "evidence": evidence[-6:],
        }
        tasks[task["task_id"]] = task

    task_list = sorted(
        tasks.values(),
        key=lambda task: (task["priority"] != "high", task["state"] in {"done", "cancelled"}, task["chat_title"], task["latest_message_id"]),
    )

    out_json = root / "derived" / "task_queue.json"
    out_md = root / "derived" / "task_queue_summary.md"
    out_json.write_text(json.dumps(task_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_counts = Counter(task["state"] for task in task_list)
    priority_counts = Counter(task["priority"] for task in task_list)
    category_counts = Counter(task["primary_category"] for task in task_list)

    lines = [
        "# Telegram Task Queue Summary",
        "",
        f"- Profile: {args.profile}",
        f"- Tasks built: {len(task_list)}",
        f"- Source days window: {args.days}",
        "",
        "## State Counts",
        "",
    ]
    for name, count in state_counts.most_common():
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Priority Counts", ""])
    for name, count in priority_counts.most_common():
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Category Counts", ""])
    for name, count in category_counts.most_common():
        lines.append(f"- {name}: {count}")

    lines.extend(["", "## Active Queue", ""])
    for task in task_list[:20]:
        evidence = task["evidence"][-1]["text"] if task["evidence"] else ""
        lines.append(f"### {task['task_id']} | {task['chat_title']}")
        lines.append("")
        lines.append(f"- Subject: {task['subject_key']}")
        lines.append(f"- State: {task['state']}")
        lines.append(f"- Priority: {task['priority']}")
        lines.append(f"- Category: {task['primary_category']}")
        lines.append(f"- Suggested action: {task['suggested_action']}")
        lines.append(f"- Suggested reply: {task['suggested_reply']}")
        if task['assigned_workers']:
            lines.append(f"- Workers: {', '.join(task['assigned_workers'])}")
        if task['regions']:
            lines.append(f"- Regions: {', '.join(task['regions'])}")
        if task['ports']:
            lines.append(f"- Ports: {', '.join(task['ports'])}")
        lines.append(f"- Latest evidence: {evidence}")
        lines.append("")

    out_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {out_json} and {out_md}")


if __name__ == "__main__":
    main()
