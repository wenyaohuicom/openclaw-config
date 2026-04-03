#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT_ROOT = SKILL_ROOT / "output"

ISSUE_TERMS = ["验证失败", "登不上", "不稳定", "掉", "跳", "异常"]
FOLLOWUP_TERMS = ["好了吗", "好了没有", "修复好了吗", "再催"]
DISPATCH_TERMS = ["安排", "联系", "处理", "稍等", "加急", "我去看", "我加速"]
INFO_TERMS = ["资料", "几号", "账号", "密码", "云机"]
ACK_TERMS = ["1", "好的", "好的哥", "是的", "收到"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Derive a human-like Telegram operations playbook from reply pairs."
    )
    parser.add_argument("--profile", default="default")
    parser.add_argument("--input-root")
    return parser.parse_args()


def output_root(profile, input_root=None):
    if input_root:
        return Path(input_root)
    return DEFAULT_OUTPUT_ROOT if profile == "default" else DEFAULT_OUTPUT_ROOT / profile


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def classify(reply, context):
    text = normalize(reply)
    blob = (" ".join(context[-3:]) + " " + text).strip()
    if any(term in blob for term in ISSUE_TERMS):
        return "issue-report"
    if any(term in blob for term in FOLLOWUP_TERMS):
        return "follow-up"
    if any(term in blob for term in DISPATCH_TERMS):
        return "dispatch"
    if any(term in blob for term in INFO_TERMS):
        return "request-info"
    if text in ACK_TERMS or (len(text) <= 8 and any(term in text for term in ["好的", "收到", "1", "是的"])):
        return "ack"
    if text.startswith("@"):
        return "mention-worker"
    return "other"


def summarize_chat(items):
    cats = Counter()
    top_replies = defaultdict(Counter)
    flows = []
    for item in items:
        ctx = [x.get("text", "") for x in item.get("context", []) if x.get("text")]
        reply = normalize(item.get("assistant_reply", ""))
        category = classify(reply, ctx)
        cats[category] += 1
        top_replies[category][reply] += 1
        if len(flows) < 8:
            flows.append((category, ctx[-3:], reply))
    return cats, top_replies, flows


def describe_chat(chat, cats):
    if chat == "118 ip":
        return "人工主要在这里做 IP 异常转发、@下游处理人、追问修复进度。"
    if "企业微信" in chat or "二梯队" in chat:
        return "人工主要在这里做派单、催办、确认认证进度、补资料。"
    if "风油精" in chat:
        return "这里混有安排、主体处理和账单/费用话题，自动化需要更谨慎。"
    return "这里的人工操作以短句调度和确认状态为主。"


def main():
    args = parse_args()
    root = output_root(args.profile, args.input_root)
    pairs = load_jsonl(root / "derived" / "reply_pairs.jsonl")

    by_chat = defaultdict(list)
    for item in pairs:
        by_chat[item.get("chat_title", "unknown")].append(item)

    out_md = root / "derived" / "human_playbook.md"
    out_json = root / "derived" / "human_playbook.json"

    result = {}
    lines = [
        "# Human Operations Playbook",
        "",
        f"- Profile: {args.profile}",
        f"- Reply pairs analyzed: {len(pairs)}",
        "",
        "这份文档回答的不是“机器人该建议什么”，而是“人工原先通常怎么处理”。",
        "",
    ]

    for chat, items in sorted(by_chat.items(), key=lambda kv: len(kv[1]), reverse=True):
        cats, top_replies, flows = summarize_chat(items)
        result[chat] = {
            "category_counts": dict(cats),
            "top_replies": {name: dict(counter.most_common(8)) for name, counter in top_replies.items()},
            "behavior_summary": describe_chat(chat, cats),
            "representative_flows": [
                {"category": category, "context": ctx, "reply": reply}
                for category, ctx, reply in flows
            ],
        }

        lines.append(f"## {chat}")
        lines.append("")
        lines.append(f"- {describe_chat(chat, cats)}")
        lines.append(f"- 高频类型: {', '.join(f'{name}={count}' for name, count in cats.most_common())}")
        lines.append("")
        lines.append("### 人工常用回复")
        lines.append("")
        for category, counter in sorted(top_replies.items(), key=lambda kv: sum(kv[1].values()), reverse=True):
            if not counter:
                continue
            samples = ", ".join(f"`{text}` x{count}" for text, count in counter.most_common(5))
            lines.append(f"- `{category}`: {samples}")
        lines.append("")
        lines.append("### 典型处理流程")
        lines.append("")
        for category, ctx, reply in flows[:6]:
            lines.append(f"- `{category}` -> 上文: {' / '.join(ctx) if ctx else '无'} -> 人工回复: `{reply}`")
        lines.append("")

    lines.extend([
        "## 总结",
        "",
        "- 人工风格是极短句、少废话、强上下文依赖。",
        "- 人工不是客服口吻，而是调度口吻：先报问题、再@人、再催办、再确认。",
        "- `118 ip` 更像异常分发台；`鸿运,企业微信(二梯队)` 更像派单与跟进台；`风油精,企业微信【87】` 混有费用/主体类内容，需要人工审核更多。",
        "- 想做到“看不出是机器人”，就不能默认输出泛化客服句，必须按群场景复用这些短句和节奏。",
        "",
    ])

    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_md} and {out_json}")


if __name__ == "__main__":
    main()
