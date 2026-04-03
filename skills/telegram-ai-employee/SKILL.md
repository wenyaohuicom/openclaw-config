---
name: telegram-ai-employee
description: Build and operate a Telegram AI employee workflow. Use when Codex needs to connect a personal Telegram account, inspect how a human handles day-to-day work in Telegram, export work-related chats, derive reusable work patterns, and prepare datasets or prompts for automation, imitation, or later model training.
---

# Telegram AI Employee

## First Feature: Observe Human Telegram Work

- Use this feature to learn how the owner works inside Telegram before automating replies.
- Connect through the owner's Telegram user account API session, not through a bot token.
- Current priority: private chats and group chats first; channels stay optional.
- Prefer exporting only work-related chats. Do not blindly ingest every private conversation when a narrower scope is possible.
- Use `--keyword`, `--dialog`, and `--exclude-dialog` to narrow the export before training.
- Keep credentials and session files out of git.
- Default session files live under `skills/telegram-ai-employee/secrets/` so they stay scoped and ignored.
- Use `--profile <name>` to keep multiple Telegram accounts isolated from each other.

## Workflow

1. Create a local Telegram user session with `scripts/collect_telegram_work.py`.
2. Export recent dialogs and messages into a raw dataset.
3. Derive reply pairs, timing patterns, recurring tasks, and high-signal examples from the raw export.
4. Review the derived dataset for privacy and relevance before using it for prompts, retrieval, or training.

## Required Inputs

- `TG_API_ID`
- `TG_API_HASH`
- Optional: `TG_PHONE`
- Optional: `TG_SESSION_PATH`
- Optional launcher env file: `skills/telegram-ai-employee/secrets/telegram.env`
- Optional per-profile env file: `skills/telegram-ai-employee/secrets/telegram.<profile>.env`
- Optional runtime flags: `--phone`, `--profile`

## Output Layout

- Default profile: `skills/telegram-ai-employee/output/raw/dialogs.json`
- Default profile: `skills/telegram-ai-employee/output/raw/messages.jsonl`
- Named profile: `skills/telegram-ai-employee/output/<profile>/raw/dialogs.json`
- Named profile: `skills/telegram-ai-employee/output/<profile>/derived/reply_pairs.jsonl`
- Named profile: `skills/telegram-ai-employee/output/<profile>/derived/work_summary.md`

## Safety Rules

- Exclude clearly personal, family, financial, or unrelated chats unless the owner explicitly wants them included.
- Prefer allowlisting work dialogs by title or username instead of scraping everything.
- Treat the exported data as sensitive local training material.
- Redact secrets, OTPs, access tokens, and bank or ID data before downstream use.

## Using The Script

- Read `references/feature-1-data-pipeline.md` before first use.
- Run `scripts/collect_telegram_work.py` with a time window, `--scope users,groups`, and optional dialog or keyword filters.
- Or use `scripts/run_collect_telegram_work.sh` after filling `secrets/telegram.env`.
- For multiple accounts, keep shared API creds in `secrets/telegram.env` and per-account phone overrides in `secrets/telegram.<profile>.env`, then run with `--profile <name>`.
- Use `--list-dialogs` first when you want to inspect candidate chats before exporting messages.
- Leave redaction on unless there is a strong reason to keep raw secrets in the dataset.
- If the goal is later training, use the derived reply pairs as the first dataset, not the full raw dump.

## Notes For Future Features

- Add contact and chat classification before auto-reply features.
- Add approval gates before any outbound automation.
- Keep observation and learning separate from acting on behalf of the owner.
