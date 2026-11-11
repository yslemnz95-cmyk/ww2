#!/usr/bin/env python3
"""
Moteur `trace` (a la demande) : jamais choisi automatiquement, trace etiquetee, fonctionne sur un script quelconque.

Usage : python3 tests/test_trace.py
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


SCRIPT = ('local r = game:HttpGet("https://example.com/lib.lua")\n'
          'local w = Instance.new("ScreenGui")\nw.Name = "Demo"\nprint("bonjour")\n')

engines = {e.name: e for e in R.load_engines()}
check("trace" in engines and engines["trace"].safe, "moteur `trace` installe et sur")
d = R.detect_text(SCRIPT)
check(not any(n == "trace" for n, _, _ in d), "jamais choisi automatiquement (aucune regle de detection)")

with tempfile.TemporaryDirectory() as td:
    src, out = Path(td) / "in.lua", Path(td) / "out.lua"
    src.write_text(SCRIPT)
    auto = subprocess.run([sys.executable, "-I", str(ROOT / "deobf_router.py"), "run", str(src), str(out), "--json"],
                          capture_output=True, text=True, timeout=120)
    res = json.loads(auto.stdout.strip().splitlines()[-1])
    check(res["ok"] is False and "--engine trace" in res.get("log", ""), "sans moteur impose : echec clair qui propose `trace`")
    p = subprocess.run([sys.executable, "-I", str(ROOT / "deobf_router.py"), "run", str(src), str(out), "--engine", "trace", "--json"],
                       capture_output=True, text=True, timeout=240)
    res = json.loads(p.stdout.strip().splitlines()[-1])
    body = out.read_text("utf-8") if out.exists() else ""
    check(res["ok"] and res["engine"] == "trace", f"moteur impose : ok ({res.get('engine')})")
    check(body.startswith("-- TRACE") and "PAS le code source d'origine" in body, "sortie etiquetee TRACE")
    check("example.com/lib.lua" in body and 'Instance.new("ScreenGui")' in body and "finished" in body,
          "la trace contient la requete, la creation d'interface et le statut")
    ast_bin = ROOT / "runtime" / "bin" / "linux-x86_64" / "luau-ast"
    if ast_bin.exists():
        check(subprocess.run([str(ast_bin), str(out)], capture_output=True).returncode == 0, "la trace est du Luau valide")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : moteur trace (a la demande) verifie")
