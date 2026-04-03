# Phase 8 Chat Role And Correlation Requirements

Use this as the product requirement layer for replacing the owner's Telegram work. This phase exists because the current evidence shows that not every chat does the same job, and a single global bot policy will fail.

## Core Requirement

Model Telegram as a workflow graph, not a flat inbox.

The bot must understand:

- which chat is a control room
- which chat is an execution queue
- which chat is an exception queue
- which private chat is a side-channel for补资料/补协调
- when a message should cause no reply at all

## Evidence Already Seen

Based on current exports and derived artifacts:

- `skills/telegram-ai-employee/output/test-cross/derived/work_summary.md`
- `skills/telegram-ai-employee/output/test-users/derived/work_summary.md`
- `skills/telegram-ai-employee/output/test/derived/human_playbook.md`
- `skills/telegram-ai-employee/output/test/derived/task_queue_summary.md`

Current high-confidence role hypotheses:

- `118公司总群` -> total control / global dispatch / resource coordination
- `118二梯队上号群` -> execution / onboarding / runbook handoff
- `鸿运,企业微信(二梯队)` -> dispatch /催办 /补资料 / short confirmations
- `118 ip` -> exception intake / IP failure handling / downstream worker escalation
- `风油精,企业微信【87】` -> mixed operations + billing/price/body topics; higher risk
- `118 Monica` (private) -> side-channel for sending structured execution data and follow-up coordination

## Requirement 1: Every Chat Needs A Role

Do not treat chats as one pool. For each chat, assign at least:

- `role`: control | dispatch | execution | exception | mixed-risk | side-channel | unknown
- `automationLevel`: deny | suggest-only | whitelist-send | full-playbook
- `replyStyle`: terse-dispatch | terse-ack | issue-routing | mixed-review
- `riskFlags`: pricing | billing | usdt | subject-change | credential-flow | none

## Requirement 2: Private Chats Need Correlation, Not Just Export

Private chats must be checked against nearby group activity.

For each private message, the system should ask:

- did a group task appear within +/- 30 minutes?
- does the same cloud machine / port / region / subject / worker appear?
- is this a补资料 event, a催办 side-channel, or unrelated noise?

The output should not be a generic "private chat summary". It should be a correlation record.

## Requirement 3: Build A Workflow Graph

The bot should model likely edges such as:

- control chat -> dispatch chat
- dispatch chat -> exception chat
- private side-channel -> dispatch chat
- private side-channel -> control chat

This matters more than raw message classification, because the owner's work is cross-chat coordination.

## Requirement 4: Decide Silence Explicitly

The current system still over-focuses on reply generation. That is insufficient.

For each chat role, define:

- what kinds of messages require a reply
- what kinds only update task state
- what kinds are human-only
- what kinds should be ignored entirely

A correct `no reply` decision is often more valuable than a fluent reply.

## Requirement 5: Separate Safe Automation From True Takeover

Near-term safe automation:

- short acknowledgements in stable dispatch chats
-资料 collection prompts in stable dispatch chats
- follow-up nudges on known active tasks

Not yet safe for full takeover:

- billing, pricing, USDT,主体 topics
- ambiguous blame/negotiation threads
- mixed-risk chats without per-chat playbooks
- issue threads where no downstream execution hook exists

## Requirement 6: Replace Work, Not Just Language

The bot must not stop at reply text. It must also know how to:

- create the task
- attach the chat evidence
- route to the right downstream worker
- wait
- re-check
-催办
- mark done / cancelled

If a message only changes queue state, the system should be allowed to do that without replying.

## Immediate Development Implications

1. Add a machine-readable chat role map.
2. Add cross-chat correlation outputs for private + group timing windows.
3. Add per-role silence rules.
4. Add per-role automation policy.
5. Only then widen auto-send.
