# Phase 3 Action Playbook

Use this after `operation_labels.jsonl` exists. The goal is to move from passive analysis into actionable bot behavior.

## What The Bot Should Output First

Do not auto-send everything. First produce a structured suggestion object with:

- `operation_category`
- `confidence`
- `suggested_action`
- `suggested_reply`
- `historical_reply` when a human actually replied later

This lets you compare the bot's recommendation with real human behavior before turning on automation.

## Initial Automation Ladder

1. `acknowledge` - safest to auto-send when confidence is high.
2. `follow-up` - semi-auto; safe if a task id or assigned worker already exists.
3. `request-info` - semi-auto; ask only for clearly missing fields.
4. `dispatch-escalate` - suggest first, then auto-send after playbooks stabilize.
5. `issue-report` - classify and route automatically, but keep outbound reply human-approved until confidence is high.

## Suggested Bot Behaviors By Category

### issue-report

- Extract region, port, worker mention, and symptom.
- Create or update a task.
- Suggest a short escalation reply.
- Example action: `创建异常工单并转给下游处理 (region=河南, port=38020)`

### dispatch-escalate

- Mark the task as processing.
- Notify the assigned downstream worker if present.
- Keep replies short: `正在安排`, `稍等`, `我去看一下`.

### follow-up

- Check whether the task already exists and when it was last updated.
- If stale, auto-mention the worker or output a催办 suggestion.

### request-info

- Identify the missing field: account, cloud machine number, region, port, password, or profile data.
- Ask only for the missing field.

### acknowledge

- Use compact confirmations only.
- Avoid long natural-language replies.

## Guardrails

- Never send passwords or secrets back into the group.
- Never mark tasks done without evidence from the downstream side.
- Prefer short operational replies over verbose assistant language.
- Log confidence and compare against historical replies before enabling full auto-send.
