#!/usr/bin/env python3
"""
Moteur wearedevs : detection (avec ou sans en-tete), reconstruction du Lua (machine a etats relevee, chaines dechiffrees),
verification dans le bac a sable, repli sur la trace quand le releve est impossible.

Usage : python3 tests/test_wearedevs.py
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import deobf_router as R  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


S = ROOT / "tests" / "samples"
AST = ROOT / "engines" / "sandbox" / "bin" / "luau-ast"


def run(sample_path, extra=()):
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.lua"
        p = subprocess.run([sys.executable, "-I", str(ROOT / "deobf_router.py"), "run", str(sample_path), str(out), "--json", *extra],
                           capture_output=True, text=True, timeout=600)
        res = json.loads(p.stdout.strip().splitlines()[-1])
        body = out.read_text("utf-8") if out.exists() else ""
        ok_syntax = None
        if body and AST.exists():
            ok_syntax = subprocess.run([str(AST), str(out)], capture_output=True).returncode == 0
        return res, body, ok_syntax


# --- detection ---
text = (S / "wearedevs.lua").read_text("latin-1")
d = R.detect_text(text)
check(bool(d) and d[0][0] == "wearedevs" and d[0][1] >= R.MIN_CONFIDENCE, f"en-tete WeAreDevs reconnu ({d[:1]})")
nh = R.detect_text((S / "wearedevs_noheader.lua").read_text("latin-1"))
check(bool(nh) and nh[0][0] == "wearedevs" and nh[0][1] >= R.MIN_CONFIDENCE, f"modele sans en-tete reconnu ({nh[:1]})")
for other in ("legaxyobf.lua", "ironbrew1.lua", "hercules_vm.lua", "ironveil.lua", "plain.lua"):
    dd = R.detect_text((S / other).read_text("latin-1"))
    check(not (dd and dd[0][0] == "wearedevs"), f"{other} : pas pris pour WeAreDevs")
check(not R.detect_text('local x = "wearedevs.net/obfuscator"\nprint(x)\n') or
      R.detect_text('local x = "wearedevs.net/obfuscator"\nprint(x)\n')[0][0] != "wearedevs",
      "la simple mention de l'adresse (pas en en-tete) ne declenche pas le moteur")

# --- reconstruction : script avec cle, tables chiffrees, anti-alteration ---
res, body, syn = run(S / "wearedevs_payload.lua")
check(res["ok"] and res["engine"] == "wearedevs", f"routeur : moteur wearedevs, ok ({res.get('engine')}, {res.get('ok')})")
check(body.startswith("-- Source RECONSTRUIT (WeAreDevs"), "la sortie est etiquetee Source RECONSTRUIT (pas presentee comme l'original)")
check("PAS le fichier d'origine" in body, "la sortie dit que ce n'est pas le fichier d'origine")
check("VERIFIE" in body.split("local ", 1)[0], "verification : traces du bac a sable identiques")
check("Fluent-Renewed" in body and "loadstring" in body and "HttpGet" in body, "URL et appels recuperes en clair")
check("Verification System" in body and "Copy Discord Link" in body and "discord.gg/cmq6hjxAhq" in body, "interface et lien Discord en clair")
check(re.search(r"Chaines chiffrees : (\d+) / \1 dechiffrees", body) is not None, "toutes les chaines chiffrees sont dechiffrees")
check(syn is not False, "le Lua reconstruit est syntaxiquement valide")
check(len(body.splitlines()) < 2000, f"pas d'explosion de taille ({len(body.splitlines())} lignes)")

# --- modele sans en-tete, script minuscule ---
res, body, syn = run(S / "wearedevs_noheader.lua")
check(res["ok"] and "Source RECONSTRUIT" in body and "discord.gg/D72Y2RvKz" in body and 'setclipboard(' in body, "modele sans en-tete : source reconstruit")

# --- ancienne generation du modele (chaines a deux encodages, tables-registres) ---
res, body, syn = run(S / "wearedevs.lua")
check(res["ok"] and "Source RECONSTRUIT" in body and "[NugHub] Inicializando" in body, "ancienne generation : source reconstruit")
check(syn is not False, "ancienne generation : Lua valide")
check(len(body.splitlines()) < 20000, f"ancienne generation : taille raisonnable ({len(body.splitlines())} lignes)")

# --- repli : en-tete WeAreDevs mais pas la machine a etats -> trace etiquetee ---
with tempfile.TemporaryDirectory() as td:
    fake = Path(td) / "fake.lua"
    fake.write_text('--[[ v1.0.0 https://wearedevs.net/obfuscator ]] print("bonjour")\n')
    res, body, syn = run(fake)
    check(res["ok"] and body.startswith("-- TRACE (WeAreDevs") and "n'a pas abouti" in body and "bonjour" in body,
          "repli : trace etiquetee quand le releve est impossible")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : moteur wearedevs verifie")
