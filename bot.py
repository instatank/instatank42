"""Personal AI agent on Telegram.

One user (allowlisted by Telegram ID) talks to Claude. Haiku handles routine
turns, Sonnet the complex ones. Memory is plain files (see memory.py); spend
is capped per-turn and per-day (see budget.py).
"""

import asyncio
import logging
import os
import sys
import time
from collections import deque

import anthropic
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import budget
import dayos_store
import digests
import ingest
import memory
import playbook_store
import whatsapp_store
import youtube_ingest
import youtube_store

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("agent")

# --- Config (all secrets from environment; nothing in the repo) ------------

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_ID = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "")
# ANTHROPIC_API_KEY is read by the anthropic client itself.

HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-5"
MAX_TOKENS = 1000           # per-turn output cap (hard limit on reply cost)
MAX_TOOL_ROUNDS = 3         # tool loop safety valve
MAX_HISTORY_MSGS = 20       # in-memory conversation window (10 exchanges)
RATE_LIMIT = (15, 60)       # max 15 messages per 60 seconds

SYSTEM_PROMPT = """You are a sharp, concise personal assistant for one person, \
chatting over Telegram. You know him from the profile below and recent session \
notes. Speak plainly, think in expected-value terms like he does, and keep \
replies short unless depth is asked for — this is a chat app, not a report.

When he tells you something durable about himself — a goal, preference, rule, \
decision, or life fact worth remembering next week — save it with the \
remember_fact tool (once per fact, only genuinely durable things).

You can search the web (web_search). Use it whenever current information would \
change the answer — news, prices, schedules, releases, anything after your \
training data — instead of answering from memory. Mention your sources briefly."""

TOOLS = [
    {
        "name": "remember_fact",
        "description": (
            "Save one durable fact about the user to long-term memory. Use for "
            "goals, preferences, rules, decisions, and life facts that should be "
            "remembered across days. Do not save small talk or transient details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The fact, as one self-contained sentence."}
            },
            "required": ["fact"],
        },
    }
]

# Anthropic's server-side web search: declared like a tool, but executed by
# the API itself — results come back inside the same response, cited. Cost is
# $10 per 1,000 searches (accounted in budget.py) + normal tokens; max_uses
# caps searches per message. Set WEB_SEARCH_MAX_USES=0 in .env to disable.
WEB_SEARCH_MAX_USES = int(os.environ.get("WEB_SEARCH_MAX_USES", "3"))
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": WEB_SEARCH_MAX_USES,
    "user_location": {
        "type": "approximate",
        "city": "New Delhi",
        "region": "Delhi",
        "country": "IN",
        "timezone": "Asia/Kolkata",
    },
}

# DayOS memory-bank tools — read the local file mirror that dayos_sync.py
# maintains (no network, no extra API cost per call beyond the tokens).
DAYOS_TOOLS = [
    {
        "name": "search_dayos",
        "description": (
            "Search everything the user logged in DayOS (his time-tracking + "
            "journaling app): journals, notes, project sessions, learning entries, "
            "activity blocks, weekly/monthly reviews. A single '#tag' query (e.g. "
            "'#win') matches that exact tag only; any other query requires ALL "
            "words to appear. Returns matching lines labeled by date/source, "
            "newest first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search words, or one '#tag'."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "dayos_day",
        "description": (
            "Full DayOS digest for one day: activity timeline with hours by "
            "category, daily journal, captures, project sessions, learning, "
            "end-of-day note, day rating, daily focus task."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "'today', 'yesterday' or YYYY-MM-DD."}
            },
            "required": ["date"],
        },
    },
    {
        "name": "dayos_period",
        "description": (
            "Weekly or monthly DayOS rollup: hours by category and by project, "
            "day ratings, focus-task completion, wins, plus his own Weekly/Monthly "
            "Review answers and AI summary. Use for trends and 'how was my week/month'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": (
                        "'this week', 'last week', 'this month', 'last month', "
                        "'YYYY-MM', or any date inside the week you want."
                    ),
                }
            },
            "required": ["period"],
        },
    },
    {
        "name": "dayos_project",
        "description": (
            "Per-project log from DayOS: all work sessions (before/during/after "
            "notes, done, pending, learned), project notes, tagged learning "
            "entries, and hours logged."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name or its #tag."}
            },
            "required": ["name"],
        },
    },
]


# Playbook memory-bank tools — read the git mirror playbook_sync.py maintains.
PLAYBOOK_TOOLS = [
    {
        "name": "search_playbook",
        "description": (
            "Search the user's written playbook: his cross-project working rules, "
            "transferable lessons learned from real failures, skill-building North "
            "Star (tracks, portfolio tiers), weekly technique curriculum, SOPs, and "
            "per-repo LEARNINGS ledgers. Use whenever he asks about his own rules, "
            "lessons, methods, priorities, or how he works. A single '#tag' query "
            "matches that exact tag only; any other query requires ALL words."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search words, or one '#tag'."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "playbook_doc",
        "description": (
            "Read one playbook document in full. Names are forgiving: 'playbook' "
            "(global rules + lessons), 'north star' (skill tracks + portfolio "
            "tiers), 'curriculum' (technique-of-the-week ladder), 'learning "
            "method', 'learnings' (friction/decision ledger), 'build brief' "
            "(template), 'sop ship' / 'sop deploy' / 'sop firebase sync' / "
            "'sop verify on phone', 'readme'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Document name, e.g. 'north star'."}
            },
            "required": ["name"],
        },
    },
]


# WhatsApp memory-bank tools — read the snapshot files whatsapp_ingest.py
# writes when the founder uploads a chat export (no live sync by design).
WHATSAPP_TOOLS = [
    {
        "name": "search_whatsapp",
        "description": (
            "Search the user's ingested WhatsApp conversations (manual chat-export "
            "snapshots). Use for 'what did we discuss/agree/decide with X about Y'. "
            "A single '#tag' query matches that exact tag only; any other query "
            "requires ALL words. Results are labeled by chat and day, newest first. "
            "Data ends at each chat's snapshot date — never treat it as live."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search words, or one '#tag'."},
                "chat": {"type": "string",
                         "description": "Optional: limit to one chat, by name."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "whatsapp_chat",
        "description": (
            "Read one ingested WhatsApp chat's messages, one month at a time "
            "(most recent month by default). Use after search_whatsapp when the "
            "surrounding conversation matters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Chat name, e.g. the contact or group."},
                "month": {"type": "string", "description": "Optional YYYY-MM."},
            },
            "required": ["name"],
        },
    },
]


# YouTube memory-bank tools — read the per-video snapshots youtube_ingest.py
# writes when the founder sends the bot a video link (link-drop tagging).
YOUTUBE_TOOLS = [
    {
        "name": "search_youtube",
        "description": (
            "Search the transcripts/summaries of YouTube videos the user chose "
            "to save (he tags a video by sending its link to this bot). Use for "
            "'that video about X I saved/sent you'. A single '#tag' query "
            "matches that exact tag only; any other query requires ALL words. "
            "Results are labeled with the video's title, newest saves first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search words, or one '#tag'."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "youtube_video",
        "description": (
            "Read one saved YouTube video's full entry — its transcript (or the "
            "user's pasted summary, when marked so), channel, save date, and any "
            "note he added. Match by title words or video id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Title words or the video id."}
            },
            "required": ["name"],
        },
    },
]


# Weekly-synthesis read tool — reads stored digests only; generation (which
# costs tokens) happens solely via /digest or the Friday timer.
DIGEST_TOOL = {
    "name": "weekly_digest",
    "description": (
        "Read one of YOUR OWN stored weekly syntheses — the distillation you "
        "(the agent) wrote about the user's week: patterns, deltas, open loops. "
        "Clearly your notes, not his words. Use for 'what did you make of my "
        "week' or when past weeks' arcs matter."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "period": {"type": "string",
                       "description": "'this week', 'last week', or a date in the week."}
        },
        "required": ["period"],
    },
}


def current_tools() -> list:
    """Bank tools appear once their sync is configured or data exists, so the
    bot works unchanged before each integration is set up."""
    tools = list(TOOLS)
    if WEB_SEARCH_MAX_USES > 0:
        tools.append(WEB_SEARCH_TOOL)
    if dayos_store.has_data() or os.environ.get("FIREBASE_SERVICE_ACCOUNT_FILE") \
            or os.environ.get("FIREBASE_SERVICE_ACCOUNT"):
        tools += DAYOS_TOOLS
    if playbook_store.has_data() or os.environ.get("PLAYBOOK_REPO_URL"):
        tools += PLAYBOOK_TOOLS
    if whatsapp_store.has_data():
        tools += WHATSAPP_TOOLS
    if youtube_store.has_data():
        tools += YOUTUBE_TOOLS
    if digests.has_any():
        tools.append(DIGEST_TOOL)
    return tools


def handle_tool(name: str, args: dict) -> str:
    """Execute one tool call, always returning a string for the model.
    Errors come back as text (fail loud to the model, never crash the turn)."""
    try:
        if name == "remember_fact":
            memory.append_fact(args["fact"])
            log.info("Saved fact: %s", args["fact"])
            return "Saved."
        if name == "search_dayos":
            return dayos_store.search(args.get("query", ""))
        if name == "dayos_day":
            return dayos_store.day(args.get("date", "today"))
        if name == "dayos_period":
            return dayos_store.period(args.get("period", "this week"))
        if name == "dayos_project":
            return dayos_store.project(args.get("name", ""))
        if name == "search_playbook":
            return playbook_store.search(args.get("query", ""))
        if name == "playbook_doc":
            return playbook_store.doc(args.get("name", ""))
        if name == "search_whatsapp":
            return whatsapp_store.search(args.get("query", ""), args.get("chat", ""))
        if name == "whatsapp_chat":
            return whatsapp_store.chat(args.get("name", ""), args.get("month", ""))
        if name == "search_youtube":
            return youtube_store.search(args.get("query", ""))
        if name == "youtube_video":
            return youtube_store.video(args.get("name", ""))
        if name == "weekly_digest":
            return digests.load(args.get("period", "this week"))
        return f"Unknown tool: {name}"
    except Exception as e:
        log.exception("Tool %s failed", name)
        return f"Tool error in {name}: {e}"

def health_banner() -> str:
    """Sync problems ride on every reply mechanically — never via the model
    remembering to mention them (playbook L11: machine-enforced, not
    memory-enforced). Verified necessary: the model happily answered from a
    broken bank's mirror without relaying the warning it was given."""
    notes = [n for n in (dayos_store.staleness_note(), playbook_store.staleness_note(),
                         whatsapp_store.staleness_note(), youtube_store.staleness_note()) if n]
    return "\n".join(notes)


client = anthropic.Anthropic()

# chat_id -> list of {"role", "content"} for the live conversation window
histories: dict[int, list] = {}
# user_id -> deque of recent message timestamps (rate limiting)
recent_msgs: dict[int, deque] = {}
# chat_id -> a detected-but-unconfirmed file upload (confirm-first ingestion;
# in-memory only — a bot restart drops it and the file just gets re-sent)
pending_ingests: dict[int, dict] = {}
# chat_id -> a fetched-but-unconfirmed YouTube link (same confirm-first rule;
# "awaiting_summary" means the founder pressed the fallback button and the
# next plain message is the summary to store)
pending_youtube: dict[int, dict] = {}

COMPLEX_HINTS = (
    "plan", "analyze", "analyse", "strategy", "strategic", "tradeoff",
    "trade-off", "decide", "decision", "think through", "pros and cons",
    "review my", "deep dive",
)


def pick_model(text: str) -> str:
    t = text.lower()
    if len(text) > 700 or any(h in t for h in COMPLEX_HINTS):
        return SONNET
    return HAIKU


def build_system() -> list:
    """Static prompt + profile (cached) + volatile recent notes after the
    cache breakpoint, so profile edits are the only thing that busts the cache.
    The DayOS snapshot (today/yesterday digest) also sits after the breakpoint —
    it changes through the day by design."""
    parts = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {
            "type": "text",
            "text": "## User profile\n" + memory.load_profile(),
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "## Recent session notes\n" + memory.recent_sessions()},
    ]
    snapshot = dayos_store.prompt_snapshot()
    if snapshot:
        parts.append({"type": "text", "text": snapshot})
    pb_note = playbook_store.prompt_note()
    if pb_note:
        parts.append({"type": "text", "text": pb_note})
    wa_note = whatsapp_store.prompt_note()
    if wa_note:
        parts.append({"type": "text", "text": wa_note})
    yt_note = youtube_store.prompt_note()
    if yt_note:
        parts.append({"type": "text", "text": yt_note})
    return parts


def run_claude(model: str, messages: list) -> tuple[str, float, list]:
    """One agent turn: call the API, execute remember_fact if requested,
    loop until Claude is done. Returns (reply_text, cost_usd, new_messages)."""
    cost = 0.0
    new_messages = list(messages)
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=build_system(),
            tools=current_tools(),
            messages=new_messages,
        )
        cost += budget.cost_of(model, response.usage)
        new_messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            # server-side web search paused mid-turn; re-send to let it resume
            continue
        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            return text.strip(), cost, new_messages
        results = [
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": handle_tool(block.name, block.input),
            }
            for block in response.content
            if block.type == "tool_use"
        ]
        new_messages.append({"role": "user", "content": results})
    return "(I got stuck in a tool loop — try rephrasing.)", cost, new_messages


def rate_limited(user_id: int) -> bool:
    q = recent_msgs.setdefault(user_id, deque())
    cutoff = time.time() - RATE_LIMIT[1]
    while q and q[0] < cutoff:
        q.popleft()
    q.append(time.time())
    return len(q) > RATE_LIMIT[0]


def authorized(update: Update) -> bool:
    user = update.effective_user
    if user and str(user.id) == ALLOWED_USER_ID:
        return True
    if user:
        log.warning("Ignored message from unauthorized user id=%s", user.id)
    return False


async def send_reply(update: Update, text: str) -> None:
    # Telegram caps messages at 4096 chars
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i : i + 4000])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update) or not update.message or not update.message.text:
        return
    user_text = update.message.text

    if rate_limited(update.effective_user.id):
        await send_reply(update, "Slowing down — too many messages in the last minute.")
        return

    # Link-drop tagging: a message containing a YouTube link IS the tag —
    # it goes to the ingest flow, not to Claude (and costs no API tokens).
    chat_id = update.effective_chat.id
    link = youtube_ingest.find_link(user_text)
    if link:
        await handle_youtube_link(update, user_text, *link)
        return
    pending_yt = pending_youtube.get(chat_id)
    if pending_yt and pending_yt.get("awaiting_summary"):
        await handle_youtube_summary(update, pending_yt, user_text)
        return

    if budget.over_daily_cap():
        await send_reply(
            update,
            f"Daily budget cap reached (${budget.DAILY_CAP_USD:.2f}). "
            "Resets at midnight IST. Raise DAILY_CAP_USD in the .env file if needed.",
        )
        return

    history = histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})
    model = pick_model(user_text)

    try:
        reply, cost, new_messages = await asyncio.to_thread(run_claude, model, history)
    except anthropic.APIError as e:
        log.error("API error: %s", e)
        await send_reply(update, f"Claude API error — paste this to Claude Code to debug:\n{e}")
        history.pop()  # don't leave a user turn with no assistant turn
        return

    budget.add_spend(cost)
    histories[chat_id] = new_messages[-MAX_HISTORY_MSGS:]
    memory.append_session("user", user_text)
    memory.append_session("agent", reply)
    banner = health_banner()
    prefix = f"⚠️ {banner}\n\n" if banner else ""
    await send_reply(update, prefix + (reply or "(empty reply)"))


async def handle_youtube_link(update: Update, user_text: str, vid: str, url: str) -> None:
    """Link-drop ingestion: fetch title + transcript (best effort), preview,
    and wait for a button press — nothing enters the brain silently. When the
    transcript can't be fetched (YouTube blocks datacenter IPs sometimes),
    offer the fallback: the founder pastes a summary instead."""
    await update.message.reply_text("YouTube link — fetching the video's info…")
    info = await asyncio.to_thread(youtube_ingest.fetch, vid)
    title = info["title"] or f"video {vid}"
    channel = info["channel"] or "unknown channel"
    pending_youtube[update.effective_chat.id] = {
        **info, "url": url,
        "note": youtube_ingest.note_from(user_text, url),
        "awaiting_summary": False,
    }
    if info["transcript"]:
        words = len(info["transcript"].split())
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Add to brain", callback_data="yt:add"),
            InlineKeyboardButton("Discard", callback_data="yt:discard"),
        ]])
        await update.message.reply_text(
            f"“{title}” — {channel}. Transcript fetched "
            f"({info['lang']}, ~{words} words). Save it to the brain? "
            "Re-sending this link later replaces the entry.",
            reply_markup=keyboard)
    else:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("I'll paste a summary", callback_data="yt:summary"),
            InlineKeyboardButton("Discard", callback_data="yt:discard"),
        ]])
        await update.message.reply_text(
            f"“{title}” — {channel}. Couldn't fetch the transcript: "
            f"{info['error']}. I can save the video with a summary you paste "
            "instead (e.g. from Gemini's summarize button).",
            reply_markup=keyboard)


async def handle_youtube_summary(update: Update, pending: dict, user_text: str) -> None:
    """The message after the 'I'll paste a summary' button = the summary."""
    if len(user_text.strip()) < 20:
        await update.message.reply_text(
            "That looks too short for a summary — paste the summary text, or "
            "send the link again to start over.")
        return
    pending_youtube.pop(update.effective_chat.id, None)
    try:
        result = await asyncio.to_thread(
            youtube_ingest.ingest, pending["vid"], pending["title"],
            pending["channel"], user_text, "summary", "", pending.get("note", ""))
    except Exception as e:
        log.exception("YouTube summary save failed")
        youtube_ingest.record_error(str(e))
        await update.message.reply_text(f"Save FAILED: {e}")
        return
    await update.message.reply_text(result)


async def handle_youtube_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The confirm/fallback/discard press for a pending YouTube link."""
    query = update.callback_query
    if not query or not query.from_user or str(query.from_user.id) != ALLOWED_USER_ID:
        return
    await query.answer()
    chat_id = query.message.chat_id if query.message else None
    pending = pending_youtube.get(chat_id)
    if pending is None:
        await query.edit_message_text("Nothing pending (the bot may have restarted) — send the link again.")
        return
    if query.data == "yt:discard":
        pending_youtube.pop(chat_id, None)
        await query.edit_message_text("Discarded — nothing was saved.")
        return
    if query.data == "yt:summary":
        pending["awaiting_summary"] = True
        await query.edit_message_text(
            "Okay — paste the summary as your next message and I'll save it "
            "with the video's link.")
        return
    pending_youtube.pop(chat_id, None)
    await query.edit_message_text("Saving…")
    try:
        result = await asyncio.to_thread(
            youtube_ingest.ingest, pending["vid"], pending["title"],
            pending["channel"], pending["transcript"] or "", "transcript",
            pending.get("lang", ""), pending.get("note", ""), pending.get("raw") or "")
    except Exception as e:
        log.exception("YouTube save failed")
        youtube_ingest.record_error(str(e))
        await query.edit_message_text(f"Save FAILED: {e}")
        return
    await query.edit_message_text(result)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """File-drop ingestion (building block #2): detect what an uploaded file
    is, show a preview, and wait for an explicit button press before anything
    touches the brain. Today that means WhatsApp chat exports (.txt/.zip)."""
    if not authorized(update) or not update.message or not update.message.document:
        return
    doc = update.message.document
    if doc.file_size and doc.file_size > ingest.MAX_FILE_BYTES:
        await update.message.reply_text(
            f"That file is {doc.file_size / 1e6:.1f} MB — over the "
            f"{ingest.MAX_FILE_BYTES / 1e6:.0f} MB ingest cap. For WhatsApp, "
            "export WITHOUT media and it'll be tiny.")
        return
    tg_file = await doc.get_file()
    data = bytes(await tg_file.download_as_bytearray())
    try:
        filename, text = ingest.extract_text(doc.file_name or "upload", data)
        parser, info = await asyncio.to_thread(ingest.detect, filename, text)
    except ValueError as e:
        await update.message.reply_text(f"Can't ingest that: {e}")
        return
    if parser is None:
        await update.message.reply_text(info)
        return
    pending_ingests[update.effective_chat.id] = {
        "parser": parser["name"], "filename": filename, "text": text,
    }
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Add to brain", callback_data="ingest:add"),
        InlineKeyboardButton("Discard", callback_data="ingest:discard"),
    ]])
    await update.message.reply_text(info["preview"], reply_markup=keyboard)


async def handle_ingest_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The confirm/discard press for a pending upload."""
    query = update.callback_query
    if not query or not query.from_user or str(query.from_user.id) != ALLOWED_USER_ID:
        return
    await query.answer()
    pending = pending_ingests.pop(query.message.chat_id, None) if query.message else None
    if pending is None:
        await query.edit_message_text("Nothing pending (the bot may have restarted) — send the file again.")
        return
    if query.data != "ingest:add":
        await query.edit_message_text("Discarded — nothing was saved.")
        return
    await query.edit_message_text("Ingesting…")
    try:
        summary = await asyncio.to_thread(
            ingest.run, pending["parser"], pending["filename"], pending["text"])
    except Exception as e:  # already recorded to the bank's status by ingest.run
        log.exception("Ingest failed")
        await query.edit_message_text(f"Ingest FAILED: {e}")
        return
    await query.edit_message_text(summary)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not authorized(update):
        # Help the owner find his numeric ID during setup
        await update.message.reply_text(
            f"Not authorized. Your Telegram user ID is {user.id} — "
            "put it in TELEGRAM_ALLOWED_USER_ID if this bot is yours."
        )
        return
    await update.message.reply_text(
        "Hi — I'm your agent. Just talk to me. /remember saves a fact, "
        "/spend shows today's cost, /sync refreshes the memory banks, "
        "/digest writes this week's synthesis now. Send me a WhatsApp chat "
        "export (.txt or .zip, no media) to add that conversation to the brain, "
        "or a YouTube link to save that video's transcript."
    )


async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    fact = " ".join(context.args or []).strip()
    if not fact:
        await update.message.reply_text("Usage: /remember I meditate at 6am daily")
        return
    memory.append_fact(fact)
    await update.message.reply_text("Saved to your profile.")


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh every configured memory bank on demand. `/sync full` forces a
    complete DayOS re-pull. Failures are reported per bank, never silent."""
    if not authorized(update):
        return
    import dayos_sync  # lazy: pulls httpx/cryptography only when actually used
    import playbook_sync

    if not dayos_sync.configured() and not playbook_sync.configured():
        await update.message.reply_text(
            "No memory banks are set up yet — deploy/DEPLOY.md steps 7 (DayOS) "
            "and 8 (playbook) have the walkthrough."
        )
        return
    await update.message.reply_text("Syncing memory banks…")
    lines = []
    if dayos_sync.configured():
        mode = "full" if (context.args and context.args[0].lower() == "full") else "auto"
        try:
            status = await asyncio.to_thread(dayos_sync.sync, mode)
            counts = status.get("counts", {})
            core = ", ".join(
                f"{counts[k]} {k}"
                for k in ("blocks", "captures", "dailyJournal", "sessions", "learning")
                if k in counts
            )
            lines.append(
                f"DayOS ({status.get('mode')} sync, {status.get('duration_s')}s): {core}. "
                f"{counts.get('digest_files', 0)} memory files up to date."
            )
        except Exception as e:  # surfaced, never silent — he must know it failed
            log.exception("DayOS sync failed")
            lines.append(f"DayOS sync FAILED: {e}")
    if playbook_sync.configured():
        try:
            status = await asyncio.to_thread(playbook_sync.sync)
            lines.append(
                f"Playbook: commit {status.get('commit')}, {status.get('files')} docs."
            )
        except Exception as e:
            log.exception("Playbook sync failed")
            lines.append(f"Playbook sync FAILED: {e}")
    await send_reply(update, "\n".join(lines))


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate (or regenerate) this week's synthesis right now and reply with
    it. The Friday timer does the same thing unprompted."""
    if not authorized(update):
        return
    if not dayos_store.has_data():
        await update.message.reply_text(
            "No DayOS data synced yet — the synthesis is written from it. Run /sync first.")
        return
    await update.message.reply_text("Writing this week's synthesis…")
    try:
        result = await asyncio.to_thread(digests.generate_week, "", client)
    except digests.BudgetCapError as e:
        await send_reply(update, f"Skipped: {e}")
        return
    except Exception as e:
        log.exception("Digest generation failed")
        await send_reply(update, f"Synthesis FAILED: {e}")
        return
    await send_reply(update, result["text"])


async def cmd_spend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        f"Today: ${budget.today_spend():.4f} (cap ${budget.DAILY_CAP_USD:.2f})\n"
        f"This month: ${budget.month_spend():.4f}"
    )


def main() -> None:
    missing = [
        name
        for name, val in [
            ("TELEGRAM_BOT_TOKEN", BOT_TOKEN),
            ("TELEGRAM_ALLOWED_USER_ID", ALLOWED_USER_ID),
            ("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")),
        ]
        if not val
    ]
    if missing:
        sys.exit(f"Missing environment variables: {', '.join(missing)} — set them in .env")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("remember", cmd_remember))
    app.add_handler(CommandHandler("spend", cmd_spend))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(handle_ingest_button, pattern=r"^ingest:"))
    app.add_handler(CallbackQueryHandler(handle_youtube_button, pattern=r"^yt:"))
    log.info("Bot starting (models: %s / %s, daily cap $%.2f)", HAIKU, SONNET, budget.DAILY_CAP_USD)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
