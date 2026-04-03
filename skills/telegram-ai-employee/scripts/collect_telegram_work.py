#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

try:
    from telethon import TelegramClient
except ImportError as exc:
    raise SystemExit(
        "Telethon is required. Install it with `pip install telethon` before running this script."
    ) from exc


PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)")
OTP_RE = re.compile(r"\b(?:code|otp|password|verification|login code)\b[:\s-]*[A-Za-z0-9-]{4,}", re.IGNORECASE)
TOKEN_RE = re.compile(r"\b(?:sk|rk|pk|ghp|gho|ghu|glpat|eyJ)[A-Za-z0-9._-]{8,}\b")
QUERY_SECRET_RE = re.compile(r"([?&](?:token|code|key|auth|access_token|refresh_token|password)=)[^&\s]+", re.IGNORECASE)
PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
SECRETS_DIR = SKILL_ROOT / "secrets"
OUTPUT_ROOT = SKILL_ROOT / "output"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export Telegram work activity from a personal account and derive training examples."
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("TG_PROFILE", "default"),
        help="Account profile name; keeps session and output isolated per account",
    )
    parser.add_argument("--output", help="Output root directory")
    parser.add_argument("--session", help="Telethon session file path")
    parser.add_argument("--days", type=int, default=14, help="Look back N days")
    parser.add_argument(
        "--phone",
        default=os.getenv("TG_PHONE"),
        help="Telegram login phone number; prompts interactively when omitted in a TTY",
    )
    parser.add_argument(
        "--dialog",
        action="append",
        default=[],
        help="Dialog title or username filter; repeatable",
    )
    parser.add_argument(
        "--exclude-dialog",
        action="append",
        default=[],
        help="Dialog title or username exclusion filter; repeatable",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Work keyword filter for dialog title, username, or message text; repeatable",
    )
    parser.add_argument(
        "--scope",
        default="users,groups",
        help="Comma-separated dialog scopes to export; default is private chats plus groups",
    )
    parser.add_argument(
        "--dialog-limit", type=int, default=50, help="Maximum dialogs to scan"
    )
    parser.add_argument(
        "--message-limit", type=int, default=5000, help="Maximum messages to export"
    )
    parser.add_argument(
        "--min-outbound",
        type=int,
        default=3,
        help="Minimum owner outbound messages per dialog",
    )
    parser.add_argument(
        "--list-dialogs",
        action="store_true",
        help="List matching dialogs and exit without exporting messages",
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Disable text redaction in exports",
    )
    return parser.parse_args()


def env_required(name):
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def normalize(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def resolve_profile(profile):
    profile = normalize(profile) or "default"
    if not PROFILE_RE.match(profile):
        raise SystemExit(
            "Invalid profile name. Use only letters, digits, dot, underscore, or hyphen."
        )
    return profile


def default_output_dir(profile):
    return OUTPUT_ROOT if profile == "default" else OUTPUT_ROOT / profile


def default_session_path(profile):
    name = "telegram-user.session" if profile == "default" else f"telegram-user.{profile}.session"
    return SECRETS_DIR / name


def parse_scope(scope_value):
    scopes = {
        item.strip().lower() for item in (scope_value or "").split(",") if item.strip()
    }
    if not scopes:
        scopes = {"users", "groups"}
    allowed = {"users", "groups", "channels", "all"}
    invalid = scopes - allowed
    if invalid:
        raise SystemExit(f"Invalid scope value(s): {', '.join(sorted(invalid))}")
    if "all" in scopes:
        return {"users", "groups", "channels"}
    return scopes


def dialog_scope_name(dialog):
    if dialog.is_user:
        return "user"
    if dialog.is_group:
        return "group"
    if dialog.is_channel:
        return "channel"
    return "other"


def dialog_in_scope(dialog, scopes):
    return (
        ("users" in scopes and bool(dialog.is_user))
        or ("groups" in scopes and bool(dialog.is_group))
        or ("channels" in scopes and bool(dialog.is_channel))
    )


def haystacks_for_dialog(dialog):
    return {
        normalize(getattr(dialog, "name", "")).lower(),
        normalize(getattr(dialog.entity, "title", "")).lower(),
        normalize(getattr(dialog.entity, "username", "")).lower(),
    }


def matches_any_filter(values, filters):
    if not filters:
        return True
    return any(any(term in value for value in values if value) for term in filters)


def matches_no_exclusions(values, filters):
    return not any(any(term in value for value in values if value) for term in filters)


def dialog_matches(dialog, include_filters, exclude_filters):
    values = haystacks_for_dialog(dialog)
    return matches_any_filter(values, include_filters) and matches_no_exclusions(
        values, exclude_filters
    )


def redact_text(text):
    if not text:
        return text
    text = PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = OTP_RE.sub("[REDACTED_OTP]", text)
    text = TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    text = QUERY_SECRET_RE.sub(r"\1[REDACTED]", text)
    return text


def row_matches_keywords(row, keywords):
    if not keywords:
        return True
    haystack = " ".join(
        [
            normalize(row.get("chat_title", "")).lower(),
            normalize(row.get("username", "")).lower(),
            normalize(row.get("text", "")).lower(),
        ]
    )
    return any(keyword in haystack for keyword in keywords)


async def collect_messages(client, args, since_dt):
    include_filters = [item.lower() for item in args.dialog]
    exclude_filters = [item.lower() for item in args.exclude_dialog]
    scopes = parse_scope(args.scope)
    dialogs = []
    exported = []
    per_chat_outbound = Counter()

    async for dialog in client.iter_dialogs(limit=args.dialog_limit):
        if not dialog_in_scope(dialog, scopes):
            continue
        if not dialog_matches(dialog, include_filters, exclude_filters):
            continue

        dialog_row = {
            "id": dialog.id,
            "name": dialog.name,
            "is_user": dialog.is_user,
            "is_group": dialog.is_group,
            "is_channel": dialog.is_channel,
            "username": getattr(dialog.entity, "username", None),
            "scope": dialog_scope_name(dialog),
        }
        dialogs.append(dialog_row)

        if args.list_dialogs:
            continue

        async for message in client.iter_messages(dialog.id):
            if len(exported) >= args.message_limit:
                return dialogs, exported, per_chat_outbound
            if not message.date:
                continue
            dt = message.date.astimezone(timezone.utc)
            if dt < since_dt:
                break
            text = normalize(message.message)
            row = {
                "chat_id": dialog.id,
                "chat_title": dialog.name,
                "message_id": message.id,
                "date": dt.isoformat(),
                "sender_id": getattr(message, "sender_id", None),
                "out": bool(message.out),
                "reply_to_msg_id": getattr(
                    getattr(message, "reply_to", None), "reply_to_msg_id", None
                ),
                "text": text,
                "media": bool(message.media),
                "scope": dialog_scope_name(dialog),
                "username": getattr(dialog.entity, "username", None),
            }
            exported.append(row)
            if row["out"] and text:
                per_chat_outbound[dialog.id] += 1

    return dialogs, exported, per_chat_outbound


def filter_messages(dialogs, messages, args):
    keywords = [normalize(item).lower() for item in args.keyword if normalize(item)]
    by_chat = defaultdict(list)
    for row in messages:
        by_chat[row["chat_id"]].append(row)

    if keywords:
        allowed_chat_ids = set()
        for dialog in dialogs:
            dialog_blob = " ".join(
                [
                    normalize(dialog.get("name", "")).lower(),
                    normalize(dialog.get("username", "")).lower(),
                ]
            )
            if any(keyword in dialog_blob for keyword in keywords):
                allowed_chat_ids.add(dialog["id"])
                continue
            if any(row_matches_keywords(row, keywords) for row in by_chat.get(dialog["id"], [])):
                allowed_chat_ids.add(dialog["id"])
    else:
        allowed_chat_ids = {dialog["id"] for dialog in dialogs}

    filtered_dialogs = [dialog for dialog in dialogs if dialog["id"] in allowed_chat_ids]
    filtered_messages = [row for row in messages if row["chat_id"] in allowed_chat_ids]
    return filtered_dialogs, filtered_messages, keywords


def apply_redaction(messages, enabled):
    if not enabled:
        return messages
    redacted = []
    for row in messages:
        new_row = dict(row)
        new_row["text"] = redact_text(row.get("text", ""))
        redacted.append(new_row)
    return redacted


def derive_reply_pairs(messages, min_outbound):
    by_chat = defaultdict(list)
    for row in messages:
        by_chat[row["chat_id"]].append(row)

    pairs = []
    response_minutes = []

    for chat_rows in by_chat.values():
        chat_rows.sort(key=lambda row: (row["date"], row["message_id"]))
        outbound_count = sum(1 for row in chat_rows if row["out"] and row["text"])
        if outbound_count < min_outbound:
            continue

        for index, row in enumerate(chat_rows):
            if not row["out"] or not row["text"]:
                continue

            prior = [item for item in chat_rows[max(0, index - 6) : index] if item["text"]]
            context = [
                {"role": "assistant" if item["out"] else "other", "text": item["text"]}
                for item in prior[-4:]
            ]
            if not context:
                continue

            reply_delay = None
            prev_other = next((item for item in reversed(prior) if not item["out"]), None)
            if prev_other:
                prev_dt = datetime.fromisoformat(prev_other["date"])
                cur_dt = datetime.fromisoformat(row["date"])
                reply_delay = round((cur_dt - prev_dt).total_seconds() / 60, 2)
                if reply_delay >= 0:
                    response_minutes.append(reply_delay)

            labels = []
            blob = " ".join(item["text"] for item in prior[-2:] + [row]).lower()
            if any(
                word in blob
                for word in ["today", "tonight", "tomorrow", "deadline", "asap"]
            ):
                labels.append("timing")
            if "?" in blob:
                labels.append("question")
            if any(
                word in blob for word in ["send", "share", "file", "contract", "invoice"]
            ):
                labels.append("delivery")

            pairs.append(
                {
                    "chat_title": row["chat_title"],
                    "reply_message_id": row["message_id"],
                    "scope": row["scope"],
                    "context": context,
                    "assistant_reply": row["text"],
                    "reply_delay_minutes": reply_delay,
                    "labels": labels,
                }
            )

    stats = {
        "reply_pair_count": len(pairs),
        "median_reply_delay_minutes": median(response_minutes)
        if response_minutes
        else None,
    }
    return pairs, stats


def summarize(
    dialogs,
    messages,
    pairs,
    stats,
    since_dt,
    scopes,
    keywords,
    redaction_enabled,
    profile,
):
    per_chat = Counter(row["chat_title"] for row in messages)
    scope_counts = Counter(row["scope"] for row in messages)
    outbound = sum(1 for row in messages if row["out"])
    inbound = len(messages) - outbound
    top_chats = per_chat.most_common(10)

    lines = [
        "# Telegram Work Summary",
        "",
        f"- Profile: {profile}",
        f"- Time window start: {since_dt.isoformat()}",
        f"- Scopes: {', '.join(sorted(scopes))}",
        f"- Dialogs scanned: {len(dialogs)}",
        f"- Messages exported: {len(messages)}",
        f"- Outbound messages: {outbound}",
        f"- Inbound messages: {inbound}",
        f"- Reply pairs derived: {stats['reply_pair_count']}",
        f"- Redaction enabled: {'yes' if redaction_enabled else 'no'}",
    ]
    if keywords:
        lines.append(f"- Work keywords: {', '.join(keywords)}")
    if stats["median_reply_delay_minutes"] is not None:
        lines.append(
            f"- Median reply delay: {stats['median_reply_delay_minutes']} minutes"
        )

    lines.extend(["", "## Scope Breakdown", ""])
    for scope, count in sorted(scope_counts.items()):
        lines.append(f"- {scope}: {count} messages")

    lines.extend(["", "## Top Chats", ""])
    for name, count in top_chats:
        lines.append(f"- {name}: {count} messages")

    lines.extend(["", "## Notes", ""])
    lines.append("- Review the raw export for privacy before downstream use.")
    if not keywords:
        lines.append("- No keyword filter was used; review chat relevance before training.")
    if not pairs:
        lines.append(
            "- No reply pairs were derived; widen the time range or include more work dialogs."
        )
    return "\n".join(lines) + "\n"


def resolve_phone(args):
    if args.phone:
        return args.phone
    if os.isatty(0):
        phone = input("Telegram phone number: ").strip()
        if phone:
            return phone
    raise SystemExit(
        "Missing Telegram phone number. Set TG_PHONE, pass --phone, or run in a TTY to enter it interactively."
    )


async def main():
    args = parse_args()
    profile = resolve_profile(args.profile)
    api_id = int(env_required("TG_API_ID"))
    api_hash = env_required("TG_API_HASH")
    phone = resolve_phone(args)
    scopes = parse_scope(args.scope)
    redaction_enabled = not args.no_redact

    out_root = Path(args.output or os.getenv("TG_OUTPUT_DIR") or default_output_dir(profile))
    session_path = Path(args.session or os.getenv("TG_SESSION_PATH") or default_session_path(profile))
    raw_dir = out_root / "raw"
    derived_dir = out_root / "derived"
    raw_dir.mkdir(parents=True, exist_ok=True)
    derived_dir.mkdir(parents=True, exist_ok=True)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    since_dt = datetime.now(timezone.utc) - timedelta(days=args.days)

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.start(phone=phone)

    dialogs, messages, per_chat_outbound = await collect_messages(client, args, since_dt)
    if args.list_dialogs:
        await client.disconnect()
        print(json.dumps(dialogs, ensure_ascii=False, indent=2))
        return

    dialogs, messages, keywords = filter_messages(dialogs, messages, args)
    messages = [
        row for row in messages if per_chat_outbound[row["chat_id"]] >= args.min_outbound
    ]
    messages = apply_redaction(messages, redaction_enabled)
    pairs, stats = derive_reply_pairs(messages, args.min_outbound)
    summary = summarize(
        dialogs,
        messages,
        pairs,
        stats,
        since_dt,
        scopes,
        keywords,
        redaction_enabled,
        profile,
    )

    (raw_dir / "dialogs.json").write_text(
        json.dumps(dialogs, ensure_ascii=False, indent=2) + "\n"
    )
    with (raw_dir / "messages.jsonl").open("w", encoding="utf-8") as fh:
        for row in messages:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (derived_dir / "reply_pairs.jsonl").open("w", encoding="utf-8") as fh:
        for row in pairs:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (derived_dir / "work_summary.md").write_text(summary, encoding="utf-8")

    await client.disconnect()
    print(
        f"Exported {len(messages)} messages and {len(pairs)} reply pairs to {out_root} (profile={profile})"
    )


if __name__ == "__main__":
    asyncio.run(main())
