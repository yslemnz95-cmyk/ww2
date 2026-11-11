#!/usr/bin/env python3
"""
Non-regression des bugs corriges dans cogs/tools_cog.py et cogs/deobf_cog.py :

  1. _fetch_url tronquait les gros fichiers (StreamReader.read(n) ne rend pas n octets) ;
  2. _fetch_url ne gerait pas les liens « page » (github blob, pastebin) ;
  3. scan()/_heuristic() pouvaient geler la boucle d'evenements (regex quadratique sur 7 Mo) ;
  4. le resultat d'un job de > 15 min ne pouvait plus etre envoye (jeton d'interaction expire) ;
  5. les pieces jointes > limite Discord faisaient echouer l'envoi ;
  6. les handlers d'erreur restaient muets apres un defer().

Usage : python3 tests/test_cog_fixes.py     (discord.py >= 2.3, aiohttp)
"""
import asyncio
import gzip
import http.server
import sys
import threading
import time
import types
from pathlib import Path

import discord

COGS = Path(__file__).resolve().parent.parent / "cogs"
sys.path.insert(0, str(COGS))
import tools_cog as m  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


# -- 1/2 : telechargement ------------------------------------------------------------------------
PAYLOAD = bytes(range(256)) * 4096          # 1 Mo
BIG = b"x" * (m._MAX_BYTES + 10)


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = BIG if self.path.startswith("/big") else PAYLOAD
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        for i in range(0, len(body), 7000):          # petits morceaux + pauses : provoque les lectures partielles
            self.wfile.write(body[i:i + 7000])
            self.wfile.flush()
            if i % 140000 == 0:
                time.sleep(0.01)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]

# l'anti-SSRF refuse (a raison) 127.0.0.1 : on le neutralise pour ce test uniquement
m._is_unsafe_ip = lambda ip: False
name, data = asyncio.run(m._fetch_url(f"http://127.0.0.1:{port}/a/b/script.lua"))
check(data == PAYLOAD, f"_fetch_url rend les {len(PAYLOAD)} octets (recu {len(data)})")
check(name == "script.lua", "nom de fichier deduit de l'URL")
try:
    asyncio.run(m._fetch_url(f"http://127.0.0.1:{port}/big.lua"))
    check(False, "_fetch_url refuse un fichier > limite")
except ValueError:
    check(True, "_fetch_url refuse un fichier > limite")
srv.shutdown()

check(m._normalize_url("https://github.com/u/r/blob/main/a/b.lua") == "https://raw.githubusercontent.com/u/r/main/a/b.lua",
      "github blob -> raw")
check(m._normalize_url("https://pastebin.com/AbC123") == "https://pastebin.com/raw/AbC123", "pastebin -> raw")
check(m._normalize_url("https://pastebin.com/raw/AbC123") == "https://pastebin.com/raw/AbC123", "pastebin raw inchange")
check(m._normalize_url("https://example.com/x.lua") == "https://example.com/x.lua", "autre URL inchangee")

# -- 3 : analyse bornee -------------------------------------------------------------------------
nasty = ("local a = {" + "x" * 300 + "}\n") * 40000          # ~12 Mo de motifs pathologiques
t0 = time.monotonic()
m.scan(nasty)
m._heuristic(nasty, nasty.encode(), "n.lua")
dt = time.monotonic() - t0
check(dt < 20, f"scan + heuristique bornes sur une entree pathologique ({dt:.1f}s)")

# -- 5 : pieces jointes --------------------------------------------------------------------------
items = [("a.lua", b"A" * (9 * 1024 * 1024)), ("log.txt", b"B" * 1024)]
packed, notes = m._pack_files(items)
check(sum(len(b) for _, b in packed) <= m._DISCORD_MAX_UPLOAD and any(n.endswith(".gz") for n, _ in packed),
      "fichier trop gros compresse en gzip")
check(gzip.decompress(dict(packed)["a.lua.gz"]) == items[0][1], "le gzip est fidele")
import os  # noqa: E402
rnd = os.urandom(9 * 1024 * 1024)
packed, notes = m._pack_files([("r.bin", rnd), ("log.txt", b"ok")])
check(not any(n.startswith("r.bin") for n, _ in packed) and packed and notes
      and sum(len(b) for _, b in packed) <= m._DISCORD_MAX_UPLOAD, "incompressible et trop gros -> omis, avec note")


# -- 4/6 : livraison tardive et handlers d'erreur ----------------------------------------------
class FakeFollowup:
    def __init__(self, expired):
        self.expired, self.sent = expired, []

    async def send(self, content=None, **kw):
        if content is not None:
            kw["content"] = content
        if self.expired:
            raise discord.HTTPException(types.SimpleNamespace(status=401, reason="Unauthorized"), "Invalid Webhook Token")
        self.sent.append(kw)


class FakeUser:
    def __init__(self):
        self.dms = []

    async def send(self, **kw):
        self.dms.append(kw)


def inter(expired):
    return types.SimpleNamespace(followup=FakeFollowup(expired), user=FakeUser(),
                                 response=types.SimpleNamespace(is_done=lambda: True))


i = inter(False)
how = asyncio.run(m._deliver(i, "ok", files=[("a.lua", b"x")]))
check(how == "followup" and i.followup.sent and i.followup.sent[0]["ephemeral"] is True, "livraison normale = followup ephemere")
i = inter(True)
how = asyncio.run(m._deliver(i, "ok", files=[("a.lua", b"x")]))
check(how == "dm" and i.user.dms, "jeton expire -> repli en message prive")

cog = m.ToolsCog.__new__(m.ToolsCog)
for handler, label in ((m.ToolsCog.analyse_error, "analyse_error"), (m.ToolsCog.process_error, "process_error")):
    i = inter(False)
    asyncio.run(handler(cog, i, discord.app_commands.AppCommandError("boom")))
    check(len(i.followup.sent) == 1 and "boom" in i.followup.sent[0]["content"], f"{label} repond apres un defer()")

# -- 7 : le compte a rebours du tableau de bord ne remonte jamais ----------------------------------------
import re as _re  # noqa: E402


def _eta(line):
    mm = _re.search(r"reste ~(?:(\d+) min )?(\d+) s", line)
    return int(mm.group(2)) + 60 * int(mm.group(1) or 0) if mm else None


_real_time = time.time
_t = [1000.0]
time.time = lambda: _t[0]
try:
    job = {"name": "x.lua", "kb": 10, "started": 1000.0, "stage": 3, "est": 100}
    ends, lines = [], []
    for el in range(0, 130, 5):                      # 130 s simules : l'estimation (100 s) est depassee
        _t[0] = 1000.0 + el
        if el == 60:
            job["est"] = 190                         # l'estimation change : l'echeance interne ne doit pas reculer
        lines.append(m._job_line(job))
        ends.append(job.get("eta_end"))
finally:
    time.time = _real_time
# l'affichage est volontairement court (plus de « reste ~N s » dans le tableau de bord) ; l'echeance interne reste monotone
vals = [e for e in ends if e is not None]
check(all(a >= b for a, b in zip(vals, vals[1:])), "echeance interne : ne recule jamais quand l'estimation change")
check(not any("reste ~" in l for l in lines) and all("x.lua" in l for l in lines), "tableau de bord court : pas de compte a rebours affiche")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : correctifs des cogs verifies")
