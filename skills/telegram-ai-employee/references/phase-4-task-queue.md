# Phase 4 Task Queue

Use this after action suggestions exist. The goal is to stop thinking in single replies and start thinking in persistent operational tasks.

## Why A Queue Matters

The human is not only replying. They are tracking work across multiple group messages:

- issue appears
- worker gets mentioned
- operator says `稍等` or `正在安排`
- someone asks again `好了没有`
- final resolution or cancellation arrives

A bot cannot replace this job without a queue.

## Minimum Queue Fields

Each task should carry at least:

- `task_id`
- `chat_title`
- `subject_key`
- `primary_category`
- `state`
- `priority`
- `assigned_workers`
- `regions`
- `ports`
- `latest_message_date`
- `suggested_action`
- `suggested_reply`

## Recommended States

- `new` - fresh issue report
- `processing` - someone is handling it
- `waiting` - follow-up needed
- `waiting-info` - blocked on missing资料
- `done` - fixed or confirmed complete
- `cancelled` - user canceled or said not needed
- `watch` - low-confidence item worth monitoring

## Initial Automation Path

1. Build queue entries from issue, follow-up, dispatch, and request-info messages.
2. Auto-send only `acknowledge` first.
3. For `new` and `processing`, generate short suggested replies and route suggestions.
4. For `waiting`, auto-remind only when the queue has an assigned worker and a timeout rule.
5. For `done` and `cancelled`, close the task and suppress extra replies.

## Guardrails

- Never infer `done` without strong completion language or downstream confirmation.
- Never collapse unrelated issues in the same group unless they share a clear subject key such as port, worker, or region.
- Keep the queue inspectable; every task should retain recent evidence messages.
