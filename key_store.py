"""Script keys and the public verify endpoint (contract: docs/API.md).

  * Only a salted SHA-256 of a key is stored. The clear key exists once, in the
    DM that hands it over; it is never logged and cannot be read back.
  * One key per Discord account AND one per Roblox user id (two unique
    indexes). A key is bound to the Roblox user id it was issued for.
  * Keys expire (30 days by default). /key reset replaces the key: at most one
    per week and three per month, and the old key answers "revoked".
  * The endpoint answers the same way for an unknown key, a wrong key and a key
    that belongs to another Roblox account, and is rate limited per address and
    per key. It sends no CORS headers, so browsers cannot call it.
"""
import hashlib
import json
import os
import re
import secrets
import string
import threading
import time
from collections import deque
from urllib.parse import urlsplit

KEY_PREFIX = "YSL-"
KEY_MAX_LEN = 128
_KEY_RE = re.compile(r"^YSL-[A-Za-z0-9_-]{24,124}$")
DAY = 86400

# Rate limits: (hits, window seconds)
RATE_IP = (30, 60)       # any request, per client address (a player makes 1 at start, then 1 per 15 min)
RATE_KEY = (30, 60)      # per key (a script verifies every 15 minutes)
RATE_FAIL = (12, 60)     # failed checks, per client address
MAX_BODY = 2048
RESET_MIN_GAP_DAYS = 7
RESET_MONTH_MAX = 3
KEEP_DEAD_RECORDS_DAYS = 90

_lock = threading.RLock()
_state_salt = ""             # generated once and saved with the bot state
# key hash -> record
_records = {}
_by_discord = {}             # discord id -> current key hash   (unique)
_by_roblox = {}              # roblox id  -> current key hash   (unique)
_banned_discord = {}         # discord id -> reason
_banned_roblox = {}          # roblox id  -> reason
_reset_log = {}              # discord id -> [timestamps of resets]
_rate_all, _rate_key, _rate_fail = {}, {}, {}
# False until the saved keys have been loaded: answering "invalid" for every key
# while the bot is still restoring them would stop every player's script.
_ready = False


def set_ready(value):
    global _ready
    _ready = bool(value)


def is_ready():
    return _ready
_SCRIPT_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_script_stats = {}           # script name -> {"valid": n, "other": n}; in memory, no personal data
_SCRIPT_STATS_MAX = 50


def ttl_days():
    try:
        return max(1, int(os.environ.get("KEY_TTL_DAYS", "30")))
    except ValueError:
        return 30


# --- hashing ---------------------------------------------------------------------

def _salt():
    """Server-side salt: the KEY_SALT environment variable when set, otherwise a
    random value generated once and kept in the bot state."""
    global _state_salt
    env = os.environ.get("KEY_SALT", "")
    if env:
        return env.encode("utf-8")
    with _lock:
        if not _state_salt:
            _state_salt = secrets.token_hex(32)
        return _state_salt.encode("utf-8")


def _hash(key):
    return hashlib.sha256(_salt() + b":" + key.encode("utf-8")).hexdigest()


_KEY_ALPHABET = string.ascii_letters + string.digits


def new_key():
    """"YSL-" + 32 letters and digits (a subset of base64url, so it is a valid key
    for the contract, and it shows and copies cleanly in Discord: no `_` or `-`
    inside that chat markdown could eat). About 190 bits."""
    return KEY_PREFIX + "".join(secrets.choice(_KEY_ALPHABET) for _ in range(32))


def valid_format(key):
    return isinstance(key, str) and len(key) <= KEY_MAX_LEN and bool(_KEY_RE.match(key))


# --- lifecycle -------------------------------------------------------------------

def _prune(now):
    cutoff = now - KEEP_DEAD_RECORDS_DAYS * DAY
    current = set(_by_discord.values()) | set(_by_roblox.values())
    for h in [h for h, r in _records.items()
              if h not in current and (r["revoked"] or r["expires"] < cutoff) and r["created"] < cutoff]:
        _records.pop(h, None)


def issue(discord_id, roblox_id, roblox_name="", reset=False, now=None):
    """Create a key. Returns (code, key, record):

    ok, banned, admin_revoked, active_exists, linked_other, roblox_taken,
    no_key (reset without a key), reset_too_soon, reset_quota.
    key is the clear key and only set when code == "ok".
    """
    now = now or time.time()
    with _lock:
        if discord_id in _banned_discord or roblox_id in _banned_roblox:
            return "banned", None, None
        old_hash = _by_discord.get(discord_id)
        old = _records.get(old_hash) if old_hash else None
        if old is not None:
            if old["admin_revoked"]:
                return "admin_revoked", None, None
            if old["roblox_id"] != roblox_id:
                return "linked_other", None, None
        other_hash = _by_roblox.get(roblox_id)
        if other_hash and _records[other_hash]["discord_id"] != discord_id:
            return "roblox_taken", None, None
        if reset:
            if old is None:
                return "no_key", None, None
            history = [t for t in _reset_log.get(discord_id, []) if now - t < 30 * DAY]
            if any(now - t < RESET_MIN_GAP_DAYS * DAY for t in history):
                return "reset_too_soon", None, None
            if len(history) >= RESET_MONTH_MAX:
                return "reset_quota", None, None
        elif old is not None and not old["revoked"] and old["expires"] > now:
            return "active_exists", None, None
        # --- allowed ---
        if old is not None:
            old["revoked"] = True          # the previous key now answers "revoked"
        if reset:
            _reset_log[discord_id] = history + [now]
        while True:
            key = new_key()
            digest = _hash(key)
            if digest not in _records:
                break
        _records[digest] = {
            "discord_id": discord_id, "roblox_id": roblox_id, "roblox_name": roblox_name,
            "created": now, "expires": now + ttl_days() * DAY, "revoked": False, "admin_revoked": False,
        }
        _by_discord[discord_id] = digest
        _by_roblox[roblox_id] = digest
        _prune(now)
        return "ok", key, dict(_records[digest])


def can_issue(discord_id, roblox_id, now=None):
    """Would a first request for this pair be accepted? "ok" or the refusal code
    (same checks as issue(), without creating anything)."""
    now = now or time.time()
    with _lock:
        if discord_id in _banned_discord or roblox_id in _banned_roblox:
            return "banned"
        old = _records.get(_by_discord.get(discord_id))
        if old is not None:
            if old["admin_revoked"]:
                return "admin_revoked"
            if old["roblox_id"] != roblox_id:
                return "linked_other"
        other = _by_roblox.get(roblox_id)
        if other and _records[other]["discord_id"] != discord_id:
            return "roblox_taken"
        if old is not None and not old["revoked"] and old["expires"] > now:
            return "active_exists"
        return "ok"


def can_reset(discord_id, now=None):
    """"ok", or why a replacement key cannot be given now (reset_too_soon / reset_quota)."""
    now = now or time.time()
    with _lock:
        history = [t for t in _reset_log.get(discord_id, []) if now - t < 30 * DAY]
    if any(now - t < RESET_MIN_GAP_DAYS * DAY for t in history):
        return "reset_too_soon"
    return "reset_quota" if len(history) >= RESET_MONTH_MAX else "ok"


def current_record(discord_id):
    with _lock:
        rec = _records.get(_by_discord.get(discord_id))
        return dict(rec) if rec else None


def next_reset_in(discord_id, now=None):
    """Seconds until a reset is allowed again (0 = allowed now)."""
    now = now or time.time()
    with _lock:
        history = [t for t in _reset_log.get(discord_id, []) if now - t < 30 * DAY]
        waits = []
        recent = [t for t in history if now - t < RESET_MIN_GAP_DAYS * DAY]
        if recent:
            waits.append(max(recent) + RESET_MIN_GAP_DAYS * DAY - now)
        if len(history) >= RESET_MONTH_MAX:
            waits.append(sorted(history)[-RESET_MONTH_MAX] + 30 * DAY - now)
        return int(max(waits)) if waits else 0


def resets_used(discord_id, now=None):
    now = now or time.time()
    with _lock:
        return len([t for t in _reset_log.get(discord_id, []) if now - t < 30 * DAY])


def admin_revoke(discord_id):
    with _lock:
        rec = _records.get(_by_discord.get(discord_id))
        if rec is None:
            return False
        rec["revoked"] = True
        rec["admin_revoked"] = True
        return True


def ban(discord_id, reason=""):
    """Ban a Discord account and the Roblox account linked to its key."""
    with _lock:
        _banned_discord[discord_id] = reason
        rec = _records.get(_by_discord.get(discord_id))
        if rec is not None:
            _banned_roblox[rec["roblox_id"]] = reason
        return rec["roblox_id"] if rec else None


def unban(discord_id):
    with _lock:
        found = _banned_discord.pop(discord_id, None) is not None
        rec = _records.get(_by_discord.get(discord_id))
        if rec is not None:
            found = (_banned_roblox.pop(rec["roblox_id"], None) is not None) or found
        return found


def is_banned(discord_id=None, roblox_id=None):
    with _lock:
        return discord_id in _banned_discord or roblox_id in _banned_roblox


def count_script(name, status):
    """Count one check for the stats (script name only, never who or which key)."""
    name = name if isinstance(name, str) and _SCRIPT_RE.match(name) else "other"
    with _lock:
        if name not in _script_stats and len(_script_stats) >= _SCRIPT_STATS_MAX:
            name = "other"
        entry = _script_stats.setdefault(name, {"valid": 0, "other": 0})
        entry["valid" if status == "valid" else "other"] += 1


def script_stats():
    with _lock:
        return {n: dict(v) for n, v in sorted(_script_stats.items())}


def count():
    with _lock:
        now = time.time()
        live = [r for r in _records.values() if not r["revoked"] and r["expires"] > now]
        return len(live), len(_banned_discord)


# --- verification ----------------------------------------------------------------

def verify(key, roblox_id, now=None):
    """Return (status, expiresAt). A key that is unknown, malformed, or that
    belongs to another Roblox account all give the same ("invalid", 0)."""
    now = now or time.time()
    if not valid_format(key) or not isinstance(roblox_id, int):
        return "invalid", 0
    with _lock:
        rec = _records.get(_hash(key))
        if rec is None or rec["roblox_id"] != roblox_id:
            return "invalid", 0
        if rec["discord_id"] in _banned_discord or rec["roblox_id"] in _banned_roblox:
            return "banned", 0
        if rec["revoked"]:
            return "revoked", 0
        if rec["expires"] <= now:
            return "expired", int(rec["expires"])
        return "valid", int(rec["expires"])


# --- persistence -----------------------------------------------------------------

def dump():
    with _lock:
        return {
            "salt": _state_salt,
            "records": {h: dict(r) for h, r in _records.items()},
            "banned_discord": {str(k): v for k, v in _banned_discord.items()},
            "banned_roblox": {str(k): v for k, v in _banned_roblox.items()},
            "reset_log": {str(k): list(v) for k, v in _reset_log.items()},
        }


def load(data):
    global _state_salt
    with _lock:
        _records.clear(); _by_discord.clear(); _by_roblox.clear()
        _banned_discord.clear(); _banned_roblox.clear(); _reset_log.clear()
        _state_salt = data.get("salt") or _state_salt
        for h, r in (data.get("records") or {}).items():
            _records[h] = dict(r)
        _rebuild_indexes()
        _banned_discord.update({int(k): v for k, v in (data.get("banned_discord") or {}).items()})
        _banned_roblox.update({int(k): v for k, v in (data.get("banned_roblox") or {}).items()})
        _reset_log.update({int(k): list(v) for k, v in (data.get("reset_log") or {}).items()})


def _rebuild_indexes():
    """The current key of an account is its newest record."""
    by_d, by_r = {}, {}
    for h, r in _records.items():
        if r["discord_id"] not in by_d or r["created"] > _records[by_d[r["discord_id"]]]["created"]:
            by_d[r["discord_id"]] = h
        if r["roblox_id"] not in by_r or r["created"] > _records[by_r[r["roblox_id"]]]["created"]:
            by_r[r["roblox_id"]] = h
    _by_discord.update(by_d)
    _by_roblox.update(by_r)


# --- HTTP ------------------------------------------------------------------------

def _hit(table, name, limit, now):
    max_hits, window = limit
    dq = table.setdefault(name, deque())
    while dq and now - dq[0] > window:
        dq.popleft()
    if len(dq) >= max_hits:
        return False
    dq.append(now)
    if len(table) > 5000:
        for k in [k for k, v in table.items() if not v or now - v[-1] > window]:
            table.pop(k, None)
    return True


def _client_ip(handler):
    # Behind the host's proxy the real address is the LAST X-Forwarded-For entry
    # (the one the proxy appended); earlier ones can be forged by the caller.
    fwd = handler.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[-1].strip()[:64] if fwd else handler.client_address[0]


def _send(handler, code, payload, extra=None):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    for k, v in (extra or {}).items():
        handler.send_header(k, v)
    # Deliberately no Access-Control-* header: browsers cannot call this from a page.
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass  # the client disconnected before the response arrived -- nothing to do


def handle(handler):
    """Serve POST /v1/verify. Returns True when the request was handled."""
    if urlsplit(handler.path).path.rstrip("/") != "/v1/verify":
        return False
    now = time.time()
    ip = _client_ip(handler)
    with _lock:
        allowed = _hit(_rate_all, ip, RATE_IP, now)
    if not allowed:
        _send(handler, 429, {"status": "rate_limited"}, {"Retry-After": "60"})
        return True
    if handler.command != "POST":
        _send(handler, 405, {"status": "error"}, {"Allow": "POST"})
        return True
    if not _ready:
        # Not an answer about the key: the script treats it as a network error and
        # tries again, instead of being told that a good key is "invalid".
        _send(handler, 503, {"status": "starting"}, {"Retry-After": "15"})
        return True
    try:
        length = int(handler.headers.get("Content-Length", 0) or 0)
    except ValueError:
        length = -1
    if length <= 0 or length > MAX_BODY:
        _send(handler, 400, {"status": "error"})
        return True
    try:
        body = json.loads(handler.rfile.read(length))
        key, roblox_id, version = body["key"], body["robloxUserId"], body.get("v", 1)
        script = body.get("script")
    except (ValueError, KeyError, TypeError, AttributeError):
        _send(handler, 400, {"status": "error"})
        return True
    if (not isinstance(key, str) or isinstance(roblox_id, bool) or not isinstance(roblox_id, int)
            or not 0 < roblox_id < 10 ** 15 or version != 1):
        _send(handler, 400, {"status": "error"})
        return True
    bucket = hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:32]
    with _lock:
        allowed = _hit(_rate_key, bucket, RATE_KEY, now)
    if not allowed:
        _send(handler, 429, {"status": "rate_limited"}, {"Retry-After": "60"})
        return True
    status, expires = verify(key, roblox_id, now)
    count_script(script, status)
    if status != "valid":
        with _lock:
            allowed = _hit(_rate_fail, ip, RATE_FAIL, now)
        if not allowed:
            _send(handler, 429, {"status": "rate_limited"}, {"Retry-After": "60"})
            return True
    _send(handler, 200, {"status": status, "expiresAt": expires})
    return True
