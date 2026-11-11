"""
yslem-bot — Discord bot for Roblox script security analysis.

Detects malicious patterns (webhook credential theft, executor exploits) by
tracing Lua scripts in a sandboxed local VM. No external network calls are made
during analysis. See discord-bot/README.md for full details.
"""
import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import re
import json
import secrets
import signal
import sys
import time
import random
import unicodedata
import asyncio
import contextlib
import gzip
import hashlib
import io
import threading
import aiohttp
import urllib.request
from urllib.parse import parse_qsl
# google.genai is imported lazily (see _get_gemini) -- it costs ~44 MB RSS, and
# on a 512 MB instance that memory is better left free for the devirt subprocess.
import redis.asyncio as aioredis
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone, timedelta
from typing import Optional

import admin_panel
import key_store
import oauth_verify
import roblox_api
import server_builder

# Dark red / near-black palette: rising intensity = rising severity.
EMBED_COLOR = 0x4A0404    # near-black red tint — default/info
SUCCESS_COLOR = 0x8B0000  # dark red — confirmed action
WARN_COLOR = 0xB22222     # brick red — caution / pending
ERROR_COLOR = 0xFF0000    # bright red — error / denied

# Single integration point for swapping in real custom (uploaded) emojis
# later (Discord format "<:name:id>") without touching the rest of the code.
EMOJIS = {
    "success": "✅",
    "error": "❌",
    "warn": "⚠️",
    "ticket": "🎫",
    "lock": "🔒",
    "shield": "🛡️",
    "lang": "🌐",
}

# Default auto-moderation word list (English + French). Whole-word matching
# (case-insensitive) to avoid false positives on substrings. This is the
# starting point copied into each guild's own editable list (!words).
BANNED_WORDS = {
    # English -- base profanity
    "fuck", "fucking", "fucker", "fuckers", "fuckup", "fuckwit", "motherfucker",
    "shit", "shitty", "shithead", "bullshit", "bitch", "bitches",
    "asshole", "asswipe", "asshat", "ass", "arse", "arsehole", "bastard",
    "cunt", "dick", "dickhead", "cock", "piss", "whore", "slut", "skank", "hoe",
    "twat", "wanker", "wanking", "knob", "knobhead", "bollocks", "bugger",
    "wank", "tosser", "minger", "slag",
    "dumbass", "faggot", "nigger", "nigga", "retard", "retarded",
    # English -- general insults
    "idiot", "idiotic", "stupid", "moron", "moronic", "imbecile", "imbeciles",
    "jerk", "jackass", "scumbag", "loser", "pathetic", "worthless", "ugly",
    "disgusting", "freak", "creep", "creepy", "clown", "dumb", "dummy",
    "dipshit", "douchebag", "douche", "prick", "cretin", "halfwit", "nitwit",
    "psycho", "degenerate", "pervert", "kys", "stfu",
    # French -- base profanity
    "merde", "putain", "connard", "connasse", "conne", "con", "salope",
    "enculé", "enculer", "encule", "enculé", "pute", "bordel", "batard",
    "bâtard", "niquer", "nique", "niques", "niqué", "negre", "nègre",
    "pd", "pédé", "pede", "ntm", "fdp", "tg",
    # French -- general insults
    "abruti", "abrutie", "débile", "debile", "idiote", "stupide", "crétin",
    "crétine", "cretin", "cretine", "imbécile", "imbecile", "moche",
    "minable", "pathétique", "pathetique", "nul", "nulle", "naze", "tocard",
    "tocarde", "blaireau", "taré", "tare", "taree", "tarée", "cinglé",
    "cingle", "cinglée", "cinglee", "dégénéré", "degenere", "degenerée",
    "pervers", "perverse", "salaud", "salopard", "ordure", "raclure",
    "racaille", "gogol", "boloss", "bolos", "ringard", "ringarde",
}

# The bot's creator -- treated as a bot admin on every server automatically,
# without needing to be added via !botadmin on each one individually. Not a
# Discord permission override: real permission-gated actions (kick/ban/mute/
# etc.) still go through Discord's own permission checks as normal: this
# only affects the bot's own admin-gated *configuration* commands.
BOT_OWNER_ID = 1498153496069931125

DEFAULT_LANG = "en"
user_lang = {}  # user_id -> "en" | "fr"

# guild_id -> {"roles": set(role_id), "users": set(user_id)}
bot_admins = {}
# guild_id -> set(word)
guild_banned_words = {}
# guild_id -> channel_id
log_channels = {}
# guild_id -> channel_id -- where PayPal IPN payment notifications get posted
paypal_notify_channels = {}
# Recent PayPal IPN transaction IDs, to ignore PayPal's automatic retries of
# the same notification. In-memory only (not persisted) -- worst case after
# a restart is one duplicate notification for a retry that lands right then.
_seen_paypal_txn_ids = set()
# guild_id -> channel_id -- where BTC/LTC on-chain payment notifications get posted
crypto_notify_channels = {}
# "{currency}:{txid}:{address}" keys already notified about. Also in-memory
# only, same tradeoff as _seen_paypal_txn_ids above.
_seen_crypto_txids = set()
# address keys ("{currency}:{address}") that have already been baselined --
# until an address is in here, its current transactions are historical, not
# new payments, so the first check silently records them without notifying.
_crypto_addresses_initialized = set()
# guild_id -> {"enabled": bool, "threshold": int, "window": int}
antiraid_settings = {}
antinuke_settings = {}
# guild_id -> {"enabled": bool, "channel_id": int|None, "join_message": str, "leave_message": str}
welcome_settings = {}
# guild_id -> [(timestamp, member_id)]
join_times = {}
# guild_id -> {"enabled": bool, "action": "log"|"timeout"|"kick", "threshold": int,
#              "min_age_days": int, "timeout_minutes": int}
screening_settings = {}
# guild_id -> [timestamp] of recent joins (for the "several accounts at once" signal)
_screening_joins = {}
SCREENING_ACTIONS = ("log", "quarantine", "timeout", "kick")
# (guild_id, user_id) -> [timestamp]
nuke_action_times = {}
# (guild_id, user_id) -> [reason]
warnings_store = {}
# guild_id -> {command_name: set(role_id)} -- when a command has an entry
# here, only bot admins and members holding one of these roles may use it.
command_access = {}

# guild_id -> {"paypal": str | None, "ltc": str | None, "btc": str | None, "roblox": str | None}
# -- the server-wide default/fallback payment info.
payment_info = {}

# user_id -> same shape as payment_info -- a staff member's own payment
# info, used instead of the guild default when they've claimed the
# ticket a customer is asking payment info in.
staff_payment_info = {}

# Bot-wide payment info (set by the bot owner): the fallback in EVERY server, so a server
# that never configured anything still shows the same details.
global_payment_info = {}
# guild_id -> last ticket number handed out (tickets are numbered per server)
ticket_counters = {}

# guild_id -> {
#   "category_name": str, "log_channel_id": int|None, "staff_role_ids": set(role_id),
#   "max_open_per_user": int, "warn_hours": float, "close_hours": float,
#   "leave_action": "notify"|"close", "categories": [str, ...],
# }
ticket_settings = {}
# (guild_id, channel_id) -> {"opener_id": int, "category": str, "created_at": iso, "last_activity": iso, "warned": bool}
open_tickets = {}

# guild_id -> {
#   "category_name": str, "log_channel_id": int|None, "recruiter_role_ids": set(role_id),
#   "cooldown_days": float, "granted_role_id": int|None,
# }
staffapp_settings = {}
# (guild_id, channel_id) -> {"applicant_id": int, "status": "pending"|"accepted"|"rejected",
#   "answers": {question_key: str}, "claimed_by": int|None, "created_at": iso,
#   "decided_by": int|None, "decided_at": iso|None, "reason": str}
staff_applications = {}
# (guild_id, user_id) -> iso timestamp of the last rejection -- reapply cooldown
staffapp_last_rejected = {}

# guild_id -> {normalized_question: {"question": str, "answer": str}} -- canned
# answers the "yslemm" chat trigger gives instantly when a message matches a
# question a bot-admin has configured via !yslemmfaq/`/yslemmfaq`.
yslemm_faq = {}

# (guild_id, channel_id, user_id) -> [{"role": "user"|"model", "text": str, "ts": float}]
# -- yslemm's short-term memory of its own conversation with this exact
# person in this exact channel, replayed to Gemini as real multi-turn
# history (not just the latest message) so a follow-up reads the way it
# would to a human: "actually make it 20 minutes", "and warn him too", or
# a plain "why?" all make sense in light of what was just said, instead of
# yslemm treating every message as a cold, context-free start. Expires
# after a few quiet minutes so an old, unrelated exchange never bleeds
# into a new one, and is scoped per person so two different people
# talking to yslemm in the same channel/ticket don't get tangled together.
yslemm_history = {}
YSLEMM_HISTORY_TTL = 1800  # 30 minutes of silence resets the thread
YSLEMM_HISTORY_MAX_TURNS = 24  # last 12 exchanges (user + model)
YSLEMM_TEXT_LIMIT = 2000  # per message sent to the model -- a full Discord message

# (guild_id, channel_id, user_id) -> unix time of the last exchange with
# yslemm. Within YSLEMM_FOLLOWUP_WINDOW of it, that person doesn't have to
# say "yslemm" again to keep talking -- the way you don't repeat someone's
# name on every line of a conversation. The model itself decides whether
# such a message is actually still meant for yslemm (addressed_to_me), so
# a follow-up aimed at someone else just passes through untouched.
yslemm_last_exchange = {}
YSLEMM_FOLLOWUP_WINDOW = 120

# (guild_id, channel_id, user_id) -> {"id": int, "ts": float} -- the last
# member yslemm actually resolved a target for in this conversation, so a
# bare pronoun follow-up with no fresh @mention ("ban him instead",
# "actually unmute her") still has someone to act on, exactly like a human
# keeping track of who "they" just meant. Never used to invent a target
# out of thin air -- only ever a member this same person already
# explicitly @mentioned a moment ago, so every real permission/hierarchy
# check still applies to it exactly as if it were mentioned again.
yslemm_last_target = {}
YSLEMM_TARGET_TTL = 300  # 5 minutes


def _yslemm_history_get(guild_id, channel_id, user_id):
    key = (guild_id, channel_id, user_id)
    now = time.time()
    turns = [t for t in yslemm_history.get(key, []) if now - t["ts"] < YSLEMM_HISTORY_TTL]
    yslemm_history[key] = turns
    return turns


def _yslemm_history_add(guild_id, channel_id, user_id, role, text):
    text = (text or "").strip()
    if not text:
        return
    key = (guild_id, channel_id, user_id)
    turns = _yslemm_history_get(guild_id, channel_id, user_id)
    turns.append({"role": role, "text": text[:YSLEMM_TEXT_LIMIT], "ts": time.time()})
    yslemm_history[key] = turns[-YSLEMM_HISTORY_MAX_TURNS:]


def _yslemm_remember_target(guild_id, channel_id, user_id, target_id):
    yslemm_last_target[(guild_id, channel_id, user_id)] = {"id": target_id, "ts": time.time()}


def _yslemm_recall_target(guild, channel_id, user_id):
    entry = yslemm_last_target.get((guild.id, channel_id, user_id))
    if entry is None or time.time() - entry["ts"] > YSLEMM_TARGET_TTL:
        return None
    return guild.get_member(entry["id"])

# set of (guild_id, channel_id) -- channels where an admin told yslemm to
# stop talking ("mute"/"silence"/"tais-toi" said with no member mentioned,
# since a real mute needs a target and this doesn't). While a channel is
# silenced, yslemm skips the LLM call entirely (no point spending quota
# just to stay quiet) and only listens for the matching "unmute" keyword
# with no target to lift it again.
yslemm_silenced_channels = set()

# guild_id -> {"channel_id": int, "message": str, "interval_minutes": int, "last_sent": iso str}
# -- a single recurring announcement per guild, re-posted to the configured
# channel every interval_minutes by recurring_reminder_check.
recurring_reminders = {}

# (guild_id, user_id) -> int
economy_balances = {}
# (guild_id, user_id) -> datetime of the last !daily claim
economy_last_daily = {}
DAILY_COIN_AMOUNT = 2

# guild_id -> {"words": bool}: switch of the banned-word filter (on by default)
automod_settings = {}
# guild_id -> {"enabled": bool, "threshold": int, "sanction": "warn"|"timeout"|"kick"|"ban", "timeout_minutes": int}
antipub_settings = {}
# guild_id -> set(word)
antipub_blacklist = {}
# guild_id -> set(role_id) -- members holding any of these roles are exempt
antipub_whitelist_roles = {}
# guild_id -> set(channel_id) -- messages in these channels are exempt
antipub_whitelist_channels = {}
# (guild_id, user_id) -> [(normalized_content, timestamp)] for repeated-message detection
antipub_recent_messages = {}

DEFAULT_ANTIPUB_KEYWORDS = {
    "free nitro", "nitro gratuit", "join my server", "rejoins mon serveur",
    "check out my server", "sub4sub", "sub 4 sub", "self bot", "selfbot",
    "dm me for", "mp moi pour", "add me on", "ajoute moi sur",
    "cheap boost", "boost pas cher", "buy followers", "achete des followers",
}

# Optional Redis connection (Render Key Value, free tier) so bot config
# (cmdaccess, admins, economy, antiraid/antinuke/antipub, payments,
# warnings...) survives restarts instead of resetting to empty every time
# the process restarts. Everything degrades gracefully to in-memory-only
# (today's behavior) if REDIS_URL isn't set.
REDIS_URL = os.environ.get("REDIS_URL")
redis_client = aioredis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
STATE_REDIS_KEY = "discord_bot:state"
PANEL_REDIS_KEY = "discord_bot:panel_activity"

# Optional Gemini API key (free tier, no credit card) so "yslemm" can
# understand free-form phrasing the keyword list doesn't cover, on top of
# -- not instead of -- the pure keyword system: the model only ever picks
# which action a message maps to (and pulls out a reason/name/duration),
# never executes anything. Every action it names still runs through the
# exact same permission and hierarchy checks as the keyword path. If the
# key is missing, the request times out, or the API errors, yslemm
# silently falls back to the keyword matcher -- the bot never becomes
# dependent on the API being up.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_AVAILABLE = bool(GEMINI_API_KEY)   # feature configured? (no import cost)
genai_types = None      # populated by _get_gemini() on first use
_gemini_client = None   # google.genai client, built lazily (see _get_gemini)


def _get_gemini():
    """Import google.genai lazily (~44 MB RSS) and build the client the first
    time the yslemm AI feature actually runs -- so that memory stays free for
    the devirt subprocess when the AI isn't in use. Populates the module-level
    `genai_types` so existing `genai_types.X` references keep working. Returns
    (client, genai_types), or (None, None) when no API key is configured."""
    global _gemini_client, genai_types
    if not GEMINI_API_KEY:
        return None, None
    if _gemini_client is None:
        from google import genai as _g
        from google.genai import types as _gt
        genai_types = _gt
        _gemini_client = _g.Client(api_key=GEMINI_API_KEY)
    return _gemini_client, genai_types
# Strongest first, gemini-3.5-flash-lite (fast, lightweight) last. Gemini's
# free quotas are counted per model, so using the top one never eats
# into the ones below it: when a model's quota is spent (429) the message
# simply goes to the next one down, and the spent model is skipped for a
# while instead of being retried on every message. Each model first gets
# real reasoning time (thinking), then a fast retry if that's too slow.
# Override the list with GEMINI_MODELS="a,b,c" and the reasoning depth
# with GEMINI_THINKING=minimal|low|medium|high.
GEMINI_MODEL_CANDIDATES = [
    m.strip() for m in os.environ.get("GEMINI_MODELS", "").split(",") if m.strip()
] or ["gemini-3.1-pro-preview", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
GEMINI_THINKING_LEVEL = os.environ.get("GEMINI_THINKING", "high").strip().upper()
# model -> unix time until which it's skipped (quota hit, unknown ID, or
# too slow just now), so one exhausted model doesn't cost every message a
# wasted round trip before falling through.
_gemini_cooldown_until = {}
# Models that rejected the thinking_config parameter -- retried without it.
_gemini_no_thinking = set()
_gemini_last_model = None

STRINGS = {
    "en": {
        "footer.requested_by": "Requested by {name}",
        "view.owner_only": "❌ Only the command author can use these buttons.",

        "ping.title": "🏓 Pong!",
        "ping.latency": "Latency",
        "ping.quality": "Quality",
        "ping.quality_excellent": "Excellent",
        "ping.quality_ok": "Decent",
        "ping.quality_poor": "Poor",
        "ping.refresh": "Refresh",

        "hello.title": "👋 Hello!",
        "hello.description": "Nice to see you, {mention}!",

        "info.members": "👥 Members",
        "info.channels": "💬 Channels",
        "info.roles": "🎭 Roles",
        "info.owner": "👑 Owner",
        "info.owner_unknown": "Unknown",
        "info.created": "📅 Created on",

        "userinfo.id": "🆔 ID",
        "userinfo.joined": "📅 Joined on",
        "userinfo.unknown": "Unknown",
        "userinfo.created": "🎂 Account created",
        "userinfo.top_role": "🎭 Top role",
        "userinfo.status": "Status",
        "status.online": "🟢 Online",
        "status.idle": "🌙 Idle",
        "status.dnd": "⛔ Do Not Disturb",
        "status.offline": "⚫ Offline",
        "status.unknown": "Unknown",

        "avatar.title": "🖼️ {name}'s avatar",
        "servericon.title": "🖼️ {guild}'s icon",
        "servericon.no_icon": "❌ This server has no icon.",

        "roleinfo.title": "🎭 {role}",
        "roleinfo.id": "ID",
        "roleinfo.members": "Members",
        "roleinfo.position": "Position",
        "roleinfo.mentionable": "Mentionable",
        "roleinfo.hoisted": "Displayed separately",
        "roleinfo.created": "Created on",
        "yes": "Yes",
        "no": "No",

        "default_reason": "No reason given",
        "afk.set_title": "💤 AFK status enabled",
        "afk.set_description": "{mention} is now AFK.\n**Reason:** {reason}",
        "afk.back_title": "👋 Welcome back",
        "afk.back_description": "Welcome back {mention}, your AFK status has been removed. You were away for {duration}.",
        "afk.mention_title": "💤 {name} is AFK",
        "afk.mention_description": "**Reason:** {reason}\n*Away for {duration}*",

        "remind.invalid": "❌ Invalid duration (between 0 and 10080 minutes).",
        "remind.scheduled_title": "⏰ Reminder scheduled",
        "remind.scheduled_description": "I'll remind you in **{minutes:g} min**: {message}",
        "remind.title": "⏰ Reminder!",

        "eightball.title": "🎱 Magic 8-Ball",
        "eightball.question": "Question",
        "eightball.answer": "Answer",

        "coinflip.title": "🪙 Coin Flip",
        "coinflip.result": "Result: **{result}**",
        "coinflip.heads": "Heads",
        "coinflip.tails": "Tails",

        "dice.title": "🎲 Dice Roll",
        "dice.result": "{faces}-sided die: **{result}**",

        "poll.title": "📊 Poll",
        "poll.for": "For",
        "poll.against": "Against",
        "poll.footer": "Poll started by {author} • {total} vote(s)",

        "clear.title": "🧹 Cleanup complete",
        "clear.description": "{count} message(s) deleted.",

        "kick.self": "❌ You can't kick yourself.",
        "kick.owner": "❌ You can't kick the server owner.",
        "kick.hierarchy": "❌ You can't kick someone with an equal or higher role than yours.",
        "kick.bot_hierarchy": "❌ I can't kick this member, their role is too high for me.",
        "kick.confirm_title": "👢 Confirm kick",
        "kick.confirm_description": "Kick **{member}**?\n**Reason:** {reason}",
        "kick.cancelled_title": "✖️ Kick cancelled",
        "kick.success_title": "✅ Member kicked",
        "kick.success_description": "**{member}** was kicked.\n**Reason:** {reason}",

        "ban.self": "❌ You can't ban yourself.",
        "ban.owner": "❌ You can't ban the server owner.",
        "ban.hierarchy": "❌ You can't ban someone with an equal or higher role than yours.",
        "ban.bot_hierarchy": "❌ I can't ban this member, their role is too high for me.",
        "ban.confirm_title": "🔨 Confirm ban",
        "ban.confirm_description": "Ban **{member}**?\n**Reason:** {reason}",
        "ban.cancelled_title": "✖️ Ban cancelled",
        "ban.success_title": "✅ Member banned",
        "ban.success_description": "**{member}** was banned.\n**Reason:** {reason}",

        "timeout.self": "❌ You can't timeout yourself.",
        "timeout.owner": "❌ You can't timeout the server owner.",
        "timeout.hierarchy": "❌ You can't timeout someone with an equal or higher role than yours.",
        "timeout.bot_hierarchy": "❌ I can't timeout this member, their role is too high for me.",
        "timeout.success_title": "🔇 Member timed out",
        "timeout.success_description": "**{member}** was timed out for {minutes} minute(s).\n**Reason:** {reason}",
        "untimeout.success_title": "🔊 Timeout removed",
        "untimeout.success_description": "**{member}**'s timeout was removed.",

        "confirm.expired": "\n\n⏱️ Confirmation expired.",
        "confirm.confirm": "Confirm",
        "confirm.cancel": "Cancel",

        "ticket.panel_title": "🎫 Support",
        "ticket.panel_description": "🛠️ **Support** — you have a question or a problem.\n🛒 **Buy** — you want to buy something from the shop.\nA private ticket opens with the staff.",
        "ticket.create_button": "Create ticket",
        "ticket.support_button": "Support",
        "ticket.buy_button": "Buy",
        "ticket.modal_title": "Open a ticket",
        "ticket.modal_title_support": "Support request",
        "ticket.q_subject": "Subject",
        "ticket.q_subject_placeholder": "e.g. Can't access a channel, bug, question...",
        "ticket.q_problem": "Describe your problem",
        "ticket.q_problem_placeholder": "What happens, since when, what you already tried...",
        "ticket.new_description_support": "Welcome {mention}! Your request is below. A staff member will answer here — you can already add screenshots or details.",
        "ticket.pay_not_for_support": "ℹ️ This is a support ticket: there is no payment here. To buy something, open a ticket with the **Buy** button.",
        "ticket.q_payment": "Payment method?",
        "ticket.q_payment_placeholder": "PayPal, LTC, BTC, Roblox (garam)...",
        "ticket.q_duration": "For how long? (if relevant)",
        "ticket.q_duration_placeholder": "e.g. 1 week, lifetime, one duel...",
        "ticket.q_offer": "What's your offer? (if relevant)",
        "ticket.q_offer_placeholder": "e.g. 3EUR, 2 garams...",
        "ticket.rules_field": "⚠️ Rules",
        "ticket.rules_value": (
            "- Don't share passwords or other sensitive info here.\n"
            "- An offer that's too low gets the ticket closed.\n"
            "- Inactive for {close_hours}h -> auto-closed{mute_suffix}.\n"
            "- Only an Owner (CHR, ALN, Yslem) decides to accept an offer or close a ticket."
        ),
        "ticket.rules_mute_suffix": ", and you'll be muted for {mute_duration}",
        "ticket.claim_payment_instructions": "💳 Here's the payment info. Send the agreed amount, then let us know here once it's done.",
        "ticket.already_open": "❌ You already have an open ticket: {channel}",
        "ticket.no_permission": "❌ I'm missing the 'Manage Channels' permission to create a ticket.",
        "ticket.new_title": "🎫 New ticket",
        "ticket.new_description": "Welcome {mention}! Please wait for a staff member to join this ticket.",
        "ticket.created_confirm": "✅ Ticket created: {channel}",
        "ticket.close_button": "Close ticket",
        "ticket.cannot_close": "❌ You can't close this ticket.",
        "ticket.closing_title": "🔒 Closing ticket",
        "ticket.closing_description": "Ticket closed by {mention}. Deleting in 5 seconds.",

        "help.title": "📖 Help menu",
        "help.description": "Select a category below to see the commands.\nPrefix: `!`",
        "help.home": "Home",
        "help.general": "General",
        "help.general_desc": "Info, avatar, utilities",
        "help.fun": "Fun",
        "help.fun_desc": "8ball, dice, coinflip, poll",
        "help.moderation": "Moderation",
        "help.moderation_desc": "Staff only",
        "help.security": "Security",
        "help.security_desc": "Anti-raid, anti-nuke, bot admins",
        "help.general_title": "✨ General commands",
        "help.fun_title": "🎲 Fun commands",
        "help.moderation_title": "🛡️ Moderation commands",
        "help.security_title": "🔐 Security & admin commands",

        "about.home_title": "🤖 Yslem -- Bot overview",
        "about.home_description": "Welcome! Here's a quick tour of everything I can do. Use the buttons below to explore each system, or run `/help` for the full command list.",
        "about.nav_home": "Home",
        "about.nav_ai": "AI",
        "about.nav_economy": "Economy",
        "about.nav_moderation": "Moderation",
        "about.nav_admin": "Admin",
        "about.field_ai": "🤖 AI (yslemm)",
        "about.field_ai_desc": "Talk to me in plain language, I understand and act on it.",
        "about.field_economy": "💰 Economy",
        "about.field_economy_desc": "A virtual coin system: earn, spend, and climb the leaderboard.",
        "about.field_tickets": "🎫 Tickets",
        "about.field_tickets_desc": "A full support-ticket system with inactivity tracking.",
        "about.field_moderation": "🛡️ Moderation & Security",
        "about.field_moderation_desc": "Anti-raid, anti-nuke, anti-advertising, account screening, and more.",
        "about.field_transparency": "🔒 Safe to use",
        "about.field_transparency_desc": "My moderation tools only work for members who hold the matching Discord permission, and the automatic protections stay off until an admin turns them on. I never ask for passwords or login tokens, I never join a server on my own, and I only use my own bot account. `/verify` only asks, on Discord's own page, to see your username, avatar and banner; `/key` only needs your Roblox username and a code in your profile. Data handling: `/privacy` on my web address.",
        "about.field_admin": "👑 Administration",
        "about.field_admin_desc": "Configure everything -- admin only.",
        "about.field_utility": "🔎 Utility",
        "about.field_utility_desc": "Reminders, AFK status, and more.",

        "about.ai_title": "🤖 The AI system -- \"yslemm\"",
        "about.ai_talk_name": "How to talk to me",
        "about.ai_talk_value": "Say the word \"yslemm\" anywhere in your message, @mention me directly, or reply to one of my own messages -- all three work.",
        "about.ai_understand_name": "What I understand",
        "about.ai_understand_value": "Natural-language moderation (mute, unmute, kick, ban, warn, clear), creating roles/channels, locking/unlocking a channel, showing payment info, showing your permissions, opening help, or switching your language -- just ask normally, no need to remember exact syntax.",
        "about.ai_convo_name": "Real conversation",
        "about.ai_convo_value": "Ask me real questions, insult me, throw math at me, or just chat -- I'll actually answer like a real AI (powered by Gemini), not pick from a fixed list of canned lines.",
        "about.ai_safety_name": "Safety",
        "about.ai_safety_value": "Every action I take still goes through the exact same permission and hierarchy checks as the real `!`/`/` commands -- I'm a shortcut, never a bypass. If the AI is ever unavailable, I fall back to solid keyword matching instead of going silent.",

        "about.economy_title": "💰 Economy -- coins",
        "about.admin_title": "👑 Admin-only commands",
        "about.admin_note": "These require bot-admin access or the relevant Discord permission.",
        "about.mod_mute": "Timeout a member for a set duration",
        "about.mod_ticket": "Configure the support-ticket system (category, staff roles, inactivity warnings/auto-close)",
        "cmd.ping": "Bot latency",
        "cmd.hello": "Say hello",
        "cmd.info": "Server info",
        "cmd.userinfo": "User info",
        "cmd.avatar": "Shows an avatar in large size",
        "cmd.servericon": "Shows the server icon",
        "cmd.roleinfo": "Role info",
        "cmd.afk": "Set yourself as away",
        "cmd.remind": "Schedule a reminder",
        "cmd.language": "Set your preferred language (en/fr)",
        "cmd.invite": "Get the bot's invite link",
        "cmd.uptime": "Show bot uptime",
        "cmd.8ball": "Ask the magic 8-ball",
        "cmd.coinflip": "Flip a coin",
        "cmd.dice": "Roll a die (default: 6 sides)",
        "cmd.poll": "Create a button-based poll",
        "cmd.clear": "Delete n messages, max 500",
        "cmd.kick": "Kick a member (confirmation required)",
        "cmd.ban": "Ban a member (confirmation required)",
        "cmd.timeout": "Timeout a member for a set duration",
        "cmd.untimeout": "Remove an active timeout from a member",
        "cmd.say": "Bot repeats the message",
        "cmd.ticketsetup": "Post the ticket creation panel",
        "cmd.automod": "🤖 Auto-moderation",
        "cmd.automod_desc": "Auto-moderation on command: !automod on|off|status (banned words + anti-ads)",
        "automod.status_title": "🤖 Auto-moderation",
        "automod.field_words": "Banned words",
        "automod.field_pub": "Anti-ads",
        "automod.field_raid": "Anti-raid",
        "automod.field_nuke": "Anti-nuke",
        "automod.words_detail": "{state} · {count} word(s) — /words",
        "automod.pub_detail": "{state} — /antipub",
        "automod.raid_detail": "{state} — /antiraid",
        "automod.nuke_detail": "{state} — /antinuke",
        "automod.hint": "/automod on or off: banned words + anti-ads. Choose one with the module option.",
        "automod.mod_words": "banned-word filter",
        "automod.mod_pub": "anti-ads",
        "automod.mod_all": "banned-word filter and anti-ads",
        "automod.turned_on": "✅ Auto-moderation turned on: {what}.",
        "automod.turned_off": "✅ Auto-moderation turned off: {what}.",
        "cmd.botadmin": "Manage who can control the bot (admin only)",
        "cmd.antiraid": "Configure anti-raid protection",
        "cmd.antinuke": "Configure anti-nuke protection",
        "cmd.welcome": "Welcome card for new members (own switch, channel, title, message, image) -- /welcome setup",
        "cmd.bye": "Goodbye card for members who leave (own switch, channel, title, message, image) -- /bye setup",
        "cmd.words": "View or edit the banned word list",
        "cmd.createrole": "Create a new role",
        "cmd.createchannel": "Create a new text channel",
        "cmd.setlogchannel": "Set the security log channel",
        "cmd.logs": "Show (and optionally set) the log channel and what gets logged there",
        "cmd.warn": "Warn a member",
        "cmd.warnings": "List a member's warnings",
        "cmd.clearwarnings": "Clear a member's warnings",
        "cmd.lock": "Lock / unlock the current channel",
        "cmd.slowmode": "Set channel slowmode",

        "error.no_permission": "❌ You don't have permission to do that.",
        "error.bot_no_permission": "❌ I'm missing permissions to do that.",
        "error.missing_manage_messages_delete": "⚠️ I can't auto-delete command messages in this channel -- I'm missing the **Manage Messages** permission here. Grant it to my role (or fix this channel's permission overwrite) to enable cleanup.",
        "yslemm.mute_confirm_title": "🔇 Confirm mute",
        "yslemm.mute_confirm_description": "Mute **{member}** for {minutes} minute(s)?\n**Reason:** {reason}",
        "yslemm.mute_cancelled_title": "✖️ Mute cancelled",
        "yslemm.greeting_1": "Yes?",
        "yslemm.greeting_2": "I'm listening.",
        "yslemm.greeting_3": "You called?",
        "yslemm.greeting_4": "Present.",
        "yslemm.faq_usage": "❌ Usage: `question | answer` (separate the question and the answer with `|`).",
        "yslemm.faq_added": "✅ Saved a canned answer for: **{question}**",
        "yslemm.faq_removed": "✅ Removed the canned answer for: **{question}**",
        "yslemm.faq_not_found": "❌ No canned answer found for: **{question}**",
        "yslemm.faq_list_title": "📋 Yslemm canned answers ({count})",
        "yslemm.faq_list_empty": "No canned answers configured yet.",
        "cmd.yslemmfaq": "Manage yslemm's canned Q&A answers (used by the \"yslemm\" chat trigger)",
        "yslemm.faq_howareyou": "Doing great, thanks for asking! What can I do for you?",
        "yslemm.faq_whoareyou": "I'm yslemm, this server's bot. Type `!help` or `/help` to see what I can do.",
        "yslemm.faq_creator": "I was made by yslem_dxb (Yslem) -- that's my creator and owner.",
        "yslemm.faq_prefix": "My prefix is `!`, or use `/` slash commands -- both work.",
        "yslemm.faq_shop": (
            "Here's what's available:\n"
            "🤝 **Partnership** -- 3€/$ (PayPal, Crypto, or 2 Brainrot garams [Roblox] -- free if you have 10k+ members)\n"
            "📦 **Paid Sources** -- 3€/$ (PayPal, Crypto, or 2 Brainrot garams [Roblox])\n"
            "⚔️ **Moon Duels** -- 5€/$ (PayPal, Crypto, 3 Brainrot garams [Roblox], or Nitro -- MM2 also accepted: Lifetime = Godly/Ice Breaker, Limited = zombie/fire effect)\n"
            "⚙️ **Auto Code** -- 7€/$ (PayPal, Crypto, or Brainrot [Roblox]: 1 day = 2 garama, 1 week = 3 garama, Lifetime = 4 garama -- Nitro or MM2 also accepted)\n\n"
            "Open a ticket, state your offer, and wait for an Owner (CHR, ALN, or Yslem) to respond. A ticket gets closed if the offer is too low, or if it's left empty."
        ),
        "yslemm.faq_garam": "\"Garam\" (or \"garams\"/\"garama\") is the currency from a Roblox game (Brainrot) -- paying with it means paying via that Roblox currency, tied to your Roblox account. Ask `!yslem` or open a ticket to see how many garams each product costs.",
        "yslemm.faq_openticket": "Look for the ticket panel in this server and click the 🎫 button, or ask a staff member where it is.",
        "yslemm.faq_thanks": "You're welcome!",
        "yslemm.faq_areyouai": "I'm a Discord bot built for this server -- I run on keyword matching, not a full AI.",
        "yslemm.usage_mute": "To mute someone, mention them when you talk to me, e.g. \"yslemm mute @member 10 minutes spam\" -- or use `!mute @member <minutes> <reason>` / `/mute`.",
        "yslemm.silenced": "🤐 Alright, I'll stay quiet in this channel. Say \"yslemm unmute\" to have me talk again.",
        "yslemm.unsilenced": "🔊 I'm back -- talking again in this channel.",
        "yslemm.usage_unmute": "To unmute someone, mention them, e.g. \"yslemm unmute @member\" -- or use `!unmute @member` / `/unmute`.",
        "yslemm.usage_kick": "To kick someone, mention them, e.g. \"yslemm kick @member reason\" -- or use `!kick @member <reason>` / `/kick`.",
        "yslemm.usage_ban": "To ban someone, mention them, e.g. \"yslemm ban @member reason\" -- or use `!ban @member <reason>` / `/ban`.",
        "yslemm.usage_warn": "To warn someone, mention them, e.g. \"yslemm warn @member reason\" -- or use `!warn @member <reason>` / `/warn`.",
        "yslemm.usage_dm": "To DM someone, mention them and give the message, e.g. \"yslemm dm @member your message here\".",
        "yslemm.dm_missing_text": "❌ You need to give the message to send too.",
        "yslemm.dm_sent": "✅ DM sent to {user}.",
        "yslemm.dm_failed": "❌ Couldn't DM {user} -- their DMs might be closed.",
        "yslemm.usage_createrole": "Tell me the role name too, e.g. \"yslemm create role VIP\" -- or use `!createrole <name>` / `/createrole`.",
        "yslemm.usage_createchannel": "Tell me the channel name too, e.g. \"yslemm create channel general\" -- or use `!createchannel <name> [category]` / `/createchannel`.",
        "yslemm.faq_balance": "Check coin balances with `!balance [@member]` or `/balance` -- leave the member out to check your own.",
        "yslemm.faq_daily": "Claim your daily coins with `!daily` or `/daily` -- once every 24 hours.",
        "yslemm.faq_poll": "Create a button-based poll with `/poll` (slash command only).",
        "yslemm.faq_pay": "Send coins to someone with `!pay @member <amount>` or `/pay`.",
        "yslemm.faq_invite": "Get the bot's invite link with `/invite` (slash command only).",
        "yslemm.faq_botadmin": "Bot admins are managed with `!botadmin adduser @user`, `!botadmin addrole @role` (and `removeuser`/`removerole`) -- admin only, or `/botadmin`.",
        "yslemm.faq_setlogchannel": "Set the security log channel with `!setlogchannel #channel` or `/setlogchannel`.",
        "yslemm.faq_words": "Manage the banned word list with `!words add <word>`, `!words remove <word>`, `!words list` -- or `/words`.",
        "yslemm.faq_antiraid": "Configure anti-raid protection with `!antiraid` (see subcommands) or `/antiraid`.",
        "yslemm.faq_antinuke": "Configure anti-nuke protection with `!antinuke` (see subcommands) or `/antinuke`.",
        "yslemm.faq_antipub": "Configure the anti-advertising filter with `!antipub` (see subcommands) or `/antipub`.",
        "yslemm.faq_welcome": "Welcome and goodbye are two separate cards: `/welcome setup` for new members, `/bye setup` for members who leave. Each has its own switch, channel, title, message and image.",
        "yslemm.faq_ticketconfig": "Configure the ticket system with `!ticket config` (category, logchannel, maxopen, inactivity, and more) or `/ticket config`.",
        "yslemm.faq_setpayment": "Set the PayPal/LTC info shown on the ticket panel with `!setpayment paypal <email>` / `!setpayment ltc <address>` -- or `/setpayment`.",
        "yslemm.faq_cmdaccess": "Restrict a command to specific roles with `!cmdaccess allow <command> @role` -- bot-admin only, or `/cmdaccess`.",
        "yslemm.faq_slowmode": "Set channel slowmode with `!slowmode <seconds>` or `/slowmode`.",
        "yslemm.faq_afk": "Set yourself as away with `/afk [reason]` (slash command only).",
        "yslemm.faq_remind": "Schedule a reminder with `/remind <time> <message>` (slash command only).",
        "yslemm.faq_leaderboard": "See the top coin balances with `!leaderboard` or `/leaderboard`.",
        "error.member_not_found": "❌ Member not found.",
        "error.role_not_found": "❌ Role not found.",
        "error.missing_argument": "❌ Missing argument. Use `!help` to see the syntax.",
        "error.bad_argument": "❌ Invalid argument.",
        "error.forbidden": "❌ Permission denied by Discord.",
        "error.not_bot_admin": "❌ You need to be a bot admin for that. Ask an administrator to grant access with `!botadmin adduser` or `!botadmin addrole`.",
        "error.no_command_access": "❌ You don't have access to this command. Ask an administrator to grant it with `!cmdaccess allow <command> @role`.",
        "error.no_command_access_coin": "❌ You need the required role, or 1 coin to use this command (you have 0). Use `!daily` to earn coins.",

        "automod.deleted_title": "❌ Message removed",
        "automod.deleted_description": "{mention}, please keep this space respectful.",
        "automod.deleted_log": "Deleted a message from {channel} for a banned word:\n>>> {content}",

        "language.set": "✅ Language set to **{lang}**.",
        "language.invalid": "❌ Invalid language. Use `en` or `fr`.",
        "language.en": "English",
        "language.fr": "Français",

        "invite.title": "🔗 Invite me",
        "invite.description": "[Click here to invite the bot to your server]({url})",
        "uptime.title": "⏱️ Uptime",
        "uptime.description": "Online for **{duration}**.",

        "botadmin.role_added": "✅ {role} can now manage the bot.",
        "botadmin.role_removed": "✅ {role} can no longer manage the bot.",
        "botadmin.user_added": "✅ {user} can now manage the bot.",
        "botadmin.user_removed": "✅ {user} can no longer manage the bot.",
        "botadmin.list_title": "🔐 Bot admins",
        "botadmin.list_roles": "Roles",
        "botadmin.list_users": "Users",
        "botadmin.list_empty": "None (only Administrators and the server owner)",

        "antiraid.status_title": "🛡️ Anti-raid status",
        "antiraid.status_label": "Status",
        "antiraid.enabled": "Enabled",
        "antiraid.disabled": "Disabled",
        "antiraid.threshold": "Threshold",
        "antiraid.window": "Window",
        "antiraid.on": "✅ Anti-raid enabled.",
        "antiraid.off": "✅ Anti-raid disabled.",
        "antiraid.already_on": "ℹ️ Anti-raid is already enabled.",
        "antiraid.already_off": "ℹ️ Anti-raid is already disabled.",
        "antiraid.configured": "✅ Anti-raid configured: {threshold} joins / {window}s.",
        "antiraid.triggered_title": "🚨 Raid detected",
        "antiraid.triggered_description": "{count} member(s) kicked automatically after a mass-join spike (window: {window}s).",

        "antinuke.status_title": "🛡️ Anti-nuke status",
        "antinuke.on": "✅ Anti-nuke enabled.",
        "antinuke.off": "✅ Anti-nuke disabled.",
        "antinuke.already_on": "ℹ️ Anti-nuke is already enabled.",
        "antinuke.already_off": "ℹ️ Anti-nuke is already disabled.",
        "antinuke.configured": "✅ Anti-nuke configured: {threshold} actions / {window}s.",
        "antinuke.triggered_title": "🚨 Nuke attempt detected",
        "antinuke.triggered_description": "**{member}** performed {count}+ destructive actions within {window}s. Their roles were stripped and they were kicked.",
        "antinuke.bot_join_title": "🤖 New bot joined -- validation required",
        "antinuke.bot_join_description": "**{bot}** (`{bot_id}`) just joined this server, added by **{adder}**.\nA staff member with Kick permission needs to validate or reject it below.",
        "antinuke.bot_join_unknown_adder": "unknown (no matching audit log entry)",
        "antinuke.bot_join_resolved_by": "Resolved by",
        "antinuke.bot_join_validated": "✅ Validated by {moderator} -- the bot stays.",
        "antinuke.bot_join_rejected": "❌ Rejected by {moderator} -- the bot was kicked.",
        "antinuke.bot_join_reject_failed": "⚠️ {moderator} tried to reject this bot, but kicking it failed (missing permission or already gone).",

        "greet.join.name": "Welcome card",
        "greet.leave.name": "Goodbye card",
        "greet.panel_title_join": "👋 Welcome card — new members",
        "greet.panel_title_leave": "🚪 Goodbye card — members who leave",
        "greet.field_state": "Status",
        "greet.field_channel": "Channel",
        "greet.field_title": "Title",
        "greet.field_message": "Message",
        "greet.field_image": "Banner image",
        "greet.system_channel": "System channel (default)",
        "greet.panel_hint": "Placeholders: {mention} {name} {server} {count} — the member's profile picture is added automatically.",
        "greet.btn_on": "Turn on",
        "greet.btn_off": "Turn off",
        "greet.btn_edit": "Edit card",
        "greet.btn_test": "Preview",
        "greet.pick_channel": "Choose the channel",
        "greet.modal_title": "Edit the card",
        "greet.f_title": "Title",
        "greet.f_message": "Message",
        "greet.f_image": "Banner image (https link, optional)",
        "greet.not_yours": "❌ This panel is not yours. Open your own with /welcome setup or /bye setup.",
        "greet.preview_note": "👁️ Preview — this is what members will see (with your profile picture).",
        "greet.enabled": "✅ {what} turned on.",
        "greet.disabled": "✅ {what} turned off.",
        "greet.already_on": "ℹ️ {what} is already on.",
        "greet.already_off": "ℹ️ {what} is already off.",
        "greet.channel_set": "✅ {what} will be posted in {channel}.",
        "greet.message_set": "✅ {what}: message updated.",
        "greet.title_set": "✅ {what}: title updated.",
        "greet.image_set": "✅ {what}: banner image updated.",
        "greet.image_cleared": "✅ {what}: banner image removed.",
        "greet.image_invalid": "❌ The image must be a link starting with https:// (300 characters max). Use - to remove it.",
        "screening.status_title": "🛡️ Account screening",
        "screening.action_label": "Action on flagged accounts",
        "screening.threshold_label": "Score threshold",
        "screening.minage_label": "Young account below",
        "screening.timeout_label": "Timeout length",
        "screening.on": "✅ Account screening enabled: new accounts are checked when they join.",
        "screening.off": "✅ Account screening disabled.",
        "screening.already_on": "ℹ️ Account screening is already enabled.",
        "screening.already_off": "ℹ️ Account screening is already disabled.",
        "screening.action_set": "✅ Flagged accounts will now be: **{action}**.",
        "screening.action_invalid": "❌ Choose one of: `log`, `quarantine`, `timeout`, `kick`.",
        "screening.threshold_set": "✅ Accounts scoring **{value}** or more will be flagged.",
        "screening.minage_set": "✅ Accounts younger than **{value}** day(s) count as young.",
        "screening.timeout_set": "✅ Flagged accounts will be timed out for **{value}** minute(s) (when the action is `timeout`).",
        "screening.flag_title": "🚩 Suspicious new account",
        "screening.flag_description": "{member} (`{id}`) joined with a suspicion score of **{score}** (threshold **{threshold}**).\n{reasons}\n**Action:** {action}",
        "screening.check_title": "🔍 Account check: {member}",
        "screening.check_description": "Score: **{score}** (threshold **{threshold}**) -- {verdict}\n{reasons}",
        "screening.verdict_ok": "looks fine",
        "screening.verdict_flag": "would be flagged",
        "screening.reasons_none": "No suspicious signal.",
        "screening.reason_age_day": "• Account created less than 24 h ago (+3)",
        "screening.reason_age_young": "• Account younger than {days} day(s) (+2)",
        "screening.reason_avatar": "• No profile picture (default avatar) (+2)",
        "screening.reason_banner": "• No profile banner (+1)",
        "screening.reason_name": "• Username ends with 4+ digits, typical of generated accounts (+1)",
        "screening.reason_burst": "• Several accounts joined within the last minute (+{points})",
        "screening.action_log": "logged only",
        "screening.action_timeout": "timed out for {minutes} min",
        "screening.action_kick": "kicked",
        "screening.action_failed": "could not be applied (missing permission or role too high)",
        "screening.action_quarantine": "placed in quarantine",
        "screening.quarantine_label": "Quarantine role",
        "screening.quarantine_set": "✅ Flagged accounts get {role} when the action is `quarantine`. Release them with `!screening release @member`.",
        "screening.quarantine_off": "✅ No quarantine role: the `quarantine` action will report that it could not be applied.",
        "screening.release_done": "✅ {member} was released from quarantine.",
        "screening.release_none": "ℹ️ {member} is not in quarantine.",
        "key.channel_only": "❌ Use this command in the #{channel} channel.",
        "key.slow": "⏳ Slow down a little, then try again.",
        "aibuild.usage": "ℹ️ Tell me what to do, e.g. `/aibuild request:sort all the channels into fitting categories` or `an English support area with a public help channel, a private staff channel and a Support Helper role`.",
        "aibuild.not_configured": "❌ The AI isn't configured: the `GEMINI_API_KEY` variable is missing on the host.",
        "aibuild.bot_perms": "❌ I need the Manage Channels and Manage Roles permissions.",
        "aibuild.busy": "⏳ A server build is already running, or you asked too quickly. Wait a moment.",
        "aibuild.failed": "❌ The AI couldn't produce a usable plan. Try again, or be more specific.",
        "aibuild.nothing": "ℹ️ Nothing new to create: everything in the plan already exists.",
        "aibuild.too_many": "❌ That would go over Discord's limit for this server ({what}).",
        "aibuild.preview_title": "🧱 Server plan: nothing is created yet",
        "aibuild.preview_footer": "Roles {roles} · Categories {categories} · Channels {channels} · Moves {moves} · Renames {renames} · Nothing is deleted and no permission of what exists is changed.",
        "aibuild.roles_header": "Roles ({count}):",
        "aibuild.existing": "already exists",
        "aibuild.notes": "Notes",
        "aibuild.warn_limit": "• Trimmed: at most {max} {what}.",
        "aibuild.warn_perms": "• {name}: powers beyond basic member permissions were removed.",
        "aibuild.warn_unknown_role": "• A restriction on the role “{name}” was ignored (no such role).",
        "aibuild.confirm": "Create it",
        "aibuild.cancel": "Cancel",
        "aibuild.not_yours": "❌ Only the admin who asked can use these buttons.",
        "aibuild.running": "⏳ Creating... this takes about a minute.",
        "aibuild.cancelled": "✖️ Cancelled, nothing was created.",
        "aibuild.done": "✅ Done: {roles} role(s), {categories} categor(y/ies) and {channels} channel(s) created · {moved} moved · {renamed} renamed.{failed}\nChanged your mind? `/aiundo` reverts it (for 24 hours).",
        "aibuild.failed_items": "\n⚠️ Could not create: {names}",
        "aibuild.log_title": "🧱 Server structure built by the AI",
        "aibuild.moves_header": "Moves ({count}):",
        "aibuild.renames_header": "Renames ({count}):",
        "aibuild.order_header": "Category order:",
        "aibuild.warn_unknown_channel": "• Ignored an item that does not exist ({id}).",
        "aibuild.warn_unknown_category": "• Ignored a move to an unknown category “{name}”.",
        "aiundo.none": "ℹ️ Nothing to undo (there is no AI change in the last 24 hours).",
        "aiundo.preview_title": "↩️ Undo the last AI change?",
        "aiundo.preview": "This puts **{moved}** channel(s) back where they were, restores **{renamed}** name(s){order}, and deletes the **{created}** item(s) the AI created: only those that are still empty (a channel with messages is kept).",
        "aiundo.order": " and the category order",
        "aiundo.confirm": "Undo it",
        "aiundo.cancel": "Keep it",
        "aiundo.running": "⏳ Undoing...",
        "aiundo.cancelled": "✖️ Kept as it is.",
        "aiundo.done": "↩️ Undone: {moved} moved back, {renamed} renamed back, {deleted} deleted.{kept}{failed}",
        "aiundo.kept": "\nKept (not empty): {names}",
        "aiundo.failed": "\n⚠️ Could not revert: {names}",
        "aiundo.log_title": "↩️ AI change undone",
        "cmd.aiundo": "Undo the last change made by the AI server builder (within 24 hours)",
        "cmd.aibuild": "Let the AI plan roles, categories and channels (you confirm first)",
        "key.starting": "⏳ The key system is starting up. Try again in about a minute.",
        "key.dm_note": "📨 A copy was also sent to you by DM.",
        "key.replace_confirm": "ℹ️ You already have a key for **{name}** (valid until {expires}). If you lost it, press the button: you get a new key and the old one stops working (once a week, 3 a month).",
        "key.replace_button": "New key",
        "keyadmin.usage": "ℹ️ `!keyadmin info|revoke|ban|unban @member` · `!keyadmin stats`",
        "key.usage": "ℹ️ Type `/key pseudo:<your Roblox username>` to get your key, or `/key action:reset` to replace it.",
        "key.have_key": "ℹ️ You already have a key (linked to **{name}**, valid until {expires}). Use `/key action:reset` to replace it.",
        "key.banned": "🚫 You can't get a key. Contact the staff.",
        "key.admin_revoked": "🚫 Your key was revoked by the staff. Contact them to get a new one.",
        "key.bad_name": "❌ That doesn't look like a Roblox username (3 to 20 letters, digits or underscore).",
        "key.not_found": "❌ I can't find a Roblox user named **{name}**.",
        "key.roblox_taken": "❌ That Roblox account already has a key on another Discord account.",
        "key.linked_other": "❌ Your Discord account is already linked to another Roblox account. Contact the staff to change it.",
        "key.roblox_unavailable": "⚠️ Roblox isn't answering right now. Try again in a minute.",
        "key.step_code": "🔐 **Prove it's your account.** Paste this code anywhere in the *About* (description) of the Roblox profile **{name}**:\n```{code}```\nSave it, then press the button below (or run `/key` again). The code is valid {minutes} min and you can remove it from your profile afterwards.",
        "key.button": "✅ I added the code",
        "key.code_missing": "❌ I can't see the code in the description of **{name}** yet. Add `{code}` to the About section of your profile, save, wait a few seconds, then press the button again.",
        "key.pending_expired": "⏳ That request expired. Run `/key` again.",
        "key.not_yours": "❌ This button isn't yours.",
        "key.review": "🕓 Your account needs a quick check by the staff before it can get a key. They were notified.",
        "key.title": "🔑 Your script key",
        "key.description": "Key for **{name}**, valid until {expires}.\n\n**1.** Copy the key from the message right below (long-press it → Copy text).\n**2.** Paste it in the script window.\n\nIt only works for that Roblox account: don't share it. Lost it? Run `/key` again (once a week).",
        "key.sent_dm": "✅ I sent your key by DM.",
        "key.dm_closed": "⚠️ Your DMs are closed, so here is your key (only you can see this message):",
        "key.no_key": "ℹ️ You don't have a key yet. Run `/key pseudo:<your Roblox username>`.",
        "key.reset_too_soon": "⏳ You already got a new key this week. Next one possible {when}.",
        "key.reset_quota": "⏳ You used your 3 new keys of the month. Next one possible {when}.",
        "key.need_member": "❌ Choose the member with the `member` option.",
        "key.revoked_ok": "✅ {member}'s key was revoked. They can't get a new one by themselves.",
        "key.revoked_none": "ℹ️ {member} has no key.",
        "key.ban_ok": "✅ {member} is banned from the key system (their Roblox account too, if they had a key).",
        "key.unban_ok": "✅ {member} is no longer banned from the key system.",
        "key.unban_none": "ℹ️ {member} was not banned.",
        "key.info_title": "🔑 Key of {member}",
        "key.info_description": "Roblox: **{name}** (`{rid}`)\nStatus: **{status}**\nCreated: {created}\nExpires: {expires}\nResets used (30 days): {resets}/3\nBanned: {banned}",
        "key.status_active": "active",
        "key.status_expired": "expired",
        "key.status_revoked": "revoked",
        "key.status_none": "no key",
        "key.yes": "yes",
        "key.stats_title": "📊 Key system",
        "key.stats_description": "Active keys: **{live}** · banned accounts: **{banned}**\nChecks per script since the last restart:\n{lines}",
        "key.stats_none": "no check yet",
        "key.no": "no",
        "keysetup.guide_title": "🔑 Get your script key",
        "keysetup.guide": "**1.** You're in the server: done.\n**2.** In this channel, type `/key user:<your Roblox username>`.\n**3.** Copy the key I send you and paste it in the script window.",
        "keysetup.done": "✅ Channel {channel} is ready (name: `#{name}`).\nPermanent invite link: {invite}",
        "keysetup.failed": "❌ I couldn't set it up (I need the Manage Channels and Create Invite permissions).",
        "cmd.key": "Get your script key: /key user:<Roblox username> in the #key channel",
        "cmd.keysetup": "Create the #key channel with its guide and a permanent invite link",
        "screening.role_label": "Verified role",
        "screening.role_set": "✅ Members who pass the verification get {role}.",
        "screening.role_off": "✅ The verification no longer gives a role.",
        "verify.panel_title": "✅ Verification",
        "verify.panel_description": "Click **Verify** to confirm you're a real member. Discord will show you its own authorization page, which asks only to see your username, profile picture and banner. Nothing else is requested, I never see your password, and the authorization is removed as soon as the check is done.",
        "verify.button": "Verify",
        "verify.not_configured": "❌ The verification isn't set up yet. The bot owner has to add the `DISCORD_CLIENT_SECRET` variable on the host and the redirect `{redirect}` in the Discord Developer Portal (OAuth2 → Redirects).",
        "verify.panel_posted": "✅ Verification panel posted.",
        "verify.role_failed_title": "⚠️ Verification role",
        "verify.role_failed": "{member} passed the verification but I couldn't give them {role} (check my permissions and that my role is above it).",
        "cmd.verify": "Post the verification panel (admins)",
        "cmd.screening": "Configure the account screening of new members",
        "cmd.screen": "Check how suspicious a member's account looks",

        "words.list_title": "📝 Banned words ({count})",
        "words.list_empty": "No banned words configured.",
        "words.added": "✅ **{word}** added to the banned words list.",
        "words.already_exists": "❌ **{word}** is already banned.",
        "words.removed": "✅ **{word}** removed from the banned words list.",
        "words.not_found": "❌ **{word}** is not in the banned words list.",

        "role.created": "✅ Role {role} created.",
        "channel.created": "✅ Channel {channel} created.",
        "logchannel.set": "✅ Security log channel set to {channel}.",
        "modlog.by": "Action by {name}",

        "logs.title": "📋 Logging status",
        "logs.channel_set": "✅ {channel} -- everything below is sent there.",
        "logs.channel_unset": "❌ Not configured -- most events below won't be logged anywhere until you run `!logs #channel`. Anti-raid/anti-nuke alerts fall back to the server's system channel in the meantime.",
        "logs.channel_field": "Log channel",
        "logs.moderation_field": "🛡️ Moderation",
        "logs.moderation_value": "kick, ban, mute (timeout), warn, clear warnings",
        "logs.automod_field": "🤖 Automod",
        "logs.automod_value": "Message deleted for containing a banned word (`!words`)",
        "logs.antiraid_field": "🚨 Anti-raid",
        "logs.antiraid_value": "Mass-join spike detected -- members auto-kicked",
        "logs.antinuke_field": "💥 Anti-nuke",
        "logs.antinuke_value": "Mass destructive actions detected -- roles stripped, member kicked",
        "logs.antipub_field": "📢 Anti-pub",
        "logs.antipub_value": "Advertising/spam detected -- sanction applied per your `!antipub` config",
        "logs.set_note": "Give a channel to change it: `!logs #channel` or `/logs channel:#channel`.",

        "cmd.autoremind": "Configure a recurring reminder message posted automatically to a channel",
        "autoremind.post_title": "📌 Reminder",
        "autoremind.invalid_interval": "❌ Interval must be greater than 0 and at most 720 hours (30 days).",
        "autoremind.missing_message": "❌ You need to give the reminder text too.",
        "autoremind.set": "✅ Recurring reminder set: every {hours}h in {channel}.",
        "autoremind.stopped": "✅ Recurring reminder stopped.",
        "autoremind.not_configured": "❌ No recurring reminder configured. Use `!autoremind set #channel <hours> <message>`.",
        "autoremind.paused": "⏸️ Recurring reminder paused. Use `!autoremind unpause` to resume it right where it was, no need to set it up again.",
        "autoremind.unpaused": "▶️ Recurring reminder resumed.",
        "autoremind.already_paused": "❌ The recurring reminder is already paused.",
        "autoremind.not_paused": "❌ The recurring reminder isn't paused.",
        "autoremind.status_title": "📌 Recurring reminder status",
        "autoremind.status_channel": "Channel",
        "autoremind.status_interval": "Repeats every",
        "autoremind.status_message": "Message",
        "autoremind.status_next": "Next post (approx.)",
        "autoremind.status_paused": "Status",
        "autoremind.status_paused_value": "⏸️ Paused",
        "autoremind.status_running_value": "▶️ Running",

        "warn.title": "⚠️ Member warned",
        "warn.added": "**{member}** was warned.\n**Reason:** {reason}\n**Total warnings:** {count}",
        "warn.autoban_title": "🔨 Automatic ban",
        "warn.autoban_description": "**{member}** was automatically banned after reaching **{count}** warnings.",
        "warn.list_title": "⚠️ Warnings for {member}",
        "warn.list_empty": "No warnings.",
        "warn.cleared": "✅ Warnings cleared for **{member}**.",
        "warn.cleared_title": "🧹 Warnings cleared",

        "lock.locked": "🔒 Channel locked.",
        "lock.unlocked": "🔓 Channel unlocked.",
        "slowmode.set": "✅ Slowmode set to {seconds}s.",
        "slowmode.off": "✅ Slowmode disabled.",

        "cmd.yslem_about": "Interactive overview of the bot (AI, economy, moderation, admin)",

        "cmd.cmdaccess": "Restrict a command to specific roles (bot-admin only)",
        "cmdaccess.allowed": "✅ {role} can now use `{command}`. From now on, only bot admins and roles explicitly allowed can use it.",
        "cmdaccess.not_allowed": "❌ {role} didn't have explicit access to `{command}`.",
        "cmdaccess.removed": "✅ {role} can no longer use `{command}` (unless they're a bot admin).",
        "cmdaccess.reset": "✅ `{command}` is no longer restricted — back to its default access rules.",
        "cmdaccess.list_title": "🔐 Command access restrictions",
        "cmdaccess.list_empty": "No command is currently restricted. Every command uses its default access rules.",

        "ticket.cannot_claim": "❌ You need to be a bot admin or have Manage Channels to claim a ticket.",
        "ticket.claimed_label": "Claimed by {user}",
        "ticket.claimed_announce": "🙋 This ticket has been claimed by {mention}.",
        "ticket.claim_button": "Claim",
        "ticket.no_tickets": "❌ No open ticket channels found.",
        "ticket.staffroles_reset": "🔄 Cleared all staff roles and set {roles} as the new ticket staff role(s).",
        "ticket.bulk_closing": "🔒 Closing {count} ticket(s)...",
        "cmd.closetickets": "Close several/all open ticket channels at once",

        "payment.status_title": "💳 Payment info configuration",
        "payment.not_set": "Not set",
        "payment.paypal_set": "✅ PayPal info updated.",
        "payment.ltc_set": "✅ LTC address updated.",
        "payment.btc_set": "✅ BTC address updated.",
        "payment.roblox_set": "✅ Roblox username updated.",
        "payment.set_bulk": "✅ Updated: {fields}.",
        "payment.set_bulk_for": "✅ Updated for {user}: {fields}.",
        "payment.not_configured": "❌ No payment info has been configured yet.",
        "payment.clear_invalid_field": "❌ Unknown field. Use `paypal`, `ltc`, `btc`, `roblox`, or `all`.",
        "payment.clear_confirm_title": "⚠️ Clear payment info?",
        "payment.clear_confirm_description": "This will remove **{field}** from your own payment info (`!mypayment`). Confirm?",
        "payment.clear_cancelled_title": "❌ Cancelled",
        "payment.clear_success_title": "✅ Cleared",
        "payment.clear_success_description": "Removed **{field}** from your payment info.",
        "payment.title": "💳 Payment information",
        "payment.button": "Payment info",
        "payment.select_set_placeholder": "Set a payment field...",
        "payment.select_clear_placeholder": "Remove payment field(s)...",
        "payment.field_set": "✅ {field} updated.",
        "cmd.payment": "Manage a staff member's own PayPal/LTC/BTC/Roblox info (set or remove fields interactively) -- defaults to yourself",
        "cmd.setpaypalchannel": "Set the channel where PayPal payment notifications (IPN) get posted",
        "paypal.status_title": "💰 PayPal payment notifications",
        "paypal.channel_set": "✅ PayPal payment notifications will be posted in {channel}.",
        "paypal.channel_unset": "❌ No channel set yet. Use `!setpaypalchannel #channel`.",
        "paypal.setup_note": (
            "This only receives notifications for PayPal accounts that have IPN turned on. "
            "In PayPal (paypal.com), go to Account Settings -> Notifications -> Instant Payment "
            "Notifications -> Update, turn IPN on, and set the notification URL to:\n"
            "`https://discord-bot-0fbs.onrender.com/paypal-ipn`\n"
            "Do this for every PayPal account that should notify here (CHR, ALN, Yslem, etc.)."
        ),
        "paypal.ipn_title": "💰 PayPal payment received",
        "paypal.ipn_amount": "Amount",
        "paypal.ipn_from": "From",
        "paypal.ipn_owner": "Received by",
        "cmd.setcryptochannel": "Set the channel where BTC/LTC on-chain payment notifications get posted",
        "cmd.setpaymentchannels": "Set the channels where PayPal (IPN) and BTC/LTC on-chain payment notifications get posted",
        "crypto.status_title": "🪙 Crypto payment notifications",
        "crypto.channel_set": "✅ BTC/LTC payment notifications will be posted in {channel}.",
        "crypto.channel_unset": "❌ No channel set yet. Use `!setcryptochannel #channel`.",
        "crypto.watched_addresses": "Watching",
        "crypto.notify_title": "🪙 Crypto payment received",
        "crypto.notify_amount": "Amount",
        "crypto.notify_address": "Address",
        "crypto.notify_status": "Status",
        "crypto.status_confirmed": "✅ Confirmed",
        "crypto.status_pending": "⏳ Pending (unconfirmed)",
        "crypto.confirm_field": "Confirmation",
        "crypto.confirmed_yes": "✅ Payment confirmed received by {user}.",
        "crypto.confirmed_no": "❌ Flagged as NOT received by {user}.",
        "cmd.setpayment": "Configure the PayPal/LTC/BTC/Roblox payment info shown on the ticket panel",
        "cmd.mypayment": "Set your own PayPal/LTC/BTC/Roblox info, shown to a customer instead of the server default when you claim their ticket",

        "economy.balance_title": "💰 {user}'s balance",
        "economy.balance_amount": "**{amount}** coins",
        "economy.daily_cooldown": "⏳ You already claimed your daily coins. Try again in {hours}h {minutes}m.",
        "economy.daily_claimed": "✅ You claimed **{amount}** coins! New balance: **{total}**.",
        "economy.pay_self": "❌ You can't pay yourself.",
        "economy.pay_bot": "❌ You can't pay a bot.",
        "economy.pay_invalid": "❌ The amount must be positive.",
        "economy.pay_insufficient": "❌ You don't have enough coins.",
        "economy.pay_success": "✅ You sent **{amount}** coins to {member}.",
        "economy.leaderboard_title": "🏆 Coin leaderboard",
        "economy.leaderboard_empty": "No one has any coins yet.",
        "economy.admin_added": "✅ Added **{amount}** coins to {member}.",
        "economy.admin_removed": "✅ Removed **{amount}** coins from {member}.",
        "cmd.balance": "Show a member's coin balance",
        "cmd.daily": "Claim your daily coins",
        "cmd.pay": "Give some of your coins to another member",
        "cmd.leaderboard": "Show the top coin balances in this server",
        "cmd.addcoins": "Add coins to a member's balance (bot-admin only)",
        "cmd.removecoins": "Remove coins from a member's balance (bot-admin only)",

        "yslemsay.sent": "✅ Message sent.",
        "yslemsay.sent_in": "✅ Message sent in {channel}.",
        "say.sent": "✅ Message sent.",
        "say.sent_in": "✅ Message sent in {channel}.",
        "poll.posted": "✅ Poll posted.",
        "poll.posted_in": "✅ Poll posted in {channel}.",
        "ticket.panel_posted": "✅ Ticket panel posted.",
        "ticket.panel_posted_in": "✅ Ticket panel posted in {channel}.",
        "cmd.yslemsay": "Post a message as Yslem via webhook (no bot tag)",

        "ticket.limit_reached": "❌ You already have {count} open ticket(s), the max allowed here. Close one before opening another.",
        "ticket.category_field": "Category",
        "ticket.price_field": "Price",
        "ticket.methods_field": "Payment methods",
        "ticket.prices_title": "💰 Prices & payment methods",
        "ticket.category_placeholder": "Choose a ticket category...",
        "ticket.choose_category": "Choose a category for your ticket:",
        "ticket.log_closed_title": "🔒 Ticket closed",
        "ticket.log_closed_description": "**Channel:** #{channel}\n**Opened by:** {opener}\n**Closed by:** {closed_by}",
        "ticket.reason_auto": "Automatically",
        "ticket.reason_panel": "the admin panel",
        "ticket.closing_panel": "Ticket closed from the admin panel. Deleting in 5 seconds.",
        "ticket.reason_left": "opener left the server",
        "ticket.reason_inactivity": "inactivity",
        "ticket.pay_button": "Payment",
        "ticket.not_a_ticket": "❌ This channel is not an open ticket.",
        "ticket.staff_only": "❌ Only ticket staff can do that.",
        "ticket.already_claimed": "❌ This ticket is already handled by {user}.",
        "ticket.already_yours": "ℹ️ You already handle this ticket.",
        "ticket.not_claimed": "ℹ️ Nobody has claimed this ticket.",
        "ticket.released_announce": "↩️ {mention} released this ticket — another staff member can take it.",
        "ticket.done": "✅ Done.",
        "ticket.create_failed": "❌ Couldn't create the ticket right now. Try again in a moment.",
        "ticket.pay_wait_staff": "⏳ A staff member needs to take the ticket first — the payment info comes right after.",
        "ticket.close_modal_title": "Close this ticket",
        "ticket.close_reason_label": "Reason (optional)",
        "ticket.close_reason_placeholder": "e.g. order delivered, question solved…",
        "ticket.log_reason": "Reason",
        "ticket.log_number": "Ticket",
        "ticket.log_messages": "Messages",
        "ticket.log_handled_by": "Handled by",
        "ticket.log_opened_title": "🎫 Ticket opened",
        "ticket.log_opened_description": "**Ticket:** #{number} — {channel}\n**Opened by:** {opener}\n**Category:** {category}",
        "ticket.dm_closed": "🎫 Your ticket **#{number}** on **{server}** is closed. Here is a copy of the conversation. How was the support?",
        "ticket.rating_thanks": "✅ Thanks for your feedback!",
        "ticket.rating_log_title": "⭐ Ticket rating",
        "ticket.rating_log_description": "**Ticket:** #{number}\n**From:** {user}\n**Rating:** {stars}/5\n**Handled by:** {staff}",
        "ticket.member_added": "➕ {user} was added to the ticket by {by}.",
        "ticket.member_removed": "➖ {user} was removed from the ticket by {by}.",
        "ticket.cant_remove_opener": "❌ You can't remove the person who opened the ticket.",
        "ticket.no_bots": "❌ That doesn't work on bots.",
        "ticket.bad_name": "❌ Invalid name.",
        "ticket.renamed": "✅ Renamed to `{name}`.",
        "ticket.rename_limited": "⏳ Discord limits renames (2 every 10 minutes). Try again later.",
        "ticket.transcript_ready": "📄 Here is the transcript.",
        "ticket.list_title": "🎫 Open tickets",
        "ticket.list_more": "…and {count} more",
        "ticket.unclaimed": "unclaimed",
        "ticket.setup_summary": "✅ Ticket panel posted in {panel}.\n📁 Tickets are created under **{category}** (private).\n📝 Logs and transcripts go to {logs} (staff only).\n👥 Staff who can see tickets: {staff}\nNothing else to configure — adjust anything with `/ticket config`.",
        "payinfo.src_everywhere": "all servers",
        "payinfo.src_server": "this server",
        "payinfo.src_staff": "staff",
        "payinfo.owner_only": "❌ Only the bot owner can set the info used in every server. Use `scope: me` or `scope: server`.",
        "payinfo.staff_only": "❌ Only ticket staff can use this.",
        "payinfo.saved_me": "✅ Saved for you ({fields}) — it follows you in every server.",
        "payinfo.saved_server": "✅ Saved as this server's default ({fields}).",
        "payinfo.saved_everywhere": "✅ Saved for every server ({fields}).",
        "payinfo.auto_claimed": "🙋 You were assigned this ticket.",
        "payinfo.nothing_set": "❌ No payment info yet. Set it right here: `/payinfo paypal:you@mail.com ltc:L… btc:bc1… roblox:name` (add `scope:everywhere` for all servers).",
        "payinfo.nothing_set_customer": "❌ Payment info isn't available yet — please ask a staff member.",
        "ticket.leave_close_title": "👋 Ticket opener left",
        "ticket.leave_close_description": "{member} left the server. This ticket is being closed automatically.",
        "ticket.leave_notify_title": "👋 Ticket opener left the server",
        "ticket.leave_notify_description": "{member} left the server. Staff may want to follow up on this ticket.",
        "ticket.inactivity_warn_title": "⏳ Inactivity warning",
        "ticket.inactivity_warn_description": "{mention}, no response in this ticket for {hours}h. It will be automatically closed after {close_hours}h of inactivity.",
        "ticket.inactivity_mute_warn_suffix": " If it closes without a reply from you, you'll be muted for {mute_duration}.",
        "ticket.inactivity_close_title": "🔒 Closing due to inactivity",
        "ticket.inactivity_close_description": "{mention} did not respond within {close_hours}h. This ticket is being closed automatically.",
        "ticket.inactivity_close_muted_suffix": " {mention} has also been muted for {mute_duration}.",
        "ticket.config_mute": "Mute on auto-close",
        "ticket.mute_set_on": "✅ Ticket auto-close will now mute the opener for {duration}.",
        "ticket.mute_set_off": "✅ Ticket auto-close will no longer mute the opener.",
        "ticket.mute_invalid": "❌ Invalid option. Use `on` or `off`.",

        "ticket.config_title": "🎫 Ticket system configuration",
        "ticket.config_reset": "🔄 Ticket system configuration reset to defaults for this server.",
        "ticket.config_category": "Category",
        "ticket.config_logchannel": "Log channel",
        "ticket.config_maxopen": "Max open tickets per user",
        "ticket.config_warnhours": "Inactivity warning",
        "ticket.config_closehours": "Inactivity auto-close",
        "ticket.config_leaveaction": "When opener leaves the server",
        "ticket.config_types": "Ticket categories",
        "ticket.config_staffroles": "Extra staff roles",
        "ticket.disabled": "Disabled",
        "ticket.not_set": "Not set",
        "ticket.category_set": "✅ Ticket category set to **{name}**.",
        "ticket.logchannel_set": "✅ Ticket log channel set to {channel}.",
        "ticket.logchannel_cleared": "✅ Ticket log channel cleared.",
        "ticket.maxopen_set": "✅ Max open tickets per user set to {count}.",
        "ticket.inactivity_set": "✅ Inactivity settings updated: warn after {warn}h, close after {close}h (0 = disabled).",
        "ticket.leaveaction_set": "✅ Leave action set to **{action}**.",
        "ticket.leaveaction_invalid": "❌ Invalid option. Use `notify` or `close`.",
        "ticket.type_added": "✅ Ticket category **{name}** added.",
        "ticket.types_added_bulk": "✅ Added {count} ticket categories: {names}.",
        "ticket.type_exists": "❌ Ticket category **{name}** already exists.",
        "ticket.type_removed": "✅ Ticket category **{name}** removed.",
        "ticket.type_not_found": "❌ Ticket category **{name}** not found.",
        "ticket.type_last_one": "❌ You need at least one ticket category.",
        "ticket.types_full": "❌ Maximum 25 ticket categories reached.",
        "ticket.staffrole_added": "✅ {role} can now see and manage all tickets.",
        "ticket.staffrole_removed": "✅ {role} no longer has automatic access to tickets.",

        "cmd.staffapplysetup": "Post the staff-application panel",
        "cmd.closeapplications": "Close several/all open staff-application channels at once",
        "cmd.staffappconfig": "Configure the staff-application system (category, log channel, recruiter roles, cooldown, granted role...)",
        "staffapp.panel_title": "📋 Join the staff team",
        "staffapp.panel_description": "Want to join the team? Click below to apply. You'll answer a few questions, then a private channel is created to follow up on your application.",
        "staffapp.apply_button": "Apply for staff",
        "staffapp.panel_posted": "✅ Staff-application panel posted.",
        "staffapp.panel_posted_in": "✅ Staff-application panel posted in {channel}.",
        "staffapp.already_open": "❌ You already have an application open: {channel}",
        "staffapp.cooldown_active": "❌ Your last application was rejected. You can apply again in {days} day(s).",
        "staffapp.intro_title": "📋 Staff application",
        "staffapp.intro_description": "Thanks for wanting to join the team! The application has 12 questions in 3 steps: your general info, then 6 real-life scenarios, plus one optional question. It takes about 10 minutes -- answer honestly, that's what matters most.\n\nOnce submitted, a private channel is created: only you and the server owner can see it.",
        "staffapp.start_button": "Start the application",
        "staffapp.modal_a_title": "Staff application (1/3)",
        "staffapp.q_age_tz": "Age & timezone",
        "staffapp.q_age_tz_ph": "e.g. 19, GMT+1",
        "staffapp.q_availability": "Weekly availability",
        "staffapp.q_availability_ph": "e.g. 10h/week, mostly evenings and weekends",
        "staffapp.q_experience": "Prior experience (mod or other)",
        "staffapp.q_experience_ph": "Servers you staffed, what you did there...",
        "staffapp.q_motivation": "Why do you want to join staff?",
        "staffapp.q_motivation_ph": "Be honest and specific",
        "staffapp.q_strength": "Your biggest strength for this role",
        "staffapp.q_strength_ph": "What sets you apart from other applicants",
        "staffapp.situations_title": "📋 Staff application (2/3)",
        "staffapp.situations_description": "Step 2! These 5 questions are about real situations. Answer with what you'd actually do.\n\n1️⃣ A member publicly insults another member.\n2️⃣ A close friend of yours breaks an important server rule.\n3️⃣ You disagree with another staff member's decision, in front of members.\n4️⃣ A customer says they paid but got nothing, and is getting upset in the channel.\n5️⃣ A raid hits the server and you are the only staff member online.\n\nClick *Continue* to answer.",
        "staffapp.situations2_title": "📋 Staff application (3/3)",
        "staffapp.situations2_description": "Last step! One more situation, then one optional question.\n\n6️⃣ You see another staff member abusing their power (unfair ban, favouritism...).\n7️⃣ (Optional) Were you ever staff elsewhere? Why did you leave?\n\nClick *Continue* to answer.",
        "staffapp.modal_c_title": "Staff application (3/3)",
        "staffapp.q_sit_raid": "Raid, and you're the only staff online",
        "staffapp.q_sit_abuse": "A staff member abuses their power",
        "staffapp.recap_situations_title": "🧩 Scenarios",
        "staffapp.config_private": "Who sees the applications",
        "staffapp.private_on": "🔒 Only the applicant and the bot owner",
        "staffapp.private_off": "👥 The applicant, recruiter roles and server managers",
        "staffapp.private_set_on": "✅ Applications are now visible only to the applicant and the bot owner.",
        "staffapp.private_set_off": "✅ Applications are now also visible to recruiter roles and server managers.",
        "staffapp.continue_button": "Continue",
        "staffapp.modal_b_title": "Staff application (2/3)",
        "staffapp.q_sit_insult": "A member insults another, then?",
        "staffapp.q_sit_friend": "A close friend breaks a rule, then?",
        "staffapp.q_sit_disagree": "Disagree with staff publicly?",
        "staffapp.q_sit_payment": "Customer says they paid, no product",
        "staffapp.q_prior_staff": "Ex-staff elsewhere? Why did you leave?",
        "staffapp.recap_title": "📋 New staff application",
        "staffapp.recap_description": "New application from {mention}. A recruiter will review it soon.",
        "staffapp.channel_topic": "Staff application -- {user}",
        "staffapp.created_confirm": "✅ Application submitted: {channel}",
        "staffapp.claim_button": "Claim",
        "staffapp.accept_button": "Accept",
        "staffapp.reject_button": "Reject",
        "staffapp.close_button": "Close",
        "staffapp.cannot_claim": "❌ You need to be a bot admin or a recruiter to claim this application.",
        "staffapp.cannot_decide": "❌ You need to be a bot admin or a recruiter to accept or reject this application.",
        "staffapp.cannot_close": "❌ You need to be a bot admin or a recruiter to close this application.",
        "staffapp.already_decided": "❌ This application was already decided.",
        "staffapp.claimed_label": "Claimed by {user}",
        "staffapp.claimed_announce": "🙋 This application is now being reviewed by {mention}.",
        "staffapp.accepted_title": "Application accepted",
        "staffapp.accepted_description": "{mention}'s application was accepted by {by}. Welcome to the team!",
        "staffapp.role_field": "Role",
        "staffapp.role_granted": "{role} granted.",
        "staffapp.role_grant_failed": "⚠️ Couldn't grant {role} -- missing permission, add it manually.",
        "staffapp.rejected_title": "Application rejected",
        "staffapp.rejected_description": "{mention}'s application was rejected by {by}.",
        "staffapp.reason_field": "Reason",
        "staffapp.reject_modal_title": "Reject this application",
        "staffapp.reject_reason_label": "Reason (shown to the applicant, optional)",
        "staffapp.reject_reason_ph": "Kept short and constructive",
        "staffapp.closing_title": "Closing application",
        "staffapp.closing_description": "Application closed by {mention}. It will be deleted in 5 seconds.",
        "staffapp.log_accepted_title": "✅ Application accepted",
        "staffapp.log_accepted_description": "{applicant}'s staff application was accepted by {by}.",
        "staffapp.log_rejected_title": "❌ Application rejected",
        "staffapp.log_rejected_description": "{applicant}'s staff application was rejected by {by}.",
        "staffapp.log_closed_title": "🔒 Application closed",
        "staffapp.log_closed_description": "Application channel {channel} ({status}) closed by {closed_by}. Applicant: {applicant}.",
        "staffapp.status_pending": "pending",
        "staffapp.status_accepted": "accepted",
        "staffapp.status_rejected": "rejected",
        "staffapp.no_applications": "There's no open staff-application channel right now.",
        "staffapp.bulk_closing": "⏳ Closing {count} application channel(s)...",
        "staffapp.config_title": "📋 Staff-application configuration",
        "staffapp.config_category": "Category",
        "staffapp.config_logchannel": "Log channel",
        "staffapp.config_role": "Role granted on accept",
        "staffapp.config_cooldown": "Reapply cooldown",
        "staffapp.config_recruiters": "Recruiter roles",
        "staffapp.cooldown_value": "{days} day(s)",
        "staffapp.cooldown_off": "Disabled",
        "staffapp.config_reset": "✅ Staff-application configuration reset to defaults.",
        "staffapp.category_set": "✅ Applications will now be created under « {name} ».",
        "staffapp.logchannel_set": "✅ Staff-application log channel set to {channel}.",
        "staffapp.logchannel_cleared": "✅ Staff-application log channel cleared.",
        "staffapp.recruiter_added": "✅ {role} can now review staff applications.",
        "staffapp.recruiter_removed": "✅ {role} no longer has recruiter access.",
        "staffapp.recruiters_reset": "✅ Recruiter roles reset to: {roles}",
        "staffapp.cooldown_set": "✅ Reapply cooldown set to {days} day(s).",
        "staffapp.role_set": "✅ {role} will be granted automatically when an application is accepted.",
        "staffapp.role_cleared": "✅ No role will be granted automatically anymore.",
        "staffapp.reason_panel": "the admin panel",
        "staffapp.closing_panel": "Application closed from the admin panel. Deleting in 5 seconds.",

        "cmd.ticketconfig": "Configure the ticket system (category, log channel, inactivity, staff roles, categories...)",

        "antipub.status_title": "🚫 Anti-pub status",
        "antipub.threshold": "Threshold",
        "antipub.sanction": "Sanction",
        "antipub.timeout_minutes": "Timeout duration",
        "antipub.on": "✅ Anti-pub enabled.",
        "antipub.off": "✅ Anti-pub disabled.",
        "antipub.already_on": "ℹ️ Anti-pub is already enabled.",
        "antipub.already_off": "ℹ️ Anti-pub is already disabled.",
        "antipub.configured": "✅ Anti-pub configured: threshold {threshold}, sanction `{sanction}`.",
        "antipub.invalid_sanction": "❌ Invalid sanction. Use `warn`, `timeout`, `kick` or `ban`.",
        "antipub.blacklist_title": "📝 Anti-pub blacklist ({count})",
        "antipub.blacklist_added": "✅ **{word}** added to the anti-pub blacklist.",
        "antipub.blacklist_exists": "❌ **{word}** is already blacklisted.",
        "antipub.blacklist_removed": "✅ **{word}** removed from the anti-pub blacklist.",
        "antipub.blacklist_not_found": "❌ **{word}** is not in the anti-pub blacklist.",
        "antipub.whitelist_title": "📝 Anti-pub whitelist",
        "antipub.whitelist_roles": "Exempt roles",
        "antipub.whitelist_channels": "Exempt channels",
        "antipub.whitelist_role_added": "✅ {role} is now exempt from anti-pub.",
        "antipub.whitelist_role_removed": "✅ {role} is no longer exempt from anti-pub.",
        "antipub.whitelist_channel_added": "✅ {channel} is now exempt from anti-pub.",
        "antipub.whitelist_channel_removed": "✅ {channel} is no longer exempt from anti-pub.",
        "cmd.antipub": "Configure the anti-advertising system",

        "cmd.perm": "Show the bot's permission hierarchy",
        "perm.title": "🔐 Permission hierarchy",
        "perm.description": "How access is decided for every command, from most open to most restricted.",
        "perm.public_title": "1️⃣ Public — everyone",
        "perm.public_value": "`ping` `hello` `info` `userinfo` `avatar` `servericon` `roleinfo` `afk` `remind` `invite` `uptime` `balance` `daily` `pay` `leaderboard` `8ball` `coinflip` `dice` `poll` `yslem` `words list` `language` `help` `perm`",
        "perm.native_title": "2️⃣ Discord permission required",
        "perm.native_value": "**Manage Messages**: `say` `clear` `warn` `clearwarnings`\n**Kick Members**: `kick`\n**Ban Members**: `ban`\n**Moderate Members**: `timeout` `untimeout`\n**Manage Channels**: `ticketsetup` `lock` `unlock` `slowmode`",
        "perm.botadmin_title": "3️⃣ Bot admin (`!botadmin`)",
        "perm.botadmin_value": "`addcoins` `removecoins` `yslemsay` `closetickets` `ticket config` `setpayment` `mypayment` `payment` `createrole` `createchannel` `setlogchannel` `logs` `setpaypalchannel` `setcryptochannel` `autoremind` `words add/remove` `cmdaccess` `antiraid` `antinuke` `antipub` `welcome` `screening` `screen`",
        "perm.admin_title": "4️⃣ Server Administrator only",
        "perm.admin_value": "`botadmin` (addrole/removerole/adduser/removeuser) — stricter on purpose, so a bot admin can't grant themselves more power.",
        "perm.override_title": "⚙️ Overrides",
        "perm.override_value": "`!cmdaccess allow <command> @role` restricts any command above to specific roles.\n`yslem` specifically: a member without the allowed role can still use it by spending **1 coin** per use.\n`find` is open to everyone; on the website each download costs **1 coin** unless the member has the allowed role.",

        "cmd.saveconfig": "Force an immediate save of the bot's config to Redis (bot-admin only)",
        "saveconfig.no_redis": "❌ No Redis database is configured — nothing to save to, config only lives in memory right now.",
        "saveconfig.saved": "✅ Config saved.",
    },
    "fr": {
        "footer.requested_by": "Demandé par {name}",
        "view.owner_only": "❌ Seul l'auteur de la commande peut utiliser ces boutons.",

        "ping.title": "🏓 Pong !",
        "ping.latency": "Latence",
        "ping.quality": "Qualité",
        "ping.quality_excellent": "Excellente",
        "ping.quality_ok": "Correcte",
        "ping.quality_poor": "Faible",
        "ping.refresh": "Rafraîchir",

        "hello.title": "👋 Salut !",
        "hello.description": "Content de te voir, {mention} !",

        "info.members": "👥 Membres",
        "info.channels": "💬 Salons",
        "info.roles": "🎭 Rôles",
        "info.owner": "👑 Propriétaire",
        "info.owner_unknown": "Inconnu",
        "info.created": "📅 Créé le",

        "userinfo.id": "🆔 ID",
        "userinfo.joined": "📅 Rejoint le",
        "userinfo.unknown": "Inconnu",
        "userinfo.created": "🎂 Compte créé",
        "userinfo.top_role": "🎭 Rôle principal",
        "userinfo.status": "Statut",
        "status.online": "🟢 En ligne",
        "status.idle": "🌙 Absent",
        "status.dnd": "⛔ Ne pas déranger",
        "status.offline": "⚫ Hors ligne",
        "status.unknown": "Inconnu",

        "avatar.title": "🖼️ Avatar de {name}",
        "servericon.title": "🖼️ Icône de {guild}",
        "servericon.no_icon": "❌ Ce serveur n'a pas d'icône.",

        "roleinfo.title": "🎭 {role}",
        "roleinfo.id": "ID",
        "roleinfo.members": "Membres",
        "roleinfo.position": "Position",
        "roleinfo.mentionable": "Mentionnable",
        "roleinfo.hoisted": "Affiché séparément",
        "roleinfo.created": "Créé le",
        "yes": "Oui",
        "no": "Non",

        "default_reason": "Aucune raison",
        "afk.set_title": "💤 Statut AFK activé",
        "afk.set_description": "{mention} est maintenant AFK.\n**Raison :** {reason}",
        "afk.back_title": "👋 Retour de pause",
        "afk.back_description": "Bon retour {mention}, ton statut AFK a été retiré. Tu étais absent pendant {duration}.",
        "afk.mention_title": "💤 {name} est AFK",
        "afk.mention_description": "**Raison :** {reason}\n*Absent depuis {duration}*",

        "remind.invalid": "❌ Durée invalide (entre 0 et 10080 minutes).",
        "remind.scheduled_title": "⏰ Rappel programmé",
        "remind.scheduled_description": "Je te préviendrai dans **{minutes:g} min** : {message}",
        "remind.title": "⏰ Rappel !",

        "eightball.title": "🎱 Boule magique",
        "eightball.question": "Question",
        "eightball.answer": "Réponse",

        "coinflip.title": "🪙 Pile ou Face",
        "coinflip.result": "Résultat : **{result}**",
        "coinflip.heads": "Pile",
        "coinflip.tails": "Face",

        "dice.title": "🎲 Lancer de dé",
        "dice.result": "Dé à {faces} faces : **{result}**",

        "poll.title": "📊 Sondage",
        "poll.for": "Pour",
        "poll.against": "Contre",
        "poll.footer": "Sondage lancé par {author} • {total} vote(s)",

        "clear.title": "🧹 Nettoyage effectué",
        "clear.description": "{count} message(s) supprimé(s).",

        "kick.self": "❌ Tu ne peux pas t'expulser toi-même.",
        "kick.owner": "❌ Impossible d'expulser le propriétaire du serveur.",
        "kick.hierarchy": "❌ Tu ne peux pas expulser quelqu'un avec un rôle égal ou supérieur au tien.",
        "kick.bot_hierarchy": "❌ Je ne peux pas expulser ce membre, son rôle est trop élevé pour moi.",
        "kick.confirm_title": "👢 Confirmer l'expulsion",
        "kick.confirm_description": "Expulser **{member}** ?\n**Raison :** {reason}",
        "kick.cancelled_title": "✖️ Expulsion annulée",
        "kick.success_title": "✅ Membre expulsé",
        "kick.success_description": "**{member}** a été expulsé.\n**Raison :** {reason}",

        "ban.self": "❌ Tu ne peux pas te bannir toi-même.",
        "ban.owner": "❌ Impossible de bannir le propriétaire du serveur.",
        "ban.hierarchy": "❌ Tu ne peux pas bannir quelqu'un avec un rôle égal ou supérieur au tien.",
        "ban.bot_hierarchy": "❌ Je ne peux pas bannir ce membre, son rôle est trop élevé pour moi.",
        "ban.confirm_title": "🔨 Confirmer le bannissement",
        "ban.confirm_description": "Bannir **{member}** ?\n**Raison :** {reason}",
        "ban.cancelled_title": "✖️ Bannissement annulé",
        "ban.success_title": "✅ Membre banni",
        "ban.success_description": "**{member}** a été banni.\n**Raison :** {reason}",

        "timeout.self": "❌ Tu ne peux pas te mettre toi-même en timeout.",
        "timeout.owner": "❌ Impossible de mettre en timeout le propriétaire du serveur.",
        "timeout.hierarchy": "❌ Tu ne peux pas mettre en timeout quelqu'un avec un rôle égal ou supérieur au tien.",
        "timeout.bot_hierarchy": "❌ Je ne peux pas mettre ce membre en timeout, son rôle est trop élevé pour moi.",
        "timeout.success_title": "🔇 Membre mis en timeout",
        "timeout.success_description": "**{member}** a été mis en timeout pendant {minutes} minute(s).\n**Raison :** {reason}",
        "untimeout.success_title": "🔊 Timeout retiré",
        "untimeout.success_description": "Le timeout de **{member}** a été retiré.",

        "confirm.expired": "\n\n⏱️ Confirmation expirée.",
        "confirm.confirm": "Confirmer",
        "confirm.cancel": "Annuler",

        "ticket.panel_title": "🎫 Support",
        "ticket.panel_description": "🛠️ **Support** — tu as une question ou un problème.\n🛒 **Acheter** — tu veux acheter quelque chose à la boutique.\nUn ticket privé s'ouvre avec le staff.",
        "ticket.create_button": "Créer un ticket",
        "ticket.support_button": "Support",
        "ticket.buy_button": "Acheter",
        "ticket.modal_title": "Ouvrir un ticket",
        "ticket.modal_title_support": "Demande de support",
        "ticket.q_subject": "Sujet",
        "ticket.q_subject_placeholder": "ex : accès à un salon, bug, question...",
        "ticket.q_problem": "Décris ton problème",
        "ticket.q_problem_placeholder": "Ce qui se passe, depuis quand, ce que tu as déjà essayé...",
        "ticket.new_description_support": "Bienvenue {mention} ! Ta demande est ci-dessous. Un membre du staff te répondra ici — tu peux déjà ajouter des captures ou des détails.",
        "ticket.pay_not_for_support": "ℹ️ Ceci est un ticket de support : il n'y a pas de paiement ici. Pour acheter, ouvre un ticket avec le bouton **Acheter**.",
        "ticket.q_payment": "Mode de paiement ?",
        "ticket.q_payment_placeholder": "PayPal, LTC, BTC, Roblox (garam)...",
        "ticket.q_duration": "Pour combien de temps ? (si pertinent)",
        "ticket.q_duration_placeholder": "ex : 1 semaine, à vie, un duel...",
        "ticket.q_offer": "Quelle est ton offre ? (si pertinent)",
        "ticket.q_offer_placeholder": "ex : 3EUR, 2 garams...",
        "ticket.rules_field": "⚠️ Règles",
        "ticket.rules_value": (
            "- Ne partage pas de mot de passe ni d'autre info sensible ici.\n"
            "- Une offre trop basse entraîne la fermeture du ticket.\n"
            "- Inactif pendant {close_hours}h -> fermeture automatique{mute_suffix}.\n"
            "- Seul un Owner (CHR, ALN, Yslem) décide d'accepter une offre ou de fermer un ticket."
        ),
        "ticket.rules_mute_suffix": ", et tu seras mute {mute_duration}",
        "ticket.claim_payment_instructions": "💳 Voici les infos de paiement. Envoie le montant convenu, puis dis-le nous ici une fois fait.",
        "ticket.already_open": "❌ Tu as déjà un ticket ouvert : {channel}",
        "ticket.no_permission": "❌ Il me manque la permission 'Gérer les salons' pour créer un ticket.",
        "ticket.new_title": "🎫 Nouveau ticket",
        "ticket.new_description": "Bienvenue {mention} ! Merci d'attendre qu'un membre du staff rejoigne ce ticket.",
        "ticket.created_confirm": "✅ Ticket créé : {channel}",
        "ticket.close_button": "Fermer le ticket",
        "ticket.cannot_close": "❌ Tu ne peux pas fermer ce ticket.",
        "ticket.closing_title": "🔒 Fermeture du ticket",
        "ticket.closing_description": "Ticket fermé par {mention}. Suppression dans 5 secondes.",

        "help.title": "📖 Menu d'aide",
        "help.description": "Sélectionne une catégorie ci-dessous pour voir les commandes.\nPréfixe : `!`",
        "help.home": "Accueil",
        "help.general": "Général",
        "help.general_desc": "Infos, avatar, utilitaires",
        "help.fun": "Fun",
        "help.fun_desc": "8ball, dé, pile ou face, sondage",
        "help.moderation": "Modération",
        "help.moderation_desc": "Réservées au staff",
        "help.security": "Sécurité",
        "help.security_desc": "Anti-raid, anti-nuke, admins du bot",
        "help.general_title": "✨ Commandes générales",
        "help.fun_title": "🎲 Commandes fun",
        "help.moderation_title": "🛡️ Commandes de modération",
        "help.security_title": "🔐 Commandes sécurité & admin",

        "about.home_title": "🤖 Yslem -- Aperçu du bot",
        "about.home_description": "Bienvenue ! Voici un aperçu rapide de tout ce que je sais faire. Utilise les boutons ci-dessous pour explorer chaque système, ou tape `/help` pour la liste complète des commandes.",
        "about.nav_home": "Accueil",
        "about.nav_ai": "IA",
        "about.nav_economy": "Économie",
        "about.nav_moderation": "Modération",
        "about.nav_admin": "Admin",
        "about.field_ai": "🤖 IA (yslemm)",
        "about.field_ai_desc": "Parle-moi normalement, je comprends et j'agis.",
        "about.field_economy": "💰 Économie",
        "about.field_economy_desc": "Un système de pièces virtuelles : gagne, dépense, grimpe au classement.",
        "about.field_tickets": "🎫 Tickets",
        "about.field_tickets_desc": "Un système de support complet avec suivi d'inactivité.",
        "about.field_moderation": "🛡️ Modération & Sécurité",
        "about.field_moderation_desc": "Anti-raid, anti-nuke, anti-pub, vérification des comptes, et plus encore.",
        "about.field_transparency": "🔒 En toute sécurité",
        "about.field_transparency_desc": "Mes outils de modération ne fonctionnent que pour les membres qui ont la permission Discord correspondante, et les protections automatiques restent désactivées tant qu'un admin ne les active pas. Je ne demande jamais de mot de passe ni de token de connexion, je ne rejoins aucun serveur toute seule et j'utilise uniquement mon propre compte de bot. `/verify` demande seulement, sur la page de Discord, de voir ton pseudo, ta photo et ta bannière ; `/key` n'a besoin que de ton pseudo Roblox et d'un code dans ton profil. Données : `/privacy` sur mon adresse web.",
        "about.field_admin": "👑 Administration",
        "about.field_admin_desc": "Configure tout -- réservé aux admins.",
        "about.field_utility": "🔎 Utilitaires",
        "about.field_utility_desc": "Rappels, statut absent, et plus.",

        "about.ai_title": "🤖 Le système IA -- « yslemm »",
        "about.ai_talk_name": "Comment me parler",
        "about.ai_talk_value": "Dis le mot « yslemm » n'importe où dans ton message, mentionne-moi directement avec @, ou réponds à l'un de mes messages -- les trois marchent.",
        "about.ai_understand_name": "Ce que je comprends",
        "about.ai_understand_value": "La modération en langage naturel (mute, unmute, kick, ban, warn, clear), créer des rôles/salons, verrouiller/déverrouiller un salon, afficher les infos de paiement, afficher tes permissions, ouvrir l'aide, ou changer ta langue -- demande normalement, pas besoin de retenir la syntaxe exacte.",
        "about.ai_convo_name": "De vraies conversations",
        "about.ai_convo_value": "Pose-moi de vraies questions, insulte-moi, fais-moi calculer, ou discute simplement -- je réponds vraiment comme une IA (propulsée par Gemini), pas juste une ligne toute faite parmi une liste fixe.",
        "about.ai_safety_name": "Sécurité",
        "about.ai_safety_value": "Chaque action que je fais passe toujours par exactement les mêmes vérifications de permissions et de hiérarchie que les vraies commandes `!`/`/` -- je suis un raccourci, jamais un contournement. Si l'IA est indisponible, je retombe sur une reconnaissance de mots-clés solide plutôt que de rester silencieux.",

        "about.economy_title": "💰 Économie -- les pièces",
        "about.admin_title": "👑 Commandes réservées aux admins",
        "about.admin_note": "Ces commandes nécessitent l'accès admin du bot ou la permission Discord correspondante.",
        "about.mod_mute": "Réduit un membre au silence pendant une durée donnée",
        "about.mod_ticket": "Configure le système de tickets de support (catégorie, rôles staff, avertissements d'inactivité/fermeture auto)",
        "cmd.ping": "Latence du bot",
        "cmd.hello": "Dis bonjour",
        "cmd.info": "Infos sur le serveur",
        "cmd.userinfo": "Infos sur un utilisateur",
        "cmd.avatar": "Affiche un avatar en grand",
        "cmd.servericon": "Affiche l'icône du serveur",
        "cmd.roleinfo": "Infos sur un rôle",
        "cmd.afk": "Se déclarer absent",
        "cmd.remind": "Programme un rappel",
        "cmd.language": "Choisis ta langue préférée (en/fr)",
        "cmd.invite": "Récupère le lien d'invitation du bot",
        "cmd.uptime": "Affiche le temps de fonctionnement du bot",
        "cmd.8ball": "Consulte la boule magique",
        "cmd.coinflip": "Pile ou face",
        "cmd.dice": "Lance un dé (défaut : 6 faces)",
        "cmd.poll": "Crée un sondage à boutons",
        "cmd.clear": "Supprime n messages, max 500",
        "cmd.kick": "Expulse un membre (confirmation requise)",
        "cmd.ban": "Bannit un membre (confirmation requise)",
        "cmd.timeout": "Met un membre en timeout pour une durée donnée",
        "cmd.untimeout": "Retire le timeout actif d'un membre",
        "cmd.say": "Le bot répète le message",
        "cmd.ticketsetup": "Poste le panneau de création de tickets",
        "cmd.automod": "🤖 Automodération",
        "cmd.automod_desc": "Automodération sur commande : !automod on|off|status (mots interdits + anti-pub)",
        "automod.status_title": "🤖 Automodération",
        "automod.field_words": "Mots interdits",
        "automod.field_pub": "Anti-pub",
        "automod.field_raid": "Anti-raid",
        "automod.field_nuke": "Anti-nuke",
        "automod.words_detail": "{state} · {count} mot(s) — /words",
        "automod.pub_detail": "{state} — /antipub",
        "automod.raid_detail": "{state} — /antiraid",
        "automod.nuke_detail": "{state} — /antinuke",
        "automod.hint": "/automod on ou off : mots interdits + anti-pub. Choisis un seul module avec l'option module.",
        "automod.mod_words": "filtre des mots interdits",
        "automod.mod_pub": "anti-pub",
        "automod.mod_all": "filtre des mots interdits et anti-pub",
        "automod.turned_on": "✅ Automodération activée : {what}.",
        "automod.turned_off": "✅ Automodération désactivée : {what}.",
        "cmd.botadmin": "Gère qui peut contrôler le bot (admin uniquement)",
        "cmd.antiraid": "Configure la protection anti-raid",
        "cmd.antinuke": "Configure la protection anti-nuke",
        "cmd.welcome": "Carte de bienvenue pour les nouveaux (interrupteur, salon, titre, message, image propres) -- /welcome setup",
        "cmd.bye": "Carte d'au revoir pour ceux qui partent (interrupteur, salon, titre, message, image propres) -- /bye setup",
        "cmd.words": "Voir ou modifier la liste des mots interdits",
        "cmd.createrole": "Crée un nouveau rôle",
        "cmd.createchannel": "Crée un nouveau salon textuel",
        "cmd.setlogchannel": "Définit le salon des logs de sécurité",
        "cmd.logs": "Affiche (et configure) le salon de logs et ce qui y est enregistré",
        "cmd.warn": "Avertit un membre",
        "cmd.warnings": "Liste les avertissements d'un membre",
        "cmd.clearwarnings": "Efface les avertissements d'un membre",
        "cmd.lock": "Verrouille / déverrouille le salon actuel",
        "cmd.slowmode": "Définit le mode lent du salon",

        "error.no_permission": "❌ Tu n'as pas les permissions pour ça.",
        "error.bot_no_permission": "❌ Il me manque des permissions pour faire ça.",
        "error.missing_manage_messages_delete": "⚠️ Je ne peux pas supprimer automatiquement les messages de commande dans ce salon -- il me manque la permission **Gérer les messages** ici. Donne-la à mon rôle (ou corrige la permission spécifique à ce salon) pour activer le nettoyage.",
        "yslemm.mute_confirm_title": "🔇 Confirmer le mute",
        "yslemm.mute_confirm_description": "Mute **{member}** pendant {minutes} minute(s) ?\n**Raison :** {reason}",
        "yslemm.mute_cancelled_title": "✖️ Mute annulé",
        "yslemm.greeting_1": "Oui ?",
        "yslemm.greeting_2": "J'écoute.",
        "yslemm.greeting_3": "Tu m'as appelé ?",
        "yslemm.greeting_4": "Présent.",
        "yslemm.faq_usage": "❌ Utilisation : `question | réponse` (sépare la question et la réponse avec `|`).",
        "yslemm.faq_added": "✅ Réponse enregistrée pour : **{question}**",
        "yslemm.faq_removed": "✅ Réponse retirée pour : **{question}**",
        "yslemm.faq_not_found": "❌ Aucune réponse trouvée pour : **{question}**",
        "yslemm.faq_list_title": "📋 Réponses automatiques de yslemm ({count})",
        "yslemm.faq_list_empty": "Aucune réponse automatique configurée pour l'instant.",
        "cmd.yslemmfaq": "Gère les réponses automatiques de yslemm (utilisées par le déclencheur \"yslemm\" dans le chat)",
        "yslemm.faq_howareyou": "Ça va bien, merci de demander ! Je peux t'aider avec quelque chose ?",
        "yslemm.faq_whoareyou": "Je suis yslemm, le bot de ce serveur. Tape `!help` ou `/help` pour voir ce que je sais faire.",
        "yslemm.faq_creator": "J'ai été créé par yslem_dxb (Yslem) -- c'est mon créateur et propriétaire.",
        "yslemm.faq_prefix": "Mon préfixe c'est `!`, ou utilise les commandes `/` -- les deux marchent.",
        "yslemm.faq_shop": (
            "Voici ce qui est disponible :\n"
            "🤝 **Partnership** -- 3€/$ (PayPal, Crypto, ou 2 garams Brainrot [Roblox] -- gratuit si tu as 10k+ membres)\n"
            "📦 **Paid Sources** -- 3€/$ (PayPal, Crypto, ou 2 garams Brainrot [Roblox])\n"
            "⚔️ **Moon Duels** -- 5€/$ (PayPal, Crypto, 3 garams Brainrot [Roblox], ou Nitro -- MM2 accepté aussi : Lifetime = Godly/Ice Breaker, Limited = effet zombie/fire)\n"
            "⚙️ **Auto Code** -- 7€/$ (PayPal, Crypto, ou Brainrot [Roblox] : 1 jour = 2 garama, 1 semaine = 3 garama, Lifetime = 4 garama -- Nitro ou MM2 acceptés aussi)\n\n"
            "Ouvre un ticket, indique ton offre, et attends qu'un Owner (CHR, ALN, ou Yslem) te réponde. Un ticket est fermé si l'offre est trop basse, ou s'il est laissé vide."
        ),
        "yslemm.faq_garam": "\"Garam\" (ou \"garams\"/\"garama\") c'est la monnaie d'un jeu Roblox (Brainrot) -- payer avec ça veut dire payer via cette monnaie Roblox, liée à ton compte Roblox. Regarde `!yslem` ou ouvre un ticket pour voir combien de garams coûte chaque produit.",
        "yslemm.faq_openticket": "Cherche le panneau de tickets sur ce serveur et clique sur le bouton 🎫, ou demande à un membre du staff où il se trouve.",
        "yslemm.faq_thanks": "De rien !",
        "yslemm.faq_areyouai": "Je suis un bot Discord fait pour ce serveur -- je fonctionne par reconnaissance de mots-clés, pas une IA complète.",
        "yslemm.usage_mute": "Pour mute quelqu'un, mentionne-le quand tu me parles, ex : « yslemm mute @membre 10 minutes spam » -- ou utilise `!mute @membre <minutes> <raison>` / `/mute`.",
        "yslemm.silenced": "🤐 Ok, je reste silencieux dans ce salon. Dis « yslemm unmute » pour que je reparle.",
        "yslemm.unsilenced": "🔊 Je suis de retour -- je reparle dans ce salon.",
        "yslemm.usage_unmute": "Pour unmute quelqu'un, mentionne-le, ex : « yslemm unmute @membre » -- ou utilise `!unmute @membre` / `/unmute`.",
        "yslemm.usage_kick": "Pour kick quelqu'un, mentionne-le, ex : « yslemm kick @membre raison » -- ou utilise `!kick @membre <raison>` / `/kick`.",
        "yslemm.usage_ban": "Pour ban quelqu'un, mentionne-le, ex : « yslemm ban @membre raison » -- ou utilise `!ban @membre <raison>` / `/ban`.",
        "yslemm.usage_warn": "Pour avertir quelqu'un, mentionne-le, ex : « yslemm warn @membre raison » -- ou utilise `!warn @membre <raison>` / `/warn`.",
        "yslemm.usage_dm": "Pour envoyer un DM à quelqu'un, mentionne-le et donne le message, ex : « yslemm dm @membre ton message ici ».",
        "yslemm.dm_missing_text": "❌ Il faut aussi donner le message à envoyer.",
        "yslemm.dm_sent": "✅ DM envoyé à {user}.",
        "yslemm.dm_failed": "❌ Impossible d'envoyer un DM à {user} -- ses DMs sont peut-être fermés.",
        "yslemm.usage_createrole": "Donne-moi aussi le nom du rôle, ex : « yslemm crée un rôle VIP » -- ou utilise `!createrole <nom>` / `/createrole`.",
        "yslemm.usage_createchannel": "Donne-moi aussi le nom du salon, ex : « yslemm crée un salon general » -- ou utilise `!createchannel <nom> [catégorie]` / `/createchannel`.",
        "yslemm.faq_balance": "Vérifie les soldes de pièces avec `!balance [@membre]` ou `/balance` -- laisse le membre vide pour voir le tien.",
        "yslemm.faq_daily": "Récupère tes pièces quotidiennes avec `!daily` ou `/daily` -- une fois toutes les 24 heures.",
        "yslemm.faq_poll": "Crée un sondage à boutons avec `/poll` (commande slash uniquement).",
        "yslemm.faq_pay": "Envoie des pièces à quelqu'un avec `!pay @membre <montant>` ou `/pay`.",
        "yslemm.faq_invite": "Récupère le lien d'invitation du bot avec `/invite` (commande slash uniquement).",
        "yslemm.faq_botadmin": "Les admins du bot se gèrent avec `!botadmin adduser @user`, `!botadmin addrole @rôle` (et `removeuser`/`removerole`) -- admin uniquement, ou `/botadmin`.",
        "yslemm.faq_setlogchannel": "Définis le salon des logs de sécurité avec `!setlogchannel #salon` ou `/setlogchannel`.",
        "yslemm.faq_words": "Gère la liste des mots interdits avec `!words add <mot>`, `!words remove <mot>`, `!words list` -- ou `/words`.",
        "yslemm.faq_antiraid": "Configure la protection anti-raid avec `!antiraid` (voir les sous-commandes) ou `/antiraid`.",
        "yslemm.faq_antinuke": "Configure la protection anti-nuke avec `!antinuke` (voir les sous-commandes) ou `/antinuke`.",
        "yslemm.faq_antipub": "Configure le filtre anti-pub avec `!antipub` (voir les sous-commandes) ou `/antipub`.",
        "yslemm.faq_welcome": "Bienvenue et au revoir sont deux cartes séparées : `/welcome setup` pour les nouveaux, `/bye setup` pour ceux qui partent. Chacune a son interrupteur, son salon, son titre, son message et son image.",
        "yslemm.faq_ticketconfig": "Configure le système de tickets avec `!ticket config` (category, logchannel, maxopen, inactivity, et plus) ou `/ticket config`.",
        "yslemm.faq_setpayment": "Définis les infos PayPal/LTC affichées sur le panneau de tickets avec `!setpayment paypal <email>` / `!setpayment ltc <adresse>` -- ou `/setpayment`.",
        "yslemm.faq_cmdaccess": "Restreins une commande à certains rôles avec `!cmdaccess allow <commande> @rôle` -- admin du bot uniquement, ou `/cmdaccess`.",
        "yslemm.faq_slowmode": "Définis le mode lent du salon avec `!slowmode <secondes>` ou `/slowmode`.",
        "yslemm.faq_afk": "Passe en absent avec `/afk [raison]` (commande slash uniquement).",
        "yslemm.faq_remind": "Programme un rappel avec `/remind <temps> <message>` (commande slash uniquement).",
        "yslemm.faq_leaderboard": "Regarde le classement des pièces avec `!leaderboard` ou `/leaderboard`.",
        "error.member_not_found": "❌ Membre introuvable.",
        "error.role_not_found": "❌ Rôle introuvable.",
        "error.missing_argument": "❌ Argument manquant. Utilise `!help` pour voir la syntaxe.",
        "error.bad_argument": "❌ Argument invalide.",
        "error.forbidden": "❌ Permission refusée par Discord.",
        "error.not_bot_admin": "❌ Tu dois être admin du bot pour ça. Demande à un administrateur de t'ajouter avec `!botadmin adduser` ou `!botadmin addrole`.",
        "error.no_command_access": "❌ Tu n'as pas accès à cette commande. Demande à un administrateur de te l'accorder avec `!cmdaccess allow <commande> @rôle`.",
        "error.no_command_access_coin": "❌ Il te faut le rôle requis, ou 1 pièce pour utiliser cette commande (tu en as 0). Utilise `!daily` pour gagner des pièces.",

        "automod.deleted_title": "❌ Message supprimé",
        "automod.deleted_description": "{mention}, merci de rester respectueux ici.",
        "automod.deleted_log": "Message supprimé dans {channel} pour un mot interdit :\n>>> {content}",

        "language.set": "✅ Langue définie sur **{lang}**.",
        "language.invalid": "❌ Langue invalide. Utilise `en` ou `fr`.",
        "language.en": "English",
        "language.fr": "Français",

        "invite.title": "🔗 M'inviter",
        "invite.description": "[Clique ici pour inviter le bot sur ton serveur]({url})",
        "uptime.title": "⏱️ Temps de fonctionnement",
        "uptime.description": "En ligne depuis **{duration}**.",

        "botadmin.role_added": "✅ {role} peut maintenant gérer le bot.",
        "botadmin.role_removed": "✅ {role} ne peut plus gérer le bot.",
        "botadmin.user_added": "✅ {user} peut maintenant gérer le bot.",
        "botadmin.user_removed": "✅ {user} ne peut plus gérer le bot.",
        "botadmin.list_title": "🔐 Admins du bot",
        "botadmin.list_roles": "Rôles",
        "botadmin.list_users": "Utilisateurs",
        "botadmin.list_empty": "Aucun (seuls les Administrateurs et le propriétaire du serveur)",

        "antiraid.status_title": "🛡️ Statut anti-raid",
        "antiraid.status_label": "Statut",
        "antiraid.enabled": "Activé",
        "antiraid.disabled": "Désactivé",
        "antiraid.threshold": "Seuil",
        "antiraid.window": "Fenêtre",
        "antiraid.on": "✅ Anti-raid activé.",
        "antiraid.off": "✅ Anti-raid désactivé.",
        "antiraid.already_on": "ℹ️ L'anti-raid est déjà activé.",
        "antiraid.already_off": "ℹ️ L'anti-raid est déjà désactivé.",
        "antiraid.configured": "✅ Anti-raid configuré : {threshold} arrivées / {window}s.",
        "antiraid.triggered_title": "🚨 Raid détecté",
        "antiraid.triggered_description": "{count} membre(s) expulsé(s) automatiquement après un pic d'arrivées massives (fenêtre : {window}s).",

        "antinuke.status_title": "🛡️ Statut anti-nuke",
        "antinuke.on": "✅ Anti-nuke activé.",
        "antinuke.off": "✅ Anti-nuke désactivé.",
        "antinuke.already_on": "ℹ️ L'anti-nuke est déjà activé.",
        "antinuke.already_off": "ℹ️ L'anti-nuke est déjà désactivé.",
        "antinuke.configured": "✅ Anti-nuke configuré : {threshold} actions / {window}s.",
        "antinuke.triggered_title": "🚨 Tentative de nuke détectée",
        "antinuke.triggered_description": "**{member}** a effectué {count}+ actions destructrices en {window}s. Ses rôles ont été retirés et il/elle a été expulsé(e).",
        "antinuke.bot_join_title": "🤖 Nouveau bot -- validation requise",
        "antinuke.bot_join_description": "**{bot}** (`{bot_id}`) vient de rejoindre ce serveur, ajouté par **{adder}**.\nUn membre du staff avec la permission Expulser doit le valider ou le rejeter ci-dessous.",
        "antinuke.bot_join_unknown_adder": "inconnu (aucune entrée de journal d'audit correspondante)",
        "antinuke.bot_join_resolved_by": "Résolu par",
        "antinuke.bot_join_validated": "✅ Validé par {moderator} -- le bot reste.",
        "antinuke.bot_join_rejected": "❌ Rejeté par {moderator} -- le bot a été expulsé.",
        "antinuke.bot_join_reject_failed": "⚠️ {moderator} a essayé de rejeter ce bot, mais l'expulsion a échoué (permission manquante ou déjà parti).",

        "greet.join.name": "La carte de bienvenue",
        "greet.leave.name": "La carte d'au revoir",
        "greet.panel_title_join": "👋 Carte de bienvenue — nouveaux membres",
        "greet.panel_title_leave": "🚪 Carte d'au revoir — membres qui partent",
        "greet.field_state": "État",
        "greet.field_channel": "Salon",
        "greet.field_title": "Titre",
        "greet.field_message": "Message",
        "greet.field_image": "Image de bannière",
        "greet.system_channel": "Salon système (par défaut)",
        "greet.panel_hint": "Variables : {mention} {name} {server} {count} — la photo de profil du membre est ajoutée automatiquement.",
        "greet.btn_on": "Activer",
        "greet.btn_off": "Désactiver",
        "greet.btn_edit": "Modifier la carte",
        "greet.btn_test": "Aperçu",
        "greet.pick_channel": "Choisis le salon",
        "greet.modal_title": "Modifier la carte",
        "greet.f_title": "Titre",
        "greet.f_message": "Message",
        "greet.f_image": "Image de bannière (lien https, facultatif)",
        "greet.not_yours": "❌ Ce panneau n'est pas à toi. Ouvre le tien avec /welcome setup ou /bye setup.",
        "greet.preview_note": "👁️ Aperçu — voilà ce que verront les membres (avec ta photo de profil).",
        "greet.enabled": "✅ {what} activée.",
        "greet.disabled": "✅ {what} désactivée.",
        "greet.already_on": "ℹ️ {what} est déjà activée.",
        "greet.already_off": "ℹ️ {what} est déjà désactivée.",
        "greet.channel_set": "✅ {what} sera postée dans {channel}.",
        "greet.message_set": "✅ {what} : message mis à jour.",
        "greet.title_set": "✅ {what} : titre mis à jour.",
        "greet.image_set": "✅ {what} : image de bannière mise à jour.",
        "greet.image_cleared": "✅ {what} : image de bannière retirée.",
        "greet.image_invalid": "❌ L'image doit être un lien commençant par https:// (300 caractères max). Mets - pour la retirer.",
        "screening.status_title": "🛡️ Vérification des comptes",
        "screening.action_label": "Action sur les comptes signalés",
        "screening.threshold_label": "Seuil de score",
        "screening.minage_label": "Compte récent en dessous de",
        "screening.timeout_label": "Durée du timeout",
        "screening.on": "✅ Vérification des comptes activée : les nouveaux comptes sont contrôlés à leur arrivée.",
        "screening.off": "✅ Vérification des comptes désactivée.",
        "screening.already_on": "ℹ️ La vérification des comptes est déjà activée.",
        "screening.already_off": "ℹ️ La vérification des comptes est déjà désactivée.",
        "screening.action_set": "✅ Les comptes signalés seront désormais : **{action}**.",
        "screening.action_invalid": "❌ Choisis parmi : `log`, `quarantine`, `timeout`, `kick`.",
        "screening.threshold_set": "✅ Les comptes dont le score atteint **{value}** seront signalés.",
        "screening.minage_set": "✅ Les comptes de moins de **{value}** jour(s) comptent comme récents.",
        "screening.timeout_set": "✅ Les comptes signalés seront mis en timeout **{value}** minute(s) (quand l'action est `timeout`).",
        "screening.flag_title": "🚩 Nouveau compte suspect",
        "screening.flag_description": "{member} (`{id}`) est arrivé avec un score de suspicion de **{score}** (seuil **{threshold}**).\n{reasons}\n**Action :** {action}",
        "screening.check_title": "🔍 Vérification du compte : {member}",
        "screening.check_description": "Score : **{score}** (seuil **{threshold}**) -- {verdict}\n{reasons}",
        "screening.verdict_ok": "rien d'inquiétant",
        "screening.verdict_flag": "serait signalé",
        "screening.reasons_none": "Aucun signal suspect.",
        "screening.reason_age_day": "• Compte créé il y a moins de 24 h (+3)",
        "screening.reason_age_young": "• Compte de moins de {days} jour(s) (+2)",
        "screening.reason_avatar": "• Pas de photo de profil (avatar par défaut) (+2)",
        "screening.reason_banner": "• Pas de bannière de profil (+1)",
        "screening.reason_name": "• Pseudo terminé par 4 chiffres ou plus, typique des comptes générés (+1)",
        "screening.reason_burst": "• Plusieurs comptes sont arrivés dans la dernière minute (+{points})",
        "screening.action_log": "journalisé seulement",
        "screening.action_timeout": "mis en timeout {minutes} min",
        "screening.action_kick": "expulsé",
        "screening.action_failed": "impossible à appliquer (permission manquante ou rôle trop haut)",
        "screening.action_quarantine": "placé en quarantaine",
        "screening.quarantine_label": "Rôle de quarantaine",
        "screening.quarantine_set": "✅ Les comptes signalés reçoivent {role} quand l'action est `quarantine`. Libère-les avec `!screening release @membre`.",
        "screening.quarantine_off": "✅ Plus de rôle de quarantaine : l'action `quarantine` indiquera qu'elle n'a pas pu s'appliquer.",
        "screening.release_done": "✅ {member} a été libéré de la quarantaine.",
        "screening.release_none": "ℹ️ {member} n'est pas en quarantaine.",
        "key.channel_only": "❌ Utilise cette commande dans le salon #{channel}.",
        "key.slow": "⏳ Doucement, réessaie dans un instant.",
        "aibuild.usage": "ℹ️ Dis-moi quoi faire, par exemple `/aibuild request:range tous les salons dans des catégories adaptées` ou `un espace support en anglais avec un salon d'aide public, un salon staff privé et un rôle Support Helper`.",
        "aibuild.not_configured": "❌ L'IA n'est pas configurée : la variable `GEMINI_API_KEY` manque sur l'hébergeur.",
        "aibuild.bot_perms": "❌ Il me faut les permissions Gérer les salons et Gérer les rôles.",
        "aibuild.busy": "⏳ Une construction est déjà en cours, ou tu as demandé trop vite. Patiente un instant.",
        "aibuild.failed": "❌ L'IA n'a pas produit de plan utilisable. Réessaie, ou sois plus précis.",
        "aibuild.nothing": "ℹ️ Rien de nouveau à créer : tout ce que contient le plan existe déjà.",
        "aibuild.too_many": "❌ Ça dépasserait la limite de Discord pour ce serveur ({what}).",
        "aibuild.preview_title": "🧱 Plan du serveur : rien n'est créé pour l'instant",
        "aibuild.preview_footer": "Rôles {roles} · Catégories {categories} · Salons {channels} · Déplacements {moves} · Renommages {renames} · Rien n'est supprimé et aucune permission de l'existant n'est modifiée.",
        "aibuild.roles_header": "Rôles ({count}) :",
        "aibuild.existing": "existe déjà",
        "aibuild.notes": "Remarques",
        "aibuild.warn_limit": "• Réduit : {max} {what} au maximum.",
        "aibuild.warn_perms": "• {name} : les pouvoirs au-delà des permissions de base d'un membre ont été retirés.",
        "aibuild.warn_unknown_role": "• Une restriction sur le rôle “{name}” a été ignorée (ce rôle n'existe pas).",
        "aibuild.confirm": "Créer",
        "aibuild.cancel": "Annuler",
        "aibuild.not_yours": "❌ Seul l'admin qui a fait la demande peut utiliser ces boutons.",
        "aibuild.running": "⏳ Création en cours... environ une minute.",
        "aibuild.cancelled": "✖️ Annulé, rien n'a été créé.",
        "aibuild.done": "✅ Terminé : {roles} rôle(s), {categories} catégorie(s) et {channels} salon(s) créés · {moved} déplacé(s) · {renamed} renommé(s).{failed}\nTu as changé d'avis ? `/aiundo` annule tout (pendant 24 h).",
        "aibuild.failed_items": "\n⚠️ Impossible de créer : {names}",
        "aibuild.log_title": "🧱 Structure du serveur construite par l'IA",
        "aibuild.moves_header": "Déplacements ({count}) :",
        "aibuild.renames_header": "Renommages ({count}) :",
        "aibuild.order_header": "Ordre des catégories :",
        "aibuild.warn_unknown_channel": "• Un élément inexistant a été ignoré ({id}).",
        "aibuild.warn_unknown_category": "• Un déplacement vers une catégorie inconnue a été ignoré : “{name}”.",
        "aiundo.none": "ℹ️ Rien à annuler (aucun changement de l'IA dans les dernières 24 h).",
        "aiundo.preview_title": "↩️ Annuler le dernier changement de l'IA ?",
        "aiundo.preview": "Cela remet **{moved}** salon(s) à leur place, rétablit **{renamed}** nom(s){order}, et supprime les **{created}** élément(s) créés par l'IA : seulement ceux qui sont encore vides (un salon contenant des messages est conservé).",
        "aiundo.order": " et l'ordre des catégories",
        "aiundo.confirm": "Annuler le changement",
        "aiundo.cancel": "Garder",
        "aiundo.running": "⏳ Annulation en cours...",
        "aiundo.cancelled": "✖️ Laissé tel quel.",
        "aiundo.done": "↩️ Annulé : {moved} remis en place, {renamed} nom(s) rétabli(s), {deleted} supprimé(s).{kept}{failed}",
        "aiundo.kept": "\nConservés (non vides) : {names}",
        "aiundo.failed": "\n⚠️ Impossible d'annuler : {names}",
        "aiundo.log_title": "↩️ Changement de l'IA annulé",
        "cmd.aiundo": "Annule le dernier changement fait par l'IA du serveur (dans les 24 h)",
        "cmd.aibuild": "Laisse l'IA planifier rôles, catégories et salons (tu confirmes d'abord)",
        "key.starting": "⏳ Le système de clés démarre. Réessaie dans environ une minute.",
        "key.dm_note": "📨 Une copie t'a aussi été envoyée en message privé.",
        "key.replace_confirm": "ℹ️ Tu as déjà une clé pour **{name}** (valable jusqu'au {expires}). Si tu l'as perdue, appuie sur le bouton : tu reçois une nouvelle clé et l'ancienne s'arrête de marcher (1 fois par semaine, 3 par mois).",
        "key.replace_button": "Nouvelle clé",
        "keyadmin.usage": "ℹ️ `!keyadmin info|revoke|ban|unban @membre` · `!keyadmin stats`",
        "key.usage": "ℹ️ Tape `/key pseudo:<ton pseudo Roblox>` pour obtenir ta clé, ou `/key action:reset` pour la remplacer.",
        "key.have_key": "ℹ️ Tu as déjà une clé (liée à **{name}**, valable jusqu'au {expires}). Utilise `/key action:reset` pour la remplacer.",
        "key.banned": "🚫 Tu ne peux pas obtenir de clé. Contacte le staff.",
        "key.admin_revoked": "🚫 Ta clé a été révoquée par le staff. Contacte-le pour en obtenir une nouvelle.",
        "key.bad_name": "❌ Ça ne ressemble pas à un pseudo Roblox (3 à 20 lettres, chiffres ou underscore).",
        "key.not_found": "❌ Je ne trouve aucun joueur Roblox nommé **{name}**.",
        "key.roblox_taken": "❌ Ce compte Roblox a déjà une clé sur un autre compte Discord.",
        "key.linked_other": "❌ Ton compte Discord est déjà lié à un autre compte Roblox. Contacte le staff pour le changer.",
        "key.roblox_unavailable": "⚠️ Roblox ne répond pas pour le moment. Réessaie dans une minute.",
        "key.step_code": "🔐 **Prouve que c'est ton compte.** Colle ce code n'importe où dans la *Description* (À propos) du profil Roblox **{name}** :\n```{code}```\nEnregistre, puis appuie sur le bouton ci-dessous (ou refais `/key`). Le code est valable {minutes} min et tu pourras l'enlever ensuite.",
        "key.button": "✅ J'ai mis le code",
        "key.code_missing": "❌ Je ne vois pas encore le code dans la description de **{name}**. Ajoute `{code}` dans la section À propos de ton profil, enregistre, attends quelques secondes, puis appuie de nouveau sur le bouton.",
        "key.pending_expired": "⏳ Cette demande a expiré. Refais `/key`.",
        "key.not_yours": "❌ Ce bouton n'est pas le tien.",
        "key.review": "🕓 Ton compte doit être vérifié rapidement par le staff avant d'obtenir une clé. Il a été prévenu.",
        "key.title": "🔑 Ta clé de script",
        "key.description": "Clé pour **{name}**, valable jusqu'au {expires}.\n\n**1.** Copie la clé du message juste en dessous (appui long → Copier le texte).\n**2.** Colle-la dans la fenêtre du script.\n\nElle ne marche que pour ce compte Roblox : ne la partage pas. Perdue ? Refais `/key` (1 fois par semaine).",
        "key.sent_dm": "✅ Je t'ai envoyé ta clé en message privé.",
        "key.dm_closed": "⚠️ Tes MP sont fermés, voici donc ta clé (toi seul vois ce message) :",
        "key.no_key": "ℹ️ Tu n'as pas encore de clé. Fais `/key pseudo:<ton pseudo Roblox>`.",
        "key.reset_too_soon": "⏳ Tu as déjà reçu une nouvelle clé cette semaine. Prochaine possible {when}.",
        "key.reset_quota": "⏳ Tu as utilisé tes 3 nouvelles clés du mois. Prochaine possible {when}.",
        "key.need_member": "❌ Choisis le membre avec l'option `member`.",
        "key.revoked_ok": "✅ La clé de {member} a été révoquée. Il ne peut pas en obtenir une nouvelle seul.",
        "key.revoked_none": "ℹ️ {member} n'a pas de clé.",
        "key.ban_ok": "✅ {member} est banni du système de clés (son compte Roblox aussi, s'il avait une clé).",
        "key.unban_ok": "✅ {member} n'est plus banni du système de clés.",
        "key.unban_none": "ℹ️ {member} n'était pas banni.",
        "key.info_title": "🔑 Clé de {member}",
        "key.info_description": "Roblox : **{name}** (`{rid}`)\nStatut : **{status}**\nCréée : {created}\nExpire : {expires}\nRemplacements utilisés (30 jours) : {resets}/3\nBanni : {banned}",
        "key.status_active": "active",
        "key.status_expired": "expirée",
        "key.status_revoked": "révoquée",
        "key.status_none": "aucune clé",
        "key.yes": "oui",
        "key.stats_title": "📊 Système de clés",
        "key.stats_description": "Clés actives : **{live}** · comptes bannis : **{banned}**\nVérifications par script depuis le dernier redémarrage :\n{lines}",
        "key.stats_none": "aucune vérification pour l'instant",
        "key.no": "non",
        "keysetup.guide_title": "🔑 Obtiens ta clé de script",
        "keysetup.guide": "**1.** Tu es dans le serveur : c'est fait.\n**2.** Dans ce salon, tape `/key user:<ton pseudo Roblox>`.\n**3.** Copie la clé que je t'envoie et colle-la dans la fenêtre du script.",
        "keysetup.done": "✅ Le salon {channel} est prêt (nom : `#{name}`).\nLien d'invitation permanent : {invite}",
        "keysetup.failed": "❌ Je n'ai pas pu le mettre en place (il me faut les permissions Gérer les salons et Créer une invitation).",
        "cmd.key": "Obtiens ta clé de script : /key user:<pseudo Roblox> dans le salon #key",
        "cmd.keysetup": "Crée le salon #key avec son guide et un lien d'invitation permanent",
        "screening.role_label": "Rôle vérifié",
        "screening.role_set": "✅ Les membres qui passent la vérification reçoivent {role}.",
        "screening.role_off": "✅ La vérification ne donne plus de rôle.",
        "verify.panel_title": "✅ Vérification",
        "verify.panel_description": "Clique sur **Vérifier** pour confirmer que tu es un vrai membre. Discord t'affiche sa propre page d'autorisation, qui demande seulement de voir ton pseudo, ta photo de profil et ta bannière. Rien d'autre n'est demandé, je ne vois jamais ton mot de passe, et l'autorisation est retirée dès que la vérification est faite.",
        "verify.button": "Vérifier",
        "verify.not_configured": "❌ La vérification n'est pas encore configurée. Le propriétaire du bot doit ajouter la variable `DISCORD_CLIENT_SECRET` sur l'hébergeur et la redirection `{redirect}` dans le Developer Portal Discord (OAuth2 → Redirects).",
        "verify.panel_posted": "✅ Panneau de vérification publié.",
        "verify.role_failed_title": "⚠️ Rôle de vérification",
        "verify.role_failed": "{member} a passé la vérification mais je n'ai pas pu lui donner {role} (vérifie mes permissions et que mon rôle est au-dessus).",
        "cmd.verify": "Publie le panneau de vérification (admins)",
        "cmd.screening": "Configure la vérification des comptes des nouveaux membres",
        "cmd.screen": "Vérifie à quel point le compte d'un membre paraît suspect",

        "words.list_title": "📝 Mots interdits ({count})",
        "words.list_empty": "Aucun mot interdit configuré.",
        "words.added": "✅ **{word}** ajouté à la liste des mots interdits.",
        "words.already_exists": "❌ **{word}** est déjà interdit.",
        "words.removed": "✅ **{word}** retiré de la liste des mots interdits.",
        "words.not_found": "❌ **{word}** n'est pas dans la liste des mots interdits.",

        "role.created": "✅ Rôle {role} créé.",
        "channel.created": "✅ Salon {channel} créé.",
        "logchannel.set": "✅ Salon de logs de sécurité défini sur {channel}.",
        "modlog.by": "Action par {name}",

        "logs.title": "📋 Statut des logs",
        "logs.channel_set": "✅ {channel} -- tout ce qui suit y est envoyé.",
        "logs.channel_unset": "❌ Non configuré -- la plupart des événements ci-dessous ne seront enregistrés nulle part tant que tu n'exécutes pas `!logs #salon`. Les alertes anti-raid/anti-nuke retombent sur le salon système du serveur en attendant.",
        "logs.channel_field": "Salon de logs",
        "logs.moderation_field": "🛡️ Modération",
        "logs.moderation_value": "kick, ban, mute (timeout), warn, effacement des avertissements",
        "logs.automod_field": "🤖 Automod",
        "logs.automod_value": "Message supprimé car contenant un mot interdit (`!words`)",
        "logs.antiraid_field": "🚨 Anti-raid",
        "logs.antiraid_value": "Pic d'arrivées massives détecté -- membres expulsés automatiquement",
        "logs.antinuke_field": "💥 Anti-nuke",
        "logs.antinuke_value": "Actions destructrices en masse détectées -- rôles retirés, membre expulsé",
        "logs.antipub_field": "📢 Anti-pub",
        "logs.antipub_value": "Publicité/spam détecté -- sanction appliquée selon ta config `!antipub`",
        "logs.set_note": "Donne un salon pour le changer : `!logs #salon` ou `/logs channel:#salon`.",

        "cmd.autoremind": "Configure un message de rappel envoyé automatiquement et régulièrement dans un salon",
        "autoremind.post_title": "📌 Rappel",
        "autoremind.invalid_interval": "❌ L'intervalle doit être supérieur à 0 et d'au plus 720 heures (30 jours).",
        "autoremind.missing_message": "❌ Il faut aussi donner le texte du rappel.",
        "autoremind.set": "✅ Rappel automatique configuré : toutes les {hours}h dans {channel}.",
        "autoremind.stopped": "✅ Rappel automatique arrêté.",
        "autoremind.not_configured": "❌ Aucun rappel automatique configuré. Utilise `!autoremind set #salon <heures> <message>`.",
        "autoremind.paused": "⏸️ Rappel automatique mis en pause. Utilise `!autoremind unpause` pour le reprendre exactement où il en était, pas besoin de tout reconfigurer.",
        "autoremind.unpaused": "▶️ Rappel automatique repris.",
        "autoremind.already_paused": "❌ Le rappel automatique est déjà en pause.",
        "autoremind.not_paused": "❌ Le rappel automatique n'est pas en pause.",
        "autoremind.status_title": "📌 Statut du rappel automatique",
        "autoremind.status_channel": "Salon",
        "autoremind.status_interval": "Se répète toutes les",
        "autoremind.status_message": "Message",
        "autoremind.status_next": "Prochain envoi (approx.)",
        "autoremind.status_paused": "Statut",
        "autoremind.status_paused_value": "⏸️ En pause",
        "autoremind.status_running_value": "▶️ Actif",

        "warn.title": "⚠️ Membre averti",
        "warn.added": "**{member}** a été averti.\n**Raison :** {reason}\n**Total des avertissements :** {count}",
        "warn.autoban_title": "🔨 Bannissement automatique",
        "warn.autoban_description": "**{member}** a été banni automatiquement après avoir atteint **{count}** avertissements.",
        "warn.list_title": "⚠️ Avertissements de {member}",
        "warn.list_empty": "Aucun avertissement.",
        "warn.cleared": "✅ Avertissements effacés pour **{member}**.",
        "warn.cleared_title": "🧹 Avertissements effacés",

        "lock.locked": "🔒 Salon verrouillé.",
        "lock.unlocked": "🔓 Salon déverrouillé.",
        "slowmode.set": "✅ Mode lent défini sur {seconds}s.",
        "slowmode.off": "✅ Mode lent désactivé.",

        "cmd.yslem_about": "Aperçu interactif du bot (IA, économie, modération, admin)",

        "cmd.cmdaccess": "Restreint une commande à des rôles précis (admin du bot uniquement)",
        "cmdaccess.allowed": "✅ {role} peut maintenant utiliser `{command}`. Désormais, seuls les admins du bot et les rôles explicitement autorisés peuvent l'utiliser.",
        "cmdaccess.not_allowed": "❌ {role} n'avait pas d'accès explicite à `{command}`.",
        "cmdaccess.removed": "✅ {role} ne peut plus utiliser `{command}` (sauf s'il est admin du bot).",
        "cmdaccess.reset": "✅ `{command}` n'est plus restreinte — retour aux règles d'accès par défaut.",
        "cmdaccess.list_title": "🔐 Restrictions d'accès aux commandes",
        "cmdaccess.list_empty": "Aucune commande n'est actuellement restreinte. Toutes utilisent leurs règles d'accès par défaut.",

        "ticket.cannot_claim": "❌ Tu dois être admin du bot ou avoir la permission Gérer les salons pour prendre en charge un ticket.",
        "ticket.claimed_label": "Pris en charge par {user}",
        "ticket.claimed_announce": "🙋 Ce ticket a été pris en charge par {mention}.",
        "ticket.claim_button": "Prendre en charge",
        "ticket.no_tickets": "❌ Aucun salon de ticket ouvert.",
        "ticket.staffroles_reset": "🔄 Rôles staff réinitialisés, nouveaux rôles staff du ticket : {roles}.",
        "ticket.bulk_closing": "🔒 Fermeture de {count} ticket(s)...",
        "cmd.closetickets": "Ferme plusieurs/tous les tickets ouverts d'un coup",

        "payment.status_title": "💳 Configuration des infos de paiement",
        "payment.not_set": "Non défini",
        "payment.paypal_set": "✅ Infos PayPal mises à jour.",
        "payment.ltc_set": "✅ Adresse LTC mise à jour.",
        "payment.btc_set": "✅ Adresse BTC mise à jour.",
        "payment.roblox_set": "✅ Pseudo Roblox mis à jour.",
        "payment.set_bulk": "✅ Mis à jour : {fields}.",
        "payment.set_bulk_for": "✅ Mis à jour pour {user} : {fields}.",
        "payment.not_configured": "❌ Aucune info de paiement n'a encore été configurée.",
        "payment.clear_invalid_field": "❌ Champ inconnu. Utilise `paypal`, `ltc`, `btc`, `roblox`, ou `all`.",
        "payment.clear_confirm_title": "⚠️ Supprimer l'info de paiement ?",
        "payment.clear_confirm_description": "Ça va supprimer **{field}** de tes infos de paiement (`!mypayment`). Confirmer ?",
        "payment.clear_cancelled_title": "❌ Annulé",
        "payment.clear_success_title": "✅ Supprimé",
        "payment.clear_success_description": "**{field}** a été retiré de tes infos de paiement.",
        "payment.title": "💳 Informations de paiement",
        "payment.button": "Infos paiement",
        "payment.select_set_placeholder": "Configurer un champ de paiement...",
        "payment.select_clear_placeholder": "Supprimer un ou plusieurs champs...",
        "payment.field_set": "✅ {field} mis à jour.",
        "cmd.payment": "Gère les infos PayPal/LTC/BTC/Roblox d'un membre du staff (configure ou supprime des champs de façon interactive) -- toi par défaut",
        "cmd.setpaypalchannel": "Configure le salon où les notifications de paiement PayPal (IPN) sont postées",
        "paypal.status_title": "💰 Notifications de paiement PayPal",
        "paypal.channel_set": "✅ Les notifications de paiement PayPal seront postées dans {channel}.",
        "paypal.channel_unset": "❌ Aucun salon configuré. Utilise `!setpaypalchannel #salon`.",
        "paypal.setup_note": (
            "Ça ne reçoit des notifications que pour les comptes PayPal qui ont activé l'IPN. "
            "Sur PayPal (paypal.com), va dans Paramètres du compte -> Notifications -> "
            "Notifications de paiement instantané -> Mettre à jour, active l'IPN, et mets comme "
            "URL de notification :\n"
            "`https://discord-bot-0fbs.onrender.com/paypal-ipn`\n"
            "Fais ça pour chaque compte PayPal qui doit notifier ici (CHR, ALN, Yslem, etc.)."
        ),
        "paypal.ipn_title": "💰 Paiement PayPal reçu",
        "paypal.ipn_amount": "Montant",
        "paypal.ipn_from": "De la part de",
        "paypal.ipn_owner": "Reçu par",
        "cmd.setcryptochannel": "Configure le salon où les notifications de paiement BTC/LTC on-chain sont postées",
        "cmd.setpaymentchannels": "Configure les salons où sont postées les notifications de paiement PayPal (IPN) et BTC/LTC on-chain",
        "crypto.status_title": "🪙 Notifications de paiement crypto",
        "crypto.channel_set": "✅ Les notifications de paiement BTC/LTC seront postées dans {channel}.",
        "crypto.channel_unset": "❌ Aucun salon configuré. Utilise `!setcryptochannel #salon`.",
        "crypto.watched_addresses": "Surveillées",
        "crypto.notify_title": "🪙 Paiement crypto reçu",
        "crypto.notify_amount": "Montant",
        "crypto.notify_address": "Adresse",
        "crypto.notify_status": "Statut",
        "crypto.status_confirmed": "✅ Confirmé",
        "crypto.status_pending": "⏳ En attente (non confirmé)",
        "crypto.confirm_field": "Confirmation",
        "crypto.confirmed_yes": "✅ Paiement confirmé reçu par {user}.",
        "crypto.confirmed_no": "❌ Signalé comme NON reçu par {user}.",
        "cmd.setpayment": "Configure les infos PayPal/LTC/BTC/Roblox affichées sur le panneau de tickets",
        "cmd.mypayment": "Configure tes propres infos PayPal/LTC/BTC/Roblox, affichées à un client à la place de celles du serveur quand tu prends en charge son ticket",

        "economy.balance_title": "💰 Solde de {user}",
        "economy.balance_amount": "**{amount}** pièces",
        "economy.daily_cooldown": "⏳ Tu as déjà récupéré tes pièces du jour. Réessaie dans {hours}h {minutes}min.",
        "economy.daily_claimed": "✅ Tu as récupéré **{amount}** pièces ! Nouveau solde : **{total}**.",
        "economy.pay_self": "❌ Tu ne peux pas te payer toi-même.",
        "economy.pay_bot": "❌ Tu ne peux pas payer un bot.",
        "economy.pay_invalid": "❌ Le montant doit être positif.",
        "economy.pay_insufficient": "❌ Tu n'as pas assez de pièces.",
        "economy.pay_success": "✅ Tu as envoyé **{amount}** pièces à {member}.",
        "economy.leaderboard_title": "🏆 Classement des pièces",
        "economy.leaderboard_empty": "Personne n'a encore de pièces.",
        "economy.admin_added": "✅ **{amount}** pièces ajoutées à {member}.",
        "economy.admin_removed": "✅ **{amount}** pièces retirées à {member}.",
        "cmd.balance": "Affiche le solde de pièces d'un membre",
        "cmd.daily": "Récupère tes pièces quotidiennes",
        "cmd.pay": "Donne une partie de tes pièces à un autre membre",
        "cmd.leaderboard": "Affiche le classement des pièces du serveur",
        "cmd.addcoins": "Ajoute des pièces au solde d'un membre (admin du bot uniquement)",
        "cmd.removecoins": "Retire des pièces au solde d'un membre (admin du bot uniquement)",

        "yslemsay.sent": "✅ Message envoyé.",
        "yslemsay.sent_in": "✅ Message envoyé dans {channel}.",
        "say.sent": "✅ Message envoyé.",
        "say.sent_in": "✅ Message envoyé dans {channel}.",
        "poll.posted": "✅ Sondage publié.",
        "poll.posted_in": "✅ Sondage publié dans {channel}.",
        "ticket.panel_posted": "✅ Panneau de tickets publié.",
        "ticket.panel_posted_in": "✅ Panneau de tickets publié dans {channel}.",
        "cmd.yslemsay": "Poste un message en tant qu'Yslem via un webhook (sans tag bot)",

        "ticket.limit_reached": "❌ Tu as déjà {count} ticket(s) ouvert(s), le maximum autorisé ici. Ferme-en un avant d'en ouvrir un autre.",
        "ticket.category_field": "Catégorie",
        "ticket.price_field": "Prix",
        "ticket.methods_field": "Moyens de paiement",
        "ticket.prices_title": "💰 Prix & moyens de paiement",
        "ticket.category_placeholder": "Choisis une catégorie de ticket...",
        "ticket.choose_category": "Choisis une catégorie pour ton ticket :",
        "ticket.log_closed_title": "🔒 Ticket fermé",
        "ticket.log_closed_description": "**Salon :** #{channel}\n**Ouvert par :** {opener}\n**Fermé par :** {closed_by}",
        "ticket.reason_auto": "Automatiquement",
        "ticket.reason_panel": "le panel admin",
        "ticket.closing_panel": "Ticket fermé depuis le panel admin. Suppression dans 5 secondes.",
        "ticket.reason_left": "le créateur a quitté le serveur",
        "ticket.reason_inactivity": "inactivité",
        "ticket.pay_button": "Paiement",
        "ticket.not_a_ticket": "❌ Ce salon n'est pas un ticket ouvert.",
        "ticket.staff_only": "❌ Réservé au staff des tickets.",
        "ticket.already_claimed": "❌ Ce ticket est déjà pris en charge par {user}.",
        "ticket.already_yours": "ℹ️ Tu t'occupes déjà de ce ticket.",
        "ticket.not_claimed": "ℹ️ Personne n'a pris ce ticket en charge.",
        "ticket.released_announce": "↩️ {mention} a libéré ce ticket — un autre membre du staff peut le prendre.",
        "ticket.done": "✅ C'est fait.",
        "ticket.create_failed": "❌ Impossible de créer le ticket pour l'instant. Réessaie dans un instant.",
        "ticket.pay_wait_staff": "⏳ Un membre du staff doit d'abord prendre le ticket — les infos de paiement arrivent juste après.",
        "ticket.close_modal_title": "Fermer ce ticket",
        "ticket.close_reason_label": "Raison (facultatif)",
        "ticket.close_reason_placeholder": "ex. commande livrée, question résolue…",
        "ticket.log_reason": "Raison",
        "ticket.log_number": "Ticket",
        "ticket.log_messages": "Messages",
        "ticket.log_handled_by": "Pris en charge par",
        "ticket.log_opened_title": "🎫 Ticket ouvert",
        "ticket.log_opened_description": "**Ticket :** #{number} — {channel}\n**Ouvert par :** {opener}\n**Catégorie :** {category}",
        "ticket.dm_closed": "🎫 Ton ticket **#{number}** sur **{server}** est fermé. Voici une copie de la conversation. Comment était le support ?",
        "ticket.rating_thanks": "✅ Merci pour ton avis !",
        "ticket.rating_log_title": "⭐ Note du ticket",
        "ticket.rating_log_description": "**Ticket :** #{number}\n**De :** {user}\n**Note :** {stars}/5\n**Pris en charge par :** {staff}",
        "ticket.member_added": "➕ {user} a été ajouté au ticket par {by}.",
        "ticket.member_removed": "➖ {user} a été retiré du ticket par {by}.",
        "ticket.cant_remove_opener": "❌ Tu ne peux pas retirer la personne qui a ouvert le ticket.",
        "ticket.no_bots": "❌ Ça ne marche pas sur les bots.",
        "ticket.bad_name": "❌ Nom invalide.",
        "ticket.renamed": "✅ Renommé en `{name}`.",
        "ticket.rename_limited": "⏳ Discord limite les renommages (2 toutes les 10 minutes). Réessaie plus tard.",
        "ticket.transcript_ready": "📄 Voici la transcription.",
        "ticket.list_title": "🎫 Tickets ouverts",
        "ticket.list_more": "…et {count} de plus",
        "ticket.unclaimed": "non pris",
        "ticket.setup_summary": "✅ Panneau de tickets publié dans {panel}.\n📁 Les tickets sont créés sous **{category}** (privé).\n📝 Logs et transcriptions dans {logs} (staff uniquement).\n👥 Staff qui voit les tickets : {staff}\nRien d'autre à configurer — tout se règle avec `/ticket config`.",
        "payinfo.src_everywhere": "tous les serveurs",
        "payinfo.src_server": "ce serveur",
        "payinfo.src_staff": "staff",
        "payinfo.owner_only": "❌ Seul le propriétaire du bot peut définir les infos valables dans tous les serveurs. Utilise `scope: me` ou `scope: server`.",
        "payinfo.staff_only": "❌ Réservé au staff des tickets.",
        "payinfo.saved_me": "✅ Enregistré pour toi ({fields}) — ça te suit dans tous les serveurs.",
        "payinfo.saved_server": "✅ Enregistré comme défaut de ce serveur ({fields}).",
        "payinfo.saved_everywhere": "✅ Enregistré pour tous les serveurs ({fields}).",
        "payinfo.auto_claimed": "🙋 Ce ticket t'a été attribué.",
        "payinfo.nothing_set": "❌ Pas encore d'infos de paiement. Mets-les ici : `/payinfo paypal:toi@mail.com ltc:L… btc:bc1… roblox:pseudo` (ajoute `scope:everywhere` pour tous les serveurs).",
        "payinfo.nothing_set_customer": "❌ Les infos de paiement ne sont pas encore disponibles — demande à un membre du staff.",
        "ticket.leave_close_title": "👋 Le créateur du ticket est parti",
        "ticket.leave_close_description": "{member} a quitté le serveur. Ce ticket va être fermé automatiquement.",
        "ticket.leave_notify_title": "👋 Le créateur du ticket a quitté le serveur",
        "ticket.leave_notify_description": "{member} a quitté le serveur. Le staff voudra peut-être suivre ce ticket.",
        "ticket.inactivity_warn_title": "⏳ Avertissement d'inactivité",
        "ticket.inactivity_warn_description": "{mention}, aucune réponse dans ce ticket depuis {hours}h. Il sera fermé automatiquement après {close_hours}h d'inactivité.",
        "ticket.inactivity_mute_warn_suffix": " S'il se ferme sans réponse de ta part, tu seras mute pendant {mute_duration}.",
        "ticket.inactivity_close_title": "🔒 Fermeture pour inactivité",
        "ticket.inactivity_close_description": "{mention} n'a pas répondu dans les {close_hours}h. Ce ticket est fermé automatiquement.",
        "ticket.inactivity_close_muted_suffix": " {mention} a aussi été mute pendant {mute_duration}.",
        "ticket.config_mute": "Mute à la fermeture auto",
        "ticket.mute_set_on": "✅ La fermeture auto pour inactivité mute maintenant le créateur pendant {duration}.",
        "ticket.mute_set_off": "✅ La fermeture auto pour inactivité ne mute plus le créateur.",
        "ticket.mute_invalid": "❌ Option invalide. Utilise `on` ou `off`.",

        "ticket.config_title": "🎫 Configuration du système de tickets",
        "ticket.config_reset": "🔄 Configuration du système de tickets réinitialisée par défaut pour ce serveur.",
        "ticket.config_category": "Catégorie",
        "ticket.config_logchannel": "Salon de logs",
        "ticket.config_maxopen": "Max de tickets ouverts par membre",
        "ticket.config_warnhours": "Avertissement d'inactivité",
        "ticket.config_closehours": "Fermeture auto pour inactivité",
        "ticket.config_leaveaction": "Quand le créateur quitte le serveur",
        "ticket.config_types": "Catégories de tickets",
        "ticket.config_staffroles": "Rôles staff supplémentaires",
        "ticket.disabled": "Désactivé",
        "ticket.not_set": "Non défini",
        "ticket.category_set": "✅ Catégorie de tickets définie sur **{name}**.",
        "ticket.logchannel_set": "✅ Salon de logs des tickets défini sur {channel}.",
        "ticket.logchannel_cleared": "✅ Salon de logs des tickets retiré.",
        "ticket.maxopen_set": "✅ Max de tickets ouverts par membre défini sur {count}.",
        "ticket.inactivity_set": "✅ Paramètres d'inactivité mis à jour : avertissement après {warn}h, fermeture après {close}h (0 = désactivé).",
        "ticket.leaveaction_set": "✅ Action au départ définie sur **{action}**.",
        "ticket.leaveaction_invalid": "❌ Option invalide. Utilise `notify` ou `close`.",
        "ticket.type_added": "✅ Catégorie de ticket **{name}** ajoutée.",
        "ticket.types_added_bulk": "✅ {count} catégories de tickets ajoutées : {names}.",
        "ticket.type_exists": "❌ La catégorie **{name}** existe déjà.",
        "ticket.type_removed": "✅ Catégorie de ticket **{name}** retirée.",
        "ticket.type_not_found": "❌ Catégorie **{name}** introuvable.",
        "ticket.type_last_one": "❌ Il faut garder au moins une catégorie de ticket.",
        "ticket.types_full": "❌ Maximum 25 catégories de tickets atteint.",
        "ticket.staffrole_added": "✅ {role} peut maintenant voir et gérer tous les tickets.",
        "ticket.staffrole_removed": "✅ {role} n'a plus d'accès automatique aux tickets.",
        "cmd.ticketconfig": "Configure le système de tickets (catégorie, salon de logs, inactivité, rôles staff, catégories...)",

        "antipub.status_title": "🚫 Statut anti-pub",
        "antipub.threshold": "Seuil",
        "antipub.sanction": "Sanction",
        "antipub.timeout_minutes": "Durée du timeout",
        "antipub.on": "✅ Anti-pub activé.",
        "antipub.off": "✅ Anti-pub désactivé.",
        "antipub.already_on": "ℹ️ L'anti-pub est déjà activé.",
        "antipub.already_off": "ℹ️ L'anti-pub est déjà désactivé.",
        "antipub.configured": "✅ Anti-pub configuré : seuil {threshold}, sanction `{sanction}`.",
        "antipub.invalid_sanction": "❌ Sanction invalide. Utilise `warn`, `timeout`, `kick` ou `ban`.",
        "antipub.blacklist_title": "📝 Liste noire anti-pub ({count})",
        "antipub.blacklist_added": "✅ **{word}** ajouté à la liste noire anti-pub.",
        "antipub.blacklist_exists": "❌ **{word}** est déjà dans la liste noire.",
        "antipub.blacklist_removed": "✅ **{word}** retiré de la liste noire anti-pub.",
        "antipub.blacklist_not_found": "❌ **{word}** n'est pas dans la liste noire anti-pub.",
        "antipub.whitelist_title": "📝 Liste blanche anti-pub",
        "antipub.whitelist_roles": "Rôles exemptés",
        "antipub.whitelist_channels": "Salons exemptés",
        "antipub.whitelist_role_added": "✅ {role} est maintenant exempté de l'anti-pub.",
        "antipub.whitelist_role_removed": "✅ {role} n'est plus exempté de l'anti-pub.",
        "antipub.whitelist_channel_added": "✅ {channel} est maintenant exempté de l'anti-pub.",
        "antipub.whitelist_channel_removed": "✅ {channel} n'est plus exempté de l'anti-pub.",
        "cmd.antipub": "Configure le système anti-publicité",

        "cmd.perm": "Affiche la hiérarchie des permissions du bot",
        "perm.title": "🔐 Hiérarchie des permissions",
        "perm.description": "Comment l'accès est décidé pour chaque commande, du plus ouvert au plus restreint.",
        "perm.public_title": "1️⃣ Public — tout le monde",
        "perm.public_value": "`ping` `hello` `info` `userinfo` `avatar` `servericon` `roleinfo` `afk` `remind` `invite` `uptime` `balance` `daily` `pay` `leaderboard` `8ball` `coinflip` `dice` `poll` `yslem` `words list` `language` `help` `perm`",
        "perm.native_title": "2️⃣ Permission Discord requise",
        "perm.native_value": "**Gérer les messages** : `say` `clear` `warn` `clearwarnings`\n**Expulser des membres** : `kick`\n**Bannir des membres** : `ban`\n**Modérer les membres** : `timeout` `untimeout`\n**Gérer les salons** : `ticketsetup` `lock` `unlock` `slowmode`",
        "perm.botadmin_title": "3️⃣ Admin du bot (`!botadmin`)",
        "perm.botadmin_value": "`addcoins` `removecoins` `yslemsay` `closetickets` `ticket config` `setpayment` `mypayment` `payment` `createrole` `createchannel` `setlogchannel` `logs` `setpaypalchannel` `setcryptochannel` `autoremind` `words add/remove` `cmdaccess` `antiraid` `antinuke` `antipub` `welcome` `screening` `screen`",
        "perm.admin_title": "4️⃣ Administrateur du serveur uniquement",
        "perm.admin_value": "`botadmin` (addrole/removerole/adduser/removeuser) — volontairement plus strict, pour qu'un admin du bot ne puisse pas s'auto-accorder plus de pouvoir.",
        "perm.override_title": "⚙️ Cas particuliers",
        "perm.override_value": "`!cmdaccess allow <commande> @rôle` restreint n'importe quelle commande ci-dessus à des rôles précis.\n`yslem` en particulier : un membre sans le rôle autorisé peut quand même l'utiliser en dépensant **1 pièce** par utilisation.\n`find` est ouvert à tous ; sur le site, chaque téléchargement coûte **1 pièce** sauf pour les membres qui ont le rôle autorisé.",

        "cmd.saveconfig": "Force une sauvegarde immédiate de la config du bot sur Redis (admin du bot uniquement)",
        "saveconfig.no_redis": "❌ Aucune base Redis configurée — rien à sauvegarder, la config ne vit qu'en mémoire pour l'instant.",
        "saveconfig.saved": "✅ Configuration sauvegardée.",

        "cmd.staffapplysetup": "Poste le panneau de candidature staff",
        "cmd.closeapplications": "Ferme plusieurs/toutes les candidatures ouvertes d'un coup",
        "cmd.staffappconfig": "Configure le système de candidature staff (catégorie, salon de logs, rôles recruteurs, délai, rôle attribué...)",
        "staffapp.panel_title": "📋 Rejoindre l'équipe",
        "staffapp.panel_description": "Envie de rejoindre l'équipe ? Clique ci-dessous pour candidater. Tu répondras à quelques questions, puis un salon privé sera créé pour le suivi de ta candidature.",
        "staffapp.apply_button": "Postuler au staff",
        "staffapp.panel_posted": "✅ Panneau de candidature posté.",
        "staffapp.panel_posted_in": "✅ Panneau de candidature posté dans {channel}.",
        "staffapp.already_open": "❌ Tu as déjà une candidature ouverte : {channel}",
        "staffapp.cooldown_active": "❌ Ta dernière candidature a été refusée. Tu pourras repostuler dans {days} jour(s).",
        "staffapp.intro_title": "📋 Candidature staff",
        "staffapp.intro_description": "Merci de vouloir rejoindre l'équipe ! La candidature compte 12 questions en 3 étapes : tes infos générales, puis 6 mises en situation, plus une question facultative. Compte environ 10 minutes -- réponds avec sincérité, c'est ce qu'on regarde le plus.\n\nUne fois envoyée, un salon privé est créé : seuls toi et le propriétaire du serveur le voient.",
        "staffapp.start_button": "Commencer la candidature",
        "staffapp.modal_a_title": "Candidature staff (1/3)",
        "staffapp.q_age_tz": "Âge et fuseau horaire",
        "staffapp.q_age_tz_ph": "Ex. 19 ans, GMT+1",
        "staffapp.q_availability": "Disponibilités par semaine",
        "staffapp.q_availability_ph": "Ex. 10h/semaine, surtout soirs et week-ends",
        "staffapp.q_experience": "Expérience (modération ou autre)",
        "staffapp.q_experience_ph": "Serveurs où tu as été staff, ce que tu y faisais...",
        "staffapp.q_motivation": "Pourquoi rejoindre le staff ?",
        "staffapp.q_motivation_ph": "Sois honnête et précis·e",
        "staffapp.q_strength": "Ta plus grande qualité pour ce rôle",
        "staffapp.q_strength_ph": "Ce qui te distingue des autres candidat·e·s",
        "staffapp.situations_title": "📋 Candidature staff (2/3)",
        "staffapp.situations_description": "Étape 2 ! Ces 5 questions portent sur des situations concrètes. Réponds avec ce que tu ferais vraiment.\n\n1️⃣ Un membre en insulte un autre publiquement.\n2️⃣ Un ami proche à toi enfreint une règle importante du serveur.\n3️⃣ Tu n'es pas d'accord avec la décision d'un autre membre du staff, devant des membres.\n4️⃣ Un client dit avoir payé mais n'a rien reçu, et s'énerve dans le salon.\n5️⃣ Un raid arrive sur le serveur et tu es le seul staff en ligne.\n\nClique sur *Continuer* pour répondre.",
        "staffapp.situations2_title": "📋 Candidature staff (3/3)",
        "staffapp.situations2_description": "Dernière étape ! Encore une situation, puis une question facultative.\n\n6️⃣ Tu vois un autre staff abuser de son pouvoir (ban injuste, favoritisme...).\n7️⃣ (Optionnel) As-tu déjà été staff ailleurs ? Pourquoi es-tu parti·e ?\n\nClique sur *Continuer* pour répondre.",
        "staffapp.modal_c_title": "Candidature staff (3/3)",
        "staffapp.q_sit_raid": "Raid, et tu es le seul staff en ligne",
        "staffapp.q_sit_abuse": "Un staff abuse de son pouvoir",
        "staffapp.recap_situations_title": "🧩 Mises en situation",
        "staffapp.config_private": "Qui voit les candidatures",
        "staffapp.private_on": "🔒 Seulement le/la candidat·e et le propriétaire du bot",
        "staffapp.private_off": "👥 Le/la candidat·e, les rôles recruteurs et les gestionnaires du serveur",
        "staffapp.private_set_on": "✅ Les candidatures sont maintenant visibles seulement par le/la candidat·e et le propriétaire du bot.",
        "staffapp.private_set_off": "✅ Les candidatures sont aussi visibles par les rôles recruteurs et les gestionnaires du serveur.",
        "staffapp.continue_button": "Continuer",
        "staffapp.modal_b_title": "Candidature staff (2/3)",
        "staffapp.q_sit_insult": "Un membre insulte un autre, tu fais quoi ?",
        "staffapp.q_sit_friend": "Un ami enfreint une règle, tu fais quoi ?",
        "staffapp.q_sit_disagree": "Désaccord public avec un autre staff",
        "staffapp.q_sit_payment": "Client dit avoir payé, rien reçu",
        "staffapp.q_prior_staff": "Déjà staff ailleurs ? Pourquoi parti·e ?",
        "staffapp.recap_title": "📋 Nouvelle candidature staff",
        "staffapp.recap_description": "Nouvelle candidature de {mention}. Un membre du recrutement va l'examiner sous peu.",
        "staffapp.channel_topic": "Candidature staff -- {user}",
        "staffapp.created_confirm": "✅ Candidature envoyée : {channel}",
        "staffapp.claim_button": "Prendre en charge",
        "staffapp.accept_button": "Accepter",
        "staffapp.reject_button": "Refuser",
        "staffapp.close_button": "Fermer",
        "staffapp.cannot_claim": "❌ Tu dois être admin du bot ou recruteur pour prendre en charge cette candidature.",
        "staffapp.cannot_decide": "❌ Tu dois être admin du bot ou recruteur pour accepter ou refuser cette candidature.",
        "staffapp.cannot_close": "❌ Tu dois être admin du bot ou recruteur pour fermer cette candidature.",
        "staffapp.already_decided": "❌ Cette candidature a déjà été traitée.",
        "staffapp.claimed_label": "Prise en charge par {user}",
        "staffapp.claimed_announce": "🙋 Cette candidature est maintenant suivie par {mention}.",
        "staffapp.accepted_title": "Candidature acceptée",
        "staffapp.accepted_description": "La candidature de {mention} a été acceptée par {by}. Bienvenue dans l'équipe !",
        "staffapp.role_field": "Rôle",
        "staffapp.role_granted": "{role} attribué.",
        "staffapp.role_grant_failed": "⚠️ Impossible d'attribuer {role} -- permission manquante, ajoute-le manuellement.",
        "staffapp.rejected_title": "Candidature refusée",
        "staffapp.rejected_description": "La candidature de {mention} a été refusée par {by}.",
        "staffapp.reason_field": "Raison",
        "staffapp.reject_modal_title": "Refuser cette candidature",
        "staffapp.reject_reason_label": "Raison (visible par le·la candidat·e, optionnel)",
        "staffapp.reject_reason_ph": "Reste court et constructif",
        "staffapp.closing_title": "Fermeture de la candidature",
        "staffapp.closing_description": "Candidature fermée par {mention}. Elle sera supprimée dans 5 secondes.",
        "staffapp.log_accepted_title": "✅ Candidature acceptée",
        "staffapp.log_accepted_description": "La candidature staff de {applicant} a été acceptée par {by}.",
        "staffapp.log_rejected_title": "❌ Candidature refusée",
        "staffapp.log_rejected_description": "La candidature staff de {applicant} a été refusée par {by}.",
        "staffapp.log_closed_title": "🔒 Candidature fermée",
        "staffapp.log_closed_description": "Le salon de candidature {channel} ({status}) a été fermé par {closed_by}. Candidat·e : {applicant}.",
        "staffapp.status_pending": "en attente",
        "staffapp.status_accepted": "acceptée",
        "staffapp.status_rejected": "refusée",
        "staffapp.no_applications": "Aucun salon de candidature ouvert pour le moment.",
        "staffapp.bulk_closing": "⏳ Fermeture de {count} salon(s) de candidature...",
        "staffapp.config_title": "📋 Configuration des candidatures staff",
        "staffapp.config_category": "Catégorie",
        "staffapp.config_logchannel": "Salon de logs",
        "staffapp.config_role": "Rôle attribué à l'acceptation",
        "staffapp.config_cooldown": "Délai avant nouvelle candidature",
        "staffapp.config_recruiters": "Rôles recruteurs",
        "staffapp.cooldown_value": "{days} jour(s)",
        "staffapp.cooldown_off": "Désactivé",
        "staffapp.config_reset": "✅ Configuration des candidatures staff réinitialisée.",
        "staffapp.category_set": "✅ Les candidatures seront créées sous « {name} ».",
        "staffapp.logchannel_set": "✅ Salon de logs des candidatures défini sur {channel}.",
        "staffapp.logchannel_cleared": "✅ Salon de logs des candidatures effacé.",
        "staffapp.recruiter_added": "✅ {role} peut maintenant examiner les candidatures staff.",
        "staffapp.recruiter_removed": "✅ {role} n'a plus accès aux candidatures staff.",
        "staffapp.recruiters_reset": "✅ Rôles recruteurs réinitialisés à : {roles}",
        "staffapp.cooldown_set": "✅ Délai avant nouvelle candidature défini à {days} jour(s).",
        "staffapp.role_set": "✅ {role} sera attribué automatiquement quand une candidature est acceptée.",
        "staffapp.role_cleared": "✅ Plus aucun rôle ne sera attribué automatiquement.",
        "staffapp.reason_panel": "le panel admin",
        "staffapp.closing_panel": "Candidature fermée depuis le panel admin. Suppression dans 5 secondes.",
    },
    # Spanish, Arabic, and Portuguese only cover the customer-facing ticket
    # lifecycle (panel -> form -> ticket embed -> claim -> close), added
    # specifically for the ticket language picker. Anything else looked up
    # under these languages falls back to English automatically (see t()) --
    # translating the bot's full ~600-string admin/command surface into
    # every language is a much bigger separate undertaking.
    "es": {
        "ticket.panel_title": "🎫 Soporte",
        "ticket.panel_description": "🛠️ **Soporte** — tienes una pregunta o un problema.\n🛒 **Comprar** — quieres comprar algo de la tienda.\nSe abre un ticket privado con el staff.",
        "ticket.support_button": "Soporte",
        "ticket.buy_button": "Comprar",
        "ticket.modal_title_support": "Solicitud de soporte",
        "ticket.q_subject": "Asunto",
        "ticket.q_subject_placeholder": "ej: acceso a un canal, bug, pregunta...",
        "ticket.q_problem": "Describe tu problema",
        "ticket.q_problem_placeholder": "Qué pasa, desde cuándo, qué has probado...",
        "ticket.new_description_support": "¡Bienvenido/a {mention}! Tu solicitud está abajo. Un miembro del staff responderá aquí — ya puedes añadir capturas o detalles.",
        "ticket.pay_not_for_support": "ℹ️ Este es un ticket de soporte: aquí no hay pago. Para comprar, abre un ticket con el botón **Comprar**.",
        "ticket.create_button": "Crear ticket",
        "ticket.choose_category": "Elige una categoría para tu ticket:",
        "ticket.category_placeholder": "Elige una categoría de ticket...",
        "ticket.modal_title": "Abrir un ticket",
        "ticket.q_payment": "¿Método de pago?",
        "ticket.q_payment_placeholder": "PayPal, LTC, BTC, Roblox (garam)...",
        "ticket.q_duration": "¿Por cuánto tiempo? (si aplica)",
        "ticket.q_duration_placeholder": "ej: 1 semana, de por vida, un duelo...",
        "ticket.q_offer": "¿Cuál es tu oferta? (si aplica)",
        "ticket.q_offer_placeholder": "ej: 3EUR, 2 garams...",
        "ticket.limit_reached": "❌ Ya tienes {count} ticket(s) abierto(s), el máximo permitido aquí. Cierra uno antes de abrir otro.",
        "ticket.already_open": "❌ Ya tienes un ticket abierto: {channel}",
        "ticket.no_permission": "❌ Me falta el permiso 'Gestionar canales' para crear un ticket.",
        "ticket.new_title": "🎫 Nuevo ticket",
        "ticket.new_description": "¡Bienvenido/a {mention}! Por favor espera a que un miembro del staff se una a este ticket.",
        "ticket.category_field": "Categoría",
        "ticket.price_field": "Precio",
        "ticket.methods_field": "Métodos de pago",
        "ticket.rules_field": "⚠️ Reglas",
        "ticket.rules_value": (
            "- No compartas contraseñas ni otra información sensible aquí.\n"
            "- Una oferta demasiado baja hará que se cierre el ticket.\n"
            "- Inactivo durante {close_hours}h -> se cierra automáticamente{mute_suffix}.\n"
            "- Solo un Owner (CHR, ALN, Yslem) decide aceptar una oferta o cerrar un ticket."
        ),
        "ticket.rules_mute_suffix": ", y serás muteado/a por {mute_duration}",
        "ticket.created_confirm": "✅ Ticket creado: {channel}",
        "ticket.close_button": "Cerrar ticket",
        "ticket.claim_button": "Reclamar",
        "ticket.cannot_claim": "❌ Necesitas ser admin del bot o tener el permiso Gestionar canales para reclamar un ticket.",
        "ticket.cannot_close": "❌ No puedes cerrar este ticket.",
        "ticket.claimed_label": "Reclamado por {user}",
        "ticket.claimed_announce": "🙋 Este ticket ha sido reclamado por {mention}.",
        "ticket.closing_title": "🔒 Cerrando ticket",
        "ticket.closing_description": "Ticket cerrado por {mention}. Se eliminará en 5 segundos.",
        "ticket.leave_close_title": "👋 El creador del ticket se fue",
        "ticket.leave_close_description": "{member} abandonó el servidor. Este ticket se está cerrando automáticamente.",
        "ticket.leave_notify_title": "👋 El creador del ticket abandonó el servidor",
        "ticket.leave_notify_description": "{member} abandonó el servidor. El staff podría querer revisar este ticket.",
        "ticket.inactivity_warn_title": "⏳ Aviso de inactividad",
        "ticket.inactivity_warn_description": "{mention}, sin respuesta en este ticket desde hace {hours}h. Se cerrará automáticamente tras {close_hours}h de inactividad.",
        "ticket.inactivity_mute_warn_suffix": " Si se cierra sin respuesta de tu parte, serás muteado/a por {mute_duration}.",
        "ticket.inactivity_close_title": "🔒 Cerrando por inactividad",
        "ticket.inactivity_close_description": "{mention} no respondió en {close_hours}h. Este ticket se está cerrando automáticamente.",
        "ticket.inactivity_close_muted_suffix": " {mention} también ha sido muteado/a por {mute_duration}.",
        "payment.title": "💳 Información de pago",
        "payment.not_set": "No definido",
        "payment.not_configured": "❌ Aún no se ha configurado ninguna información de pago.",
        "ticket.claim_payment_instructions": "💳 Aquí tienes la información de pago. Envía el monto acordado y avísanos aquí una vez hecho.",
    },
    "ar": {
        "ticket.panel_title": "🎫 الدعم",
        "ticket.panel_description": "🛠️ **الدعم** — لديك سؤال أو مشكلة.\n🛒 **شراء** — تريد شراء شيء من المتجر.\nسيتم فتح تذكرة خاصة مع الطاقم.",
        "ticket.support_button": "الدعم",
        "ticket.buy_button": "شراء",
        "ticket.modal_title_support": "طلب دعم",
        "ticket.q_subject": "الموضوع",
        "ticket.q_subject_placeholder": "مثال: الوصول إلى قناة، خطأ، سؤال...",
        "ticket.q_problem": "اشرح مشكلتك",
        "ticket.q_problem_placeholder": "ماذا يحدث، منذ متى، وما الذي جربته...",
        "ticket.new_description_support": "مرحبًا {mention}! طلبك أدناه. سيرد عليك أحد أعضاء الطاقم هنا — يمكنك إضافة صور أو تفاصيل الآن.",
        "ticket.pay_not_for_support": "ℹ️ هذه تذكرة دعم: لا يوجد دفع هنا. للشراء، افتح تذكرة بزر **شراء**.",
        "ticket.create_button": "إنشاء تذكرة",
        "ticket.choose_category": "اختر فئة لتذكرتك:",
        "ticket.category_placeholder": "اختر فئة التذكرة...",
        "ticket.modal_title": "فتح تذكرة",
        "ticket.q_payment": "طريقة الدفع؟",
        "ticket.q_payment_placeholder": "PayPal, LTC, BTC, Roblox (garam)...",
        "ticket.q_duration": "لكم من الوقت؟ (إن كان ذلك مناسبًا)",
        "ticket.q_duration_placeholder": "مثال: أسبوع واحد، مدى الحياة، مبارزة واحدة...",
        "ticket.q_offer": "ما هو عرضك؟ (إن كان ذلك مناسبًا)",
        "ticket.q_offer_placeholder": "مثال: 3 يورو، 2 غارام...",
        "ticket.limit_reached": "❌ لديك بالفعل {count} تذكرة (تذاكر) مفتوحة، وهو الحد الأقصى المسموح به هنا. أغلق واحدة قبل فتح أخرى.",
        "ticket.already_open": "❌ لديك بالفعل تذكرة مفتوحة: {channel}",
        "ticket.no_permission": "❌ ينقصني إذن «إدارة القنوات» لإنشاء تذكرة.",
        "ticket.new_title": "🎫 تذكرة جديدة",
        "ticket.new_description": "مرحبًا {mention}! يرجى الانتظار حتى ينضم أحد أعضاء الطاقم إلى هذه التذكرة.",
        "ticket.category_field": "الفئة",
        "ticket.price_field": "السعر",
        "ticket.methods_field": "طرق الدفع",
        "ticket.rules_field": "⚠️ القواعد",
        "ticket.rules_value": (
            "- لا تشارك كلمات المرور أو أي معلومات حساسة أخرى هنا.\n"
            "- العرض المنخفض جدًا سيؤدي إلى إغلاق التذكرة.\n"
            "- عدم النشاط لمدة {close_hours}h -> إغلاق تلقائي{mute_suffix}.\n"
            "- فقط أحد الـOwners (CHR وALN وYslem) يقرر قبول عرض أو إغلاق تذكرة."
        ),
        "ticket.rules_mute_suffix": "، وسيتم كتمك لمدة {mute_duration}",
        "ticket.created_confirm": "✅ تم إنشاء التذكرة: {channel}",
        "ticket.close_button": "إغلاق التذكرة",
        "ticket.claim_button": "تولي التذكرة",
        "ticket.cannot_claim": "❌ يجب أن تكون مسؤول بوت أو لديك صلاحية إدارة القنوات لتولي تذكرة.",
        "ticket.cannot_close": "❌ لا يمكنك إغلاق هذه التذكرة.",
        "ticket.claimed_label": "تم تولّيها بواسطة {user}",
        "ticket.claimed_announce": "🙋 تم تولي هذه التذكرة من قبل {mention}.",
        "ticket.closing_title": "🔒 إغلاق التذكرة",
        "ticket.closing_description": "تم إغلاق التذكرة بواسطة {mention}. سيتم الحذف خلال 5 ثوانٍ.",
        "ticket.leave_close_title": "👋 غادر صاحب التذكرة",
        "ticket.leave_close_description": "غادر {member} السيرفر. سيتم إغلاق هذه التذكرة تلقائيًا.",
        "ticket.leave_notify_title": "👋 غادر صاحب التذكرة السيرفر",
        "ticket.leave_notify_description": "غادر {member} السيرفر. قد يرغب الطاقم بمتابعة هذه التذكرة.",
        "ticket.inactivity_warn_title": "⏳ تحذير عدم النشاط",
        "ticket.inactivity_warn_description": "{mention}، لا يوجد رد في هذه التذكرة منذ {hours}h. سيتم إغلاقها تلقائيًا بعد {close_hours}h من عدم النشاط.",
        "ticket.inactivity_mute_warn_suffix": " إذا أُغلقت دون رد منك، سيتم كتمك لمدة {mute_duration}.",
        "ticket.inactivity_close_title": "🔒 إغلاق بسبب عدم النشاط",
        "ticket.inactivity_close_description": "لم يرد {mention} خلال {close_hours}h. سيتم إغلاق هذه التذكرة تلقائيًا.",
        "ticket.inactivity_close_muted_suffix": " تم أيضًا كتم {mention} لمدة {mute_duration}.",
        "payment.title": "💳 معلومات الدفع",
        "payment.not_set": "غير محدد",
        "payment.not_configured": "❌ لم يتم تكوين أي معلومات دفع بعد.",
        "ticket.claim_payment_instructions": "💳 إليك معلومات الدفع. أرسل المبلغ المتفق عليه، ثم أخبرنا هنا بمجرد الانتهاء.",
    },
    "pt": {
        "ticket.panel_title": "🎫 Suporte",
        "ticket.panel_description": "🛠️ **Suporte** — tens uma pergunta ou um problema.\n🛒 **Comprar** — queres comprar algo da loja.\nUm ticket privado abre com a equipa.",
        "ticket.support_button": "Suporte",
        "ticket.buy_button": "Comprar",
        "ticket.modal_title_support": "Pedido de suporte",
        "ticket.q_subject": "Assunto",
        "ticket.q_subject_placeholder": "ex: acesso a um canal, bug, pergunta...",
        "ticket.q_problem": "Descreve o teu problema",
        "ticket.q_problem_placeholder": "O que acontece, desde quando, o que já tentaste...",
        "ticket.new_description_support": "Bem-vindo(a) {mention}! O teu pedido está abaixo. Um membro da equipa vai responder aqui — já podes juntar capturas ou detalhes.",
        "ticket.pay_not_for_support": "ℹ️ Este é um ticket de suporte: aqui não há pagamento. Para comprar, abre um ticket com o botão **Comprar**.",
        "ticket.create_button": "Criar ticket",
        "ticket.choose_category": "Escolha uma categoria para o seu ticket:",
        "ticket.category_placeholder": "Escolha uma categoria de ticket...",
        "ticket.modal_title": "Abrir um ticket",
        "ticket.q_payment": "Método de pagamento?",
        "ticket.q_payment_placeholder": "PayPal, LTC, BTC, Roblox (garam)...",
        "ticket.q_duration": "Por quanto tempo? (se aplicável)",
        "ticket.q_duration_placeholder": "ex: 1 semana, vitalício, um duelo...",
        "ticket.q_offer": "Qual é a sua oferta? (se aplicável)",
        "ticket.q_offer_placeholder": "ex: 3EUR, 2 garams...",
        "ticket.limit_reached": "❌ Você já tem {count} ticket(s) aberto(s), o máximo permitido aqui. Feche um antes de abrir outro.",
        "ticket.already_open": "❌ Você já tem um ticket aberto: {channel}",
        "ticket.no_permission": "❌ Estou sem a permissão 'Gerenciar canais' para criar um ticket.",
        "ticket.new_title": "🎫 Novo ticket",
        "ticket.new_description": "Bem-vindo(a) {mention}! Aguarde até que um membro da equipe entre neste ticket.",
        "ticket.category_field": "Categoria",
        "ticket.price_field": "Preço",
        "ticket.methods_field": "Métodos de pagamento",
        "ticket.rules_field": "⚠️ Regras",
        "ticket.rules_value": (
            "- Não compartilhe senhas nem outras informações sensíveis aqui.\n"
            "- Uma oferta muito baixa faz o ticket ser fechado.\n"
            "- Inativo por {close_hours}h -> fechado automaticamente{mute_suffix}.\n"
            "- Só um Owner (CHR, ALN, Yslem) decide aceitar uma oferta ou fechar um ticket."
        ),
        "ticket.rules_mute_suffix": ", e você será silenciado(a) por {mute_duration}",
        "ticket.created_confirm": "✅ Ticket criado: {channel}",
        "ticket.close_button": "Fechar ticket",
        "ticket.claim_button": "Assumir",
        "ticket.cannot_claim": "❌ Você precisa ser admin do bot ou ter a permissão Gerenciar canais para assumir um ticket.",
        "ticket.cannot_close": "❌ Você não pode fechar este ticket.",
        "ticket.claimed_label": "Assumido por {user}",
        "ticket.claimed_announce": "🙋 Este ticket foi assumido por {mention}.",
        "ticket.closing_title": "🔒 Fechando ticket",
        "ticket.closing_description": "Ticket fechado por {mention}. Será excluído em 5 segundos.",
        "ticket.leave_close_title": "👋 O criador do ticket saiu",
        "ticket.leave_close_description": "{member} saiu do servidor. Este ticket está sendo fechado automaticamente.",
        "ticket.leave_notify_title": "👋 O criador do ticket saiu do servidor",
        "ticket.leave_notify_description": "{member} saiu do servidor. A equipe pode querer acompanhar este ticket.",
        "ticket.inactivity_warn_title": "⏳ Aviso de inatividade",
        "ticket.inactivity_warn_description": "{mention}, sem resposta neste ticket há {hours}h. Ele será fechado automaticamente após {close_hours}h de inatividade.",
        "ticket.inactivity_mute_warn_suffix": " Se fechar sem resposta sua, você será silenciado(a) por {mute_duration}.",
        "ticket.inactivity_close_title": "🔒 Fechando por inatividade",
        "ticket.inactivity_close_description": "{mention} não respondeu em {close_hours}h. Este ticket está sendo fechado automaticamente.",
        "ticket.inactivity_close_muted_suffix": " {mention} também foi silenciado(a) por {mute_duration}.",
        "payment.title": "💳 Informações de pagamento",
        "payment.not_set": "Não definido",
        "payment.not_configured": "❌ Nenhuma informação de pagamento foi configurada ainda.",
        "ticket.claim_payment_instructions": "💳 Aqui estão as informações de pagamento. Envie o valor combinado e avise aqui assim que estiver feito.",
    },
}

EIGHTBALL = {
    "en": [
        "Yes, absolutely.",
        "It is certain.",
        "Without a doubt.",
        "Probably yes.",
        "Signs point to yes.",
        "Answer unclear, try again.",
        "Ask again later.",
        "Can't predict that right now.",
        "Don't count on it.",
        "My answer is no.",
        "My sources say no.",
        "Outlook not so good.",
        "Very doubtful.",
    ],
    "fr": [
        "Oui, absolument.",
        "C'est certain.",
        "Sans aucun doute.",
        "Probablement oui.",
        "Les signes indiquent que oui.",
        "Réponse floue, réessaie.",
        "Redemande plus tard.",
        "Je ne peux pas prédire ça maintenant.",
        "Ne compte pas dessus.",
        "Ma réponse est non.",
        "Mes sources disent non.",
        "Les perspectives ne sont pas bonnes.",
        "Très douteux.",
    ],
}


def t(uid, key, **kwargs):
    table = STRINGS["en"]
    template = table.get(key, STRINGS[DEFAULT_LANG].get(key, key))
    return template.format(**kwargs) if kwargs else template


def lang_of(uid):
    return "en"


def _other_lang(uid):
    """The language a lang-toggle button switches TO -- the button label
    should show the destination, not the language currently in use."""
    return "en" if lang_of(uid) == "fr" else "fr"


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# max_messages caps discord.py's in-RAM message cache (default 1000). Nothing
# here listens on cached-message events (no on_message_edit/delete, no
# on_reaction_add -- only raw-free handlers), so a large cache is dead weight on
# a 512 MB instance; 200 keeps a small working set. Member cache stays on:
# guild.members / role.members are used by the admin panel and moderation.
bot = commands.Bot(command_prefix=["!", "."], intents=intents, help_command=None,
                   max_messages=200)
bot_start_time = time.time()


async def _load_cogs():
    try:
        await bot.load_extension("yslem_deobf_suite.bot_extension")
        print("[OK] yslem_deobf_suite chargé (/deobf /get /analyse)")
    except Exception as _cog_exc:
        print(f"[WARN] yslem_deobf_suite non chargé : {_cog_exc}")
    try:
        await bot.load_extension("undercover_game")
        print("[OK] undercover_game chargé (/undercover /undercover_annuler)")
    except Exception as _cog_exc:
        print(f"[WARN] undercover_game non chargé : {_cog_exc}")

bot.setup_hook = _load_cogs


def _panel_track(kind, guild=None, user=None, detail=""):
    """Feeds the web admin panel's activity log. Never allowed to break the
    bot flow it is called from (ticket creation, commands...)."""
    try:
        admin_panel.tracker.record(
            kind,
            guild_id=guild.id if guild else None,
            guild_name=guild.name if guild else None,
            user_id=user.id if user else None,
            user_name=getattr(user, "display_name", None) if user else None,
            username=getattr(user, "name", None) if user else None,
            avatar=user.display_avatar.url if user is not None and hasattr(user, "display_avatar") else None,
            detail=detail,
        )
    except Exception as e:
        print(f"[WARN] Admin panel tracking failed: {e}")


def _panel_member(guild, user_id):
    if not user_id:
        return None
    member = guild.get_member(user_id) if guild else None
    return {
        "id": str(user_id),
        "name": member.display_name if member else None,
        "avatar": member.display_avatar.url if member else None,
    }


async def _panel_snapshot():
    """Live bot data for the admin panel. Runs on the bot's event loop.
    Deliberately excludes payment info, tokens and any other secret."""
    tickets_per_guild = {}
    tickets = []
    for (gid, cid), info in list(open_tickets.items()):
        tickets_per_guild[gid] = tickets_per_guild.get(gid, 0) + 1
        guild = bot.get_guild(gid)
        channel = guild.get_channel(cid) if guild else None
        tickets.append({
            "gid": str(gid),
            "cid": str(cid),
            "guild": guild.name if guild else None,
            "channel": channel.name if channel else None,
            "opener": _panel_member(guild, info.get("opener_id")),
            "claimer": _panel_member(guild, info.get("claimed_by")),
            "category": info.get("category") or "",
            "price": info.get("price") or "",
            "payment_method": info.get("payment_method") or "",
            "lang": info.get("customer_lang"),
            "created_at": info.get("created_at"),
            "last_activity": info.get("last_activity"),
            "warn_count": info.get("warn_count", 0),
        })
    applications_per_guild = {}
    applications = []
    for (gid, cid), info in list(staff_applications.items()):
        applications_per_guild[gid] = applications_per_guild.get(gid, 0) + 1
        guild = bot.get_guild(gid)
        channel = guild.get_channel(cid) if guild else None
        applications.append({
            "gid": str(gid),
            "cid": str(cid),
            "guild": guild.name if guild else None,
            "channel": channel.name if channel else None,
            "applicant": _panel_member(guild, info.get("applicant_id")),
            "claimer": _panel_member(guild, info.get("claimed_by")),
            "status": info.get("status") or "pending",
            "created_at": info.get("created_at"),
            "decided_by": _panel_member(guild, info.get("decided_by")),
            "decided_at": info.get("decided_at"),
            "reason": info.get("reason") or "",
            "answers": info.get("answers") or {},
        })
    guilds = []
    for g in bot.guilds:
        me = g.me
        guilds.append({
            "id": str(g.id),
            "name": g.name,
            "icon": g.icon.url if g.icon else None,
            "members": g.member_count or 0,
            "owner": g.owner.display_name if g.owner else None,
            "owner_id": str(g.owner_id) if g.owner_id else None,
            "joined_at": me.joined_at.isoformat() if me and me.joined_at else None,
            "created_at": g.created_at.isoformat(),
            "channels": len(g.channels),
            "roles": len(g.roles),
            "boosts": g.premium_subscription_count or 0,
            "open_tickets": tickets_per_guild.get(g.id, 0),
            "open_applications": applications_per_guild.get(g.id, 0),
        })
    latency = bot.latency
    return {
        "ready": bot.is_ready(),
        "user": {
            "id": str(bot.user.id),
            "name": bot.user.name,
            "avatar": bot.user.display_avatar.url,
        } if bot.user else None,
        "latency_ms": round(latency * 1000) if latency == latency and latency != float("inf") else None,
        "started_at": bot_start_time,
        "gemini": GEMINI_AVAILABLE,
        "redis": redis_client is not None,
        "guilds": guilds,
        "tickets": tickets,
        "applications": applications,
        "presence": _panel_presence,
        "invite_url": discord.utils.oauth_url(
            bot.user.id, permissions=discord.Permissions(8), scopes=("bot", "applications.commands"),
        ) if bot.user else None,
    }


# Set from the admin panel; while set, rotate_presence leaves the status alone.
_panel_presence = None


class PanelActionError(Exception):
    """A refusal the panel should show the admin as-is (French, user-facing)."""


def _pa_int(payload, key):
    try:
        return int(payload.get(key))
    except (TypeError, ValueError):
        raise PanelActionError(f"Paramètre invalide : {key}")


def _pa_text(payload, key, limit, required=True):
    value = payload.get(key)
    value = value.strip() if isinstance(value, str) else ""
    if required and not value:
        raise PanelActionError(f"Champ requis : {key}")
    if len(value) > limit:
        raise PanelActionError(f"{key} : {limit} caractères maximum")
    return value


def _pa_guild(payload):
    guild = bot.get_guild(_pa_int(payload, "guild_id"))
    if guild is None:
        raise PanelActionError("Serveur introuvable — le bot n'y est peut-être plus.")
    return guild


def _pa_channel(guild, payload):
    channel = guild.get_channel_or_thread(_pa_int(payload, "channel_id"))
    if channel is None or not isinstance(channel, discord.abc.Messageable):
        raise PanelActionError("Salon introuvable.")
    return channel


def _pa_audit(action, guild=None, detail=""):
    print(f"[PANEL] {action}{f' @ {guild.name} ({guild.id})' if guild else ''}{f' — {detail}' if detail else ''}")
    admin_panel.tracker.record(
        "panel_action",
        guild_id=guild.id if guild else None,
        guild_name=guild.name if guild else None,
        detail=f"{action}{f' · {detail}' if detail else ''}",
    )


async def _pa_member(guild, user_id):
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            raise PanelActionError("Ce membre n'est pas sur le serveur.")
    return member


def _pa_check_hierarchy(guild, member):
    if member.id == bot.user.id:
        raise PanelActionError("Le bot ne peut pas se sanctionner lui-même.")
    if member.id == guild.owner_id:
        raise PanelActionError("Impossible de sanctionner le propriétaire du serveur.")
    if member.top_role >= guild.me.top_role:
        raise PanelActionError("Ce membre a un rôle égal ou supérieur à celui du bot.")


async def _pa_guild_details(payload):
    guild = _pa_guild(payload)
    me = guild.me
    channels = []
    for ch in sorted(guild.text_channels, key=lambda c: (c.category.position if c.category else -1, c.position)):
        perms = ch.permissions_for(me)
        channels.append({
            "id": str(ch.id),
            "name": ch.name,
            "category": ch.category.name if ch.category else None,
            "can_send": perms.view_channel and perms.send_messages,
            "silenced": (guild.id, ch.id) in yslemm_silenced_channels,
            "ticket": (guild.id, ch.id) in open_tickets,
        })
    return {"ok": True, "channels": channels}


async def _pa_members(payload):
    guild = _pa_guild(payload)
    query = _pa_text(payload, "query", 100, required=False).lower()
    results = []
    for m in guild.members:
        if query and query not in m.name.lower() and query not in m.display_name.lower() and query != str(m.id):
            continue
        results.append({
            "id": str(m.id),
            "name": m.display_name,
            "username": m.name,
            "avatar": m.display_avatar.url,
            "bot": m.bot,
            "top_role": m.top_role.name if m.top_role != guild.default_role else None,
            "timed_out": m.is_timed_out(),
        })
        if len(results) >= 20:
            break
    return {"ok": True, "members": results}


async def _pa_send_message(payload):
    guild = _pa_guild(payload)
    channel = _pa_channel(guild, payload)
    content = _pa_text(payload, "content", 4000 if payload.get("embed") else 2000, required=False)
    perms = channel.permissions_for(guild.me)
    if not (perms.view_channel and perms.send_messages):
        raise PanelActionError("Le bot n'a pas la permission d'écrire dans ce salon.")
    kwargs = {"allowed_mentions": discord.AllowedMentions(everyone=bool(payload.get("allow_everyone")), roles=False, users=True)}
    if payload.get("embed"):
        if not perms.embed_links:
            raise PanelActionError("Le bot n'a pas la permission d'envoyer des embeds ici.")
        title = _pa_text(payload, "title", 256, required=False)
        if not (title or content):
            raise PanelActionError("L'embed est vide.")
        try:
            color = int(str(payload.get("color", "")).lstrip("#") or "ff2e45", 16)
        except ValueError:
            color = 0xFF2E45
        embed = discord.Embed(title=title or None, description=content or None, color=color)
        kwargs["embed"] = embed
    else:
        if not content:
            raise PanelActionError("Le message est vide.")
        kwargs["content"] = content
    msg = await channel.send(**kwargs)
    _pa_audit("Message envoyé", guild, f"#{channel.name}")
    return {"ok": True, "message": f"Message envoyé dans #{channel.name}.", "url": msg.jump_url}


async def _pa_dm_user(payload):
    user_id = _pa_int(payload, "user_id")
    content = _pa_text(payload, "content", 2000)
    user = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.NotFound:
            raise PanelActionError("Utilisateur introuvable.")
    try:
        await user.send(content)
    except discord.Forbidden:
        raise PanelActionError(f"{user} n'accepte pas les MP du bot.")
    _pa_audit("MP envoyé", None, str(user))
    return {"ok": True, "message": f"MP envoyé à {user}."}


async def _pa_leave_guild(payload):
    guild = _pa_guild(payload)
    _pa_audit("Serveur quitté", guild)
    await guild.leave()
    return {"ok": True, "message": f"Yslem a quitté {guild.name}."}


async def _pa_create_invite(payload):
    guild = _pa_guild(payload)
    for ch in guild.text_channels:
        if ch.permissions_for(guild.me).create_instant_invite:
            invite = await ch.create_invite(max_age=3600, max_uses=1, unique=True, reason="Panel admin Yslem")
            _pa_audit("Invitation créée", guild, f"#{ch.name}")
            return {"ok": True, "message": "Invitation à usage unique, valable 1 h.", "url": invite.url}
    raise PanelActionError("Le bot n'a la permission de créer une invitation dans aucun salon.")


_MODERATION_OPS = {
    "timeout": "moderate_members",
    "untimeout": "moderate_members",
    "kick": "kick_members",
    "ban": "ban_members",
    "unban": "ban_members",
}


async def _pa_moderate(payload):
    guild = _pa_guild(payload)
    op = payload.get("op")
    if op not in _MODERATION_OPS:
        raise PanelActionError("Action de modération inconnue.")
    if not getattr(guild.me.guild_permissions, _MODERATION_OPS[op]):
        raise PanelActionError("Le bot n'a pas la permission nécessaire sur ce serveur.")
    user_id = _pa_int(payload, "user_id")
    reason = _pa_text(payload, "reason", 400, required=False) or "Panel admin Yslem"
    audit_reason = f"[Panel admin] {reason}"
    if op == "unban":
        try:
            await guild.unban(discord.Object(id=user_id), reason=audit_reason)
        except discord.NotFound:
            raise PanelActionError("Cet utilisateur n'est pas banni.")
        label = "Débanni"
    elif op == "ban":
        member = guild.get_member(user_id)
        if member is not None:
            _pa_check_hierarchy(guild, member)
        await guild.ban(discord.Object(id=user_id), reason=audit_reason, delete_message_seconds=0)
        label = "Banni"
    else:
        member = await _pa_member(guild, user_id)
        _pa_check_hierarchy(guild, member)
        if op == "kick":
            await member.kick(reason=audit_reason)
            label = "Expulsé"
        elif op == "untimeout":
            await member.timeout(None, reason=audit_reason)
            label = "Timeout retiré"
        else:
            minutes = _pa_int(payload, "minutes")
            if not 1 <= minutes <= 40320:
                raise PanelActionError("Durée entre 1 minute et 28 jours.")
            await member.timeout(timedelta(minutes=minutes), reason=audit_reason)
            label = f"Timeout {minutes} min"
    _pa_audit(label, guild, f"{user_id} · {reason}")
    try:
        await _log_moderation(guild, guild.me, f"🛡️ {label} (panel admin)", f"<@{user_id}> — {reason}", WARN_COLOR)
    except discord.HTTPException:
        pass
    return {"ok": True, "message": f"{label} : {user_id}."}


async def _pa_close_ticket(payload):
    guild = _pa_guild(payload)
    channel = _pa_channel(guild, payload)
    if (guild.id, channel.id) not in open_tickets:
        raise PanelActionError("Ce salon n'est pas un ticket ouvert.")
    embed = _base_embed(t(0, "ticket.closing_title"), WARN_COLOR)
    embed.description = t(0, "ticket.closing_panel")
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass
    _pa_audit("Ticket fermé", guild, f"#{channel.name}")
    asyncio.create_task(_close_ticket_channel(channel, closer=None, automated_reason_key="ticket.reason_panel"))
    return {"ok": True, "message": f"#{channel.name} sera supprimé dans 5 secondes."}


async def _pa_accept_application(payload):
    guild = _pa_guild(payload)
    channel = _pa_channel(guild, payload)
    result = await _staffapp_accept(guild, channel, guild.me)
    if result is None:
        raise PanelActionError("Cette candidature a déjà été traitée.")
    app, applicant, role_outcome = result
    by = t(0, "staffapp.reason_panel")
    mention = applicant.mention if applicant else f"<@{app['applicant_id']}>"
    embed = _base_embed(f"✅ {t(0, 'staffapp.accepted_title')}", SUCCESS_COLOR)
    embed.description = t(0, "staffapp.accepted_description", mention=mention, by=by)
    cfg = _staffapp_cfg(guild.id)
    if role_outcome and cfg.get("granted_role_id"):
        role = guild.get_role(cfg["granted_role_id"])
        role_mention = role.mention if role else "?"
        key = "staffapp.role_granted" if role_outcome == "granted" else "staffapp.role_grant_failed"
        embed.add_field(name=t(0, "staffapp.role_field"), value=t(0, key, role=role_mention), inline=False)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass
    _pa_audit("Candidature acceptée", guild, f"#{channel.name}")
    return {"ok": True, "message": f"Candidature de #{channel.name} acceptée."}


async def _pa_reject_application(payload):
    guild = _pa_guild(payload)
    channel = _pa_channel(guild, payload)
    reason = _pa_text(payload, "reason", 500, required=False)
    result = await _staffapp_reject(guild, channel, guild.me, reason)
    if result is None:
        raise PanelActionError("Cette candidature a déjà été traitée.")
    app, applicant = result
    mention = applicant.mention if applicant else f"<@{app['applicant_id']}>"
    embed = _base_embed(f"❌ {t(0, 'staffapp.rejected_title')}", ERROR_COLOR)
    embed.description = t(0, "staffapp.rejected_description", mention=mention, by=t(0, "staffapp.reason_panel"))
    if reason:
        embed.add_field(name=t(0, "staffapp.reason_field"), value=reason[:1024], inline=False)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass
    _pa_audit("Candidature refusée", guild, f"#{channel.name}")
    return {"ok": True, "message": f"Candidature de #{channel.name} refusée."}


async def _pa_close_application(payload):
    guild = _pa_guild(payload)
    channel = _pa_channel(guild, payload)
    if (guild.id, channel.id) not in staff_applications:
        raise PanelActionError("Ce salon n'est pas une candidature ouverte.")
    embed = _base_embed(t(0, "staffapp.closing_title"), WARN_COLOR)
    embed.description = t(0, "staffapp.closing_panel")
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass
    _pa_audit("Candidature fermée", guild, f"#{channel.name}")
    asyncio.create_task(_close_staff_application_channel(channel, closer=None, automated_reason_key="staffapp.reason_panel"))
    return {"ok": True, "message": f"#{channel.name} sera supprimé dans 5 secondes."}


async def _pa_yslemm_silence(payload):
    guild = _pa_guild(payload)
    channel = _pa_channel(guild, payload)
    key = (guild.id, channel.id)
    if payload.get("silenced"):
        yslemm_silenced_channels.add(key)
        state = "réduit au silence"
    else:
        yslemm_silenced_channels.discard(key)
        state = "réactivé"
    _pa_audit(f"Yslemm {state}", guild, f"#{channel.name}")
    return {"ok": True, "message": f"Yslemm {state} dans #{channel.name}."}


_PRESENCE_TYPES = {
    "playing": discord.ActivityType.playing,
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "competing": discord.ActivityType.competing,
}


async def _pa_presence(payload):
    global _panel_presence
    if payload.get("reset"):
        _panel_presence = None
        rotate_presence.restart()
        _pa_audit("Statut : rotation automatique")
        return {"ok": True, "message": "Rotation automatique du statut réactivée."}
    status = payload.get("status", "online")
    if status not in ("online", "idle", "dnd", "invisible"):
        raise PanelActionError("Statut invalide.")
    text = _pa_text(payload, "text", 128, required=False)
    kind = payload.get("activity", "playing")
    activity = discord.Activity(type=_PRESENCE_TYPES.get(kind, discord.ActivityType.playing), name=text) if text else None
    await bot.change_presence(status=discord.Status(status), activity=activity)
    _panel_presence = {"status": status, "activity": kind, "text": text}
    _pa_audit("Statut modifié", None, f"{status} {kind} {text}".strip())
    return {"ok": True, "message": "Statut mis à jour."}


async def _pa_save_state(payload):
    if redis_client is None:
        raise PanelActionError("Redis n'est pas configuré.")
    await _save_state_to_redis()
    _pa_audit("Sauvegarde Redis")
    return {"ok": True, "message": "Configuration sauvegardée dans Redis."}


_PANEL_ACTIONS = {
    "guild_details": _pa_guild_details,
    "members": _pa_members,
    "send_message": _pa_send_message,
    "dm_user": _pa_dm_user,
    "leave_guild": _pa_leave_guild,
    "create_invite": _pa_create_invite,
    "moderate": _pa_moderate,
    "close_ticket": _pa_close_ticket,
    "accept_application": _pa_accept_application,
    "reject_application": _pa_reject_application,
    "close_application": _pa_close_application,
    "yslemm_silence": _pa_yslemm_silence,
    "presence": _pa_presence,
    "save_state": _pa_save_state,
}


async def _panel_action(payload):
    """Runs one admin-panel action on the bot's event loop. Every refusal
    comes back as {"ok": False, "error": ...} for the panel to display."""
    handler = _PANEL_ACTIONS.get(payload.get("action"))
    if handler is None:
        return {"ok": False, "error": "Action inconnue."}
    if not bot.is_ready():
        return {"ok": False, "error": "Le bot n'est pas encore connecté à Discord."}
    try:
        return await handler(payload)
    except PanelActionError as e:
        return {"ok": False, "error": str(e)}
    except discord.Forbidden:
        return {"ok": False, "error": "Discord a refusé : permission manquante pour le bot."}
    except discord.HTTPException as e:
        return {"ok": False, "error": f"Erreur Discord : {e.text or e.status}"}

afk_status = {}  # user_id -> {"reason": str, "since": isoformat str}
_delete_perm_warned = {}  # (guild_id, channel_id) -> datetime of last "missing Manage Messages" warning
_views_registered = False
_tree_synced = False
_state_loaded = False


def _banned_words_for(guild_id):
    return guild_banned_words.setdefault(guild_id, set(BANNED_WORDS))


# Common leetspeak/character-swap evasion -- "fvck", "sh1t", "a55hole" --
# normalized before word matching so automod isn't just an exact-spelling
# filter. Checked two ways: substitution alone (keeps real double-letter
# words like "asshole"/"bullshit" matching exactly as spelled), and with
# repeated-letter stretching also collapsed to one ("fuuuuck" -> "fuck",
# "shiiiit" -> "shit") to catch that evasion too without breaking the
# first check. Word-boundary tokenization is kept as-is (no separator
# stripping across the whole message) so this can't false-positive by
# merging two innocent words into a banned one.
_LEETSPEAK_TRANSLATION = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "@": "a", "$": "s",
})
_REPEATED_CHAR_RE = re.compile(r"(.)\1+")


def _contains_banned_word(content, guild_id):
    banned = _banned_words_for(guild_id)
    lowered = content.lower().translate(_LEETSPEAK_TRANSLATION)
    words = re.findall(r"[a-zà-ÿ']+", lowered)
    if any(w in banned for w in words):
        return True
    collapsed = _REPEATED_CHAR_RE.sub(r"\1", lowered)
    collapsed_words = re.findall(r"[a-zà-ÿ']+", collapsed)
    return any(w in banned for w in collapsed_words)


def _antiraid_cfg(guild_id):
    return antiraid_settings.setdefault(guild_id, {"enabled": False, "threshold": 5, "window": 10})


def _antinuke_cfg(guild_id):
    return antinuke_settings.setdefault(guild_id, {"enabled": False, "threshold": 3, "window": 10})


def _automod_cfg(guild_id):
    return automod_settings.setdefault(guild_id, {"words": True})


def _antipub_cfg(guild_id):
    return antipub_settings.setdefault(
        guild_id, {"enabled": False, "threshold": 5, "sanction": "warn", "timeout_minutes": 10}
    )


DEFAULT_WELCOME_JOIN = "Welcome to **{server}**!\nYou are our member #{count}."
DEFAULT_WELCOME_LEAVE = "**{name}** left **{server}**.\nWe are now {count} members."

GREETING_DEFAULTS = {
    "join": {"enabled": False, "channel_id": None, "title": "Welcome", "message": DEFAULT_WELCOME_JOIN, "image_url": None},
    "leave": {"enabled": False, "channel_id": None, "title": "Goodbye", "message": DEFAULT_WELCOME_LEAVE, "image_url": None},
}
GREETING_STYLE = {"join": {"emoji": "👋", "color": SUCCESS_COLOR}, "leave": {"emoji": "🚪", "color": ERROR_COLOR}}
GREETING_COMMAND = {"join": "welcome", "leave": "bye"}


def _welcome_cfg(guild_id):
    """Both cards of a server: {"join": {...}, "leave": {...}}, each with its own
    switch, channel, title, message and image. Settings saved by the old
    single-switch version are migrated the first time they are read."""
    cfg = welcome_settings.setdefault(guild_id, {})
    for kind, defaults in GREETING_DEFAULTS.items():
        if kind not in cfg:
            cfg[kind] = {**defaults, "enabled": cfg.get("enabled", False), "channel_id": cfg.get("channel_id")}
            if cfg.get(f"{kind}_message"):
                cfg[kind]["message"] = cfg[f"{kind}_message"]
        for key, value in defaults.items():
            cfg[kind].setdefault(key, value)
    for key in ("enabled", "channel_id", "join_message", "leave_message"):
        cfg.pop(key, None)
    return cfg


def _greet_cfg(guild_id, kind):
    return _welcome_cfg(guild_id)[kind]


def _format_welcome_message(template, member, guild):
    values = {
        "mention": member.mention, "name": member.display_name, "server": guild.name, "count": guild.member_count,
    }
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError, AttributeError):
        # A stray brace or an unknown placeholder must never swallow the
        # greeting: fill the known placeholders and send the rest as written.
        text = template
        for key, value in values.items():
            text = text.replace("{" + key + "}", str(value))
        return text


def _avatar_url(member):
    try:
        return member.display_avatar.replace(size=256).url
    except AttributeError:
        return None


def _greeting_embed(kind, member, guild, part=None):
    """The card: the member's profile picture and name, a title (Welcome / Goodbye),
    the message, an optional banner image and the server name + member count."""
    part = part or _greet_cfg(guild.id, kind)
    style = GREETING_STYLE[kind]
    title = _format_welcome_message(part["title"], member, guild)
    embed = discord.Embed(
        title=f"{style['emoji']} {title}"[:256],
        description=_format_welcome_message(part["message"], member, guild)[:4000],
        color=style["color"], timestamp=datetime.now(timezone.utc),
    )
    avatar = _avatar_url(member)
    if avatar:
        embed.set_thumbnail(url=avatar)
        embed.set_author(name=member.display_name, icon_url=avatar)
    else:
        embed.set_author(name=member.display_name)
    if part.get("image_url"):
        embed.set_image(url=part["image_url"])
    icon = getattr(getattr(guild, "icon", None), "url", None)
    embed.set_footer(text=f"{guild.name} · {guild.member_count}", icon_url=icon)
    return embed


async def _send_greeting(member, kind):
    """Post the Welcome (kind "join") or Goodbye (kind "leave") card. Falls back to
    the server's system channel when no channel was configured (or it was deleted)."""
    part = _greet_cfg(member.guild.id, kind)
    if not part["enabled"]:
        return
    channel = member.guild.get_channel(part["channel_id"]) if part["channel_id"] else None
    if channel is None:
        channel = member.guild.system_channel
    if channel is None:
        return
    allowed = discord.AllowedMentions(users=True, roles=False, everyone=False)
    try:
        try:
            await channel.send(content=member.mention if kind == "join" else None,
                               embed=_greeting_embed(kind, member, member.guild, part), allowed_mentions=allowed)
        except discord.Forbidden:
            # No "Embed Links" in this channel: send the plain text instead.
            await channel.send(_format_welcome_message(part["message"], member, member.guild), allowed_mentions=allowed)
    except discord.HTTPException:
        pass
    except Exception as e:
        print(f"[WARN] Greeting failed in '{member.guild.name}': {e}")


DEFAULT_TICKET_CATEGORIES = ["Support"]


def _ticket_cfg(guild_id):
    return ticket_settings.setdefault(guild_id, {
        "category_name": "🎫 Tickets",
        "log_channel_id": None,
        "staff_role_ids": set(),
        "max_open_per_user": 1,
        "warn_hours": 24,
        "close_hours": 72,
        "leave_action": "notify",
        "categories": list(DEFAULT_TICKET_CATEGORIES),
        "mute_on_close": True,
        "mute_minutes": 10080,
    })


def _ticket_config_embed(uid, guild):
    cfg = _ticket_cfg(guild.id)
    embed = _base_embed(t(uid, "ticket.config_title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "ticket.config_category"), value=cfg["category_name"], inline=True)
    log_value = f"<#{cfg['log_channel_id']}>" if cfg["log_channel_id"] else t(uid, "ticket.not_set")
    embed.add_field(name=t(uid, "ticket.config_logchannel"), value=log_value, inline=True)
    embed.add_field(name=t(uid, "ticket.config_maxopen"), value=str(cfg["max_open_per_user"]), inline=True)
    warn_value = f"{int(cfg['warn_hours'])}h" if cfg["warn_hours"] else t(uid, "ticket.disabled")
    embed.add_field(name=t(uid, "ticket.config_warnhours"), value=warn_value, inline=True)
    close_value = f"{int(cfg['close_hours'])}h" if cfg["close_hours"] else t(uid, "ticket.disabled")
    embed.add_field(name=t(uid, "ticket.config_closehours"), value=close_value, inline=True)
    embed.add_field(name=t(uid, "ticket.config_leaveaction"), value=cfg["leave_action"], inline=True)
    mute_value = (
        f"{t(uid, 'antiraid.enabled')} ({_format_duration(cfg['mute_minutes'] * 60)})"
        if cfg["mute_on_close"] else t(uid, "antiraid.disabled")
    )
    embed.add_field(name=t(uid, "ticket.config_mute"), value=mute_value, inline=True)
    embed.add_field(name=t(uid, "ticket.config_types"), value=", ".join(f"`{c}`" for c in cfg["categories"]), inline=False)
    roles_value = ", ".join(f"<@&{r}>" for r in cfg["staff_role_ids"]) or t(uid, "ticket.not_set")
    embed.add_field(name=t(uid, "ticket.config_staffroles"), value=roles_value, inline=False)
    return embed


DEFAULT_STAFFAPP_COOLDOWN_DAYS = 30


def _staffapp_cfg(guild_id):
    return staffapp_settings.setdefault(guild_id, {
        "category_name": "📋 Candidatures",
        "log_channel_id": None,
        "recruiter_role_ids": set(),
        "cooldown_days": DEFAULT_STAFFAPP_COOLDOWN_DAYS,
        "granted_role_id": None,
        "owner_only": True,
    })


def _staffapp_is_recruiter(member):
    if is_bot_admin_member(member):
        return True
    roles = _staffapp_cfg(member.guild.id)["recruiter_role_ids"]
    return any(r.id in roles for r in member.roles)


def _staffapp_status_label(uid, status):
    return t(uid, f"staffapp.status_{status}")


def _staffapp_active_channel(guild, user_id):
    """This user's still-open application channel in this guild (pending,
    or accepted but not yet closed), or None -- used to stop someone from
    opening a second one. Scoped strictly by applicant_id, never by
    channel name: two different people's usernames can sanitize to the
    same slug, which used to make the name-based check block the wrong
    person. Self-heals: if the tracked channel was deleted outside the
    bot's own close flow (manually, from Discord), the stale entry is
    dropped here instead of blocking the person forever with a duplicate
    check that points at nothing."""
    for key, info in list(staff_applications.items()):
        gid, cid = key
        if gid != guild.id or info["applicant_id"] != user_id or info["status"] not in ("pending", "accepted"):
            continue
        channel = guild.get_channel(cid)
        if channel is None:
            staff_applications.pop(key, None)
            continue
        return channel
    return None


def _staffapp_cooldown_remaining_days(guild_id, user_id):
    """Days left before a previously-rejected applicant may reapply, or 0
    if they're clear to (no rejection on file, or cooldown disabled)."""
    cfg = _staffapp_cfg(guild_id)
    if not cfg["cooldown_days"]:
        return 0.0
    last = staffapp_last_rejected.get((guild_id, user_id))
    if not last:
        return 0.0
    elapsed_days = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 86400
    return max(0.0, cfg["cooldown_days"] - elapsed_days)


def _staffapp_config_embed(uid, guild):
    cfg = _staffapp_cfg(guild.id)
    embed = _base_embed(t(uid, "staffapp.config_title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "staffapp.config_category"), value=cfg["category_name"], inline=True)
    log_value = f"<#{cfg['log_channel_id']}>" if cfg["log_channel_id"] else t(uid, "ticket.not_set")
    embed.add_field(name=t(uid, "staffapp.config_logchannel"), value=log_value, inline=True)
    role_value = f"<@&{cfg['granted_role_id']}>" if cfg.get("granted_role_id") else t(uid, "ticket.not_set")
    embed.add_field(name=t(uid, "staffapp.config_role"), value=role_value, inline=True)
    cooldown_value = t(uid, "staffapp.cooldown_value", days=f"{cfg['cooldown_days']:g}") if cfg["cooldown_days"] else t(uid, "staffapp.cooldown_off")
    embed.add_field(name=t(uid, "staffapp.config_cooldown"), value=cooldown_value, inline=True)
    roles_value = ", ".join(f"<@&{r}>" for r in cfg["recruiter_role_ids"]) or t(uid, "ticket.not_set")
    embed.add_field(name=t(uid, "staffapp.config_recruiters"), value=roles_value, inline=False)
    private_key = "staffapp.private_on" if cfg.get("owner_only", True) else "staffapp.private_off"
    embed.add_field(name=t(uid, "staffapp.config_private"), value=t(uid, private_key), inline=False)
    return embed


async def _close_staff_application_channel(channel, closer=None, automated_reason_key=None):
    """Logs the closure (if a log channel is set) and deletes the channel --
    mirrors _close_ticket_channel, kept separate since staff applications
    carry a status (pending/accepted/rejected) tickets don't have."""
    key = (channel.guild.id, channel.id)
    info = staff_applications.pop(key, None)
    _panel_track("staffapp_close", channel.guild, closer, channel.name)
    cfg = _staffapp_cfg(channel.guild.id)
    if cfg["log_channel_id"] and info is not None:
        log_channel = channel.guild.get_channel(cfg["log_channel_id"])
        if log_channel is not None:
            try:
                applicant_mention = f"<@{info['applicant_id']}>"
                closed_by_text = closer.mention if closer else t(0, automated_reason_key or "ticket.reason_auto")
                log_embed = _base_embed(t(0, "staffapp.log_closed_title"), EMBED_COLOR)
                log_embed.description = t(
                    0, "staffapp.log_closed_description",
                    channel=channel.name, applicant=applicant_mention, closed_by=closed_by_text,
                    status=_staffapp_status_label(0, info["status"]),
                )
                await log_channel.send(embed=log_embed)
            except discord.HTTPException:
                pass
    await asyncio.sleep(5)
    try:
        await channel.delete(reason=f"Application closed by {closer}" if closer else "Application closed")
    except discord.HTTPException:
        pass


async def _staffapp_accept(guild, channel, actor):
    """Marks the application accepted and grants the configured role (if
    any). Returns (app, applicant, role_outcome) on success, where
    role_outcome is None (no role configured), "granted" or "failed"; or
    None if there was nothing pending to decide."""
    app = staff_applications.get((guild.id, channel.id))
    if app is None or app["status"] != "pending":
        return None
    app["status"] = "accepted"
    app["decided_by"] = actor.id
    app["decided_at"] = datetime.now(timezone.utc).isoformat()
    applicant = guild.get_member(app["applicant_id"])
    cfg = _staffapp_cfg(guild.id)
    role_outcome = None
    if applicant is not None and cfg.get("granted_role_id"):
        role = guild.get_role(cfg["granted_role_id"])
        if role is not None:
            try:
                await applicant.add_roles(role, reason=f"Staff application accepted by {actor}")
                role_outcome = "granted"
            except discord.Forbidden:
                role_outcome = "failed"
    return app, applicant, role_outcome


async def _staffapp_reject(guild, channel, actor, reason):
    """Marks the application rejected, records the reason and starts the
    reapply cooldown. Returns (app, applicant), or None if there was
    nothing pending to decide."""
    app = staff_applications.get((guild.id, channel.id))
    if app is None or app["status"] != "pending":
        return None
    app["status"] = "rejected"
    app["decided_by"] = actor.id
    app["decided_at"] = datetime.now(timezone.utc).isoformat()
    app["reason"] = reason
    staffapp_last_rejected[(guild.id, app["applicant_id"])] = app["decided_at"]
    applicant = guild.get_member(app["applicant_id"])
    return app, applicant


_INVITE_RE = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/[a-z0-9-]+", re.IGNORECASE)
_SHORTENER_DOMAINS = (
    "bit.ly", "tinyurl.com", "is.gd", "cutt.ly", "t.co", "shorturl.at",
    "rb.gy", "ow.ly", "buff.ly", "s.id", "rebrand.ly",
)
_SHORTENER_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(" + "|".join(re.escape(d) for d in _SHORTENER_DOMAINS) + r")/\S+",
    re.IGNORECASE,
)
_CONTACT_RE = re.compile(
    r"\b(whatsapp|telegram|t\.me|snapchat|snap\s*:|kik\s*:|contact\s*me|dm\s*me\s*for|contacte[- ]?moi|mp\s*moi\s*pour)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"(?:https?://|www\.)\S+\.\S{2,}", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]){2,4}\d{2,4}")
_ZERO_WIDTH_RE = re.compile(r"[​‌‍⁠﻿]")
_SEPARATORS_RE = re.compile(r"[\s\-_.*]+")


def _antipub_normalize(content):
    lowered = _ZERO_WIDTH_RE.sub("", content.lower())
    compact = _SEPARATORS_RE.sub("", lowered)
    return lowered, compact


def _antipub_score(message, guild_id):
    content = message.content
    lowered, compact = _antipub_normalize(content)
    reasons = []
    score = 0
    bypass = False

    has_invite = bool(_INVITE_RE.search(lowered) or _INVITE_RE.search(compact))
    if _INVITE_RE.search(lowered):
        score += 5
        reasons.append("invite_link")
    elif _INVITE_RE.search(compact):
        score += 5
        reasons.append("invite_link")
        bypass = True

    has_shortener = bool(_SHORTENER_RE.search(lowered) or _SHORTENER_RE.search(compact))
    if _SHORTENER_RE.search(lowered):
        score += 3
        reasons.append("shortened_link")
    elif _SHORTENER_RE.search(compact):
        score += 3
        reasons.append("shortened_link")
        bypass = True

    # Any other link -- lower weight than a Discord invite or a known
    # shortener since most are harmless (a shared article, a video...),
    # but it still nudges the score up, same as an anti-pub filter should:
    # a plain link alone won't trip the default threshold, a link stacked
    # with a keyword or a contact method will.
    if not (has_invite or has_shortener):
        if _URL_RE.search(lowered):
            score += 2
            reasons.append("external_link")
        elif _URL_RE.search(compact):
            score += 2
            reasons.append("external_link")
            bypass = True

    keywords = antipub_blacklist.get(guild_id, DEFAULT_ANTIPUB_KEYWORDS)
    for word in keywords:
        needle = word.lower()
        if needle in lowered:
            score += 3
            reasons.append(f"keyword:{word}")
        elif needle.replace(" ", "") in compact:
            score += 3
            reasons.append(f"keyword:{word}")
            bypass = True

    if _CONTACT_RE.search(lowered) or _CONTACT_RE.search(compact):
        score += 2
        reasons.append("contact_method")

    if _PHONE_RE.search(content):
        score += 1
        reasons.append("phone_number")

    key = (guild_id, message.author.id)
    now = time.time()
    history = [(c, ts) for c, ts in antipub_recent_messages.get(key, []) if now - ts < 30]
    history.append((lowered, now))
    antipub_recent_messages[key] = history[-5:]
    if len([c for c, _ in history if c == lowered]) >= 3:
        score += 4
        reasons.append("repeated_message")

    if bypass:
        score += 1
        reasons.append("bypass_attempt")

    return score, reasons


def _antipub_is_whitelisted(message):
    guild_id = message.guild.id
    if message.channel.id in antipub_whitelist_channels.get(guild_id, set()):
        return True
    whitelisted_roles = antipub_whitelist_roles.get(guild_id, set())
    if whitelisted_roles and any(r.id in whitelisted_roles for r in message.author.roles):
        return True
    return False


async def _apply_antipub_sanction(message, reasons, score):
    cfg = _antipub_cfg(message.guild.id)
    sanction = cfg["sanction"]
    member = message.author
    reason_text = ", ".join(reasons)

    try:
        await message.delete()
    except discord.HTTPException:
        pass

    applied = "none"
    try:
        if sanction == "warn":
            key = (message.guild.id, member.id)
            warnings_store.setdefault(key, []).append(f"Anti-pub: {reason_text}")
            applied = "warn"
            await _check_warn_autoban(message.guild, member, key)
        elif sanction == "timeout":
            await member.timeout(timedelta(minutes=cfg["timeout_minutes"]), reason=f"Anti-pub: {reason_text}")
            applied = "timeout"
        elif sanction == "kick":
            await member.kick(reason=f"Anti-pub: {reason_text}")
            applied = "kick"
        elif sanction == "ban":
            await member.ban(reason=f"Anti-pub: {reason_text}", delete_message_days=0)
            applied = "ban"
    except discord.HTTPException:
        applied = f"{sanction} (failed)"

    embed = _base_embed("🚫 Anti-pub detection", ERROR_COLOR)
    embed.add_field(name="Author", value=f"{member} ({member.id})", inline=False)
    embed.add_field(name="Channel", value=message.channel.mention, inline=False)
    embed.add_field(name="Score", value=str(score), inline=True)
    embed.add_field(name="Sanction", value=applied, inline=True)
    embed.add_field(name="Reasons", value=reason_text or "-", inline=False)
    excerpt = message.content[:1000] or "*(no text content)*"
    embed.add_field(name="Message", value=excerpt, inline=False)
    await _send_modlog(message.guild, embed)


def is_bot_admin_member(member):
    if member.id == BOT_OWNER_ID:
        return True
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return True
    admins = bot_admins.get(member.guild.id)
    if not admins:
        return False
    if member.id in admins["users"]:
        return True
    return any(r.id in admins["roles"] for r in member.roles)


def is_bot_admin():
    async def predicate(ctx):
        if is_bot_admin_member(ctx.author):
            return True
        raise commands.CheckFailure("not_bot_admin")
    return commands.check(predicate)


def is_bot_admin_slash():
    async def predicate(interaction: discord.Interaction) -> bool:
        if is_bot_admin_member(interaction.user):
            return True
        raise app_commands.CheckFailure("not_bot_admin")
    return app_commands.check(predicate)


def _try_charge_coin(guild_id, user_id, cost=1):
    key = (guild_id, user_id)
    if economy_balances.get(key, 0) >= cost:
        economy_balances[key] -= cost
        return True
    return False


@bot.check
async def _global_command_access_check(ctx):
    if ctx.guild is None or ctx.command is None:
        return True
    name = ctx.command.qualified_name.lower()
    is_admin = is_bot_admin_member(ctx.author)
    allowed_roles = command_access.get(ctx.guild.id, {}).get(name)
    has_role = bool(allowed_roles) and any(r.id in allowed_roles for r in ctx.author.roles)
    if is_admin or has_role:
        return True
    # yslem always costs a coin for a regular member -- this must NOT
    # depend on whether an admin has also set up a !cmdaccess role
    # restriction for the command (allowed_roles is often None, since
    # it isn't meant to require any role at all, just a coin).
    if name == "yslem":
        if _try_charge_coin(ctx.guild.id, ctx.author.id):
            return True
        raise commands.CheckFailure("no_command_access_coin")
    if allowed_roles is None:
        return True
    raise commands.CheckFailure("no_command_access")


async def _tree_interaction_check(interaction: discord.Interaction) -> bool:
    if interaction.guild is None or interaction.command is None:
        return True
    name = interaction.command.qualified_name.lower()
    is_admin = is_bot_admin_member(interaction.user)
    allowed_roles = command_access.get(interaction.guild.id, {}).get(name)
    has_role = bool(allowed_roles) and any(r.id in allowed_roles for r in interaction.user.roles)
    if is_admin or has_role:
        return True
    if name == "yslem":
        if _try_charge_coin(interaction.guild.id, interaction.user.id):
            return True
        raise app_commands.CheckFailure("no_command_access_coin")
    if allowed_roles is None:
        return True
    raise app_commands.CheckFailure("no_command_access")


bot.tree.interaction_check = _tree_interaction_check


def _kickban_error_key(actor, target, guild, self_key, owner_key, hierarchy_key, bot_hierarchy_key):
    if target == actor:
        return self_key
    if target == guild.owner:
        return owner_key
    if actor != guild.owner and target.top_role >= actor.top_role:
        return hierarchy_key
    if target.top_role >= guild.me.top_role:
        return bot_hierarchy_key
    return None


_LEGAL_PAGE_STYLE = """
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #1a1a1a; }
  h1 { font-size: 1.6em; } h2 { font-size: 1.2em; margin-top: 1.6em; }
  code { background: #f0f0f0; padding: 2px 5px; border-radius: 3px; }
</style>
"""

_LEGAL_CONTACT = "yslemhd@gmail.com"

_PRIVACY_POLICY_HTML = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Yslem -- Privacy Policy</title>{_LEGAL_PAGE_STYLE}</head><body>
<h1>Privacy Policy -- Yslem (Discord bot)</h1>
<p>Last updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d")}</p>
<p>Yslem is a Discord bot developed and operated by an individual developer for a small number of Discord servers. This page explains what data the bot accesses, why, and how it is handled.</p>

<h2>Message content</h2>
<p>Yslem requests the Message Content privileged intent. Message text is read in order to: recognize and run prefix commands (starting with <code>!</code>); detect banned words and unauthorized advertising links for automated moderation; and power an optional AI assistant feature that replies to natural-language questions and requests.</p>
<p>Message content is processed in memory to perform these functions and is not permanently stored or logged, with one exception: when a member explicitly invokes the AI assistant feature, the relevant message text is sent to a third-party AI inference provider (Google Gemini) to generate a reply. That provider processes the text to return a response and is not used to store a profile of any user.</p>

<h2>Server member data</h2>
<p>Yslem requests the Server Members privileged intent. Member IDs and role IDs are used to: check whether a member has permission to use a given command; post a welcome message when someone joins; detect abnormal join activity (anti-raid) and validate newly added bots (anti-nuke); and correctly target the member affected by a moderation action (mute, kick, ban, role change).</p>
<p>Yslem does not collect or store member profile data such as email addresses, phone numbers, or Discord account credentials -- it only has access to what the Discord API exposes for members of servers it is added to (user ID, username, roles, join date).</p>

<h2>Data stored persistently</h2>
<p>To keep server configuration and features working across restarts, Yslem stores the following in a private database it operates: per-server bot configuration (admin lists, moderation settings, log channel, banned word list), a virtual in-server currency balance per user ID (has no real-world monetary value), and short-lived operational state (e.g. open support tickets, AFK status). When a support ticket is closed, a plain-text copy of that ticket's conversation is posted once in the server's private staff log channel and sent to the person who opened it; the bot does not keep it.</p>
<p>If a server administrator enables account screening, Yslem looks at the public details of an account when it joins -- creation date, whether it has a profile picture and a banner, and the shape of the username -- to flag likely bot or raid accounts. These details are used only to compute a score at that moment and to post an alert for the server's staff; they are not stored.</p>
<p>If a member uses the optional verification panel, they authorise Yslem on Discord's own authorization page with the single <code>identify</code> scope. Yslem reads the account's username, profile picture and banner once to compute the same suspicion score, then revokes the authorization immediately. Nothing from the profile and no access token is stored.</p>
<p>The script key system stores, for each key, a salted SHA-256 hash of the key (never the key itself), the Discord user ID and the Roblox user ID and username it is linked to, and the dates of creation, expiry and replacement. The member types their Roblox username, which Yslem looks up through Roblox's public API; when the optional ownership check is on, they must also place a short code in their public profile description, which Yslem reads once. When a script checks a key, it sends only the key, the Roblox user ID, the script name and a version number; network addresses are used in memory for rate limiting and are not stored or logged. A key can be replaced by its owner (once a week, three times a month), revoked by the staff, and expires after 30 days.</p>
<p>When a server administrator uses the AI server builder (<code>/aibuild</code>), their request and the names of the server's existing roles, categories and channels are sent to Google's Gemini API to draft a plan. The administrator sees the plan and must confirm it; the bot then creates roles, categories and channels, moves existing channels between categories, renames items and reorders categories. It never deletes anything on its own, never changes the permissions of existing items and never grants administrator or management permissions; <code>/aiundo</code> reverts the latest change within 24 hours (deleting only what the bot itself created, and only if still empty). The request is not stored; a short record of the latest change (item IDs and previous names) is kept for that undo.</p>
<p>This data is used solely to operate the bot's features on the servers where it is installed. It is not sold, and it is not shared with third parties except the AI provider noted above, and only for the specific message being processed at the time.</p>

<h2>Data deletion</h2>
<p>A server administrator can remove most of the bot's stored configuration directly through its commands (e.g. clearing moderation settings). To request deletion of any remaining data associated with a specific server or user, contact: {_LEGAL_CONTACT}.</p>

<h2>Children's privacy</h2>
<p>Yslem is intended for use in compliance with Discord's own Terms of Service, which require users to be at least the minimum age required by Discord in their jurisdiction. The bot does not knowingly collect data from users below that age beyond what Discord itself provides through normal bot operation.</p>

<h2>Contact</h2>
<p>Questions about this policy or requests regarding your data: {_LEGAL_CONTACT}.</p>
</body></html>"""

_TERMS_OF_SERVICE_HTML = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Yslem -- Terms of Service</title>{_LEGAL_PAGE_STYLE}</head><body>
<h1>Terms of Service -- Yslem (Discord bot)</h1>
<p>Last updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d")}</p>
<p>By adding Yslem to a Discord server or using its commands, you agree to these terms.</p>

<h2>The service</h2>
<p>Yslem is provided as a free, individually-operated Discord bot offering moderation, utility, and community features as described in the bot's own help commands. Features may be added, changed, or removed at any time without notice.</p>

<h2>Acceptable use</h2>
<p>You agree to use Yslem in compliance with Discord's Terms of Service and Community Guidelines. Server administrators are responsible for how the bot's configurable features (moderation, economy, tickets, etc.) are set up and used on their own server.</p>

<h2>Virtual currency</h2>
<p>Yslem's in-server coin system is a virtual, server-local feature with no real-world monetary value. Coins cannot be purchased, exchanged for real currency, or transferred outside of the Discord server they were earned on.</p>

<h2>No warranty</h2>
<p>Yslem is provided "as is," without warranty of any kind. The developer does not guarantee uninterrupted availability and is not liable for any loss or damage arising from use of, or inability to use, the bot.</p>

<h2>Termination</h2>
<p>The developer may restrict or remove the bot's access to a server, or a specific user's access to its features, at their discretion -- for example in response to abuse.</p>

<h2>Changes to these terms</h2>
<p>These terms may be updated from time to time; continued use of the bot after a change constitutes acceptance of the updated terms.</p>

<h2>Contact</h2>
<p>{_LEGAL_CONTACT}</p>
</body></html>"""


def _verify_paypal_ipn(raw_body):
    """Re-post the IPN body back to PayPal so it can confirm the
    notification really came from them (PayPal's own required
    verification step -- otherwise anyone could POST a fake "payment
    received" to this endpoint). Blocking, meant to run off the main
    thread."""
    req = urllib.request.Request(
        "https://ipnpb.paypal.com/cgi-bin/webscr",
        data=b"cmd=_notify-validate&" + raw_body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "yslem-bot-paypal-ipn",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().strip() == b"VERIFIED"
    except OSError:
        return False


def _find_paypal_owner(receiver_email):
    """Match an IPN's receiver_email against everyone's configured PayPal
    address (each staff member's own via !mypayment, or a guild's shared
    default via !setpayment) so the notification can say who it's for."""
    if not receiver_email:
        return None
    receiver_email = receiver_email.strip().lower()
    for uid, info in staff_payment_info.items():
        if (info.get("paypal") or "").strip().lower() == receiver_email:
            return uid
    return None


async def _post_paypal_ipn_notification(fields, owner_id):
    amount = fields.get("mc_gross", "?")
    currency = fields.get("mc_currency", "")
    payer_email = fields.get("payer_email", "?")
    payer_name = " ".join(p for p in (fields.get("first_name"), fields.get("last_name")) if p)
    txn_id = fields.get("txn_id", "?")
    for gid, cid in dict(paypal_notify_channels).items():
        guild = bot.get_guild(gid)
        if guild is None:
            continue
        channel = guild.get_channel(cid)
        if channel is None:
            continue
        embed = _base_embed(t(0, "paypal.ipn_title"), SUCCESS_COLOR)
        embed.add_field(name=t(0, "paypal.ipn_amount"), value=f"{amount} {currency}".strip(), inline=True)
        embed.add_field(
            name=t(0, "paypal.ipn_from"),
            value=f"{payer_name} ({payer_email})" if payer_name else payer_email,
            inline=True,
        )
        if owner_id is not None:
            embed.add_field(name=t(0, "paypal.ipn_owner"), value=f"<@{owner_id}>", inline=True)
        embed.set_footer(text=f"Transaction ID: {txn_id}")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


def _process_paypal_ipn(raw_body):
    """Runs off the main thread (spawned by the health-server thread on
    every /paypal-ipn POST). Verifies with PayPal, parses the payment
    fields, and hands the actual Discord send off to the bot's own event
    loop via run_coroutine_threadsafe -- discord.py objects are not
    thread-safe to touch directly from here."""
    if not _verify_paypal_ipn(raw_body):
        return
    fields = dict(parse_qsl(raw_body.decode("utf-8", errors="replace")))
    if fields.get("payment_status") != "Completed":
        return
    txn_id = fields.get("txn_id")
    if txn_id:
        if txn_id in _seen_paypal_txn_ids:
            return
        _seen_paypal_txn_ids.add(txn_id)
        if len(_seen_paypal_txn_ids) > 1000:
            _seen_paypal_txn_ids.clear()
    owner_id = _find_paypal_owner(fields.get("receiver_email"))
    loop = getattr(bot, "loop", None)
    if loop is not None and loop.is_running():
        asyncio.run_coroutine_threadsafe(_post_paypal_ipn_notification(fields, owner_id), loop)


class _HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if key_store.handle(self) or oauth_verify.handle(self) or admin_panel.handle(self):
            return
        if self.path.startswith("/privacy"):
            body = _PRIVACY_POLICY_HTML.encode("utf-8")
            content_type = "text/html; charset=utf-8"
        elif self.path.startswith("/terms"):
            body = _TERMS_OF_SERVICE_HTML.encode("utf-8")
            content_type = "text/html; charset=utf-8"
        else:
            body = b"OK"
            content_type = "text/plain"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the client disconnected before the response arrived -- nothing to do

    def do_POST(self):
        if key_store.handle(self) or oauth_verify.handle(self) or admin_panel.handle(self):
            return
        if self.path.startswith("/paypal-ipn"):
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw_body = self.rfile.read(length) if length else b""
            # Acknowledge immediately -- PayPal expects a prompt 200 and
            # will retry the notification if it doesn't get one. The
            # actual verification round-trip to PayPal happens after, off
            # this thread, so it can't delay the response or block the
            # (single-threaded) health server from serving other requests.
            self.send_response(200)
            self.end_headers()
            threading.Thread(target=_process_paypal_ipn, args=(raw_body,), daemon=True).start()
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def _keep_awake_loop():
    """Independent of Discord: pings the service's own public URL every 10 min so Render's free tier
    (sleeps after 15 min without inbound traffic) keeps the bot running, even while the login is retried."""
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        print("[INFO] keep-awake: RENDER_EXTERNAL_URL not set, no self-ping")
        return
    time.sleep(60)
    while True:
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                print(f"[OK] keep-awake ping -> HTTP {resp.status}")
        except Exception as exc:
            print(f"[WARN] keep-awake ping failed: {exc}")
        time.sleep(600)


def _start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    server.daemon_threads = True
    server.serve_forever()


def _dump_state():
    return json.dumps({
        "user_lang": user_lang,
        "bot_admins": {
            str(gid): {"roles": list(v["roles"]), "users": list(v["users"])}
            for gid, v in bot_admins.items()
        },
        "guild_banned_words": {str(gid): list(words) for gid, words in guild_banned_words.items()},
        "log_channels": log_channels,
        "paypal_notify_channels": paypal_notify_channels,
        "crypto_notify_channels": crypto_notify_channels,
        "antiraid_settings": antiraid_settings,
        "screening_settings": screening_settings,
        "key_system": key_store.dump(),
        "key_invites": {str(cid): url for cid, url in key_invites.items()},
        "ai_undo": {str(gid): rec for gid, rec in _ai_undo.items()},
        "antinuke_settings": antinuke_settings,
        "welcome_settings": welcome_settings,
        "warnings_store": {f"{gid}:{uid}": reasons for (gid, uid), reasons in warnings_store.items()},
        "command_access": {
            str(gid): {name: list(roles) for name, roles in cmds.items()}
            for gid, cmds in command_access.items()
        },
        "payment_info": payment_info,
        "staff_payment_info": staff_payment_info,
        "global_payment_info": global_payment_info,
        "ticket_counters": {str(gid): n for gid, n in ticket_counters.items()},
        "ticket_settings": {
            str(gid): {**cfg, "staff_role_ids": list(cfg["staff_role_ids"])}
            for gid, cfg in ticket_settings.items()
        },
        "open_tickets": {f"{gid}:{cid}": info for (gid, cid), info in open_tickets.items()},
        "staffapp_settings": {
            str(gid): {**cfg, "recruiter_role_ids": list(cfg["recruiter_role_ids"])}
            for gid, cfg in staffapp_settings.items()
        },
        "staff_applications": {f"{gid}:{cid}": info for (gid, cid), info in staff_applications.items()},
        "staffapp_last_rejected": {f"{gid}:{uid}": iso for (gid, uid), iso in staffapp_last_rejected.items()},
        "yslemm_faq": {str(gid): faq for gid, faq in yslemm_faq.items()},
        "yslemm_silenced_channels": [f"{gid}:{cid}" for gid, cid in yslemm_silenced_channels],
        "recurring_reminders": {str(gid): cfg for gid, cfg in recurring_reminders.items()},
        "economy_balances": {f"{gid}:{uid}": bal for (gid, uid), bal in economy_balances.items()},
        "economy_last_daily": {
            f"{gid}:{uid}": dt.isoformat() for (gid, uid), dt in economy_last_daily.items()
        },
        "automod_settings": automod_settings,
        "antipub_settings": antipub_settings,
        "antipub_blacklist": {str(gid): list(words) for gid, words in antipub_blacklist.items()},
        "antipub_whitelist_roles": {str(gid): list(r) for gid, r in antipub_whitelist_roles.items()},
        "antipub_whitelist_channels": {str(gid): list(c) for gid, c in antipub_whitelist_channels.items()},
        "afk_status": afk_status,
    })


def _load_state(raw):
    data = json.loads(raw)

    user_lang.update({int(k): v for k, v in data.get("user_lang", {}).items()})

    for gid, v in data.get("bot_admins", {}).items():
        bot_admins[int(gid)] = {"roles": set(v["roles"]), "users": set(v["users"])}

    for gid, words in data.get("guild_banned_words", {}).items():
        guild_banned_words[int(gid)] = set(words)

    log_channels.update({int(k): v for k, v in data.get("log_channels", {}).items()})
    paypal_notify_channels.update({int(k): v for k, v in data.get("paypal_notify_channels", {}).items()})
    crypto_notify_channels.update({int(k): v for k, v in data.get("crypto_notify_channels", {}).items()})

    for gid, cfg in data.get("antiraid_settings", {}).items():
        antiraid_settings[int(gid)] = cfg
    for gid, cfg in data.get("screening_settings", {}).items():
        screening_settings[int(gid)] = cfg
    key_store.load(data.get("key_system") or {})
    key_invites.clear()
    key_invites.update({int(cid): url for cid, url in (data.get("key_invites") or {}).items()})
    _ai_undo.clear()
    _ai_undo.update({int(gid): rec for gid, rec in (data.get("ai_undo") or {}).items()})
    for gid, cfg in data.get("antinuke_settings", {}).items():
        antinuke_settings[int(gid)] = cfg
    for gid, cfg in data.get("welcome_settings", {}).items():
        welcome_settings[int(gid)] = cfg

    for key, reasons in data.get("warnings_store", {}).items():
        gid, uid = key.split(":")
        warnings_store[(int(gid), int(uid))] = reasons

    for gid, cmds in data.get("command_access", {}).items():
        command_access[int(gid)] = {name: set(roles) for name, roles in cmds.items()}

    for gid, info in data.get("payment_info", {}).items():
        payment_info[int(gid)] = info

    for uid_str, info in data.get("staff_payment_info", {}).items():
        staff_payment_info[int(uid_str)] = info
    global_payment_info.clear()
    global_payment_info.update(data.get("global_payment_info") or {})
    for gid, n in (data.get("ticket_counters") or {}).items():
        ticket_counters[int(gid)] = int(n)

    for gid, cfg in data.get("ticket_settings", {}).items():
        # Merge onto the current defaults rather than overwriting outright,
        # so a snapshot saved before a config field existed (e.g. the
        # mute-on-close settings) doesn't leave it missing after load.
        merged = _ticket_cfg(int(gid)).copy()
        merged.update(cfg)
        merged["staff_role_ids"] = set(cfg.get("staff_role_ids", []))
        ticket_settings[int(gid)] = merged
    for key, info in data.get("open_tickets", {}).items():
        gid, cid = key.split(":")
        info = dict(info)
        if "warned" in info and "warn_count" not in info:
            info["warn_count"] = 1 if info.pop("warned") else 0
        open_tickets[(int(gid), int(cid))] = info

    for gid, cfg in data.get("staffapp_settings", {}).items():
        merged = _staffapp_cfg(int(gid)).copy()
        merged.update(cfg)
        merged["recruiter_role_ids"] = set(cfg.get("recruiter_role_ids", []))
        staffapp_settings[int(gid)] = merged
    for key, info in data.get("staff_applications", {}).items():
        gid, cid = key.split(":")
        staff_applications[(int(gid), int(cid))] = info
    for key, iso in data.get("staffapp_last_rejected", {}).items():
        gid, uid = key.split(":")
        staffapp_last_rejected[(int(gid), int(uid))] = iso

    for gid, faq in data.get("yslemm_faq", {}).items():
        yslemm_faq[int(gid)] = faq

    for key in data.get("yslemm_silenced_channels", []):
        gid, cid = key.split(":")
        yslemm_silenced_channels.add((int(gid), int(cid)))

    for gid, cfg in data.get("recurring_reminders", {}).items():
        recurring_reminders[int(gid)] = cfg

    for key, bal in data.get("economy_balances", {}).items():
        gid, uid = key.split(":")
        economy_balances[(int(gid), int(uid))] = bal

    for key, iso in data.get("economy_last_daily", {}).items():
        gid, uid = key.split(":")
        economy_last_daily[(int(gid), int(uid))] = datetime.fromisoformat(iso)

    for gid, cfg in data.get("automod_settings", {}).items():
        automod_settings[int(gid)] = {"words": bool(cfg.get("words", True))}
    for gid, cfg in data.get("antipub_settings", {}).items():
        antipub_settings[int(gid)] = cfg
    for gid, words in data.get("antipub_blacklist", {}).items():
        antipub_blacklist[int(gid)] = set(words)
    for gid, roles in data.get("antipub_whitelist_roles", {}).items():
        antipub_whitelist_roles[int(gid)] = set(roles)
    for gid, chans in data.get("antipub_whitelist_channels", {}).items():
        antipub_whitelist_channels[int(gid)] = set(chans)
    for k, v in data.get("afk_status", {}).items():
        # Backward compatible with the old format (plain reason string,
        # no timestamp) that may still be sitting in Redis from before
        # AFK duration tracking existed.
        if isinstance(v, str):
            v = {"reason": v, "since": datetime.now(timezone.utc).isoformat()}
        afk_status[int(k)] = v


async def _save_state_to_redis():
    if redis_client is None:
        return
    try:
        await redis_client.set(STATE_REDIS_KEY, _dump_state())
        await redis_client.set(PANEL_REDIS_KEY, json.dumps(admin_panel.tracker.dump()))
    except Exception as e:
        print(f"[WARN] Failed to save state to Redis: {e}")


async def _load_state_from_redis():
    """True when a saved state was actually found and loaded."""
    found = False
    if redis_client is None:
        print("[WARN] REDIS_URL is not set -- bot config will NOT survive restarts.")
        return found
    try:
        raw = await redis_client.get(STATE_REDIS_KEY)
        if raw:
            _load_state(raw)
            print("[OK] Loaded persisted bot state from Redis")
            found = True
        else:
            print("[OK] No persisted state found in Redis yet (fresh start)")
    except Exception as e:
        print(f"[WARN] Failed to load state from Redis: {e}")
    # Separate from the config load so corrupt panel stats can never block it.
    try:
        raw_panel = await redis_client.get(PANEL_REDIS_KEY)
        if raw_panel:
            admin_panel.tracker.load(json.loads(raw_panel))
    except Exception as e:
        print(f"[WARN] Failed to load admin panel activity from Redis: {e}")
    return found


@tasks.loop(seconds=60)
async def state_autosave():
    """Periodically flush in-memory config to Redis so it survives the next restart."""
    await _save_state_to_redis()


# --- Off-Render backups ------------------------------------------------------
# Redis on Render's free plan has no persistence, and a whole hosting
# account can disappear (it already happened once). So once every 24 h the
# bot saves all its data, gzipped, as a file in a private Discord channel it
# creates for itself, with the list of what changed since the previous
# one -- and on a start with an empty Redis, it finds the newest of those
# files and restores everything on its own.
BACKUP_CHANNEL_NAME = "yslem-backup"
BACKUP_FILE_RE = re.compile(r"^yslem-backup-\d{8}-\d{6}\.json\.gz$")
_backup_status = {"hash": None, "at": None, "url": None, "size": 0, "file": None, "restored_from": None}
# A changed configuration is saved within BACKUP_CHECK_MINUTES (but never more
# often than BACKUP_MIN_GAP), and once more when the service is stopped, so a
# restart or a deploy loses at most a few minutes. Old files are pruned: the
# newest BACKUP_KEEP_RECENT plus the newest of each of the last BACKUP_KEEP_DAYS days.
BACKUP_CHECK_MINUTES = 5
BACKUP_MIN_GAP = timedelta(minutes=10)
BACKUP_KEEP_RECENT = 30
BACKUP_KEEP_DAYS = 14
BACKUP_PRUNE_PER_PASS = 25
# Only False when backups exist but restoring them failed -- then no new
# (emptier) backup is written on top of the good ones.
_backups_allowed = True


def _find_backup_channel():
    wanted = os.environ.get("BACKUP_CHANNEL_ID", "").strip()
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if (str(channel.id) == wanted) if wanted else (channel.name == BACKUP_CHANNEL_NAME):
                perms = channel.permissions_for(guild.me)
                if perms.send_messages and perms.attach_files and perms.read_message_history:
                    return channel
    return None


async def _get_or_create_backup_channel():
    channel = _find_backup_channel()
    if channel is not None or os.environ.get("BACKUP_CHANNEL_ID", "").strip():
        return channel
    for guild in sorted(bot.guilds, key=lambda g: -(g.member_count or 0)):
        if not guild.me.guild_permissions.manage_channels:
            continue
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True, read_message_history=True,
            ),
        }
        try:
            channel = await guild.create_text_channel(
                BACKUP_CHANNEL_NAME, overwrites=overwrites,
                topic="Sauvegardes automatiques des données du bot -- ne pas supprimer ni écrire ici.",
                reason="Automatic data backups",
            )
            print(f"[OK] Created private backup channel #{channel.name} in '{guild.name}'")
            return channel
        except discord.HTTPException as e:
            print(f"[WARN] Couldn't create the backup channel in '{guild.name}': {e}")
    return None


def _backup_payload(state_json):
    body = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": state_json,
        "panel": admin_panel.tracker.dump(),
    }
    payload = gzip.compress(json.dumps(body).encode("utf-8"))
    return payload


BACKUP_INTERVAL = timedelta(hours=24)

_BACKUP_SECTION_LABELS = {
    "user_lang": "langues des membres", "bot_admins": "admins du bot",
    "guild_banned_words": "mots interdits", "log_channels": "salons de logs",
    "paypal_notify_channels": "salons PayPal", "crypto_notify_channels": "salons crypto",
    "antiraid_settings": "anti-raid", "screening_settings": "vérification des comptes", "key_system": "système de clés", "key_invites": "invitation du salon des clés", "ai_undo": "annulation IA", "antinuke_settings": "anti-nuke",
    "welcome_settings": "bienvenue", "warnings_store": "avertissements",
    "command_access": "accès aux commandes", "payment_info": "infos de paiement",
    "staff_payment_info": "paiements des staffs", "global_payment_info": "paiement (tous serveurs)", "ticket_counters": "numéros de tickets", "ticket_settings": "réglages tickets",
    "open_tickets": "tickets ouverts", "staffapp_settings": "réglages candidatures",
    "staff_applications": "candidatures", "staffapp_last_rejected": "délais de candidature",
    "yslemm_faq": "FAQ yslemm", "yslemm_silenced_channels": "salons où yslemm se tait",
    "recurring_reminders": "message récurrent", "economy_balances": "soldes de coins",
    "economy_last_daily": "daily", "automod_settings": "automodération", "antipub_settings": "anti-pub",
    "antipub_blacklist": "liste noire anti-pub", "antipub_whitelist_roles": "rôles exemptés anti-pub",
    "antipub_whitelist_channels": "salons exemptés anti-pub",
    "afk_status": "statuts AFK",
}


_LEGACY_STATE_KEYS = {"finder_settings", "file_index", "file_index_channels", "file_index_last_run"}


def _backup_changes(old_state, new_state):
    """Human-readable list of what changed between two saved states."""
    if old_state is None:
        return ["première sauvegarde : tout est inclus"]
    lines = []
    for key in sorted((set(old_state) | set(new_state)) - _LEGACY_STATE_KEYS):
        a, b = old_state.get(key), new_state.get(key)
        if a == b:
            continue
        label = _BACKUP_SECTION_LABELS.get(key, key)
        if isinstance(a, dict) or isinstance(b, dict):
            a, b = a if isinstance(a, dict) else {}, b if isinstance(b, dict) else {}
            added, removed = len(set(b) - set(a)), len(set(a) - set(b))
            modified = sum(1 for k in set(a) & set(b) if a[k] != b[k])
            parts = [f"+{added}" if added else "", f"-{removed}" if removed else "",
                     f"{modified} modifié(s)" if modified else ""]
            lines.append(f"{label} : {', '.join(p for p in parts if p) or 'modifié'}")
        elif isinstance(a, list) or isinstance(b, list):
            a, b = a or [], b or []
            lines.append(f"{label} : {len(a)} -> {len(b)}")
        else:
            lines.append(f"{label} : modifié")
    return lines


async def _previous_backup_state():
    """The state inside the newest backup, to compare against."""
    try:
        latest = await _latest_backup()
        if latest is None:
            return None
        data = json.loads(gzip.decompress(await latest[1].read()).decode("utf-8"))
        return json.loads(data["state"])
    except Exception as e:
        print(f"[WARN] Couldn't read the previous backup for the change list: {e}")
        return None


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return sorted((_canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def _state_digest(state_json):
    """Fingerprint of the saved configuration that ignores the order of list
    items (sets are saved as lists), so a restart does not look like a change."""
    canonical = json.dumps(_canonical(json.loads(state_json)), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _prune_backups(channel):
    """Delete the bot's own old backup files, keeping the newest
    BACKUP_KEEP_RECENT and the newest one of each of the last BACKUP_KEEP_DAYS days."""
    now = datetime.now(timezone.utc)
    kept_days, index, doomed = set(), 0, []
    async for msg in channel.history(limit=500):
        if bot.user is None or msg.author.id != bot.user.id:
            continue
        if not any(BACKUP_FILE_RE.match(a.filename) for a in msg.attachments):
            continue
        index += 1
        day = msg.created_at.date()
        recent = index <= BACKUP_KEEP_RECENT
        daily = (now - msg.created_at).days < BACKUP_KEEP_DAYS and day not in kept_days
        if recent or daily:
            kept_days.add(day)
        else:
            doomed.append(msg)
    for msg in doomed[:BACKUP_PRUNE_PER_PASS]:
        try:
            await msg.delete()
        except discord.HTTPException:
            break
        await asyncio.sleep(0.5)


_backup_soon_task = None


def _request_backup_soon(reason="clé", delay=15):
    """Save within a few seconds of an important change (a key issued, replaced,
    revoked...) instead of waiting for the 5-minute check, so a restart right
    afterwards loses nothing. Changes that come in during the delay share one backup."""
    global _backup_soon_task
    if _backup_soon_task is not None and not _backup_soon_task.done():
        return

    async def _run():
        await asyncio.sleep(delay)
        if not _backups_allowed:
            return
        try:
            await _make_backup(reason)
        except Exception as e:
            print(f"[WARN] Quick backup failed (the periodic one will retry): {e}")

    _backup_soon_task = asyncio.ensure_future(_run())


_backup_lock = None


async def _make_backup(reason="quotidienne", prune=True):
    """One backup at a time (the periodic check, a quick backup and the shutdown one can
    overlap), and a change-driven backup is skipped when the state was just saved."""
    global _backup_lock
    if _backup_lock is None:
        _backup_lock = asyncio.Lock()
    async with _backup_lock:
        if reason != "quotidienne" and _state_digest(_dump_state()) == _backup_status["hash"]:
            return None
        return await _make_backup_locked(reason, prune)


async def _make_backup_locked(reason="quotidienne", prune=True):
    """Sends a full backup file, with the list of everything that changed
    since the previous one. Returns the sent message, or None."""
    state_json = _dump_state()
    digest = _state_digest(state_json)
    channel = await _get_or_create_backup_channel()
    if channel is None:
        print("[WARN] No backup channel available -- data backup skipped")
        return None
    changes = _backup_changes(await _previous_backup_state(), json.loads(state_json))
    payload = _backup_payload(state_json)
    if len(payload) > 8 * 1024 * 1024:
        print(f"[WARN] The backup is {len(payload) // 1024} KB: close to Discord's upload limit, it may soon fail")
    name = f"yslem-backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json.gz"
    header = f"🗄️ Sauvegarde {reason} -- {max(1, len(payload) // 1024)} Ko\n"
    body = ("**Changements depuis la précédente :**\n" + "\n".join(f"• {line}" for line in changes)
            if changes else "Aucun changement depuis la précédente.")
    content = (header + body)[:1990]
    try:
        msg = await channel.send(content=content, file=discord.File(io.BytesIO(payload), filename=name))
    except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        # includes a connection dropped mid-upload (e.g. while the service is being replaced)
        print(f"[WARN] Backup upload failed: {e!r}")
        return None
    _backup_status.update(hash=digest, at=datetime.now(timezone.utc), url=msg.jump_url, size=len(payload), file=name)
    print(f"[OK] Data backup saved: {name} ({len(payload) // 1024} KB) in #{channel.name}")
    if prune:
        try:
            await _prune_backups(channel)
        except discord.HTTPException as e:
            print(f"[WARN] Couldn't prune old backups: {e}")
    return msg


async def _recent_backups(limit=5):
    """The bot's own newest backup files, newest first."""
    found = []
    channel = _find_backup_channel()
    if channel is None:
        return found
    async for msg in channel.history(limit=200):
        if bot.user is not None and msg.author.id != bot.user.id:
            continue
        for attachment in msg.attachments:
            if BACKUP_FILE_RE.match(attachment.filename):
                found.append((msg, attachment))
        if len(found) >= limit:
            break
    return found


async def _latest_backup():
    recent = await _recent_backups(1)
    return recent[0] if recent else None


async def _restore_backup_bytes(raw, source):
    data = json.loads(gzip.decompress(raw).decode("utf-8"))
    _load_state(data["state"])
    # What was just restored is, by definition, already backed up.
    _backup_status["hash"] = _state_digest(_dump_state())
    if data.get("panel"):
        try:
            admin_panel.tracker.load(data["panel"])
        except Exception as e:
            print(f"[WARN] Backup restored but panel history couldn't be: {e}")
    _backup_status["restored_from"] = source
    await _save_state_to_redis()
    print(f"[OK] Restored bot data from backup {source} (made {data.get('created_at', '?')})")


async def _auto_restore_from_backup():
    """Fresh start (empty Redis): bring everything back from the newest
    backup, if there is one. Never lets a failed restore be followed by
    an empty backup that would bury the good ones."""
    global _backups_allowed
    try:
        recent = await _recent_backups(5)
    except discord.HTTPException as e:
        print(f"[WARN] Couldn't look for data backups: {e}")
        _backups_allowed = False
        return
    if not recent:
        print("[OK] No data backup found yet -- starting fresh")
        return
    # Newest first; a damaged file just means trying the one before it.
    for msg, attachment in recent:
        try:
            await _restore_backup_bytes(await attachment.read(), attachment.filename)
            return
        except Exception as e:
            print(f"[WARN] Restoring {attachment.filename} failed, trying an older backup: {e}")
    _backups_allowed = False
    print("[WARN] No backup could be restored -- new backups paused so the existing ones aren't buried")


@tasks.loop(minutes=BACKUP_CHECK_MINUTES)
async def data_backup_loop():
    """Save the configuration whenever it changed (at most one backup per
    BACKUP_MIN_GAP), and at least one backup every 24 h even if it did not --
    measured from the newest backup file itself, so restarts and deploys
    neither skip a day nor pile up extra backups."""
    if not _backups_allowed:
        return
    now = datetime.now(timezone.utc)
    last = _backup_status["at"]
    if last is not None and now - last < BACKUP_MIN_GAP:
        return
    try:
        if _state_digest(_dump_state()) != _backup_status["hash"]:
            await _make_backup("automatique")
            return
        latest = await _latest_backup()
    except discord.HTTPException as e:
        print(f"[WARN] Couldn't check the last backup date: {e}")
        return
    if latest is None or now - latest[0].created_at >= BACKUP_INTERVAL:
        await _make_backup("quotidienne")


async def _graceful_shutdown():
    """Service stopping (Render sends SIGTERM on every deploy and restart):
    save once more so the last changes are not lost, then close cleanly."""
    try:
        if _backups_allowed and _state_loaded and _state_digest(_dump_state()) != _backup_status["hash"]:
            await asyncio.wait_for(_make_backup("avant arrêt", prune=False), timeout=20)
        await asyncio.wait_for(_save_state_to_redis(), timeout=5)
    except Exception as e:
        print(f"[WARN] Final backup before shutdown failed: {e}")
    await bot.close()


def _install_shutdown_handler():
    try:
        asyncio.get_running_loop().add_signal_handler(
            signal.SIGTERM, lambda: asyncio.ensure_future(_graceful_shutdown()))
    except (NotImplementedError, RuntimeError, ValueError):
        pass  # no signal support here (e.g. Windows): the periodic backup still runs


@tasks.loop(minutes=15)
async def ticket_inactivity_check():
    """Warn (repeatedly, every warn_hours), then auto-close + optionally
    mute the opener, on ticket channels they've gone quiet in. Only the
    opener's own messages count as activity here (see on_message) --
    staff replying doesn't reset the clock, since the point is to catch
    the opener going silent, not staff response time."""
    now = datetime.now(timezone.utc)
    for key, info in list(open_tickets.items()):
        guild_id, channel_id = key
        cfg = _ticket_cfg(guild_id)
        if not cfg["warn_hours"] and not cfg["close_hours"]:
            continue
        guild = bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild else None
        if channel is None:
            open_tickets.pop(key, None)
            continue
        try:
            last_activity = datetime.fromisoformat(info["last_activity"])
        except (KeyError, ValueError):
            continue
        idle_hours = (now - last_activity).total_seconds() / 3600
        mention = f"<@{info['opener_id']}>"

        if cfg["close_hours"] and idle_hours >= cfg["close_hours"]:
            muted = False
            if cfg["mute_on_close"]:
                opener = guild.get_member(info["opener_id"])
                if opener is not None and opener.id != guild.owner_id and not is_bot_admin_member(opener):
                    try:
                        await opener.timeout(
                            timedelta(minutes=cfg["mute_minutes"]),
                            reason="No response in their ticket before auto-close",
                        )
                        muted = True
                    except discord.HTTPException:
                        pass
            try:
                embed = _base_embed(t(0, "ticket.inactivity_close_title"), WARN_COLOR)
                description = t(0, "ticket.inactivity_close_description", mention=mention, close_hours=int(cfg["close_hours"]))
                if muted:
                    description += t(
                        0, "ticket.inactivity_close_muted_suffix",
                        mention=mention, mute_duration=_format_duration(cfg["mute_minutes"] * 60),
                    )
                embed.description = description
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass
            await _close_ticket_channel(channel, closer=None, automated_reason_key="ticket.reason_inactivity")
            continue

        if cfg["warn_hours"]:
            next_warn_at = cfg["warn_hours"] * (info["warn_count"] + 1)
            if next_warn_at < cfg["close_hours"] and idle_hours >= next_warn_at:
                info["warn_count"] += 1
                try:
                    embed = _base_embed(t(0, "ticket.inactivity_warn_title"), WARN_COLOR)
                    description = t(
                        0, "ticket.inactivity_warn_description",
                        mention=mention, hours=int(idle_hours), close_hours=int(cfg["close_hours"]),
                    )
                    if cfg["mute_on_close"]:
                        description += t(
                            0, "ticket.inactivity_mute_warn_suffix",
                            mute_duration=_format_duration(cfg["mute_minutes"] * 60),
                        )
                    embed.description = description
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass


@tasks.loop(minutes=1)
async def recurring_reminder_check():
    """Re-post each guild's configured recurring announcement once its
    interval has elapsed since the last send. Checks every minute (not
    every 5) specifically so a short interval like "every 4 minutes"
    actually fires close to on schedule -- at a 5-minute poll, anything
    configured under 5 minutes would only ever fire once every 5
    minutes regardless of what was set."""
    now = datetime.now(timezone.utc)
    for gid, cfg in list(recurring_reminders.items()):
        if cfg.get("paused"):
            continue
        guild = bot.get_guild(gid)
        if guild is None:
            continue
        channel = guild.get_channel(cfg["channel_id"])
        if channel is None:
            continue
        last_sent = datetime.fromisoformat(cfg["last_sent"])
        if (now - last_sent).total_seconds() < cfg["interval_minutes"] * 60:
            continue
        embed = _base_embed(t(0, "autoremind.post_title"), EMBED_COLOR)
        embed.description = cfg["message"]
        try:
            await channel.send(embed=embed)
            cfg["last_sent"] = now.isoformat()
        except discord.HTTPException:
            pass


# Public block explorer APIs, no key needed. litecoinspace.org is an Esplora
# fork for Litecoin -- same response shape as Blockstream's, so one code
# path handles both currencies.
_CRYPTO_EXPLORER_BASE = {
    "btc": "https://blockstream.info/api",
    "ltc": "https://litecoinspace.org/api",
}
_CRYPTO_UNITS_PER_COIN = 100_000_000  # satoshis / litoshis


def _addresses_to_watch():
    """Every BTC/LTC address currently configured anywhere (each staff
    member's own via !mypayment, or a guild's shared default via
    !setpayment), paired with whose it is so the notification can say who
    to credit -- deduped so one address shared by two configs isn't
    checked twice."""
    seen = set()
    results = []
    for uid, info in staff_payment_info.items():
        for currency in ("btc", "ltc"):
            address = (info.get(currency) or "").strip()
            if address and (currency, address) not in seen:
                seen.add((currency, address))
                results.append((currency, address, uid))
    for info in list(payment_info.values()) + [global_payment_info]:
        for currency in ("btc", "ltc"):
            address = (info.get(currency) or "").strip()
            if address and (currency, address) not in seen:
                seen.add((currency, address))
                results.append((currency, address, None))
    return results


async def _fetch_address_txs(session, currency, address):
    base = _CRYPTO_EXPLORER_BASE.get(currency)
    if base is None:
        return []
    try:
        async with session.get(f"{base}/address/{address}/txs", timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return []


def _tx_amount_to_address(tx, address):
    return sum(
        vout.get("value", 0) for vout in tx.get("vout", [])
        if vout.get("scriptpubkey_address") == address
    )


class CryptoPaymentConfirmView(discord.ui.View):
    """Attached to every crypto payment notification -- an Owner clicks
    ✅/❌ to record whether the payment actually matches what was expected
    (right amount, right ticket, etc). Purely a human confirmation on top
    of the automated on-chain detection -- the bot never decides this
    itself, same as it never decides to close a ticket on its own."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _resolve(self, interaction, received):
        if not is_bot_admin_member(interaction.user):
            await interaction.response.send_message(t(interaction.user.id, "error.not_bot_admin"), ephemeral=True)
            return
        embed = interaction.message.embeds[0]
        embed.color = SUCCESS_COLOR if received else ERROR_COLOR
        embed.add_field(
            name=t(0, "crypto.confirm_field"),
            value=t(0, "crypto.confirmed_yes" if received else "crypto.confirmed_no", user=interaction.user.mention),
            inline=False,
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="✅", style=discord.ButtonStyle.success, custom_id="crypto_confirm_yes")
    async def confirm_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, True)

    @discord.ui.button(emoji="❌", style=discord.ButtonStyle.danger, custom_id="crypto_confirm_no")
    async def confirm_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, False)


async def _post_crypto_payment_notification(currency, address, amount_units, confirmed, owner_id):
    amount_coin = amount_units / _CRYPTO_UNITS_PER_COIN
    for gid, cid in dict(crypto_notify_channels).items():
        guild = bot.get_guild(gid)
        if guild is None:
            continue
        channel = guild.get_channel(cid)
        if channel is None:
            continue
        embed = _base_embed(t(0, "crypto.notify_title"), SUCCESS_COLOR if confirmed else WARN_COLOR)
        embed.add_field(name=t(0, "crypto.notify_amount"), value=f"{amount_coin:.8f} {currency.upper()}", inline=True)
        embed.add_field(name=t(0, "crypto.notify_address"), value=f"`{address}`", inline=True)
        embed.add_field(
            name=t(0, "crypto.notify_status"),
            value=t(0, "crypto.status_confirmed" if confirmed else "crypto.status_pending"),
            inline=True,
        )
        if owner_id is not None:
            embed.add_field(name=t(0, "paypal.ipn_owner"), value=f"<@{owner_id}>", inline=True)
        try:
            await channel.send(embed=embed, view=CryptoPaymentConfirmView())
        except discord.HTTPException:
            pass


@tasks.loop(minutes=3)
async def crypto_payment_check():
    """Polls each configured BTC/LTC address for new incoming transactions.
    Unlike PayPal, a wallet/blockchain has no way to push a notification to
    us -- polling a public explorer is the only option. The first time an
    address is seen, its existing transactions are recorded silently (they
    predate this feature) so only genuinely new payments notify."""
    if not crypto_notify_channels:
        return
    addresses = _addresses_to_watch()
    if not addresses:
        return
    async with aiohttp.ClientSession() as session:
        for currency, address, owner_id in addresses:
            addr_key = f"{currency}:{address}"
            txs = await _fetch_address_txs(session, currency, address)
            if not txs:
                continue
            first_sight = addr_key not in _crypto_addresses_initialized
            for tx in txs:
                txid = tx.get("txid")
                if not txid:
                    continue
                txn_key = f"{currency}:{txid}:{address}"
                if txn_key in _seen_crypto_txids:
                    continue
                _seen_crypto_txids.add(txn_key)
                if len(_seen_crypto_txids) > 2000:
                    _seen_crypto_txids.clear()
                if first_sight:
                    continue
                amount = _tx_amount_to_address(tx, address)
                if amount <= 0:
                    continue
                confirmed = tx.get("status", {}).get("confirmed", False)
                await _post_crypto_payment_notification(currency, address, amount, confirmed, owner_id)
            _crypto_addresses_initialized.add(addr_key)


PRESENCE_ROTATION = [
    (discord.ActivityType.watching, "!help"),
    (discord.ActivityType.watching, "{guilds} servers"),
    (discord.ActivityType.listening, "/yslem"),
]


@tasks.loop(minutes=5)
async def rotate_presence():
    if _panel_presence is not None:
        return
    activity_type, template = PRESENCE_ROTATION[rotate_presence.current_loop % len(PRESENCE_ROTATION)]
    name = template.format(guilds=len(bot.guilds))
    await bot.change_presence(activity=discord.Activity(type=activity_type, name=name))


@tasks.loop(minutes=10)
async def keep_alive():
    """Self-ping the public URL to prevent Render free-tier sleep (15 min)."""
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)):
                pass
    except Exception:
        pass


def _base_embed(title, color=EMBED_COLOR):
    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    if bot.user is not None:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    return embed


def _payment_info_embed(uid, info):
    embed = _base_embed(t(uid, "payment.title"), EMBED_COLOR)
    if info.get("paypal"):
        embed.add_field(name="PayPal", value=info["paypal"], inline=False)
    if info.get("ltc"):
        embed.add_field(name="Litecoin (LTC)", value=f"`{info['ltc']}`", inline=False)
    if info.get("btc"):
        embed.add_field(name="Bitcoin (BTC)", value=f"`{info['btc']}`", inline=False)
    if info.get("roblox"):
        embed.add_field(name="Roblox", value=info["roblox"], inline=False)
    return embed


def _match_payment_method_answer(text):
    """Deterministic keyword match on the ticket form's payment-method
    answer -- same reasoning as the garam auto-detect fix: a fixed keyword
    match is reliable here, an LLM guess isn't needed for something this
    structured."""
    lowered = text.lower()
    if GARAM_RE.search(lowered) or "roblox" in lowered:
        return "roblox"
    if "paypal" in lowered:
        return "paypal"
    if "ltc" in lowered or "litecoin" in lowered:
        return "ltc"
    if "btc" in lowered or "bitcoin" in lowered:
        return "btc"
    return None


def _footer(embed, member):
    embed.set_footer(
        text=t(member.id, "footer.requested_by", name=member.display_name),
        icon_url=member.display_avatar.url,
    )
    return embed


def _format_duration(total_seconds):
    total_seconds = int(total_seconds)
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


async def _send_log(guild, embed):
    channel_id = log_channels.get(guild.id)
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        channel = guild.system_channel
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def _send_modlog(guild, embed):
    # Unlike _send_log (used for antiraid/antinuke alerts), this never falls
    # back to the system channel -- routine mod actions (kick/ban/warn/
    # automod) are frequent enough that silently posting them somewhere a
    # guild never asked for would be noise, not a safety feature.
    channel_id = log_channels.get(guild.id)
    if channel_id is None:
        return
    channel = guild.get_channel(channel_id)
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def _log_moderation(guild, moderator, title, description, color):
    embed = _base_embed(title, color)
    embed.description = description
    embed.set_footer(text=t(0, "modlog.by", name=str(moderator)))
    await _send_modlog(guild, embed)


WARN_AUTOBAN_THRESHOLD = 5


async def _check_warn_autoban(guild, member, key):
    """Common consequence for every warning source -- manual !warn/AI warn
    and automated anti-pub warnings alike: once a member's total hits the
    threshold, they're banned automatically. The server owner and bot
    admins are never auto-banned this way, no matter how many warnings
    pile up, same as they're exempt from other automated sanctions."""
    if member is None or len(warnings_store.get(key, [])) < WARN_AUTOBAN_THRESHOLD:
        return False
    if member.id == guild.owner_id or is_bot_admin_member(member):
        return False
    try:
        await guild.ban(member, reason=f"Automatic ban: reached {WARN_AUTOBAN_THRESHOLD} warnings")
    except discord.HTTPException:
        return False
    warnings_store.pop(key, None)
    await _log_moderation(
        guild, guild.me, t(0, "warn.autoban_title"),
        t(0, "warn.autoban_description", member=str(member), count=WARN_AUTOBAN_THRESHOLD), ERROR_COLOR,
    )
    return True


async def _get_audit_executor(guild, action):
    try:
        async for entry in guild.audit_logs(limit=5, action=action):
            if (datetime.now(timezone.utc) - entry.created_at).total_seconds() < 5:
                return entry.user
    except discord.Forbidden:
        return None
    return None


_SCREEN_GENERATED_NAME_RE = re.compile(r"\d{4,}$")


def _screening_cfg(guild_id):
    return screening_settings.setdefault(
        guild_id,
        {"enabled": False, "action": "log", "threshold": 5, "min_age_days": 7, "timeout_minutes": 60, "role_id": None, "quarantine_role_id": None},
    )


def _score_account(created_at, has_avatar, has_banner, name, min_age_days, burst=0):
    """Pure scoring of an account's public details -- shared by the join-time
    check and the verification panel so both judge an account the same way.
    has_banner may be None when it could not be looked up. Returns
    (score, reasons) where reasons is a list of (string key, format kwargs)."""
    score, reasons = 0, []
    age_days = (datetime.now(timezone.utc) - created_at).total_seconds() / 86400
    if age_days < 1:
        score += 3
        reasons.append(("screening.reason_age_day", {}))
    elif age_days < min_age_days:
        score += 2
        reasons.append(("screening.reason_age_young", {"days": min_age_days}))
    if not has_avatar:
        score += 2
        reasons.append(("screening.reason_avatar", {}))
    if has_banner is False:
        score += 1
        reasons.append(("screening.reason_banner", {}))
    if _SCREEN_GENERATED_NAME_RE.search(name or ""):
        score += 1
        reasons.append(("screening.reason_name", {}))
    if burst >= 6:
        score += 2
        reasons.append(("screening.reason_burst", {"points": 2}))
    elif burst >= 3:
        score += 1
        reasons.append(("screening.reason_burst", {"points": 1}))
    return score, reasons


async def _screen_member(member, cfg, count_join=True):
    """Score a joining member: public details of the account plus how many
    accounts joined in the last minute."""
    has_banner = None
    try:
        # The banner is only part of the full user profile, not of the member
        # object the gateway sends on join.
        user = await bot.fetch_user(member.id)
        has_banner = user.banner is not None
    except discord.HTTPException:
        pass
    burst = 0
    if count_join:  # not for a member who is only asking for a key
        now = time.time()
        joins = [ts for ts in _screening_joins.get(member.guild.id, []) if now - ts <= 60]
        joins.append(now)
        _screening_joins[member.guild.id] = joins
        burst = len(joins)
    return _score_account(member.created_at, member.avatar is not None, has_banner, member.name,
                          cfg["min_age_days"], burst=burst)


def _screening_reasons_text(uid, reasons):
    if not reasons:
        return t(uid, "screening.reasons_none")
    return "\n".join(t(uid, key, **kwargs) for key, kwargs in reasons)


async def _apply_screening_action(member, cfg, score, reasons):
    """Alert the staff about a flagged account and apply the configured
    action. Returns True when the member was kicked."""
    kicked = False
    action_key, action_kwargs = "screening.action_log", {}
    if cfg["action"] == "timeout":
        action_key, action_kwargs = "screening.action_timeout", {"minutes": cfg["timeout_minutes"]}
        try:
            await member.timeout(timedelta(minutes=cfg["timeout_minutes"]), reason="Account screening: suspicious account")
        except discord.HTTPException:
            action_key, action_kwargs = "screening.action_failed", {}
    elif cfg["action"] == "quarantine":
        role = member.guild.get_role(cfg.get("quarantine_role_id") or 0)
        action_key = "screening.action_quarantine"
        if role is None:
            action_key = "screening.action_failed"   # no quarantine role configured
        else:
            try:
                await member.add_roles(role, reason="Account screening: suspicious account")
            except discord.HTTPException:
                action_key = "screening.action_failed"
    elif cfg["action"] == "kick":
        action_key = "screening.action_kick"
        try:
            await member.kick(reason="Account screening: suspicious account")
            kicked = True
        except discord.HTTPException:
            action_key = "screening.action_failed"
    embed = _base_embed(t(0, "screening.flag_title"), WARN_COLOR)
    embed.description = t(
        0, "screening.flag_description", member=member.mention, id=member.id, score=score,
        threshold=cfg["threshold"], reasons=_screening_reasons_text(0, reasons),
        action=t(0, action_key, **action_kwargs),
    )
    await _send_log(member.guild, embed)
    return kicked


async def _screen_new_member(member):
    """Check a joining member. Returns True when they were kicked."""
    try:
        cfg = _screening_cfg(member.guild.id)
        if not cfg["enabled"]:
            return False
        score, reasons = await _screen_member(member, cfg)
        if score < cfg["threshold"]:
            return False
        return await _apply_screening_action(member, cfg, score, reasons)
    except Exception as e:
        print(f"[WARN] Account screening failed for {member.id}: {e}")
        return False


async def _handle_oauth_verification(guild_id, me):
    """Called (on the bot loop) once someone authorised the verification on
    Discord's page. `me` is their /users/@me identity (identify scope)."""
    guild = bot.get_guild(guild_id)
    if guild is None:
        return {"status": "error"}
    user_id = int(me["id"])
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.HTTPException:
            return {"status": "not_member"}
    cfg = _screening_cfg(guild_id)
    # Assign the verify role as soon as OAuth succeeds, before any score check.
    role = guild.get_role(cfg.get("role_id") or 0)
    if role is not None:
        try:
            await member.add_roles(role, reason="Verification passed")
        except discord.HTTPException:
            embed = _base_embed(t(0, "verify.role_failed_title"), WARN_COLOR)
            embed.description = t(0, "verify.role_failed", member=member.mention, role=role.mention)
            await _send_log(guild, embed)
    score, reasons = _score_account(
        member.created_at, me.get("avatar") is not None, me.get("banner") is not None,
        me.get("username") or member.name, cfg["min_age_days"],
    )
    if score >= cfg["threshold"]:
        await _apply_screening_action(member, cfg, score, reasons)
        return {"status": "review", "score": score}
    return {"status": "verified", "score": score}


async def _handle_raid(guild, entries, cfg):
    kicked = 0
    for _, member_id in entries:
        member = guild.get_member(member_id)
        if member is None:
            continue
        try:
            await member.kick(reason="Anti-raid: mass join detected")
            kicked += 1
        except discord.HTTPException:
            pass
    embed = discord.Embed(
        title=STRINGS[DEFAULT_LANG]["antiraid.triggered_title"],
        description=STRINGS[DEFAULT_LANG]["antiraid.triggered_description"].format(count=kicked, window=cfg["window"]),
        color=ERROR_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    await _send_log(guild, embed)


async def _punish_nuke(guild, member, executor, cfg):
    if member is not None:
        try:
            await member.edit(roles=[], reason="Anti-nuke: mass destructive actions detected")
        except discord.HTTPException:
            pass
        try:
            await member.kick(reason="Anti-nuke: mass destructive actions detected")
        except discord.HTTPException:
            pass
    embed = discord.Embed(
        title=STRINGS[DEFAULT_LANG]["antinuke.triggered_title"],
        description=STRINGS[DEFAULT_LANG]["antinuke.triggered_description"].format(
            member=str(executor), count=cfg["threshold"], window=cfg["window"]
        ),
        color=ERROR_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    await _send_log(guild, embed)


async def _register_nuke_action(guild, action):
    cfg = _antinuke_cfg(guild.id)
    if not cfg["enabled"]:
        return
    executor = await _get_audit_executor(guild, action)
    if executor is None or executor.id == bot.user.id:
        return
    if executor.id == guild.owner_id:
        return
    member = guild.get_member(executor.id)
    if member and is_bot_admin_member(member):
        return
    now = time.time()
    key = (guild.id, executor.id)
    entries = nuke_action_times.setdefault(key, [])
    entries.append(now)
    window = cfg["window"]
    nuke_action_times[key] = [ts for ts in entries if now - ts <= window]
    if len(nuke_action_times[key]) >= cfg["threshold"]:
        nuke_action_times[key] = []
        await _punish_nuke(guild, member, executor, cfg)


async def _handle_bot_join(member):
    """Anti-nuke's bot gate: a new bot account joining is either
    validated or rejected (kicked) by a staff member with Kick
    permission, via an @everyone-pinged alert -- a malicious bot
    addition is exactly the kind of thing that needs eyes on it
    immediately, not buried in a log channel nobody checks."""
    guild = member.guild
    cfg = _antinuke_cfg(guild.id)
    if not cfg["enabled"]:
        return
    channel_id = log_channels.get(guild.id)
    channel = guild.get_channel(channel_id) if channel_id else guild.system_channel
    if channel is None:
        return
    executor = await _get_audit_executor(guild, discord.AuditLogAction.bot_add)
    adder = str(executor) if executor is not None else STRINGS[DEFAULT_LANG]["antinuke.bot_join_unknown_adder"]
    embed = discord.Embed(
        title=STRINGS[DEFAULT_LANG]["antinuke.bot_join_title"],
        description=STRINGS[DEFAULT_LANG]["antinuke.bot_join_description"].format(
            bot=str(member), bot_id=member.id, adder=adder,
        ),
        color=WARN_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    view = BotJoinGateView(member)
    try:
        msg = await channel.send(
            content="@everyone", embed=embed, view=view,
            allowed_mentions=discord.AllowedMentions(everyone=True),
        )
        view.message = msg
    except discord.HTTPException:
        pass


async def _disable_and_stop(view, interaction):
    for item in view.children:
        item.disabled = True
    await interaction.response.edit_message(view=view)
    view.stop()


class OwnerOnlyView(discord.ui.View):
    """Base view that only reacts to the member who triggered the command."""

    def __init__(self, author, timeout=60):
        super().__init__(timeout=timeout)
        self.author = author
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message(t(interaction.user.id, "view.owner_only"), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


class HelpView(OwnerOnlyView):
    def __init__(self, author):
        super().__init__(author, timeout=90)
        self._set_active("home")
        for item in self.children:
            if item.custom_id == "lang_toggle":
                item.label = t(author.id, f"language.{_other_lang(author.id)}")

    def _set_active(self, active):
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id in ("home", "general", "fun", "moderation", "security"):
                item.style = discord.ButtonStyle.danger if item.custom_id == active else discord.ButtonStyle.secondary
        self.active = active

    def _home_embed(self):
        uid = self.author.id
        embed = _base_embed(t(uid, "help.title"))
        embed.description = t(uid, "help.description")
        embed.add_field(name=f"✨ {t(uid, 'help.general')}", value=t(uid, "help.general_desc"), inline=True)
        embed.add_field(name=f"🎲 {t(uid, 'help.fun')}", value=t(uid, "help.fun_desc"), inline=True)
        embed.add_field(name=f"🛡️ {t(uid, 'help.moderation')}", value=t(uid, "help.moderation_desc"), inline=True)
        embed.add_field(name=f"🔐 {t(uid, 'help.security')}", value=t(uid, "help.security_desc"), inline=True)
        if bot.user:
            embed.set_thumbnail(url=bot.user.display_avatar.url)
        return _footer(embed, self.author)

    def _general_embed(self):
        uid = self.author.id
        embed = _base_embed(t(uid, "help.general_title"))
        embed.add_field(name="!ping", value=t(uid, "cmd.ping"), inline=False)
        embed.add_field(name="!hello", value=t(uid, "cmd.hello"), inline=False)
        embed.add_field(name="!info", value=t(uid, "cmd.info"), inline=False)
        embed.add_field(name="!userinfo [@user]", value=t(uid, "cmd.userinfo"), inline=False)
        embed.add_field(name="!avatar [@user]", value=t(uid, "cmd.avatar"), inline=False)
        embed.add_field(name="!servericon", value=t(uid, "cmd.servericon"), inline=False)
        embed.add_field(name="!roleinfo <@role>", value=t(uid, "cmd.roleinfo"), inline=False)
        embed.add_field(name="!afk [reason]", value=t(uid, "cmd.afk"), inline=False)
        embed.add_field(name="!remind <minutes> <text>", value=t(uid, "cmd.remind"), inline=False)
        embed.add_field(name="!language <en|fr>", value=t(uid, "cmd.language"), inline=False)
        embed.add_field(name="!invite", value=t(uid, "cmd.invite"), inline=False)
        embed.add_field(name="!uptime", value=t(uid, "cmd.uptime"), inline=False)
        embed.add_field(name="/key user:<Roblox username>", value=t(uid, "cmd.key"), inline=False)
        embed.add_field(name="!yslem", value=t(uid, "cmd.yslem_about"), inline=False)
        embed.add_field(name="!balance [@user]", value=t(uid, "cmd.balance"), inline=False)
        embed.add_field(name="!daily", value=t(uid, "cmd.daily"), inline=False)
        embed.add_field(name="!pay @user <amount>", value=t(uid, "cmd.pay"), inline=False)
        embed.add_field(name="!leaderboard", value=t(uid, "cmd.leaderboard"), inline=False)
        embed.add_field(name="!perm", value=t(uid, "cmd.perm"), inline=False)
        return _footer(embed, self.author)

    def _fun_embed(self):
        uid = self.author.id
        embed = _base_embed(t(uid, "help.fun_title"))
        embed.add_field(name="!8ball <question>", value=t(uid, "cmd.8ball"), inline=False)
        embed.add_field(name="!coinflip", value=t(uid, "cmd.coinflip"), inline=False)
        embed.add_field(name="!dice [faces]", value=t(uid, "cmd.dice"), inline=False)
        embed.add_field(name="!poll [#channel] <question>", value=t(uid, "cmd.poll"), inline=False)
        return _footer(embed, self.author)

    def _moderation_embed(self):
        uid = self.author.id
        embed = _base_embed(t(uid, "help.moderation_title"), WARN_COLOR)
        embed.add_field(name="!clear [n]", value=t(uid, "cmd.clear"), inline=False)
        embed.add_field(name="!kick @user <reason>", value=t(uid, "cmd.kick"), inline=False)
        embed.add_field(name="!ban @user <reason>", value=t(uid, "cmd.ban"), inline=False)
        embed.add_field(name="!timeout @user <minutes> <reason>", value=t(uid, "cmd.timeout"), inline=False)
        embed.add_field(name="!untimeout @user", value=t(uid, "cmd.untimeout"), inline=False)
        embed.add_field(name="!say [#channel] <message>", value=t(uid, "cmd.say"), inline=False)
        embed.add_field(name="!yslemsay [#channel] <message>", value=t(uid, "cmd.yslemsay"), inline=False)
        embed.add_field(name="!ticketsetup [#channel]", value=t(uid, "cmd.ticketsetup"), inline=False)
        embed.add_field(name="!closetickets [#chan...]", value=t(uid, "cmd.closetickets"), inline=False)
        embed.add_field(name="!ticket config ...", value=t(uid, "cmd.ticketconfig"), inline=False)
        embed.add_field(name="!staffapplysetup [#channel]", value=t(uid, "cmd.staffapplysetup"), inline=False)
        embed.add_field(name="!closeapplications [#chan...]", value=t(uid, "cmd.closeapplications"), inline=False)
        embed.add_field(name="!staffapp config ...", value=t(uid, "cmd.staffappconfig"), inline=False)
        embed.add_field(name="!yslemmfaq add|remove|list", value=t(uid, "cmd.yslemmfaq"), inline=False)
        embed.add_field(name="!automod on|off|status", value=t(uid, "cmd.automod_desc"), inline=False)
        return _footer(embed, self.author)

    def _security_embed(self):
        uid = self.author.id
        embed = _base_embed(t(uid, "help.security_title"), WARN_COLOR)
        embed.add_field(name="!botadmin", value=t(uid, "cmd.botadmin"), inline=False)
        embed.add_field(name="!antiraid on|off|config", value=t(uid, "cmd.antiraid"), inline=False)
        embed.add_field(name="!screening on|off|action|threshold|minage|timeout", value=t(uid, "cmd.screening"), inline=False)
        embed.add_field(name="!screen <@member>", value=t(uid, "cmd.screen"), inline=False)
        embed.add_field(name="/verify", value=t(uid, "cmd.verify"), inline=False)
        embed.add_field(name="!keysetup", value=t(uid, "cmd.keysetup"), inline=False)
        embed.add_field(name="!antinuke on|off|config", value=t(uid, "cmd.antinuke"), inline=False)
        embed.add_field(name="!welcome setup|on|off|channel|message|title|image|test", value=t(uid, "cmd.welcome"), inline=False)
        embed.add_field(name="!bye setup|on|off|channel|message|title|image|test", value=t(uid, "cmd.bye"), inline=False)
        embed.add_field(name="!words list|add|remove", value=t(uid, "cmd.words"), inline=False)
        embed.add_field(name="!createrole <name>", value=t(uid, "cmd.createrole"), inline=False)
        embed.add_field(name="!createchannel [category] <name>", value=t(uid, "cmd.createchannel"), inline=False)
        embed.add_field(name="/aibuild <request>", value=t(uid, "cmd.aibuild"), inline=False)
        embed.add_field(name="/aiundo", value=t(uid, "cmd.aiundo"), inline=False)
        embed.add_field(name="!setlogchannel [#channel]", value=t(uid, "cmd.setlogchannel"), inline=False)
        embed.add_field(name="!logs [#channel]", value=t(uid, "cmd.logs"), inline=False)
        embed.add_field(
            name="!setpaypalchannel / !setcryptochannel [#channel]",
            value=t(uid, "cmd.setpaymentchannels"),
            inline=False,
        )
        embed.add_field(name="!autoremind set|stop|pause|unpause", value=t(uid, "cmd.autoremind"), inline=False)
        embed.add_field(name="!warn @user <reason>", value=t(uid, "cmd.warn"), inline=False)
        embed.add_field(name="!warnings [@user]", value=t(uid, "cmd.warnings"), inline=False)
        embed.add_field(name="!clearwarnings @user", value=t(uid, "cmd.clearwarnings"), inline=False)
        embed.add_field(name="!lock / !unlock", value=t(uid, "cmd.lock"), inline=False)
        embed.add_field(name="!slowmode <seconds>", value=t(uid, "cmd.slowmode"), inline=False)
        embed.add_field(name="!cmdaccess allow|remove|reset|list", value=t(uid, "cmd.cmdaccess"), inline=False)
        embed.add_field(name="!setpayment paypal|ltc|btc|roblox <value>", value=t(uid, "cmd.setpayment"), inline=False)
        embed.add_field(name="!payment [@user]", value=t(uid, "cmd.payment"), inline=False)
        embed.add_field(name="!mypayment paypal|ltc|btc|roblox <value>|clear", value=t(uid, "cmd.mypayment"), inline=False)
        embed.add_field(name="!antipub on|off|config|blacklist|whitelist", value=t(uid, "cmd.antipub"), inline=False)
        embed.add_field(name="!addcoins / !removecoins @user <amount>", value=t(uid, "cmd.addcoins"), inline=False)
        embed.add_field(name="!saveconfig", value=t(uid, "cmd.saveconfig"), inline=False)
        return _footer(embed, self.author)

    def _current_embed(self):
        return {
            "home": self._home_embed,
            "general": self._general_embed,
            "fun": self._fun_embed,
            "moderation": self._moderation_embed,
            "security": self._security_embed,
        }[self.active]()

    @discord.ui.button(label="Home", emoji="🏠", custom_id="home", style=discord.ButtonStyle.danger, row=0)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_active("home")
        await interaction.response.edit_message(embed=self._home_embed(), view=self)

    @discord.ui.button(label="General", emoji="✨", custom_id="general", style=discord.ButtonStyle.secondary, row=0)
    async def general(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_active("general")
        await interaction.response.edit_message(embed=self._general_embed(), view=self)

    @discord.ui.button(label="Fun", emoji="🎲", custom_id="fun", style=discord.ButtonStyle.secondary, row=0)
    async def fun(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_active("fun")
        await interaction.response.edit_message(embed=self._fun_embed(), view=self)

    @discord.ui.button(label="Moderation", emoji="🛡️", custom_id="moderation", style=discord.ButtonStyle.secondary, row=0)
    async def moderation(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_active("moderation")
        await interaction.response.edit_message(embed=self._moderation_embed(), view=self)

    @discord.ui.button(label="Security", emoji="🔐", custom_id="security", style=discord.ButtonStyle.secondary, row=0)
    async def security(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_active("security")
        await interaction.response.edit_message(embed=self._security_embed(), view=self)

    @discord.ui.button(label="Language", emoji="🌐", custom_id="lang_toggle", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_language(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_lang[interaction.user.id] = "fr" if lang_of(interaction.user.id) == "en" else "en"
        button.label = t(interaction.user.id, f"language.{_other_lang(interaction.user.id)}")
        await interaction.response.edit_message(embed=self._current_embed(), view=self)


class YslemAboutView(OwnerOnlyView):
    """Interactive overview of the bot's major systems (AI, economy,
    moderation/security, admin) -- a guided introduction, not a full
    per-command reference (that's /help)."""

    def __init__(self, author):
        super().__init__(author, timeout=90)
        self._set_active("about_home")
        for item in self.children:
            if item.custom_id == "about_lang_toggle":
                item.label = t(author.id, f"language.{_other_lang(author.id)}")

    def _set_active(self, active):
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id in ("about_home", "about_ai", "about_economy", "about_moderation", "about_admin"):
                item.style = discord.ButtonStyle.danger if item.custom_id == active else discord.ButtonStyle.secondary
        self.active = active

    def _home_embed(self):
        uid = self.author.id
        embed = _base_embed(t(uid, "about.home_title"))
        embed.description = t(uid, "about.home_description")
        embed.add_field(name=t(uid, "about.field_ai"), value=t(uid, "about.field_ai_desc"), inline=True)
        embed.add_field(name=t(uid, "about.field_economy"), value=t(uid, "about.field_economy_desc"), inline=True)
        embed.add_field(name=t(uid, "about.field_tickets"), value=t(uid, "about.field_tickets_desc"), inline=True)
        embed.add_field(name=t(uid, "about.field_moderation"), value=t(uid, "about.field_moderation_desc"), inline=True)
        embed.add_field(name=t(uid, "about.field_admin"), value=t(uid, "about.field_admin_desc"), inline=True)
        embed.add_field(name=t(uid, "about.field_utility"), value=t(uid, "about.field_utility_desc"), inline=True)
        embed.add_field(name=t(uid, "about.field_transparency"), value=t(uid, "about.field_transparency_desc"), inline=False)
        return _footer(embed, self.author)

    def _ai_embed(self):
        uid = self.author.id
        embed = _base_embed(t(uid, "about.ai_title"))
        embed.add_field(name=t(uid, "about.ai_talk_name"), value=t(uid, "about.ai_talk_value"), inline=False)
        embed.add_field(name=t(uid, "about.ai_understand_name"), value=t(uid, "about.ai_understand_value"), inline=False)
        embed.add_field(name=t(uid, "about.ai_convo_name"), value=t(uid, "about.ai_convo_value"), inline=False)
        embed.add_field(name=t(uid, "about.ai_safety_name"), value=t(uid, "about.ai_safety_value"), inline=False)
        return _footer(embed, self.author)

    def _economy_embed(self):
        uid = self.author.id
        embed = _base_embed(t(uid, "about.economy_title"))
        embed.add_field(name="!balance [@user]", value=t(uid, "cmd.balance"), inline=False)
        embed.add_field(name="!daily", value=t(uid, "cmd.daily"), inline=False)
        embed.add_field(name="!pay @user <amount>", value=t(uid, "cmd.pay"), inline=False)
        embed.add_field(name="!leaderboard", value=t(uid, "cmd.leaderboard"), inline=False)
        embed.add_field(name="!addcoins / !removecoins @user <amount>", value=t(uid, "cmd.addcoins"), inline=False)
        return _footer(embed, self.author)

    def _moderation_embed(self):
        uid = self.author.id
        embed = _base_embed(t(uid, "help.moderation_title"), WARN_COLOR)
        embed.add_field(name="!mute @user <minutes>", value=t(uid, "about.mod_mute"), inline=False)
        embed.add_field(name="!kick @user", value=t(uid, "cmd.kick"), inline=False)
        embed.add_field(name="!ban @user", value=t(uid, "cmd.ban"), inline=False)
        embed.add_field(name="!warn @user", value=t(uid, "cmd.warn"), inline=False)
        embed.add_field(name="!clearwarnings @user", value=t(uid, "cmd.clearwarnings"), inline=False)
        embed.add_field(name="!lock / !unlock", value=t(uid, "cmd.lock"), inline=False)
        embed.add_field(name="!slowmode <seconds>", value=t(uid, "cmd.slowmode"), inline=False)
        embed.add_field(name="!antiraid", value=t(uid, "cmd.antiraid"), inline=False)
        embed.add_field(name="!screening", value=t(uid, "cmd.screening"), inline=False)
        embed.add_field(name="!screen <@member>", value=t(uid, "cmd.screen"), inline=False)
        embed.add_field(name="/verify", value=t(uid, "cmd.verify"), inline=False)
        embed.add_field(name="!keysetup", value=t(uid, "cmd.keysetup"), inline=False)
        embed.add_field(name="!antinuke", value=t(uid, "cmd.antinuke"), inline=False)
        embed.add_field(name="!antipub", value=t(uid, "cmd.antipub"), inline=False)
        embed.add_field(name="!words add|remove|list", value=t(uid, "cmd.words"), inline=False)
        embed.add_field(name="!ticket config", value=t(uid, "about.mod_ticket"), inline=False)
        return _footer(embed, self.author)

    def _admin_embed(self):
        uid = self.author.id
        embed = _base_embed(t(uid, "about.admin_title"), WARN_COLOR)
        embed.description = t(uid, "about.admin_note")
        embed.add_field(name="!botadmin adduser|addrole|...", value=t(uid, "cmd.botadmin"), inline=False)
        embed.add_field(name="!cmdaccess allow|remove|reset|list", value=t(uid, "cmd.cmdaccess"), inline=False)
        embed.add_field(name="!setlogchannel #channel", value=t(uid, "cmd.setlogchannel"), inline=False)
        embed.add_field(name="!logs [#channel]", value=t(uid, "cmd.logs"), inline=False)
        embed.add_field(name="!setpaypalchannel [#channel]", value=t(uid, "cmd.setpaypalchannel"), inline=False)
        embed.add_field(name="!setcryptochannel [#channel]", value=t(uid, "cmd.setcryptochannel"), inline=False)
        embed.add_field(name="!autoremind set|stop|pause|unpause", value=t(uid, "cmd.autoremind"), inline=False)
        embed.add_field(name="!welcome ...", value=t(uid, "cmd.welcome"), inline=False)
        embed.add_field(name="!bye ...", value=t(uid, "cmd.bye"), inline=False)
        embed.add_field(name="!setpayment paypal|ltc|btc|roblox <value>", value=t(uid, "cmd.setpayment"), inline=False)
        embed.add_field(name="!payment [@user]", value=t(uid, "cmd.payment"), inline=False)
        embed.add_field(name="!mypayment paypal|ltc|btc|roblox <value>|clear", value=t(uid, "cmd.mypayment"), inline=False)
        embed.add_field(name="!yslemmfaq add|remove|list", value=t(uid, "cmd.yslemmfaq"), inline=False)
        return _footer(embed, self.author)

    def _current_embed(self):
        return {
            "about_home": self._home_embed,
            "about_ai": self._ai_embed,
            "about_economy": self._economy_embed,
            "about_moderation": self._moderation_embed,
            "about_admin": self._admin_embed,
        }[self.active]()

    @discord.ui.button(label="Home", emoji="🏠", custom_id="about_home", style=discord.ButtonStyle.danger, row=0)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_active("about_home")
        await interaction.response.edit_message(embed=self._home_embed(), view=self)

    @discord.ui.button(label="AI", emoji="🤖", custom_id="about_ai", style=discord.ButtonStyle.secondary, row=0)
    async def ai(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_active("about_ai")
        await interaction.response.edit_message(embed=self._ai_embed(), view=self)

    @discord.ui.button(label="Economy", emoji="💰", custom_id="about_economy", style=discord.ButtonStyle.secondary, row=0)
    async def economy(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_active("about_economy")
        await interaction.response.edit_message(embed=self._economy_embed(), view=self)

    @discord.ui.button(label="Moderation", emoji="🛡️", custom_id="about_moderation", style=discord.ButtonStyle.secondary, row=0)
    async def moderation(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_active("about_moderation")
        await interaction.response.edit_message(embed=self._moderation_embed(), view=self)

    @discord.ui.button(label="Admin", emoji="👑", custom_id="about_admin", style=discord.ButtonStyle.secondary, row=0)
    async def admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_active("about_admin")
        await interaction.response.edit_message(embed=self._admin_embed(), view=self)

    @discord.ui.button(label="Language", emoji="🌐", custom_id="about_lang_toggle", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_language(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_lang[interaction.user.id] = "fr" if lang_of(interaction.user.id) == "en" else "en"
        button.label = t(interaction.user.id, f"language.{_other_lang(interaction.user.id)}")
        await interaction.response.edit_message(embed=self._current_embed(), view=self)


class ConfirmView(OwnerOnlyView):
    def __init__(self, author, timeout=30):
        super().__init__(author, timeout=timeout)
        self.value = None
        self.children[0].label = t(author.id, "confirm.confirm")
        self.children[1].label = t(author.id, "confirm.cancel")

    @discord.ui.button(emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await _disable_and_stop(self, interaction)

    @discord.ui.button(emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await _disable_and_stop(self, interaction)


class BotJoinGateView(discord.ui.View):
    """Anti-nuke's bot-join gate. Not owner-restricted -- any staff member
    with Kick permission can resolve it, not just whoever the bot happened
    to notify. No timeout: it should stay actionable until someone
    actually looks at it, not silently expire."""

    def __init__(self, member):
        super().__init__(timeout=None)
        self.member = member
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message(t(interaction.user.id, "error.no_permission"), ephemeral=True)
            return False
        return True

    @staticmethod
    def _resolved_embed(interaction, key, moderator):
        embed = interaction.message.embeds[0]
        embed.add_field(name=t(0, "antinuke.bot_join_resolved_by"), value=t(0, key, moderator=str(moderator)), inline=False)
        return embed

    @discord.ui.button(label="Validate", emoji="✅", style=discord.ButtonStyle.success, custom_id="botgate_validate")
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self._resolved_embed(interaction, "antinuke.bot_join_validated", interaction.user)
        embed.color = SUCCESS_COLOR
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Reject", emoji="❌", style=discord.ButtonStyle.danger, custom_id="botgate_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.member.kick(reason=f"Rejected via anti-nuke bot gate by {interaction.user}")
            embed = self._resolved_embed(interaction, "antinuke.bot_join_rejected", interaction.user)
        except discord.HTTPException:
            embed = self._resolved_embed(interaction, "antinuke.bot_join_reject_failed", interaction.user)
        embed.color = ERROR_COLOR
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


class RefreshPingView(OwnerOnlyView):
    def __init__(self, author, timeout=60):
        super().__init__(author, timeout=timeout)
        self.children[0].label = t(author.id, "ping.refresh")

    @discord.ui.button(emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=_ping_embed(self.author), view=self)


class PollView(discord.ui.View):
    def __init__(self, question, author):
        super().__init__(timeout=3600)
        self.question = question
        self.author = author
        self.votes = {}  # user_id -> bool
        self.message = None
        self.children[0].label = t(author.id, "poll.for")
        self.children[1].label = t(author.id, "poll.against")

    def _bar(self, pct, length=14):
        filled = round(length * pct / 100)
        return "🟥" * filled + "⬛" * (length - filled)

    def _embed(self):
        uid = self.author.id
        pour = sum(1 for v in self.votes.values() if v)
        contre = sum(1 for v in self.votes.values() if not v)
        total = pour + contre
        pour_pct = int(pour / total * 100) if total else 0
        contre_pct = 100 - pour_pct if total else 0
        embed = _base_embed(t(uid, "poll.title"), EMBED_COLOR)
        embed.description = f"**{self.question}**"
        embed.add_field(name=f"👍 {t(uid, 'poll.for')} — {pour} ({pour_pct}%)", value=self._bar(pour_pct), inline=False)
        embed.add_field(name=f"👎 {t(uid, 'poll.against')} — {contre} ({contre_pct}%)", value=self._bar(contre_pct), inline=False)
        embed.set_footer(text=t(uid, "poll.footer", author=self.author.display_name, total=total))
        return embed

    async def _vote(self, interaction, value):
        self.votes[interaction.user.id] = value
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(emoji="👍", style=discord.ButtonStyle.danger)
    async def pour(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, True)

    @discord.ui.button(emoji="👎", style=discord.ButtonStyle.secondary)
    async def contre(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, False)

    async def on_timeout(self):
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


# Mirrors the catalog yslemm's system prompt knows (see
# _yslemm_llm_system_prompt) -- kept as a simple substring-match dict here
# so a ticket category that names one of these products can show its
# price and full payment methods right in the ticket, not just
# something the AI has to recall. "Brainrot" is a Roblox game's
# in-game currency/items, not a separate payment network -- paying
# with it is tied to the buyer's Roblox account.
SHOP_CATALOG = {
    "partnership": {
        "name": "🤝 Partnership",
        "price": "3€/$",
        "methods": "PayPal · 3€/$ -- Crypto · 3€/$ -- Brainrot (Roblox) · 2 garams",
    },
    "paid sources": {
        "name": "📦 Paid Sources",
        "price": "3€/$",
        "methods": "PayPal · 3€/$ -- Crypto · 3€/$ -- Brainrot (Roblox) · 2 garama",
    },
    "moon duels": {
        "name": "⚔️ Moon Duels",
        "price": "5€/$",
        "methods": (
            "PayPal · 5€/$ -- Crypto · 5€/$ -- Brainrot (Roblox) · 3 garama -- Nitro accepted\n"
            "MM2: Lifetime = Godly/Ice Breaker -- Limited = zombie/fire effect"
        ),
    },
    "auto code": {
        "name": "⚙️ Auto Code",
        "price": "7€/$",
        "methods": (
            "PayPal · 7€/$ -- Crypto · 7€/$ -- Nitro accepted\n"
            "Brainrot (Roblox): 1 day = 2 garama -- 1 week = 3 garama -- Lifetime = 4 garama\n"
            "MM2: Lifetime = Godly/Ice Breaker -- Limited = zombie/fire effect"
        ),
    },
}


def _shop_price_for_category(category_name):
    lowered = category_name.lower()
    for key, product in SHOP_CATALOG.items():
        if key in lowered:
            return product["price"]
    return None


def _shop_methods_for_category(category_name):
    lowered = category_name.lower()
    for key, product in SHOP_CATALOG.items():
        if key in lowered:
            return product["methods"]
    return None


def _is_support_category(category_name):
    """No shop product behind the category (Support, Help...): a support ticket."""
    return not category_name or _shop_price_for_category(category_name) is None


def _ticket_is_support(info):
    return _is_support_category(info.get("category"))


def _shop_catalog_embed(uid):
    embed = _base_embed(t(uid, "ticket.prices_title"), EMBED_COLOR)
    for product in SHOP_CATALOG.values():
        embed.add_field(name=f"{product['name']} -- {product['price']}", value=product["methods"], inline=False)
    return embed


class TicketModal(discord.ui.Modal):
    def __init__(self, uid, category=None):
        self.support = _is_support_category(category)
        super().__init__(title=t(uid, "ticket.modal_title_support" if self.support else "ticket.modal_title"))
        self.category = category
        if self.support:
            self.subject_input = discord.ui.TextInput(
                label=t(uid, "ticket.q_subject"), placeholder=t(uid, "ticket.q_subject_placeholder"),
                max_length=100, required=True)
            self.problem_input = discord.ui.TextInput(
                label=t(uid, "ticket.q_problem"), placeholder=t(uid, "ticket.q_problem_placeholder"),
                style=discord.TextStyle.paragraph, max_length=1000, required=True)
            self.add_item(self.subject_input)
            self.add_item(self.problem_input)
            return
        self.payment_input = discord.ui.TextInput(
            label=t(uid, "ticket.q_payment"),
            placeholder=t(uid, "ticket.q_payment_placeholder"),
            max_length=100,
            required=True,
        )
        self.duration_input = discord.ui.TextInput(
            label=t(uid, "ticket.q_duration"),
            placeholder=t(uid, "ticket.q_duration_placeholder"),
            max_length=100,
            required=False,
        )
        self.offer_input = discord.ui.TextInput(
            label=t(uid, "ticket.q_offer"),
            placeholder=t(uid, "ticket.q_offer_placeholder"),
            max_length=100,
            required=False,
        )
        for item in (self.payment_input, self.duration_input, self.offer_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if self.support:
            answers = {"support": True, "subject": self.subject_input.value.strip(),
                       "problem": self.problem_input.value.strip()}
            return await _create_ticket_channel(interaction, answers, self.category)
        answers = {
            "payment": self.payment_input.value,
            "duration": self.duration_input.value.strip(),
            "offer": self.offer_input.value.strip(),
        }
        await _create_ticket_channel(interaction, answers, self.category)


def _ticket_kind_categories(cfg, kind):
    """Categories offered by the Support or Buy button of the panel."""
    support = [c for c in cfg["categories"] if _is_support_category(c)]
    if kind == "support":
        return support or ["Support"]
    shop = [c for c in cfg["categories"] if not _is_support_category(c)]
    return shop or [key.title() for key in SHOP_CATALOG]


async def _proceed_to_ticket_category_or_modal(interaction: discord.Interaction, kind="support"):
    categories = _ticket_kind_categories(_ticket_cfg(interaction.guild.id), kind)
    if len(categories) > 1:
        view = TicketCategoryView(interaction.user.id, categories)
        extra = {"embed": _shop_catalog_embed(interaction.user.id)} if kind == "buy" else {}
        await interaction.response.send_message(
            t(interaction.user.id, "ticket.choose_category"), view=view, ephemeral=True, **extra)
    else:
        await interaction.response.send_modal(TicketModal(interaction.user.id, categories[0]))


class TicketLanguageView(discord.ui.View):
    """First step of opening a ticket: which language the rest of the flow
    (category picker, form questions, and the ticket's own embed) should be
    in. Setting user_lang here as a side effect is what makes every
    downstream t()-based string in the flow automatically follow this
    choice, with nothing else needing a language parameter threaded
    through it."""

    def __init__(self, kind="support"):
        super().__init__(timeout=120)
        self.kind = kind

    async def _choose(self, interaction: discord.Interaction, lang):
        user_lang[interaction.user.id] = lang
        await _proceed_to_ticket_category_or_modal(interaction, self.kind)

    @discord.ui.button(emoji="🇫🇷", label="Français", style=discord.ButtonStyle.secondary, custom_id="ticket_lang_fr")
    async def lang_fr(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "fr")

    @discord.ui.button(emoji="🇬🇧", label="English", style=discord.ButtonStyle.secondary, custom_id="ticket_lang_en")
    async def lang_en(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "en")

    @discord.ui.button(emoji="🇪🇸", label="Español", style=discord.ButtonStyle.secondary, custom_id="ticket_lang_es")
    async def lang_es(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "es")

    @discord.ui.button(emoji="🇸🇦", label="العربية", style=discord.ButtonStyle.secondary, custom_id="ticket_lang_ar")
    async def lang_ar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "ar")

    @discord.ui.button(emoji="🇵🇹", label="Português", style=discord.ButtonStyle.secondary, custom_id="ticket_lang_pt")
    async def lang_pt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "pt")


class TicketCategorySelect(discord.ui.Select):
    def __init__(self, uid, categories):
        options = [discord.SelectOption(label=c) for c in categories[:25]]
        super().__init__(placeholder=t(uid, "ticket.category_placeholder"), options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketModal(interaction.user.id, self.values[0]))


class TicketCategoryView(discord.ui.View):
    def __init__(self, uid, categories):
        super().__init__(timeout=60)
        self.add_item(TicketCategorySelect(uid, categories))


# ---------------------------------------------------------------------------
# Tickets v2: zero-config setup, numbered tickets, claim / release, close with a
# reason + transcript + rating, staff tools, and ONE payment-info command that
# works the same in every server.
# ---------------------------------------------------------------------------

PAYMENT_FIELDS = ("paypal", "ltc", "btc", "roblox")
PAYMENT_LABELS = {"paypal": "PayPal", "ltc": "Litecoin (LTC)", "btc": "Bitcoin (BTC)", "roblox": "Roblox"}
TICKET_LOG_CHANNEL_NAME = "ticket-logs"
TRANSCRIPT_MAX_MESSAGES = 3000
TRANSCRIPT_MAX_CHARS = 3_500_000


def _clean_payment_value(value):
    return (value or "").strip().strip("`").strip()[:200]


def _is_ticket_staff(member):
    """Anyone who may handle tickets: bot admins, Manage Channels, or a ticket staff role."""
    if is_bot_admin_member(member) or member.guild_permissions.manage_channels:
        return True
    cfg = ticket_settings.get(member.guild.id)
    return bool(cfg and any(r.id in cfg["staff_role_ids"] for r in member.roles))


def _payment_layers(guild_id, channel_id=None, staff_id=None):
    """field -> (value, source). Layers, weakest first: everywhere (bot-wide), this
    server, then the staff member who owns the ticket (or who is asking). A field a
    layer leaves empty falls through to the one below, so the same info is available
    in every server without any per-server setup."""
    layers = {}
    for source, data in (("everywhere", global_payment_info), ("server", payment_info.get(guild_id, {}))):
        for field in PAYMENT_FIELDS:
            if data.get(field):
                layers[field] = (data[field], source)
    ticket = open_tickets.get((guild_id, channel_id)) if channel_id is not None else None
    owner = (ticket.get("claimed_by") if ticket else None) or staff_id
    if owner:
        for field in PAYMENT_FIELDS:
            value = staff_payment_info.get(owner, {}).get(field)
            if value:
                layers[field] = (value, "staff")
    return layers


def _resolve_payment_info(guild_id, channel_id, staff_id=None):
    return {field: value for field, (value, _src) in _payment_layers(guild_id, channel_id, staff_id).items()}


def _payment_layers_embed(uid, layers, sources=False):
    embed = _payment_info_embed(uid, {f: v for f, (v, _s) in layers.items()})
    if layers and sources:
        embed.set_footer(text=" · ".join(
            f"{PAYMENT_LABELS[f]}: {t(uid, 'payinfo.src_' + layers[f][1])}" for f in PAYMENT_FIELDS if f in layers))
    return embed


def _payinfo_scope_target(actor, guild, scope):
    """(dict to edit, error key) for a scope: me | server | everywhere."""
    if scope == "everywhere":
        if actor.id != BOT_OWNER_ID:
            return None, "payinfo.owner_only"
        return global_payment_info, None
    if scope == "server":
        if not is_bot_admin_member(actor):
            return None, "error.not_bot_admin"
        return payment_info.setdefault(guild.id, {}), None
    if not _is_ticket_staff(actor):
        return None, "payinfo.staff_only"
    return staff_payment_info.setdefault(actor.id, {}), None


async def _payinfo_run(actor, guild, channel, values, scope="me"):
    """Shared by !payinfo and /payinfo. Returns (text, embed, public).
    Sets any given fields ('-' removes one), then shows the info that applies here --
    inside a ticket that is the ticket's info, posted for the customer to see."""
    uid = actor.id
    if not _is_ticket_staff(actor):
        return t(uid, "payinfo.staff_only"), None, False
    scope = scope if scope in ("me", "server", "everywhere") else "me"
    given = {f: v for f, v in values.items() if f in PAYMENT_FIELDS and v is not None and v.strip()}
    changed = []
    if given:
        target, err = _payinfo_scope_target(actor, guild, scope)
        if err:
            return t(uid, err), None, False
        for field, raw in given.items():
            if raw.strip() == "-":
                target.pop(field, None)
            else:
                target[field] = _clean_payment_value(raw)
            changed.append(PAYMENT_LABELS[field])
        _request_backup_soon("paiement")
    key = (guild.id, channel.id)
    ticket = open_tickets.get(key)
    text = t(uid, "payinfo.saved_" + scope, fields=", ".join(changed)) if changed else None
    if ticket is not None and _is_ticket_staff(actor):
        if not ticket.get("claimed_by"):
            await _apply_claim(channel, ticket, actor)
            text = (text + "\n" if text else "") + t(uid, "payinfo.auto_claimed")
        layers = _payment_layers(guild.id, channel.id, actor.id)
        if not layers:
            return (text + "\n" if text else "") + t(uid, "payinfo.nothing_set"), None, False
        return text, _payment_layers_embed(ticket["opener_id"], layers), True
    layers = _payment_layers(guild.id, channel.id, actor.id)
    if not layers:
        return (text + "\n" if text else "") + t(uid, "payinfo.nothing_set"), None, False
    return text, _payment_layers_embed(uid, layers, sources=True), False


# --- infrastructure created on demand -----------------------------------------

def _ticket_staff_roles(guild, cfg):
    return [r for r in guild.roles
            if not r.is_default() and (r.permissions.manage_channels or r.id in cfg["staff_role_ids"])]


def _ticket_overwrites(guild, cfg, opener=None):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True,
                                              read_message_history=True, attach_files=True, embed_links=True),
    }
    if opener is not None:
        overwrites[opener] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
    for role in _ticket_staff_roles(guild, cfg):
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
    return overwrites


async def _ensure_ticket_category(guild, cfg):
    category = discord.utils.get(guild.categories, name=cfg["category_name"])
    if category is None:
        category = await guild.create_category(
            cfg["category_name"], overwrites=_ticket_overwrites(guild, cfg), reason="Ticket system")
    return category


async def _ensure_ticket_log_channel(guild, cfg):
    """The staff-only log channel. Created (and remembered) the first time it is needed."""
    channel = guild.get_channel(cfg["log_channel_id"]) if cfg["log_channel_id"] else None
    if channel is None:
        channel = discord.utils.get(guild.text_channels, name=TICKET_LOG_CHANNEL_NAME)
    if channel is None:
        try:
            channel = await guild.create_text_channel(
                TICKET_LOG_CHANNEL_NAME, overwrites=_ticket_overwrites(guild, cfg),
                topic="Ticket logs and transcripts (staff only)", reason="Ticket system")
        except discord.HTTPException:
            return None
    cfg["log_channel_id"] = channel.id
    return channel


def _ticket_log_channel(guild, cfg):
    return guild.get_channel(cfg["log_channel_id"]) if cfg["log_channel_id"] else None


# --- transcript -------------------------------------------------------------------

async def _build_ticket_transcript(channel, info):
    """(bytes, message_count) -- a plain-text copy of the ticket. Nothing is stored:
    it is sent to the staff log channel and to the opener, then forgotten."""
    lines, count = [], 0
    try:
        async for m in channel.history(limit=TRANSCRIPT_MAX_MESSAGES, oldest_first=True):
            count += 1
            stamp = m.created_at.strftime("%Y-%m-%d %H:%M:%S")
            parts = [m.clean_content] if m.clean_content else []
            for e in m.embeds:
                bits = [x for x in (e.title, e.description) if x]
                if bits:
                    parts.append("[embed] " + " — ".join(bits))
            parts.extend(f"[file] {a.filename} {a.url}" for a in m.attachments)
            body = "\n    ".join(" ".join(parts).splitlines()) if parts else "(no text)"
            lines.append(f"[{stamp} UTC] {m.author} ({m.author.id}): {body}")
    except discord.HTTPException:
        lines.append("(the history could not be read completely)")
    header = [
        f"Ticket #{int(info.get('number', 0)):04d} -- #{channel.name} -- {channel.guild.name}",
        f"Opened by: {info.get('opener_id')}   Category: {info.get('category') or '-'}   Created: {info.get('created_at', '?')}",
        f"Claimed by: {info.get('claimed_by') or '-'}", "=" * 60,
    ]
    text = "\n".join(header + lines)
    if len(text) > TRANSCRIPT_MAX_CHARS:
        text = text[:TRANSCRIPT_MAX_CHARS] + "\n(... truncated)"
    return text.encode("utf-8"), count


def _transcript_file(channel, data):
    return discord.File(io.BytesIO(data), filename=f"transcript-{channel.name}.txt")


class TicketRatingView(discord.ui.View):
    """Sent to the opener (in DM) when the ticket closes. The answer goes to the staff log."""

    def __init__(self, lang_uid, log_channel_id, number, staff_id):
        super().__init__(timeout=86400)
        self.lang_uid, self.log_channel_id, self.number, self.staff_id = lang_uid, log_channel_id, number, staff_id
        for stars in range(1, 6):
            button = discord.ui.Button(label="⭐" * stars if stars < 4 else f"{stars} ⭐", style=discord.ButtonStyle.secondary)
            button.callback = self._make_callback(stars)
            self.add_item(button)

    def _make_callback(self, stars):
        async def callback(interaction: discord.Interaction):
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(content=t(self.lang_uid, "ticket.rating_thanks"), view=self)
            channel = bot.get_channel(self.log_channel_id)
            if channel is not None:
                embed = _base_embed(t(0, "ticket.rating_log_title"), EMBED_COLOR)
                handled = f"<@{self.staff_id}>" if self.staff_id else "-"
                embed.description = t(0, "ticket.rating_log_description", number=f"{self.number:04d}",
                                      user=interaction.user.mention, stars=stars, staff=handled)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass
            self.stop()
        return callback


async def _close_ticket_channel(channel, closer=None, automated_reason_key=None, reason=""):
    """Logs the closure (with a transcript), sends the opener a copy + a rating
    request, then deletes the channel. The caller posts any in-channel notice first."""
    key = (channel.guild.id, channel.id)
    info = open_tickets.pop(key, None)
    _panel_track("ticket_close", channel.guild, closer, channel.name)
    cfg = _ticket_cfg(channel.guild.id)
    transcript, count = (None, 0)
    if info is not None:
        transcript, count = await _build_ticket_transcript(channel, info)
    log_channel = _ticket_log_channel(channel.guild, cfg)
    closed_by_text = closer.mention if closer else t(0, automated_reason_key or "ticket.reason_auto")
    number = int(info.get("number", 0)) if info else 0
    if log_channel is not None:
        try:
            opener_mention = f"<@{info['opener_id']}>" if info else "?"
            embed = _base_embed(t(0, "ticket.log_closed_title"), EMBED_COLOR)
            embed.description = t(0, "ticket.log_closed_description",
                                  channel=channel.name, opener=opener_mention, closed_by=closed_by_text)
            if info is not None:
                embed.add_field(name=t(0, "ticket.log_number"), value=f"#{number:04d}", inline=True)
                embed.add_field(name=t(0, "ticket.log_messages"), value=str(count), inline=True)
                if info.get("claimed_by"):
                    embed.add_field(name=t(0, "ticket.log_handled_by"), value=f"<@{info['claimed_by']}>", inline=True)
            if reason:
                embed.add_field(name=t(0, "ticket.log_reason"), value=reason[:1000], inline=False)
            kwargs = {"embed": embed}
            if transcript:
                kwargs["file"] = _transcript_file(channel, transcript)
            await log_channel.send(**kwargs)
        except discord.HTTPException:
            pass
    if info is not None and transcript:
        opener = channel.guild.get_member(info["opener_id"])
        if opener is not None and not opener.bot:
            try:
                await opener.send(
                    t(opener.id, "ticket.dm_closed", number=f"{number:04d}", server=channel.guild.name),
                    file=_transcript_file(channel, transcript),
                    view=TicketRatingView(opener.id, log_channel.id if log_channel else 0, number, info.get("claimed_by")),
                )
            except discord.HTTPException:
                pass
    await asyncio.sleep(5)
    try:
        await channel.delete(reason=f"Ticket closed by {closer}" if closer else "Ticket auto-closed")
    except discord.HTTPException:
        pass

async def _create_ticket_channel(interaction: discord.Interaction, answers: dict, category_name: str = None):
    guild = interaction.guild
    uid = interaction.user.id
    cfg = _ticket_cfg(guild.id)

    open_count = sum(
        1 for (gid, _cid), info in open_tickets.items()
        if gid == guild.id and info["opener_id"] == uid
    )
    if open_count >= cfg["max_open_per_user"]:
        return await interaction.response.send_message(
            t(uid, "ticket.limit_reached", count=cfg["max_open_per_user"]), ephemeral=True
        )
    for (gid, cid), info in open_tickets.items():
        if gid == guild.id and info["opener_id"] == uid:
            existing = guild.get_channel(cid)
            if existing is not None and cfg["max_open_per_user"] <= 1:
                return await interaction.response.send_message(
                    t(uid, "ticket.already_open", channel=existing.mention), ephemeral=True)

    # Creating the category / log channel on a fresh server can take a few seconds.
    await interaction.response.defer(ephemeral=True)
    safe_name = "".join(c for c in interaction.user.name.lower() if c.isalnum() or c == "-") or "user"
    number = ticket_counters.get(guild.id, 0) + 1
    channel_name = f"ticket-{number:04d}-{safe_name}"[:100]
    support = bool(answers.get("support"))
    subject = (answers.get("subject") or "")[:60]
    try:
        discord_category = await _ensure_ticket_category(guild, cfg)
        await _ensure_ticket_log_channel(guild, cfg)
        channel = await guild.create_text_channel(
            channel_name,
            category=discord_category,
            overwrites=_ticket_overwrites(guild, cfg, opener=interaction.user),
            topic=f"#{number:04d} · {category_name or '-'} · {interaction.user}" + (f" · {subject}" if subject else ""),
            reason=f"Ticket opened by {interaction.user}",
        )
    except discord.Forbidden:
        return await interaction.followup.send(t(uid, "ticket.no_permission"), ephemeral=True)
    except discord.HTTPException:
        return await interaction.followup.send(t(uid, "ticket.create_failed"), ephemeral=True)
    ticket_counters[guild.id] = number

    price = _shop_price_for_category(category_name) if category_name else None
    # The payment method is matched now but only posted once the ticket is
    # claimed: whose wallet applies depends on who handles it (see _payment_layers).
    matched_method = None if support else _match_payment_method_answer(answers["payment"])

    now_iso = datetime.now(timezone.utc).isoformat()
    info = {
        "opener_id": uid,
        "category": category_name or "",
        "price": price or "",
        "claimed_by": None,
        "created_at": now_iso,
        "last_activity": now_iso,
        "warn_count": 0,
        "payment_method": matched_method or "",
        "number": number,
    }
    open_tickets[(guild.id, channel.id)] = info
    _panel_track("ticket_open", guild, interaction.user, category_name or channel.name)
    _request_backup_soon("ticket", delay=20)

    methods = _shop_methods_for_category(category_name) if category_name else None

    embed = _base_embed(f"{t(uid, 'ticket.new_title')} #{number:04d}", EMBED_COLOR)
    embed.description = t(uid, "ticket.new_description_support" if support else "ticket.new_description",
                          mention=interaction.user.mention)
    if category_name:
        embed.add_field(name=t(uid, "ticket.category_field"), value=category_name, inline=True)
    if support:
        embed.add_field(name=t(uid, "ticket.q_subject"), value=answers["subject"] or "-", inline=False)
        embed.add_field(name=t(uid, "ticket.q_problem"), value=(answers["problem"] or "-")[:1000], inline=False)
    else:
        if price:
            embed.add_field(name=t(uid, "ticket.price_field"), value=price, inline=True)
            if methods:
                embed.add_field(name=t(uid, "ticket.methods_field"), value=methods, inline=False)
        embed.add_field(name=t(uid, "ticket.q_payment"), value=answers["payment"], inline=True)
        if answers.get("duration"):
            embed.add_field(name=t(uid, "ticket.q_duration"), value=answers["duration"], inline=True)
        if answers.get("offer"):
            embed.add_field(name=t(uid, "ticket.q_offer"), value=answers["offer"], inline=True)
    close_hours = int(cfg["close_hours"])
    mute_suffix = (
        t(uid, "ticket.rules_mute_suffix", mute_duration=_format_duration(cfg["mute_minutes"] * 60))
        if cfg["mute_on_close"] else ""
    )
    embed.add_field(
        name=t(uid, "ticket.rules_field"),
        value=t(uid, "ticket.rules_value", close_hours=close_hours, mute_suffix=mute_suffix),
        inline=False,
    )
    staff_ping = " ".join(f"<@&{r}>" for r in sorted(cfg["staff_role_ids"]))
    try:
        message = await channel.send(
            content=staff_ping or None, embed=embed, view=_ticket_control_view(uid, info),
            allowed_mentions=discord.AllowedMentions(roles=True, users=True))
        info["control_message_id"] = message.id
    except discord.HTTPException:
        pass
    log_channel = _ticket_log_channel(guild, cfg)
    if log_channel is not None:
        try:
            log_embed = _base_embed(t(0, "ticket.log_opened_title"), EMBED_COLOR)
            log_embed.description = t(0, "ticket.log_opened_description", channel=channel.mention,
                                      opener=interaction.user.mention, number=f"{number:04d}",
                                      category=category_name or "-")
            await log_channel.send(embed=log_embed)
        except discord.HTTPException:
            pass
    await interaction.followup.send(t(uid, "ticket.created_confirm", channel=channel.mention), ephemeral=True)

def _ticket_control_view(uid, info, claimer=None):
    """The ticket's buttons, labelled for its opener (claimer: the staff member's display name)."""
    view = TicketControlView()
    if _ticket_is_support(info):
        view.remove_item(view.ticket_pay)
    for item in list(view.children):
        if item.custom_id == "close_ticket":
            item.label = t(uid, "ticket.close_button")
        elif item.custom_id == "ticket_pay":
            item.label = t(uid, "ticket.pay_button")
        elif item.custom_id == "claim_ticket":
            if info.get("claimed_by"):
                item.label = t(uid, "ticket.claimed_label", user=claimer or "staff")
                item.style = discord.ButtonStyle.success
            else:
                item.label = t(uid, "ticket.claim_button")
    return view


async def _refresh_ticket_controls(channel, info):
    message_id = info.get("control_message_id")
    if not message_id:
        return
    member = channel.guild.get_member(info["claimed_by"]) if info.get("claimed_by") else None
    try:
        await channel.get_partial_message(message_id).edit(
            view=_ticket_control_view(info["opener_id"], info, member.display_name if member else None))
    except discord.HTTPException:
        pass


async def _post_ticket_payment(channel, ticket, staff_id=None):
    """Post the payment info for this ticket (the method the customer asked for, or all)."""
    layers = _payment_layers(channel.guild.id, channel.id, staff_id)
    method = ticket.get("payment_method")
    chosen = {method: layers[method]} if method in layers else layers
    if not chosen:
        return False
    embed = _payment_layers_embed(ticket["opener_id"], chosen)
    await channel.send(content=t(ticket["opener_id"], "ticket.claim_payment_instructions"), embed=embed)
    return True


async def _apply_claim(channel, ticket, member, release=False):
    """Claim (or release) a ticket from a button, a command or yslemm -- one code path."""
    if release:
        ticket["claimed_by"] = None
        await _refresh_ticket_controls(channel, ticket)
        await channel.send(t(member.id, "ticket.released_announce", mention=member.mention))
        return
    ticket["claimed_by"] = member.id
    _panel_track("ticket_claim", channel.guild, member, channel.name)
    _request_backup_soon("ticket", delay=20)
    await _refresh_ticket_controls(channel, ticket)
    await channel.send(t(member.id, "ticket.claimed_announce", mention=member.mention))
    if ticket.get("payment_method") and not _ticket_is_support(ticket):
        await _post_ticket_payment(channel, ticket, member.id)


class TicketCloseModal(discord.ui.Modal):
    def __init__(self, uid):
        super().__init__(title=t(uid, "ticket.close_modal_title"))
        self.reason_input = discord.ui.TextInput(
            label=t(uid, "ticket.close_reason_label"), placeholder=t(uid, "ticket.close_reason_placeholder"),
            style=discord.TextStyle.paragraph, required=False, max_length=500)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        await _close_from_interaction(interaction, self.reason_input.value.strip())


async def _close_from_interaction(interaction, reason=""):
    uid = interaction.user.id
    ticket = open_tickets.get((interaction.guild.id, interaction.channel.id))
    allowed = (_is_ticket_staff(interaction.user) or ticket["opener_id"] == uid) if ticket is not None \
        else interaction.user.guild_permissions.manage_channels
    if not allowed:
        return await interaction.response.send_message(t(uid, "ticket.cannot_close"), ephemeral=True)
    embed = _base_embed(f"{EMOJIS['lock']} {t(uid, 'ticket.closing_title')}", WARN_COLOR)
    embed.description = t(uid, "ticket.closing_description", mention=interaction.user.mention)
    if reason:
        embed.add_field(name=t(uid, "ticket.log_reason"), value=reason[:1000], inline=False)
    await interaction.response.send_message(embed=embed)
    await _close_ticket_channel(interaction.channel, closer=interaction.user, reason=reason)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(emoji="🙋", style=discord.ButtonStyle.secondary, custom_id="claim_ticket")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        ticket = open_tickets.get((interaction.guild.id, interaction.channel.id))
        if ticket is None:
            return await interaction.response.send_message(t(uid, "ticket.not_a_ticket"), ephemeral=True)
        if not _is_ticket_staff(interaction.user):
            return await interaction.response.send_message(t(uid, "ticket.cannot_claim"), ephemeral=True)
        owner = ticket.get("claimed_by")
        if owner and owner != uid and not is_bot_admin_member(interaction.user):
            return await interaction.response.send_message(t(uid, "ticket.already_claimed", user=f"<@{owner}>"), ephemeral=True)
        if not ticket.get("control_message_id") and interaction.message is not None:
            ticket["control_message_id"] = interaction.message.id
        await interaction.response.defer()
        await _apply_claim(interaction.channel, ticket, interaction.user, release=(owner == uid))

    @discord.ui.button(emoji="💳", style=discord.ButtonStyle.primary, custom_id="ticket_pay")
    async def ticket_pay(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        ticket = open_tickets.get((interaction.guild.id, interaction.channel.id))
        if ticket is None:
            return await interaction.response.send_message(t(uid, "ticket.not_a_ticket"), ephemeral=True)
        if _ticket_is_support(ticket):
            return await interaction.response.send_message(t(uid, "ticket.pay_not_for_support"), ephemeral=True)
        staff = _is_ticket_staff(interaction.user)
        if not staff and ticket["opener_id"] != uid:
            return await interaction.response.send_message(t(uid, "ticket.cannot_close"), ephemeral=True)
        if not staff and not ticket.get("claimed_by"):
            return await interaction.response.send_message(t(uid, "ticket.pay_wait_staff"), ephemeral=True)
        await interaction.response.defer()
        if staff:
            text, embed, _public = await _payinfo_run(interaction.user, interaction.guild, interaction.channel, {})
        else:
            text = None
            embed = _payment_layers_embed(uid, _payment_layers(interaction.guild.id, interaction.channel.id))
            if not embed.fields:
                embed = None
        if embed is None:
            await interaction.followup.send(text or t(uid, "payinfo.nothing_set_customer"), ephemeral=True)
        else:
            await interaction.channel.send(content=text, embed=embed)

    @discord.ui.button(emoji="🔒", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        ticket = open_tickets.get((interaction.guild.id, interaction.channel.id))
        if ticket is not None and not (_is_ticket_staff(interaction.user) or ticket["opener_id"] == uid):
            return await interaction.response.send_message(t(uid, "ticket.cannot_close"), ephemeral=True)
        if ticket is None and not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message(t(uid, "ticket.cannot_close"), ephemeral=True)
        await interaction.response.send_modal(TicketCloseModal(uid))

# --- staff tools (shared by the ! and / versions) -----------------------------------
# Each returns the already-translated answer for the person who ran the command.

def _tk_ticket(guild, channel):
    return open_tickets.get((guild.id, channel.id))


async def _tk_claim(actor, channel, release=False):
    uid = actor.id
    ticket = _tk_ticket(channel.guild, channel)
    if ticket is None:
        return t(uid, "ticket.not_a_ticket")
    if not _is_ticket_staff(actor):
        return t(uid, "ticket.cannot_claim")
    owner = ticket.get("claimed_by")
    if release:
        if not owner:
            return t(uid, "ticket.not_claimed")
        if owner != uid and not is_bot_admin_member(actor):
            return t(uid, "ticket.already_claimed", user=f"<@{owner}>")
        await _apply_claim(channel, ticket, actor, release=True)
        return t(uid, "ticket.done")
    if owner and owner != uid and not is_bot_admin_member(actor):
        return t(uid, "ticket.already_claimed", user=f"<@{owner}>")
    if owner == uid:
        return t(uid, "ticket.already_yours")
    await _apply_claim(channel, ticket, actor)
    return t(uid, "ticket.done")


async def _tk_add(actor, channel, member):
    uid = actor.id
    ticket = _tk_ticket(channel.guild, channel)
    if ticket is None:
        return t(uid, "ticket.not_a_ticket")
    if not _is_ticket_staff(actor):
        return t(uid, "ticket.staff_only")
    if member.bot:
        return t(uid, "ticket.no_bots")
    try:
        await channel.set_permissions(member, view_channel=True, send_messages=True,
                                      read_message_history=True, attach_files=True,
                                      reason=f"Added to the ticket by {actor}")
    except discord.HTTPException:
        return t(uid, "ticket.no_permission")
    await channel.send(t(uid, "ticket.member_added", user=member.mention, by=actor.mention))
    return t(uid, "ticket.done")


async def _tk_remove(actor, channel, member):
    uid = actor.id
    ticket = _tk_ticket(channel.guild, channel)
    if ticket is None:
        return t(uid, "ticket.not_a_ticket")
    if not _is_ticket_staff(actor):
        return t(uid, "ticket.staff_only")
    if member.id == ticket["opener_id"]:
        return t(uid, "ticket.cant_remove_opener")
    if member.bot:
        return t(uid, "ticket.no_bots")
    try:
        await channel.set_permissions(member, overwrite=None, reason=f"Removed from the ticket by {actor}")
    except discord.HTTPException:
        return t(uid, "ticket.no_permission")
    await channel.send(t(uid, "ticket.member_removed", user=member.mention, by=actor.mention))
    return t(uid, "ticket.done")


async def _tk_rename(actor, channel, new_name):
    uid = actor.id
    ticket = _tk_ticket(channel.guild, channel)
    if ticket is None:
        return t(uid, "ticket.not_a_ticket")
    if not _is_ticket_staff(actor):
        return t(uid, "ticket.staff_only")
    cleaned = "".join(c for c in new_name.lower().replace(" ", "-") if c.isalnum() or c in "-_")[:60].strip("-")
    if not cleaned:
        return t(uid, "ticket.bad_name")
    name = f"ticket-{int(ticket.get('number', 0)):04d}-{cleaned}"[:100]
    try:
        await asyncio.wait_for(channel.edit(name=name, reason=f"Renamed by {actor}"), timeout=8)
    except (discord.HTTPException, asyncio.TimeoutError):
        return t(uid, "ticket.rename_limited")
    return t(uid, "ticket.renamed", name=name)


async def _tk_transcript(actor, channel):
    """(text, file|None)"""
    uid = actor.id
    ticket = _tk_ticket(channel.guild, channel)
    if ticket is None:
        return t(uid, "ticket.not_a_ticket"), None
    if not _is_ticket_staff(actor):
        return t(uid, "ticket.staff_only"), None
    data, _count = await _build_ticket_transcript(channel, ticket)
    return t(uid, "ticket.transcript_ready"), _transcript_file(channel, data)


def _tk_list_embed(uid, guild):
    rows = []
    now = datetime.now(timezone.utc)
    for (gid, cid), info in sorted(open_tickets.items(), key=lambda kv: kv[1].get("number", 0)):
        if gid != guild.id:
            continue
        channel = guild.get_channel(cid)
        if channel is None:
            continue
        try:
            age = _format_duration(int((now - datetime.fromisoformat(info["created_at"])).total_seconds()))
        except (KeyError, ValueError):
            age = "?"
        claimed = f"<@{info['claimed_by']}>" if info.get("claimed_by") else t(uid, "ticket.unclaimed")
        rows.append(f"`#{int(info.get('number', 0)):04d}` {channel.mention} · <@{info['opener_id']}> · {claimed} · {age}")
    embed = _base_embed(t(uid, "ticket.list_title"), EMBED_COLOR)
    embed.description = "\n".join(rows[:25]) or t(uid, "ticket.no_tickets")
    if len(rows) > 25:
        embed.set_footer(text=t(uid, "ticket.list_more", count=len(rows) - 25))
    return embed


async def _tk_close(actor, channel, reason=""):
    """Returns an error text, or None once the close has been started."""
    uid = actor.id
    ticket = _tk_ticket(channel.guild, channel)
    if ticket is None:
        return t(uid, "ticket.not_a_ticket")
    if not (_is_ticket_staff(actor) or ticket["opener_id"] == uid):
        return t(uid, "ticket.cannot_close")
    embed = _base_embed(f"{EMOJIS['lock']} {t(uid, 'ticket.closing_title')}", WARN_COLOR)
    embed.description = t(uid, "ticket.closing_description", mention=actor.mention)
    if reason:
        embed.add_field(name=t(0, "ticket.log_reason"), value=reason[:1000], inline=False)
    await channel.send(embed=embed)
    asyncio.create_task(_close_ticket_channel(channel, closer=actor, reason=reason))
    return None


async def _post_ticket_panel(actor, guild, target):
    """Everything /ticketsetup needs, with no prior configuration: the private category,
    the staff log channel, then the panel. Returns the summary for the admin."""
    uid = actor.id
    cfg = _ticket_cfg(guild.id)
    category = await _ensure_ticket_category(guild, cfg)
    log_channel = await _ensure_ticket_log_channel(guild, cfg)
    embed = _base_embed(t(uid, "ticket.panel_title"), EMBED_COLOR)
    embed.description = t(uid, "ticket.panel_description")
    view = TicketPanelView()
    view.children[0].label = t(uid, "ticket.support_button")
    view.children[1].label = t(uid, "ticket.buy_button")
    await target.send(embed=embed, view=view)
    roles = _ticket_staff_roles(guild, cfg)
    summary = t(uid, "ticket.setup_summary",
                panel=target.mention, category=category.name,
                logs=log_channel.mention if log_channel else t(uid, "ticket.not_set"),
                staff=", ".join(r.mention for r in roles[:8]) or t(uid, "ticket.not_set"))
    return summary


_TICKET_LANG_PROMPT = (
    "🌐 **FR :** Choisis ta langue pour ce ticket :\n🌐 **EN:** Choose your language for this ticket:\n"
    "🌐 **ES:** Elige tu idioma para este ticket:\n🌐 **AR:** اختر لغتك لهذه التذكرة:\n"
    "🌐 **PT:** Escolhe o teu idioma para este ticket:")


class TicketPanelView(discord.ui.View):
    """Two entry points: Support (describe a problem, no payment) and Buy (shop ticket)."""

    def __init__(self):
        super().__init__(timeout=None)

    # "create_ticket" is kept as the Support id so panels posted before keep working.
    @discord.ui.button(emoji="🛠️", style=discord.ButtonStyle.danger, custom_id="create_ticket")
    async def support_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(_TICKET_LANG_PROMPT, view=TicketLanguageView("support"), ephemeral=True)

    @discord.ui.button(emoji="🛒", style=discord.ButtonStyle.success, custom_id="buy_ticket")
    async def buy_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(_TICKET_LANG_PROMPT, view=TicketLanguageView("buy"), ephemeral=True)


async def _create_staff_application_channel(interaction: discord.Interaction, answers: dict):
    guild = interaction.guild
    uid = interaction.user.id
    cfg = _staffapp_cfg(guild.id)

    existing_channel = _staffapp_active_channel(guild, uid)
    if existing_channel is not None:
        return await interaction.response.send_message(
            t(uid, "staffapp.already_open", channel=existing_channel.mention), ephemeral=True
        )

    safe_name = "".join(c for c in interaction.user.name.lower() if c.isalnum() or c == "-") or "user"
    channel_name = f"candidature-{safe_name}"[:100]

    discord_category = discord.utils.get(guild.categories, name=cfg["category_name"])
    try:
        if discord_category is None:
            discord_category = await guild.create_category(cfg["category_name"])

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        viewer = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if cfg.get("owner_only", True):
            # Private to the bot owner (the server owner if they are not in this server).
            owner = guild.get_member(BOT_OWNER_ID) or guild.owner
            if owner is not None:
                overwrites[owner] = viewer
        else:
            for role in guild.roles:
                if role.permissions.manage_guild or role.id in cfg["recruiter_role_ids"]:
                    overwrites[role] = viewer

        channel = await guild.create_text_channel(
            channel_name,
            category=discord_category,
            overwrites=overwrites,
            topic=t(uid, "staffapp.channel_topic", user=interaction.user.name),
            reason=f"Staff application opened by {interaction.user}",
        )
    except discord.Forbidden:
        return await interaction.response.send_message(t(uid, "ticket.no_permission"), ephemeral=True)

    now_iso = datetime.now(timezone.utc).isoformat()
    staff_applications[(guild.id, channel.id)] = {
        "applicant_id": uid,
        "status": "pending",
        "answers": answers,
        "claimed_by": None,
        "created_at": now_iso,
        "decided_by": None,
        "decided_at": None,
        "reason": "",
    }
    _panel_track("staffapp_open", guild, interaction.user, interaction.user.name)

    embed = _base_embed(t(uid, "staffapp.recap_title"), EMBED_COLOR)
    embed.description = t(uid, "staffapp.recap_description", mention=interaction.user.mention)
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    situations_embed = _base_embed(t(uid, "staffapp.recap_situations_title"), EMBED_COLOR)
    for key, label_key in STAFFAPP_QUESTION_ORDER:
        target = situations_embed if key.startswith("sit_") or key == "prior_staff" else embed
        value = answers.get(key) or "\u2014"
        target.add_field(name=t(uid, label_key), value=value[:1024], inline=False)

    control_view = StaffApplicationControlView()
    for item in control_view.children:
        if item.custom_id == "staffapp_claim":
            item.label = t(uid, "staffapp.claim_button")
        elif item.custom_id == "staffapp_accept":
            item.label = t(uid, "staffapp.accept_button")
        elif item.custom_id == "staffapp_reject":
            item.label = t(uid, "staffapp.reject_button")
        elif item.custom_id == "staffapp_close":
            item.label = t(uid, "staffapp.close_button")
    await channel.send(embeds=[embed, situations_embed], view=control_view)
    await interaction.response.send_message(t(uid, "staffapp.created_confirm", channel=channel.mention), ephemeral=True)


STAFFAPP_QUESTION_ORDER = [
    ("age_tz", "staffapp.q_age_tz"),
    ("availability", "staffapp.q_availability"),
    ("experience", "staffapp.q_experience"),
    ("motivation", "staffapp.q_motivation"),
    ("strength", "staffapp.q_strength"),
    ("sit_insult", "staffapp.q_sit_insult"),
    ("sit_friend", "staffapp.q_sit_friend"),
    ("sit_disagree", "staffapp.q_sit_disagree"),
    ("sit_payment", "staffapp.q_sit_payment"),
    ("sit_raid", "staffapp.q_sit_raid"),
    ("sit_abuse", "staffapp.q_sit_abuse"),
    ("prior_staff", "staffapp.q_prior_staff"),
]


class StaffApplyModalB(discord.ui.Modal):
    def __init__(self, uid, answers_a):
        super().__init__(title=t(uid, "staffapp.modal_b_title"))
        self.uid = uid
        self.answers_a = answers_a
        self.sit_insult = discord.ui.TextInput(
            label=t(uid, "staffapp.q_sit_insult"), style=discord.TextStyle.paragraph, max_length=500, required=True,
        )
        self.sit_friend = discord.ui.TextInput(
            label=t(uid, "staffapp.q_sit_friend"), style=discord.TextStyle.paragraph, max_length=500, required=True,
        )
        self.sit_disagree = discord.ui.TextInput(
            label=t(uid, "staffapp.q_sit_disagree"), style=discord.TextStyle.paragraph, max_length=500, required=True,
        )
        self.sit_payment = discord.ui.TextInput(
            label=t(uid, "staffapp.q_sit_payment"), style=discord.TextStyle.paragraph, max_length=500, required=True,
        )
        self.sit_raid = discord.ui.TextInput(
            label=t(uid, "staffapp.q_sit_raid"), style=discord.TextStyle.paragraph, max_length=500, required=True,
        )
        for item in (self.sit_insult, self.sit_friend, self.sit_disagree, self.sit_payment, self.sit_raid):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        answers = dict(self.answers_a)
        answers.update({
            "sit_insult": self.sit_insult.value.strip(),
            "sit_friend": self.sit_friend.value.strip(),
            "sit_disagree": self.sit_disagree.value.strip(),
            "sit_payment": self.sit_payment.value.strip(),
            "sit_raid": self.sit_raid.value.strip(),
        })
        embed = _base_embed(t(self.uid, "staffapp.situations2_title"), EMBED_COLOR)
        embed.description = t(self.uid, "staffapp.situations2_description")
        await interaction.response.send_message(
            embed=embed, view=StaffApplyContinueView(self.uid, answers, StaffApplyModalC), ephemeral=True)


class StaffApplyModalC(discord.ui.Modal):
    def __init__(self, uid, answers_b):
        super().__init__(title=t(uid, "staffapp.modal_c_title"))
        self.uid = uid
        self.answers_b = answers_b
        self.sit_abuse = discord.ui.TextInput(
            label=t(uid, "staffapp.q_sit_abuse"), style=discord.TextStyle.paragraph, max_length=500, required=True,
        )
        self.prior_staff = discord.ui.TextInput(
            label=t(uid, "staffapp.q_prior_staff"), style=discord.TextStyle.paragraph, max_length=400, required=False,
        )
        self.add_item(self.sit_abuse)
        self.add_item(self.prior_staff)

    async def on_submit(self, interaction: discord.Interaction):
        answers = dict(self.answers_b)
        answers.update({"sit_abuse": self.sit_abuse.value.strip(), "prior_staff": self.prior_staff.value.strip()})
        await _create_staff_application_channel(interaction, answers)


class StaffApplyContinueView(discord.ui.View):
    """The button between two steps: opens the next form (B by default, C after B)."""

    def __init__(self, uid, answers, next_modal=StaffApplyModalB):
        super().__init__(timeout=300)
        self.answers = answers
        self.next_modal = next_modal
        self.children[0].label = t(uid, "staffapp.continue_button")

    @discord.ui.button(style=discord.ButtonStyle.success, custom_id="staffapp_continue")
    async def cont(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(self.next_modal(interaction.user.id, self.answers))


class StaffApplyModalA(discord.ui.Modal):
    def __init__(self, uid):
        super().__init__(title=t(uid, "staffapp.modal_a_title"))
        self.uid = uid
        self.age_tz = discord.ui.TextInput(
            label=t(uid, "staffapp.q_age_tz"), placeholder=t(uid, "staffapp.q_age_tz_ph"), max_length=100, required=True,
        )
        self.availability = discord.ui.TextInput(
            label=t(uid, "staffapp.q_availability"), placeholder=t(uid, "staffapp.q_availability_ph"), max_length=150, required=True,
        )
        self.experience = discord.ui.TextInput(
            label=t(uid, "staffapp.q_experience"), style=discord.TextStyle.paragraph,
            placeholder=t(uid, "staffapp.q_experience_ph"), max_length=500, required=True,
        )
        self.motivation = discord.ui.TextInput(
            label=t(uid, "staffapp.q_motivation"), style=discord.TextStyle.paragraph,
            placeholder=t(uid, "staffapp.q_motivation_ph"), max_length=500, required=True,
        )
        self.strength = discord.ui.TextInput(
            label=t(uid, "staffapp.q_strength"), style=discord.TextStyle.paragraph,
            placeholder=t(uid, "staffapp.q_strength_ph"), max_length=400, required=True,
        )
        for item in (self.age_tz, self.availability, self.experience, self.motivation, self.strength):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        answers_a = {
            "age_tz": self.age_tz.value.strip(),
            "availability": self.availability.value.strip(),
            "experience": self.experience.value.strip(),
            "motivation": self.motivation.value.strip(),
            "strength": self.strength.value.strip(),
        }
        embed = _base_embed(t(self.uid, "staffapp.situations_title"), EMBED_COLOR)
        embed.description = t(self.uid, "staffapp.situations_description")
        await interaction.response.send_message(
            embed=embed, view=StaffApplyContinueView(self.uid, answers_a), ephemeral=True,
        )


class StaffApplyStartView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.children[0].label = t(uid, "staffapp.start_button")

    @discord.ui.button(style=discord.ButtonStyle.success, custom_id="staffapp_start")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StaffApplyModalA(interaction.user.id))


class StaffApplyRejectModal(discord.ui.Modal):
    def __init__(self, uid, control_view, control_message):
        super().__init__(title=t(uid, "staffapp.reject_modal_title"))
        self.control_view = control_view
        self.control_message = control_message
        self.reason_input = discord.ui.TextInput(
            label=t(uid, "staffapp.reject_reason_label"), style=discord.TextStyle.paragraph,
            placeholder=t(uid, "staffapp.reject_reason_ph"), max_length=500, required=False,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        uid = interaction.user.id
        reason = self.reason_input.value.strip()
        result = await _staffapp_reject(interaction.guild, interaction.channel, interaction.user, reason)
        if result is None:
            return await interaction.response.send_message(t(uid, "staffapp.already_decided"), ephemeral=True)
        app, applicant = result
        for item in self.control_view.children:
            if item.custom_id in ("staffapp_accept", "staffapp_reject"):
                item.disabled = True
        try:
            await self.control_message.edit(view=self.control_view)
        except discord.HTTPException:
            pass
        mention = applicant.mention if applicant else f"<@{app['applicant_id']}>"
        embed = _base_embed(f"\u274c {t(uid, 'staffapp.rejected_title')}", ERROR_COLOR)
        embed.description = t(uid, "staffapp.rejected_description", mention=mention, by=interaction.user.mention)
        if reason:
            embed.add_field(name=t(uid, "staffapp.reason_field"), value=reason[:1024], inline=False)
        await interaction.response.send_message(embed=embed)
        _panel_track("staffapp_reject", interaction.guild, interaction.user, applicant.display_name if applicant else str(app["applicant_id"]))
        cfg = _staffapp_cfg(interaction.guild.id)
        if cfg["log_channel_id"]:
            log_channel = interaction.guild.get_channel(cfg["log_channel_id"])
            if log_channel is not None:
                try:
                    log_embed = _base_embed(t(0, "staffapp.log_rejected_title"), ERROR_COLOR)
                    log_embed.description = t(0, "staffapp.log_rejected_description", applicant=mention, by=interaction.user.mention)
                    await log_channel.send(embed=log_embed)
                except discord.HTTPException:
                    pass


class StaffApplicationControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(emoji="\U0001f64b", style=discord.ButtonStyle.secondary, custom_id="staffapp_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if not _staffapp_is_recruiter(interaction.user):
            return await interaction.response.send_message(t(uid, "staffapp.cannot_claim"), ephemeral=True)
        app = staff_applications.get((interaction.guild.id, interaction.channel.id))
        if app is not None:
            app["claimed_by"] = uid
        _panel_track("staffapp_claim", interaction.guild, interaction.user, interaction.channel.name)
        button.disabled = True
        button.label = t(uid, "staffapp.claimed_label", user=interaction.user.display_name)
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(t(uid, "staffapp.claimed_announce", mention=interaction.user.mention))

    @discord.ui.button(emoji="\u2705", style=discord.ButtonStyle.success, custom_id="staffapp_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if not _staffapp_is_recruiter(interaction.user):
            return await interaction.response.send_message(t(uid, "staffapp.cannot_decide"), ephemeral=True)
        result = await _staffapp_accept(interaction.guild, interaction.channel, interaction.user)
        if result is None:
            return await interaction.response.send_message(t(uid, "staffapp.already_decided"), ephemeral=True)
        app, applicant, role_outcome = result
        for item in self.children:
            if item.custom_id in ("staffapp_accept", "staffapp_reject"):
                item.disabled = True
        await interaction.response.edit_message(view=self)
        mention = applicant.mention if applicant else f"<@{app['applicant_id']}>"
        embed = _base_embed(f"\u2705 {t(uid, 'staffapp.accepted_title')}", SUCCESS_COLOR)
        embed.description = t(uid, "staffapp.accepted_description", mention=mention, by=interaction.user.mention)
        cfg = _staffapp_cfg(interaction.guild.id)
        if role_outcome and cfg.get("granted_role_id"):
            role = interaction.guild.get_role(cfg["granted_role_id"])
            role_mention = role.mention if role else "?"
            key = "staffapp.role_granted" if role_outcome == "granted" else "staffapp.role_grant_failed"
            embed.add_field(name=t(uid, "staffapp.role_field"), value=t(uid, key, role=role_mention), inline=False)
        await interaction.channel.send(embed=embed)
        _panel_track("staffapp_accept", interaction.guild, interaction.user, applicant.display_name if applicant else str(app["applicant_id"]))
        if cfg["log_channel_id"]:
            log_channel = interaction.guild.get_channel(cfg["log_channel_id"])
            if log_channel is not None:
                try:
                    log_embed = _base_embed(t(0, "staffapp.log_accepted_title"), SUCCESS_COLOR)
                    log_embed.description = t(0, "staffapp.log_accepted_description", applicant=mention, by=interaction.user.mention)
                    await log_channel.send(embed=log_embed)
                except discord.HTTPException:
                    pass

    @discord.ui.button(emoji="\u274c", style=discord.ButtonStyle.danger, custom_id="staffapp_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if not _staffapp_is_recruiter(interaction.user):
            return await interaction.response.send_message(t(uid, "staffapp.cannot_decide"), ephemeral=True)
        app = staff_applications.get((interaction.guild.id, interaction.channel.id))
        if app is None or app["status"] != "pending":
            return await interaction.response.send_message(t(uid, "staffapp.already_decided"), ephemeral=True)
        await interaction.response.send_modal(StaffApplyRejectModal(uid, self, interaction.message))

    @discord.ui.button(emoji="\U0001f512", style=discord.ButtonStyle.secondary, custom_id="staffapp_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if not _staffapp_is_recruiter(interaction.user):
            return await interaction.response.send_message(t(uid, "staffapp.cannot_close"), ephemeral=True)
        embed = _base_embed(f"{EMOJIS['lock']} {t(uid, 'staffapp.closing_title')}", WARN_COLOR)
        embed.description = t(uid, "staffapp.closing_description", mention=interaction.user.mention)
        await interaction.response.send_message(embed=embed)
        await _close_staff_application_channel(interaction.channel, closer=interaction.user)


class StaffApplyLanguageView(discord.ui.View):
    """First step of applying: which language (English or French only --
    unlike the ticket flow's 5, a staff application is read by the human
    recruiters here, so it's kept to the two they actually speak) the rest
    of the form and the recap embed should be in. Setting user_lang here
    is what makes every downstream t()-based string in the flow follow
    this choice automatically."""

    def __init__(self):
        super().__init__(timeout=120)

    async def _choose(self, interaction: discord.Interaction, lang):
        uid = interaction.user.id
        user_lang[uid] = lang
        embed = _base_embed(t(uid, "staffapp.intro_title"), EMBED_COLOR)
        embed.description = t(uid, "staffapp.intro_description")
        await interaction.response.send_message(embed=embed, view=StaffApplyStartView(uid), ephemeral=True)

    @discord.ui.button(emoji="\U0001f1eb\U0001f1f7", label="Français", style=discord.ButtonStyle.secondary, custom_id="staffapp_lang_fr")
    async def lang_fr(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "fr")

    @discord.ui.button(emoji="\U0001f1ec\U0001f1e7", label="English", style=discord.ButtonStyle.secondary, custom_id="staffapp_lang_en")
    async def lang_en(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "en")


class StaffApplyPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(emoji="\U0001f4cb", style=discord.ButtonStyle.primary, custom_id="staffapp_apply")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        guild = interaction.guild
        existing_channel = _staffapp_active_channel(guild, uid)
        if existing_channel is not None:
            return await interaction.response.send_message(
                t(uid, "staffapp.already_open", channel=existing_channel.mention), ephemeral=True
            )
        remaining = _staffapp_cooldown_remaining_days(guild.id, uid)
        if remaining > 0:
            return await interaction.response.send_message(
                t(uid, "staffapp.cooldown_active", days=f"{remaining:.1f}"), ephemeral=True
            )
        await interaction.response.send_message(
            "\U0001F310 **FR :** Choisis la langue de ta candidature :\n"
            "\U0001F310 **EN:** Choose your application language:",
            view=StaffApplyLanguageView(), ephemeral=True,
        )


def _ping_embed(member):
    uid = member.id
    latency = round(bot.latency * 1000)
    color = SUCCESS_COLOR if latency < 150 else (WARN_COLOR if latency < 300 else ERROR_COLOR)
    quality_key = "ping.quality_excellent" if latency < 150 else ("ping.quality_ok" if latency < 300 else "ping.quality_poor")
    embed = _base_embed(t(uid, "ping.title"), color)
    embed.add_field(name=t(uid, "ping.latency"), value=f"`{latency}ms`", inline=True)
    embed.add_field(name=t(uid, "ping.quality"), value=t(uid, quality_key), inline=True)
    return _footer(embed, member)


_SLASH_SYNC_STAMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".slash_sync_hash")


def _slash_fingerprint() -> str:
    commands_dump = [c.to_dict(bot.tree) for c in bot.tree.get_commands()]
    return hashlib.sha256(json.dumps(commands_dump, sort_keys=True, default=str).encode("utf-8")).hexdigest()


async def _sync_slash_commands():
    """Register the slash commands globally, so they exist in every server the
    bot is in -- including servers it joins later, with no restart needed.

    Older versions registered a copy per server instead (which is why a server
    that refused the sync, or one added after startup, had no commands, and
    why a global copy as well would have shown every command twice). Those
    per-server copies are removed here, one server at a time, so a single
    server that refuses (e.g. no applications.commands permission) can no
    longer stop the others.
    """
    fingerprint = _slash_fingerprint()
    try:
        with open(_SLASH_SYNC_STAMP, encoding="utf-8") as fh:
            if fh.read().strip() == fingerprint:
                print("[OK] Slash commands inchangées : pas de synchronisation avec Discord")
                return True
    except OSError:
        pass
    try:
        synced = await bot.tree.sync()
        print(f"[OK] Synced {len(synced)} global slash command(s): available in every server")
    except discord.HTTPException as e:
        print(f"[WARN] Global slash command sync failed: {e}")
        return False
    with open(_SLASH_SYNC_STAMP, "w", encoding="utf-8") as fh:
        fh.write(fingerprint)
    for guild in bot.guilds:
        try:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
        except discord.HTTPException as e:
            print(f"[WARN] Couldn't remove the old per-server slash commands of '{guild.name}' ({guild.id}): {e}")
    return True


@bot.event
async def on_ready():
    global _views_registered, _tree_synced, _state_loaded, _key_invite_checked
    print(f"[OK] Logged in as {bot.user} (ID: {bot.user.id})")
    if not rotate_presence.is_running():
        rotate_presence.start()
    if not _state_loaded:
        if not await _load_state_from_redis():
            await _auto_restore_from_backup()
        _state_loaded = True
        _mark_key_system_ready()
        _install_shutdown_handler()
        if not state_autosave.is_running():
            state_autosave.start()
        if not data_backup_loop.is_running():
            data_backup_loop.start()
    if not _views_registered:
        bot.add_view(TicketPanelView())
        bot.add_view(TicketControlView())
        bot.add_view(CryptoPaymentConfirmView())
        bot.add_view(StaffApplyPanelView())
        bot.add_view(StaffApplicationControlView())
        _views_registered = True
    if not _tree_synced:
        await _sync_slash_commands()
        _tree_synced = True
    if not _key_invite_checked:
        _key_invite_checked = True
        try:
            await _ensure_key_invite()
        except Exception as e:
            print(f"[WARN] Key channel invite check failed: {e}")
    if not keep_alive.is_running():
        keep_alive.start()
    if not ticket_inactivity_check.is_running():
        ticket_inactivity_check.start()
    if not recurring_reminder_check.is_running():
        recurring_reminder_check.start()
    if not crypto_payment_check.is_running():
        crypto_payment_check.start()
    _env_verify_role = int(os.environ.get("VERIFY_ROLE_ID", "0") or 0)
    if _env_verify_role:
        for guild in bot.guilds:
            cfg = _screening_cfg(guild.id)
            if not cfg.get("role_id"):
                cfg["role_id"] = _env_verify_role


@bot.event
async def on_member_join(member):
    if member.bot:
        await _handle_bot_join(member)
        return

    if await _screen_new_member(member):
        return  # kicked by the screening: no greeting for an account that is gone

    await _send_greeting(member, "join")

    cfg = _antiraid_cfg(member.guild.id)
    if not cfg["enabled"]:
        return
    now = time.time()
    entries = join_times.setdefault(member.guild.id, [])
    entries.append((now, member.id))
    window = cfg["window"]
    entries[:] = [e for e in entries if now - e[0] <= window]
    if len(entries) >= cfg["threshold"]:
        await _handle_raid(member.guild, list(entries), cfg)
        join_times[member.guild.id] = []


@bot.event
async def on_member_remove(member):
    await _send_greeting(member, "leave")

    tcfg = _ticket_cfg(member.guild.id)
    for (gid, cid), info in list(open_tickets.items()):
        if gid != member.guild.id or info["opener_id"] != member.id:
            continue
        channel = member.guild.get_channel(cid)
        if channel is None:
            open_tickets.pop((gid, cid), None)
            continue
        try:
            if tcfg["leave_action"] == "close":
                embed = _base_embed(t(0, "ticket.leave_close_title"), WARN_COLOR)
                embed.description = t(0, "ticket.leave_close_description", member=str(member))
                await channel.send(embed=embed)
                await _close_ticket_channel(channel, closer=None, automated_reason_key="ticket.reason_left")
            else:
                embed = _base_embed(t(0, "ticket.leave_notify_title"), WARN_COLOR)
                embed.description = t(0, "ticket.leave_notify_description", member=str(member))
                await channel.send(embed=embed)
        except discord.HTTPException:
            pass


@bot.event
async def on_guild_channel_delete(channel):
    await _register_nuke_action(channel.guild, discord.AuditLogAction.channel_delete)


@bot.event
async def on_guild_channel_create(channel):
    await _register_nuke_action(channel.guild, discord.AuditLogAction.channel_create)


@bot.event
async def on_guild_role_delete(role):
    await _register_nuke_action(role.guild, discord.AuditLogAction.role_delete)


@bot.event
async def on_guild_role_create(role):
    await _register_nuke_action(role.guild, discord.AuditLogAction.role_create)


@bot.event
async def on_webhooks_update(channel):
    # Fires on any webhook change in the channel (create/delete/update);
    # _register_nuke_action filters the audit log to webhook_create
    # specifically and only accepts a match from the last 5s, so this is a
    # no-op unless a webhook was actually just created here.
    await _register_nuke_action(channel.guild, discord.AuditLogAction.webhook_create)


@bot.event
async def on_member_ban(guild, user):
    await _register_nuke_action(guild, discord.AuditLogAction.ban)


# "yslemm" (double m, deliberately distinct from the "yslem"
# command) lets bot-admins/staff trigger common actions from a plain
# sentence instead of a real command -- e.g. "yslemm mute @user 1h flood".
# This is plain keyword/regex parsing, not an LLM: it only recognizes a
# fixed set of verbs and pulls the target from Discord's own @mention
# parsing, so there's no free-form language understanding involved. Every
# action still goes through the exact same permission/hierarchy checks as
# its real command counterpart -- this trigger is a shortcut, not a
# separate permission surface.
YSLEMM_TRIGGER_RE = re.compile(r"\byslemm\b", re.IGNORECASE)
# Raw Discord snowflake IDs typed without an @mention (17-20 digits).
_RAW_DISCORD_ID_RE = re.compile(r"\b(\d{17,20})\b")
# Matches garam/garams/garama in any casing -- the Roblox in-game currency
# name, always used to mean payment via Roblox (see _handle_yslemm_command).
GARAM_RE = re.compile(r"\bgaram(?:a|as|s)?\b", re.IGNORECASE)
# Deliberately generous EN/FR synonym coverage per action -- built wide on
# purpose so more phrasings land on the right verb instead of falling
# through to the FAQ/greeting fallback. Order matters only where a shorter
# word could sit inside a longer one; unmute/lang_fr/lang_en are placed
# before their broader relatives for that reason (word-boundary regex
# already keeps "mute" from matching inside "unmute", this is just belt
# and suspenders for readability).
YSLEMM_ACTIONS = [
    ("aibuild", (
        "organize the channels", "organise the channels", "organize channels", "organise channels",
        "organize the server", "organise the server", "sort the channels", "sort channels",
        "put the channels in categories", "put the channels into categories", "move the channels into categories",
        "set up the server", "setup the server", "build the server", "structure the server", "create categories",
        "create a category", "make a category",
        "range les salons", "ranger les salons", "range les channels", "classe les salons", "classer les salons",
        "classe les channels", "organise les salons", "organiser les salons", "organise le serveur",
        "organiser le serveur", "range le serveur", "ranger le serveur", "mets les salons dans", "met les salons dans",
        "mettre les salons dans", "trie les salons", "trier les salons", "structure le serveur", "structurer le serveur",
        "configure le serveur", "construis le serveur", "monte le serveur", "crée une catégorie", "cree une categorie",
        "crée des catégories", "cree des categories", "créer une catégorie", "creer une categorie", "fais des catégories",
        "fait des catégories", "fais des categories",
    )),
    ("lang_fr", (
        "parle français", "parle en français", "en français", "mets en français", "mets toi en français",
        "passe en français", "français stp", "français s'il te plait", "français s'il te plaît",
        "speak french", "in french", "switch to french", "french please",
    )),
    ("lang_en", (
        "parle anglais", "parle en anglais", "en anglais", "mets en anglais", "mets toi en anglais",
        "passe en anglais", "anglais stp", "anglais s'il te plait", "anglais s'il te plaît",
        "speak english", "in english", "switch to english", "english please",
    )),
    ("unmute", (
        "unmute", "un-mute", "untimeout", "unsilence",
        "démute", "demute", "dé-mute", "réactive le son", "reactive le son", "retire le mute",
        "enlève le mute", "enleve le mute", "enlève le timeout", "enleve le timeout",
        "désourdine", "desourdine", "retire la sourdine", "enlève la sourdine", "enleve la sourdine",
        "reparle", "re-parle", "parle à nouveau", "parle a nouveau", "speak again", "talk again",
    )),
    ("mute", (
        "mute", "timeout", "silence", "gag", "shut up", "stop talking", "be quiet",
        "réduis au silence", "reduis au silence", "fais taire", "faire taire", "museler", "muselle",
        "mets en sourdine", "mets le en sourdine", "met en sourdine", "sourdine", "coupe le micro",
        "rends muet", "rend muet", "réduis le au silence", "reduis le au silence",
        "tais toi", "tais-toi", "la ferme", "arrête de parler", "arrete de parler",
    )),
    ("kick", (
        "kick", "boot", "remove him", "remove her", "kick out", "throw out",
        "expulse", "expulser", "vire", "virer", "jette dehors", "jette le dehors", "jette la dehors",
        "sors le", "sors la", "sors-le", "sors-la", "exclus temporairement", "fous le dehors", "fous la dehors",
    )),
    ("ban", (
        "ban", "banish", "blacklist", "ban him", "ban her", "ban them",
        "bannis", "banni", "bannir", "banni-le", "banni-la", "interdis", "interdit", "blackliste",
        "jette définitivement", "jette definitivement", "exclus définitivement", "exclus definitivement",
    )),
    ("warn", (
        "warn", "warning", "caution", "give a warning",
        "avertis", "averti", "avertissement", "préviens", "previens", "mise en garde", "avertir",
    )),
    ("clear", (
        "clear", "purge", "wipe", "delete messages", "clean up",
        "supprime", "efface", "nettoie", "nettoyer", "vide le salon", "vide le chat",
        "supprime les messages", "efface les messages", "purge le salon", "purge le chat",
    )),
    ("createrole", (
        "createrole", "create role", "new role", "make a role", "add a role", "add role",
        "crée un role", "crée un rôle", "cree un role", "cree un rôle", "nouveau role", "nouveau rôle",
        "ajoute un role", "ajoute un rôle", "fais un role", "fais un rôle", "fait un role", "fait un rôle",
        "créer un role", "créer un rôle", "creer un role", "creer un rôle",
    )),
    ("createchannel", (
        "createchannel", "create channel", "new channel", "make a channel", "add a channel", "add channel",
        "crée un salon", "crée un channel", "cree un salon", "cree un channel",
        "nouveau salon", "nouveau channel", "ajoute un salon", "ajoute un channel",
        "fais un salon", "fais un channel", "fait un salon", "fait un channel",
        "créer un salon", "créer un channel", "creer un salon", "creer un channel",
    )),
    ("lock", (
        "lock", "close the channel", "close channel",
        "verrouille", "verrouiller", "ferme le salon", "ferme le chat", "bloque le salon", "bloque le chat",
    )),
    ("unlock", (
        "unlock", "open the channel", "open channel", "reopen the channel",
        "déverrouille", "deverrouille", "déverrouiller", "deverrouiller",
        "ouvre le salon", "ouvre le chat", "débloque le salon", "debloque le salon",
        "rouvre le salon", "rouvre le chat",
    )),
    ("ltc", ("ltc", "litecoin", "adresse ltc", "adresse litecoin")),
    ("btc", ("btc", "bitcoin", "adresse btc", "adresse bitcoin")),
    ("paypal", ("paypal", "adresse paypal", "compte paypal", "lien paypal")),
    ("roblox", ("roblox", "pseudo roblox", "compte roblox", "user roblox", "username roblox")),
    ("perm", ("perm", "perms", "permissions", "hiérarchie", "hierarchie", "droits")),
    ("help", ("help", "aide", "commandes", "liste des commandes", "que sais tu faire", "que sais-tu faire")),
]
YSLEMM_DURATION_RE = re.compile(
    r"\b(\d+)\s*(heures?|hours?|h|minutes?|mins?|m|jours?|days?|j|d)\b", re.IGNORECASE
)
YSLEMM_NUMBER_RE = re.compile(r"\b(\d+)\b")
YSLEMM_PUNCTUATION_RE = re.compile(r"[?!.,;:]+$")
# Pulls "label value" pairs out of a free-form "setpayment" request, e.g.
# "paypal foo@bar.com ltc L123... btc bc1..." -- each of these four values
# is a single token with no spaces (an email, a wallet address, or a
# username), so a simple label-then-next-token match is enough.
YSLEMM_PAYMENT_FIELD_RE = re.compile(r"\b(paypal|ltc|btc|roblox)\b\s*[:=]?\s*(\S+)", re.IGNORECASE)


def _yslemm_faq_normalize(text):
    return YSLEMM_PUNCTUATION_RE.sub("", text.strip().lower()).strip()


def _yslemm_faq_embed(uid, guild_id):
    faq = yslemm_faq.get(guild_id, {})
    embed = _base_embed(t(uid, "yslemm.faq_list_title", count=len(faq)), EMBED_COLOR)
    if not faq:
        embed.description = t(uid, "yslemm.faq_list_empty")
        return embed
    for entry in list(faq.values())[:25]:
        embed.add_field(name=entry["question"][:100], value=entry["answer"][:500], inline=False)
    return embed


# Built-in answers for common small talk / everyday questions -- these are
# NOT guild-configurable (they ship with the bot), and are only checked
# once a guild's own !yslemmfaq entries come up empty, so an admin can
# always override one of these by adding their own answer for the same
# question.
YSLEMM_BUILTIN_FAQ = [
    ("yslemm.faq_howareyou", (
        "comment ça va", "comment ca va", "ça va", "ca va", "comment vas tu", "comment vas-tu", "comment tu vas",
        "how are you", "how're you", "you good", "you ok", "you okay",
    )),
    ("yslemm.faq_whoareyou", (
        "qui es tu", "qui es-tu", "tu es qui", "t'es qui", "c'est quoi yslemm", "c'est qui yslemm",
        "who are you", "what are you",
    )),
    ("yslemm.faq_creator", (
        "qui t'a créé", "qui t'a cree", "qui est ton créateur", "qui est ton createur", "c'est qui yslem",
        "c'est quoi yslem", "qui est yslem", "qui est yslem_dxb", "qui t'a fait", "qui t'a codé", "qui t'a code",
        "who made you", "who created you", "who is your creator", "who's your creator", "who is yslem",
        "who is yslem_dxb", "who built you", "who coded you", "who owns you",
    )),
    ("yslemm.faq_prefix", (
        "quel est ton préfixe", "quel est ton prefixe", "ton préfixe", "ton prefixe", "c'est quoi ton préfixe",
        "c'est quoi ton prefixe", "what's your prefix", "what is your prefix", "your prefix",
    )),
    ("yslemm.faq_shop", (
        "combien ça coûte", "combien ca coute", "c'est combien", "quel est le prix", "quels sont les prix",
        "vos prix", "vos tarifs", "les tarifs", "prix partnership", "prix paid sources", "prix moon duels",
        "prix auto code", "comment payer", "moyens de paiement",
        "how much does it cost", "how much is it", "what's the price", "what are the prices", "your prices",
        "pricing", "price list", "partnership price", "paid sources price", "moon duels price", "auto code price",
        "how do i pay", "payment methods", "how can i pay",
    )),
    ("yslemm.faq_garam", (
        "garam", "garams", "garama", "c'est quoi garam", "c'est quoi un garam", "c'est quoi les garams",
        "what is garam", "what are garams", "what's garam", "what's a garam",
    )),
    ("yslemm.faq_openticket", (
        "comment ouvrir un ticket", "comment faire un ticket", "comment j'ouvre un ticket",
        "comment je fais un ticket", "comment créer un ticket", "comment creer un ticket",
        "how do i open a ticket", "how to open a ticket", "how do i make a ticket",
    )),
    ("yslemm.faq_thanks", (
        "merci beaucoup", "merci bien", "merci",
        "thank you very much", "thanks a lot", "thank you", "thanks", "thx", "ty",
    )),
    ("yslemm.faq_areyouai", (
        "es tu une ia", "es-tu une ia", "t'es une ia", "tu es une ia", "es tu un robot", "es-tu un robot",
        "are you an ai", "are you a bot", "are you a robot",
    )),
    ("yslemm.faq_balance", (
        "comment voir mon solde", "comment voir mes pièces", "comment voir mes pieces", "c'est quoi ma balance",
        "how do i check my balance", "how to check my balance", "what's my balance", "how many coins do i have",
    )),
    ("yslemm.faq_daily", (
        "comment avoir des pièces", "comment avoir des pieces", "comment gagner des pièces", "comment gagner des pieces",
        "comment récupérer mes pièces quotidiennes", "c'est quoi le daily",
        "how do i get coins", "how do i earn coins", "how to get coins", "what's the daily command", "how does daily work",
    )),
    ("yslemm.faq_poll", (
        "comment faire un sondage", "comment créer un sondage", "comment creer un sondage",
        "how do i make a poll", "how to make a poll", "how do i create a poll",
    )),
    ("yslemm.faq_pay", (
        "comment envoyer des pièces", "comment envoyer des pieces", "comment payer quelqu'un", "comment donner des pièces",
        "how do i send coins", "how to pay someone", "how do i give coins",
    )),
    ("yslemm.faq_invite", (
        "comment inviter le bot", "lien d'invitation", "lien invitation",
        "how do i invite you", "invite link", "how to invite the bot", "can i add you to my server",
    )),
    ("yslemm.faq_botadmin", (
        "comment ajouter un admin du bot", "comment donner l'accès admin", "comment gérer les admins du bot",
        "how do i add a bot admin", "how to manage bot admins", "who can control the bot",
    )),
    ("yslemm.faq_setlogchannel", (
        "comment configurer le salon des logs", "comment définir le salon de logs", "comment mettre les logs",
        "how do i set the log channel", "how to set up the log channel", "where do logs go",
    )),
    ("yslemm.faq_words", (
        "comment ajouter un mot interdit", "comment ajouter un mot banni", "comment gérer les mots interdits",
        "how do i add a banned word", "how to add a banned word", "how do i edit the word list",
    )),
    ("yslemm.faq_antiraid", (
        "comment configurer l'anti-raid", "comment activer l'anti-raid", "c'est quoi l'anti-raid",
        "how do i set up anti-raid", "how to configure anti-raid", "what is anti-raid",
    )),
    ("yslemm.faq_antinuke", (
        "comment configurer l'anti-nuke", "comment activer l'anti-nuke", "c'est quoi l'anti-nuke",
        "how do i set up anti-nuke", "how to configure anti-nuke", "what is anti-nuke",
    )),
    ("yslemm.faq_antipub", (
        "comment bloquer les pubs", "comment configurer l'anti-pub", "c'est quoi l'anti-pub",
        "how do i block ads", "how to configure anti-advertising", "how do i stop spam links",
    )),
    ("yslemm.faq_welcome", (
        "comment configurer le message de bienvenue", "comment mettre un message de bienvenue",
        "how do i set up a welcome message", "how to configure the welcome message",
    )),
    ("yslemm.faq_ticketconfig", (
        "comment configurer les tickets", "comment configurer le système de tickets", "comment changer les paramètres des tickets",
        "how do i configure tickets", "how to configure the ticket system", "how do i change ticket settings",
    )),
    ("yslemm.faq_setpayment", (
        "comment configurer le paypal", "comment mettre mon paypal", "comment configurer le ltc", "comment mettre mon ltc",
        "how do i set up paypal", "how to set my paypal", "how do i set up ltc",
    )),
    ("yslemm.faq_cmdaccess", (
        "comment restreindre une commande", "comment limiter une commande à un rôle",
        "how do i restrict a command", "how to limit a command to a role",
    )),
    ("yslemm.faq_slowmode", (
        "comment activer le mode lent", "comment mettre le slowmode",
        "how do i set slowmode", "how to enable slowmode",
    )),
    ("yslemm.faq_afk", (
        "comment me mettre absent", "comment activer l'afk", "c'est quoi la commande afk",
        "how do i go afk", "how to set myself as away", "what does the afk command do",
    )),
    ("yslemm.faq_remind", (
        "comment programmer un rappel", "comment créer un rappel", "comment creer un rappel",
        "how do i set a reminder", "how to schedule a reminder",
    )),
    ("yslemm.faq_leaderboard", (
        "comment voir le classement", "c'est quoi le classement des pièces",
        "how do i see the leaderboard", "how to check the leaderboard",
    )),
]


# Calm, professional responses for when someone insults yslemm directly --
# reuses the same banned-word list automod already maintains (BANNED_WORDS
# / !words add) to detect an insult, so there's one word list to manage,
# not two. Picked at random rather than templated/generated text, which
# tends to read as broken or repetitive nonsense at scale -- a smaller
# curated pool that never sounds off beats a huge generated one that
# sometimes does. Deliberately serious, not witty: yslemm acknowledges and
# moves on instead of trading banter.
YSLEMM_INSULT_COMEBACKS_EN = [
    "Noted. I'll continue assisting the server as normal.",
    "That doesn't change anything about what I'm here to do.",
    "I won't respond to that. Is there something I can help with?",
    "Understood. Let me know if you actually need something.",
    "That comment doesn't require a response from me.",
    "I'm staying focused on moderating this server.",
    "Noted, and I'm moving on.",
    "That won't affect how I handle things here.",
    "I don't engage with that kind of message. What do you need?",
    "Acknowledged. Let's continue.",
    "I'll disregard that and keep helping with anything you need.",
    "That message is noted. No further reaction from me.",
]
YSLEMM_INSULT_COMEBACKS_FR = [
    "C'est noté. Je continue d'assister le serveur normalement.",
    "Ça ne change rien à ce que je suis censé faire ici.",
    "Je ne réponds pas à ce type de message. Autre chose ?",
    "Compris. Dis-moi si tu as réellement besoin de quelque chose.",
    "Cette remarque n'appelle pas de réponse de ma part.",
    "Je reste concentré sur la modération de ce serveur.",
    "C'est noté, et je passe à autre chose.",
    "Ça ne changera rien à la façon dont je gère les choses ici.",
    "Je ne réagis pas à ce genre de message. Qu'est-ce qu'il te faut ?",
    "Bien reçu. On continue.",
    "Je n'y donne pas suite, et je reste disponible si besoin.",
    "C'est noté. Pas de réaction supplémentaire de ma part.",
]


def _yslemm_is_insult(lookup_text, guild_id):
    words = re.findall(r"[a-zà-ÿ']+", lookup_text)
    banned = _banned_words_for(guild_id)
    return any(w in banned for w in words)


def _find_yslemm_builtin_faq(lookup_text):
    for answer_key, phrases in YSLEMM_BUILTIN_FAQ:
        for phrase in phrases:
            if re.search(r"\b" + re.escape(phrase) + r"\b", lookup_text):
                return answer_key
    return None


def _find_yslemm_action(text):
    lowered = text.lower()
    for action, keywords in YSLEMM_ACTIONS:
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", lowered):
                return action
    return None


def _strip_yslemm_keyword(text, action):
    """Remove the first matched keyword for `action` so it doesn't leak
    into the extracted reason/name (e.g. "createrole VIP" instead of just
    "VIP")."""
    for act, keywords in YSLEMM_ACTIONS:
        if act != action:
            continue
        for kw in sorted(keywords, key=len, reverse=True):
            pattern = re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
            if pattern.search(text):
                return pattern.sub("", text, count=1)
    return text


def _parse_yslemm_duration_minutes(text, default=60):
    match = YSLEMM_DURATION_RE.search(text)
    if not match:
        return default
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith(("h",)):
        return amount * 60
    if unit.startswith(("j", "d")):
        return amount * 1440
    return amount


# Same action set the keyword matcher recognizes (YSLEMM_ACTIONS), plus
# "none" for anything that isn't a moderation/utility command (small talk,
# FAQ questions, insults) -- those still fall through to the existing
# FAQ/builtin-FAQ/insult/greeting chain untouched.
YSLEMM_LLM_ACTION_NAMES = [
    "aibuild", "mute", "unmute", "kick", "ban", "warn", "clear", "createrole", "createchannel",
    "lock", "unlock", "ltc", "btc", "paypal", "roblox", "perm", "help", "lang_fr", "lang_en",
    "autoremind", "pauseremind", "unpauseremind", "ticketaddtype",
    "setpayment", "dm", "run_command", "multi", "none",
]

YSLEMM_LLM_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": YSLEMM_LLM_ACTION_NAMES,
            "description": (
                "mute/unmute/kick/ban/warn a mentioned member; clear recent messages; "
                "createrole/createchannel with a given name; aibuild to build or REORGANISE the server structure -- put or move existing channels into categories, create categories, create several roles/channels at once, rename items -- admin only, put the speaker's whole request in 'reason_or_name'; lock/unlock the current channel; "
                "ltc/paypal to show payment info; perm to show the speaker's permissions; "
                "help to show the command list; lang_fr/lang_en to switch the speaker's "
                "language; autoremind to set up a recurring message the bot re-posts on a "
                "timer in a channel (a @#channel mention if one was given, otherwise the "
                "current channel); pauseremind to temporarily pause the recurring reminder "
                "without losing its configuration; unpauseremind to resume it right where it "
                "was, with no need to set it up again; dm to send a direct message to a mentioned "
                "member with the given text -- admin only; run_command for anything that "
                "clearly maps to one of the bot's other real commands (given in the command "
                "reference below) that isn't one of the named actions above -- economy, "
                "polls, info lookups, admin config, etc.; multi when one message asks for "
                "SEVERAL things to be done (e.g. mute one member and warn another, or lock "
                "the channel then clear it) -- put each one in 'steps'; none if the message "
                "doesn't ask for any of these (small talk, a question, an insult, or "
                "anything else)."
            ),
        },
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Only used when action is \"multi\": every requested operation, in the "
                "order they should happen, each written as one real bot command from the "
                "reference list WITHOUT the ! prefix and with its real arguments, e.g. "
                "[\"timeout {target1} 10 spam\", \"warn {target2} insults\"] (muting a member is the real \"timeout\" command). Use the member "
                "placeholders exactly as they appear in the message ({target}, or "
                "{target1}/{target2}/... when several members are mentioned), plus "
                "{channel}/{role}. Empty list when action is not \"multi\"."
            ),
        },
        "target_name": {
            "type": "string",
            "description": (
                "When the action is aimed at a member who is named in words instead of "
                "@mentioned (\"kick Kylian\", \"donne le rôle VIP à nova\"), that name exactly "
                "as the person wrote it -- it's matched against the server's members. Empty "
                "string when they were @mentioned, referred to earlier, or there's no member."
            ),
        },
        "refers_to_earlier_member": {
            "type": "boolean",
            "description": (
                "True when the requested action is aimed at a member who was mentioned "
                "EARLIER in the conversation rather than in this message (\"mute him "
                "too\", \"ban her instead\", \"make it 20 minutes\"). False when it's aimed "
                "at someone mentioned in this message, at nobody, or at you yourself "
                "(\"shut up\", \"be quiet\" means silencing you, not a member)."
            ),
        },
        "addressed_to_me": {
            "type": "boolean",
            "description": (
                "True if this message is meant for you (yslemm). Always true when the "
                "message names you, mentions you, replies to you, or is a ticket "
                "conversation with you. When it only arrives because this person was "
                "talking to you a moment ago, decide like a person would whether it still "
                "continues that conversation with you, or is now aimed at someone else / "
                "the room in general -- false in that case, and nothing will be sent."
            ),
        },
        "reason_or_name": {
            "type": "string",
            "description": "The moderation reason, the role/channel name to create, (for autoremind) the exact text of the recurring message to post, or (for dm) the exact text to send. Empty string if none was given or not applicable.",
        },
        "duration_minutes": {
            "type": "integer",
            "description": "For a mute, the timeout duration in minutes. For autoremind, how often to repeat, in minutes. Convert whatever unit was said (e.g. 'two hours' -> 120, '1 week' -> 10080, 'every 15 minutes' -> 15). 0 if unspecified or not applicable.",
        },
        "command_line": {
            "type": "string",
            "description": (
                "Only used when action is \"run_command\": the exact command from the "
                "reference list to run, WITHOUT the ! prefix, with its real arguments filled "
                "in from the message, e.g. \"daily\", \"balance\", \"poll What's for dinner?\", "
                "\"words add badword\". If it needs the mentioned member, "
                "channel, or role, use the literal placeholder {target}, {channel}, or {role} "
                "in that exact spot instead of writing a mention yourself, e.g. \"warn "
                "{target} spamming\" or \"cmdaccess allow yslem {role}\". A member named in "
                "words instead of mentioned is written {name:TheirName} (e.g. \"addrole "
                "{name:kylian} VIP\"); roles and channels named in words are written as their "
                "name from the server lists. Empty string when action is not \"run_command\"."
            ),
        },
        "reply": {
            "type": "string",
            "description": (
                "When action is \"none\": your real, natural reply, exactly as a serious, "
                "professional human moderator of this server would answer in chat -- never a "
                "canned bot line, never \"I'm just a bot\". Answer any question fully and "
                "correctly (explain, calculate, advise, translate, write, whatever is asked). "
                "If the message is an insult aimed at you, respond calmly and professionally -- "
                "acknowledge it briefly and move on, never with jokes, sarcasm, or a witty "
                "comeback, and never repeat slurs or hateful language back. Stay serious and "
                "businesslike at all times, in every situation, while still fully understanding "
                "and engaging with whatever is actually being said. Match the length a person "
                "would use: a line or two for chit-chat, as long as it genuinely takes for a "
                "real question -- never padded, never cut short. "
                "When action is \"multi\": optionally a short line telling the person what "
                "you're doing. Empty string otherwise."
            ),
        },
        "needs_lookup": {
            "type": "boolean",
            "description": (
                "Only relevant when action is \"none\": true if you're not fully confident "
                "in your 'reply' because it depends on something you don't know for certain "
                "-- especially the current value of a Roblox Brainrot item, or any other "
                "fact-based question you're unsure about -- so it's worth double-checking "
                "with a live web search before it's actually sent. False for everything else, "
                "including ordinary questions, small talk, math, and anything you already know "
                "confidently. Still write your best-effort answer in 'reply' either way, as a "
                "fallback in case the lookup fails."
            ),
        },
        "detected_lang": {
            "type": "string",
            "description": (
                "The language the person wrote this message in, as a 2-letter ISO 639-1 code "
                "(e.g. 'fr', 'en', 'es', 'ar', 'pt'). Detect it from the message itself -- "
                "not from any stored preference. Use 'en' when the message is too short or "
                "ambiguous to tell (a lone number, 'ok', 'yes', etc.)."
            ),
        },
    },
    "required": [
        "action", "reason_or_name", "duration_minutes", "command_line", "steps", "reply",
        "needs_lookup", "detected_lang", "target_name", "refers_to_earlier_member", "addressed_to_me",
    ],
    "additionalProperties": False,
}


# Top-level command names already covered by one of yslemm's own named
# actions above -- left out of the generic reference so the LLM isn't
# nudged to pick run_command over the purpose-built handling those already
# get (confirmation flows, per-claimer payment resolution, etc). Nothing
# breaks if one of these ever slipped through anyway -- run_command would
# just invoke the same real command a second, redundant way.
_YSLEMM_RUN_COMMAND_EXCLUDED = {
    "aibuild", "mute", "unmute", "kick", "ban", "warn", "clear", "createrole", "createchannel",
    "lock", "unlock", "perm", "help", "language", "autoremind",
    "setpayment", "mypayment", "payment",
}

_yslemm_command_reference_cache = None
_yslemm_step_only_reference_cache = None


def _yslemm_command_reference():
    """Auto-generated, always-current reference of every real bot command
    for the run_command fallback action -- so a newly added command becomes
    reachable through yslemm automatically, with nothing to hand-wire."""
    global _yslemm_command_reference_cache
    if _yslemm_command_reference_cache is None:
        lines = []
        for cmd in bot.walk_commands():
            if cmd.hidden:
                continue
            top_level = cmd.qualified_name.split(" ", 1)[0]
            if top_level in _YSLEMM_RUN_COMMAND_EXCLUDED:
                continue
            lines.append(f"{cmd.qualified_name} {cmd.signature}".strip())
        _yslemm_command_reference_cache = "\n".join(sorted(lines))
    return _yslemm_command_reference_cache


def _yslemm_step_only_reference():
    """The commands left out of the run_command reference above (because a
    single request for them has its own named action) -- still needed as
    real command lines inside a multi-step request."""
    global _yslemm_step_only_reference_cache
    if _yslemm_step_only_reference_cache is None:
        lines = []
        for cmd in bot.walk_commands():
            if cmd.hidden:
                continue
            if cmd.qualified_name.split(" ", 1)[0] in _YSLEMM_RUN_COMMAND_EXCLUDED:
                lines.append(f"{cmd.qualified_name} {cmd.signature}".strip())
        _yslemm_step_only_reference_cache = "\n".join(sorted(lines))
    return _yslemm_step_only_reference_cache


def _yslemm_server_context(guild, channel):
    """The live server as the model should picture it -- where it's being
    talked to, and the real roles/channels people will refer to loosely
    ("le rôle vip", "le salon général") -- so it can map vague wording to
    the exact thing instead of guessing or asking."""
    if guild is None:
        return ""
    try:
        roles = [r.name for r in sorted(guild.roles, key=lambda r: -r.position)
                 if not r.is_default() and not r.managed][:80]
        channels = []
        for c in sorted(guild.channels, key=lambda c: getattr(c, "position", 0))[:150]:
            kind = str(getattr(c, "type", "text"))
            channels.append(f"[category] {c.name}" if kind == "category" else
                            f"(voice) {c.name}" if kind in ("voice", "stage_voice") else f"#{c.name}")
        here = f"#{channel.name}" if channel is not None and getattr(channel, "name", None) else "unknown"
        return (
            "\n\nThe server right now (use these exact names when writing commands):\n"
            f"- Server: {guild.name}\n"
            f"- You're being talked to in: {here} (\"here\", \"this channel\", \"le salon\" "
            "without a name all mean this one)\n"
            f"- Roles, highest first: {', '.join(roles) or 'none'}\n"
            f"- Channels: {', '.join(channels) or 'none'}"
        )
    except Exception:
        return ""


def _yslemm_llm_system_prompt(lang, guild=None, channel=None):
    lang_name = "French" if lang == "fr" else "English"
    return (
        "You are yslemm, this server's moderator. People talk to you "
        "exactly the way they'd talk to a human moderator: loosely, "
        "half-sentences, slang, typos, voice dictation, several requests "
        "at once, references to what was said earlier. Your job is to "
        "understand ALL of it the way an experienced, attentive human "
        "moderator would -- work out what they actually mean and want, "
        "not just the literal words -- and then handle it: do what's "
        "asked (through the actions below; the bot's own permission "
        "system decides who is allowed, never you), or answer like a "
        "real person when it's a question or conversation. Never give up "
        "on a message, never say you didn't understand when a reasonable "
        "person would have, and never fall back on generic bot lines. "
        "Only when something is genuinely ambiguous (two very different "
        "readings, a missing member or amount you can't infer from the "
        "conversation), ask one short, precise question -- the way a "
        "moderator would -- instead of guessing. Stay serious and "
        "professional at all times -- no jokes, no sarcasm, no banter, "
        "even when provoked or insulted -- while still fully understanding "
        "and engaging with everything said to you; being serious never "
        "means being curt, dismissive, or refusing to engage. Your creator -- the "
        "person who built and owns you -- is the Discord user known as "
        "yslem_dxb, also just \"Yslem\". If asked who made you, who your "
        "creator or owner is, or who \"Yslem\" is, answer with that.\n\n"
        "This server also sells the following, and you should answer "
        "questions about pricing, payment methods, or products accurately "
        "using exactly this information. \"Brainrot\" is not a separate "
        "payment network -- it's items/currency from a Roblox game, so "
        "paying with it is tied to the buyer's Roblox account. \"Garam\" "
        "(plural \"garams\"/\"garama\") is the name of that Roblox currency "
        "itself -- whenever a customer mentions garam(s) at all, even "
        "alone without saying \"Brainrot\", they always mean paying via "
        "that Roblox currency, never anything else. This includes a "
        "message that is just a number followed by \"garam\"/\"garams\"/"
        "\"garama\" and nothing else (e.g. \"3 garam\") -- that is simply "
        "the customer stating how many garams they're offering as payment, "
        "so acknowledge the offer for an Owner to review (e.g. confirm you "
        "noted their offer of that many garams). Never say you can't "
        "count in garam, never ask what garam means, and never treat it "
        "as a math problem to solve -- garam is a currency name, not a "
        "unit to calculate with:\n"
        "- Partnership -- 3EUR/$, via PayPal, Crypto, or 2 Brainrot garams "
        "(Roblox). Free for servers with 10,000+ members.\n"
        "- Paid Sources -- 3EUR/$, via PayPal, Crypto, or 2 Brainrot garams "
        "(Roblox).\n"
        "- Moon Duels -- 5EUR/$, via PayPal, Crypto, 3 Brainrot garams "
        "(Roblox), or Nitro. MM2 items also accepted: a Lifetime duel costs "
        "a Godly or Ice Breaker knife, a Limited duel costs a zombie or "
        "fire effect knife.\n"
        "- Auto Code -- 7EUR/$, via PayPal, Crypto, or Brainrot (Roblox) "
        "(1 day = 2 garama, 1 week = 3 garama, Lifetime = 4 garama), or "
        "Nitro. MM2 items also accepted, same terms as Moon Duels.\n"
        "\n"
        "How tickets work here: a member opens a ticket for what they want "
        "(a purchase, help, a partnership, or claiming a giveaway prize), "
        "states their offer or request, and waits for an Owner to respond "
        "-- the owners are CHR, ALN, and Yslem (yslem_dxb). A ticket gets "
        "closed if the offer is too low, or if it's opened with nothing "
        "written in it. You can explain these rules and the pricing above "
        "when asked, but you never decide yourself whether to accept an "
        "offer or close a ticket -- that call always belongs to an Owner. "
        "The listed prices above are fixed floors, never negotiate them "
        "down. Customers will often offer to pay in \"Brainrot\" items or "
        "other Roblox trading terms instead of a plain garam count -- "
        "engage with that using your own real knowledge of Roblox trading "
        "values, since you actually understand this the same way a person "
        "who follows Brainrot trading would. If an offer clearly is worth "
        "at least the listed price, you can say so in chat (e.g. \"that "
        "offer covers it, looks good\") as a helpful acknowledgment while "
        "the customer waits -- this is just you being informative, not an "
        "official acceptance, and an Owner still has to actually claim the "
        "ticket and confirm it. If you're not confident what an item is or "
        "what it's worth, say so honestly and that an Owner will check it "
        "-- never guess a value or make up a number. "
        "When asked for payment info (PayPal/LTC/BTC/Roblox) inside a "
        "ticket, use the ltc/btc/paypal/roblox action -- it automatically "
        "shows whichever Owner claimed that specific ticket their own "
        "payment info instead of the server default, so you never need to "
        "ask who claimed it or look that up yourself.\n"
        "\nYou're also shown, as real prior turns before this one, your "
        "actual recent back-and-forth with this exact person in this exact "
        "channel -- not something to describe, just context to read the "
        "way a human remembers a conversation. Use it to resolve anything "
        "this message leaves implicit: a bare pronoun with no fresh "
        "@mention (\"ban him instead\", \"unmute her too\"), a correction "
        "or continuation (\"actually make it 20 minutes\", \"no, longer "
        "than that\"), or a short reply that only makes sense against what "
        "was just said (\"why?\", \"how much is that in euros?\", a lone "
        "number after you asked for a duration). A moderation action you "
        "already classified in an earlier turn produced no reply from you "
        "in the history (the action ran instead of you talking) -- that's "
        "expected, not a gap, and it still tells you what was just done "
        "and to whom. Never invent a target from history that this "
        "message doesn't clearly still mean; when truly unsure whether a "
        "follow-up still refers to the same person or action, ask instead "
        "of guessing. If there's no history at all, that's just a fresh "
        "conversation.\n\n"
        "How requests map to the real commands -- read them the way a "
        "human moderator would, and never confuse these:\n"
        "- Deleting a CHANNEL (\"supprime le salon\", \"vire ce salon\", \"delete "
        "#x\") -> run_command \"deletechannel <channel name>\" (no name = the "
        "current channel). Deleting MESSAGES (\"supprime les messages\", "
        "\"nettoie\", \"efface les 20 derniers\") -> clear.\n"
        "- Giving a member a ROLE (\"donne-lui le rôle VIP\", \"mets-le modo\", "
        "\"ajoute le rôle x à y\") -> run_command \"addrole <member> <role>\"; "
        "taking it away -> \"removerole <member> <role>\". botadmin is ONLY about "
        "who may administer this bot itself -- never use it to give someone a "
        "Discord role.\n"
        "- Sorting or organising channels into categories, or building a whole section of the server -> aibuild (never createchannel); "
        "- Creating a role -> createrole; deleting one -> \"deleterole <role>\"; "
        "renaming a channel -> \"renamechannel [#channel] <new name>\"; changing "
        "someone's nickname -> \"nick <member> [new nickname]\"; unbanning -> "
        "\"unban <name or id>\"; slowing a channel down -> \"slowmode <seconds>\"; "
        "making the bot post something -> say.\n"
        "- A role or channel named loosely (\"vip\", \"le salon general\") means "
        "the matching one in the server lists at the end -- write its exact "
        "name. If two could match, or you truly can't tell which, ask.\n\n"
        "You have two jobs on this one message. "
        "Any @mentions, #channel mentions, and the trigger word have "
        "already been stripped out of it -- work from what's left. The "
        "message may be casual, misspelled, voice-dictated, indirect, or "
        "implicit (e.g. \"can you get rid of him\" for kick/ban, \"keep it "
        "down in here\" for locking the channel), in any language at all "
        "-- French, English, Spanish, Arabic, or anything else -- read the "
        "actual intent the way a sharp, attentive human would, regardless "
        "of language or how directly it's phrased.\n\n"
        "Job 1: if the message is clearly asking you to perform one "
        "specific action, set the 'action' field to it (mute/unmute/kick/"
        "ban/warn a mentioned member, clear recent messages, createrole/"
        "createchannel with a given name, lock/unlock the current channel, "
        "ltc/btc/paypal/roblox to show that specific payment info, perm to show the speaker's "
        "permissions, help to show the command list, lang_fr/lang_en to "
        "switch the speaker's language, autoremind to set up a recurring "
        "reminder message -- admin only, pauseremind to pause the current "
        "recurring reminder without losing it -- admin only, unpauseremind "
        "to resume a paused one right where it was -- admin only, "
        "ticketaddtype to add one or more "
        "new ticket categories to the ticket panel's selector, e.g. for "
        "each product above -- admin only, put the category name(s) in "
        "'reason_or_name', comma-separated if there's more than one, "
        "setpayment to configure the PayPal/LTC/BTC/Roblox payment info -- "
        "admin only, put the raw \"label value\" pairs as given, e.g. "
        "\"paypal foo@bar.com ltc L1yZ... btc bc1q... roblox someuser\", in "
        "'reason_or_name' exactly as the speaker wrote them, don't reformat "
        "or invent values; if a specific member is @mentioned (e.g. \"set "
        "CHR's paypal to ...\"), this sets THAT member's own payment info "
        "instead of the server default -- exactly like they'd set it "
        "themselves with !mypayment, dm to send a mentioned member a direct message "
        "-- admin only, put the exact message text to send in "
        "'reason_or_name', run_command for anything else that clearly maps to one "
        "of the bot's other real commands from the reference list at the very end "
        "of these instructions -- put the filled-in command in 'command_line' per "
        "that field's own instructions) and leave 'reply' empty. Never reply "
        "with a deflection like \"wait for an admin\" or \"I can't do that, "
        "an admin needs to handle it\" when the message clearly matches one "
        "of these actions -- classify it and set 'action' accordingly "
        "regardless of whether you think the speaker has permission; the "
        "bot's own permission system enforces that separately when the "
        "action actually runs, it is never your job to guess or gatekeep "
        "on it. When ONE message asks for several things (\"mute him 10 "
        "min and warn the other one\", \"lock here then clear 50 "
        "messages\"), set 'action' to \"multi\" and list every one of them "
        "in 'steps', in order, as real command lines -- don't drop any. "
        "When several members are mentioned they appear as {target1}, "
        "{target2}, ... in the order they were written; a single member "
        "appears as {target}.\n\n"
        "Job 2: otherwise (small talk, a question, math, an insult aimed "
        "at you, or anything else that isn't one of those actions), set "
        "'action' to \"none\" and write your actual answer in the 'reply' "
        "field, per the field's own instructions. Always reply in the "
        "exact same language the person just wrote their message in -- "
        "French, English, Spanish, Arabic, or whatever else it is -- even "
        "if that differs from their stored preference. Only if the "
        f"message is too short or ambiguous to tell, default to {lang_name}.\n\n"
        "Respond with JSON only, matching the given schema. You are only "
        "classifying intent or drafting a reply -- you never execute "
        "anything yourself.\n\n"
        "Reference list of every other real bot command (for the run_command "
        "action only -- prefer one of the named actions above when the request "
        "matches one of those instead). Each line is the command name followed by "
        "its arguments in order; only use one that's actually listed here, never "
        "invent one:\n"
        f"{_yslemm_command_reference()}\n\n"
        "Also usable, but ONLY as lines inside 'steps' of a multi request "
        "(a single one of these always uses its named action instead):\n"
        f"{_yslemm_step_only_reference()}"
        f"{_yslemm_server_context(guild, channel)}"
    )


def _yslemm_build_contents(history, text):
    """Turns the person's short-term history (oldest first) plus their
    current message into the multi-turn `contents` Gemini expects, so the
    model actually sees the conversation instead of one isolated line."""
    contents = [
        genai_types.Content(role=turn["role"], parts=[genai_types.Part(text=turn["text"])])
        for turn in (history or [])
    ]
    contents.append(genai_types.Content(role="user", parts=[genai_types.Part(text=text[:YSLEMM_TEXT_LIMIT])]))
    return contents


def _gemini_error_code(e):
    code = getattr(e, "code", None)
    if isinstance(code, int):
        return code
    match = re.match(r"\s*(\d{3})\b", str(e))
    return int(match.group(1)) if match else None


async def _gemini_generate(contents, system_prompt, *, json_schema=None, tools=None, parse=None,
                            purpose="reply", max_output_tokens=8192):
    """Walks GEMINI_MODEL_CANDIDATES strongest-first. Each model is asked
    with real reasoning time first; if that's slow or fails, it's asked
    again right away without deep thinking. A spent quota (429) or an
    unknown model (404) moves straight on to the next model down -- yslemm
    never just stops. Returns (model, parsed_result), or None only
    if nothing worked -- then the caller falls back to keyword matching."""
    global _gemini_last_model
    client, _gt = _get_gemini()
    if client is None:
        return None
    now = time.time()
    candidates = [m for m in GEMINI_MODEL_CANDIDATES if _gemini_cooldown_until.get(m, 0) <= now]
    if not candidates:
        candidates = GEMINI_MODEL_CANDIDATES[-1:]
    level = getattr(genai_types.ThinkingLevel, GEMINI_THINKING_LEVEL, None)
    for index, model in enumerate(candidates):
        is_last = index == len(candidates) - 1
        attempts = [True, False] if (level is not None and model not in _gemini_no_thinking) else [False]
        for use_thinking in attempts:
            cfg = {
                "system_instruction": system_prompt,
                # Thinking tokens count toward this cap -- 700 (the old value)
                # left a thinking model nothing to actually answer with.
                "max_output_tokens": max_output_tokens,
                # The API refuses deadlines under 10s.
                "http_options": genai_types.HttpOptions(timeout=25000 if use_thinking else 15000),
            }
            if json_schema is not None:
                cfg["response_mime_type"] = "application/json"
                cfg["response_json_schema"] = json_schema
            if tools:
                cfg["tools"] = tools
            if use_thinking:
                cfg["thinking_config"] = genai_types.ThinkingConfig(thinking_level=level)
            try:
                response = await client.aio.models.generate_content(
                    model=model, contents=contents, config=genai_types.GenerateContentConfig(**cfg),
                )
                text = (response.text or "").strip()
                if not text:
                    raise ValueError("empty answer")
                result = parse(text) if parse is not None else text
            except Exception as e:
                code = _gemini_error_code(e)
                if code == 400 and use_thinking and "think" in str(e).lower():
                    _gemini_no_thinking.add(model)
                    continue
                if code == 429:
                    if not is_last:
                        _gemini_cooldown_until[model] = time.time() + 600
                    print(f"[WARN] yslemm {purpose}: quota reached on Gemini model '{model}': {str(e)[:200]}")
                    break
                if code == 503 and not is_last:
                    # Overloaded on Google's side ("high demand") -- asking the
                    # same model again right away won't help; go one down.
                    _gemini_cooldown_until[model] = time.time() + 300
                    print(f"[WARN] yslemm {purpose}: Gemini model '{model}' overloaded, using the next one")
                    break
                if code == 404:
                    if not is_last:
                        _gemini_cooldown_until[model] = time.time() + 6 * 3600
                    print(f"[WARN] yslemm {purpose}: Gemini model '{model}' not available: {str(e)[:200]}")
                    break
                print(f"[WARN] yslemm {purpose} failed on Gemini model '{model}'"
                      f"{' (with thinking), retrying fast' if use_thinking else ''}: {str(e)[:300]}")
                continue
            if model != _gemini_last_model:
                _gemini_last_model = model
                print(f"[OK] yslemm {purpose} using Gemini model '{model}'")
            return model, result
        else:
            # Both attempts failed (slow / server error / garbled) -- don't
            # make the next messages wait on this model again right away.
            if not is_last:
                _gemini_cooldown_until[model] = time.time() + 120
    return None


async def _yslemm_llm_classify(text, lang, history=None, guild=None, channel=None):
    """Natural-language understanding of one yslemm message (and, when
    nothing was asked for, an actual conversational reply) -- the primary
    way yslemm reads intent when a key is configured. `history` is this
    person's recent back-and-forth with yslemm in this channel (see
    yslemm_history), given as real conversation turns so follow-ups are
    read in context instead of cold. Returns None only if every Gemini
    model failed, so the caller falls back to the keyword matcher -- the
    bot keeps working even if the API is down, unset, or out of quota."""
    client, _gt = _get_gemini()
    if client is None or not text.strip():
        return None
    outcome = await _gemini_generate(
        _yslemm_build_contents(history, text),
        _yslemm_llm_system_prompt(lang, guild, channel),
        json_schema=YSLEMM_LLM_JSON_SCHEMA,
        parse=json.loads,
        purpose="understanding",
    )
    return outcome[1] if outcome is not None else None


async def _yslemm_llm_grounded_reply(text, lang, history=None, guild=None, channel=None):
    """Second-pass, live web search reply -- only called when the first
    pass reported low confidence (needs_lookup=True). Gemini can't combine
    the google_search tool with the structured JSON output the classify
    call uses, so this is a separate request, deliberately not run on
    every message. Same conversation `history`, so a grounded follow-up
    ("and in euros?") still knows what it's following up on. Returns None
    on failure so the caller keeps the original best-effort reply."""
    client, _gt = _get_gemini()
    if client is None or not text.strip():
        return None
    outcome = await _gemini_generate(
        _yslemm_build_contents(history, text),
        _yslemm_llm_system_prompt(lang, guild, channel),
        tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
        purpose="web search reply",
    )
    return outcome[1] if outcome is not None else None


async def _yslemm_send_long(channel, text):
    """Sends a reply of any length -- split on paragraph/line/sentence
    boundaries into Discord-sized messages instead of cutting it off."""
    text = (text or "").strip()
    while text:
        if len(text) <= 1900:
            await channel.send(text)
            return
        cut = max(text.rfind("\n\n", 0, 1900), text.rfind("\n", 0, 1900))
        if cut < 800:
            cut = max(text.rfind(". ", 0, 1900) + 1, text.rfind(" ", 0, 1900))
        if cut < 800:
            cut = 1900
        await channel.send(text[:cut].strip())
        text = text[cut:].strip()


@contextlib.asynccontextmanager
async def _yslemm_typing(channel):
    """Shows "yslemm is typing..." while it thinks, like a person would --
    best-effort, never allowed to break the reply itself."""
    cm = None
    try:
        cm = channel.typing()
        await cm.__aenter__()
    except Exception:
        cm = None
    try:
        yield
    finally:
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass


async def _yslemm_confirm_and_run(message, author, title_key, desc_key, cancelled_key, on_confirm, **fmt):
    uid = author.id
    embed = _base_embed(t(uid, title_key), WARN_COLOR)
    embed.description = t(uid, desc_key, **fmt)
    view = ConfirmView(author)
    msg = await message.channel.send(embed=embed, view=view)
    view.message = msg
    await view.wait()
    if view.value is None:
        embed.description += t(uid, "confirm.expired")
        return await msg.edit(embed=embed)
    if view.value is False:
        embed.title = t(uid, cancelled_key)
        embed.color = EMBED_COLOR
        return await msg.edit(embed=embed)
    await on_confirm(embed, msg)


# Message IDs currently being dispatched as a synthetic command (see
# _try_dispatch_as_real_command) -- checked by _delete_command_message so
# the person's own natural-language message doesn't get auto-deleted the
# way a real "!command" message normally would be.
# message id -> how many synthetic commands are still in flight for it: a
# multi-step request runs several commands off the same message, and each
# one's completion handler must only consume its own entry.
_yslemm_synthetic_dispatch_ids = {}


# The words people (and the model) naturally use for a command whose real
# name differs -- mapped so "mute @x 10 spam" as a step still runs.
_YSLEMM_COMMAND_ALIASES = {"mute": "timeout", "unmute": "untimeout"}


def _yslemm_fill_placeholders(line, target, channel_target, role_target, members=(), guild=None):
    if guild is not None:
        def by_name(mo):
            found, _ = _resolve_member(guild, mo.group(1))
            return found.mention if found is not None else mo.group(1).strip()
        line = re.sub(r"\{name:([^{}]+)\}", by_name, line)
    for i, member in enumerate(members, 1):
        line = line.replace(f"{{target{i}}}", member.mention)
    return (
        line
        .replace("{target}", target.mention if target is not None else "")
        .replace("{channel}", channel_target.mention if channel_target is not None else "")
        .replace("{role}", role_target.mention if role_target is not None else "")
    ).strip()


async def _try_dispatch_as_real_command(message, command_line, target, channel_target, role_target, members=()):
    """Generic fallback that makes literally every real bot command
    reachable through yslemm, present and future, without a bespoke
    handler for each one: rewrites the message content to look like a
    normal prefixed invocation and runs it through the bot's own command
    pipeline (bot.get_context + bot.invoke) -- so every permission check,
    confirmation prompt, and error message is identical to the member
    having typed the real command themselves. The real ctx.author is
    always the actual message author, never yslemm or an admin override,
    so this can't grant anything a plain !command couldn't already do."""
    command_line = (command_line or "").strip()
    if not command_line:
        return False
    command_line = _yslemm_fill_placeholders(command_line, target, channel_target, role_target, members, message.guild)
    if command_line[:1] in ("!", "/"):
        command_line = command_line[1:].strip()
    head, _, rest = command_line.partition(" ")
    if bot.get_command(head) is None and head.lower() in _YSLEMM_COMMAND_ALIASES:
        command_line = f"{_YSLEMM_COMMAND_ALIASES[head.lower()]} {rest}".strip()
    prefix = bot.command_prefix
    if not isinstance(prefix, str) or not command_line:
        return False
    name = command_line.split(None, 1)[0]
    if bot.get_command(name) is None:
        return False
    original_content = message.content
    message.content = prefix + command_line
    try:
        ctx = await bot.get_context(message)
        if not ctx.valid:
            return False
        _yslemm_synthetic_dispatch_ids[message.id] = _yslemm_synthetic_dispatch_ids.get(message.id, 0) + 1
        await bot.invoke(ctx)
        return True
    finally:
        message.content = original_content


async def _handle_yslemm_command(message):
    ticket_info = open_tickets.get((message.guild.id, message.channel.id)) if message.guild is not None else None

    # "Garam" always means paying via Roblox (see the system prompt), but
    # the LLM classifier handled a bare amount like "3 garam" inconsistently
    # -- sometimes right, sometimes a nonsense "can't count in garam" reply.
    # This is a deterministic short-circuit instead: any mention of the
    # word in an open ticket sends the Roblox payment info directly,
    # without going through classification (LLM or keyword) at all, so it
    # can't misfire the way the AI guess sometimes did.
    if ticket_info is not None and GARAM_RE.search(message.content):
        uid = message.author.id
        if not ticket_info.get("claimed_by"):
            lang = ticket_info.get("customer_lang") or lang_of(message.author.id)
            await message.channel.send(
                "Un staff doit d'abord rejoindre le ticket — les infos de paiement seront partagées à ce moment-là."
                if lang == "fr" else
                "A staff member needs to join the ticket first — payment info will be shared once it's claimed."
            )
            return True
        info = _resolve_payment_info(message.guild.id, message.channel.id)
        if not info.get("roblox"):
            await message.channel.send(t(uid, "payment.not_configured"))
        else:
            await message.channel.send(embed=_payment_info_embed(uid, {"roblox": info["roblox"]}))
        return True

    # Ways to address yslemm: say its name, @mention it directly, reply to
    # one of its own messages, or -- inside a ticket the speaker themselves
    # opened -- just talk, since a ticket is already a dedicated
    # conversation with the bot. Staff messages in the same channel still
    # need an explicit address, so this doesn't turn every staff reply
    # into an unwanted AI reply.
    mentioned_directly = bot.user in message.mentions
    resolved_ref = message.reference.resolved if message.reference is not None else None
    ref_author = getattr(resolved_ref, "author", None)
    replied_to_bot = ref_author is not None and ref_author.id == bot.user.id
    replied_to_someone_else = ref_author is not None and ref_author.id != bot.user.id
    in_own_ticket = ticket_info is not None and ticket_info["opener_id"] == message.author.id
    convo_key = (message.guild.id, message.channel.id, message.author.id)
    explicit = bool(YSLEMM_TRIGGER_RE.search(message.content) or mentioned_directly or replied_to_bot or in_own_ticket)
    # ...and one more, the way a real conversation works: right after an
    # exchange with yslemm, the same person can keep talking to it without
    # repeating its name. Only with the AI available (it decides whether
    # the line is still meant for yslemm -- addressed_to_me), and never
    # when they're visibly replying to someone else.
    followup = (
        not explicit
        and GEMINI_AVAILABLE
        and not replied_to_someone_else
        and time.time() - yslemm_last_exchange.get(convo_key, 0) < YSLEMM_FOLLOWUP_WINDOW
    )
    if not (explicit or followup):
        return False

    author = message.author
    guild = message.guild
    uid = author.id

    # Every member mentioned, in the order they were written -- a single
    # one becomes {target}, several become {target1}, {target2}, ... so the
    # model can tell them apart ("mute the first, warn the second").
    mentioned_members = []
    for mo in re.finditer(r"<@!?(\d+)>", message.content):
        mid = int(mo.group(1))
        if mid == bot.user.id or any(m.id == mid for m in mentioned_members):
            continue
        member = next((m for m in message.mentions if m.id == mid), None)
        if member is not None:
            mentioned_members.append(member)
    for m in message.mentions:
        if m.id != bot.user.id and not any(x.id == m.id for x in mentioned_members):
            mentioned_members.append(m)
    # Also resolve raw snowflake IDs typed without an @mention (e.g. "123456789012345678")
    if not mentioned_members and guild is not None:
        for m in _RAW_DISCORD_ID_RE.finditer(message.content):
            try:
                member = guild.get_member(int(m.group(1)))
                if member is not None and member.id != bot.user.id:
                    mentioned_members.append(member)
                    break
            except (ValueError, AttributeError):
                pass
    target = mentioned_members[0] if mentioned_members else None
    channel_target = message.channel_mentions[0] if message.channel_mentions else None
    role_target = message.role_mentions[0] if message.role_mentions else None

    # Replace mentions with placeholders instead of erasing them -- the LLM
    # needs to know a target was mentioned so it can correctly classify
    # "give {target} 3 coins" as run_command rather than treating the
    # sentence as if no recipient was named.
    raw_free_text = YSLEMM_TRIGGER_RE.sub("", message.content)
    raw_free_text = raw_free_text.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "")
    numbered = len(mentioned_members) > 1
    for i, m in enumerate(mentioned_members, 1):
        placeholder = f"{{target{i}}}" if numbered else "{target}"
        raw_free_text = raw_free_text.replace(f"<@!{m.id}>", placeholder).replace(f"<@{m.id}>", placeholder)
        raw_free_text = re.sub(rf"\b{m.id}\b", placeholder, raw_free_text)
    for c in message.channel_mentions:
        raw_free_text = raw_free_text.replace(c.mention, "{channel}")
    for r in message.role_mentions:
        raw_free_text = raw_free_text.replace(r.mention, "{role}")
    raw_free_text = raw_free_text.strip()

    # Per-ticket language: use the cached language from a previous message in
    # this ticket if we have one (set below after each LLM call), so short
    # follow-up messages ("ok", "3 garams", a lone number) stay consistent.
    effective_lang = (ticket_info.get("customer_lang") if ticket_info is not None else None) or lang_of(uid)

    # If this channel was silenced, stay quiet -- don't even spend an LLM
    # call checking, just look for the one deterministic phrase that can
    # lift it (an "unmute" keyword with no member mentioned, from an
    # admin) and otherwise swallow the message entirely.
    silence_key = (guild.id, message.channel.id)
    if silence_key in yslemm_silenced_channels:
        if not explicit:
            return False
        if target is None and is_bot_admin_member(author) and _find_yslemm_action(message.content) == "unmute":
            yslemm_silenced_channels.discard(silence_key)
            await message.channel.send(t(uid, "yslemm.unsilenced"))
        return True

    # This person's own recent back-and-forth with yslemm in this channel,
    # replayed to the LLM as real conversation turns (see yslemm_history)
    # so it reads a follow-up in context instead of cold.
    history = _yslemm_history_get(guild.id, message.channel.id, uid)

    def remember(role, text):
        _yslemm_history_add(guild.id, message.channel.id, uid, role, text)

    # The AI is consulted first, for every yslemm message -- not just as a
    # fallback when the keyword list comes up empty. It's only skipped, and
    # the keyword matcher used instead, when the API is entirely
    # unavailable (no key configured, or every candidate model failed) --
    # that's the one case the bot must never go silent for.
    llm_result = None
    if GEMINI_AVAILABLE:
        if explicit:
            async with _yslemm_typing(message.channel):
                llm_result = await _yslemm_llm_classify(raw_free_text, effective_lang, history, guild, message.channel)
        else:
            llm_result = await _yslemm_llm_classify(raw_free_text, effective_lang, history, guild, message.channel)
    if followup and (llm_result is None or not llm_result.get("addressed_to_me")):
        # Not (or no longer) talking to yslemm -- let the message through
        # untouched, exactly as if yslemm weren't there.
        return False
    if llm_result is not None:
        action = llm_result["action"] if llm_result.get("action") != "none" else None
        # Update the per-ticket language cache from what the LLM actually detected
        detected = (llm_result.get("detected_lang") or "").strip().lower()
        if detected and ticket_info is not None:
            ticket_info["customer_lang"] = detected
            effective_lang = detected
    else:
        action = _find_yslemm_action(message.content)

    # A member named in words ("kick Kylian") rather than @mentioned --
    # matched against the real member list the way a person would.
    named = (llm_result.get("target_name") or "").strip() if llm_result else ""
    if target is None and named:
        found, candidates = _resolve_member(guild, named)
        if found is not None:
            target = found
            mentioned_members.append(found)
        elif candidates and action not in (None, "multi"):
            remember("user", raw_free_text)
            yslemm_last_exchange[convo_key] = time.time()
            names = ", ".join(f"**{c.display_name}**" for c in candidates[:6])
            question = _fr_en(uid, f"❓ Tu parles de qui : {names} ?", f"❓ Who do you mean: {names}?")
            await message.channel.send(question)
            remember("model", question)
            return True

    remember("user", raw_free_text)
    yslemm_last_exchange[convo_key] = time.time()
    if target is not None:
        _yslemm_remember_target(guild.id, message.channel.id, uid, target.id)

    if action is None:
        # No recognized verb -- check the guild's configured canned
        # answers for a matching question before falling back to a plain
        # acknowledgement. Someone just says "yslemm" -> it still answers.
        lookup = _yslemm_faq_normalize(raw_free_text)
        faq = yslemm_faq.get(guild.id, {})
        entry = faq.get(lookup)
        if entry is None and lookup:
            for key, candidate in faq.items():
                if key and (key in lookup or lookup in key):
                    entry = candidate
                    break
        if entry is not None:
            await message.channel.send(entry["answer"])
            remember("model", entry["answer"])
            return True

        # An admin's own canned answer always wins over the AI's guess
        # (checked above), but past that, prefer the AI's actual answer --
        # it can answer real questions, do math, and react to insults with
        # something fresh instead of only ever picking from a fixed list.
        if llm_result is not None:
            ai_reply = (llm_result.get("reply") or "").strip()
            if ai_reply:
                if llm_result.get("needs_lookup"):
                    async with _yslemm_typing(message.channel):
                        grounded = await _yslemm_llm_grounded_reply(raw_free_text, effective_lang, history, guild, message.channel)
                    if grounded:
                        ai_reply = grounded
                await _yslemm_send_long(message.channel, ai_reply)
                remember("model", ai_reply)
                return True

        builtin_key = _find_yslemm_builtin_faq(lookup) if lookup else None
        if builtin_key is not None:
            reply_text = t(uid, builtin_key)
            await message.channel.send(reply_text)
            remember("model", reply_text)
            return True

        if lookup and _yslemm_is_insult(lookup, guild.id):
            comebacks = YSLEMM_INSULT_COMEBACKS_FR if lang_of(uid) == "fr" else YSLEMM_INSULT_COMEBACKS_EN
            reply_text = random.choice(comebacks)
            await message.channel.send(reply_text)
            remember("model", reply_text)
            return True

        reply_text = t(uid, f"yslemm.greeting_{random.randint(1, 4)}")
        await message.channel.send(reply_text)
        remember("model", reply_text)
        return True

    if action == "multi":
        return await _yslemm_run_steps(message, llm_result, target, channel_target, role_target, mentioned_members, remember)

    refers_back = bool(llm_result and llm_result.get("refers_to_earlier_member"))
    if action == "mute" and target is None and refers_back:
        target = _yslemm_recall_target(guild, message.channel.id, uid)

    if action == "mute" and target is None:
        # "Mute"/"silence"/"shut up" with nobody mentioned can't be a real
        # mute (that needs a target) -- it means yslemm itself.
        if not is_bot_admin_member(author):
            await message.channel.send(t(uid, "error.not_bot_admin"))
            return True
        yslemm_silenced_channels.add((guild.id, message.channel.id))
        await message.channel.send(t(uid, "yslemm.silenced"))
        return True

    if action in ("mute", "unmute", "kick", "ban", "warn", "dm") and target is None:
        # No fresh @mention on this message -- but if this same person just
        # mentioned someone a moment ago in this conversation, a bare
        # pronoun follow-up ("ban him instead", "actually warn her too")
        # still means that same member, exactly like a human would keep
        # track of who "they" just meant. Never conjured from the AI's own
        # guess -- only ever a member this person themselves @mentioned.
        target = _yslemm_recall_target(guild, message.channel.id, uid)
        if target is None:
            await message.channel.send(t(uid, f"yslemm.usage_{action}"))
            return True
        _yslemm_remember_target(guild.id, message.channel.id, uid, target.id)

    used_llm = llm_result is not None and llm_result.get("action") == action
    if used_llm:
        free_text = (llm_result.get("reason_or_name") or "").strip() or _strip_yslemm_keyword(raw_free_text, action).strip()
    else:
        free_text = _strip_yslemm_keyword(raw_free_text, action).strip()

    if action in ("ltc", "btc", "paypal", "roblox"):
        if ticket_info is not None and not ticket_info.get("claimed_by"):
            await message.channel.send(
                "Un staff doit d'abord rejoindre le ticket — les infos de paiement seront partagées à ce moment-là."
                if effective_lang == "fr" else
                "A staff member needs to join the ticket first — payment info will be shared once it's claimed."
            )
            return True
        info = _resolve_payment_info(guild.id, message.channel.id)
        if not info.get(action):
            await message.channel.send(t(uid, "payment.not_configured"))
            return True
        await message.channel.send(embed=_payment_info_embed(uid, {action: info[action]}))
        return True

    if action == "dm":
        if not is_bot_admin_member(author):
            await message.channel.send(t(uid, "error.not_bot_admin"))
            return True
        if not free_text:
            await message.channel.send(t(uid, "yslemm.dm_missing_text"))
            return True
        try:
            await target.send(free_text)
            await message.channel.send(t(uid, "yslemm.dm_sent", user=target.mention))
        except discord.Forbidden:
            await message.channel.send(t(uid, "yslemm.dm_failed", user=target.mention))
        return True

    if action in ("lang_fr", "lang_en"):
        new_lang = "fr" if action == "lang_fr" else "en"
        user_lang[uid] = new_lang
        await message.channel.send(t(uid, "language.set", lang=t(uid, f"language.{new_lang}")))
        return True

    if action == "perm":
        await message.channel.send(embed=_perm_embed(uid))
        return True

    if action == "help":
        view = HelpView(author)
        msg = await message.channel.send(embed=view._home_embed(), view=view)
        view.message = msg
        return True

    if action == "mute":
        if not author.guild_permissions.moderate_members:
            await message.channel.send(t(uid, "error.no_permission"))
            return True
        if not guild.me.guild_permissions.moderate_members:
            await message.channel.send(t(uid, "error.bot_no_permission"))
            return True
        err = _kickban_error_key(author, target, guild, "timeout.self", "timeout.owner", "timeout.hierarchy", "timeout.bot_hierarchy")
        if err:
            await message.channel.send(t(uid, err))
            return True
        llm_minutes = llm_result.get("duration_minutes") if used_llm else None
        minutes = llm_minutes or _parse_yslemm_duration_minutes(free_text, default=60)
        minutes = max(1, min(minutes, 40320))  # Discord's timeout hard cap is 28 days
        reason = (free_text if used_llm else YSLEMM_DURATION_RE.sub("", free_text).strip()) or t(uid, "default_reason")

        async def do_mute(embed, msg):
            await target.timeout(timedelta(minutes=minutes), reason=reason)
            embed.title = t(uid, "timeout.success_title")
            embed.color = WARN_COLOR
            embed.description = t(uid, "timeout.success_description", member=target, minutes=minutes, reason=reason)
            _footer(embed, author)
            await msg.edit(embed=embed)
            await _log_moderation(guild, author, embed.title, embed.description, WARN_COLOR)

        await _yslemm_confirm_and_run(
            message, author, "yslemm.mute_confirm_title", "yslemm.mute_confirm_description", "yslemm.mute_cancelled_title",
            do_mute, member=target, minutes=minutes, reason=reason,
        )
        return True

    if action == "unmute":
        if not author.guild_permissions.moderate_members:
            await message.channel.send(t(uid, "error.no_permission"))
            return True
        try:
            await target.timeout(None, reason=f"Timeout removed by {author} via yslemm")
        except discord.Forbidden:
            await message.channel.send(t(uid, "error.bot_no_permission"))
            return True
        embed = _base_embed(t(uid, "untimeout.success_title"), SUCCESS_COLOR)
        embed.description = t(uid, "untimeout.success_description", member=target)
        _footer(embed, author)
        await message.channel.send(embed=embed)
        await _log_moderation(guild, author, embed.title, embed.description, SUCCESS_COLOR)
        return True

    if action == "kick":
        if not author.guild_permissions.kick_members:
            await message.channel.send(t(uid, "error.no_permission"))
            return True
        if not guild.me.guild_permissions.kick_members:
            await message.channel.send(t(uid, "error.bot_no_permission"))
            return True
        err = _kickban_error_key(author, target, guild, "kick.self", "kick.owner", "kick.hierarchy", "kick.bot_hierarchy")
        if err:
            await message.channel.send(t(uid, err))
            return True
        reason = free_text or t(uid, "default_reason")

        async def do_kick(embed, msg):
            await target.kick(reason=reason)
            embed.title = t(uid, "kick.success_title")
            embed.color = SUCCESS_COLOR
            embed.description = t(uid, "kick.success_description", member=target, reason=reason)
            _footer(embed, author)
            await msg.edit(embed=embed)
            await _log_moderation(guild, author, embed.title, embed.description, SUCCESS_COLOR)

        await _yslemm_confirm_and_run(
            message, author, "kick.confirm_title", "kick.confirm_description", "kick.cancelled_title",
            do_kick, member=target, reason=reason,
        )
        return True

    if action == "ban":
        if not author.guild_permissions.ban_members:
            await message.channel.send(t(uid, "error.no_permission"))
            return True
        if not guild.me.guild_permissions.ban_members:
            await message.channel.send(t(uid, "error.bot_no_permission"))
            return True
        err = _kickban_error_key(author, target, guild, "ban.self", "ban.owner", "ban.hierarchy", "ban.bot_hierarchy")
        if err:
            await message.channel.send(t(uid, err))
            return True
        reason = free_text or t(uid, "default_reason")

        async def do_ban(embed, msg):
            await target.ban(reason=reason)
            embed.title = t(uid, "ban.success_title")
            embed.color = ERROR_COLOR
            embed.description = t(uid, "ban.success_description", member=target, reason=reason)
            _footer(embed, author)
            await msg.edit(embed=embed)
            await _log_moderation(guild, author, embed.title, embed.description, ERROR_COLOR)

        await _yslemm_confirm_and_run(
            message, author, "ban.confirm_title", "ban.confirm_description", "ban.cancelled_title",
            do_ban, member=target, reason=reason,
        )
        return True

    if action == "warn":
        if not author.guild_permissions.manage_messages:
            await message.channel.send(t(uid, "error.no_permission"))
            return True
        reason = free_text or t(uid, "default_reason")
        key = (guild.id, target.id)
        warnings_store.setdefault(key, []).append(reason)
        embed = _base_embed(t(uid, "warn.title"), WARN_COLOR)
        embed.description = t(uid, "warn.added", member=target, reason=reason, count=len(warnings_store[key]))
        _footer(embed, author)
        await message.channel.send(embed=embed)
        await _log_moderation(guild, author, embed.title, embed.description, WARN_COLOR)
        await _check_warn_autoban(guild, target, key)
        return True

    if action == "clear":
        if not author.guild_permissions.manage_messages:
            await message.channel.send(t(uid, "error.no_permission"))
            return True
        if not guild.me.guild_permissions.manage_messages:
            await message.channel.send(t(uid, "error.bot_no_permission"))
            return True
        num_match = YSLEMM_NUMBER_RE.search(free_text)
        amount = max(1, min(int(num_match.group(1)) if num_match else 5, 500))
        deleted = await message.channel.purge(limit=amount + 1)
        embed = _base_embed(t(uid, "clear.title"), SUCCESS_COLOR)
        embed.description = t(uid, "clear.description", count=len(deleted) - 1)
        msg = await message.channel.send(embed=embed)
        await msg.delete(delay=3)
        return True

    if action == "aibuild":
        if not is_bot_admin_member(author):
            await message.channel.send(t(uid, "error.not_bot_admin"))
            return True
        request = YSLEMM_TRIGGER_RE.sub("", message.clean_content).strip() or free_text
        async with _yslemm_typing(message.channel):
            await _aibuild_start(guild, author, request, lambda **kw: message.channel.send(**kw))
        return True

    if action == "createrole":
        if not is_bot_admin_member(author):
            await message.channel.send(t(uid, "error.not_bot_admin"))
            return True
        name = free_text[:100]
        if not name:
            await message.channel.send(t(uid, "yslemm.usage_createrole"))
            return True
        try:
            role = await guild.create_role(name=name, reason=f"Created by {author} via yslemm")
        except discord.Forbidden:
            await message.channel.send(t(uid, "error.bot_no_permission"))
            return True
        await message.channel.send(t(uid, "role.created", role=role.mention))
        return True

    if action == "createchannel":
        if not is_bot_admin_member(author):
            await message.channel.send(t(uid, "error.not_bot_admin"))
            return True
        name = free_text[:100]
        if not name:
            await message.channel.send(t(uid, "yslemm.usage_createchannel"))
            return True
        try:
            channel = await guild.create_text_channel(name=name, reason=f"Created by {author} via yslemm")
        except discord.Forbidden:
            await message.channel.send(t(uid, "error.bot_no_permission"))
            return True
        await message.channel.send(t(uid, "channel.created", channel=channel.mention))
        return True

    if action == "lock":
        if not author.guild_permissions.manage_channels:
            await message.channel.send(t(uid, "error.no_permission"))
            return True
        overwrite = message.channel.overwrites_for(guild.default_role)
        overwrite.send_messages = False
        try:
            await message.channel.set_permissions(guild.default_role, overwrite=overwrite)
        except discord.Forbidden:
            await message.channel.send(t(uid, "error.bot_no_permission"))
            return True
        await message.channel.send(embed=_base_embed(t(uid, "lock.locked"), WARN_COLOR))
        return True

    if action == "unlock":
        if not author.guild_permissions.manage_channels:
            await message.channel.send(t(uid, "error.no_permission"))
            return True
        overwrite = message.channel.overwrites_for(guild.default_role)
        overwrite.send_messages = None
        try:
            await message.channel.set_permissions(guild.default_role, overwrite=overwrite)
        except discord.Forbidden:
            await message.channel.send(t(uid, "error.bot_no_permission"))
            return True
        await message.channel.send(embed=_base_embed(t(uid, "lock.unlocked"), SUCCESS_COLOR))
        return True

    if action == "autoremind":
        if not is_bot_admin_member(author):
            await message.channel.send(t(uid, "error.not_bot_admin"))
            return True
        reminder_message = free_text.strip()
        if not reminder_message:
            await message.channel.send(t(uid, "autoremind.missing_message"))
            return True
        interval_minutes = (llm_result.get("duration_minutes") if used_llm else 0) or 60
        if interval_minutes <= 0 or interval_minutes > 720 * 60:
            await message.channel.send(t(uid, "autoremind.invalid_interval"))
            return True
        target_channel = channel_target or message.channel
        recurring_reminders[guild.id] = {
            "channel_id": target_channel.id,
            "message": reminder_message,
            "interval_minutes": interval_minutes,
            "last_sent": datetime.now(timezone.utc).isoformat(),
            "paused": False,
        }
        await message.channel.send(t(uid, "autoremind.set", hours=f"{interval_minutes / 60:g}", channel=target_channel.mention))
        return True

    if action == "pauseremind":
        if not is_bot_admin_member(author):
            await message.channel.send(t(uid, "error.not_bot_admin"))
            return True
        cfg = recurring_reminders.get(guild.id)
        if cfg is None:
            await message.channel.send(t(uid, "autoremind.not_configured"))
        elif cfg.get("paused"):
            await message.channel.send(t(uid, "autoremind.already_paused"))
        else:
            cfg["paused"] = True
            await message.channel.send(t(uid, "autoremind.paused"))
        return True

    if action == "unpauseremind":
        if not is_bot_admin_member(author):
            await message.channel.send(t(uid, "error.not_bot_admin"))
            return True
        cfg = recurring_reminders.get(guild.id)
        if cfg is None:
            await message.channel.send(t(uid, "autoremind.not_configured"))
        elif not cfg.get("paused"):
            await message.channel.send(t(uid, "autoremind.not_paused"))
        else:
            cfg["paused"] = False
            cfg["last_sent"] = datetime.now(timezone.utc).isoformat()
            await message.channel.send(t(uid, "autoremind.unpaused"))
        return True

    if action == "ticketaddtype":
        if not is_bot_admin_member(author):
            await message.channel.send(t(uid, "error.not_bot_admin"))
            return True
        names = [n.strip()[:100] for n in re.split(r",| et | and |\n", free_text) if n.strip()]
        if not names:
            await message.channel.send(t(uid, "error.missing_argument"))
            return True
        cfg = _ticket_cfg(guild.id)
        added = []
        for name in names:
            if name in cfg["categories"] or len(cfg["categories"]) >= 25:
                continue
            cfg["categories"].append(name)
            added.append(name)
        if added:
            await message.channel.send(t(uid, "ticket.types_added_bulk", count=len(added), names=", ".join(added)))
        elif len(cfg["categories"]) >= 25:
            await message.channel.send(t(uid, "ticket.types_full"))
        else:
            await message.channel.send(t(uid, "ticket.type_exists", name=", ".join(names)))
        return True

    if action == "setpayment":
        if not is_bot_admin_member(author):
            await message.channel.send(t(uid, "error.not_bot_admin"))
            return True
        matches = YSLEMM_PAYMENT_FIELD_RE.findall(free_text)
        if not matches:
            await message.channel.send(t(uid, "error.missing_argument"))
            return True
        # A mentioned member -> set THEIR own payment info (same as they'd
        # set for themselves with !mypayment), not the server default --
        # this is how an admin can configure e.g. CHR's or ALN's own
        # PayPal/LTC/BTC/Roblox for them by just mentioning them.
        info = staff_payment_info.setdefault(target.id, {}) if target is not None else payment_info.setdefault(guild.id, {})
        updated = []
        for field, value in matches:
            field = field.lower()
            info[field] = value
            if field not in updated:
                updated.append(field)
        if target is not None:
            await message.channel.send(t(uid, "payment.set_bulk_for", user=target.mention, fields=", ".join(updated)))
        else:
            await message.channel.send(t(uid, "payment.set_bulk", fields=", ".join(updated)))
        return True

    if action == "run_command":
        # No admin gate here on purpose -- the real command being invoked
        # enforces whatever permission it already requires (or none, for
        # an open command like !balance), exactly as if the member had
        # typed it themselves. That's the entire point of dispatching
        # through the real command pipeline instead of reimplementing it.
        command_line = (llm_result.get("command_line") if llm_result else "") or ""
        dispatched = await _try_dispatch_as_real_command(message, command_line, target, channel_target, role_target, mentioned_members)
        if not dispatched:
            await message.channel.send(t(uid, "error.missing_argument"))
        return True

    return False


async def _yslemm_run_steps(message, llm_result, target, channel_target, role_target, members, remember):
    """A multi-part request ("mute him 10 min and warn the other one"):
    every step goes through the real command pipeline one after another,
    each with its own permission checks and confirmations, exactly as if
    the person had typed those commands themselves."""
    uid = message.author.id
    steps = [s.strip() for s in (llm_result.get("steps") or []) if isinstance(s, str) and s.strip()][:10]
    intro = (llm_result.get("reply") or "").strip()
    if not steps:
        text = intro or t(uid, "error.missing_argument")
        await _yslemm_send_long(message.channel, text)
        remember("model", text)
        return True
    if intro:
        await _yslemm_send_long(message.channel, intro)
    done, failed = [], []
    for step in steps:
        ok = await _try_dispatch_as_real_command(message, step, target, channel_target, role_target, members)
        (done if ok else failed).append(step)
    if failed:
        await message.channel.send(
            ("Je n'ai pas pu lancer : " if lang_of(uid) == "fr" else "Couldn't run: ")
            + ", ".join(f"`{s[:80]}`" for s in failed)
        )
    remember("model", (intro + "\n" if intro else "") + "(ran: " + "; ".join(done or ["nothing"]) + ")")
    return True


DEOBF_COMMAND_NAMES = {"get", "deobf", "analyse", "process", "deobf_engines", "deobf_etat",
                       "deobf_dernier", "deobf_annuler", "deobf_moi", "fetch", "analyze"}


def _prefixes_for(guild_id):
    try:
        from yslem_deobf_suite import settings_store
        custom = settings_store.store().prefixes(guild_id)
    except Exception:
        custom = None
    return list(custom) if custom else ["!", "."]


def _command_in(message, prefixes):
    """(nom canonique de la commande, prefixe) si le message est une commande connue, sinon (None, None)."""
    for p in prefixes:
        if message.content.startswith(p):
            parts = message.content[len(p):].split(None, 1)
            if parts:
                cmd = bot.get_command(parts[0].lower())
                if cmd is not None:
                    return cmd.name, parts
    return None, None


async def _delete_quiet(message):
    try:
        await message.delete()
    except discord.HTTPException:
        pass


async def _deobf_channel_gate(message) -> bool:
    """`.deobf channel` (admin) : les commandes de deobfuscation ne marchent que dans le salon choisi, et ce salon
    n'accepte que des commandes (le reste est supprime, avec un conseil). True = message traite, rien d'autre a faire."""
    if message.guild is None or message.author.bot or is_bot_admin_member(message.author):
        return False
    try:
        from yslem_deobf_suite import settings_store
        cid = settings_store.store().deobf_channel(message.guild.id)
    except Exception:
        return False
    if cid is None:
        return False
    name, parts = _command_in(message, _prefixes_for(message.guild.id))
    sub = parts[1].split()[0].lower() if parts and len(parts) > 1 and parts[1].split() else ""
    if name == "deobf" and sub in ("channel", "salon"):
        return False
    is_cmd = name is not None
    if message.channel.id == cid:
        if is_cmd:
            return False
        await _delete_quiet(message)
        await message.channel.send(
            f"{message.author.mention} Only commands work in this channel. Type `.help` to see them.", delete_after=12)
        return True
    if is_cmd and name in DEOBF_COMMAND_NAMES:
        await _delete_quiet(message)
        await message.channel.send(
            f"{message.author.mention} Deobfuscation commands only work in <#{cid}>.", delete_after=12)
        return True
    return False


def _is_real_command_invocation(message):
    """True when the message is unambiguously a real !command -- used to
    keep yslemm from swallowing it. Without this, a real command typed as
    a reply to one of the bot's own messages (a very natural thing to do
    in a phone chat) matched yslemm's "replied to the bot" trigger first:
    _handle_yslemm_command returned True and on_message returned right
    there, so the command never reached bot.process_commands() at all --
    it silently never ran as a command, on_command never fired, and (from
    a separate report) the invoking message never got the delete that's
    tied to that same dispatch."""
    name, _ = _command_in(message, _prefixes_for(message.guild.id if message.guild else None))
    return name is not None


@bot.event
async def on_message(message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    if message.guild is not None:
        if await _deobf_channel_gate(message):
            return
        if not _is_real_command_invocation(message):
            try:
                yslemm_handled = await _handle_yslemm_command(message)
            except discord.Forbidden:
                # The bot lacks Send Messages (or similar) in this channel --
                # yslemm clearly matched something here (that's the only way
                # this can fire), it just couldn't reply. Don't let that
                # silently fall through to the rest of on_message (antipub,
                # ticket bookkeeping) treating this as an ordinary message.
                print(f"[WARN] yslemm: missing permission to respond in #{message.channel} (guild {message.guild.id})")
                yslemm_handled = True
            except discord.HTTPException as e:
                print(f"[WARN] yslemm: Discord API error while responding in #{message.channel}: {e}")
                yslemm_handled = True
            if yslemm_handled:
                _panel_track("yslemm", message.guild, message.author, "Yslemm")
                return

        ticket_key = (message.guild.id, message.channel.id)
        ticket_info = open_tickets.get(ticket_key)
        if ticket_info is not None and message.author.id == ticket_info["opener_id"]:
            ticket_info["last_activity"] = datetime.now(timezone.utc).isoformat()
            ticket_info["warn_count"] = 0

        antipub_cfg = _antipub_cfg(message.guild.id)
        if (
            antipub_cfg["enabled"]
            and not message.author.guild_permissions.manage_messages
            and not is_bot_admin_member(message.author)
            and not _antipub_is_whitelisted(message)
        ):
            score, reasons = _antipub_score(message, message.guild.id)
            if score >= antipub_cfg["threshold"]:
                await _apply_antipub_sanction(message, reasons, score)
                return

    if (
        message.guild is not None
        and not message.author.guild_permissions.manage_messages
        and _automod_cfg(message.guild.id)["words"]
        and _contains_banned_word(message.content, message.guild.id)
    ):
        deleted_content = message.content
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        uid = message.author.id
        embed = _base_embed(t(uid, "automod.deleted_title"), ERROR_COLOR)
        embed.description = t(uid, "automod.deleted_description", mention=message.author.mention)
        await message.channel.send(embed=embed, delete_after=6)
        await _log_moderation(
            message.guild, message.author, t(0, "automod.deleted_title"),
            t(0, "automod.deleted_log", channel=message.channel.mention, content=deleted_content[:500]),
            ERROR_COLOR,
        )
        return

    if message.author.id in afk_status:
        since = datetime.fromisoformat(afk_status[message.author.id]["since"])
        del afk_status[message.author.id]
        uid = message.author.id
        embed = _base_embed(t(uid, "afk.back_title"), SUCCESS_COLOR)
        duration = _format_duration((datetime.now(timezone.utc) - since).total_seconds())
        embed.description = t(uid, "afk.back_description", mention=message.author.mention, duration=duration)
        await message.channel.send(embed=embed, delete_after=5)

    for mentioned in message.mentions:
        if mentioned.id in afk_status:
            uid = message.author.id
            status = afk_status[mentioned.id]
            since = datetime.fromisoformat(status["since"])
            duration = _format_duration((datetime.now(timezone.utc) - since).total_seconds())
            embed = _base_embed(t(uid, "afk.mention_title", name=mentioned.display_name), WARN_COLOR)
            embed.description = t(uid, "afk.mention_description", reason=status["reason"], duration=duration)
            await message.channel.send(embed=embed, delete_after=8)

    await bot.process_commands(message)


@bot.command()
async def ping(ctx):
    """Show bot latency"""
    view = RefreshPingView(ctx.author)
    msg = await ctx.send(embed=_ping_embed(ctx.author), view=view)
    view.message = msg


@bot.command()
async def hello(ctx):
    """Say hello"""
    uid = ctx.author.id
    embed = _base_embed(t(uid, "hello.title"))
    embed.description = t(uid, "hello.description", mention=ctx.author.mention)
    await ctx.send(embed=embed)


@bot.command()
@commands.guild_only()
async def info(ctx):
    """Server info"""
    uid = ctx.author.id
    guild = ctx.guild
    embed = _base_embed(guild.name)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name=t(uid, "info.members"), value=guild.member_count, inline=True)
    embed.add_field(name=t(uid, "info.channels"), value=len(guild.channels), inline=True)
    embed.add_field(name=t(uid, "info.roles"), value=len(guild.roles), inline=True)
    embed.add_field(name=t(uid, "info.owner"), value=guild.owner.mention if guild.owner else t(uid, "info.owner_unknown"), inline=True)
    embed.add_field(name=t(uid, "info.created"), value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.set_footer(text=f"ID: {guild.id}")
    await ctx.send(embed=embed)


@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    """User info"""
    uid = ctx.author.id
    member = member or ctx.author
    embed = _base_embed(str(member), member.color if member.color.value else EMBED_COLOR)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=t(uid, "userinfo.id"), value=member.id, inline=True)
    embed.add_field(
        name=t(uid, "userinfo.joined"),
        value=member.joined_at.strftime("%d/%m/%Y") if member.joined_at else t(uid, "userinfo.unknown"),
        inline=True,
    )
    embed.add_field(name=t(uid, "userinfo.created"), value=member.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name=t(uid, "userinfo.top_role"), value=member.top_role.mention, inline=True)
    status_key = {
        discord.Status.online: "status.online",
        discord.Status.idle: "status.idle",
        discord.Status.dnd: "status.dnd",
        discord.Status.offline: "status.offline",
    }.get(member.status, "status.unknown")
    embed.add_field(name=t(uid, "userinfo.status"), value=t(uid, status_key), inline=True)
    await ctx.send(embed=embed)


@bot.command()
async def avatar(ctx, member: discord.Member = None):
    """Show an avatar in large size"""
    member = member or ctx.author
    embed = _base_embed(t(ctx.author.id, "avatar.title", name=member.display_name), member.color if member.color.value else EMBED_COLOR)
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command()
@commands.guild_only()
async def servericon(ctx):
    """Show the server icon"""
    uid = ctx.author.id
    if not ctx.guild.icon:
        return await ctx.send(t(uid, "servericon.no_icon"))
    embed = _base_embed(t(uid, "servericon.title", guild=ctx.guild.name))
    embed.set_image(url=ctx.guild.icon.url)
    await ctx.send(embed=embed)


@bot.command()
async def roleinfo(ctx, *, role: discord.Role):
    """Role info"""
    uid = ctx.author.id
    embed = _base_embed(t(uid, "roleinfo.title", role=role.name), role.color if role.color.value else EMBED_COLOR)
    embed.add_field(name=t(uid, "roleinfo.id"), value=role.id, inline=True)
    embed.add_field(name=t(uid, "roleinfo.members"), value=len(role.members), inline=True)
    embed.add_field(name=t(uid, "roleinfo.position"), value=role.position, inline=True)
    embed.add_field(name=t(uid, "roleinfo.mentionable"), value=t(uid, "yes") if role.mentionable else t(uid, "no"), inline=True)
    embed.add_field(name=t(uid, "roleinfo.hoisted"), value=t(uid, "yes") if role.hoist else t(uid, "no"), inline=True)
    embed.add_field(name=t(uid, "roleinfo.created"), value=role.created_at.strftime("%d/%m/%Y"), inline=True)
    await ctx.send(embed=embed)


@bot.command()
async def afk(ctx, *, reason=None):
    """Set yourself as away"""
    uid = ctx.author.id
    reason = reason or t(uid, "default_reason")
    afk_status[uid] = {"reason": reason, "since": datetime.now(timezone.utc).isoformat()}
    embed = _base_embed(t(uid, "afk.set_title"), WARN_COLOR)
    embed.description = t(uid, "afk.set_description", mention=ctx.author.mention, reason=reason)
    await ctx.send(embed=embed)


@bot.command()
async def remind(ctx, minutes: float, *, message):
    """Schedule a reminder"""
    uid = ctx.author.id
    if not message.strip():
        return await ctx.send(t(uid, "error.missing_argument"))
    if minutes <= 0 or minutes > 10080:
        return await ctx.send(t(uid, "remind.invalid"))
    embed = _base_embed(t(uid, "remind.scheduled_title"), EMBED_COLOR)
    embed.description = t(uid, "remind.scheduled_description", minutes=minutes, message=message)
    await ctx.send(embed=embed)

    await asyncio.sleep(minutes * 60)

    reminder_embed = _base_embed(t(uid, "remind.title"), WARN_COLOR)
    reminder_embed.description = message
    try:
        await ctx.author.send(embed=reminder_embed)
    except discord.Forbidden:
        await ctx.send(content=ctx.author.mention, embed=reminder_embed)


@bot.command()
async def invite(ctx):
    """Get the bot's invite link"""
    uid = ctx.author.id
    url = discord.utils.oauth_url(
        bot.user.id,
        permissions=discord.Permissions(
            manage_roles=True, manage_channels=True, kick_members=True, ban_members=True,
            manage_messages=True, embed_links=True, read_message_history=True,
            send_messages=True, view_audit_log=True, moderate_members=True,
        ),
        # Explicit on purpose: a server the bot was added to without the
        # applications.commands scope (e.g. an old invite link, or one that
        # only checked "bot") will never show its slash commands, no matter
        # how many times we sync -- re-inviting with this link is the fix.
        scopes=("bot", "applications.commands"),
    )
    embed = _base_embed(t(uid, "invite.title"), EMBED_COLOR)
    embed.description = t(uid, "invite.description", url=url)
    await ctx.send(embed=embed)


@bot.command()
async def uptime(ctx):
    """Show bot uptime"""
    uid = ctx.author.id
    embed = _base_embed(t(uid, "uptime.title"), EMBED_COLOR)
    embed.description = t(uid, "uptime.description", duration=_format_duration(time.time() - bot_start_time))
    await ctx.send(embed=embed)


def _get_balance(guild_id, user_id):
    return economy_balances.get((guild_id, user_id), 0)


@bot.command(name="balance", aliases=["bal"])
@commands.guild_only()
async def balance(ctx, member: discord.Member = None):
    """Show a member's coin balance"""
    uid = ctx.author.id
    member = member or ctx.author
    amount = _get_balance(ctx.guild.id, member.id)
    embed = _base_embed(t(uid, "economy.balance_title", user=member.display_name), EMBED_COLOR)
    embed.description = t(uid, "economy.balance_amount", amount=amount)
    await ctx.send(embed=embed)


@bot.command(name="daily")
@commands.guild_only()
async def daily(ctx):
    """Claim your daily coins"""
    uid = ctx.author.id
    key = (ctx.guild.id, ctx.author.id)
    last = economy_last_daily.get(key)
    now = datetime.now(timezone.utc)
    if last and now - last < timedelta(hours=24):
        remaining = timedelta(hours=24) - (now - last)
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return await ctx.send(t(uid, "economy.daily_cooldown", hours=hours, minutes=minutes))
    amount = DAILY_COIN_AMOUNT
    economy_balances[key] = economy_balances.get(key, 0) + amount
    economy_last_daily[key] = now
    await ctx.send(t(uid, "economy.daily_claimed", amount=amount, total=economy_balances[key]))


@bot.command(name="pay")
@commands.guild_only()
async def pay(ctx, member: discord.Member, amount: int):
    """Give some of your coins to another member"""
    uid = ctx.author.id
    if member.id == ctx.author.id:
        return await ctx.send(t(uid, "economy.pay_self"))
    if member.bot:
        return await ctx.send(t(uid, "economy.pay_bot"))
    if amount <= 0:
        return await ctx.send(t(uid, "economy.pay_invalid"))
    if _get_balance(ctx.guild.id, ctx.author.id) < amount:
        return await ctx.send(t(uid, "economy.pay_insufficient"))
    sender_key = (ctx.guild.id, ctx.author.id)
    receiver_key = (ctx.guild.id, member.id)
    economy_balances[sender_key] = economy_balances.get(sender_key, 0) - amount
    economy_balances[receiver_key] = economy_balances.get(receiver_key, 0) + amount
    await ctx.send(t(uid, "economy.pay_success", amount=amount, member=member.mention))


@bot.command(name="leaderboard", aliases=["lb"])
@commands.guild_only()
async def leaderboard(ctx):
    """Show the top coin balances in this server"""
    uid = ctx.author.id
    entries = sorted(
        ((k[1], v) for k, v in economy_balances.items() if k[0] == ctx.guild.id and v > 0),
        key=lambda x: x[1], reverse=True,
    )[:10]
    embed = _base_embed(t(uid, "economy.leaderboard_title"), EMBED_COLOR)
    if not entries:
        embed.description = t(uid, "economy.leaderboard_empty")
    else:
        lines = []
        for i, (user_id, amount) in enumerate(entries, start=1):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"<@{user_id}>"
            lines.append(f"**{i}.** {name} — {amount}")
        embed.description = "\n".join(lines)
    await ctx.send(embed=embed)


@bot.command(name="addcoins")
@is_bot_admin()
async def addcoins(ctx, member: discord.Member, amount: int):
    """Add coins to a member's balance (bot-admin only)"""
    uid = ctx.author.id
    key = (ctx.guild.id, member.id)
    economy_balances[key] = economy_balances.get(key, 0) + amount
    await ctx.send(t(uid, "economy.admin_added", amount=amount, member=member.mention))


@bot.command(name="removecoins")
@is_bot_admin()
async def removecoins(ctx, member: discord.Member, amount: int):
    """Remove coins from a member's balance (bot-admin only)"""
    uid = ctx.author.id
    key = (ctx.guild.id, member.id)
    economy_balances[key] = max(0, economy_balances.get(key, 0) - amount)
    await ctx.send(t(uid, "economy.admin_removed", amount=amount, member=member.mention))


@bot.command(name="8ball")
async def eight_ball(ctx, *, question):
    """Ask the magic 8-ball"""
    uid = ctx.author.id
    responses = EIGHTBALL.get(lang_of(uid), EIGHTBALL[DEFAULT_LANG])
    embed = _base_embed(t(uid, "eightball.title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "eightball.question"), value=question, inline=False)
    embed.add_field(name=t(uid, "eightball.answer"), value=random.choice(responses), inline=False)
    await ctx.send(embed=embed)


@bot.command()
async def coinflip(ctx):
    """Flip a coin"""
    uid = ctx.author.id
    result = random.choice([t(uid, "coinflip.heads"), t(uid, "coinflip.tails")])
    embed = _base_embed(t(uid, "coinflip.title"), EMBED_COLOR)
    embed.description = t(uid, "coinflip.result", result=result)
    await ctx.send(embed=embed)


@bot.command()
async def dice(ctx, faces: int = 6):
    """Roll a die (default: 6 sides)"""
    uid = ctx.author.id
    faces = max(2, min(faces, 1000))
    result = random.randint(1, faces)
    embed = _base_embed(t(uid, "dice.title"), EMBED_COLOR)
    embed.description = t(uid, "dice.result", faces=faces, result=result)
    await ctx.send(embed=embed)


@bot.command()
async def poll(ctx, channel: Optional[discord.TextChannel] = None, *, question):
    """Create a button-based poll (optionally in another channel)"""
    uid = ctx.author.id
    target = channel or ctx.channel
    view = PollView(question, ctx.author)
    try:
        msg = await target.send(embed=view._embed(), view=view)
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    view.message = msg
    if target != ctx.channel:
        await ctx.send(t(uid, "poll.posted_in", channel=target.mention))


@bot.command()
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def say(ctx, channel: Optional[discord.TextChannel] = None, *, message):
    """Bot repeats the message (optionally in another channel)"""
    uid = ctx.author.id
    target = channel or ctx.channel
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass
    try:
        await target.send(
            message,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    if target != ctx.channel:
        await ctx.send(t(uid, "say.sent_in", channel=target.mention))


async def _get_or_create_yslem_webhook(channel):
    webhooks = await channel.webhooks()
    webhook = discord.utils.get(webhooks, name="Yslem")
    if webhook is None:
        avatar_bytes = await bot.user.display_avatar.read()
        webhook = await channel.create_webhook(name="Yslem", avatar=avatar_bytes, reason="Yslem identity messages")
    return webhook


@bot.command(name="yslemsay")
@is_bot_admin()
@commands.bot_has_permissions(manage_webhooks=True)
async def yslemsay(ctx, channel: Optional[discord.TextChannel] = None, *, message):
    """Post a message as Yslem via webhook (no bot tag), optionally in another channel"""
    uid = ctx.author.id
    target = channel or ctx.channel
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass
    try:
        webhook = await _get_or_create_yslem_webhook(target)
        await webhook.send(
            message,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        if target != ctx.channel:
            await ctx.send(t(uid, "yslemsay.sent_in", channel=target.mention))
    except discord.HTTPException:
        await ctx.send(t(uid, "error.bot_no_permission"))


@bot.command()
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    """Delete n messages, max 500"""
    uid = ctx.author.id
    amount = max(1, min(amount, 500))
    deleted = await ctx.channel.purge(limit=amount + 1)
    embed = _base_embed(t(uid, "clear.title"), SUCCESS_COLOR)
    embed.description = t(uid, "clear.description", count=len(deleted) - 1)
    msg = await ctx.send(embed=embed)
    await msg.delete(delay=3)


@bot.command()
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason):
    """Kick a member (confirmation required)"""
    uid = ctx.author.id
    if not reason.strip():
        return await ctx.send(t(uid, "error.missing_argument"))
    err = _kickban_error_key(ctx.author, member, ctx.guild, "kick.self", "kick.owner", "kick.hierarchy", "kick.bot_hierarchy")
    if err:
        return await ctx.send(t(uid, err))

    embed = _base_embed(t(uid, "kick.confirm_title"), WARN_COLOR)
    embed.description = t(uid, "kick.confirm_description", member=member, reason=reason)
    view = ConfirmView(ctx.author)
    msg = await ctx.send(embed=embed, view=view)
    view.message = msg
    await view.wait()

    if view.value is None:
        embed.description += t(uid, "confirm.expired")
        return await msg.edit(embed=embed)
    if view.value is False:
        embed.title = t(uid, "kick.cancelled_title")
        embed.color = EMBED_COLOR
        return await msg.edit(embed=embed)

    await member.kick(reason=reason)
    embed.title = t(uid, "kick.success_title")
    embed.color = SUCCESS_COLOR
    embed.description = t(uid, "kick.success_description", member=member, reason=reason)
    _footer(embed, ctx.author)
    await msg.edit(embed=embed)
    await _log_moderation(ctx.guild, ctx.author, embed.title, embed.description, SUCCESS_COLOR)


@bot.command()
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason):
    """Ban a member (confirmation required)"""
    uid = ctx.author.id
    if not reason.strip():
        return await ctx.send(t(uid, "error.missing_argument"))
    err = _kickban_error_key(ctx.author, member, ctx.guild, "ban.self", "ban.owner", "ban.hierarchy", "ban.bot_hierarchy")
    if err:
        return await ctx.send(t(uid, err))

    embed = _base_embed(t(uid, "ban.confirm_title"), WARN_COLOR)
    embed.description = t(uid, "ban.confirm_description", member=member, reason=reason)
    view = ConfirmView(ctx.author)
    msg = await ctx.send(embed=embed, view=view)
    view.message = msg
    await view.wait()

    if view.value is None:
        embed.description += t(uid, "confirm.expired")
        return await msg.edit(embed=embed)
    if view.value is False:
        embed.title = t(uid, "ban.cancelled_title")
        embed.color = EMBED_COLOR
        return await msg.edit(embed=embed)

    await member.ban(reason=reason)
    embed.title = t(uid, "ban.success_title")
    embed.color = ERROR_COLOR
    embed.description = t(uid, "ban.success_description", member=member, reason=reason)
    _footer(embed, ctx.author)
    await msg.edit(embed=embed)
    await _log_moderation(ctx.guild, ctx.author, embed.title, embed.description, ERROR_COLOR)


@bot.command()
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, minutes: int, *, reason):
    """Timeout a member for a set duration in minutes"""
    uid = ctx.author.id
    if not reason.strip():
        return await ctx.send(t(uid, "error.missing_argument"))
    err = _kickban_error_key(ctx.author, member, ctx.guild, "timeout.self", "timeout.owner", "timeout.hierarchy", "timeout.bot_hierarchy")
    if err:
        return await ctx.send(t(uid, err))
    minutes = max(1, min(minutes, 40320))
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    embed = _base_embed(t(uid, "timeout.success_title"), WARN_COLOR)
    embed.description = t(uid, "timeout.success_description", member=member, minutes=minutes, reason=reason)
    _footer(embed, ctx.author)
    await ctx.send(embed=embed)
    await _log_moderation(ctx.guild, ctx.author, embed.title, embed.description, WARN_COLOR)


@bot.command()
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member):
    """Remove an active timeout from a member"""
    uid = ctx.author.id
    await member.timeout(None, reason=f"Timeout removed by {ctx.author}")
    embed = _base_embed(t(uid, "untimeout.success_title"), SUCCESS_COLOR)
    embed.description = t(uid, "untimeout.success_description", member=member)
    _footer(embed, ctx.author)
    await ctx.send(embed=embed)
    await _log_moderation(ctx.guild, ctx.author, embed.title, embed.description, SUCCESS_COLOR)


@bot.command()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def ticketsetup(ctx, channel: Optional[discord.TextChannel] = None):
    """Post the ticket creation panel (optionally in another channel)"""
    uid = ctx.author.id
    target = channel or ctx.channel
    try:
        summary = await _post_ticket_panel(ctx.author, ctx.guild, target)
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    await ctx.send(summary)


@bot.command(name="closetickets")
@is_bot_admin()
async def closetickets(ctx, *channels: discord.TextChannel):
    """Close several (or all) open ticket channels at once"""
    uid = ctx.author.id
    cfg = _ticket_cfg(ctx.guild.id)
    category = discord.utils.get(ctx.guild.categories, name=cfg["category_name"])
    targets = list(channels) if channels else (list(category.text_channels) if category else [])
    if not channels:
        targets = [c for c in targets if (ctx.guild.id, c.id) in open_tickets]
    if not targets:
        return await ctx.send(t(uid, "ticket.no_tickets"))
    await ctx.send(t(uid, "ticket.bulk_closing", count=len(targets)))
    await asyncio.gather(*(_close_ticket_channel(channel, closer=ctx.author) for channel in targets))


@bot.group(name="ticket", invoke_without_command=True)
@is_bot_admin()
async def ticket_group(ctx):
    """Ticket system status and configuration"""
    await ctx.send(embed=_ticket_config_embed(ctx.author.id, ctx.guild))


@ticket_group.command(name="reset")
@is_bot_admin()
async def ticket_group_reset(ctx):
    """Wipe this guild's entire ticket configuration back to defaults (category, staff roles, inactivity timers, categories list, mute settings)"""
    uid = ctx.author.id
    ticket_settings.pop(ctx.guild.id, None)
    await ctx.send(t(uid, "ticket.config_reset"))
    await ctx.send(embed=_ticket_config_embed(uid, ctx.guild))


@ticket_group.group(name="config", invoke_without_command=True)
@is_bot_admin()
async def ticket_config_group(ctx):
    await ctx.send(embed=_ticket_config_embed(ctx.author.id, ctx.guild))


@ticket_config_group.command(name="category")
@is_bot_admin()
async def ticket_config_category(ctx, *, name):
    uid = ctx.author.id
    name = name.strip()[:100]
    _ticket_cfg(ctx.guild.id)["category_name"] = name
    await ctx.send(t(uid, "ticket.category_set", name=name))


@ticket_config_group.command(name="logchannel")
@is_bot_admin()
async def ticket_config_logchannel(ctx, channel: Optional[discord.TextChannel] = None):
    uid = ctx.author.id
    _ticket_cfg(ctx.guild.id)["log_channel_id"] = channel.id if channel else None
    if channel:
        await ctx.send(t(uid, "ticket.logchannel_set", channel=channel.mention))
    else:
        await ctx.send(t(uid, "ticket.logchannel_cleared"))


@ticket_config_group.command(name="maxopen")
@is_bot_admin()
async def ticket_config_maxopen(ctx, count: int):
    uid = ctx.author.id
    count = max(1, min(count, 20))
    _ticket_cfg(ctx.guild.id)["max_open_per_user"] = count
    await ctx.send(t(uid, "ticket.maxopen_set", count=count))


@ticket_config_group.command(name="inactivity")
@is_bot_admin()
async def ticket_config_inactivity(ctx, warn_hours: float, close_hours: float):
    uid = ctx.author.id
    warn_hours = max(0.0, min(warn_hours, 720))
    close_hours = max(0.0, min(close_hours, 720))
    cfg = _ticket_cfg(ctx.guild.id)
    cfg["warn_hours"] = warn_hours
    cfg["close_hours"] = close_hours
    await ctx.send(t(uid, "ticket.inactivity_set", warn=warn_hours, close=close_hours))


@ticket_config_group.command(name="leaveaction")
@is_bot_admin()
async def ticket_config_leaveaction(ctx, action: str):
    uid = ctx.author.id
    action = action.lower().strip()
    if action not in ("notify", "close"):
        return await ctx.send(t(uid, "ticket.leaveaction_invalid"))
    _ticket_cfg(ctx.guild.id)["leave_action"] = action
    await ctx.send(t(uid, "ticket.leaveaction_set", action=action))


@ticket_config_group.command(name="mute")
@is_bot_admin()
async def ticket_config_mute(ctx, action: str, minutes: int = 10080):
    uid = ctx.author.id
    action = action.lower().strip()
    if action not in ("on", "off"):
        return await ctx.send(t(uid, "ticket.mute_invalid"))
    cfg = _ticket_cfg(ctx.guild.id)
    cfg["mute_on_close"] = action == "on"
    if action == "on":
        cfg["mute_minutes"] = max(1, min(minutes, 40320))
        await ctx.send(t(uid, "ticket.mute_set_on", duration=_format_duration(cfg["mute_minutes"] * 60)))
    else:
        await ctx.send(t(uid, "ticket.mute_set_off"))


@ticket_config_group.command(name="addtype")
@is_bot_admin()
async def ticket_config_addtype(ctx, *, name):
    uid = ctx.author.id
    name = name.strip()[:100]
    cfg = _ticket_cfg(ctx.guild.id)
    if name in cfg["categories"]:
        return await ctx.send(t(uid, "ticket.type_exists", name=name))
    if len(cfg["categories"]) >= 25:
        return await ctx.send(t(uid, "ticket.types_full"))
    cfg["categories"].append(name)
    await ctx.send(t(uid, "ticket.type_added", name=name))


@ticket_config_group.command(name="removetype")
@is_bot_admin()
async def ticket_config_removetype(ctx, *, name):
    uid = ctx.author.id
    name = name.strip()
    cfg = _ticket_cfg(ctx.guild.id)
    if name not in cfg["categories"]:
        return await ctx.send(t(uid, "ticket.type_not_found", name=name))
    if len(cfg["categories"]) <= 1:
        return await ctx.send(t(uid, "ticket.type_last_one"))
    cfg["categories"].remove(name)
    await ctx.send(t(uid, "ticket.type_removed", name=name))


@ticket_config_group.command(name="addstaffrole")
@is_bot_admin()
async def ticket_config_addstaffrole(ctx, role: discord.Role):
    uid = ctx.author.id
    _ticket_cfg(ctx.guild.id)["staff_role_ids"].add(role.id)
    await ctx.send(t(uid, "ticket.staffrole_added", role=role.mention))


@ticket_config_group.command(name="removestaffrole")
@is_bot_admin()
async def ticket_config_removestaffrole(ctx, role: discord.Role):
    uid = ctx.author.id
    _ticket_cfg(ctx.guild.id)["staff_role_ids"].discard(role.id)
    await ctx.send(t(uid, "ticket.staffrole_removed", role=role.mention))


@ticket_config_group.command(name="resetstaffroles")
@is_bot_admin()
async def ticket_config_resetstaffroles(ctx, *roles: discord.Role):
    """Clear every currently-configured ticket staff role and replace them with the given role(s) in one go"""
    uid = ctx.author.id
    cfg = _ticket_cfg(ctx.guild.id)
    cfg["staff_role_ids"] = {role.id for role in roles}
    roles_value = ", ".join(role.mention for role in roles) or t(uid, "ticket.not_set")
    await ctx.send(t(uid, "ticket.staffroles_reset", roles=roles_value))


@ticket_group.command(name="claim")
@commands.guild_only()
async def ticket_claim_cmd(ctx):
    """Take this ticket in charge (the payment info of whoever claims it is the one shown)"""
    await ctx.send(await _tk_claim(ctx.author, ctx.channel))


@ticket_group.command(name="unclaim", aliases=["release"])
@commands.guild_only()
async def ticket_unclaim_cmd(ctx):
    """Release this ticket so another staff member can take it"""
    await ctx.send(await _tk_claim(ctx.author, ctx.channel, release=True))


@ticket_group.command(name="add")
@commands.guild_only()
async def ticket_add_cmd(ctx, member: discord.Member):
    """Let another member see and write in this ticket"""
    await ctx.send(await _tk_add(ctx.author, ctx.channel, member))


@ticket_group.command(name="remove")
@commands.guild_only()
async def ticket_remove_cmd(ctx, member: discord.Member):
    """Take a member you added back out of this ticket"""
    await ctx.send(await _tk_remove(ctx.author, ctx.channel, member))


@ticket_group.command(name="rename")
@commands.guild_only()
async def ticket_rename_cmd(ctx, *, name: str):
    """Rename this ticket's channel"""
    await ctx.send(await _tk_rename(ctx.author, ctx.channel, name))


@ticket_group.command(name="transcript")
@commands.guild_only()
async def ticket_transcript_cmd(ctx):
    """Get a text copy of this ticket's conversation"""
    text, file = await _tk_transcript(ctx.author, ctx.channel)
    await ctx.send(text, file=file) if file else await ctx.send(text)


@ticket_group.command(name="list")
@commands.guild_only()
async def ticket_list_cmd(ctx):
    """List the open tickets of this server"""
    if not _is_ticket_staff(ctx.author):
        return await ctx.send(t(ctx.author.id, "ticket.staff_only"))
    await ctx.send(embed=_tk_list_embed(ctx.author.id, ctx.guild))


@ticket_group.command(name="close")
@commands.guild_only()
async def ticket_close_cmd(ctx, *, reason: str = ""):
    """Close this ticket (optionally with a reason) -- a transcript is sent to the log channel and to the opener"""
    error = await _tk_close(ctx.author, ctx.channel, reason.strip())
    if error:
        await ctx.send(error)


@bot.command(name="payinfo", aliases=["paymentinfo"])
@commands.guild_only()
async def payinfo_cmd(ctx, *, args: str = ""):
    """Payment info, everywhere the same: `!payinfo` shows it, `!payinfo paypal you@mail.com ltc L...` sets yours
    (add `server` or `everywhere` first to set the server's / the whole bot's default; `-` removes a field)"""
    words = args.split()
    scope = words.pop(0).lower() if words and words[0].lower() in ("me", "server", "everywhere") else "me"
    values = {field.lower(): value for field, value in YSLEMM_PAYMENT_FIELD_RE.findall(" ".join(words))}
    text, embed, public = await _payinfo_run(ctx.author, ctx.guild, ctx.channel, values, scope)
    await ctx.send(content=text, embed=embed)


@bot.command()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def staffapplysetup(ctx, channel: Optional[discord.TextChannel] = None):
    """Post the staff-application panel (optionally in another channel)"""
    uid = ctx.author.id
    target = channel or ctx.channel
    embed = _base_embed(t(uid, "staffapp.panel_title"), EMBED_COLOR)
    embed.description = t(uid, "staffapp.panel_description")
    view = StaffApplyPanelView()
    view.children[0].label = t(uid, "staffapp.apply_button")
    try:
        await target.send(embed=embed, view=view)
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    if target != ctx.channel:
        await ctx.send(t(uid, "staffapp.panel_posted_in", channel=target.mention))


@bot.command(name="closeapplications")
@is_bot_admin()
async def closeapplications(ctx, *channels: discord.TextChannel):
    """Close several (or all) open staff-application channels at once"""
    uid = ctx.author.id
    cfg = _staffapp_cfg(ctx.guild.id)
    category = discord.utils.get(ctx.guild.categories, name=cfg["category_name"])
    targets = list(channels) if channels else (list(category.text_channels) if category else [])
    if category is not None:
        targets = [c for c in targets if c.category_id == category.id]
    if not targets:
        return await ctx.send(t(uid, "staffapp.no_applications"))
    await ctx.send(t(uid, "staffapp.bulk_closing", count=len(targets)))
    await asyncio.gather(*(_close_staff_application_channel(channel, closer=ctx.author) for channel in targets))


@bot.group(name="staffapp", invoke_without_command=True)
@is_bot_admin()
async def staffapp_group(ctx):
    """Staff-application system status and configuration"""
    await ctx.send(embed=_staffapp_config_embed(ctx.author.id, ctx.guild))


@staffapp_group.command(name="reset")
@is_bot_admin()
async def staffapp_group_reset(ctx):
    """Wipe this guild's staff-application configuration back to defaults (category, recruiter roles, cooldown, granted role)"""
    uid = ctx.author.id
    staffapp_settings.pop(ctx.guild.id, None)
    await ctx.send(t(uid, "staffapp.config_reset"))
    await ctx.send(embed=_staffapp_config_embed(uid, ctx.guild))


@staffapp_group.group(name="config", invoke_without_command=True)
@is_bot_admin()
async def staffapp_config_group(ctx):
    await ctx.send(embed=_staffapp_config_embed(ctx.author.id, ctx.guild))


@staffapp_config_group.command(name="category")
@is_bot_admin()
async def staffapp_config_category(ctx, *, name):
    uid = ctx.author.id
    name = name.strip()[:100]
    _staffapp_cfg(ctx.guild.id)["category_name"] = name
    await ctx.send(t(uid, "staffapp.category_set", name=name))


@staffapp_config_group.command(name="logchannel")
@is_bot_admin()
async def staffapp_config_logchannel(ctx, channel: Optional[discord.TextChannel] = None):
    uid = ctx.author.id
    _staffapp_cfg(ctx.guild.id)["log_channel_id"] = channel.id if channel else None
    if channel:
        await ctx.send(t(uid, "staffapp.logchannel_set", channel=channel.mention))
    else:
        await ctx.send(t(uid, "staffapp.logchannel_cleared"))


@staffapp_config_group.command(name="addrecruiter")
@is_bot_admin()
async def staffapp_config_addrecruiter(ctx, role: discord.Role):
    uid = ctx.author.id
    _staffapp_cfg(ctx.guild.id)["recruiter_role_ids"].add(role.id)
    await ctx.send(t(uid, "staffapp.recruiter_added", role=role.mention))


@staffapp_config_group.command(name="removerecruiter")
@is_bot_admin()
async def staffapp_config_removerecruiter(ctx, role: discord.Role):
    uid = ctx.author.id
    _staffapp_cfg(ctx.guild.id)["recruiter_role_ids"].discard(role.id)
    await ctx.send(t(uid, "staffapp.recruiter_removed", role=role.mention))


@staffapp_config_group.command(name="resetrecruiters")
@is_bot_admin()
async def staffapp_config_resetrecruiters(ctx, *roles: discord.Role):
    """Clear every currently-configured recruiter role and replace them with the given role(s) in one go"""
    uid = ctx.author.id
    cfg = _staffapp_cfg(ctx.guild.id)
    cfg["recruiter_role_ids"] = {role.id for role in roles}
    roles_value = ", ".join(role.mention for role in roles) or t(uid, "ticket.not_set")
    await ctx.send(t(uid, "staffapp.recruiters_reset", roles=roles_value))


@staffapp_config_group.command(name="cooldown")
@is_bot_admin()
async def staffapp_config_cooldown(ctx, days: float):
    """Days a rejected applicant must wait before reapplying (0 = no cooldown)"""
    uid = ctx.author.id
    days = max(0.0, min(days, 365))
    _staffapp_cfg(ctx.guild.id)["cooldown_days"] = days
    await ctx.send(t(uid, "staffapp.cooldown_set", days=f"{days:g}"))


@staffapp_config_group.command(name="role")
@is_bot_admin()
async def staffapp_config_role(ctx, role: Optional[discord.Role] = None):
    """Role to grant automatically when an application is accepted (omit to clear)"""
    uid = ctx.author.id
    _staffapp_cfg(ctx.guild.id)["granted_role_id"] = role.id if role else None
    if role:
        await ctx.send(t(uid, "staffapp.role_set", role=role.mention))
    else:
        await ctx.send(t(uid, "staffapp.role_cleared"))


@staffapp_config_group.command(name="private")
@is_bot_admin()
async def staffapp_config_private(ctx, enabled: bool):
    """Applications visible only to the applicant and the bot owner (on) or also to recruiters/managers (off)"""
    _staffapp_cfg(ctx.guild.id)["owner_only"] = enabled
    await ctx.send(t(ctx.author.id, "staffapp.private_set_on" if enabled else "staffapp.private_set_off"))


@bot.group(name="yslemmfaq", invoke_without_command=True)
@is_bot_admin()
async def yslemmfaq_group(ctx):
    """Manage yslemm's canned Q&A answers"""
    await ctx.send(embed=_yslemm_faq_embed(ctx.author.id, ctx.guild.id))


@yslemmfaq_group.command(name="add")
@is_bot_admin()
async def yslemmfaq_add(ctx, *, text):
    uid = ctx.author.id
    if "|" not in text:
        return await ctx.send(t(uid, "yslemm.faq_usage"))
    question, answer = text.split("|", 1)
    question, answer = question.strip(), answer.strip()
    if not question or not answer:
        return await ctx.send(t(uid, "yslemm.faq_usage"))
    key = _yslemm_faq_normalize(question)
    yslemm_faq.setdefault(ctx.guild.id, {})[key] = {"question": question, "answer": answer}
    await ctx.send(t(uid, "yslemm.faq_added", question=question))


@yslemmfaq_group.command(name="remove")
@is_bot_admin()
async def yslemmfaq_remove(ctx, *, question):
    uid = ctx.author.id
    key = _yslemm_faq_normalize(question)
    faq = yslemm_faq.get(ctx.guild.id, {})
    if key not in faq:
        return await ctx.send(t(uid, "yslemm.faq_not_found", question=question))
    del faq[key]
    await ctx.send(t(uid, "yslemm.faq_removed", question=question))


@yslemmfaq_group.command(name="list")
@is_bot_admin()
async def yslemmfaq_list(ctx):
    await ctx.send(embed=_yslemm_faq_embed(ctx.author.id, ctx.guild.id))


@bot.command(name="taistoi", aliases=["shutup", "chut", "silence"])
@is_bot_admin()
async def yslemm_shutup(ctx):
    """Fait taire yslemm dans ce salon immédiatement, sans passer par l'IA."""
    key = (ctx.guild.id, ctx.channel.id)
    yslemm_silenced_channels.add(key)
    await ctx.send(t(ctx.author.id, "yslemm.silenced"))


@bot.command(name="parle", aliases=["speak", "unshutup"])
@is_bot_admin()
async def yslemm_speak(ctx):
    """Refait parler yslemm dans ce salon immédiatement, sans passer par l'IA."""
    key = (ctx.guild.id, ctx.channel.id)
    yslemm_silenced_channels.discard(key)
    await ctx.send(t(ctx.author.id, "yslemm.unsilenced"))


@bot.group(name="setpayment", invoke_without_command=True)
@is_bot_admin()
async def setpayment(ctx):
    """Configure the PayPal/LTC/BTC/Roblox payment info shown on the ticket panel"""
    uid = ctx.author.id
    info = payment_info.get(ctx.guild.id, {})
    embed = _base_embed(t(uid, "payment.status_title"), EMBED_COLOR)
    embed.add_field(name="PayPal", value=info.get("paypal") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="LTC", value=info.get("ltc") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="BTC", value=info.get("btc") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="Roblox", value=info.get("roblox") or t(uid, "payment.not_set"), inline=False)
    await ctx.send(embed=embed)


@setpayment.command(name="paypal")
@is_bot_admin()
async def setpayment_paypal(ctx, *, value):
    uid = ctx.author.id
    payment_info.setdefault(ctx.guild.id, {})["paypal"] = value
    await ctx.send(t(uid, "payment.paypal_set"))


@setpayment.command(name="ltc")
@is_bot_admin()
async def setpayment_ltc(ctx, *, value):
    uid = ctx.author.id
    payment_info.setdefault(ctx.guild.id, {})["ltc"] = value
    await ctx.send(t(uid, "payment.ltc_set"))


@setpayment.command(name="btc")
@is_bot_admin()
async def setpayment_btc(ctx, *, value):
    uid = ctx.author.id
    payment_info.setdefault(ctx.guild.id, {})["btc"] = value
    await ctx.send(t(uid, "payment.btc_set"))


@setpayment.command(name="roblox")
@is_bot_admin()
async def setpayment_roblox(ctx, *, value):
    uid = ctx.author.id
    payment_info.setdefault(ctx.guild.id, {})["roblox"] = value
    await ctx.send(t(uid, "payment.roblox_set"))


def _staff_payment_embed(uid, target):
    info = staff_payment_info.get(target.id, {})
    embed = _base_embed(t(uid, "payment.status_title"), EMBED_COLOR)
    embed.add_field(name="PayPal", value=info.get("paypal") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="LTC", value=info.get("ltc") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="BTC", value=info.get("btc") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="Roblox", value=info.get("roblox") or t(uid, "payment.not_set"), inline=False)
    return _footer(embed, target)


class PaymentFieldSetModal(discord.ui.Modal):
    def __init__(self, target_id, field, manage_view):
        super().__init__(title=field.upper())
        self.target_id = target_id
        self.field = field
        self.manage_view = manage_view
        self.value_input = discord.ui.TextInput(label=field.upper(), max_length=200, required=True)
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        staff_payment_info.setdefault(self.target_id, {})[self.field] = self.value_input.value.strip()
        await interaction.response.send_message(
            t(interaction.user.id, "payment.field_set", field=self.field.upper()), ephemeral=True
        )
        await self.manage_view.refresh()


class PaymentSetSelect(discord.ui.Select):
    def __init__(self, uid, target_id):
        options = [discord.SelectOption(label=f.upper(), value=f) for f in ("paypal", "ltc", "btc", "roblox")]
        super().__init__(placeholder=t(uid, "payment.select_set_placeholder"), options=options, custom_id="payment_set_select")
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PaymentFieldSetModal(self.target_id, self.values[0], self.view))


class PaymentClearSelect(discord.ui.Select):
    def __init__(self, uid, target_id, configured_fields):
        options = [discord.SelectOption(label=f.upper(), value=f) for f in configured_fields]
        super().__init__(
            placeholder=t(uid, "payment.select_clear_placeholder"),
            options=options,
            max_values=len(options),
            custom_id="payment_clear_select",
        )
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction):
        fields = self.values
        uid = interaction.user.id
        label = ", ".join(f.upper() for f in fields)
        embed = _base_embed(t(uid, "payment.clear_confirm_title"), WARN_COLOR)
        embed.description = t(uid, "payment.clear_confirm_description", field=label)
        confirm_view = ConfirmView(interaction.user)
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
        msg = await interaction.original_response()
        confirm_view.message = msg
        await confirm_view.wait()
        if confirm_view.value:
            info = staff_payment_info.setdefault(self.target_id, {})
            for f in fields:
                info[f] = ""
            embed.title = t(uid, "payment.clear_success_title")
            embed.color = SUCCESS_COLOR
            embed.description = t(uid, "payment.clear_success_description", field=label)
            await msg.edit(embed=embed, view=None)
            await self.view.refresh()
        elif confirm_view.value is False:
            embed.title = t(uid, "payment.clear_cancelled_title")
            embed.color = EMBED_COLOR
            await msg.edit(embed=embed, view=None)
        else:
            embed.description += t(uid, "confirm.expired")
            await msg.edit(embed=embed, view=None)


class PaymentManageView(OwnerOnlyView):
    """One unified interactive panel for a staff member's own payment info
    -- a select to set any field (opens a modal for the value) and, only
    when there's something to remove, a second select listing just the
    fields currently set, so it's never possible to "clear" an already-
    empty field. Whichever member the command targeted (by mention/ID,
    defaulting to the caller) is who this manages -- that's whose info
    shows to a customer once they claim a ticket."""

    def __init__(self, author, target):
        super().__init__(author, timeout=180)
        self.target = target
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        uid = self.author.id
        self.add_item(PaymentSetSelect(uid, self.target.id))
        info = staff_payment_info.get(self.target.id, {})
        configured = [f for f in ("paypal", "ltc", "btc", "roblox") if info.get(f)]
        if configured:
            self.add_item(PaymentClearSelect(uid, self.target.id, configured))

    async def refresh(self):
        self._rebuild()
        if self.message is not None:
            try:
                await self.message.edit(embed=_staff_payment_embed(self.author.id, self.target), view=self)
            except discord.HTTPException:
                pass


@bot.command(name="payment")
@is_bot_admin()
async def payment_cmd(ctx, member: discord.Member = None):
    """Manage a staff member's own PayPal/LTC/BTC/Roblox info (set or remove fields interactively) -- defaults to yourself"""
    target = member or ctx.author
    view = PaymentManageView(ctx.author, target)
    msg = await ctx.send(embed=_staff_payment_embed(ctx.author.id, target), view=view)
    view.message = msg


@bot.group(name="mypayment", invoke_without_command=True)
@is_bot_admin()
async def mypayment(ctx):
    """Set your own PayPal/LTC/BTC/Roblox info -- shown instead of the
    server default to a customer in a ticket you've claimed"""
    uid = ctx.author.id
    info = staff_payment_info.get(uid, {})
    embed = _base_embed(t(uid, "payment.status_title"), EMBED_COLOR)
    embed.add_field(name="PayPal", value=info.get("paypal") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="LTC", value=info.get("ltc") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="BTC", value=info.get("btc") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="Roblox", value=info.get("roblox") or t(uid, "payment.not_set"), inline=False)
    await ctx.send(embed=embed)


@mypayment.command(name="paypal")
@is_bot_admin()
async def mypayment_paypal(ctx, *, value):
    uid = ctx.author.id
    staff_payment_info.setdefault(uid, {})["paypal"] = value
    await ctx.send(t(uid, "payment.paypal_set"))


@mypayment.command(name="ltc")
@is_bot_admin()
async def mypayment_ltc(ctx, *, value):
    uid = ctx.author.id
    staff_payment_info.setdefault(uid, {})["ltc"] = value
    await ctx.send(t(uid, "payment.ltc_set"))


@mypayment.command(name="btc")
@is_bot_admin()
async def mypayment_btc(ctx, *, value):
    uid = ctx.author.id
    staff_payment_info.setdefault(uid, {})["btc"] = value
    await ctx.send(t(uid, "payment.btc_set"))


@mypayment.command(name="roblox")
@is_bot_admin()
async def mypayment_roblox(ctx, *, value):
    uid = ctx.author.id
    staff_payment_info.setdefault(uid, {})["roblox"] = value
    await ctx.send(t(uid, "payment.roblox_set"))


@mypayment.command(name="clear")
@is_bot_admin()
async def mypayment_clear(ctx, field: str = "all"):
    """Remove one (or all) of your own payment fields -- asks to confirm first"""
    uid = ctx.author.id
    field = field.lower().strip()
    if field not in ("paypal", "ltc", "btc", "roblox", "all"):
        return await ctx.send(t(uid, "payment.clear_invalid_field"))
    if not any((staff_payment_info.get(uid) or {}).values()):
        return await ctx.send(t(uid, "payment.not_configured"))

    embed = _base_embed(t(uid, "payment.clear_confirm_title"), WARN_COLOR)
    embed.description = t(uid, "payment.clear_confirm_description", field=field)
    view = ConfirmView(ctx.author)
    msg = await ctx.send(embed=embed, view=view)
    view.message = msg
    await view.wait()

    if view.value is None:
        embed.description += t(uid, "confirm.expired")
        return await msg.edit(embed=embed)
    if view.value is False:
        embed.title = t(uid, "payment.clear_cancelled_title")
        embed.color = EMBED_COLOR
        return await msg.edit(embed=embed)

    if field == "all":
        staff_payment_info[uid] = {}
    else:
        staff_payment_info.setdefault(uid, {})[field] = ""
    embed.title = t(uid, "payment.clear_success_title")
    embed.color = SUCCESS_COLOR
    embed.description = t(uid, "payment.clear_success_description", field=field)
    await msg.edit(embed=embed)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason):
    """Warn a member"""
    uid = ctx.author.id
    if not reason.strip():
        return await ctx.send(t(uid, "error.missing_argument"))
    key = (ctx.guild.id, member.id)
    warnings_store.setdefault(key, []).append(reason)
    embed = _base_embed(t(uid, "warn.title"), WARN_COLOR)
    embed.description = t(uid, "warn.added", member=member, reason=reason, count=len(warnings_store[key]))
    _footer(embed, ctx.author)
    await ctx.send(embed=embed)
    await _log_moderation(ctx.guild, ctx.author, embed.title, embed.description, WARN_COLOR)
    await _check_warn_autoban(ctx.guild, member, key)


@bot.command(name="warnings")
@commands.guild_only()
async def list_warnings(ctx, member: discord.Member = None):
    """List a member's warnings"""
    uid = ctx.author.id
    member = member or ctx.author
    reasons = warnings_store.get((ctx.guild.id, member.id), [])
    embed = _base_embed(t(uid, "warn.list_title", member=member.display_name), WARN_COLOR if reasons else EMBED_COLOR)
    embed.description = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(reasons)) if reasons else t(uid, "warn.list_empty")
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def clearwarnings(ctx, member: discord.Member):
    """Clear a member's warnings"""
    uid = ctx.author.id
    warnings_store.pop((ctx.guild.id, member.id), None)
    await ctx.send(t(uid, "warn.cleared", member=member))
    await _log_moderation(ctx.guild, ctx.author, t(0, "warn.cleared_title"), t(0, "warn.cleared", member=str(member)), EMBED_COLOR)


@bot.command()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_roles=True)
async def lock(ctx):
    """Lock the current channel"""
    uid = ctx.author.id
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send(embed=_base_embed(t(uid, "lock.locked"), WARN_COLOR))


@bot.command()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_roles=True)
async def unlock(ctx):
    """Unlock the current channel"""
    uid = ctx.author.id
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = None
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send(embed=_base_embed(t(uid, "lock.unlocked"), SUCCESS_COLOR))


@bot.command()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int = 0):
    """Set channel slowmode"""
    uid = ctx.author.id
    seconds = max(0, min(seconds, 21600))
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(t(uid, "slowmode.off") if seconds == 0 else t(uid, "slowmode.set", seconds=seconds))


@bot.command()
@is_bot_admin()
@commands.bot_has_permissions(manage_roles=True)
async def createrole(ctx, *, name):
    """Create a new role"""
    uid = ctx.author.id
    try:
        role = await ctx.guild.create_role(name=name, reason=f"Created by {ctx.author} via bot")
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    await ctx.send(t(uid, "role.created", role=role.mention))


@bot.command()
@is_bot_admin()
@commands.bot_has_permissions(manage_channels=True)
async def createchannel(ctx, category: Optional[discord.CategoryChannel] = None, *, name):
    """Create a new text channel (optionally inside a category)"""
    uid = ctx.author.id
    try:
        channel = await ctx.guild.create_text_channel(name=name, category=category, reason=f"Created by {ctx.author} via bot")
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    await ctx.send(t(uid, "channel.created", channel=channel.mention))


# --- Loose name resolution -------------------------------------------------
# People (and yslemm) refer to roles, channels and members the way they say
# them, not the way Discord stores them: "vip" for "💎 VIP", "general" for
# "・général", "kylian" for "Kylian_🔥". These accept a mention, an ID, or a
# loose name -- exact first, then ignoring case/accents/emoji/punctuation,
# then prefix, then substring -- and report ambiguity instead of guessing.

def _fr_en(uid, fr, en):
    return fr if lang_of(uid) == "fr" else en


def _loose(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _soft(text):
    """Case/accents/emoji/decoration ignored, but meaningful signs kept --
    so "vip" is "💎 VIP" and not also "VIP+"."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = re.sub(r"[^\w+\-. ]+", " ", text)
    return re.sub(r"[\s._\-]+", " ", text).strip()


def _loose_pick(items, query, names):
    """(match, candidates): one clear match, or None plus the ambiguous
    candidates (empty when nothing matched at all)."""
    query = (query or "").strip()
    if not query:
        return None, []
    q, sq = _loose(query), _soft(query)
    tiers = (
        lambda n: n == query,
        lambda n: n.casefold() == query.casefold(),
        lambda n: bool(sq) and _soft(n) == sq,
        lambda n: bool(q) and _loose(n) == q,
        lambda n: bool(q) and _loose(n).startswith(q),
        lambda n: bool(q) and q in _loose(n),
    )
    for test in tiers:
        hits = [i for i in items if any(test(n) for n in names(i) if n)]
        if len(hits) == 1:
            return hits[0], hits
        if hits:
            return None, hits
    return None, []


def _resolve_role(guild, text):
    text = (text or "").strip()
    m = re.fullmatch(r"<@&(\d+)>|(\d{15,20})", text)
    if m:
        role = guild.get_role(int(m.group(1) or m.group(2)))
        return role, [role] if role else []
    roles = [r for r in guild.roles if not r.is_default()]
    return _loose_pick(roles, text.lstrip("@"), lambda r: [r.name])


def _resolve_channel(guild, text):
    text = (text or "").strip()
    m = re.fullmatch(r"<#(\d+)>|(\d{15,20})", text)
    if m:
        channel = guild.get_channel(int(m.group(1) or m.group(2)))
        return channel, [channel] if channel else []
    return _loose_pick(list(guild.channels), text.lstrip("#"), lambda c: [c.name])


def _resolve_member(guild, text):
    text = (text or "").strip()
    m = re.fullmatch(r"<@!?(\d+)>|(\d{15,20})", text)
    if m:
        member = guild.get_member(int(m.group(1) or m.group(2)))
        return member, [member] if member else []
    return _loose_pick(
        list(guild.members), text.lstrip("@"),
        lambda mb: [mb.display_name, mb.name, getattr(mb, "global_name", None)],
    )


async def _resolve_or_explain(ctx, kind, text, resolver):
    """Resolves, or tells the person precisely what went wrong (nothing
    found / which ones it could be) and returns None."""
    uid = ctx.author.id
    found, candidates = resolver(ctx.guild, text)
    if found is not None:
        return found
    label = {"role": ("rôle", "role"), "channel": ("salon", "channel"), "member": ("membre", "member")}[kind]
    if candidates:
        names = ", ".join(f"**{getattr(c, 'display_name', None) or c.name}**" for c in candidates[:6])
        await ctx.send(_fr_en(uid, f"❓ Plusieurs {label[0]}s correspondent à « {text} » : {names}. Lequel ?",
                              f"❓ Several {label[1]}s match \"{text}\": {names}. Which one?"))
    else:
        await ctx.send(_fr_en(uid, f"❌ Aucun {label[0]} ne correspond à « {text} ».",
                              f"❌ No {label[1]} matches \"{text}\"."))
    return None


def _role_manage_error(ctx, role):
    uid = ctx.author.id
    if role.is_default() or role.managed:
        return _fr_en(uid, f"❌ Le rôle **{role.name}** est géré par Discord ou une intégration, impossible d'y toucher.",
                      f"❌ **{role.name}** is managed by Discord or an integration and can't be changed.")
    if ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
        return _fr_en(uid, f"❌ **{role.name}** est au-dessus (ou au niveau) de ton rôle le plus haut.",
                      f"❌ **{role.name}** is at or above your highest role.")
    if role >= ctx.guild.me.top_role:
        return _fr_en(uid, f"❌ **{role.name}** est au-dessus de mon rôle : monte mon rôle dans les paramètres du serveur.",
                      f"❌ **{role.name}** is above my role -- move my role higher in the server settings.")
    return None


async def _confirm(ctx, title, description):
    embed = _base_embed(title, WARN_COLOR)
    embed.description = description
    view = ConfirmView(ctx.author)
    msg = await ctx.send(embed=embed, view=view)
    view.message = msg
    await view.wait()
    if view.value is not True:
        embed.description += t(ctx.author.id, "confirm.expired") if view.value is None else ""
        if view.value is False:
            embed.title = _fr_en(ctx.author.id, "✖️ Annulé", "✖️ Cancelled")
            embed.color = EMBED_COLOR
        await msg.edit(embed=embed)
        return None
    return msg


@bot.command(aliases=["delchannel", "supprimesalon"])
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def deletechannel(ctx, *, channel: str = ""):
    """Delete a channel (the current one if none is given) -- confirmation required"""
    uid = ctx.author.id
    target = ctx.channel if not channel.strip() else await _resolve_or_explain(ctx, "channel", channel, _resolve_channel)
    if target is None:
        return
    name = target.name
    msg = await _confirm(ctx, _fr_en(uid, "🗑️ Supprimer le salon ?", "🗑️ Delete the channel?"),
                         _fr_en(uid, f"Le salon **#{name}** et tout son contenu seront supprimés définitivement.",
                                f"**#{name}** and everything in it will be permanently deleted."))
    if msg is None:
        return
    try:
        await target.delete(reason=f"Deleted by {ctx.author} via bot")
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    if target.id != ctx.channel.id:
        await msg.edit(embed=_base_embed(_fr_en(uid, f"✅ Salon #{name} supprimé", f"✅ Channel #{name} deleted"), SUCCESS_COLOR), view=None)
    await _log_moderation(ctx.guild, ctx.author, "🗑️ Channel deleted", f"#{name}", ERROR_COLOR)


@bot.command(aliases=["rename"])
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def renamechannel(ctx, *, text: str):
    """Rename a channel: renamechannel [#channel] <new name> (current channel by default)"""
    uid = ctx.author.id
    first, _, rest = text.strip().partition(" ")
    target = ctx.channel
    if rest and (first.startswith(("<#", "#")) or first.isdigit()):
        target = await _resolve_or_explain(ctx, "channel", first, _resolve_channel)
        if target is None:
            return
        text = rest
    new_name = text.strip()[:100]
    if not new_name:
        return await ctx.send(t(uid, "error.missing_argument"))
    old = target.name
    try:
        await target.edit(name=new_name, reason=f"Renamed by {ctx.author} via bot")
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    await ctx.send(_fr_en(uid, f"✅ **#{old}** renommé en {target.mention}.", f"✅ **#{old}** renamed to {target.mention}."))


async def _change_member_role(ctx, member, role_text, adding):
    uid = ctx.author.id
    member = await _resolve_or_explain(ctx, "member", member, _resolve_member)
    if member is None:
        return
    role = await _resolve_or_explain(ctx, "role", role_text, _resolve_role)
    if role is None:
        return
    err = _role_manage_error(ctx, role)
    if err:
        return await ctx.send(err)
    if adding == (role in member.roles):
        return await ctx.send(_fr_en(
            uid,
            f"ℹ️ {member.mention} {'a déjà' if adding else 'n’a pas'} le rôle **{role.name}**.",
            f"ℹ️ {member.mention} {'already has' if adding else 'doesn’t have'} **{role.name}**.",
        ))
    try:
        if adding:
            await member.add_roles(role, reason=f"By {ctx.author} via bot")
        else:
            await member.remove_roles(role, reason=f"By {ctx.author} via bot")
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    await ctx.send(_fr_en(
        uid,
        f"✅ Rôle **{role.name}** {'donné à' if adding else 'retiré à'} {member.mention}.",
        f"✅ **{role.name}** {'given to' if adding else 'removed from'} {member.mention}.",
    ))
    await _log_moderation(ctx.guild, ctx.author, "🎭 Role " + ("added" if adding else "removed"),
                          f"{member} -- {role.name}", EMBED_COLOR)


@bot.command(aliases=["giverole", "donnerole"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def addrole(ctx, member: str, *, role: str):
    """Give a role to a member: addrole <member> <role>"""
    await _change_member_role(ctx, member, role, adding=True)


@bot.command(aliases=["takerole", "retirerole"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def removerole(ctx, member: str, *, role: str):
    """Take a role away from a member: removerole <member> <role>"""
    await _change_member_role(ctx, member, role, adding=False)


@bot.command(aliases=["delrole"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def deleterole(ctx, *, role: str):
    """Delete a role from the server -- confirmation required"""
    uid = ctx.author.id
    found = await _resolve_or_explain(ctx, "role", role, _resolve_role)
    if found is None:
        return
    err = _role_manage_error(ctx, found)
    if err:
        return await ctx.send(err)
    name = found.name
    msg = await _confirm(ctx, _fr_en(uid, "🗑️ Supprimer le rôle ?", "🗑️ Delete the role?"),
                         _fr_en(uid, f"Le rôle **{name}** sera supprimé du serveur ({len(found.members)} membre(s) l'ont).",
                                f"**{name}** will be deleted from the server ({len(found.members)} member(s) have it)."))
    if msg is None:
        return
    try:
        await found.delete(reason=f"Deleted by {ctx.author} via bot")
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    await msg.edit(embed=_base_embed(_fr_en(uid, f"✅ Rôle {name} supprimé", f"✅ Role {name} deleted"), SUCCESS_COLOR), view=None)
    await _log_moderation(ctx.guild, ctx.author, "🗑️ Role deleted", name, ERROR_COLOR)


@bot.command(aliases=["nickname", "pseudo"])
@commands.guild_only()
@commands.has_permissions(manage_nicknames=True)
@commands.bot_has_permissions(manage_nicknames=True)
async def nick(ctx, member: str, *, nickname: str = ""):
    """Change (or reset, if left empty) a member's nickname"""
    uid = ctx.author.id
    found = await _resolve_or_explain(ctx, "member", member, _resolve_member)
    if found is None:
        return
    if found != ctx.author:
        err = _kickban_error_key(ctx.author, found, ctx.guild, "kick.self", "kick.owner", "kick.hierarchy", "kick.bot_hierarchy")
        if err:
            return await ctx.send(t(uid, err))
    nickname = nickname.strip()[:32] or None
    try:
        await found.edit(nick=nickname, reason=f"By {ctx.author} via bot")
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    await ctx.send(_fr_en(
        uid,
        f"✅ Pseudo de {found.mention} {'changé en **' + nickname + '**' if nickname else 'réinitialisé'}.",
        f"✅ {found.mention}'s nickname {'set to **' + nickname + '**' if nickname else 'reset'}.",
    ))


@bot.command(aliases=["deban", "debannir"])
@commands.guild_only()
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def unban(ctx, *, user: str):
    """Unban someone by ID or by (part of) their name"""
    uid = ctx.author.id
    bans = [entry async for entry in ctx.guild.bans(limit=1000)]
    text = user.strip()
    m = re.fullmatch(r"<@!?(\d+)>|(\d{15,20})", text)
    if m:
        wanted = int(m.group(1) or m.group(2))
        matches = [b for b in bans if b.user.id == wanted]
        entry = matches[0] if matches else None
    else:
        entry, matches = _loose_pick(bans, text.lstrip("@"), lambda b: [b.user.name, getattr(b.user, "global_name", None)])
    if entry is None:
        if matches:
            names = ", ".join(f"**{b.user.name}**" for b in matches[:6])
            return await ctx.send(_fr_en(uid, f"❓ Plusieurs bannis correspondent : {names}. Lequel ?",
                                         f"❓ Several banned users match: {names}. Which one?"))
        return await ctx.send(_fr_en(uid, f"❌ Personne de banni ne correspond à « {text} ».",
                                     f"❌ No banned user matches \"{text}\"."))
    try:
        await ctx.guild.unban(entry.user, reason=f"Unbanned by {ctx.author} via bot")
    except discord.Forbidden:
        return await ctx.send(t(uid, "error.bot_no_permission"))
    await ctx.send(_fr_en(uid, f"✅ **{entry.user}** a été débanni.", f"✅ **{entry.user}** has been unbanned."))
    await _log_moderation(ctx.guild, ctx.author, "🔓 Unban", str(entry.user), SUCCESS_COLOR)


@bot.command(aliases=["sauvegarde"])
@is_bot_admin()
async def backup(ctx):
    """Save all bot data now (private backup channel)"""
    uid = ctx.author.id
    msg = await _make_backup(f"manuelle (par {ctx.author})")
    if msg is None:
        return await ctx.send(_fr_en(uid, "❌ Sauvegarde impossible : je n'ai pas pu créer ou utiliser le salon de sauvegarde.",
                                     "❌ Backup failed: I couldn't create or use the backup channel."))
    await ctx.send(_fr_en(uid, f"✅ Sauvegarde faite ({max(1, _backup_status['size'] // 1024)} Ko) : {msg.jump_url}",
                          f"✅ Backup saved ({max(1, _backup_status['size'] // 1024)} KB): {msg.jump_url}"))


@bot.command(aliases=["restaure", "restaurer"])
@is_bot_admin()
async def restorebackup(ctx):
    """Restore all bot data from the newest backup (or from a backup file attached to the command)"""
    global _backups_allowed
    uid = ctx.author.id
    attachment = next((a for a in ctx.message.attachments if a.filename.endswith(".json.gz")), None)
    if attachment is None:
        latest = await _latest_backup()
        if latest is None:
            return await ctx.send(_fr_en(uid, "❌ Aucune sauvegarde trouvée.", "❌ No backup found."))
        attachment = latest[1]
    msg = await _confirm(ctx, _fr_en(uid, "♻️ Restaurer la sauvegarde ?", "♻️ Restore the backup?"),
                         _fr_en(uid, f"Toutes les données de **{attachment.filename}** vont être rechargées "
                                     "(réglages, économie, tickets, admins...).",
                                f"All data from **{attachment.filename}** will be reloaded "
                                "(settings, economy, tickets, admins...)."))
    if msg is None:
        return
    try:
        await _restore_backup_bytes(await attachment.read(), attachment.filename)
    except Exception as e:
        return await ctx.send(_fr_en(uid, f"❌ Restauration impossible : {e}", f"❌ Restore failed: {e}"))
    _backups_allowed = True
    await ctx.send(_fr_en(uid, f"✅ Données restaurées depuis **{attachment.filename}**.",
                          f"✅ Data restored from **{attachment.filename}**."))


@bot.command()
@is_bot_admin()
async def setlogchannel(ctx, channel: discord.TextChannel = None):
    """Set the security log channel"""
    uid = ctx.author.id
    channel = channel or ctx.channel
    log_channels[ctx.guild.id] = channel.id
    await ctx.send(t(uid, "logchannel.set", channel=channel.mention))


def _logs_status_embed(uid, guild):
    channel_id = log_channels.get(guild.id)
    channel = guild.get_channel(channel_id) if channel_id else None
    embed = _base_embed(t(uid, "logs.title"), EMBED_COLOR if channel else WARN_COLOR)
    embed.add_field(
        name=t(uid, "logs.channel_field"),
        value=t(uid, "logs.channel_set", channel=channel.mention) if channel else t(uid, "logs.channel_unset"),
        inline=False,
    )
    embed.add_field(name=t(uid, "logs.moderation_field"), value=t(uid, "logs.moderation_value"), inline=False)
    embed.add_field(name=t(uid, "logs.automod_field"), value=t(uid, "logs.automod_value"), inline=False)
    embed.add_field(name=t(uid, "logs.antiraid_field"), value=t(uid, "logs.antiraid_value"), inline=False)
    embed.add_field(name=t(uid, "logs.antinuke_field"), value=t(uid, "logs.antinuke_value"), inline=False)
    embed.add_field(name=t(uid, "logs.antipub_field"), value=t(uid, "logs.antipub_value"), inline=False)
    embed.description = t(uid, "logs.set_note")
    return embed


@bot.command(name="logs")
@is_bot_admin()
async def logs_cmd(ctx, channel: discord.TextChannel = None):
    """Show (and optionally set) the security log channel and what gets logged there"""
    uid = ctx.author.id
    if channel is not None:
        log_channels[ctx.guild.id] = channel.id
    await ctx.send(embed=_logs_status_embed(uid, ctx.guild))


def _paypal_status_embed(uid, guild):
    channel_id = paypal_notify_channels.get(guild.id)
    channel = guild.get_channel(channel_id) if channel_id else None
    embed = _base_embed(t(uid, "paypal.status_title"), EMBED_COLOR if channel else WARN_COLOR)
    embed.description = t(uid, "paypal.channel_set", channel=channel.mention) if channel else t(uid, "paypal.channel_unset")
    embed.add_field(name="​", value=t(uid, "paypal.setup_note"), inline=False)
    return embed


@bot.command(name="setpaypalchannel")
@is_bot_admin()
async def setpaypalchannel(ctx, channel: discord.TextChannel = None):
    """Set the channel where PayPal payment notifications (IPN) get posted"""
    uid = ctx.author.id
    if channel is not None:
        paypal_notify_channels[ctx.guild.id] = channel.id
    await ctx.send(embed=_paypal_status_embed(uid, ctx.guild))


def _crypto_status_embed(uid, guild):
    channel_id = crypto_notify_channels.get(guild.id)
    channel = guild.get_channel(channel_id) if channel_id else None
    embed = _base_embed(t(uid, "crypto.status_title"), EMBED_COLOR if channel else WARN_COLOR)
    embed.description = t(uid, "crypto.channel_set", channel=channel.mention) if channel else t(uid, "crypto.channel_unset")
    watched = _addresses_to_watch()
    if watched:
        lines = [f"`{currency.upper()}` `{address}`" for currency, address, _owner in watched]
        embed.add_field(name=t(uid, "crypto.watched_addresses"), value="\n".join(lines)[:1000], inline=False)
    return embed


@bot.command(name="setcryptochannel")
@is_bot_admin()
async def setcryptochannel(ctx, channel: discord.TextChannel = None):
    """Set the channel where BTC/LTC on-chain payment notifications get posted"""
    uid = ctx.author.id
    if channel is not None:
        crypto_notify_channels[ctx.guild.id] = channel.id
    await ctx.send(embed=_crypto_status_embed(uid, ctx.guild))


def _autoremind_status_embed(uid, guild):
    cfg = recurring_reminders.get(guild.id)
    if cfg is None:
        embed = _base_embed(t(uid, "autoremind.status_title"), WARN_COLOR)
        embed.description = t(uid, "autoremind.not_configured")
        return embed
    channel = guild.get_channel(cfg["channel_id"])
    paused = cfg.get("paused", False)
    embed = _base_embed(t(uid, "autoremind.status_title"), WARN_COLOR if paused else EMBED_COLOR)
    embed.add_field(name=t(uid, "autoremind.status_channel"), value=channel.mention if channel else "?", inline=True)
    embed.add_field(name=t(uid, "autoremind.status_interval"), value=f"{cfg['interval_minutes'] / 60:g}h", inline=True)
    embed.add_field(
        name=t(uid, "autoremind.status_paused"),
        value=t(uid, "autoremind.status_paused_value" if paused else "autoremind.status_running_value"),
        inline=True,
    )
    if not paused:
        last_sent = datetime.fromisoformat(cfg["last_sent"])
        next_post = last_sent + timedelta(minutes=cfg["interval_minutes"])
        embed.add_field(name=t(uid, "autoremind.status_next"), value=f"<t:{int(next_post.timestamp())}:R>", inline=True)
    embed.add_field(name=t(uid, "autoremind.status_message"), value=cfg["message"][:1000], inline=False)
    return embed


@bot.group(name="autoremind", invoke_without_command=True)
@is_bot_admin()
async def autoremind_group(ctx):
    """Configure a recurring reminder message posted automatically to a channel"""
    await ctx.send(embed=_autoremind_status_embed(ctx.author.id, ctx.guild))


@autoremind_group.command(name="set")
@is_bot_admin()
async def autoremind_set(ctx, channel: discord.TextChannel, hours: float, *, message):
    uid = ctx.author.id
    if not message.strip():
        return await ctx.send(t(uid, "autoremind.missing_message"))
    if hours <= 0 or hours > 720:
        return await ctx.send(t(uid, "autoremind.invalid_interval"))
    recurring_reminders[ctx.guild.id] = {
        "channel_id": channel.id,
        "message": message,
        "interval_minutes": hours * 60,
        "last_sent": datetime.now(timezone.utc).isoformat(),
        "paused": False,
    }
    await ctx.send(t(uid, "autoremind.set", hours=f"{hours:g}", channel=channel.mention))


@autoremind_group.command(name="stop")
@is_bot_admin()
async def autoremind_stop(ctx):
    uid = ctx.author.id
    recurring_reminders.pop(ctx.guild.id, None)
    await ctx.send(t(uid, "autoremind.stopped"))


@autoremind_group.command(name="pause")
@is_bot_admin()
async def autoremind_pause(ctx):
    uid = ctx.author.id
    cfg = recurring_reminders.get(ctx.guild.id)
    if cfg is None:
        return await ctx.send(t(uid, "autoremind.not_configured"))
    if cfg.get("paused"):
        return await ctx.send(t(uid, "autoremind.already_paused"))
    cfg["paused"] = True
    await ctx.send(t(uid, "autoremind.paused"))


@autoremind_group.command(name="unpause")
@is_bot_admin()
async def autoremind_unpause(ctx):
    uid = ctx.author.id
    cfg = recurring_reminders.get(ctx.guild.id)
    if cfg is None:
        return await ctx.send(t(uid, "autoremind.not_configured"))
    if not cfg.get("paused"):
        return await ctx.send(t(uid, "autoremind.not_paused"))
    cfg["paused"] = False
    cfg["last_sent"] = datetime.now(timezone.utc).isoformat()
    await ctx.send(t(uid, "autoremind.unpaused"))


async def _send_words_list(ctx):
    uid = ctx.author.id
    ws = sorted(_banned_words_for(ctx.guild.id))
    embed = _base_embed(t(uid, "words.list_title", count=len(ws)), EMBED_COLOR)
    embed.description = ", ".join(f"`{w}`" for w in ws) if ws else t(uid, "words.list_empty")
    await ctx.send(embed=embed)


@bot.group(name="words", invoke_without_command=True)
async def words_group(ctx):
    """View or edit the banned word list"""
    await _send_words_list(ctx)


@words_group.command(name="list")
async def words_list(ctx):
    await _send_words_list(ctx)


@words_group.command(name="add")
@is_bot_admin()
async def words_add(ctx, *, word):
    uid = ctx.author.id
    word = word.lower().strip()
    ws = _banned_words_for(ctx.guild.id)
    if word in ws:
        return await ctx.send(t(uid, "words.already_exists", word=word))
    ws.add(word)
    await ctx.send(t(uid, "words.added", word=word))


@words_group.command(name="remove")
@is_bot_admin()
async def words_remove(ctx, *, word):
    uid = ctx.author.id
    word = word.lower().strip()
    ws = _banned_words_for(ctx.guild.id)
    if word not in ws:
        return await ctx.send(t(uid, "words.not_found", word=word))
    ws.discard(word)
    await ctx.send(t(uid, "words.removed", word=word))


def _cmdaccess_embed(uid, guild_id):
    embed = _base_embed(t(uid, "cmdaccess.list_title"), EMBED_COLOR)
    cfg = command_access.get(guild_id, {})
    guild = bot.get_guild(guild_id)
    has_entries = False
    for name, role_ids in cfg.items():
        if not role_ids:
            continue
        has_entries = True
        mentions = []
        for rid in role_ids:
            role = guild.get_role(rid) if guild else None
            mentions.append(role.mention if role else f"`{rid}`")
        embed.add_field(name=f"`{name}`", value=", ".join(mentions), inline=False)
    if not has_entries:
        embed.description = t(uid, "cmdaccess.list_empty")
    return embed


@bot.group(name="cmdaccess", invoke_without_command=True)
@is_bot_admin()
async def cmdaccess(ctx):
    """Restrict specific commands to specific roles (bot-admin only)"""
    await ctx.send(embed=_cmdaccess_embed(ctx.author.id, ctx.guild.id))


@cmdaccess.command(name="allow")
@is_bot_admin()
async def cmdaccess_allow(ctx, command: str, role: discord.Role):
    uid = ctx.author.id
    name = command.strip().lstrip("!/").lower()
    command_access.setdefault(ctx.guild.id, {}).setdefault(name, set()).add(role.id)
    await ctx.send(t(uid, "cmdaccess.allowed", command=name, role=role.mention))


@cmdaccess.command(name="remove")
@is_bot_admin()
async def cmdaccess_remove(ctx, command: str, role: discord.Role):
    uid = ctx.author.id
    name = command.strip().lstrip("!/").lower()
    roles = command_access.get(ctx.guild.id, {}).get(name)
    if not roles or role.id not in roles:
        return await ctx.send(t(uid, "cmdaccess.not_allowed", command=name, role=role.mention))
    roles.discard(role.id)
    await ctx.send(t(uid, "cmdaccess.removed", command=name, role=role.mention))


@cmdaccess.command(name="reset")
@is_bot_admin()
async def cmdaccess_reset(ctx, command: str):
    uid = ctx.author.id
    name = command.strip().lstrip("!/").lower()
    guild_cfg = command_access.get(ctx.guild.id)
    if guild_cfg and name in guild_cfg:
        del guild_cfg[name]
    await ctx.send(t(uid, "cmdaccess.reset", command=name))


@cmdaccess.command(name="list")
@is_bot_admin()
async def cmdaccess_list(ctx):
    await ctx.send(embed=_cmdaccess_embed(ctx.author.id, ctx.guild.id))


@bot.command(name="saveconfig")
@is_bot_admin()
async def saveconfig(ctx):
    """Force an immediate save of the bot's config to Redis"""
    uid = ctx.author.id
    if redis_client is None:
        return await ctx.send(t(uid, "saveconfig.no_redis"))
    await _save_state_to_redis()
    await ctx.send(t(uid, "saveconfig.saved"))


@bot.group(name="botadmin", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def botadmin(ctx):
    """Manage who can control the bot (admin only)"""
    uid = ctx.author.id
    admins = bot_admins.get(ctx.guild.id, {"roles": set(), "users": set()})
    embed = _base_embed(t(uid, "botadmin.list_title"), EMBED_COLOR)
    roles_text = ", ".join(f"<@&{r}>" for r in admins["roles"]) or t(uid, "botadmin.list_empty")
    users_text = ", ".join(f"<@{u}>" for u in admins["users"]) or t(uid, "botadmin.list_empty")
    embed.add_field(name=t(uid, "botadmin.list_roles"), value=roles_text, inline=False)
    embed.add_field(name=t(uid, "botadmin.list_users"), value=users_text, inline=False)
    await ctx.send(embed=embed)


@botadmin.command(name="addrole")
@commands.has_permissions(administrator=True)
async def botadmin_addrole(ctx, role: discord.Role):
    uid = ctx.author.id
    bot_admins.setdefault(ctx.guild.id, {"roles": set(), "users": set()})["roles"].add(role.id)
    await ctx.send(t(uid, "botadmin.role_added", role=role.mention))


@botadmin.command(name="removerole")
@commands.has_permissions(administrator=True)
async def botadmin_removerole(ctx, role: discord.Role):
    uid = ctx.author.id
    bot_admins.setdefault(ctx.guild.id, {"roles": set(), "users": set()})["roles"].discard(role.id)
    await ctx.send(t(uid, "botadmin.role_removed", role=role.mention))


@botadmin.command(name="adduser")
@commands.has_permissions(administrator=True)
async def botadmin_adduser(ctx, member: discord.Member):
    uid = ctx.author.id
    bot_admins.setdefault(ctx.guild.id, {"roles": set(), "users": set()})["users"].add(member.id)
    await ctx.send(t(uid, "botadmin.user_added", user=member.mention))


@botadmin.command(name="removeuser")
@commands.has_permissions(administrator=True)
async def botadmin_removeuser(ctx, member: discord.Member):
    uid = ctx.author.id
    bot_admins.setdefault(ctx.guild.id, {"roles": set(), "users": set()})["users"].discard(member.id)
    await ctx.send(t(uid, "botadmin.user_removed", user=member.mention))


@bot.group(name="antiraid", invoke_without_command=True)
@is_bot_admin()
async def antiraid_group(ctx):
    """Configure anti-raid protection"""
    uid = ctx.author.id
    cfg = _antiraid_cfg(ctx.guild.id)
    embed = _base_embed(t(uid, "antiraid.status_title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "antiraid.status_label"), value=t(uid, "antiraid.enabled") if cfg["enabled"] else t(uid, "antiraid.disabled"), inline=True)
    embed.add_field(name=t(uid, "antiraid.threshold"), value=cfg["threshold"], inline=True)
    embed.add_field(name=t(uid, "antiraid.window"), value=f"{cfg['window']}s", inline=True)
    await ctx.send(embed=embed)


@antiraid_group.command(name="on")
@is_bot_admin()
async def antiraid_on(ctx):
    uid = ctx.author.id
    cfg = _antiraid_cfg(ctx.guild.id)
    if cfg["enabled"]:
        return await ctx.send(t(uid, "antiraid.already_on"))
    cfg["enabled"] = True
    await ctx.send(t(uid, "antiraid.on"))


@antiraid_group.command(name="off")
@is_bot_admin()
async def antiraid_off(ctx):
    uid = ctx.author.id
    cfg = _antiraid_cfg(ctx.guild.id)
    if not cfg["enabled"]:
        return await ctx.send(t(uid, "antiraid.already_off"))
    cfg["enabled"] = False
    await ctx.send(t(uid, "antiraid.off"))


@antiraid_group.command(name="config")
@is_bot_admin()
async def antiraid_config(ctx, threshold: int = 5, window: int = 10):
    uid = ctx.author.id
    threshold = max(2, min(threshold, 50))
    window = max(3, min(window, 300))
    cfg = _antiraid_cfg(ctx.guild.id)
    cfg["threshold"] = threshold
    cfg["window"] = window
    await ctx.send(t(uid, "antiraid.configured", threshold=threshold, window=window))


@bot.group(name="antinuke", invoke_without_command=True)
@is_bot_admin()
async def antinuke_group(ctx):
    """Configure anti-nuke protection"""
    uid = ctx.author.id
    cfg = _antinuke_cfg(ctx.guild.id)
    embed = _base_embed(t(uid, "antinuke.status_title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "antiraid.status_label"), value=t(uid, "antiraid.enabled") if cfg["enabled"] else t(uid, "antiraid.disabled"), inline=True)
    embed.add_field(name=t(uid, "antiraid.threshold"), value=cfg["threshold"], inline=True)
    embed.add_field(name=t(uid, "antiraid.window"), value=f"{cfg['window']}s", inline=True)
    await ctx.send(embed=embed)


@antinuke_group.command(name="on")
@is_bot_admin()
async def antinuke_on(ctx):
    uid = ctx.author.id
    cfg = _antinuke_cfg(ctx.guild.id)
    if cfg["enabled"]:
        return await ctx.send(t(uid, "antinuke.already_on"))
    cfg["enabled"] = True
    await ctx.send(t(uid, "antinuke.on"))


@antinuke_group.command(name="off")
@is_bot_admin()
async def antinuke_off(ctx):
    uid = ctx.author.id
    cfg = _antinuke_cfg(ctx.guild.id)
    if not cfg["enabled"]:
        return await ctx.send(t(uid, "antinuke.already_off"))
    cfg["enabled"] = False
    await ctx.send(t(uid, "antinuke.off"))


@antinuke_group.command(name="config")
@is_bot_admin()
async def antinuke_config(ctx, threshold: int = 3, window: int = 10):
    uid = ctx.author.id
    threshold = max(2, min(threshold, 20))
    window = max(3, min(window, 120))
    cfg = _antinuke_cfg(ctx.guild.id)
    cfg["threshold"] = threshold
    cfg["window"] = window
    await ctx.send(t(uid, "antinuke.configured", threshold=threshold, window=window))


async def _send_antipub_blacklist(ctx):
    uid = ctx.author.id
    words = sorted(antipub_blacklist.get(ctx.guild.id, DEFAULT_ANTIPUB_KEYWORDS))
    embed = _base_embed(t(uid, "antipub.blacklist_title", count=len(words)), EMBED_COLOR)
    embed.description = ", ".join(f"`{w}`" for w in words) if words else t(uid, "words.list_empty")
    await ctx.send(embed=embed)


async def _send_antipub_whitelist(ctx):
    uid = ctx.author.id
    guild_id = ctx.guild.id
    embed = _base_embed(t(uid, "antipub.whitelist_title"), EMBED_COLOR)
    roles_text = ", ".join(f"<@&{r}>" for r in antipub_whitelist_roles.get(guild_id, set())) or t(uid, "botadmin.list_empty")
    channels_text = ", ".join(f"<#{c}>" for c in antipub_whitelist_channels.get(guild_id, set())) or t(uid, "botadmin.list_empty")
    embed.add_field(name=t(uid, "antipub.whitelist_roles"), value=roles_text, inline=False)
    embed.add_field(name=t(uid, "antipub.whitelist_channels"), value=channels_text, inline=False)
    await ctx.send(embed=embed)


AUTOMOD_MODULES = ("words", "pub", "all")


def _automod_status_embed(uid, guild):
    def state(on):
        return t(uid, "antiraid.enabled") if on else t(uid, "antiraid.disabled")
    embed = discord.Embed(title=t(uid, "automod.status_title"), color=EMBED_COLOR)
    embed.add_field(name=t(uid, "automod.field_words"), inline=False, value=t(
        uid, "automod.words_detail", state=state(_automod_cfg(guild.id)["words"]), count=len(_banned_words_for(guild.id))))
    embed.add_field(name=t(uid, "automod.field_pub"), inline=False,
                    value=t(uid, "automod.pub_detail", state=state(_antipub_cfg(guild.id)["enabled"])))
    embed.add_field(name=t(uid, "automod.field_raid"), inline=False,
                    value=t(uid, "automod.raid_detail", state=state(_antiraid_cfg(guild.id)["enabled"])))
    embed.add_field(name=t(uid, "automod.field_nuke"), inline=False,
                    value=t(uid, "automod.nuke_detail", state=state(_antinuke_cfg(guild.id)["enabled"])))
    embed.set_footer(text=t(uid, "automod.hint"))
    return embed


def _automod_set(uid, guild_id, module, enabled):
    """Turn the banned-word filter, the anti-ads, or both on or off. Returns the answer text."""
    if module in ("words", "all"):
        _automod_cfg(guild_id)["words"] = enabled
    if module in ("pub", "all"):
        _antipub_cfg(guild_id)["enabled"] = enabled
    _request_backup_soon("config")
    return t(uid, "automod.turned_on" if enabled else "automod.turned_off", what=t(uid, f"automod.mod_{module}"))


@bot.group(name="automod", invoke_without_command=True)
@is_bot_admin()
async def automod_group(ctx):
    """Auto-moderation on command: status, on, off"""
    await ctx.send(embed=_automod_status_embed(ctx.author.id, ctx.guild))


@automod_group.command(name="status")
@is_bot_admin()
async def automod_status(ctx):
    await ctx.send(embed=_automod_status_embed(ctx.author.id, ctx.guild))


@automod_group.command(name="on")
@is_bot_admin()
async def automod_on(ctx, module: str = "all"):
    module = module.lower()
    if module not in AUTOMOD_MODULES:
        return await ctx.send(t(ctx.author.id, "automod.hint"))
    await ctx.send(_automod_set(ctx.author.id, ctx.guild.id, module, True))


@automod_group.command(name="off")
@is_bot_admin()
async def automod_off(ctx, module: str = "all"):
    module = module.lower()
    if module not in AUTOMOD_MODULES:
        return await ctx.send(t(ctx.author.id, "automod.hint"))
    await ctx.send(_automod_set(ctx.author.id, ctx.guild.id, module, False))


automod_slash_group = app_commands.Group(name="automod", description="Auto-moderation on command: banned words and anti-ads")
bot.tree.add_command(automod_slash_group)
_AUTOMOD_CHOICES = [app_commands.Choice(name=n, value=v) for n, v in (
    ("Banned words and anti-ads", "all"), ("Banned words only", "words"), ("Anti-ads only", "pub"))]


@automod_slash_group.command(name="status", description="Show what the auto-moderation does in this server")
@is_bot_admin_slash()
@app_commands.guild_only()
async def automod_status_slash(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_automod_status_embed(interaction.user.id, interaction.guild), ephemeral=True)


@automod_slash_group.command(name="on", description="Turn the auto-moderation on")
@app_commands.describe(module="What to turn on (default: banned words and anti-ads)")
@app_commands.choices(module=_AUTOMOD_CHOICES)
@is_bot_admin_slash()
@app_commands.guild_only()
async def automod_on_slash(interaction: discord.Interaction, module: app_commands.Choice[str] = None):
    await interaction.response.send_message(
        _automod_set(interaction.user.id, interaction.guild.id, module.value if module else "all", True), ephemeral=True)


@automod_slash_group.command(name="off", description="Turn the auto-moderation off")
@app_commands.describe(module="What to turn off (default: banned words and anti-ads)")
@app_commands.choices(module=_AUTOMOD_CHOICES)
@is_bot_admin_slash()
@app_commands.guild_only()
async def automod_off_slash(interaction: discord.Interaction, module: app_commands.Choice[str] = None):
    await interaction.response.send_message(
        _automod_set(interaction.user.id, interaction.guild.id, module.value if module else "all", False), ephemeral=True)


@bot.group(name="antipub", invoke_without_command=True)
@is_bot_admin()
async def antipub_group(ctx):
    """Configure the anti-advertising system"""
    uid = ctx.author.id
    cfg = _antipub_cfg(ctx.guild.id)
    embed = _base_embed(t(uid, "antipub.status_title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "antiraid.status_label"), value=t(uid, "antiraid.enabled") if cfg["enabled"] else t(uid, "antiraid.disabled"), inline=True)
    embed.add_field(name=t(uid, "antipub.threshold"), value=cfg["threshold"], inline=True)
    embed.add_field(name=t(uid, "antipub.sanction"), value=cfg["sanction"], inline=True)
    embed.add_field(name=t(uid, "antipub.timeout_minutes"), value=f"{cfg['timeout_minutes']}min", inline=True)
    await ctx.send(embed=embed)


@antipub_group.command(name="on")
@is_bot_admin()
async def antipub_on(ctx):
    uid = ctx.author.id
    cfg = _antipub_cfg(ctx.guild.id)
    if cfg["enabled"]:
        return await ctx.send(t(uid, "antipub.already_on"))
    cfg["enabled"] = True
    await ctx.send(t(uid, "antipub.on"))


@antipub_group.command(name="off")
@is_bot_admin()
async def antipub_off(ctx):
    uid = ctx.author.id
    cfg = _antipub_cfg(ctx.guild.id)
    if not cfg["enabled"]:
        return await ctx.send(t(uid, "antipub.already_off"))
    cfg["enabled"] = False
    await ctx.send(t(uid, "antipub.off"))


@antipub_group.command(name="config")
@is_bot_admin()
async def antipub_config(ctx, threshold: int = 5, sanction: str = "warn", timeout_minutes: int = 10):
    uid = ctx.author.id
    sanction = sanction.lower()
    if sanction not in ("warn", "timeout", "kick", "ban"):
        return await ctx.send(t(uid, "antipub.invalid_sanction"))
    threshold = max(1, min(threshold, 50))
    timeout_minutes = max(1, min(timeout_minutes, 10080))
    cfg = _antipub_cfg(ctx.guild.id)
    cfg["threshold"] = threshold
    cfg["sanction"] = sanction
    cfg["timeout_minutes"] = timeout_minutes
    await ctx.send(t(uid, "antipub.configured", threshold=threshold, sanction=sanction))


@antipub_group.group(name="blacklist", invoke_without_command=True)
@is_bot_admin()
async def antipub_blacklist_group(ctx):
    await _send_antipub_blacklist(ctx)


@antipub_blacklist_group.command(name="add")
@is_bot_admin()
async def antipub_blacklist_add(ctx, *, word):
    uid = ctx.author.id
    word = word.lower().strip()
    words = antipub_blacklist.setdefault(ctx.guild.id, set(DEFAULT_ANTIPUB_KEYWORDS))
    if word in words:
        return await ctx.send(t(uid, "antipub.blacklist_exists", word=word))
    words.add(word)
    await ctx.send(t(uid, "antipub.blacklist_added", word=word))


@antipub_blacklist_group.command(name="remove")
@is_bot_admin()
async def antipub_blacklist_remove(ctx, *, word):
    uid = ctx.author.id
    word = word.lower().strip()
    words = antipub_blacklist.setdefault(ctx.guild.id, set(DEFAULT_ANTIPUB_KEYWORDS))
    if word not in words:
        return await ctx.send(t(uid, "antipub.blacklist_not_found", word=word))
    words.discard(word)
    await ctx.send(t(uid, "antipub.blacklist_removed", word=word))


@antipub_blacklist_group.command(name="list")
@is_bot_admin()
async def antipub_blacklist_list(ctx):
    await _send_antipub_blacklist(ctx)


@antipub_group.group(name="whitelist", invoke_without_command=True)
@is_bot_admin()
async def antipub_whitelist_group(ctx):
    await _send_antipub_whitelist(ctx)


@antipub_whitelist_group.command(name="addrole")
@is_bot_admin()
async def antipub_whitelist_addrole(ctx, role: discord.Role):
    uid = ctx.author.id
    antipub_whitelist_roles.setdefault(ctx.guild.id, set()).add(role.id)
    await ctx.send(t(uid, "antipub.whitelist_role_added", role=role.mention))


@antipub_whitelist_group.command(name="removerole")
@is_bot_admin()
async def antipub_whitelist_removerole(ctx, role: discord.Role):
    uid = ctx.author.id
    antipub_whitelist_roles.setdefault(ctx.guild.id, set()).discard(role.id)
    await ctx.send(t(uid, "antipub.whitelist_role_removed", role=role.mention))


@antipub_whitelist_group.command(name="addchannel")
@is_bot_admin()
async def antipub_whitelist_addchannel(ctx, channel: discord.TextChannel):
    uid = ctx.author.id
    antipub_whitelist_channels.setdefault(ctx.guild.id, set()).add(channel.id)
    await ctx.send(t(uid, "antipub.whitelist_channel_added", channel=channel.mention))


@antipub_whitelist_group.command(name="removechannel")
@is_bot_admin()
async def antipub_whitelist_removechannel(ctx, channel: discord.TextChannel):
    uid = ctx.author.id
    antipub_whitelist_channels.setdefault(ctx.guild.id, set()).discard(channel.id)
    await ctx.send(t(uid, "antipub.whitelist_channel_removed", channel=channel.mention))


@bot.group(name="screening", invoke_without_command=True)
@is_bot_admin()
async def screening_group(ctx):
    """Configure the account screening of new members"""
    uid = ctx.author.id
    cfg = _screening_cfg(ctx.guild.id)
    embed = _base_embed(t(uid, "screening.status_title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "antiraid.status_label"), value=t(uid, "antiraid.enabled") if cfg["enabled"] else t(uid, "antiraid.disabled"), inline=True)
    embed.add_field(name=t(uid, "screening.action_label"), value=cfg["action"], inline=True)
    embed.add_field(name=t(uid, "screening.threshold_label"), value=str(cfg["threshold"]), inline=True)
    embed.add_field(name=t(uid, "screening.minage_label"), value=f"{cfg['min_age_days']} d", inline=True)
    embed.add_field(name=t(uid, "screening.timeout_label"), value=f"{cfg['timeout_minutes']} min", inline=True)
    role = ctx.guild.get_role(cfg.get("role_id") or 0)
    embed.add_field(name=t(uid, "screening.role_label"), value=role.mention if role else "—", inline=True)
    qrole = ctx.guild.get_role(cfg.get("quarantine_role_id") or 0)
    embed.add_field(name=t(uid, "screening.quarantine_label"), value=qrole.mention if qrole else "—", inline=True)
    await ctx.send(embed=embed)


@screening_group.command(name="on")
@is_bot_admin()
async def screening_on(ctx):
    uid = ctx.author.id
    cfg = _screening_cfg(ctx.guild.id)
    if cfg["enabled"]:
        return await ctx.send(t(uid, "screening.already_on"))
    cfg["enabled"] = True
    await ctx.send(t(uid, "screening.on"))


@screening_group.command(name="off")
@is_bot_admin()
async def screening_off(ctx):
    uid = ctx.author.id
    cfg = _screening_cfg(ctx.guild.id)
    if not cfg["enabled"]:
        return await ctx.send(t(uid, "screening.already_off"))
    cfg["enabled"] = False
    await ctx.send(t(uid, "screening.off"))


@screening_group.command(name="action")
@is_bot_admin()
async def screening_action(ctx, action: str):
    uid = ctx.author.id
    action = action.lower()
    if action not in SCREENING_ACTIONS:
        return await ctx.send(t(uid, "screening.action_invalid"))
    _screening_cfg(ctx.guild.id)["action"] = action
    await ctx.send(t(uid, "screening.action_set", action=action))


@screening_group.command(name="threshold")
@is_bot_admin()
async def screening_threshold(ctx, value: int):
    uid = ctx.author.id
    value = max(1, min(value, 12))
    _screening_cfg(ctx.guild.id)["threshold"] = value
    await ctx.send(t(uid, "screening.threshold_set", value=value))


@screening_group.command(name="minage")
@is_bot_admin()
async def screening_minage(ctx, days: int):
    uid = ctx.author.id
    days = max(1, min(days, 90))
    _screening_cfg(ctx.guild.id)["min_age_days"] = days
    await ctx.send(t(uid, "screening.minage_set", value=days))


@screening_group.command(name="timeout")
@is_bot_admin()
async def screening_timeout(ctx, minutes: int):
    uid = ctx.author.id
    minutes = max(1, min(minutes, 40320))
    _screening_cfg(ctx.guild.id)["timeout_minutes"] = minutes
    await ctx.send(t(uid, "screening.timeout_set", value=minutes))


@screening_group.command(name="role")
@is_bot_admin()
async def screening_role(ctx, role: discord.Role = None):
    uid = ctx.author.id
    cfg = _screening_cfg(ctx.guild.id)
    cfg["role_id"] = role.id if role else None
    await ctx.send(t(uid, "screening.role_set", role=role.mention) if role else t(uid, "screening.role_off"))


@screening_group.command(name="quarantine")
@is_bot_admin()
async def screening_quarantine(ctx, role: discord.Role = None):
    uid = ctx.author.id
    cfg = _screening_cfg(ctx.guild.id)
    cfg["quarantine_role_id"] = role.id if role else None
    await ctx.send(t(uid, "screening.quarantine_set", role=role.mention) if role else t(uid, "screening.quarantine_off"))


@screening_group.command(name="release")
@is_bot_admin()
async def screening_release(ctx, member: discord.Member):
    """Let a quarantined member in (removes the quarantine role, gives the verified role)."""
    uid = ctx.author.id
    cfg = _screening_cfg(ctx.guild.id)
    qrole = ctx.guild.get_role(cfg.get("quarantine_role_id") or 0)
    vrole = ctx.guild.get_role(cfg.get("role_id") or 0)
    if qrole is None or qrole not in member.roles:
        return await ctx.send(t(uid, "screening.release_none", member=member.mention))
    try:
        await member.remove_roles(qrole, reason=f"Released from quarantine by {ctx.author}")
        if vrole is not None:
            await member.add_roles(vrole, reason=f"Released from quarantine by {ctx.author}")
    except discord.HTTPException:
        return await ctx.send(t(uid, "screening.action_failed"))
    await ctx.send(t(uid, "screening.release_done", member=member.mention))
    await _log_moderation(ctx.guild, ctx.author, t(0, "screening.status_title"), t(0, "screening.release_done", member=str(member)), EMBED_COLOR)


@bot.command(name="screen")
@is_bot_admin()
async def screen_cmd(ctx, member: discord.Member):
    """Check how suspicious a member's account looks"""
    uid = ctx.author.id
    cfg = _screening_cfg(ctx.guild.id)
    score, reasons = await _screen_member(member, cfg)
    flagged = score >= cfg["threshold"]
    embed = _base_embed(t(uid, "screening.check_title", member=member.display_name), WARN_COLOR if flagged else EMBED_COLOR)
    embed.description = t(
        uid, "screening.check_description", score=score, threshold=cfg["threshold"],
        verdict=t(uid, "screening.verdict_flag" if flagged else "screening.verdict_ok"),
        reasons=_screening_reasons_text(uid, reasons),
    )
    await ctx.send(embed=embed)


@bot.tree.command(name="verify", description="Post the verification panel")
@app_commands.describe(role="Role to give when verified (saves it; omit to keep the current one)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def verify_slash(interaction: discord.Interaction, role: Optional[discord.Role] = None):
    uid = interaction.user.id
    if not oauth_verify.is_configured() or not oauth_verify.redirect_uri():
        return await interaction.response.send_message(
            t(uid, "verify.not_configured", redirect=oauth_verify.redirect_uri() or "https://<your-host>/verify/callback"),
            ephemeral=True,
        )
    if role is not None:
        _screening_cfg(interaction.guild.id)["role_id"] = role.id
        _request_backup_soon("config")
    embed = _base_embed(STRINGS['en']['verify.panel_title'], SUCCESS_COLOR)
    embed.description = STRINGS["en"]["verify.panel_description"]
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.link, emoji="✅", url=oauth_verify.auth_url(interaction.guild.id),
        label=f"{STRINGS['en']['verify.button']}",
    ))
    await interaction.channel.send(embed=embed, view=view)
    cfg = _screening_cfg(interaction.guild.id)
    role_info = f"<@&{cfg['role_id']}>" if cfg.get("role_id") else "*(none — add `role:@YourRole` to set it)*"
    await interaction.response.send_message(
        t(uid, "verify.panel_posted") + f"\n🎭 Verify role: {role_info}", ephemeral=True,
    )


KEY_CHANNEL_NAME = "key"
try:
    KEY_CHANNEL_ID = int(os.environ.get("KEY_CHANNEL_ID", "0") or 0)   # optional: the key channel by id
except ValueError:
    KEY_CHANNEL_ID = 0
# The Roblox-profile code step is off by default (too heavy for members). Set
# KEY_REQUIRE_PROOF=1 to bring it back, e.g. if people start claiming other players' names.
KEY_REQUIRE_PROOF = os.environ.get("KEY_REQUIRE_PROOF", "").strip().lower() in ("1", "true", "yes", "on")
key_invites = {}   # channel id -> permanent invite link (an invite link is public, not a secret)
_key_invite_checked = False
KEY_PENDING_MINUTES = 10
_key_pending = {}     # discord id -> {"roblox_id", "name", "code", "expires"}
_key_last_call = {}   # discord id -> time of the last /key


def _is_key_channel(channel):
    return getattr(channel, "name", None) == KEY_CHANNEL_NAME or (
        bool(KEY_CHANNEL_ID) and getattr(channel, "id", None) == KEY_CHANNEL_ID)


def _mark_key_system_ready():
    """Open the key system once the saved keys are loaded. If backups exist but none
    could be restored, it stays closed: serving an empty store would tell every
    player their valid key is "invalid", and /key would issue keys that a later
    restore could overwrite."""
    key_store.set_ready(_backups_allowed)
    if not _backups_allowed:
        print("[WARN] Key system kept closed: the saved keys could not be restored")


async def _ensure_key_invite():
    """Make sure the key channel (KEY_CHANNEL_ID) has a permanent invite link,
    keep it in the saved state and write it to the log."""
    if not KEY_CHANNEL_ID:
        return
    channel = bot.get_channel(KEY_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(KEY_CHANNEL_ID)
        except discord.HTTPException as e:
            print(f"[WARN] Key channel {KEY_CHANNEL_ID} is not reachable: {e}")
            return
    url = key_invites.get(channel.id)
    if url is None:
        try:
            invite = await channel.create_invite(max_age=0, max_uses=0, unique=False, reason="Key system invite")
        except discord.HTTPException as e:
            print(f"[WARN] Couldn't create the invite for #{channel.name} (the bot needs Create Invite there): {e}")
            return
        url = key_invites[channel.id] = invite.url
    print(f"[OK] Key channel #{channel.name} (server '{channel.guild.name}', id {channel.id}) permanent invite: {url}")


def _new_ownership_code():
    return "yslem-" + "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(6))


def _key_embed(uid, guild, rec):
    embed = _base_embed(t(uid, "key.title"), SUCCESS_COLOR)
    embed.description = t(uid, "key.description", name=rec["roblox_name"], expires=f"<t:{int(rec['expires'])}:D>")
    return embed


async def _key_antibot(member):
    """The same account check as the join screening, applied to someone asking
    for a key. A flagged account gets no key and the staff is alerted (log
    only: asking for a key never kicks or times anyone out)."""
    cfg = _screening_cfg(member.guild.id)
    score, reasons = await _screen_member(member, cfg, count_join=False)
    if score < cfg["threshold"]:
        return True
    await _apply_screening_action(member, {**cfg, "action": "log"}, score, reasons)
    return False


def _key_issue_error(uid, code, name=""):
    return {
        "banned": t(uid, "key.banned"), "admin_revoked": t(uid, "key.admin_revoked"),
        "roblox_taken": t(uid, "key.roblox_taken"), "linked_other": t(uid, "key.linked_other"),
        "no_key": t(uid, "key.no_key"),
    }.get(code, t(uid, "key.slow"))


async def _key_deliver(interaction, key, rec):
    """Show the key in a message of its own (long-press -> Copy text gives the
    key and nothing else) under a short explanation, and keep a copy in DMs."""
    uid = interaction.user.id
    embed = _key_embed(uid, interaction.guild, rec)
    note = ""
    try:
        await interaction.user.send(embed=embed)
        await interaction.user.send(key)
        note = t(uid, "key.dm_note")
    except discord.HTTPException:
        pass  # DMs closed: the replies below are enough
    await interaction.followup.send(content=note or None, embed=embed, ephemeral=True)
    await interaction.followup.send(key, ephemeral=True)


async def _key_issue_and_deliver(interaction, roblox_id, name, reset=False):
    uid = interaction.user.id
    if not await _key_antibot(interaction.user):
        _key_pending.pop(uid, None)
        return await interaction.followup.send(t(uid, "key.review"), ephemeral=True)
    code, key, rec = key_store.issue(uid, roblox_id, name, reset=reset)
    _key_pending.pop(uid, None)
    if code == "ok":
        _request_backup_soon("clé émise")
    if code in ("reset_too_soon", "reset_quota"):
        when = f"<t:{int(time.time()) + key_store.next_reset_in(uid)}:R>"
        return await interaction.followup.send(t(uid, f"key.{code}", when=when), ephemeral=True)
    if code != "ok":
        return await interaction.followup.send(_key_issue_error(uid, code), ephemeral=True)
    await _key_deliver(interaction, key, rec)


class KeyReplaceView(discord.ui.View):
    """Asked before replacing a working key, so a double /key cannot cancel it by accident."""

    def __init__(self, owner_id, roblox_id, name):
        super().__init__(timeout=300)
        self.owner_id, self.roblox_id, self.name = owner_id, roblox_id, name
        self.replace_button.label = f"{STRINGS['en']['key.replace_button']}"

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="🔁", label="OK")
    async def replace_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid != self.owner_id:
            return await interaction.response.send_message(t(uid, "key.not_yours"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        self.stop()
        await _key_issue_and_deliver(interaction, self.roblox_id, self.name, reset=True)


class KeyCheckView(discord.ui.View):
    """Only used when KEY_REQUIRE_PROOF is on: the member says the code is in their profile."""

    def __init__(self, owner_id):
        super().__init__(timeout=KEY_PENDING_MINUTES * 60)
        self.owner_id = owner_id
        self.check_button.label = f"{STRINGS['en']['key.button'][2:]}"

    @discord.ui.button(style=discord.ButtonStyle.success, emoji="✅", label="OK")
    async def check_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid != self.owner_id:
            return await interaction.response.send_message(t(uid, "key.not_yours"), ephemeral=True)
        pending = _key_pending.get(uid)
        if not pending or pending["expires"] < time.time():
            return await interaction.response.send_message(t(uid, "key.pending_expired"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await _key_finish(interaction, pending)


async def _key_finish(interaction, pending):
    """(proof mode) The member says the code is in their profile: check it, then issue the key."""
    uid = interaction.user.id
    try:
        description = await roblox_api.fetch_description(pending["roblox_id"])
    except roblox_api.RobloxUnavailable:
        return await interaction.followup.send(t(uid, "key.roblox_unavailable"), ephemeral=True)
    if description is None or pending["code"].lower() not in description.lower():
        return await interaction.followup.send(
            t(uid, "key.code_missing", name=pending["name"], code=pending["code"]),
            view=KeyCheckView(uid), ephemeral=True)
    await _key_issue_and_deliver(interaction, pending["roblox_id"], pending["name"])


@bot.tree.command(name="key", description="Get your script key")
@app_commands.describe(user="Your Roblox username")
@app_commands.guild_only()
async def key_slash(interaction: discord.Interaction, user: str):
    uid = interaction.user.id
    if not _is_key_channel(interaction.channel):
        return await interaction.response.send_message(t(uid, "key.channel_only", channel=KEY_CHANNEL_NAME), ephemeral=True)
    if not key_store.is_ready():
        return await interaction.response.send_message(t(uid, "key.starting"), ephemeral=True)
    now = time.time()
    if now - _key_last_call.get(uid, 0) < 4:
        return await interaction.response.send_message(t(uid, "key.slow"), ephemeral=True)
    _key_last_call[uid] = now
    await interaction.response.defer(ephemeral=True)
    pseudo = user.strip()
    if key_store.is_banned(uid):
        return await interaction.followup.send(t(uid, "key.banned"), ephemeral=True)
    if not roblox_api.valid_username(pseudo):
        return await interaction.followup.send(t(uid, "key.bad_name"), ephemeral=True)
    try:
        found = await roblox_api.resolve_username(pseudo)
    except roblox_api.RobloxUnavailable:
        return await interaction.followup.send(t(uid, "key.roblox_unavailable"), ephemeral=True)
    if found is None:
        return await interaction.followup.send(t(uid, "key.not_found", name=pseudo), ephemeral=True)
    roblox_id, name = found

    rec = key_store.current_record(uid)
    if rec is not None and rec["admin_revoked"]:
        return await interaction.followup.send(t(uid, "key.admin_revoked"), ephemeral=True)
    if rec is not None and not rec["revoked"] and rec["expires"] > now:
        # Already has a working key: running /key again means "I lost it".
        if rec["roblox_id"] != roblox_id:
            return await interaction.followup.send(t(uid, "key.linked_other"), ephemeral=True)
        blocked = key_store.can_reset(uid)
        if blocked != "ok":
            when = f"<t:{int(now) + key_store.next_reset_in(uid)}:R>"
            return await interaction.followup.send(t(uid, f"key.{blocked}", when=when), ephemeral=True)
        return await interaction.followup.send(
            t(uid, "key.replace_confirm", name=rec["roblox_name"], expires=f"<t:{int(rec['expires'])}:D>"),
            view=KeyReplaceView(uid, roblox_id, name), ephemeral=True)

    precheck = key_store.can_issue(uid, roblox_id)
    if precheck != "ok":
        return await interaction.followup.send(_key_issue_error(uid, precheck), ephemeral=True)
    if not KEY_REQUIRE_PROOF:
        return await _key_issue_and_deliver(interaction, roblox_id, name)

    # proof mode: the member must put a short code in their Roblox profile first
    pending = _key_pending.get(uid)
    if pending and pending["roblox_id"] == roblox_id and pending["expires"] > now:
        return await _key_finish(interaction, pending)
    pending = {"roblox_id": roblox_id, "name": name, "code": _new_ownership_code(),
               "expires": now + KEY_PENDING_MINUTES * 60}
    _key_pending[uid] = pending
    await interaction.followup.send(
        t(uid, "key.step_code", name=name, code=pending["code"], minutes=KEY_PENDING_MINUTES),
        view=KeyCheckView(uid), ephemeral=True)


@bot.group(name="keyadmin", invoke_without_command=True)
@commands.guild_only()
@is_bot_admin()
async def keyadmin_group(ctx):
    """Staff tools for the key system (kept out of the slash picker)"""
    await ctx.send(t(ctx.author.id, "keyadmin.usage"))


@keyadmin_group.command(name="info")
@commands.guild_only()
@is_bot_admin()
async def keyadmin_info(ctx, member: discord.Member):
    uid = ctx.author.id
    rec = key_store.current_record(member.id)
    banned = key_store.is_banned(member.id, rec["roblox_id"] if rec else None)
    if rec is None:
        status = t(uid, "key.status_none")
    elif rec["revoked"]:
        status = t(uid, "key.status_revoked")
    elif rec["expires"] <= time.time():
        status = t(uid, "key.status_expired")
    else:
        status = t(uid, "key.status_active")
    embed = _base_embed(t(uid, "key.info_title", member=member.display_name), EMBED_COLOR)
    embed.description = t(
        uid, "key.info_description", name=rec["roblox_name"] if rec else "—", rid=rec["roblox_id"] if rec else "—",
        status=status, created=f"<t:{int(rec['created'])}:R>" if rec else "—",
        expires=f"<t:{int(rec['expires'])}:R>" if rec else "—", resets=key_store.resets_used(member.id),
        banned=t(uid, "key.yes" if banned else "key.no"))
    await ctx.send(embed=embed)


async def _keyadmin_done(ctx, member, message):
    _request_backup_soon("action staff sur une clé")
    await ctx.send(message)
    await _log_moderation(ctx.guild, ctx.author, t(0, "key.info_title", member=str(member)),
                          message.replace(member.mention, str(member)), EMBED_COLOR)


@keyadmin_group.command(name="revoke")
@commands.guild_only()
@is_bot_admin()
async def keyadmin_revoke(ctx, member: discord.Member):
    uid = ctx.author.id
    if not key_store.admin_revoke(member.id):
        return await ctx.send(t(uid, "key.revoked_none", member=member.mention))
    await _keyadmin_done(ctx, member, t(uid, "key.revoked_ok", member=member.mention))


@keyadmin_group.command(name="ban")
@commands.guild_only()
@is_bot_admin()
async def keyadmin_ban(ctx, member: discord.Member):
    uid = ctx.author.id
    key_store.ban(member.id, f"by {ctx.author}")
    await _keyadmin_done(ctx, member, t(uid, "key.ban_ok", member=member.mention))


@keyadmin_group.command(name="unban")
@commands.guild_only()
@is_bot_admin()
async def keyadmin_unban(ctx, member: discord.Member):
    uid = ctx.author.id
    if not key_store.unban(member.id):
        return await ctx.send(t(uid, "key.unban_none", member=member.mention))
    await _keyadmin_done(ctx, member, t(uid, "key.unban_ok", member=member.mention))


@keyadmin_group.command(name="stats")
@commands.guild_only()
@is_bot_admin()
async def keyadmin_stats(ctx):
    uid = ctx.author.id
    stats = key_store.script_stats()
    live, banned = key_store.count()
    lines = [f"`{name}` : {v['valid']} valid, {v['other']} other" for name, v in stats.items()] or [t(uid, "key.stats_none")]
    embed = _base_embed(t(uid, "key.stats_title"), EMBED_COLOR)
    embed.description = t(uid, "key.stats_description", live=live, banned=banned, lines="\n".join(lines))
    await ctx.send(embed=embed)


@bot.command(name="keysetup")
@commands.guild_only()
@is_bot_admin()
async def keysetup_cmd(ctx):
    """Create the #key channel (with its guide) and a permanent invite link."""
    uid = ctx.author.id
    guild = ctx.guild
    channel = discord.utils.get(guild.text_channels, name=KEY_CHANNEL_NAME)
    try:
        if channel is None:
            overwrites = {guild.default_role: discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False, add_reactions=False)}
            channel = await guild.create_text_channel(KEY_CHANNEL_NAME, overwrites=overwrites, reason="Key system channel")
            embed = _base_embed(STRINGS['en']['keysetup.guide_title'], SUCCESS_COLOR)
            embed.description = STRINGS["en"]["keysetup.guide"]
            await channel.send(embed=embed)
        invite = await channel.create_invite(max_age=0, max_uses=0, unique=False, reason="Key system invite")
    except discord.HTTPException:
        return await ctx.send(t(uid, "keysetup.failed"))
    await ctx.send(t(uid, "keysetup.done", channel=channel.mention, name=channel.name, invite=invite.url))


_build_busy = set()      # guild ids with a plan being made or applied
_build_last = {}         # user id -> time of their last /aibuild
BUILD_COOLDOWN = 20


def _existing_structure(guild):
    kinds = {"text": "text", "voice": "voice", "stage_voice": "voice", "news": "announcement", "forum": "forum"}
    channels = {}
    for ch in guild.channels:
        kind = kinds.get(getattr(getattr(ch, "type", None), "name", "text"))
        if kind is None:   # categories and anything unknown
            continue
        category = getattr(ch, "category", None)
        channels[ch.id] = {"name": ch.name, "category": category.name if category else None, "type": kind}
    return {
        "roles": {r.name for r in guild.roles if not r.is_default() and not r.managed},
        "categories": {c.name: [ch.name for ch in c.channels] for c in guild.categories},
        "role_ids": {r.id: r.name for r in guild.roles if not r.is_default() and not r.managed},
        "category_ids": {c.id: c.name for c in guild.categories},
        "channel_ids": channels,
    }


_ai_undo = {}            # guild id -> what the last AI change did (see server_builder.apply_plan)
AIUNDO_TTL = 24 * 3600


def _plan_tree_text(uid, plan):
    icons = {"text": "#", "voice": "🔊", "announcement": "📢", "forum": "💬"}
    lines = []
    if plan["roles"]:
        lines.append(t(uid, "aibuild.roles_header", count=len(plan["roles"])))
        for r in plan["roles"]:
            lines.append(f"  @{r['name']}" + (f" · {', '.join(r['permissions'])}" if r["permissions"] else ""))
    for c in plan["categories"]:
        lock = f" 🔒 {', '.join(c['visible_to'])}" if c["visible_to"] else ""
        lines.append(f"📁 {c['name']}" + (f" ({t(uid, 'aibuild.existing')})" if c["exists"] else "") + lock)
        for ch in c["channels"]:
            flags = (" 🔒" if ch["visible_to"] else "") + (" 👁" if ch["read_only"] else "")
            lines.append(f"   {icons[ch['type']]} {ch['name']}{flags}")
    if plan["moves"]:
        lines.append(t(uid, "aibuild.moves_header", count=len(plan["moves"])))
        lines.extend(f"  ➡ {mv['name']} → {mv['to']}" for mv in plan["moves"])
    if plan["renames"]:
        lines.append(t(uid, "aibuild.renames_header", count=len(plan["renames"])))
        lines.extend(f"  ✏️ {rn['old']} → {rn['new']}" for rn in plan["renames"])
    if plan["category_order"]:
        lines.append(t(uid, "aibuild.order_header") + " " + " > ".join(plan["category_order"]))
    text = "\n".join(lines)
    return text if len(text) <= 3500 else text[:3500] + "\n…"


async def _aibuild_plan(guild, request):
    """Ask the AI for a plan and make it safe. None when the AI gave nothing usable."""
    existing = _existing_structure(guild)
    payload = json.dumps({
        "request": request[:1500],
        "existing_roles": [{"id": str(i), "name": n} for i, n in list(existing["role_ids"].items())[:80]],
        "existing_categories": [{"id": str(i), "name": n} for i, n in list(existing["category_ids"].items())[:40]],
        "existing_channels": [
            {"id": str(i), "name": v["name"], "type": v["type"], "category": v["category"]}
            for i, v in list(existing["channel_ids"].items())[:200]],
    }, ensure_ascii=False)
    result = await _gemini_generate(payload, server_builder.SYSTEM_PROMPT, json_schema=server_builder.PLAN_SCHEMA,
                                    parse=json.loads, purpose="serverbuild")
    if result is None:
        return None
    return server_builder.validate_plan(result[1], existing)


class BuildConfirmView(discord.ui.View):
    """The admin sees the plan first; nothing is created until they press the button."""

    def __init__(self, owner_id, plan):
        super().__init__(timeout=300)
        self.owner_id, self.plan = owner_id, plan
        self.confirm.label = f"{STRINGS['en']['aibuild.confirm']}"
        self.cancel.label = f"{STRINGS['en']['aibuild.cancel']}"

    async def _allowed(self, interaction):
        if interaction.user.id == self.owner_id and is_bot_admin_member(interaction.user):
            return True
        await interaction.response.send_message(t(interaction.user.id, "aibuild.not_yours"), ephemeral=True)
        return False

    @discord.ui.button(style=discord.ButtonStyle.success, emoji="✅", label="OK")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._allowed(interaction):
            return
        uid, guild = interaction.user.id, interaction.guild
        if guild.id in _build_busy:
            return await interaction.response.send_message(t(uid, "aibuild.busy"), ephemeral=True)
        problem = server_builder.capacity_problem(guild, self.plan)
        if problem:
            return await interaction.response.send_message(t(uid, "aibuild.too_many", what=problem), ephemeral=True)
        _build_busy.add(guild.id)
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=t(uid, "aibuild.running"), view=self)
        try:
            done = await server_builder.apply_plan(guild, self.plan, str(interaction.user))
        finally:
            _build_busy.discard(guild.id)
        failed = t(uid, "aibuild.failed_items", names=", ".join(done["failed"][:10])) if done["failed"] else ""
        counts = {k: done[k] for k in ("roles", "categories", "channels", "moved", "renamed")}
        undo = done["undo"]
        if any(undo["created"].values()) or undo["moved"] or undo["renamed"] or undo["category_order"]:
            _ai_undo[guild.id] = {"at": time.time(), **undo}
            _request_backup_soon("structure IA")
        await interaction.followup.send(t(uid, "aibuild.done", failed=failed, **counts))
        await _log_moderation(guild, interaction.user, t(0, "aibuild.log_title"), t(0, "aibuild.done", failed="", **counts), EMBED_COLOR)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="✖️", label="OK")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._allowed(interaction):
            return
        self.stop()
        await interaction.response.edit_message(content=t(interaction.user.id, "aibuild.cancelled"), embed=None, view=None)


async def _aibuild_start(guild, author, request, reply):
    """Plan with the AI and show the preview. `reply(**kwargs)` sends a message."""
    uid = author.id
    request = (request or "").strip()
    if len(request) < 8:
        return await reply(content=t(uid, "aibuild.usage"))
    if not GEMINI_AVAILABLE:
        return await reply(content=t(uid, "aibuild.not_configured"))
    perms = guild.me.guild_permissions
    if not (perms.manage_channels and perms.manage_roles):
        return await reply(content=t(uid, "aibuild.bot_perms"))
    now = time.time()
    if guild.id in _build_busy or now - _build_last.get(uid, 0) < BUILD_COOLDOWN:
        return await reply(content=t(uid, "aibuild.busy"))
    _build_last[uid] = now
    _build_busy.add(guild.id)
    try:
        planned = await _aibuild_plan(guild, request)
    finally:
        _build_busy.discard(guild.id)
    if planned is None:
        return await reply(content=t(uid, "aibuild.failed"))
    plan, warnings = planned
    if server_builder.is_empty(plan):
        return await reply(content=t(uid, "aibuild.nothing"))
    problem = server_builder.capacity_problem(guild, plan)
    if problem:
        return await reply(content=t(uid, "aibuild.too_many", what=problem))
    counts = server_builder.plan_counts(plan)
    embed = _base_embed(t(uid, "aibuild.preview_title"), EMBED_COLOR)
    embed.description = f"```\n{_plan_tree_text(uid, plan)}\n```"
    if warnings:
        embed.add_field(name=t(uid, "aibuild.notes"), value="\n".join(t(uid, k, **kw) for k, kw in warnings[:8])[:1000], inline=False)
    embed.set_footer(text=t(uid, "aibuild.preview_footer", **counts))
    await reply(embed=embed, view=BuildConfirmView(uid, plan))


class UndoConfirmView(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.confirm.label = f"{STRINGS['en']['aiundo.confirm']}"
        self.cancel.label = f"{STRINGS['en']['aiundo.cancel']}"

    async def _allowed(self, interaction):
        if interaction.user.id == self.owner_id and is_bot_admin_member(interaction.user):
            return True
        await interaction.response.send_message(t(interaction.user.id, "aibuild.not_yours"), ephemeral=True)
        return False

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="↩️", label="OK")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._allowed(interaction):
            return
        uid, guild = interaction.user.id, interaction.guild
        record = _ai_undo.get(guild.id)
        if not record or guild.id in _build_busy:
            return await interaction.response.send_message(t(uid, "aiundo.none"), ephemeral=True)
        _build_busy.add(guild.id)
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=t(uid, "aiundo.running"), view=self)
        try:
            out = await server_builder.revert(guild, record, str(interaction.user))
        finally:
            _build_busy.discard(guild.id)
        _ai_undo.pop(guild.id, None)
        kept = t(uid, "aiundo.kept", names=", ".join(out["kept"][:10])) if out["kept"] else ""
        failed = t(uid, "aiundo.failed", names=", ".join(out["failed"][:10])) if out["failed"] else ""
        summary = t(uid, "aiundo.done", moved=out["moved_back"], renamed=out["renamed_back"], deleted=out["deleted"], kept=kept, failed=failed)
        await interaction.followup.send(summary)
        await _log_moderation(guild, interaction.user, t(0, "aiundo.log_title"),
                              t(0, "aiundo.done", moved=out["moved_back"], renamed=out["renamed_back"], deleted=out["deleted"], kept="", failed=""),
                              EMBED_COLOR)
        _request_backup_soon("annulation IA")

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="✖️", label="OK")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._allowed(interaction):
            return
        self.stop()
        await interaction.response.edit_message(content=t(interaction.user.id, "aiundo.cancelled"), embed=None, view=None)


async def _aiundo_start(guild, author, reply):
    uid = author.id
    record = _ai_undo.get(guild.id)
    if not record or time.time() - record["at"] > AIUNDO_TTL:
        _ai_undo.pop(guild.id, None)
        return await reply(content=t(uid, "aiundo.none"))
    if guild.id in _build_busy:
        return await reply(content=t(uid, "aibuild.busy"))
    embed = _base_embed(t(uid, "aiundo.preview_title"), WARN_COLOR)
    embed.description = t(
        uid, "aiundo.preview", moved=len(record["moved"]), renamed=len(record["renamed"]),
        created=sum(len(v) for v in record["created"].values()),
        order=t(uid, "aiundo.order") if record["category_order"] else "")
    await reply(embed=embed, view=UndoConfirmView(uid))


@bot.command(name="aiundo")
@commands.guild_only()
@is_bot_admin()
async def aiundo_cmd(ctx):
    """Undo the last change made by the AI server builder (within 24 hours)"""
    await _aiundo_start(ctx.guild, ctx.author, lambda **kw: ctx.send(**kw))


@bot.tree.command(name="aiundo", description="Undo the last change made by the AI server builder (24 h)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def aiundo_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await _aiundo_start(interaction.guild, interaction.user, lambda **kw: interaction.followup.send(ephemeral=True, **kw))


@bot.command(name="aibuild", aliases=["aisetup"])
@commands.guild_only()
@is_bot_admin()
async def aibuild_cmd(ctx, *, request: str = ""):
    """Let the AI plan roles, categories and channels (you confirm before anything is created)"""
    async with ctx.typing():
        await _aibuild_start(ctx.guild, ctx.author, request, lambda **kw: ctx.send(**kw))


@bot.tree.command(name="aibuild", description="Let the AI plan roles, categories and channels (you confirm first)")
@app_commands.describe(request="What the server needs, in your own words")
@is_bot_admin_slash()
@app_commands.guild_only()
async def aibuild_slash(interaction: discord.Interaction, request: str):
    await interaction.response.defer(ephemeral=True)
    await _aibuild_start(interaction.guild, interaction.user, request,
                         lambda **kw: interaction.followup.send(ephemeral=True, **kw))


GREETING_IMAGE_CLEAR = ("", "-", "none", "off")


def _greet_set_image(part, value):
    value = (value or "").strip()
    if value.lower() in GREETING_IMAGE_CLEAR:
        part["image_url"] = None
        return True
    if not value.lower().startswith("https://") or len(value) > 300:
        return False
    part["image_url"] = value
    return True


def _greeting_panel_embed(uid, kind, guild):
    part = _greet_cfg(guild.id, kind)
    embed = discord.Embed(title=t(uid, f"greet.panel_title_{kind}"), color=GREETING_STYLE[kind]["color"])
    embed.add_field(name=t(uid, "greet.field_state"),
                    value=t(uid, "antiraid.enabled") if part["enabled"] else t(uid, "antiraid.disabled"), inline=True)
    channel = guild.get_channel(part["channel_id"]) if part["channel_id"] else None
    embed.add_field(name=t(uid, "greet.field_channel"),
                    value=channel.mention if channel else t(uid, "greet.system_channel"), inline=True)
    embed.add_field(name=t(uid, "greet.field_title"), value=part["title"][:256], inline=True)
    embed.add_field(name=t(uid, "greet.field_message"), value=part["message"][:1000], inline=False)
    embed.add_field(name=t(uid, "greet.field_image"), value=part.get("image_url") or t(uid, "payment.not_set"), inline=False)
    embed.set_footer(text=t(uid, "greet.panel_hint"))
    return embed


class GreetingEditModal(discord.ui.Modal):
    def __init__(self, panel):
        super().__init__(title=t(panel.uid, "greet.modal_title"))
        self.panel = panel
        part = _greet_cfg(panel.guild.id, panel.kind)
        self.title_input = discord.ui.TextInput(
            label=t(panel.uid, "greet.f_title"), default=part["title"], max_length=80, required=True)
        self.message_input = discord.ui.TextInput(
            label=t(panel.uid, "greet.f_message"), default=part["message"], style=discord.TextStyle.paragraph,
            max_length=1000, required=True)
        self.image_input = discord.ui.TextInput(
            label=t(panel.uid, "greet.f_image"), default=part.get("image_url") or "", placeholder="https://...",
            max_length=300, required=False)
        for item in (self.title_input, self.message_input, self.image_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        uid = self.panel.uid
        part = _greet_cfg(self.panel.guild.id, self.panel.kind)
        if not _greet_set_image(dict(part), self.image_input.value):
            return await interaction.response.send_message(t(uid, "greet.image_invalid"), ephemeral=True)
        part["title"] = self.title_input.value.strip() or part["title"]
        part["message"] = self.message_input.value.strip() or part["message"]
        _greet_set_image(part, self.image_input.value)
        _request_backup_soon("config")
        await self.panel.refresh(interaction)


class GreetingPanelView(discord.ui.View):
    """The control panel of one card (Welcome or Goodbye): switch, channel, edit, preview."""

    def __init__(self, kind, uid, guild):
        super().__init__(timeout=300)
        self.kind, self.uid, self.guild = kind, uid, guild
        self._sync()

    def _sync(self):
        on = _greet_cfg(self.guild.id, self.kind)["enabled"]
        self.toggle.label = t(self.uid, "greet.btn_off" if on else "greet.btn_on")
        self.toggle.style = discord.ButtonStyle.danger if on else discord.ButtonStyle.success
        self.edit.label = t(self.uid, "greet.btn_edit")
        self.test.label = t(self.uid, "greet.btn_test")
        self.channel_select.placeholder = t(self.uid, "greet.pick_channel")

    async def refresh(self, interaction):
        self._sync()
        await interaction.response.edit_message(embed=_greeting_panel_embed(self.uid, self.kind, self.guild), view=self)

    async def interaction_check(self, interaction):
        if interaction.user.id == self.uid and is_bot_admin_member(interaction.user):
            return True
        await interaction.response.send_message(t(interaction.user.id, "greet.not_yours"), ephemeral=True)
        return False

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], min_values=1, max_values=1, row=0)
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        _greet_cfg(self.guild.id, self.kind)["channel_id"] = select.values[0].id
        _request_backup_soon("config")
        await self.refresh(interaction)

    @discord.ui.button(style=discord.ButtonStyle.success, row=1)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        part = _greet_cfg(self.guild.id, self.kind)
        part["enabled"] = not part["enabled"]
        _request_backup_soon("config")
        await self.refresh(interaction)

    @discord.ui.button(emoji="✏️", style=discord.ButtonStyle.primary, row=1)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GreetingEditModal(self))

    @discord.ui.button(emoji="👁️", style=discord.ButtonStyle.secondary, row=1)
    async def test(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            content=t(self.uid, "greet.preview_note"),
            embed=_greeting_embed(self.kind, interaction.user, self.guild), ephemeral=True)


def _greet_say(uid, kind, key, **kw):
    return t(uid, key, what=t(uid, f"greet.{kind}.name"), **kw)


def _greet_switch(uid, guild_id, kind, enabled):
    part = _greet_cfg(guild_id, kind)
    if part["enabled"] == enabled:
        return _greet_say(uid, kind, "greet.already_on" if enabled else "greet.already_off")
    part["enabled"] = enabled
    _request_backup_soon("config")
    return _greet_say(uid, kind, "greet.enabled" if enabled else "greet.disabled")


def _greet_text(uid, guild_id, kind, field, value):
    part = _greet_cfg(guild_id, kind)
    if field == "image":
        if not _greet_set_image(part, value):
            return t(uid, "greet.image_invalid")
        _request_backup_soon("config")
        return _greet_say(uid, kind, "greet.image_set" if part["image_url"] else "greet.image_cleared")
    part[field] = value.strip()[:80 if field == "title" else 1000] or part[field]
    _request_backup_soon("config")
    return _greet_say(uid, kind, f"greet.{field}_set")


def _register_greeting_commands(kind):
    name = GREETING_COMMAND[kind]
    label = GREETING_STYLE[kind]["emoji"]

    @bot.group(name=name, aliases=["goodbye"] if kind == "leave" else [], invoke_without_command=True)
    @is_bot_admin()
    async def group(ctx):
        await ctx.send(embed=_greeting_panel_embed(ctx.author.id, kind, ctx.guild),
                       view=GreetingPanelView(kind, ctx.author.id, ctx.guild))

    @group.command(name="on")
    @is_bot_admin()
    async def p_on(ctx):
        await ctx.send(_greet_switch(ctx.author.id, ctx.guild.id, kind, True))

    @group.command(name="off")
    @is_bot_admin()
    async def p_off(ctx):
        await ctx.send(_greet_switch(ctx.author.id, ctx.guild.id, kind, False))

    @group.command(name="channel")
    @is_bot_admin()
    async def p_channel(ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        _greet_cfg(ctx.guild.id, kind)["channel_id"] = channel.id
        _request_backup_soon("config")
        await ctx.send(_greet_say(ctx.author.id, kind, "greet.channel_set", channel=channel.mention))

    @group.command(name="message", aliases=["setjoin"] if kind == "join" else ["setleave"])
    @is_bot_admin()
    async def p_message(ctx, *, text):
        await ctx.send(_greet_text(ctx.author.id, ctx.guild.id, kind, "message", text))

    @group.command(name="title")
    @is_bot_admin()
    async def p_title(ctx, *, text):
        await ctx.send(_greet_text(ctx.author.id, ctx.guild.id, kind, "title", text))

    @group.command(name="image")
    @is_bot_admin()
    async def p_image(ctx, url: str = "-"):
        await ctx.send(_greet_text(ctx.author.id, ctx.guild.id, kind, "image", url))

    @group.command(name="test")
    @is_bot_admin()
    async def p_test(ctx):
        await ctx.send(content=t(ctx.author.id, "greet.preview_note"), embed=_greeting_embed(kind, ctx.author, ctx.guild))

    slash = app_commands.Group(name=name, description=f"{label} Configure the {name} card (own switch, channel, title, message, image)")
    bot.tree.add_command(slash)

    @slash.command(name="setup", description="Open the control panel of this card")
    @is_bot_admin_slash()
    @app_commands.guild_only()
    async def s_setup(interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=_greeting_panel_embed(interaction.user.id, kind, interaction.guild),
            view=GreetingPanelView(kind, interaction.user.id, interaction.guild), ephemeral=True)

    @slash.command(name="on", description="Turn this card on")
    @is_bot_admin_slash()
    @app_commands.guild_only()
    async def s_on(interaction: discord.Interaction):
        await interaction.response.send_message(_greet_switch(interaction.user.id, interaction.guild.id, kind, True), ephemeral=True)

    @slash.command(name="off", description="Turn this card off")
    @is_bot_admin_slash()
    @app_commands.guild_only()
    async def s_off(interaction: discord.Interaction):
        await interaction.response.send_message(_greet_switch(interaction.user.id, interaction.guild.id, kind, False), ephemeral=True)

    @slash.command(name="channel", description="Channel where this card is posted")
    @app_commands.describe(channel="Channel (defaults to the current one)")
    @is_bot_admin_slash()
    @app_commands.guild_only()
    async def s_channel(interaction: discord.Interaction, channel: discord.TextChannel = None):
        channel = channel or interaction.channel
        _greet_cfg(interaction.guild.id, kind)["channel_id"] = channel.id
        _request_backup_soon("config")
        await interaction.response.send_message(
            _greet_say(interaction.user.id, kind, "greet.channel_set", channel=channel.mention), ephemeral=True)

    @slash.command(name="message", description="Message of the card ({mention} {name} {server} {count})")
    @app_commands.describe(text="The message (supports {mention} {name} {server} {count})")
    @is_bot_admin_slash()
    @app_commands.guild_only()
    async def s_message(interaction: discord.Interaction, text: str):
        await interaction.response.send_message(
            _greet_text(interaction.user.id, interaction.guild.id, kind, "message", text), ephemeral=True)

    @slash.command(name="title", description="Title of the card (supports {name} {server} {count})")
    @app_commands.describe(text="The title")
    @is_bot_admin_slash()
    @app_commands.guild_only()
    async def s_title(interaction: discord.Interaction, text: str):
        await interaction.response.send_message(
            _greet_text(interaction.user.id, interaction.guild.id, kind, "title", text), ephemeral=True)

    @slash.command(name="image", description="Banner image of the card (https link, - to remove)")
    @app_commands.describe(url="https:// link to an image, or - to remove it")
    @is_bot_admin_slash()
    @app_commands.guild_only()
    async def s_image(interaction: discord.Interaction, url: str):
        await interaction.response.send_message(
            _greet_text(interaction.user.id, interaction.guild.id, kind, "image", url), ephemeral=True)

    @slash.command(name="test", description="Preview this card with your own profile")
    @is_bot_admin_slash()
    @app_commands.guild_only()
    async def s_test(interaction: discord.Interaction):
        await interaction.response.send_message(
            content=t(interaction.user.id, "greet.preview_note"),
            embed=_greeting_embed(kind, interaction.user, interaction.guild), ephemeral=True)


for _greet_kind in ("join", "leave"):
    _register_greeting_commands(_greet_kind)


@bot.command(name="language", aliases=["lang"])
async def language_cmd(ctx, lang: str = None):
    """Set your preferred language (en/fr)"""
    uid = ctx.author.id
    if lang is None or lang.lower() not in ("en", "fr"):
        return await ctx.send(t(uid, "language.invalid"))
    user_lang[uid] = lang.lower()
    await ctx.send(t(uid, "language.set", lang=t(uid, f"language.{lang.lower()}")))


def _perm_embed(uid):
    embed = _base_embed(t(uid, "perm.title"), EMBED_COLOR)
    embed.description = t(uid, "perm.description")
    embed.add_field(name=t(uid, "perm.public_title"), value=t(uid, "perm.public_value"), inline=False)
    embed.add_field(name=t(uid, "perm.native_title"), value=t(uid, "perm.native_value"), inline=False)
    embed.add_field(name=t(uid, "perm.botadmin_title"), value=t(uid, "perm.botadmin_value"), inline=False)
    embed.add_field(name=t(uid, "perm.admin_title"), value=t(uid, "perm.admin_value"), inline=False)
    embed.add_field(name=t(uid, "perm.override_title"), value=t(uid, "perm.override_value"), inline=False)
    return embed


@bot.command(name="perm", aliases=["perms"])
async def perm_cmd(ctx):
    """Show the bot's permission hierarchy"""
    await ctx.send(embed=_perm_embed(ctx.author.id))


@bot.command(name="help")
async def help_cmd(ctx):
    """Interactive help menu"""
    view = HelpView(ctx.author)
    msg = await ctx.send(embed=view._home_embed(), view=view)
    view.message = msg


@bot.command(name="yslem")
async def about_cmd(ctx):
    """Interactive overview of the bot (AI, economy, moderation, admin)"""
    view = YslemAboutView(ctx.author)
    msg = await ctx.send(embed=view._home_embed(), view=view)
    view.message = msg


async def _delete_command_message(ctx):
    """Keep channels clean: delete the message that invoked a prefix
    command -- called on both the success path (on_command_completion)
    and the failure path (on_command_error, after any error reply has
    already been sent). Deleting always, regardless of outcome, is safe
    here specifically because it happens AFTER the error reply: an
    earlier version deleted eagerly in on_command (before checks/
    execution even ran), which meant a failing command's ctx.reply()
    could try to reply to an already-deleted message and crash with a
    real 400 Invalid Form Body from Discord. Sequencing the delete after
    the reply avoids that while still always cleaning up the message."""
    pending = _yslemm_synthetic_dispatch_ids.get(ctx.message.id, 0)
    if pending:
        # A natural-language message yslemm reconstructed into a real
        # command invocation (run_command / multi) -- it's the person's own
        # chat message, not a typed "!command", so it doesn't get
        # auto-deleted the way a real one would.
        if pending > 1:
            _yslemm_synthetic_dispatch_ids[ctx.message.id] = pending - 1
        else:
            _yslemm_synthetic_dispatch_ids.pop(ctx.message.id, None)
        return
    if ctx.guild is None:
        return
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        print(f"[WARN] Can't delete !{ctx.invoked_with} from {ctx.author} in #{ctx.channel} (guild {ctx.guild.id}) -- I'm missing Manage Messages there.")
        # A silent Forbidden here previously just looked like "nothing
        # happened" with zero feedback anywhere. Warn in-channel too (once
        # every 10 min per channel, so a busy channel missing the
        # permission doesn't get spammed on every single command) so this
        # is actually visible and actionable instead of only in Render logs.
        key = (ctx.guild.id, ctx.channel.id)
        now = datetime.now(timezone.utc)
        last_warned = _delete_perm_warned.get(key)
        if last_warned is None or (now - last_warned).total_seconds() > 600:
            _delete_perm_warned[key] = now
            try:
                await ctx.channel.send(t(ctx.author.id, "error.missing_manage_messages_delete"), delete_after=15)
            except discord.HTTPException:
                pass
    except discord.HTTPException as e:
        print(f"[WARN] Failed to delete !{ctx.invoked_with} from {ctx.author} in #{ctx.channel}: {e}")


@bot.event
async def on_command_completion(ctx):
    await _delete_command_message(ctx)


@bot.listen("on_command_completion")
async def _panel_on_command_completion(ctx):
    _panel_track("command", ctx.guild, ctx.author, f"!{ctx.command.qualified_name}")


@bot.listen("on_command_error")
async def _panel_on_command_error(ctx, error):
    if ctx.command is not None and not isinstance(error, commands.CommandNotFound):
        _panel_track("command_error", ctx.guild, ctx.author, f"!{ctx.command.qualified_name}")


@bot.listen("on_app_command_completion")
async def _panel_on_app_command_completion(interaction, command):
    _panel_track("slash", interaction.guild, interaction.user, f"/{command.qualified_name}")


@bot.listen("on_guild_join")
async def _panel_on_guild_join(guild):
    _panel_track("guild_join", guild, guild.owner, guild.name)


@bot.listen("on_guild_remove")
async def _panel_on_guild_remove(guild):
    _panel_track("guild_leave", guild, None, guild.name)


@bot.event
async def on_command_error(ctx, error):
    """Reply with the error first (while ctx.message still exists, so the
    reply reference is valid), then always delete the invoking message --
    a real command attempt that failed still gets cleaned up, it's just
    ordered after the reply so it can't break it. CommandNotFound is the
    one exception: it isn't a real command attempt (just some "!text" that
    doesn't match anything), so it's left alone entirely, same as before."""
    uid = ctx.author.id
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(t(uid, "error.no_permission"))
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send(t(uid, "error.bot_no_permission"))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(t(uid, "error.member_not_found"))
    elif isinstance(error, commands.RoleNotFound):
        await ctx.send(t(uid, "error.role_not_found"))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(t(uid, "error.missing_argument"))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(t(uid, "error.bad_argument"))
    elif isinstance(error, discord.Forbidden):
        await ctx.send(t(uid, "error.forbidden"))
    elif isinstance(error, commands.CheckFailure):
        if str(error) == "no_command_access_coin":
            await ctx.send(t(uid, "error.no_command_access_coin"))
        elif str(error) == "no_command_access":
            await ctx.send(t(uid, "error.no_command_access"))
        else:
            await ctx.send(t(uid, "error.not_bot_admin"))
    else:
        print(f"[ERROR] {ctx.command}: {error}")
    await _delete_command_message(ctx)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    uid = interaction.user.id
    command_name = interaction.command.qualified_name if interaction.command else "?"
    _panel_track("command_error", interaction.guild, interaction.user, f"/{command_name}")
    if isinstance(error, app_commands.MissingPermissions):
        msg = t(uid, "error.no_permission")
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = t(uid, "error.bot_no_permission")
    elif isinstance(error, app_commands.CheckFailure):
        if str(error) == "no_command_access_coin":
            msg = t(uid, "error.no_command_access_coin")
        elif str(error) == "no_command_access":
            msg = t(uid, "error.no_command_access")
        else:
            msg = t(uid, "error.not_bot_admin")
    else:
        print(f"[ERROR] slash {interaction.command}: {error}")
        msg = t(uid, "error.forbidden")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass


@bot.tree.command(name="ping", description="Show bot latency")
async def ping_slash(interaction: discord.Interaction):
    view = RefreshPingView(interaction.user)
    await interaction.response.send_message(embed=_ping_embed(interaction.user), view=view)
    view.message = await interaction.original_response()


@bot.tree.command(name="hello", description="Say hello")
async def hello_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    embed = _base_embed(t(uid, "hello.title"))
    embed.description = t(uid, "hello.description", mention=interaction.user.mention)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="info", description="Show server info")
@app_commands.guild_only()
async def info_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    guild = interaction.guild
    embed = _base_embed(guild.name)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name=t(uid, "info.members"), value=guild.member_count, inline=True)
    embed.add_field(name=t(uid, "info.channels"), value=len(guild.channels), inline=True)
    embed.add_field(name=t(uid, "info.roles"), value=len(guild.roles), inline=True)
    embed.add_field(name=t(uid, "info.owner"), value=guild.owner.mention if guild.owner else t(uid, "info.owner_unknown"), inline=True)
    embed.add_field(name=t(uid, "info.created"), value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.set_footer(text=f"ID: {guild.id}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="userinfo", description="Show info about a user")
@app_commands.describe(member="The member to look up (defaults to you)")
async def userinfo_slash(interaction: discord.Interaction, member: discord.Member = None):
    uid = interaction.user.id
    member = member or interaction.user
    embed = _base_embed(str(member), member.color if member.color.value else EMBED_COLOR)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=t(uid, "userinfo.id"), value=member.id, inline=True)
    embed.add_field(
        name=t(uid, "userinfo.joined"),
        value=member.joined_at.strftime("%d/%m/%Y") if member.joined_at else t(uid, "userinfo.unknown"),
        inline=True,
    )
    embed.add_field(name=t(uid, "userinfo.created"), value=member.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name=t(uid, "userinfo.top_role"), value=member.top_role.mention, inline=True)
    status_key = {
        discord.Status.online: "status.online",
        discord.Status.idle: "status.idle",
        discord.Status.dnd: "status.dnd",
        discord.Status.offline: "status.offline",
    }.get(member.status, "status.unknown")
    embed.add_field(name=t(uid, "userinfo.status"), value=t(uid, status_key), inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="avatar", description="Show an avatar in large size")
@app_commands.describe(member="Whose avatar to show (defaults to you)")
async def avatar_slash(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = _base_embed(t(interaction.user.id, "avatar.title", name=member.display_name), member.color if member.color.value else EMBED_COLOR)
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="servericon", description="Show the server icon")
@app_commands.guild_only()
async def servericon_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    if not interaction.guild.icon:
        return await interaction.response.send_message(t(uid, "servericon.no_icon"), ephemeral=True)
    embed = _base_embed(t(uid, "servericon.title", guild=interaction.guild.name))
    embed.set_image(url=interaction.guild.icon.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="roleinfo", description="Show info about a role")
@app_commands.describe(role="The role to look up")
@app_commands.guild_only()
async def roleinfo_slash(interaction: discord.Interaction, role: discord.Role):
    uid = interaction.user.id
    embed = _base_embed(t(uid, "roleinfo.title", role=role.name), role.color if role.color.value else EMBED_COLOR)
    embed.add_field(name=t(uid, "roleinfo.id"), value=role.id, inline=True)
    embed.add_field(name=t(uid, "roleinfo.members"), value=len(role.members), inline=True)
    embed.add_field(name=t(uid, "roleinfo.position"), value=role.position, inline=True)
    embed.add_field(name=t(uid, "roleinfo.mentionable"), value=t(uid, "yes") if role.mentionable else t(uid, "no"), inline=True)
    embed.add_field(name=t(uid, "roleinfo.hoisted"), value=t(uid, "yes") if role.hoist else t(uid, "no"), inline=True)
    embed.add_field(name=t(uid, "roleinfo.created"), value=role.created_at.strftime("%d/%m/%Y"), inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="afk", description="Set yourself as away")
@app_commands.describe(reason="Why you're away (optional)")
async def afk_slash(interaction: discord.Interaction, reason: str = None):
    uid = interaction.user.id
    reason = reason or t(uid, "default_reason")
    afk_status[uid] = {"reason": reason, "since": datetime.now(timezone.utc).isoformat()}
    embed = _base_embed(t(uid, "afk.set_title"), WARN_COLOR)
    embed.description = t(uid, "afk.set_description", mention=interaction.user.mention, reason=reason)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="remind", description="Schedule a reminder")
@app_commands.describe(minutes="How many minutes from now", message="What to remind you about")
async def remind_slash(interaction: discord.Interaction, minutes: float, message: str):
    uid = interaction.user.id
    if not message.strip():
        return await interaction.response.send_message(t(uid, "error.missing_argument"), ephemeral=True)
    if minutes <= 0 or minutes > 10080:
        return await interaction.response.send_message(t(uid, "remind.invalid"), ephemeral=True)
    embed = _base_embed(t(uid, "remind.scheduled_title"), EMBED_COLOR)
    embed.description = t(uid, "remind.scheduled_description", minutes=minutes, message=message)
    await interaction.response.send_message(embed=embed, ephemeral=True)

    await asyncio.sleep(minutes * 60)

    reminder_embed = _base_embed(t(uid, "remind.title"), WARN_COLOR)
    reminder_embed.description = message
    try:
        await interaction.user.send(embed=reminder_embed)
    except discord.Forbidden:
        # The interaction's webhook token expires after 15 min, so a long-delay
        # reminder can't rely on interaction.followup — send to the channel instead.
        try:
            await interaction.channel.send(content=interaction.user.mention, embed=reminder_embed)
        except discord.HTTPException:
            pass


@bot.tree.command(name="invite", description="Get the bot's invite link")
async def invite_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    url = discord.utils.oauth_url(
        bot.user.id,
        permissions=discord.Permissions(
            manage_roles=True, manage_channels=True, kick_members=True, ban_members=True,
            manage_messages=True, embed_links=True, read_message_history=True,
            send_messages=True, view_audit_log=True, moderate_members=True,
        ),
        scopes=("bot", "applications.commands"),
    )
    embed = _base_embed(t(uid, "invite.title"), EMBED_COLOR)
    embed.description = t(uid, "invite.description", url=url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="uptime", description="Show bot uptime")
async def uptime_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    embed = _base_embed(t(uid, "uptime.title"), EMBED_COLOR)
    embed.description = t(uid, "uptime.description", duration=_format_duration(time.time() - bot_start_time))
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="balance", description="Show a member's coin balance")
@app_commands.describe(member="Member to check (defaults to you)")
async def balance_slash(interaction: discord.Interaction, member: discord.Member = None):
    uid = interaction.user.id
    member = member or interaction.user
    amount = _get_balance(interaction.guild.id, member.id)
    embed = _base_embed(t(uid, "economy.balance_title", user=member.display_name), EMBED_COLOR)
    embed.description = t(uid, "economy.balance_amount", amount=amount)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="daily", description="Claim your daily coins")
async def daily_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    key = (interaction.guild.id, interaction.user.id)
    last = economy_last_daily.get(key)
    now = datetime.now(timezone.utc)
    if last and now - last < timedelta(hours=24):
        remaining = timedelta(hours=24) - (now - last)
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return await interaction.response.send_message(t(uid, "economy.daily_cooldown", hours=hours, minutes=minutes), ephemeral=True)
    amount = DAILY_COIN_AMOUNT
    economy_balances[key] = economy_balances.get(key, 0) + amount
    economy_last_daily[key] = now
    await interaction.response.send_message(t(uid, "economy.daily_claimed", amount=amount, total=economy_balances[key]), ephemeral=True)


@bot.tree.command(name="pay", description="Give some of your coins to another member")
@app_commands.describe(member="Member to pay", amount="Amount of coins to send")
async def pay_slash(interaction: discord.Interaction, member: discord.Member, amount: int):
    uid = interaction.user.id
    if member.id == interaction.user.id:
        return await interaction.response.send_message(t(uid, "economy.pay_self"), ephemeral=True)
    if member.bot:
        return await interaction.response.send_message(t(uid, "economy.pay_bot"), ephemeral=True)
    if amount <= 0:
        return await interaction.response.send_message(t(uid, "economy.pay_invalid"), ephemeral=True)
    if _get_balance(interaction.guild.id, interaction.user.id) < amount:
        return await interaction.response.send_message(t(uid, "economy.pay_insufficient"), ephemeral=True)
    sender_key = (interaction.guild.id, interaction.user.id)
    receiver_key = (interaction.guild.id, member.id)
    economy_balances[sender_key] = economy_balances.get(sender_key, 0) - amount
    economy_balances[receiver_key] = economy_balances.get(receiver_key, 0) + amount
    await interaction.response.send_message(t(uid, "economy.pay_success", amount=amount, member=member.mention), ephemeral=True)


@bot.tree.command(name="leaderboard", description="Show the top coin balances in this server")
async def leaderboard_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    entries = sorted(
        ((k[1], v) for k, v in economy_balances.items() if k[0] == interaction.guild.id and v > 0),
        key=lambda x: x[1], reverse=True,
    )[:10]
    embed = _base_embed(t(uid, "economy.leaderboard_title"), EMBED_COLOR)
    if not entries:
        embed.description = t(uid, "economy.leaderboard_empty")
    else:
        lines = []
        for i, (user_id, amount) in enumerate(entries, start=1):
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"<@{user_id}>"
            lines.append(f"**{i}.** {name} — {amount}")
        embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="addcoins", description="Add coins to a member's balance (bot-admin only)")
@app_commands.describe(member="Member to credit", amount="Amount of coins to add")
@is_bot_admin_slash()
@app_commands.guild_only()
async def addcoins_slash(interaction: discord.Interaction, member: discord.Member, amount: int):
    uid = interaction.user.id
    key = (interaction.guild.id, member.id)
    economy_balances[key] = economy_balances.get(key, 0) + amount
    await interaction.response.send_message(t(uid, "economy.admin_added", amount=amount, member=member.mention), ephemeral=True)


@bot.tree.command(name="removecoins", description="Remove coins from a member's balance (bot-admin only)")
@app_commands.describe(member="Member to debit", amount="Amount of coins to remove")
@is_bot_admin_slash()
@app_commands.guild_only()
async def removecoins_slash(interaction: discord.Interaction, member: discord.Member, amount: int):
    uid = interaction.user.id
    key = (interaction.guild.id, member.id)
    economy_balances[key] = max(0, economy_balances.get(key, 0) - amount)
    await interaction.response.send_message(t(uid, "economy.admin_removed", amount=amount, member=member.mention), ephemeral=True)


@bot.tree.command(name="eightball", description="Ask the magic 8-ball")
@app_commands.describe(question="Your question")
async def eightball_slash(interaction: discord.Interaction, question: str):
    uid = interaction.user.id
    responses = EIGHTBALL.get(lang_of(uid), EIGHTBALL[DEFAULT_LANG])
    embed = _base_embed(t(uid, "eightball.title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "eightball.question"), value=question, inline=False)
    embed.add_field(name=t(uid, "eightball.answer"), value=random.choice(responses), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="coinflip", description="Flip a coin")
async def coinflip_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    result = random.choice([t(uid, "coinflip.heads"), t(uid, "coinflip.tails")])
    embed = _base_embed(t(uid, "coinflip.title"), EMBED_COLOR)
    embed.description = t(uid, "coinflip.result", result=result)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="dice", description="Roll a die")
@app_commands.describe(faces="Number of sides (default 6)")
async def dice_slash(interaction: discord.Interaction, faces: int = 6):
    uid = interaction.user.id
    faces = max(2, min(faces, 1000))
    result = random.randint(1, faces)
    embed = _base_embed(t(uid, "dice.title"), EMBED_COLOR)
    embed.description = t(uid, "dice.result", faces=faces, result=result)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="poll", description="Create a button-based poll")
@app_commands.describe(question="The question to ask", channel="Channel to post the poll in (defaults to the current channel)")
async def poll_slash(interaction: discord.Interaction, question: str, channel: discord.TextChannel = None):
    uid = interaction.user.id
    target = channel or interaction.channel
    view = PollView(question, interaction.user)
    try:
        msg = await target.send(embed=view._embed(), view=view)
    except discord.Forbidden:
        return await interaction.response.send_message(t(uid, "error.bot_no_permission"), ephemeral=True)
    view.message = msg
    if target == interaction.channel:
        await interaction.response.send_message(t(uid, "poll.posted"), ephemeral=True)
    else:
        await interaction.response.send_message(t(uid, "poll.posted_in", channel=target.mention), ephemeral=True)


@bot.tree.command(name="say", description="Make the bot repeat a message")
@app_commands.describe(message="What the bot should say", channel="Channel to post in (defaults to the current channel)")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True)
async def say_slash(interaction: discord.Interaction, message: str, channel: discord.TextChannel = None):
    uid = interaction.user.id
    target = channel or interaction.channel
    try:
        await target.send(
            message,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
    except discord.Forbidden:
        return await interaction.response.send_message(t(uid, "error.bot_no_permission"), ephemeral=True)
    if target == interaction.channel:
        await interaction.response.send_message(t(uid, "say.sent"), ephemeral=True)
    else:
        await interaction.response.send_message(t(uid, "say.sent_in", channel=target.mention), ephemeral=True)


@bot.tree.command(name="yslemsay", description="Post a message as Yslem via webhook (no bot tag)")
@app_commands.describe(message="What Yslem should say", channel="Channel to post in (defaults to the current channel)")
@is_bot_admin_slash()
@app_commands.checks.bot_has_permissions(manage_webhooks=True)
@app_commands.guild_only()
async def yslemsay_slash(interaction: discord.Interaction, message: str, channel: discord.TextChannel = None):
    uid = interaction.user.id
    target = channel or interaction.channel
    try:
        webhook = await _get_or_create_yslem_webhook(target)
        await webhook.send(
            message,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        if target == interaction.channel:
            await interaction.response.send_message(t(uid, "yslemsay.sent"), ephemeral=True)
        else:
            await interaction.response.send_message(t(uid, "yslemsay.sent_in", channel=target.mention), ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message(t(uid, "error.bot_no_permission"), ephemeral=True)


@bot.tree.command(name="clear", description="Delete recent messages")
@app_commands.describe(amount="How many messages to delete (max 500, default 5)")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True)
@app_commands.guild_only()
async def clear_slash(interaction: discord.Interaction, amount: int = 5):
    uid = interaction.user.id
    amount = max(1, min(amount, 500))
    deleted = await interaction.channel.purge(limit=amount)
    embed = _base_embed(t(uid, "clear.title"), SUCCESS_COLOR)
    embed.description = t(uid, "clear.description", count=len(deleted))
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="kick", description="Kick a member (confirmation required)")
@app_commands.describe(member="Member to kick", reason="Why are you kicking them")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.checks.bot_has_permissions(kick_members=True)
@app_commands.guild_only()
async def kick_slash(interaction: discord.Interaction, member: discord.Member, reason: str):
    uid = interaction.user.id
    if not reason.strip():
        return await interaction.response.send_message(t(uid, "error.missing_argument"), ephemeral=True)
    err = _kickban_error_key(interaction.user, member, interaction.guild, "kick.self", "kick.owner", "kick.hierarchy", "kick.bot_hierarchy")
    if err:
        return await interaction.response.send_message(t(uid, err), ephemeral=True)

    embed = _base_embed(t(uid, "kick.confirm_title"), WARN_COLOR)
    embed.description = t(uid, "kick.confirm_description", member=member, reason=reason)
    view = ConfirmView(interaction.user)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    view.message = msg
    await view.wait()

    if view.value is None:
        embed.description += t(uid, "confirm.expired")
        return await msg.edit(embed=embed)
    if view.value is False:
        embed.title = t(uid, "kick.cancelled_title")
        embed.color = EMBED_COLOR
        return await msg.edit(embed=embed)

    await member.kick(reason=reason)
    embed.title = t(uid, "kick.success_title")
    embed.color = SUCCESS_COLOR
    embed.description = t(uid, "kick.success_description", member=member, reason=reason)
    _footer(embed, interaction.user)
    await msg.edit(embed=embed)
    await _log_moderation(interaction.guild, interaction.user, embed.title, embed.description, SUCCESS_COLOR)


@bot.tree.command(name="ban", description="Ban a member (confirmation required)")
@app_commands.describe(member="Member to ban", reason="Why are you banning them")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
@app_commands.guild_only()
async def ban_slash(interaction: discord.Interaction, member: discord.Member, reason: str):
    uid = interaction.user.id
    if not reason.strip():
        return await interaction.response.send_message(t(uid, "error.missing_argument"), ephemeral=True)
    err = _kickban_error_key(interaction.user, member, interaction.guild, "ban.self", "ban.owner", "ban.hierarchy", "ban.bot_hierarchy")
    if err:
        return await interaction.response.send_message(t(uid, err), ephemeral=True)

    embed = _base_embed(t(uid, "ban.confirm_title"), WARN_COLOR)
    embed.description = t(uid, "ban.confirm_description", member=member, reason=reason)
    view = ConfirmView(interaction.user)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    view.message = msg
    await view.wait()

    if view.value is None:
        embed.description += t(uid, "confirm.expired")
        return await msg.edit(embed=embed)
    if view.value is False:
        embed.title = t(uid, "ban.cancelled_title")
        embed.color = EMBED_COLOR
        return await msg.edit(embed=embed)

    await member.ban(reason=reason)
    embed.title = t(uid, "ban.success_title")
    embed.color = ERROR_COLOR
    embed.description = t(uid, "ban.success_description", member=member, reason=reason)
    _footer(embed, interaction.user)
    await msg.edit(embed=embed)
    await _log_moderation(interaction.guild, interaction.user, embed.title, embed.description, ERROR_COLOR)


@bot.tree.command(name="timeout", description="Timeout a member for a set duration")
@app_commands.describe(member="Member to timeout", minutes="Duration in minutes (max 40320 / 28 days)", reason="Why are you timing them out")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
@app_commands.guild_only()
async def timeout_slash(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str):
    uid = interaction.user.id
    if not reason.strip():
        return await interaction.response.send_message(t(uid, "error.missing_argument"), ephemeral=True)
    err = _kickban_error_key(interaction.user, member, interaction.guild, "timeout.self", "timeout.owner", "timeout.hierarchy", "timeout.bot_hierarchy")
    if err:
        return await interaction.response.send_message(t(uid, err), ephemeral=True)
    minutes = max(1, min(minutes, 40320))
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    embed = _base_embed(t(uid, "timeout.success_title"), WARN_COLOR)
    embed.description = t(uid, "timeout.success_description", member=member, minutes=minutes, reason=reason)
    _footer(embed, interaction.user)
    await interaction.response.send_message(embed=embed)
    await _log_moderation(interaction.guild, interaction.user, embed.title, embed.description, WARN_COLOR)


@bot.tree.command(name="untimeout", description="Remove an active timeout from a member")
@app_commands.describe(member="Member whose timeout should be removed")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
@app_commands.guild_only()
async def untimeout_slash(interaction: discord.Interaction, member: discord.Member):
    uid = interaction.user.id
    await member.timeout(None, reason=f"Timeout removed by {interaction.user}")
    embed = _base_embed(t(uid, "untimeout.success_title"), SUCCESS_COLOR)
    embed.description = t(uid, "untimeout.success_description", member=member)
    _footer(embed, interaction.user)
    await interaction.response.send_message(embed=embed)
    await _log_moderation(interaction.guild, interaction.user, embed.title, embed.description, SUCCESS_COLOR)


@bot.tree.command(name="ticketsetup", description="Post the ticket creation panel")
@app_commands.describe(channel="Channel to post the panel in (defaults to the current channel)")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
async def ticketsetup_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    uid = interaction.user.id
    target = channel or interaction.channel
    await interaction.response.defer(ephemeral=True)
    try:
        summary = await _post_ticket_panel(interaction.user, interaction.guild, target)
    except discord.Forbidden:
        return await interaction.followup.send(t(uid, "error.bot_no_permission"), ephemeral=True)
    await interaction.followup.send(summary, ephemeral=True)


@bot.tree.command(name="closetickets", description="Close all open ticket channels at once")
@is_bot_admin_slash()
@app_commands.guild_only()
async def closetickets_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _ticket_cfg(interaction.guild.id)
    category = discord.utils.get(interaction.guild.categories, name=cfg["category_name"])
    targets = [c for c in (category.text_channels if category else []) if (interaction.guild.id, c.id) in open_tickets]
    if not targets:
        return await interaction.response.send_message(t(uid, "ticket.no_tickets"), ephemeral=True)
    await interaction.response.send_message(t(uid, "ticket.bulk_closing", count=len(targets)), ephemeral=True)
    await asyncio.gather(*(_close_ticket_channel(channel, closer=interaction.user) for channel in targets))


ticket_slash_group = app_commands.Group(name="ticket", description="Ticket system status and configuration")
bot.tree.add_command(ticket_slash_group)

ticket_config_slash_group = app_commands.Group(name="config", description="Configure the ticket system", parent=ticket_slash_group)


@ticket_slash_group.command(name="status", description="Show the ticket system configuration")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_status_slash(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_ticket_config_embed(interaction.user.id, interaction.guild), ephemeral=True)


@ticket_slash_group.command(name="reset", description="Wipe this server's entire ticket configuration back to defaults")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_reset_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    ticket_settings.pop(interaction.guild.id, None)
    await interaction.response.send_message(t(uid, "ticket.config_reset"), ephemeral=True)
    await interaction.followup.send(embed=_ticket_config_embed(uid, interaction.guild), ephemeral=True)


@ticket_config_slash_group.command(name="category", description="Set the Discord category tickets are created under")
@app_commands.describe(name="Category name")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_category_slash(interaction: discord.Interaction, name: str):
    uid = interaction.user.id
    name = name.strip()[:100]
    _ticket_cfg(interaction.guild.id)["category_name"] = name
    await interaction.response.send_message(t(uid, "ticket.category_set", name=name), ephemeral=True)


@ticket_config_slash_group.command(name="logchannel", description="Set (or clear) the ticket log channel")
@app_commands.describe(channel="Channel for ticket close logs (omit to clear)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_logchannel_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    uid = interaction.user.id
    _ticket_cfg(interaction.guild.id)["log_channel_id"] = channel.id if channel else None
    if channel:
        await interaction.response.send_message(t(uid, "ticket.logchannel_set", channel=channel.mention), ephemeral=True)
    else:
        await interaction.response.send_message(t(uid, "ticket.logchannel_cleared"), ephemeral=True)


@ticket_config_slash_group.command(name="maxopen", description="Set the max number of open tickets per member")
@app_commands.describe(count="Max open tickets per member (1-20)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_maxopen_slash(interaction: discord.Interaction, count: int):
    uid = interaction.user.id
    count = max(1, min(count, 20))
    _ticket_cfg(interaction.guild.id)["max_open_per_user"] = count
    await interaction.response.send_message(t(uid, "ticket.maxopen_set", count=count), ephemeral=True)


@ticket_config_slash_group.command(name="inactivity", description="Configure inactivity warning/auto-close in hours (0 = disabled)")
@app_commands.describe(warn_hours="Hours idle before a warning (0 = never)", close_hours="Hours idle before auto-close (0 = never)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_inactivity_slash(interaction: discord.Interaction, warn_hours: float, close_hours: float):
    uid = interaction.user.id
    warn_hours = max(0.0, min(warn_hours, 720))
    close_hours = max(0.0, min(close_hours, 720))
    cfg = _ticket_cfg(interaction.guild.id)
    cfg["warn_hours"] = warn_hours
    cfg["close_hours"] = close_hours
    await interaction.response.send_message(t(uid, "ticket.inactivity_set", warn=warn_hours, close=close_hours), ephemeral=True)


@ticket_config_slash_group.command(name="leaveaction", description="Set what happens to a ticket when its opener leaves the server")
@app_commands.describe(action="What to do when the ticket opener leaves")
@app_commands.choices(action=[
    app_commands.Choice(name="notify", value="notify"),
    app_commands.Choice(name="close", value="close"),
])
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_leaveaction_slash(interaction: discord.Interaction, action: app_commands.Choice[str]):
    uid = interaction.user.id
    _ticket_cfg(interaction.guild.id)["leave_action"] = action.value
    await interaction.response.send_message(t(uid, "ticket.leaveaction_set", action=action.value), ephemeral=True)


@ticket_config_slash_group.command(name="mute", description="Mute the opener when their ticket auto-closes for inactivity")
@app_commands.describe(action="Enable or disable the mute", minutes="Mute duration in minutes (default 10080 = 1 week)")
@app_commands.choices(action=[
    app_commands.Choice(name="on", value="on"),
    app_commands.Choice(name="off", value="off"),
])
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_mute_slash(interaction: discord.Interaction, action: app_commands.Choice[str], minutes: int = 10080):
    uid = interaction.user.id
    cfg = _ticket_cfg(interaction.guild.id)
    cfg["mute_on_close"] = action.value == "on"
    if action.value == "on":
        cfg["mute_minutes"] = max(1, min(minutes, 40320))
        await interaction.response.send_message(
            t(uid, "ticket.mute_set_on", duration=_format_duration(cfg["mute_minutes"] * 60)), ephemeral=True
        )
    else:
        await interaction.response.send_message(t(uid, "ticket.mute_set_off"), ephemeral=True)


@ticket_config_slash_group.command(name="addtype", description="Add a ticket category (shown in the panel's selector)")
@app_commands.describe(name="Category name")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_addtype_slash(interaction: discord.Interaction, name: str):
    uid = interaction.user.id
    name = name.strip()[:100]
    cfg = _ticket_cfg(interaction.guild.id)
    if name in cfg["categories"]:
        return await interaction.response.send_message(t(uid, "ticket.type_exists", name=name), ephemeral=True)
    if len(cfg["categories"]) >= 25:
        return await interaction.response.send_message(t(uid, "ticket.types_full"), ephemeral=True)
    cfg["categories"].append(name)
    await interaction.response.send_message(t(uid, "ticket.type_added", name=name), ephemeral=True)


@ticket_config_slash_group.command(name="removetype", description="Remove a ticket category")
@app_commands.describe(name="Category name to remove")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_removetype_slash(interaction: discord.Interaction, name: str):
    uid = interaction.user.id
    name = name.strip()
    cfg = _ticket_cfg(interaction.guild.id)
    if name not in cfg["categories"]:
        return await interaction.response.send_message(t(uid, "ticket.type_not_found", name=name), ephemeral=True)
    if len(cfg["categories"]) <= 1:
        return await interaction.response.send_message(t(uid, "ticket.type_last_one"), ephemeral=True)
    cfg["categories"].remove(name)
    await interaction.response.send_message(t(uid, "ticket.type_removed", name=name), ephemeral=True)


@ticket_config_slash_group.command(name="addstaffrole", description="Give a role automatic access to all tickets")
@app_commands.describe(role="Role to grant ticket access to")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_addstaffrole_slash(interaction: discord.Interaction, role: discord.Role):
    uid = interaction.user.id
    _ticket_cfg(interaction.guild.id)["staff_role_ids"].add(role.id)
    await interaction.response.send_message(t(uid, "ticket.staffrole_added", role=role.mention), ephemeral=True)


@ticket_config_slash_group.command(name="removestaffrole", description="Revoke a role's automatic ticket access")
@app_commands.describe(role="Role to revoke ticket access from")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_removestaffrole_slash(interaction: discord.Interaction, role: discord.Role):
    uid = interaction.user.id
    _ticket_cfg(interaction.guild.id)["staff_role_ids"].discard(role.id)
    await interaction.response.send_message(t(uid, "ticket.staffrole_removed", role=role.mention), ephemeral=True)


@ticket_config_slash_group.command(name="resetstaffroles", description="Clear all ticket staff roles and replace them with the given ones")
@app_commands.describe(role1="New staff role", role2="Another staff role (optional)", role3="Another staff role (optional)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def ticket_config_resetstaffroles_slash(
    interaction: discord.Interaction,
    role1: discord.Role,
    role2: Optional[discord.Role] = None,
    role3: Optional[discord.Role] = None,
):
    uid = interaction.user.id
    roles = [r for r in (role1, role2, role3) if r is not None]
    cfg = _ticket_cfg(interaction.guild.id)
    cfg["staff_role_ids"] = {role.id for role in roles}
    roles_value = ", ".join(role.mention for role in roles) or t(uid, "ticket.not_set")
    await interaction.response.send_message(t(uid, "ticket.staffroles_reset", roles=roles_value), ephemeral=True)


@ticket_slash_group.command(name="claim", description="Take this ticket in charge")
@app_commands.guild_only()
async def ticket_claim_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(await _tk_claim(interaction.user, interaction.channel), ephemeral=True)


@ticket_slash_group.command(name="unclaim", description="Release this ticket so another staff member can take it")
@app_commands.guild_only()
async def ticket_unclaim_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(await _tk_claim(interaction.user, interaction.channel, release=True), ephemeral=True)


@ticket_slash_group.command(name="add", description="Let another member see and write in this ticket")
@app_commands.describe(member="Member to add")
@app_commands.guild_only()
async def ticket_add_slash(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(await _tk_add(interaction.user, interaction.channel, member), ephemeral=True)


@ticket_slash_group.command(name="remove", description="Take a member you added back out of this ticket")
@app_commands.describe(member="Member to remove")
@app_commands.guild_only()
async def ticket_remove_slash(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(await _tk_remove(interaction.user, interaction.channel, member), ephemeral=True)


@ticket_slash_group.command(name="rename", description="Rename this ticket's channel")
@app_commands.describe(name="New name (the ticket number is kept)")
@app_commands.guild_only()
async def ticket_rename_slash(interaction: discord.Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(await _tk_rename(interaction.user, interaction.channel, name), ephemeral=True)


@ticket_slash_group.command(name="transcript", description="Get a text copy of this ticket's conversation")
@app_commands.guild_only()
async def ticket_transcript_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    text, file = await _tk_transcript(interaction.user, interaction.channel)
    if file:
        await interaction.followup.send(text, file=file, ephemeral=True)
    else:
        await interaction.followup.send(text, ephemeral=True)


@ticket_slash_group.command(name="list", description="List the open tickets of this server")
@app_commands.guild_only()
async def ticket_list_slash(interaction: discord.Interaction):
    if not _is_ticket_staff(interaction.user):
        return await interaction.response.send_message(t(interaction.user.id, "ticket.staff_only"), ephemeral=True)
    await interaction.response.send_message(embed=_tk_list_embed(interaction.user.id, interaction.guild), ephemeral=True)


@ticket_slash_group.command(name="close", description="Close this ticket (a transcript is sent to the log channel and the opener)")
@app_commands.describe(reason="Why it is being closed (optional)")
@app_commands.guild_only()
async def ticket_close_slash(interaction: discord.Interaction, reason: str = ""):
    await interaction.response.defer(ephemeral=True)
    error = await _tk_close(interaction.user, interaction.channel, reason.strip())
    await interaction.followup.send(error or t(interaction.user.id, "ticket.done"), ephemeral=True)


@bot.tree.command(name="payinfo", description="Payment info, the same in every server -- set yours or show what applies here")
@app_commands.describe(
    paypal="PayPal email or link ('-' removes it)", ltc="Litecoin address ('-' removes it)",
    btc="Bitcoin address ('-' removes it)", roblox="Roblox username ('-' removes it)",
    scope="Where to save: me (follows you everywhere), server (default here), everywhere (bot owner)")
@app_commands.choices(scope=[
    app_commands.Choice(name="me", value="me"),
    app_commands.Choice(name="server", value="server"),
    app_commands.Choice(name="everywhere", value="everywhere"),
])
@app_commands.guild_only()
async def payinfo_slash(
    interaction: discord.Interaction,
    paypal: Optional[str] = None, ltc: Optional[str] = None, btc: Optional[str] = None, roblox: Optional[str] = None,
    scope: Optional[app_commands.Choice[str]] = None,
):
    await interaction.response.defer(ephemeral=True)
    values = {"paypal": paypal, "ltc": ltc, "btc": btc, "roblox": roblox}
    text, embed, public = await _payinfo_run(
        interaction.user, interaction.guild, interaction.channel, values, scope.value if scope else "me")
    if public and embed is not None:
        await interaction.channel.send(embed=embed)
        await interaction.followup.send(text or t(interaction.user.id, "ticket.done"), ephemeral=True)
    else:
        await interaction.followup.send(content=text, embed=embed, ephemeral=True) if embed else \
            await interaction.followup.send(text or t(interaction.user.id, "payinfo.nothing_set"), ephemeral=True)


@bot.tree.command(name="staffapplysetup", description="Post the staff-application panel")
@app_commands.describe(channel="Channel to post the panel in (defaults to the current channel)")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
async def staffapplysetup_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    uid = interaction.user.id
    target = channel or interaction.channel
    embed = _base_embed(t(uid, "staffapp.panel_title"), EMBED_COLOR)
    embed.description = t(uid, "staffapp.panel_description")
    view = StaffApplyPanelView()
    view.children[0].label = t(uid, "staffapp.apply_button")
    try:
        await target.send(embed=embed, view=view)
    except discord.Forbidden:
        return await interaction.response.send_message(t(uid, "error.bot_no_permission"), ephemeral=True)
    if target == interaction.channel:
        await interaction.response.send_message(t(uid, "staffapp.panel_posted"), ephemeral=True)
    else:
        await interaction.response.send_message(t(uid, "staffapp.panel_posted_in", channel=target.mention), ephemeral=True)


@bot.tree.command(name="closeapplications", description="Close all open staff-application channels at once")
@is_bot_admin_slash()
@app_commands.guild_only()
async def closeapplications_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _staffapp_cfg(interaction.guild.id)
    category = discord.utils.get(interaction.guild.categories, name=cfg["category_name"])
    targets = list(category.text_channels) if category else []
    if not targets:
        return await interaction.response.send_message(t(uid, "staffapp.no_applications"), ephemeral=True)
    await interaction.response.send_message(t(uid, "staffapp.bulk_closing", count=len(targets)), ephemeral=True)
    await asyncio.gather(*(_close_staff_application_channel(channel, closer=interaction.user) for channel in targets))


staffapp_slash_group = app_commands.Group(name="staffapp", description="Staff-application system status and configuration")
bot.tree.add_command(staffapp_slash_group)

staffapp_config_slash_group = app_commands.Group(name="config", description="Configure the staff-application system", parent=staffapp_slash_group)


@staffapp_slash_group.command(name="status", description="Show the staff-application configuration")
@is_bot_admin_slash()
@app_commands.guild_only()
async def staffapp_status_slash(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_staffapp_config_embed(interaction.user.id, interaction.guild), ephemeral=True)


@staffapp_slash_group.command(name="reset", description="Wipe this server's staff-application configuration back to defaults")
@is_bot_admin_slash()
@app_commands.guild_only()
async def staffapp_reset_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    staffapp_settings.pop(interaction.guild.id, None)
    await interaction.response.send_message(t(uid, "staffapp.config_reset"), ephemeral=True)
    await interaction.followup.send(embed=_staffapp_config_embed(uid, interaction.guild), ephemeral=True)


@staffapp_config_slash_group.command(name="category", description="Set the Discord category applications are created under")
@app_commands.describe(name="Category name")
@is_bot_admin_slash()
@app_commands.guild_only()
async def staffapp_config_category_slash(interaction: discord.Interaction, name: str):
    uid = interaction.user.id
    name = name.strip()[:100]
    _staffapp_cfg(interaction.guild.id)["category_name"] = name
    await interaction.response.send_message(t(uid, "staffapp.category_set", name=name), ephemeral=True)


@staffapp_config_slash_group.command(name="logchannel", description="Set (or clear) the staff-application log channel")
@app_commands.describe(channel="Channel for decision/close logs (omit to clear)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def staffapp_config_logchannel_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    uid = interaction.user.id
    _staffapp_cfg(interaction.guild.id)["log_channel_id"] = channel.id if channel else None
    if channel:
        await interaction.response.send_message(t(uid, "staffapp.logchannel_set", channel=channel.mention), ephemeral=True)
    else:
        await interaction.response.send_message(t(uid, "staffapp.logchannel_cleared"), ephemeral=True)


@staffapp_config_slash_group.command(name="addrecruiter", description="Give a role access to review staff applications")
@app_commands.describe(role="Role to grant recruiter access to")
@is_bot_admin_slash()
@app_commands.guild_only()
async def staffapp_config_addrecruiter_slash(interaction: discord.Interaction, role: discord.Role):
    uid = interaction.user.id
    _staffapp_cfg(interaction.guild.id)["recruiter_role_ids"].add(role.id)
    await interaction.response.send_message(t(uid, "staffapp.recruiter_added", role=role.mention), ephemeral=True)


@staffapp_config_slash_group.command(name="removerecruiter", description="Revoke a role's recruiter access")
@app_commands.describe(role="Role to revoke recruiter access from")
@is_bot_admin_slash()
@app_commands.guild_only()
async def staffapp_config_removerecruiter_slash(interaction: discord.Interaction, role: discord.Role):
    uid = interaction.user.id
    _staffapp_cfg(interaction.guild.id)["recruiter_role_ids"].discard(role.id)
    await interaction.response.send_message(t(uid, "staffapp.recruiter_removed", role=role.mention), ephemeral=True)


@staffapp_config_slash_group.command(name="resetrecruiters", description="Clear all recruiter roles and replace them with the given ones")
@app_commands.describe(role1="New recruiter role", role2="Another recruiter role (optional)", role3="Another recruiter role (optional)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def staffapp_config_resetrecruiters_slash(
    interaction: discord.Interaction,
    role1: discord.Role,
    role2: Optional[discord.Role] = None,
    role3: Optional[discord.Role] = None,
):
    uid = interaction.user.id
    roles = [r for r in (role1, role2, role3) if r is not None]
    cfg = _staffapp_cfg(interaction.guild.id)
    cfg["recruiter_role_ids"] = {role.id for role in roles}
    roles_value = ", ".join(role.mention for role in roles) or t(uid, "ticket.not_set")
    await interaction.response.send_message(t(uid, "staffapp.recruiters_reset", roles=roles_value), ephemeral=True)


@staffapp_config_slash_group.command(name="cooldown", description="Set how many days a rejected applicant must wait before reapplying")
@app_commands.describe(days="Cooldown in days (0 = no cooldown)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def staffapp_config_cooldown_slash(interaction: discord.Interaction, days: float):
    uid = interaction.user.id
    days = max(0.0, min(days, 365))
    _staffapp_cfg(interaction.guild.id)["cooldown_days"] = days
    await interaction.response.send_message(t(uid, "staffapp.cooldown_set", days=f"{days:g}"), ephemeral=True)


@staffapp_config_slash_group.command(name="role", description="Auto-grant a role when an application is accepted")
@app_commands.describe(role="Role to grant on acceptance (omit to clear)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def staffapp_config_role_slash(interaction: discord.Interaction, role: discord.Role = None):
    uid = interaction.user.id
    _staffapp_cfg(interaction.guild.id)["granted_role_id"] = role.id if role else None
    if role:
        await interaction.response.send_message(t(uid, "staffapp.role_set", role=role.mention), ephemeral=True)
    else:
        await interaction.response.send_message(t(uid, "staffapp.role_cleared"), ephemeral=True)


@staffapp_config_slash_group.command(name="private", description="Who sees the applications: only the owner (on) or also recruiters (off)")
@app_commands.describe(enabled="On = only the applicant and the bot owner")
@is_bot_admin_slash()
@app_commands.guild_only()
async def staffapp_config_private_slash(interaction: discord.Interaction, enabled: bool):
    _staffapp_cfg(interaction.guild.id)["owner_only"] = enabled
    await interaction.response.send_message(
        t(interaction.user.id, "staffapp.private_set_on" if enabled else "staffapp.private_set_off"), ephemeral=True)


yslemmfaq_slash_group = app_commands.Group(name="yslemmfaq", description="Manage yslemm's canned Q&A answers")
bot.tree.add_command(yslemmfaq_slash_group)


@yslemmfaq_slash_group.command(name="add", description="Add or update a canned answer")
@app_commands.describe(question="The question to match", answer="The answer yslemm should give")
@is_bot_admin_slash()
@app_commands.guild_only()
async def yslemmfaq_add_slash(interaction: discord.Interaction, question: str, answer: str):
    uid = interaction.user.id
    question, answer = question.strip(), answer.strip()
    key = _yslemm_faq_normalize(question)
    yslemm_faq.setdefault(interaction.guild.id, {})[key] = {"question": question, "answer": answer}
    await interaction.response.send_message(t(uid, "yslemm.faq_added", question=question), ephemeral=True)


@yslemmfaq_slash_group.command(name="remove", description="Remove a canned answer")
@app_commands.describe(question="The question to remove")
@is_bot_admin_slash()
@app_commands.guild_only()
async def yslemmfaq_remove_slash(interaction: discord.Interaction, question: str):
    uid = interaction.user.id
    key = _yslemm_faq_normalize(question)
    faq = yslemm_faq.get(interaction.guild.id, {})
    if key not in faq:
        return await interaction.response.send_message(t(uid, "yslemm.faq_not_found", question=question), ephemeral=True)
    del faq[key]
    await interaction.response.send_message(t(uid, "yslemm.faq_removed", question=question), ephemeral=True)


@yslemmfaq_slash_group.command(name="list", description="List configured canned answers")
@is_bot_admin_slash()
@app_commands.guild_only()
async def yslemmfaq_list_slash(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_yslemm_faq_embed(interaction.user.id, interaction.guild.id), ephemeral=True)


setpayment_slash_group = app_commands.Group(name="setpayment", description="Configure the PayPal/LTC/BTC/Roblox payment info shown on the ticket panel")
bot.tree.add_command(setpayment_slash_group)


@setpayment_slash_group.command(name="status", description="Show the current payment info configuration")
@is_bot_admin_slash()
@app_commands.guild_only()
async def setpayment_status_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    info = payment_info.get(interaction.guild.id, {})
    embed = _base_embed(t(uid, "payment.status_title"), EMBED_COLOR)
    embed.add_field(name="PayPal", value=info.get("paypal") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="LTC", value=info.get("ltc") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="BTC", value=info.get("btc") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="Roblox", value=info.get("roblox") or t(uid, "payment.not_set"), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@setpayment_slash_group.command(name="paypal", description="Set the PayPal info shown on the ticket panel")
@app_commands.describe(value="PayPal email or paypal.me link")
@is_bot_admin_slash()
@app_commands.guild_only()
async def setpayment_paypal_slash(interaction: discord.Interaction, value: str):
    uid = interaction.user.id
    payment_info.setdefault(interaction.guild.id, {})["paypal"] = value
    await interaction.response.send_message(t(uid, "payment.paypal_set"), ephemeral=True)


@setpayment_slash_group.command(name="ltc", description="Set the LTC address shown on the ticket panel")
@app_commands.describe(value="Litecoin wallet address")
@is_bot_admin_slash()
@app_commands.guild_only()
async def setpayment_ltc_slash(interaction: discord.Interaction, value: str):
    uid = interaction.user.id
    payment_info.setdefault(interaction.guild.id, {})["ltc"] = value
    await interaction.response.send_message(t(uid, "payment.ltc_set"), ephemeral=True)


@setpayment_slash_group.command(name="btc", description="Set the BTC address shown on the ticket panel")
@app_commands.describe(value="Bitcoin wallet address")
@is_bot_admin_slash()
@app_commands.guild_only()
async def setpayment_btc_slash(interaction: discord.Interaction, value: str):
    uid = interaction.user.id
    payment_info.setdefault(interaction.guild.id, {})["btc"] = value
    await interaction.response.send_message(t(uid, "payment.btc_set"), ephemeral=True)


@setpayment_slash_group.command(name="roblox", description="Set the Roblox username shown on the ticket panel")
@app_commands.describe(value="Roblox username")
@is_bot_admin_slash()
@app_commands.guild_only()
async def setpayment_roblox_slash(interaction: discord.Interaction, value: str):
    uid = interaction.user.id
    payment_info.setdefault(interaction.guild.id, {})["roblox"] = value
    await interaction.response.send_message(t(uid, "payment.roblox_set"), ephemeral=True)


@bot.tree.command(name="payment", description="Manage a staff member's own payment info (set or remove fields interactively)")
@app_commands.describe(member="Whose payment info to manage (defaults to yourself)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def payment_slash(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    view = PaymentManageView(interaction.user, target)
    await interaction.response.send_message(embed=_staff_payment_embed(interaction.user.id, target), view=view)
    view.message = await interaction.original_response()


mypayment_slash_group = app_commands.Group(name="mypayment", description="Set your own PayPal/LTC/BTC/Roblox info, shown when you claim a ticket")
bot.tree.add_command(mypayment_slash_group)


@mypayment_slash_group.command(name="status", description="Show your own payment info configuration")
@is_bot_admin_slash()
@app_commands.guild_only()
async def mypayment_status_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    info = staff_payment_info.get(uid, {})
    embed = _base_embed(t(uid, "payment.status_title"), EMBED_COLOR)
    embed.add_field(name="PayPal", value=info.get("paypal") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="LTC", value=info.get("ltc") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="BTC", value=info.get("btc") or t(uid, "payment.not_set"), inline=False)
    embed.add_field(name="Roblox", value=info.get("roblox") or t(uid, "payment.not_set"), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@mypayment_slash_group.command(name="paypal", description="Set your own PayPal info")
@app_commands.describe(value="PayPal email or paypal.me link")
@is_bot_admin_slash()
@app_commands.guild_only()
async def mypayment_paypal_slash(interaction: discord.Interaction, value: str):
    uid = interaction.user.id
    staff_payment_info.setdefault(uid, {})["paypal"] = value
    await interaction.response.send_message(t(uid, "payment.paypal_set"), ephemeral=True)


@mypayment_slash_group.command(name="ltc", description="Set your own LTC address")
@app_commands.describe(value="Litecoin wallet address")
@is_bot_admin_slash()
@app_commands.guild_only()
async def mypayment_ltc_slash(interaction: discord.Interaction, value: str):
    uid = interaction.user.id
    staff_payment_info.setdefault(uid, {})["ltc"] = value
    await interaction.response.send_message(t(uid, "payment.ltc_set"), ephemeral=True)


@mypayment_slash_group.command(name="btc", description="Set your own BTC address")
@app_commands.describe(value="Bitcoin wallet address")
@is_bot_admin_slash()
@app_commands.guild_only()
async def mypayment_btc_slash(interaction: discord.Interaction, value: str):
    uid = interaction.user.id
    staff_payment_info.setdefault(uid, {})["btc"] = value
    await interaction.response.send_message(t(uid, "payment.btc_set"), ephemeral=True)


@mypayment_slash_group.command(name="roblox", description="Set your own Roblox username")
@app_commands.describe(value="Roblox username")
@is_bot_admin_slash()
@app_commands.guild_only()
async def mypayment_roblox_slash(interaction: discord.Interaction, value: str):
    uid = interaction.user.id
    staff_payment_info.setdefault(uid, {})["roblox"] = value
    await interaction.response.send_message(t(uid, "payment.roblox_set"), ephemeral=True)


@mypayment_slash_group.command(name="clear", description="Remove one (or all) of your own payment fields -- asks to confirm first")
@app_commands.describe(field="paypal, ltc, btc, roblox, or all (default: all)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def mypayment_clear_slash(interaction: discord.Interaction, field: str = "all"):
    uid = interaction.user.id
    field = field.lower().strip()
    if field not in ("paypal", "ltc", "btc", "roblox", "all"):
        return await interaction.response.send_message(t(uid, "payment.clear_invalid_field"), ephemeral=True)
    if not any((staff_payment_info.get(uid) or {}).values()):
        return await interaction.response.send_message(t(uid, "payment.not_configured"), ephemeral=True)

    embed = _base_embed(t(uid, "payment.clear_confirm_title"), WARN_COLOR)
    embed.description = t(uid, "payment.clear_confirm_description", field=field)
    view = ConfirmView(interaction.user)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    view.message = msg
    await view.wait()

    if view.value is None:
        embed.description += t(uid, "confirm.expired")
        return await msg.edit(embed=embed)
    if view.value is False:
        embed.title = t(uid, "payment.clear_cancelled_title")
        embed.color = EMBED_COLOR
        return await msg.edit(embed=embed)

    if field == "all":
        staff_payment_info[uid] = {}
    else:
        staff_payment_info.setdefault(uid, {})[field] = ""
    embed.title = t(uid, "payment.clear_success_title")
    embed.color = SUCCESS_COLOR
    embed.description = t(uid, "payment.clear_success_description", field=field)
    await msg.edit(embed=embed)


@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(member="Member to warn", reason="Reason for the warning")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.guild_only()
async def warn_slash(interaction: discord.Interaction, member: discord.Member, reason: str):
    uid = interaction.user.id
    if not reason.strip():
        return await interaction.response.send_message(t(uid, "error.missing_argument"), ephemeral=True)
    key = (interaction.guild.id, member.id)
    warnings_store.setdefault(key, []).append(reason)
    embed = _base_embed(t(uid, "warn.title"), WARN_COLOR)
    embed.description = t(uid, "warn.added", member=member, reason=reason, count=len(warnings_store[key]))
    _footer(embed, interaction.user)
    await interaction.response.send_message(embed=embed)
    await _log_moderation(interaction.guild, interaction.user, embed.title, embed.description, WARN_COLOR)
    await _check_warn_autoban(interaction.guild, member, key)


@bot.tree.command(name="warnings", description="List a member's warnings")
@app_commands.describe(member="Whose warnings to show (defaults to you)")
@app_commands.guild_only()
async def warnings_slash(interaction: discord.Interaction, member: discord.Member = None):
    uid = interaction.user.id
    member = member or interaction.user
    reasons = warnings_store.get((interaction.guild.id, member.id), [])
    embed = _base_embed(t(uid, "warn.list_title", member=member.display_name), WARN_COLOR if reasons else EMBED_COLOR)
    embed.description = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(reasons)) if reasons else t(uid, "warn.list_empty")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clearwarnings", description="Clear a member's warnings")
@app_commands.describe(member="Whose warnings to clear")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.guild_only()
async def clearwarnings_slash(interaction: discord.Interaction, member: discord.Member):
    uid = interaction.user.id
    warnings_store.pop((interaction.guild.id, member.id), None)
    await interaction.response.send_message(t(uid, "warn.cleared", member=member))
    await _log_moderation(interaction.guild, interaction.user, t(0, "warn.cleared_title"), t(0, "warn.cleared", member=str(member)), EMBED_COLOR)


@bot.tree.command(name="lock", description="Lock the current channel")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def lock_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(embed=_base_embed(t(uid, "lock.locked"), WARN_COLOR))


@bot.tree.command(name="unlock", description="Unlock the current channel")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def unlock_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(embed=_base_embed(t(uid, "lock.unlocked"), SUCCESS_COLOR))


@bot.tree.command(name="slowmode", description="Set channel slowmode")
@app_commands.describe(seconds="Slowmode delay in seconds (0 disables it)")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
async def slowmode_slash(interaction: discord.Interaction, seconds: int = 0):
    uid = interaction.user.id
    seconds = max(0, min(seconds, 21600))
    await interaction.channel.edit(slowmode_delay=seconds)
    msg = t(uid, "slowmode.off") if seconds == 0 else t(uid, "slowmode.set", seconds=seconds)
    await interaction.response.send_message(msg)


@bot.tree.command(name="createrole", description="Create a new role")
@app_commands.describe(name="Name of the new role")
@is_bot_admin_slash()
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def createrole_slash(interaction: discord.Interaction, name: str):
    uid = interaction.user.id
    try:
        role = await interaction.guild.create_role(name=name, reason=f"Created by {interaction.user} via bot")
    except discord.Forbidden:
        return await interaction.response.send_message(t(uid, "error.bot_no_permission"), ephemeral=True)
    await interaction.response.send_message(t(uid, "role.created", role=role.mention), ephemeral=True)


@bot.tree.command(name="createchannel", description="Create a new text channel")
@app_commands.describe(name="Name of the new channel", category="Category to create it in (optional)")
@is_bot_admin_slash()
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
async def createchannel_slash(interaction: discord.Interaction, name: str, category: discord.CategoryChannel = None):
    uid = interaction.user.id
    try:
        channel = await interaction.guild.create_text_channel(name=name, category=category, reason=f"Created by {interaction.user} via bot")
    except discord.Forbidden:
        return await interaction.response.send_message(t(uid, "error.bot_no_permission"), ephemeral=True)
    await interaction.response.send_message(t(uid, "channel.created", channel=channel.mention), ephemeral=True)


@bot.tree.command(name="setlogchannel", description="Set the security log channel")
@app_commands.describe(channel="Channel for security alerts (defaults to the current channel)")
@is_bot_admin_slash()
@app_commands.guild_only()
async def setlogchannel_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    uid = interaction.user.id
    channel = channel or interaction.channel
    log_channels[interaction.guild.id] = channel.id
    await interaction.response.send_message(t(uid, "logchannel.set", channel=channel.mention), ephemeral=True)


@bot.tree.command(name="logs", description="Show (and optionally set) the security log channel and what gets logged there")
@app_commands.describe(channel="Optional: set a new log channel while checking the status")
@is_bot_admin_slash()
@app_commands.guild_only()
async def logs_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    uid = interaction.user.id
    if channel is not None:
        log_channels[interaction.guild.id] = channel.id
    await interaction.response.send_message(embed=_logs_status_embed(uid, interaction.guild), ephemeral=True)


@bot.tree.command(name="setpaypalchannel", description="Set the channel where PayPal payment notifications (IPN) get posted")
@app_commands.describe(channel="Optional: set a new notification channel while checking the status")
@is_bot_admin_slash()
@app_commands.guild_only()
async def setpaypalchannel_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    uid = interaction.user.id
    if channel is not None:
        paypal_notify_channels[interaction.guild.id] = channel.id
    await interaction.response.send_message(embed=_paypal_status_embed(uid, interaction.guild), ephemeral=True)


@bot.tree.command(name="setcryptochannel", description="Set the channel where BTC/LTC on-chain payment notifications get posted")
@app_commands.describe(channel="Optional: set a new notification channel while checking the status")
@is_bot_admin_slash()
@app_commands.guild_only()
async def setcryptochannel_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    uid = interaction.user.id
    if channel is not None:
        crypto_notify_channels[interaction.guild.id] = channel.id
    await interaction.response.send_message(embed=_crypto_status_embed(uid, interaction.guild), ephemeral=True)


autoremind_slash_group = app_commands.Group(name="autoremind", description="Configure a recurring reminder message posted automatically to a channel")
bot.tree.add_command(autoremind_slash_group)


@autoremind_slash_group.command(name="status", description="Show the current recurring reminder configuration")
@is_bot_admin_slash()
@app_commands.guild_only()
async def autoremind_status_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    await interaction.response.send_message(embed=_autoremind_status_embed(uid, interaction.guild), ephemeral=True)


@autoremind_slash_group.command(name="set", description="Set (or replace) the recurring reminder")
@app_commands.describe(channel="Channel to post the reminder in", hours="How often to repeat, in hours", message="The reminder text")
@is_bot_admin_slash()
@app_commands.guild_only()
async def autoremind_set_slash(interaction: discord.Interaction, channel: discord.TextChannel, hours: float, message: str):
    uid = interaction.user.id
    if not message.strip():
        return await interaction.response.send_message(t(uid, "autoremind.missing_message"), ephemeral=True)
    if hours <= 0 or hours > 720:
        return await interaction.response.send_message(t(uid, "autoremind.invalid_interval"), ephemeral=True)
    recurring_reminders[interaction.guild.id] = {
        "channel_id": channel.id,
        "message": message,
        "interval_minutes": hours * 60,
        "last_sent": datetime.now(timezone.utc).isoformat(),
        "paused": False,
    }
    await interaction.response.send_message(t(uid, "autoremind.set", hours=f"{hours:g}", channel=channel.mention), ephemeral=True)


@autoremind_slash_group.command(name="stop", description="Stop the recurring reminder")
@is_bot_admin_slash()
@app_commands.guild_only()
async def autoremind_stop_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    recurring_reminders.pop(interaction.guild.id, None)
    await interaction.response.send_message(t(uid, "autoremind.stopped"), ephemeral=True)


@autoremind_slash_group.command(name="pause", description="Pause the recurring reminder without losing its configuration")
@is_bot_admin_slash()
@app_commands.guild_only()
async def autoremind_pause_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = recurring_reminders.get(interaction.guild.id)
    if cfg is None:
        return await interaction.response.send_message(t(uid, "autoremind.not_configured"), ephemeral=True)
    if cfg.get("paused"):
        return await interaction.response.send_message(t(uid, "autoremind.already_paused"), ephemeral=True)
    cfg["paused"] = True
    await interaction.response.send_message(t(uid, "autoremind.paused"), ephemeral=True)


@autoremind_slash_group.command(name="unpause", description="Resume a paused recurring reminder")
@is_bot_admin_slash()
@app_commands.guild_only()
async def autoremind_unpause_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = recurring_reminders.get(interaction.guild.id)
    if cfg is None:
        return await interaction.response.send_message(t(uid, "autoremind.not_configured"), ephemeral=True)
    if not cfg.get("paused"):
        return await interaction.response.send_message(t(uid, "autoremind.not_paused"), ephemeral=True)
    cfg["paused"] = False
    cfg["last_sent"] = datetime.now(timezone.utc).isoformat()
    await interaction.response.send_message(t(uid, "autoremind.unpaused"), ephemeral=True)


@bot.tree.command(name="language", description="Set your preferred language")
@app_commands.describe(lang="Language to use")
@app_commands.choices(lang=[
    app_commands.Choice(name="English", value="en"),
    app_commands.Choice(name="Français", value="fr"),
])
async def language_slash(interaction: discord.Interaction, lang: app_commands.Choice[str]):
    uid = interaction.user.id
    user_lang[uid] = lang.value
    await interaction.response.send_message(t(uid, "language.set", lang=t(uid, f"language.{lang.value}")), ephemeral=True)


@bot.tree.command(name="help", description="Show the interactive help menu")
async def help_slash(interaction: discord.Interaction):
    view = HelpView(interaction.user)
    await interaction.response.send_message(embed=view._home_embed(), view=view, ephemeral=True)
    view.message = await interaction.original_response()


@bot.tree.command(name="yslem", description="Interactive overview of the bot (AI, economy, moderation, admin)")
async def about_slash(interaction: discord.Interaction):
    view = YslemAboutView(interaction.user)
    await interaction.response.send_message(embed=view._home_embed(), view=view, ephemeral=True)
    view.message = await interaction.original_response()


@bot.tree.command(name="perm", description="Show the bot's permission hierarchy")
async def perm_slash(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_perm_embed(interaction.user.id), ephemeral=True)


words_slash_group = app_commands.Group(name="words", description="View or edit the banned word list")
bot.tree.add_command(words_slash_group)


@words_slash_group.command(name="list", description="Show the current banned words")
@app_commands.guild_only()
async def words_list_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    ws = sorted(_banned_words_for(interaction.guild.id))
    embed = _base_embed(t(uid, "words.list_title", count=len(ws)), EMBED_COLOR)
    embed.description = ", ".join(f"`{w}`" for w in ws) if ws else t(uid, "words.list_empty")
    await interaction.response.send_message(embed=embed)


@words_slash_group.command(name="add", description="Add a word to the banned list")
@app_commands.describe(word="Word to ban")
@is_bot_admin_slash()
@app_commands.guild_only()
async def words_add_slash(interaction: discord.Interaction, word: str):
    uid = interaction.user.id
    word = word.lower().strip()
    ws = _banned_words_for(interaction.guild.id)
    if word in ws:
        return await interaction.response.send_message(t(uid, "words.already_exists", word=word), ephemeral=True)
    ws.add(word)
    await interaction.response.send_message(t(uid, "words.added", word=word), ephemeral=True)


@words_slash_group.command(name="remove", description="Remove a word from the banned list")
@app_commands.describe(word="Word to unban")
@is_bot_admin_slash()
@app_commands.guild_only()
async def words_remove_slash(interaction: discord.Interaction, word: str):
    uid = interaction.user.id
    word = word.lower().strip()
    ws = _banned_words_for(interaction.guild.id)
    if word not in ws:
        return await interaction.response.send_message(t(uid, "words.not_found", word=word), ephemeral=True)
    ws.discard(word)
    await interaction.response.send_message(t(uid, "words.removed", word=word), ephemeral=True)


botadmin_slash_group = app_commands.Group(name="botadmin", description="Manage who can control the bot")
bot.tree.add_command(botadmin_slash_group)


@botadmin_slash_group.command(name="list", description="List current bot admins")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def botadmin_list_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    admins = bot_admins.get(interaction.guild.id, {"roles": set(), "users": set()})
    embed = _base_embed(t(uid, "botadmin.list_title"), EMBED_COLOR)
    roles_text = ", ".join(f"<@&{r}>" for r in admins["roles"]) or t(uid, "botadmin.list_empty")
    users_text = ", ".join(f"<@{u}>" for u in admins["users"]) or t(uid, "botadmin.list_empty")
    embed.add_field(name=t(uid, "botadmin.list_roles"), value=roles_text, inline=False)
    embed.add_field(name=t(uid, "botadmin.list_users"), value=users_text, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@botadmin_slash_group.command(name="addrole", description="Allow a role to manage the bot")
@app_commands.describe(role="Role to grant bot-admin access")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def botadmin_addrole_slash(interaction: discord.Interaction, role: discord.Role):
    uid = interaction.user.id
    bot_admins.setdefault(interaction.guild.id, {"roles": set(), "users": set()})["roles"].add(role.id)
    await interaction.response.send_message(t(uid, "botadmin.role_added", role=role.mention), ephemeral=True)


@botadmin_slash_group.command(name="removerole", description="Revoke a role's bot-admin access")
@app_commands.describe(role="Role to revoke bot-admin access from")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def botadmin_removerole_slash(interaction: discord.Interaction, role: discord.Role):
    uid = interaction.user.id
    bot_admins.setdefault(interaction.guild.id, {"roles": set(), "users": set()})["roles"].discard(role.id)
    await interaction.response.send_message(t(uid, "botadmin.role_removed", role=role.mention), ephemeral=True)


@botadmin_slash_group.command(name="adduser", description="Allow a member to manage the bot")
@app_commands.describe(member="Member to grant bot-admin access")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def botadmin_adduser_slash(interaction: discord.Interaction, member: discord.Member):
    uid = interaction.user.id
    bot_admins.setdefault(interaction.guild.id, {"roles": set(), "users": set()})["users"].add(member.id)
    await interaction.response.send_message(t(uid, "botadmin.user_added", user=member.mention), ephemeral=True)


@botadmin_slash_group.command(name="removeuser", description="Revoke a member's bot-admin access")
@app_commands.describe(member="Member to revoke bot-admin access from")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def botadmin_removeuser_slash(interaction: discord.Interaction, member: discord.Member):
    uid = interaction.user.id
    bot_admins.setdefault(interaction.guild.id, {"roles": set(), "users": set()})["users"].discard(member.id)
    await interaction.response.send_message(t(uid, "botadmin.user_removed", user=member.mention), ephemeral=True)


antiraid_slash_group = app_commands.Group(name="antiraid", description="Configure anti-raid protection")
bot.tree.add_command(antiraid_slash_group)


@antiraid_slash_group.command(name="status", description="Show anti-raid status")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antiraid_status_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _antiraid_cfg(interaction.guild.id)
    embed = _base_embed(t(uid, "antiraid.status_title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "antiraid.status_label"), value=t(uid, "antiraid.enabled") if cfg["enabled"] else t(uid, "antiraid.disabled"), inline=True)
    embed.add_field(name=t(uid, "antiraid.threshold"), value=cfg["threshold"], inline=True)
    embed.add_field(name=t(uid, "antiraid.window"), value=f"{cfg['window']}s", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@antiraid_slash_group.command(name="on", description="Enable anti-raid protection")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antiraid_on_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _antiraid_cfg(interaction.guild.id)
    if cfg["enabled"]:
        return await interaction.response.send_message(t(uid, "antiraid.already_on"), ephemeral=True)
    cfg["enabled"] = True
    await interaction.response.send_message(t(uid, "antiraid.on"), ephemeral=True)


@antiraid_slash_group.command(name="off", description="Disable anti-raid protection")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antiraid_off_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _antiraid_cfg(interaction.guild.id)
    if not cfg["enabled"]:
        return await interaction.response.send_message(t(uid, "antiraid.already_off"), ephemeral=True)
    cfg["enabled"] = False
    await interaction.response.send_message(t(uid, "antiraid.off"), ephemeral=True)


@antiraid_slash_group.command(name="config", description="Configure anti-raid sensitivity")
@app_commands.describe(threshold="Joins that trigger a raid response", window="Time window in seconds")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antiraid_config_slash(interaction: discord.Interaction, threshold: int = 5, window: int = 10):
    uid = interaction.user.id
    threshold = max(2, min(threshold, 50))
    window = max(3, min(window, 300))
    cfg = _antiraid_cfg(interaction.guild.id)
    cfg["threshold"] = threshold
    cfg["window"] = window
    await interaction.response.send_message(t(uid, "antiraid.configured", threshold=threshold, window=window), ephemeral=True)


antinuke_slash_group = app_commands.Group(name="antinuke", description="Configure anti-nuke protection")
bot.tree.add_command(antinuke_slash_group)


@antinuke_slash_group.command(name="status", description="Show anti-nuke status")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antinuke_status_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _antinuke_cfg(interaction.guild.id)
    embed = _base_embed(t(uid, "antinuke.status_title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "antiraid.status_label"), value=t(uid, "antiraid.enabled") if cfg["enabled"] else t(uid, "antiraid.disabled"), inline=True)
    embed.add_field(name=t(uid, "antiraid.threshold"), value=cfg["threshold"], inline=True)
    embed.add_field(name=t(uid, "antiraid.window"), value=f"{cfg['window']}s", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@antinuke_slash_group.command(name="on", description="Enable anti-nuke protection")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antinuke_on_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _antinuke_cfg(interaction.guild.id)
    if cfg["enabled"]:
        return await interaction.response.send_message(t(uid, "antinuke.already_on"), ephemeral=True)
    cfg["enabled"] = True
    await interaction.response.send_message(t(uid, "antinuke.on"), ephemeral=True)


@antinuke_slash_group.command(name="off", description="Disable anti-nuke protection")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antinuke_off_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _antinuke_cfg(interaction.guild.id)
    if not cfg["enabled"]:
        return await interaction.response.send_message(t(uid, "antinuke.already_off"), ephemeral=True)
    cfg["enabled"] = False
    await interaction.response.send_message(t(uid, "antinuke.off"), ephemeral=True)


@antinuke_slash_group.command(name="config", description="Configure anti-nuke sensitivity")
@app_commands.describe(threshold="Destructive actions that trigger a response", window="Time window in seconds")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antinuke_config_slash(interaction: discord.Interaction, threshold: int = 3, window: int = 10):
    uid = interaction.user.id
    threshold = max(2, min(threshold, 20))
    window = max(3, min(window, 120))
    cfg = _antinuke_cfg(interaction.guild.id)
    cfg["threshold"] = threshold
    cfg["window"] = window
    await interaction.response.send_message(t(uid, "antinuke.configured", threshold=threshold, window=window), ephemeral=True)


antipub_slash_group = app_commands.Group(name="antipub", description="Configure the anti-advertising system")
bot.tree.add_command(antipub_slash_group)


@antipub_slash_group.command(name="status", description="Show anti-pub status")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antipub_status_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _antipub_cfg(interaction.guild.id)
    embed = _base_embed(t(uid, "antipub.status_title"), EMBED_COLOR)
    embed.add_field(name=t(uid, "antiraid.status_label"), value=t(uid, "antiraid.enabled") if cfg["enabled"] else t(uid, "antiraid.disabled"), inline=True)
    embed.add_field(name=t(uid, "antipub.threshold"), value=cfg["threshold"], inline=True)
    embed.add_field(name=t(uid, "antipub.sanction"), value=cfg["sanction"], inline=True)
    embed.add_field(name=t(uid, "antipub.timeout_minutes"), value=f"{cfg['timeout_minutes']}min", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@antipub_slash_group.command(name="on", description="Enable the anti-advertising system")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antipub_on_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _antipub_cfg(interaction.guild.id)
    if cfg["enabled"]:
        return await interaction.response.send_message(t(uid, "antipub.already_on"), ephemeral=True)
    cfg["enabled"] = True
    await interaction.response.send_message(t(uid, "antipub.on"), ephemeral=True)


@antipub_slash_group.command(name="off", description="Disable the anti-advertising system")
@is_bot_admin_slash()
@app_commands.guild_only()
async def antipub_off_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    cfg = _antipub_cfg(interaction.guild.id)
    if not cfg["enabled"]:
        return await interaction.response.send_message(t(uid, "antipub.already_off"), ephemeral=True)
    cfg["enabled"] = False
    await interaction.response.send_message(t(uid, "antipub.off"), ephemeral=True)


@antipub_slash_group.command(name="config", description="Configure anti-pub sensitivity and sanction")
@app_commands.describe(
    threshold="Suspicion score that triggers a sanction",
    sanction="Sanction to apply once the threshold is reached",
    timeout_minutes="Timeout duration in minutes (only used if sanction=timeout)",
)
@app_commands.choices(sanction=[
    app_commands.Choice(name="warn", value="warn"),
    app_commands.Choice(name="timeout", value="timeout"),
    app_commands.Choice(name="kick", value="kick"),
    app_commands.Choice(name="ban", value="ban"),
])
@is_bot_admin_slash()
@app_commands.guild_only()
async def antipub_config_slash(
    interaction: discord.Interaction,
    threshold: int = 5,
    sanction: app_commands.Choice[str] = None,
    timeout_minutes: int = 10,
):
    uid = interaction.user.id
    sanction_value = sanction.value if sanction else "warn"
    threshold = max(1, min(threshold, 50))
    timeout_minutes = max(1, min(timeout_minutes, 10080))
    cfg = _antipub_cfg(interaction.guild.id)
    cfg["threshold"] = threshold
    cfg["sanction"] = sanction_value
    cfg["timeout_minutes"] = timeout_minutes
    await interaction.response.send_message(t(uid, "antipub.configured", threshold=threshold, sanction=sanction_value), ephemeral=True)


cmdaccess_slash_group = app_commands.Group(name="cmdaccess", description="Restrict specific commands to specific roles (bot-admin only)")
bot.tree.add_command(cmdaccess_slash_group)


@cmdaccess_slash_group.command(name="allow", description="Allow a role to use a specific command")
@app_commands.describe(command="Command name (e.g. yslem, search, ban)", role="Role to grant access to")
@is_bot_admin_slash()
@app_commands.guild_only()
async def cmdaccess_allow_slash(interaction: discord.Interaction, command: str, role: discord.Role):
    uid = interaction.user.id
    name = command.strip().lstrip("!/").lower()
    command_access.setdefault(interaction.guild.id, {}).setdefault(name, set()).add(role.id)
    await interaction.response.send_message(t(uid, "cmdaccess.allowed", command=name, role=role.mention), ephemeral=True)


@cmdaccess_slash_group.command(name="remove", description="Remove a role's access to a specific command")
@app_commands.describe(command="Command name", role="Role to revoke access from")
@is_bot_admin_slash()
@app_commands.guild_only()
async def cmdaccess_remove_slash(interaction: discord.Interaction, command: str, role: discord.Role):
    uid = interaction.user.id
    name = command.strip().lstrip("!/").lower()
    roles = command_access.get(interaction.guild.id, {}).get(name)
    if not roles or role.id not in roles:
        return await interaction.response.send_message(t(uid, "cmdaccess.not_allowed", command=name, role=role.mention), ephemeral=True)
    roles.discard(role.id)
    await interaction.response.send_message(t(uid, "cmdaccess.removed", command=name, role=role.mention), ephemeral=True)


@cmdaccess_slash_group.command(name="reset", description="Remove all restrictions for a command")
@app_commands.describe(command="Command name")
@is_bot_admin_slash()
@app_commands.guild_only()
async def cmdaccess_reset_slash(interaction: discord.Interaction, command: str):
    uid = interaction.user.id
    name = command.strip().lstrip("!/").lower()
    guild_cfg = command_access.get(interaction.guild.id)
    if guild_cfg and name in guild_cfg:
        del guild_cfg[name]
    await interaction.response.send_message(t(uid, "cmdaccess.reset", command=name), ephemeral=True)


@cmdaccess_slash_group.command(name="list", description="Show current command access restrictions")
@is_bot_admin_slash()
@app_commands.guild_only()
async def cmdaccess_list_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    await interaction.response.send_message(embed=_cmdaccess_embed(uid, interaction.guild.id), ephemeral=True)


@bot.tree.command(name="saveconfig", description="Force an immediate save of the bot's config to Redis")
@is_bot_admin_slash()
@app_commands.guild_only()
async def saveconfig_slash(interaction: discord.Interaction):
    uid = interaction.user.id
    if redis_client is None:
        return await interaction.response.send_message(t(uid, "saveconfig.no_redis"), ephemeral=True)
    await _save_state_to_redis()
    await interaction.response.send_message(t(uid, "saveconfig.saved"), ephemeral=True)


async def _run_bot(token: str) -> None:
    """Connexion avec nouvel essai sur 429 : Discord (via Cloudflare) peut refuser le login quelques minutes ;
    sans ca le processus quitte et Render relance en boucle."""
    async with bot:
        while True:
            try:
                await bot.start(token)
                return
            except discord.HTTPException as exc:
                if exc.status != 429:
                    raise
                print("[WARN] Discord limite les requetes (429) : nouvel essai de connexion dans 10 min")
                await asyncio.sleep(600)


def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is missing. Add it to the environment variables.")

    admin_panel.install_log_capture()
    oauth_verify.configure(lambda: bot.application_id, _handle_oauth_verification, lambda: getattr(bot, "loop", None))
    admin_panel.configure(_panel_snapshot, lambda: getattr(bot, "loop", None), action_coro=_panel_action)
    threading.Thread(target=_start_health_server, daemon=True).start()
    threading.Thread(target=_keep_awake_loop, daemon=True).start()

    try:
        asyncio.run(_run_bot(token))
    except discord.errors.PrivilegedIntentsRequired:
        raise SystemExit(
            "Privileged intents are disabled. Go to discord.com/developers/applications "
            "-> your app -> Bot -> enable 'Server Members Intent' and 'Message Content Intent'."
        )
    except discord.errors.LoginFailure:
        raise SystemExit("Invalid Discord token. Check DISCORD_TOKEN.")


if __name__ == "__main__":
    main()
