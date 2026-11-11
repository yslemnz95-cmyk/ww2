#!/usr/bin/env python3
"""
Identification de l'obfuscateur (obf_identify.py + /analyse), SANS reseau : l'appel a l'API du modele est remplace par
une reponse simulee. Verifie : detecteur local, retrait des secrets avant envoi, liste fermee de moteurs, pas de cle ->
aucun appel, la cle n'apparait nulle part, et /analyse affiche l'identification.

  python3 tests/test_identify.py
"""
import asyncio
import json
import os
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("DEOBF_LLM_API_KEY", None)
os.environ["DEOBF_LLM_OFF"] = ""
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


import obf_identify as oi  # noqa: E402

oi.KEY_FILE = ROOT / "tests" / "_pas_de_cle.txt"
S = ROOT / "tests" / "samples"

# 1. detecteur local
r = oi.identify((S / "legaxyobf.lua").read_text("utf-8", "replace"))
check(r["local"] and r["local"][0][0] == "legaxyobf" and r["llm"] is None, "detecteur local : legaxyobf reconnu, aucun appel au modele")
check(oi.identify((S / "plain.lua").read_text())["llm"] is None, "sans cle : aucun appel reseau, aucun avis")

# 2. extrait : secrets retires, taille bornee
hook = "https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-AbCdEfGhIjKlMnOpQrStUvWxYz01"
ex = oi.excerpt("print(1)\n" + hook + "\n" + "A" * 3000 + "\n" + "B" * 5000)
check("AbCdEfGhIjKl" not in ex and "<RETIRE>" in ex, "extrait : jeton de webhook retire")
check(len(ex) < oi.HEAD_CHARS + oi.TAIL_CHARS + 400, "extrait : borne (%d car.)" % len(ex))

# 3. avis du modele (simule) : liste fermee, texte assaini
SECRET = "AQ.cle-de-test-ne-doit-jamais-apparaitre"
os.environ["DEOBF_LLM_API_KEY"] = SECRET
seen = {}


def fake_post(url, headers, body, timeout):
    seen.update(url=url, headers=headers, body=body)
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({
        "engine": "pwn_engine; rm -rf /", "obfuscator": "Prometheus `x`\n@everyone", "confidence": 7,
        "reason": "ligne1\nligne2 " + "z" * 500})}]}}]}


oi._CACHE.clear(); oi._post = fake_post
a = oi.llm_identify("local x = 1\n" + hook)
check(a and a["engine"] == "unknown", "moteur hors liste -> unknown (le modele ne choisit jamais un moteur)")
check(a and a["confidence"] == 1.0 and "\n" not in a["obfuscator"] and "`" not in a["obfuscator"], "confiance bornee, texte assaini (pas de ` ni de saut de ligne)")
check(a and len(a["reason"]) <= 240, "raison tronquee")
check(SECRET not in seen["url"] and seen["headers"].get("x-goog-api-key") == SECRET, "cle Gemini en-tete (jamais dans l'URL)")
check("AbCdEfGhIjKl" not in json.dumps(seen["body"]), "le jeton de webhook n'est pas envoye au modele")

# 4. echec reseau : jamais bloquant, jamais la cle
def boom(*a, **k):
    raise urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None)


oi._CACHE.clear(); oi._post = boom
b = oi.identify("print(1)")
check(b["llm"] and b["llm"].get("error") and SECRET not in json.dumps(b), "echec API : message neutre, la cle n'apparait pas")

# 5. repli de modeles Gemini : 503 puis succes
calls = []


def flaky(url, headers, body, timeout):
    calls.append(url)
    if len(calls) == 1:
        raise urllib.error.HTTPError(url, 503, "busy", {}, None)
    return {"candidates": [{"content": {"parts": [{"text": '{"engine":"legaxyobf","obfuscator":"legaxyobf","confidence":0.8,"reason":"x"}'}]}}]}


oi._CACHE.clear(); oi._post = flaky
c = oi.llm_identify("x")
check(c and c["engine"] == "legaxyobf" and len(calls) == 2 and calls[0] != calls[1], "503 -> modele suivant de la chaine")

# 6. /analyse affiche l'identification
from cogs import tools_cog as m  # noqa: E402

oi._CACHE.clear(); oi._post = fake_post
text = (S / "plain.lua").read_text()
cog = m.ToolsCog.__new__(m.ToolsCog)


async def go():
    return await cog._analyse_core(text, text.encode(), "plain.lua")


embed, report = asyncio.run(go())
vals = " ".join(f.value for f in embed.fields)
check("Avis du modèle" in vals and "Avis du modèle" in report and "Identification" in report, "/analyse : identification dans l'embed et le rapport")
check(SECRET not in vals and SECRET not in report, "/analyse : la cle n'est jamais affichee")
check(all(len(f.value) <= 1024 for f in embed.fields), "limites d'embed respectees")

# 7. routeur : le detecteur local ne reconnait rien -> l'avis du modele choisit le moteur (liste fermee) ; sinon echec clair
import tempfile  # noqa: E402
import deobf_router  # noqa: E402

os.environ["DEOBF_LLM_API_KEY"] = SECRET
unk = Path(tempfile.mkdtemp(prefix="idt_")) / "inconnu.lua"
unk.write_text("local a = 1\nprint(a)\n")
ran = []
orig_run = deobf_router.run_engine
deobf_router.run_engine = lambda eng, src, dst, *a, **k: (ran.append(eng.name), {"ok": True, "engine": eng.name, "log": "", "code": 0})[1]
oi._CACHE.clear(); oi._post = lambda *a, **k: {"candidates": [{"content": {"parts": [{"text": '{"engine":"hercules","obfuscator":"Hercules","confidence":0.9,"reason":"x"}'}]}}]}
res = deobf_router.deobfuscate(unk, unk.with_suffix(".out.lua"))
check(ran == ["hercules"] and res["ok"], "routeur : rien reconnu en local -> moteur propose par le modele (%s)" % ran)
ran.clear()
oi._CACHE.clear(); oi._post = lambda *a, **k: {"candidates": [{"content": {"parts": [{"text": '{"engine":"rm_rf","obfuscator":"X","confidence":0.99,"reason":"x"}'}]}}]}
res = deobf_router.deobfuscate(unk, unk.with_suffix(".out.lua"))
check(not ran and not res["ok"], "routeur : moteur hors liste ignore, echec clair")
os.environ.pop("DEOBF_LLM_API_KEY", None)
ran.clear()
res = deobf_router.deobfuscate(unk, unk.with_suffix(".out.lua"))
check(not ran and not res["ok"], "routeur sans cle : comportement d'origine")
deobf_router.run_engine = orig_run

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : identification de l'obfuscateur verifiee")
