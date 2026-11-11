#!/usr/bin/env python3
"""
Pipeline reel (vrais moteurs, vrais echantillons) a travers le bot : decision automatique, nettoyage des bannieres, statut honnete
(reussi / partiel / echec), UN seul message par operation, aucune protection d'acces contournee.

Usage : python3 tests/test_pipeline_real.py
"""
import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path

import discord

SUITE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE.parent))
sys.path.insert(0, str(SUITE))
os.environ["DEOBF_DATA_DIR"] = tempfile.mkdtemp(prefix="pipe_data_")
os.environ.pop("DEOBF_ALLOWED_IDS", None)
os.environ["DEOBF_PICKER"] = "0"

import stats_store as ST  # noqa: E402
from yslem_deobf_suite.cogs import tools_cog as L  # noqa: E402

FAILS = []
OWNER = 111
S = SUITE / "tests" / "samples"


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label, flush=True)
    if not cond:
        FAILS.append(label)


class Msg:
    def __init__(self, embed, files, content):
        self.embed, self.files, self.content, self.deleted, self.edits = embed, files, content, False, []

    async def edit(self, content=None, embed=None, **kw):
        self.edits.append(embed)
        if embed is not None:
            self.embed = embed

    async def delete(self):
        self.deleted = True

    @property
    def text(self):
        d = self.embed.to_dict() if self.embed is not None else {}
        return "\n".join([self.content or "", d.get("title", ""), d.get("description", "")]
                         + [f"{f['name']} {f['value']}" for f in d.get("fields", [])])


class Chan:
    def __init__(self):
        self.msgs = []

    async def send(self, content=None, embed=None, files=None, **kw):
        m = Msg(embed, {f.filename: f.fp.read() for f in (files or [])}, content)
        self.msgs.append(m)
        return m


class Resp:
    def is_done(self):
        return True


class FUser:
    id = OWNER
    mention = "<@111>"

    async def create_dm(self):
        raise RuntimeError("pas de MP")


def inter():
    return types.SimpleNamespace(user=FUser(), guild=None, channel=Chan(), channel_id=7, response=Resp(), client=None,
                                 followup=types.SimpleNamespace(send=None))


async def run(name: str, raw: bytes, moteur="auto"):
    i = inter()
    L._cache_get = lambda sha, m: None
    await L.run_items(i, [(name, raw)], moteur, 600, True)
    res = [m for m in i.channel.msgs if m.files]
    if os.environ.get("TDEBUG"):
        print("DEBUG", name, [m.text for m in i.channel.msgs])
    return i, (res[0] if res else None), [m for m in i.channel.msgs if not m.files]


async def main():
    ST.reset_stats_for_tests(Path(os.environ["DEOBF_DATA_DIR"]) / "stats.json")
    # 1. legaxyobf : source complet
    i, res, boards = await run("legaxy.lua", (S / "legaxyobf.lua").read_bytes())
    out = next(iter(res.files.values())).decode() if res else ""
    check(res is not None and "Deobfuscation successful" in res.text, "legaxyobf : statut REUSSI affiche")
    check(res is not None and "legaxyobf" in res.text and "Duration" in res.text and "legaxy.lua" in res.text, "embed : fichier, protection, moteur, duree")
    check(res is not None and len(res.text) < 400, f"message court ({len(res.text) if res else '-'} caracteres)")
    check(len(i.channel.msgs) <= 2 and all(b.deleted for b in boards), "UN seul message restant : le suivi est retire apres livraison")

    # 2. MoonSec V2 : trace -> PARTIEL, jamais « reussi » ; en-tete de trace retire du fichier
    i, res, boards = await run("moon.lua", (S / "moonsec_v2.lua").read_bytes())
    out = next(iter(res.files.values())).decode() if res else ""
    check(res is not None and "⚠️" in res.text and "Deobfuscation successful" not in res.text, "MoonSec V2 (trace) : statut PARTIEL, pas « reussi »")
    check(res is not None and "trace d'exécution" in res.text, "partiel : la raison est dite (trace d'execution)")
    check("-- TRACE" not in out and "Ce n'est PAS" not in out and "warning:" not in out, "fichier : en-tete de trace et avertissements retires")

    # 2b. MoonSec V3 : devirtualise + decompile (LuaDec) -> source lisible mais approximatif (upval_N) = PARTIEL, dit clairement
    i, res, boards = await run("moon3.lua", (S / "moonsec_v3.lua").read_bytes())
    out = next(iter(res.files.values())).decode() if res else ""
    check(res is not None and "⚠️" in res.text and "moonsec_v3" in res.text and "upval_N" in res.text and "Deobfuscation successful" not in res.text,
          "MoonSec V3 : moteur de devirtualisation, PARTIEL (decompilation approximative), raison dite")
    check("loadstring(game:HttpGet(" in out and "-- MoonSec V3 [" not in out and "-- filename:" not in out and "protected with MoonSec" not in out,
          "MoonSec V3 : vrai script recupere, en-tetes du moteur retires")

    # 3. WeAreDevs avec payload : reussi, en-tete retire
    i, res, boards = await run("hub.lua", (S / "wearedevs_payload.lua").read_bytes())
    out = next(iter(res.files.values())).decode() if res else ""
    check(res is not None and "Deobfuscation successful" in res.text, "WeAreDevs (payload) : REUSSI")
    check("Source RECONSTRUIT" not in out and "Verification :" not in out and "Fluent-Renewed" in out, "WeAreDevs : bannieres retirees, code conserve")

    # 4. script lisible : rien a deobfusquer, aucun moteur lance
    i, res, boards = await run("plain.lua", (S / "plain.lua").read_bytes())
    check(res is not None and "aucune obfuscation" in res.text, "script lisible : « aucune obfuscation detectee », fichier renvoye")

    # 5. Luraph : non pris en charge, dit clairement, aucun fichier
    i, res, boards = await run("lu.lua", b"-- This file was protected using Luraph Obfuscator v14.4 [https://lura.ph/]\nreturn(function(...)end)()\n")
    last = i.channel.msgs[-1]
    check(res is None and "Failed" in last.text and "Luraph" in last.text and "plus pris en charge" in last.text, "Luraph : echec court, « n'est plus pris en charge »")

    # 6. Luarmor : protection d'acces reconnue, rien de telecharge ni contourne
    i, res, boards = await run("l.lua", b'getgenv().script_key="k"\nloadstring(game:HttpGet("https://api.luarmor.net/files/v3/loaders/abc.lua"))()\n')
    last = i.channel.msgs[-1]
    check(res is None and "Luarmor" in last.text and "key" in last.text and "not bypass" in last.text, "Luarmor : protege, cle requise, non contourne")

    # 7. contenu invalide
    i, res, boards = await run("p.lua", b"<!DOCTYPE html><html><head><title>404</title></head><body>x</body></html>")
    check(res is None and "HTML" in i.channel.msgs[-1].text, "page HTML : refus court et clair")

    # 8. statistiques
    sn = ST.stats().snapshot()
    check(sn["deobf"] == 8 and sn["success"] >= 3 and sn["partial"] >= 2 and sn["failed"] >= 3, f"statistiques : {sn['success']} reussies, {sn['partial']} partielle(s), {sn['failed']} echec(s)")
    # 9. journal technique pour l'administrateur
    logs = list((L._find_suite() / "logs" / "jobs").glob("*.log"))
    check(bool(logs), "journal technique complet dans logs/jobs/ (reserve a l'administrateur)")


asyncio.run(main())
print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : pipeline reel (decision, nettoyage, statut honnete)")
