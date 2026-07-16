---
name: save-to-brain
description: Condense the current Claude Code session into a markdown digest and push it to the instatank/2ndbrain repo (the second brain's storehouse). Use when the user says /save-to-brain, "save this session to the brain", or wants the session's insights/decisions preserved before ending.
---

# Save this session to the second brain

*(Convenience mirror — the canonical copy lives in
`instatank/2ndbrain/.claude/skills/save-to-brain/SKILL.md`; edit there
first, then re-copy here.)*

You are writing the ONE artifact of this session that survives: a digest a
future reader (the founder, his Telegram agent, or a later Claude session)
can understand **without having seen the conversation**. The founder is
non-technical — write for him first.

## Step 1 — compose the digest

Distill the session. This is a synthesis, NOT a transcript and NOT a log of
tool calls. Include only sections that have real content:

```markdown
# <Short, specific title of what the session was about>

- Date: <YYYY-MM-DD, IST>
- Project/repo(s): <repo names, or "general">
- Where it ran: <local Mac / cloud (claude.ai/code) / unknown>

## What this session was about
2–5 sentences: the ask, and why it mattered.

## Decisions made
One bullet per decision, WITH the reasoning ("chose X over Y because …").
Decisions are the highest-value content here — never drop one.

## Insights & learnings
Things worth knowing next month: gotchas hit, facts derived, approaches
that failed and why. Skip generic knowledge — keep what was learned HERE.

## What shipped / state of the work
What was built or changed, whether it's tested/deployed/merged, branch or
commit pointers if relevant.

## Open items
What's unfinished, blocked, or explicitly deferred — and on whom/what.
```

Rules:
- Plain prose, complete sentences. No tool-call noise, no file dumps, no
  code blocks unless a short snippet IS the insight.
- Self-contained: expand shorthand and codenames on first use.
- **Never include secrets**: no tokens, API keys, passwords, `.env`
  contents, or private URLs with credentials — even redacted-looking ones.
- Typical length 40–120 lines. If the session was trivial, say so in five
  lines rather than padding.

## Step 2 — decide the file path

`sessions/<YYYY>/<YYYY-MM-DD>--<project>--<topic-slug>.md`

- Date in IST (Asia/Kolkata). Project = main repo touched (or `general`).
  Slug = 2–5 lowercase hyphenated words.
- Saving the SAME session again (updates later in the conversation):
  overwrite the same file — do not create a second one.
- Two different sessions on the same day/topic: add `-2` to the slug.

## Step 3 — push it to instatank/2ndbrain (branch: main)

1. Find or get a clone:
   - A clone already in this session (e.g. `/workspace/2ndbrain` in cloud
     sessions, or a local checkout)? Use it: `git pull` first.
   - Cloud session without the repo: add `instatank/2ndbrain` to the
     session with the add_repo tool, then clone it.
   - Local Mac session: `git clone --depth 1
     https://github.com/instatank/2ndbrain ~/tmp-2ndbrain` (or reuse an
     existing local clone).
2. Write the digest file, then:
   `git add <file> && git commit -m "session: <date> <title>" && git push origin main`
3. Push rejected (someone else pushed)? `git pull --rebase origin main`
   and push again. **Never force-push** — this repo is memory; history is
   the point.
4. No repo access at all (auth fails, add_repo unavailable)? Do NOT drop
   the work: print the complete digest in chat, tell the founder it
   couldn't be pushed and why, and that he can either add the
   `instatank/2ndbrain` repo to this session and re-run `/save-to-brain`,
   or paste the digest into the repo himself.

## Step 4 — confirm

Reply with one short line: the file path saved, and a one-sentence summary
of what the digest captured. Nothing else — the digest is the deliverable,
not the announcement.
