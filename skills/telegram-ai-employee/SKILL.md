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

## Phase 2: Replace Manual Operations

- Read `references/phase-2-operations-model.md` after the first export exists.
- Run `scripts/analyze_telegram_operations.py --profile <name>` to turn reply pairs into operation categories.
- Treat the operator role as dispatch-heavy work coordination, not generic conversation.
- Start with message classification, task extraction, and suggested replies before enabling auto-send.

## Phase 3: Suggest Actions And Replies

- Read `references/phase-3-action-playbook.md` after `operation_labels.jsonl` exists.
- Run `scripts/suggest_telegram_actions.py --profile <name>` to generate action suggestions for recent inbound messages.
- Review `output/<profile>/derived/action_suggestions.md` to compare suggested replies with historical human replies.
- Compare `suggested_reply` against `historical_reply` before enabling any auto-send path.
- Treat `acknowledge` as the safest first auto-send category; keep issue reports human-approved longer.

## Phase 4: Build A Task Queue

- Read `references/phase-4-task-queue.md` after action suggestions exist.
- Run `scripts/build_telegram_task_queue.py --profile <name>` to convert grouped operational messages into queue items.
- Treat queue state as the source of truth before any follow-up or催办 auto-send.
- Keep evidence snippets on each task so a human can audit why the bot thinks something is `new`, `processing`, or `done`.

## Phase 5: Live Dispatch Runner

- Read `references/phase-5-live-runner.md` before using the live runner on real chats.
- Run `scripts/run_telegram_dispatch_runner.sh --profile <name> --chat '<group name>'` to process recent inbound messages into a live queue.
- Add `--watch` to keep listening for new messages, but keep it suggestion-only until the owner explicitly approves auto-send.
- Read from `output/<profile>/runtime/live_suggestions.jsonl` and `output/<profile>/runtime/live_task_queue.json`.
- Use this phase to validate that the bot can keep up with real work before it sends anything.

## Phase 6: Human Mimic Mode

- Read `references/phase-6-human-mimic-mode.md` before enabling any outbound behavior.
- Run `scripts/derive_human_playbook.py --profile <name>` to summarize how the human actually works in each group.
- Optimize for role mimicry, not generic assistant helpfulness.
- Keep finance, pricing, and ambiguous negotiation topics in human-review mode longer than pure dispatch flows.

## Phase 7: Auto-Send Whitelist

- Read `references/phase-7-autosend-whitelist.md` before enabling any real outbound sends.
- Use `--send-mode shadow` by default; switch to `--send-mode whitelist` only on narrow chat/category allowlists.
- Prefer mimic mode so replies come from the per-chat human playbook rather than generic assistant phrasing.
- Keep `issue-report` and finance-related topics in human-review mode longer.

## Notes For Future Features

- Add contact and chat classification before broad auto-reply features.
- Add approval gates before any outbound automation.
- Keep observation and learning separate from acting on behalf of the owner.
