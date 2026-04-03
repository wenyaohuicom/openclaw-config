# Phase 7 Auto-Send Whitelist

This phase is the first real step from shadow mode toward replacing the human in production.

## Important Principle

Do not turn on broad auto-send. Start with a whitelist of:

- specific chats
- specific categories
- short, human-native replies only

## Recommended First Whitelist

Start with:

- `acknowledge`
- `dispatch-escalate`
- `follow-up`
- `request-info`

Keep these in shadow longer:

- `issue-report`
- anything involving billing, price, USDT,主体, or ambiguous negotiation

## Launch Pattern

Shadow mode first:

```sh
scripts/run_telegram_dispatch_runner.sh --profile test --chat '118 ip' --watch
```

Whitelist mode after review:

```sh
scripts/run_telegram_dispatch_runner.sh \
  --profile test \
  --chat '118 ip' \
  --watch \
  --send-mode whitelist \
  --allow-category acknowledge \
  --allow-category dispatch-escalate \
  --allow-category follow-up
```

## Why This Can Pass As Human

The runner now prefers per-chat replies from `human_playbook.json` when they are short and safe.
That means it will prefer local phrases like:

- `1`
- `好的`
- `稍等`
- `正在处理`
- `发一下资料哥`

instead of generic assistant text.

## Guardrails

- Keep a cooldown between auto-sends in the same chat.
- Skip messages containing price, billing, USDT,主体, or other high-risk terms.
- Keep a send log so every outbound line is auditable.
- Use small chat allowlists while tuning.
