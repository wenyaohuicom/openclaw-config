#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from analyze_telegram_operations import (
    ACK_TERMS,
    CATEGORY_DESCRIPTIONS,
    DISPATCH_TERMS,
    FOLLOWUP_TERMS,
    INFO_TERMS,
    ISSUE_TERMS,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT_ROOT = SKILL_ROOT / "output"
PORT_RE = re.compile(r"\b\d{4,6}\b")
MENTION_RE = re.compile(r"@[-_A-Za-z0-9]+")
PROVINCES = [
    "安徽", "河南", "湖北", "江苏", "山西", "云南", "昆明", "郑州", "太原",
    "河北", "四川", "广东", "浙江", "福建", "湖南", "江西", "山东",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Suggest bot actions and short replies from exported Telegram work messages."
    )
    parser.add_argument("--profile", default="default")
    parser.add_argument("--input-root")
    parser.add_argument(
        "--recent-per-chat",
        type=int,
        default=12,
        help="How many recent inbound messages to inspect per chat",
    )
    parser.add_argument(
        "--chat",
        action="append",
        default=[],
        help="Limit to chat titles containing this text; repeatable",
    )
    return parser.parse_args()


def output_root(profile, input_root=None):
    if input_root:
        return Path(input_root)
    return DEFAULT_OUTPUT_ROOT if profile == "default" else DEFAULT_OUTPUT_ROOT / profile


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def classify_message(text):
    text = normalize(text)
    blob = text.lower()
    if any(term in blob for term in ISSUE_TERMS):
        return "issue-report"
    if any(term in blob for term in FOLLOWUP_TERMS):
        return "follow-up"
    if any(term in blob for term in INFO_TERMS):
        return "request-info"
    if any(term in blob for term in DISPATCH_TERMS):
        return "dispatch-escalate"
    if blob in {term.lower() for term in ACK_TERMS} or (
        len(text) <= 8 and any(term in text for term in ["收到", "好的", "是的"])
    ):
        return "acknowledge"
    return "other"


def find_mentions(text):
    return MENTION_RE.findall(text or "")


def find_ports(text):
    return PORT_RE.findall(text or "")


def find_regions(text):
    return [name for name in PROVINCES if name in (text or "")]


def build_reply_bank(operation_labels):
    bank = defaultdict(Counter)
    for item in operation_labels:
        reply = normalize(item.get("assistant_reply", ""))
        if reply:
            bank[item.get("operation_category", "other")][reply] += 1
    return bank


def choose_template(category, bank):
    defaults = {
        "issue-report": "收到，我这边安排处理",
        "dispatch-escalate": "正在安排，稍等",
        "follow-up": "我这边再催一下",
        "request-info": "发一下资料哥",
        "acknowledge": "好的",
        "other": "收到，我先看一下",
    }
    # Only reuse historical short replies for categories that are stable and low-risk.
    if category not in {"dispatch-escalate", "follow-up", "request-info", "acknowledge"}:
        return defaults[category]
    common = bank.get(category, Counter()).most_common(8)
    for text, _count in common:
        if 1 <= len(text) <= 18 and not any(token in text for token in ["[REDACTED_", "@IP", "@mq", "："]):
            return text
    return defaults[category]


def suggest_reply(category, message_text, bank):
    mentions = find_mentions(message_text)
    regions = find_regions(message_text)
    ports = find_ports(message_text)
    if category == "issue-report":
        if mentions:
            return f"{mentions[0]} 看一下这个问题"
        if regions and ports:
            return f"{regions[0]} {ports[0]} 这个异常，我这边安排处理"
        return choose_template(category, bank)
    if category == "dispatch-escalate":
        return choose_template(category, bank)
    if category == "follow-up":
        if mentions:
            return f"{mentions[0]} 好了吗？"
        return choose_template(category, bank)
    if category == "request-info":
        if "几号" in (message_text or ""):
            return "你是几号哥"
        if any(term in (message_text or "") for term in ["资料", "账号", "密码", "云机"]):
            return "发一下资料哥"
        return choose_template(category, bank)
    if category == "acknowledge":
        return choose_template(category, bank)
    return choose_template(category, bank)


def suggested_action(category, message_text):
    ports = find_ports(message_text)
    regions = find_regions(message_text)
    mentions = find_mentions(message_text)
    detail = []
    if regions:
        detail.append("region=" + "/".join(regions[:2]))
    if ports:
        detail.append("port=" + "/".join(ports[:2]))
    if mentions:
        detail.append("worker=" + "/".join(mentions[:2]))
    suffix = f" ({', '.join(detail)})" if detail else ""
    base = {
        "issue-report": "创建异常工单并转给下游处理",
        "dispatch-escalate": "标记为处理中并通知执行人",
        "follow-up": "查询工单状态并自动催办",
        "request-info": "补齐执行资料后再继续",
        "acknowledge": "做轻量确认，不新建工单",
        "other": "低置信度，建议人工复核",
    }[category]
    return base + suffix


def confidence_for(category, message_text):
    if category in {"issue-report", "dispatch-escalate", "request-info"}:
        return "high"
    if category in {"follow-up", "acknowledge"}:
        return "medium"
    return "low"


def recent_inbound_candidates(messages, recent_per_chat, chat_filters):
    by_chat = defaultdict(list)
    for row in messages:
        if chat_filters and not any(f.lower() in row.get("chat_title", "").lower() for f in chat_filters):
            continue
        by_chat[row["chat_id"]].append(row)

    selected = []
    for chat_rows in by_chat.values():
        chat_rows.sort(key=lambda row: (row["date"], row["message_id"]))
        inbound = [row for row in chat_rows if (not row.get("out")) and row.get("text")]
        selected.extend(inbound[-recent_per_chat:])
    selected.sort(key=lambda row: (row["date"], row["message_id"]))
    return selected, by_chat


def find_historical_reply(chat_rows, message_id):
    seen = False
    for row in chat_rows:
        if row["message_id"] == message_id:
            seen = True
            continue
        if not seen:
            continue
        if row.get("out") and row.get("text"):
            return row.get("text")
        if not row.get("out") and row.get("text"):
            break
    return None


def main():
    args = parse_args()
    root = output_root(args.profile, args.input_root)
    messages = load_jsonl(root / "raw" / "messages.jsonl")
    operation_labels = load_jsonl(root / "derived" / "operation_labels.jsonl")
    reply_bank = build_reply_bank(operation_labels)

    candidates, by_chat = recent_inbound_candidates(messages, args.recent_per_chat, args.chat)
    suggestions = []
    category_counts = Counter()

    for row in candidates:
        category = classify_message(row.get("text", ""))
        suggestion = {
            "chat_title": row.get("chat_title"),
            "message_id": row.get("message_id"),
            "date": row.get("date"),
            "message_text": row.get("text"),
            "operation_category": category,
            "category_description": CATEGORY_DESCRIPTIONS[category],
            "confidence": confidence_for(category, row.get("text", "")),
            "suggested_action": suggested_action(category, row.get("text", "")),
            "suggested_reply": suggest_reply(category, row.get("text", ""), reply_bank),
            "historical_reply": find_historical_reply(by_chat[row["chat_id"]], row["message_id"]),
        }
        suggestions.append(suggestion)
        category_counts[category] += 1

    out_jsonl = root / "derived" / "action_suggestions.jsonl"
    out_md = root / "derived" / "action_suggestions.md"
    out_jsonl.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in suggestions), encoding="utf-8")

    lines = [
        "# Telegram Action Suggestions",
        "",
        f"- Profile: {args.profile}",
        f"- Candidate inbound messages: {len(suggestions)}",
        "",
        "## Category Counts",
        "",
    ]
    for category, count in category_counts.most_common():
        lines.append(f"- {category}: {count}")

    lines.extend(["", "## Suggestions", ""])
    for item in suggestions[-20:]:
        dt = datetime.fromisoformat(item["date"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"### {item['chat_title']} | {dt}")
        lines.append("")
        lines.append(f"- Incoming: {item['message_text']}")
        lines.append(f"- Category: {item['operation_category']} ({item['confidence']})")
        lines.append(f"- Suggested action: {item['suggested_action']}")
        lines.append(f"- Suggested reply: {item['suggested_reply']}")
        if item.get("historical_reply"):
            lines.append(f"- Historical reply: {item['historical_reply']}")
        lines.append("")

    out_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {out_jsonl} and {out_md}")


if __name__ == "__main__":
    main()
