#!/usr/bin/env python3
"""
Moteur `moonsec_trace` : MoonSec V2 / V3 detectes par leur en-tete (V2 : seul moteur ; V3 : moteur de secours derriere `moonsec_v3` si .NET est indisponible),
trace etiquetee, pas de confusion avec WeAreDevs / PSU / autres.

Usage : python3 tests/test_moonsec_trace.py
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
for ver in ("v2",):
    text = (S / f"moonsec_{ver}.lua").read_text("latin-1")
    d = R.detect_text(text)
    check(bool(d) and d[0][0] == "moonsec_trace" and d[0][1] >= R.MIN_CONFIDENCE, f"MoonSec {ver.upper()} : premier choix = moonsec_trace ({d[:2]})")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.lua"
        p = subprocess.run([sys.executable, "-I", str(ROOT / "deobf_router.py"), "run", str(S / f"moonsec_{ver}.lua"), str(out), "--json"],
                           capture_output=True, text=True, timeout=240)
        res = json.loads(p.stdout.strip().splitlines()[-1])
        body = out.read_text("utf-8") if out.exists() else ""
        check(res["ok"] and res["engine"] == "moonsec_trace", f"MoonSec {ver.upper()} : routeur -> moonsec_trace, ok ({res.get('engine')})")
        check(body.startswith("-- TRACE (MoonSec V2/V3)") and "PAS le code source d'origine" in body, f"MoonSec {ver.upper()} : sortie etiquetee TRACE")
        check(len(body.splitlines()) > 20, f"MoonSec {ver.upper()} : trace utile ({len(body.splitlines())} lignes)")
d3 = R.detect_text((S / "moonsec_v3.lua").read_text("latin-1"))
check([n for n, _, _ in d3[:2]] == ["moonsec_v3", "moonsec_trace"], f"MoonSec V3 : moonsec_v3 d'abord, moonsec_trace en secours ({d3[:2]})")
for other in ("wearedevs.lua", "legaxyobf.lua", "ironbrew1.lua", "hercules_vm.lua", "plain.lua"):
    dd = R.detect_text((S / other).read_text("latin-1"))
    check(not (dd and dd[0][0] in ("moonsec_trace", "moonsec_v3")), f"{other} : pas pris pour MoonSec")
check(not any(n == "moonsec_v3" and c > 0.7 for n, c, _ in R.detect_text('print("moonsec")')), "le simple mot « moonsec » ne declenche plus moonsec_v3")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : moteur moonsec_trace verifie")
