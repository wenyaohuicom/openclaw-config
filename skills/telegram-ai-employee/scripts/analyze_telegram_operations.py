#!/usr/bin/env python3
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT_ROOT = SKILL_ROOT / "output"


ISSUE_TERMS = ["验证失败", "跳", "登不上", "不稳定", "掉", "异常", "修复", "拉主体"]
DISPATCH_TERMS = ["安排", "联系", "处理", "催", "加急", "我去看", "稍等", "在修复"]
FOLLOWUP_TERMS = ["好了吗", "好了没有", "修复好了吗", "没登", "对吧", "好了?"]
INFO_TERMS = ["发一下", "几号", "资料", "账号", "密码", "云机", "二维码"]
ACK_TERMS = ["好的", "好的哥", "1", "是的", "收到", "ok"]

CATEGORY_DESCRIPTIONS = {
    "issue-report": "上报异常、失败、跳地区、登不上、拉主体等具体问题",
    "dispatch-escalate": "安排处理、联系下游、催办、加急、查看状态",
    "follow-up": "追问进度、确认是否修复、继续推进",
    "request-info": "索取资料、确认账号/云机/编号等执行参数",
    "acknowledge": "简单确认、接单、收到",
    "other": "未被规则命中的回复",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Analyze exported Telegram work samples and derive bot-oriented task categories."
    )
    parser.add_argument(
        "--profile",
        default="default",
        help="Profile name matching the export directory under skills/telegram-ai-employee/output/",
    )
    parser.add_argument(
        "--input-root",
        help="Override export root directory; defaults to output/<profile> or output for default profile",
    )
    return parser.parse_args()


def output_root(profile, input_root=None):
    if input_root:
        return Path(input_root)
    return DEFAULT_OUTPUT_ROOT if profile == "default" else DEFAULT_OUTPUT_ROOT / profile


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def classify(reply_text, context_texts):
    text = (reply_text or "").strip()
    blob = " ".join([*context_texts[-3:], text]).lower()

    if any(term in blob for term in ISSUE_TERMS):
        return "issue-report"
    if any(term in blob for term in DISPATCH_TERMS):
        return "dispatch-escalate"
    if any(term in blob for term in FOLLOWUP_TERMS):
        return "follow-up"
    if any(term in blob for term in INFO_TERMS):
        return "request-info"
    if text.lower() in {term.lower() for term in ACK_TERMS}:
        return "acknowledge"
    return "other"


def recommended_action(category):
    return {
        "issue-report": "提取故障对象和症状，@对应下游或记录进待处理队列",
        "dispatch-escalate": "更新工单状态为处理中，并通知对应执行人",
        "follow-up": "查询当前状态；若超时未完成则自动催办",
        "request-info": "向对方补齐账号、资料、云机编号等缺失字段",
        "acknowledge": "做轻量确认，不必重复生成长回复",
        "other": "转人工复核或进入低优先级分析队列",
    }[category]


def main():
    args = parse_args()
    root = output_root(args.profile, args.input_root)
    pair_path = root / "derived" / "reply_pairs.jsonl"
    summary_path = root / "derived" / "operations_summary.md"
    labels_path = root / "derived" / "operation_labels.jsonl"

    if not pair_path.exists():
        raise SystemExit(f"Missing reply pair dataset: {pair_path}")

    pairs = load_jsonl(pair_path)
    labeled = []
    category_counts = Counter()
    chat_category_counts = defaultdict(Counter)
    examples = {}

    for pair in pairs:
        context_texts = [item.get("text", "") for item in pair.get("context", [])]
        category = classify(pair.get("assistant_reply", ""), context_texts)
        item = dict(pair)
        item["operation_category"] = category
        item["recommended_action"] = recommended_action(category)
        labeled.append(item)
        category_counts[category] += 1
        chat_category_counts[pair.get("chat_title", "unknown")][category] += 1
        examples.setdefault(category, item)

    labels_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in labeled),
        encoding="utf-8",
    )

    lines = [
        "# Telegram Operations Summary",
        "",
        f"- Profile: {args.profile}",
        f"- Reply pairs analyzed: {len(labeled)}",
        "",
        "## Category Breakdown",
        "",
    ]
    for category, count in category_counts.most_common():
        lines.append(f"- {category}: {count} - {CATEGORY_DESCRIPTIONS[category]}")

    lines.extend(["", "## Chat Breakdown", ""])
    for chat, counts in sorted(chat_category_counts.items(), key=lambda item: sum(item[1].values()), reverse=True):
        top = ", ".join(f"{name}={count}" for name, count in counts.most_common())
        lines.append(f"- {chat}: {top}")

    lines.extend(["", "## Bot Workflow Draft", ""])
    workflow = [
        "1. 先识别消息属于异常上报、派单催办、进度追问、资料补齐还是简单确认。",
        "2. 异常上报类自动提取对象（IP/账号/群名/地区）和症状，发给下游或写入待处理队列。",
        "3. 派单催办类优先输出短句，并同步状态为处理中。",
        "4. 进度追问类先查队列状态，超时则自动@对应执行人。",
        "5. 资料补齐类先问缺少的字段，不要直接进入处理。",
        "6. 只有低风险的确认型回复才允许全自动发送，其余先做建议或半自动。",
    ]
    for line in workflow:
        lines.append(f"- {line}")

    lines.extend(["", "## Representative Examples", ""])
    for category in ["issue-report", "dispatch-escalate", "follow-up", "request-info", "acknowledge", "other"]:
        example = examples.get(category)
        if not example:
            continue
        lines.append(f"### {category}")
        lines.append("")
        lines.append(f"- Reply: {example['assistant_reply']}")
        lines.append(f"- Chat: {example['chat_title']}")
        lines.append(f"- Recommended action: {example['recommended_action']}")
        if example.get("context"):
            lines.append("- Context:")
            for item in example["context"][-3:]:
                role = item.get("role", "other")
                text = item.get("text", "")
                lines.append(f"  - {role}: {text}")
        lines.append("")

    summary_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {labels_path} and {summary_path}")


if __name__ == "__main__":
    main()
