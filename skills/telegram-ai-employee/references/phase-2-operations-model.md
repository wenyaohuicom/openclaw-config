# Phase 2 Operations Model

Use this after raw Telegram samples exist. The goal is no longer just export; it is to model the human operator's real job so the bot can take over low-risk work first.

## Core Work Types

- `issue-report`: report a concrete failure or abnormal state, usually around IP, login, verification, region mismatch, or account setup.
- `dispatch-escalate`: assign, arrange, contact,催办, or push another worker to handle the task.
- `follow-up`: ask whether a task is fixed, done, logged in, or confirmed.
- `request-info`: ask for missing资料, account details, cloud machine number, or setup parameters.
- `acknowledge`: short acceptance or confirmation like `1`, `好的`, `收到`, `是的`.

## Replacement Strategy

Do not jump straight to full auto-reply. Replace the human in layers:

1. Classify incoming messages into the operation types above.
2. Extract structured fields: target account, IP/port, region, cloud machine, worker handle, symptom, urgency.
3. Build a task queue that tracks `new -> processing -> waiting -> done -> blocked`.
4. Let the bot auto-send only low-risk confirmations first.
5. For issue reports and dispatch tasks, generate short suggested replies and route to the right downstream contact.
6. After confidence is high, allow auto-send for narrow playbooks with clear rollback.

## Signals Seen In The Current Dataset

The sampled work is group-driven and dispatch-heavy:

- Repeated references to IP instability, verification failure, region mismatch, and login problems.
- Repeated short operational replies like `正在安排`, `稍等`, `好的`, `加急了`, `我去看一下`.
- The operator acts more like a coordinator than a long-form salesperson or support rep.

This means the first valuable bot is an operations coordinator bot, not a generic chat bot.

## Recommended Bot Pipeline

1. Read each group message.
2. Detect whether it creates work, updates work, asks for status, or only acknowledges.
3. Attach the message to an existing task when possible.
4. Generate one of:
   - no reply
   - short acknowledgment
   - short follow-up
   - escalation note
   - request for missing info
5. Log every action with chat, message id, task id, and confidence.

## Guardrails

- Never auto-send sensitive credentials.
- Never claim a task is completed unless the queue state or downstream confirmation supports it.
- Prefer `suggest + approve` for issue reports until enough examples prove the playbook is safe.
- Keep all exports and sessions local; use derived data for training.
