# Phase 6 Human Mimic Mode

The owner's stated goal is not a dashboard that tells a human what to do. The goal is for the bot to replace the human in Telegram operations without sounding obviously robotic.

## Core Rule

Do not optimize for generic helpfulness. Optimize for human operational mimicry.

That means:

- use short group-native replies
- preserve the operator's terse style
- reuse local phrasing like `1`, `好的`, `稍等`, `正在安排`, `发一下资料哥`
- separate groups by work function instead of using one global tone

## Current Group Roles Seen In Data

- `118 ip`: issue intake, downstream mentions, repair follow-up, region/IP anomaly handling
- `鸿运,企业微信(二梯队)`: dispatch,催办,认证推进,资料收集
- `风油精,企业微信【87】`: mixed operational + financial / billing /主体 topics; keep more human review here

## Replacement Path

1. Shadow mode: generate the exact reply the bot would have sent.
2. Compare against historical human replies and current operator judgment.
3. Auto-send only for the safest group/category combinations.
4. Keep finance, pricing, and ambiguous negotiation in human-review mode.

## Wrong Direction To Avoid

- Long assistant-style explanations
- Polite customer-service paragraphs
- Generic “I understand” phrasing
- Replying when the human would normally only send `1`, `好的`, or `@worker`

## Immediate Goal

For each watched chat, learn:

- what triggers a reply
- whether the reply is acknowledgement, escalation,催办, or资料索取
- the exact short sentence shape the human tends to use
- when the human does **not** reply at all
