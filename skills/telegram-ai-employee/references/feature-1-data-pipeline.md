# Feature 1 Data Pipeline

## Goal

Capture how the owner actually works in Telegram, then turn that activity into structured material that can guide an AI employee.

## Recommended Process

1. Put API credentials in `secrets/telegram.env` or environment variables.
2. Authenticate the owner's Telegram user account locally.
3. Pull recent dialogs and let the owner narrow the scope to work-related chats when possible.
4. Default to private chats plus group chats when the owner wants to learn both direct handling and group-work patterns.
5. Leave channels optional unless the owner explicitly wants feed-style sources included.
6. Export raw messages with sender, timestamp, chat metadata, and reply links.
7. Build derived examples from outbound human replies.
8. Review and redact before using the material for prompting or training.

## Raw Export

The raw export keeps enough context for later analysis:

```json
{
  "chat_id": 123,
  "chat_title": "Client A",
  "message_id": 456,
  "date": "2026-04-02T23:00:00+00:00",
  "sender_id": 789,
  "sender_name": "Owner",
  "out": true,
  "reply_to_msg_id": 455,
  "text": "I'll send the contract tonight.",
  "media": false
}
```

## Derived Training Pairs

A useful first training shape is one human-written reply plus a compact context window:

```json
{
  "chat_title": "Client A",
  "reply_message_id": 456,
  "context": [
    {"role": "other", "text": "Can you send the contract today?"},
    {"role": "other", "text": "Need it before 8pm."}
  ],
  "assistant_reply": "I'll send the contract tonight.",
  "labels": ["deadline", "client-followup"]
}
```

## What To Learn From The Data

- Working hours and response windows
- Common request types
- Message length and tone
- Follow-up habits
- Recurring operational tasks
- Contacts or groups that require special handling

## Filtering Guidance

Prefer one or more of these filters:

- Scope selection: `users,groups` by default; optionally include `channels` or use `all`
- Explicit dialog allowlist with `--dialog`
- Dialog exclusion list with `--exclude-dialog`
- Recent days window
- Minimum outbound message count
- Keyword-based work classification with `--keyword`
- `--list-dialogs` before export when scope is still broad
- Excluding archived or muted personal chats

## Privacy Review

Before training or prompt-ingesting the data:

- Remove passwords, OTPs, tokens, bank details, IDs, and home addresses.
- Remove chats unrelated to work.
- Consider replacing personal names with stable labels when identity is not needed.
- Store raw exports locally; use derived datasets for most downstream work.
- Keep the default session file under `skills/telegram-ai-employee/secrets/` and the export under `skills/telegram-ai-employee/output/` unless you have a better local layout.
- Keep redaction enabled for phones, OTPs, obvious tokens, and secret-looking query params unless a controlled review requires raw text.
