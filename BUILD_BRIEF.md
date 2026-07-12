# BUILD BRIEF — The Second Brain (instatank42 memory banks)

*Pre-filled by the 2026-07-12 strategy session from the founder's answers and
the playbook template (`time-tracker/playbook/templates/BUILD_BRIEF.md`).
Founder: edit anything that reads wrong — especially §4 and §6, which are
promises only you can make.*

**Date:** 2026-07-12
**Tier it enters:** 1 — flagship, **as a stop-gap** (founder's words): active
flagship while second-brain work is the focus, worked in bursts between
maturing the feeder products (Cadence, Meal-Planner, TradeGenie). PartySpark
drops to Tier 2 for the duration (max-2-flagships rule stands). Revisit at
the first monthly review.

## 1. User & pain — one sentence each
- **Who is this for?** Me, and honestly so — single-user by design (the bot is
  allowlisted to one Telegram ID).
- **What specific moment of pain does it remove?** Everything I log — journals,
  time blocks, project sessions, learnings — is write-only today; I record
  faithfully but can't *ask my own life questions*. The brain makes my data
  answerable from my phone.

## 2. Why this, why now — the training answer
- **Which tracks does this stretch?** S — my first real two-system pipeline
  (producer contract in DayOS → sync → consumer), the kind of system I should
  be able to whiteboard (CURRICULUM item 12). O — my first VPS: systemd,
  timers, logs, no Vercel guardrails. D — context engineering: deciding what
  memory enters the model, when, at what cost.
- **What will building it teach that the last build didn't?** Running a system
  whose failure mode is *silence* (a stale mirror answering confidently from
  old data) rather than a visibly broken page — and designing the loud-failure
  defenses for that.

## 3. Smallest shippable slice
- **Already shipped:** the talking bot + the DayOS memory bank (deployed,
  in daily use as of 2026-07-12).
- **The next one-session slice:** the principles layer — mirror the playbook +
  LEARNINGS into the brain so the bot can quote my own rules (ROADMAP Phase 2).
- **Explicitly NOT in v1:** embeddings / vector DB; WhatsApp, trading-journal,
  and Drive banks (backlogged, gated); proactive messages beyond the Friday
  synthesis; any dashboard; write access to anything.

## 4. Done means — acceptance criteria (testable, mine)
1. I ask "what did I do yesterday?" and the answer matches DayOS's Today view.
   *(✅ verified in daily use, 2026-07-12)*
2. I ask "what's my rule about ___?" and the bot quotes the actual playbook
   entry. *(Phase 2)*
3. When sync breaks, the bot itself tells me its data is stale — I never find
   out from a wrong answer. *(staleness drill — checklist item 5, run once)*
4. The Friday synthesis arrives unprompted on Telegram and is worth reading.
   *(Phase 4)*

## 5. The silent-failure question (PLAYBOOK Rule 4)
- **Worst quiet failure:** the sync dies, the mirror goes stale, and the bot
  keeps answering confidently from old data — wrong answers that look right.
- **How I find out:** `sync_status.json` heartbeat → loud staleness warnings
  injected into every DayOS tool result and the daily snapshot, plus `/sync`
  to force a refresh. The staleness drill proves the alarm actually fires.

## 6. Kill / park criteria
- If by ~6 weeks I'm not actually consulting the bot a few times a week
  (visible in `memory/usage/`), Phase 4 (proactive) does NOT ship, the project
  drops back to Tier 2 maintenance, and PartySpark returns to flagship.
  Existing banks keep syncing either way — they're free.
