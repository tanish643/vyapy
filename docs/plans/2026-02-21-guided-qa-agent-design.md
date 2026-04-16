# Vyapy Guided QA Agent — Design Doc
**Date:** 2026-02-21
**Status:** Approved
**Scope:** Phase 1 (single-user) + Phase 2 (multi-user), consumer app only

---

## Problem

The current `preorder_bot.py` is brittle — hardcoded content-descs, fixed flow, breaks on any UI change. It covers one scenario. There are 26 test categories and 100+ individual test goals across two apps (Vyapy consumer + Vyapy Ara business). Manual testing is slow and inconsistent.

---

## Solution: Guided Exploration Agent

A goal-driven QA bot where:
- **You define what to test** (goal list)
- **Gemini Flash decides how** (reads XML, picks next action)
- **Bot executes + reports** (ADB taps, logs bugs, continues)

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              GOAL RUNNER                    │
│  Reads goals.json → executes one at a time  │
└──────────────┬──────────────────────────────┘
               │
       ┌───────▼────────┐
       │   AI AGENT     │  ← Gemini Flash (free tier)
       │  (ReAct loop)  │  XML → next action JSON
       └───────┬────────┘
               │
       ┌───────▼────────┐
       │  ADB EXECUTOR  │  tap / scroll / swipe / switch app
       └───────┬────────┘
               │
       ┌───────▼────────┐
       │  BUG REPORTER  │  screenshot + log → report.html
       └────────────────┘
```

---

## Components

### 1. Goal Registry (`goals.json`)

Each goal is a structured entry:

```json
{
  "id": "preorder_coupon_cycle",
  "category": "Preorder",
  "description": "Add coupon, remove it, add it again, verify total updates correctly each time",
  "app": "consumer",
  "accounts": ["host"],
  "phase": 1,
  "tags": ["coupon", "billing"]
}
```

Fields:
- `id` — unique snake_case identifier
- `category` — matches the 26 test categories
- `description` — plain English, what Gemini reads to understand goal
- `app` — `consumer` or `business`
- `accounts` — `["host"]` or `["host", "participant"]`
- `phase` — 1 (single-user) or 2 (multi-user)
- `tags` — for filtering runs (e.g. run only `payment` goals)

---

### 2. AI Agent Loop

**Per step:**
1. Dump UI via `adb shell uiautomator dump`
2. Strip XML to essentials: content-desc, text, clickable=true elements only (~500 tokens)
3. Send to Gemini Flash:
   - System prompt: "You are a mobile QA agent. Given the current screen elements and a goal, output the next action as JSON."
   - Context: goal description + last 5 actions taken
4. Parse Gemini response — one of:

```json
{"action": "tap",          "target": "applyCoupon"}
{"action": "tap_text",     "target": "Apply"}
{"action": "scroll_down"}
{"action": "scroll_up"}
{"action": "type",         "target": "inputField", "text": "Hello"}
{"action": "switch_account","to": "participant"}
{"action": "goal_complete","notes": "Coupon applied and total updated correctly"}
{"action": "bug_found",    "description": "Total did not change after removing coupon", "severity": "high"}
```

5. Execute action via ADB
6. Loop (max 40 steps per goal — safety limit)

**Token optimization:** XML is filtered before sending. Only send: `content-desc`, `text`, `clickable`, `bounds` for clickable elements. Removes ~80% of XML noise.

---

### 3. Account Manager

Stores credentials for 2 consumer accounts:

```python
ACCOUNTS = {
    "host":        {"phone": "...", "password": "..."},
    "participant": {"phone": "...", "password": "..."}
}
```

**Switch flow:**
1. Tap profile/menu → logout
2. Wait for login screen
3. Type credentials for target account
4. Wait for home screen
5. Continue goal

Account switches only happen when `accounts` field in goal requires it.

---

### 4. Bug Reporter

On every `bug_found` action:
- Save screenshot as `bug_<timestamp>.png`
- Append to `report.html`:
  - Goal ID + category
  - Bug description + severity
  - Screenshot embed
  - Timestamp
  - Last 5 actions taken (breadcrumb)

Bot **never stops** on a bug — logs and moves to next goal.

Final summary printed to terminal:
```
══════════════════════════════
QA Run Complete — 2026-02-21
Goals attempted:  47
Goals passed:     39
Bugs found:       8
Report: C:\Users\gullu\Downloads\VYAPY\report.html
══════════════════════════════
```

---

## Phase Plan

### Phase 1 — Single User (Consumer App)
Goals where `accounts: ["host"]` only. Bot uses Account 1 throughout.

Categories covered:
- Preorder (single user flows)
- Payments C-App (host pays for all)
- Subscriptions & Ratings
- Blocked Users
- Filters (C-App)
- Reviews (host only)
- Status Verification (single user)

### Phase 2 — Multi User (Consumer App)
Goals where `accounts: ["host", "participant"]`. Bot switches accounts mid-test.

Categories covered:
- Event Booking (with participants/guests)
- Ordering (split, assign items)
- Contacts & Wallet
- Preorder (host + invitee flows)
- Event Cancellations
- Payments (split, mixed methods)
- Create & Manage Events

### Phase 3 — Business App (Future)
Blocked on: obtaining Vyapy Ara login credentials.

---

## Tech Stack

| Component | Tool |
|---|---|
| Device control | ADB (existing) |
| UI parsing | uiautomator XML dump (existing) |
| AI reasoning | Gemini Flash API (free tier, 1500 req/day) |
| Report output | HTML file (no dependencies) |
| Language | Python 3.12 (existing) |
| Config | `goals.json` + `accounts.json` (gitignored) |

---

## Files to Create

```
C:\Users\gullu\Downloads\VYAPY\
├── qa_agent.py          # Main agent loop + goal runner
├── goals.json           # All test goals (Phase 1 + 2)
├── accounts.json        # Credentials (gitignored)
├── reporter.py          # Bug reporter → report.html
├── account_manager.py   # Login/logout/switch logic
└── docs/plans/
    └── 2026-02-21-guided-qa-agent-design.md
```

---

## Constraints & Limits

- Max 40 AI steps per goal (prevents infinite loops)
- Gemini Flash free tier: 1500 requests/day — enough for ~37 goals at 40 steps each
- Account switch adds ~30s per switch (logout + login)
- No business app until credentials obtained
- Some goals require physical payment (e-payment, food voucher) — bot marks these as `manual_required` and skips
