#!/usr/bin/env python3
"""
Moteur `psu_trace` : PSU Obfuscator detecte par sa signature, trace etiquetee, pas de confusion avec les autres moteurs.

Usage : python3 tests/test_psu_trace.py
"""
import json
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
text = (S / "psu.lua").read_text("latin-1")
d = R.detect_text(text)
check(bool(d) and d[0][0] == "psu_trace" and d[0][1] >= R.MIN_CONFIDENCE, f"PSU : psu_trace en premier choix ({d[:1]})")
for other in ("wearedevs.lua", "moonsec_v2.lua", "moonsec_v3.lua", "legaxyobf.lua", "ironbrew1.lua", "hercules_vm.lua", "plain.lua"):
    dd = R.detect_text((S / other).read_text("latin-1"))
    check(not (dd and dd[0][0] == "psu_trace"), f"{other} : pas pris pour PSU")
check(not any(n == "psu_trace" for n, _, _ in R.detect_text('print("PSU Obfuscator")')),
      "la simple mention du nom (pas la signature) ne declenche pas le moteur")
with tempfile.TemporaryDirectory() as td:
    out = Path(td) / "o.lua"
    p = subprocess.run([sys.executable, "-I", str(ROOT / "deobf_router.py"), "run", str(S / "psu.lua"), str(out), "--json"],
                       capture_output=True, text=True, timeout=240)
    res = json.loads(p.stdout.strip().splitlines()[-1])
    body = out.read_text("utf-8") if out.exists() else ""
    check(res["ok"] and res["engine"] == "psu_trace", f"routeur : psu_trace, ok ({res.get('engine')})")
    check(body.startswith("-- TRACE (PSU Obfuscator)") and "PAS le code source d'origine" in body, "sortie etiquetee TRACE")
    check(len(body.splitlines()) > 12, f"trace utile ({len(body.splitlines())} lignes)")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : moteur psu_trace verifie")
