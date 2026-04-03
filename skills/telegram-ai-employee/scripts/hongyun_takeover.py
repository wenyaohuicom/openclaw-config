#!/usr/bin/env python3
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT_ROOT = SKILL_ROOT / "output"
RULES_PATH = SKILL_ROOT / "assets" / "hongyun-takeover-rules.json"
TARGET_CHAT = "鸿运,企业微信(二梯队)"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Replay and score a handoff engine for 鸿运,企业微信(二梯队)."
    )
    parser.add_argument("--profile", default="test")
    parser.add_argument("--input-root")
    return parser.parse_args()


def output_root(profile, input_root=None):
    if input_root:
        return Path(input_root)
    return DEFAULT_OUTPUT_ROOT if profile == "default" else DEFAULT_OUTPUT_ROOT / profile


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize(text):
    return " ".join((text or "").split()).strip()


def load_rules():
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def family_of(reply, families):
    reply = normalize(reply)
    for family, phrases in families.items():
        if reply in phrases:
            return family
    return "other"


def match_rule(text, rule):
    text = normalize(text)
    lowered = text.lower()
    if rule.get("whenExact") and text in rule["whenExact"]:
        return True
    if rule.get("whenAny") and any(term.lower() in lowered for term in rule["whenAny"]):
        return True
    return False


def last_other_text(context_items):
    for item in reversed(context_items):
        if item.get("role") == "other" and normalize(item.get("text", "")):
            return normalize(item.get("text", ""))
    return ""


def choose_reply(message_text, context_items, rules):
    text = normalize(message_text)
    context_texts = [normalize(item.get("text", "")) for item in context_items if normalize(item.get("text", ""))]
    context_blob = " | ".join(context_texts[-4:])

    if any(term in text for term in rules["riskTerms"]) and "发一下资料哥" not in context_blob:
        return None, "human-review", "risk"

    # Context-first rules for this specific dispatch group.
    if text == "企业微信要认证":
        return "好的", "ack", "ctx-auth-ack"
    if text == "@HK11808":
        return "我已经在联系兼职了", "dispatch", "ctx-contact-worker"
    if text == "正在联系兼职":
        return "处理", "dispatch", "ctx-progress-step"
    if text == "1" and any(key in context_blob for key in ["你是几号哥", "好的 有问题再找我"]):
        return "1号云机对吧", "request_info", "ctx-worker-id-followup"
    if text == "1" and any(key in context_blob for key in ["118", "处理一下", "加急"]):
        return "1", "ack", "ctx-force-ack"
    if any(key in text for key in ["半个小时了 没有动静", "那么久没有动静"]):
        return "我加速", "dispatch", "ctx-speed-up"
    if "怎么回事 没找到人" in text:
        return "正在努力联系 哥", "dispatch", "ctx-contacting-hard"
    if any(key in text for key in ["云机号", "云机密码", "微信手机号", "企业主体", "归属地", "上号："]):
        if "发一下资料哥" in context_blob or "1号云机对吧" in context_blob:
            return "好的", "ack", "ctx-structured-info-ack"

    for rule in rules["rules"]:
        if match_rule(text, rule):
            return rule["reply"], rule["family"], rule["name"]
    return None, "no-reply", "no-match"


def main():
    args = parse_args()
    root = output_root(args.profile, args.input_root)
    pairs = [p for p in load_jsonl(root / "derived" / "reply_pairs.jsonl") if p.get("chat_title") == TARGET_CHAT]
    rules = load_rules()
    families = rules["replyFamilies"]

    results = []
    exact = 0
    family = 0
    no_reply = 0
    reason_counts = Counter()
    family_counts = Counter()

    for item in pairs:
        actual = normalize(item.get("assistant_reply", ""))
        context_items = item.get("context", [])
        incoming = last_other_text(context_items)
        predicted, predicted_family, reason = choose_reply(incoming, context_items, rules)
        actual_family = family_of(actual, families)
        exact_match = bool(predicted and predicted == actual)
        family_match = bool(predicted and predicted_family == actual_family)
        if exact_match:
            exact += 1
        if family_match:
            family += 1
        if predicted is None:
            no_reply += 1
        reason_counts[reason] += 1
        family_counts[actual_family] += 1
        results.append({
            "incoming": incoming,
            "actual_reply": actual,
            "actual_family": actual_family,
            "predicted_reply": predicted,
            "predicted_family": predicted_family,
            "exact_match": exact_match,
            "family_match": family_match,
            "reason": reason,
        })

    out_jsonl = root / "derived" / "hongyun_takeover_replay.jsonl"
    out_md = root / "derived" / "hongyun_takeover_replay.md"
    out_jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")

    lines = [
        "# Hongyun Takeover Replay",
        "",
        f"- Profile: {args.profile}",
        f"- Samples: {len(results)}",
        f"- Exact match: {exact}",
        f"- Family match: {family}",
        f"- No-reply/human-review: {no_reply}",
        "",
        "## Actual Reply Families",
        "",
    ]
    for name, count in family_counts.most_common():
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Rule Hit Reasons", ""])
    for name, count in reason_counts.most_common():
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Representative Replay", ""])
    for row in results[:18]:
        lines.append(f"- Incoming: {row['incoming']}")
        lines.append(f"  - Actual: {row['actual_reply']} ({row['actual_family']})")
        lines.append(f"  - Predicted: {row['predicted_reply']} ({row['predicted_family']})")
        lines.append(f"  - Reason: {row['reason']}")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_jsonl} and {out_md}")


if __name__ == "__main__":
    main()
