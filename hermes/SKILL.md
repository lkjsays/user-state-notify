---
name: location-reminders
description: "Register location/device-context reminders that fire when the user next activates a Mac (login/wake/unlock) at a place or on a device — deferred, not immediate, notifications. Use whenever the user ties a task, notification, or 'let me know' to a place or a specific machine, even phrased casually or as a question: '회사맥 알림 줄 수 있니?', '회사맥에 알림 걸어줘', '집맥 켜면 ~', '회사 가면 ~ 알려줘', '@회사맥 ~ 기억해', 'remind me on my work Mac'. Any mention of a device/place alias (회사맥, 집맥, 회사맥북, 회사, 집) combined with remind/notify intent should trigger this skill. If unsure whether the user wants an immediate message or a context-triggered reminder, still consult this skill and offer it as an option. Time/date reminders ('3시에', 'tomorrow') belong to apple-reminders instead."
version: 1.1.0
author: kijeong.lee
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [reminder, reminders, location, context, todo, tasks, notify, 리마인더, 알림, 알려줘, 회사맥, 집맥, user-state-notify]
prerequisites:
  commands: [curl]
---

# Location / Context Reminders

Register reminders bound to a **place** and/or **device** through the
`user-state-notify` proxy. When the user later activates the matching Mac
(login / wake / unlock) at that place, the reminder is pushed back to them
over the normal notification channel — once per session, repeating until
marked done.

This is for **context-triggered** reminders ("remind me when I'm at X"), not
time-based ones. For time/date reminders that sync to iPhone, use the
`apple-reminders` skill instead.

## Endpoint

Resolve the base URL from the environment, falling back to loopback:

```bash
BASE="${USER_STATE_SERVER_URL:-http://127.0.0.1:8645}"
SECRET="${USER_STATE_SECRET:-hermes-claude-hook}"
```

- If Hermes runs on the **same** Mac as the proxy, the `127.0.0.1:8645`
  default works — leave `USER_STATE_SERVER_URL` unset.
- If Hermes runs on a **different** Mac, set `USER_STATE_SERVER_URL` to the
  server's reachable address in Hermes's environment.
- Write requests (`/remind`, `/reminders/{id}/done`) **require** the header
  `X-Webhook-Secret: $SECRET`.

## When to Use

Trigger this skill when the user wants to be reminded to do something tied to
a location or a specific computer, e.g.:

- "회사 가면 보고서 쓰라고 알려줘" → place = office
- "집 컴퓨터 켜면 ~ 하라고 알려줘" → device = mac-mini-home
- "회사 맥에서 ~ / @회사맥 ~" → device = mac-studio-office
- "회사맥 알림 줄 수 있니?" → device = mac-studio-office (질문형이어도 등록 의도)
- "집맥 켜면 그거 보여줘" → device = mac-mini-home
- "remind me to review the PR when I'm on my work Mac"

Requests may be phrased as questions ("~줄 수 있니?") or casual statements,
not just imperatives. A device/place alias appearing anywhere in the message
is a strong signal, with or without the `@` prefix.

Do **not** use this for time-based reminders ("at 3pm", "tomorrow") — that is
`apple-reminders`.

### When the intent is ambiguous

If you cannot tell whether the user wants an **immediate** notification or a
**context** reminder ("next time that Mac is active"), do NOT guess and do
NOT omit this skill from your clarifying options. Always include
"register it as a reminder that fires when that Mac is activated
(login/wake/unlock)" as one of the choices you offer.

## How To Register

Translate the user's phrasing into a `place` and/or `device`, then POST:

```bash
curl -fsS -X POST http://127.0.0.1:8645/remind \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: hermes-claude-hook' \
  -d '{"text":"보고서 작성","device":"mac-studio-office"}'
```

Fields (at least one of `place`/`device` is required, else the server returns 400):

- `text` — the task text (required, non-empty after token stripping).
- `place` — one of `office`, `home`, `mobile`.
- `device` — a canonical device name, e.g. `mac-studio-office`, `macbook`,
  `mac-mini-home`.

You may instead pass an `@token` inside `text` (e.g. `"보고서 작성@회사맥"`) and
let the server resolve it. The token map lives in
`~/.hermes/state/reminder_aliases.json` — **read that file** to learn the
user's current aliases before mapping, since they can customize it. Default
aliases:

| token | resolves to |
|-------|-------------|
| `회사맥`   | device `mac-studio-office` |
| `회사맥북` | device `macbook`, place `office` |
| `집맥`     | device `mac-mini-home` |
| `회사`     | place `office` |
| `집`       | place `home` |

Prefer sending structured `place`/`device` fields (resolve the token yourself
from the alias file) so the behavior is explicit.

On success the response is `{"ok":true,"id":"r_...","reminder":{...}}`.
**Echo the `id` back to the user** so they can complete it later.

## List Pending

```bash
curl -fsS "http://127.0.0.1:8645/reminders?status=pending"
```

## Mark Done

```bash
curl -fsS -X POST http://127.0.0.1:8645/reminders/<ID>/done \
  -H 'X-Webhook-Secret: hermes-claude-hook'
```

When the user says "끝냈어", "그거 완료", "done with the report", find the
matching reminder via the list endpoint and POST its id to `/done`.

## Behavior The User Should Understand

- Fires on `device.login` / `device.wake` / `device.unlock`.
- **Once per session** — `login` always starts a new session; `wake`/`unlock`
  start one only if more than ~60 minutes (`USER_STATE_SESSION_GAP_MIN`)
  passed since last activity. So a quick screen unlock won't re-spam.
- Matching is **AND**: every condition set on the reminder must match the
  event. A `place`-qualified reminder only fires when the activating device
  reports that place.
- Repeats every new session **until marked done**.

## Caveats

- A `place: office` reminder won't fire on a MacBook unless that MacBook's
  client reports `place=office` (the default MacBook mapping is `mobile`).
  When in doubt, target a specific `device` instead of `place`.
- If a write returns 401, the secret is wrong; if 400, no valid place/device
  was supplied or the text was empty.
