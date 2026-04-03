# Phase 5 Live Runner

Use this after the queue and suggestion layers exist. The purpose is to validate the bot against real incoming Telegram traffic without giving it outbound autonomy yet.

## What It Does

The live runner:

- loads an already-authorized Telegram user session
- watches selected chats or scans recent inbound messages
- classifies each message
- writes `live_suggestions.jsonl`
- updates `live_task_queue.json`
- renders a small markdown summary for human review

## Recommended Launch Pattern

Start narrow. Do not watch every chat at once.

```sh
scripts/run_telegram_dispatch_runner.sh --profile test --chat '118 ip' --recent-per-chat 6
```

Then move to watch mode:

```sh
scripts/run_telegram_dispatch_runner.sh --profile test --chat '118 ip' --watch
```

## Review Loop

For each run, compare:

- incoming message
- category
- suggested action
- suggested reply
- resulting queue state

If the bot repeatedly classifies and suggests correctly, that category can move closer to auto-send.

## Safe Rollout Order

1. Observe only
2. Suggest only
3. Auto-send `acknowledge`
4. Auto-send narrow `dispatch-escalate` / `follow-up` / `request-info` playbooks
5. Keep issue reports and finance-related threads human-reviewed until queue quality is stable

## Runtime Artifacts

- `output/<profile>/runtime/live_suggestions.jsonl`
- `output/<profile>/runtime/live_task_queue.json`
- `output/<profile>/runtime/live_task_queue_summary.md`

## Guardrails

- Do not enable broad auto-send from this phase alone.
- Keep queue evidence intact so humans can audit bad classifications.
- Use small chat allowlists while tuning the runner.
