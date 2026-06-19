---
name: location-reminders
description: "Register location/device-context reminders that fire when the user activates a Mac at a place. Use when the user asks to be reminded to do something 'when I get to the office', 'on my work Mac', '@회사맥', etc."
version: 1.0.0
author: kijeong.lee
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [reminder, reminders, location, context, todo, tasks, 리마인더, 알림, user-state-notify]
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
- "remind me to review the PR when I'm on my work Mac"

Do **not** use this for time-based reminders ("at 3pm", "tomorrow") — that is
`apple-reminders`.

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
