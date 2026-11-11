#!/usr/bin/env python3
"""
Fidelite de la pile C du bac a sable (FINAL15).

Les scripts Luraph de la famille `_bsdata0` (le fichier f4 / eb0bb500, un chargeur FlowAuth) construisent la cle de
leur vrai programme a partir de controles d'environnement, dont deux sur la pile :
  - une recursion via __index qui doit atteindre "C stack overflow" a la profondeur EXACTE d'un script Roblox (198) ;
  - un parcours de pile : au-dessus du code principal du script il ne doit rien y avoir (debug.info(2, "f") == nil).
Un seul niveau de difference et le piege anti-falsification abime le programme chiffre.

Ce test lance une sonde (script en clair) dans le bac a sable du moteur luraph_v15 et verifie ces deux points.

  python3 tests/test_stack_fidelity.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


PROBE = '''local n, maxn = 0, 0
local function f()
	n += 1
	if n > maxn then maxn = n end
	local x = setmetatable({}, { __index = f })
	local _ = x.foo
	n -= 1
end
local ok, err = pcall(function() local x = setmetatable({}, { __index = f }); return x.bar end)
print("depth", maxn, ok)
print("lvl2", type(debug.info(2, "f")))
'''

sys.path.insert(0, str(ROOT))
import bootstrap  # noqa: E402

state = bootstrap.ensure_ready(need_node=True, need_luau=True)
node = state.get("node") or "node"
deob = ROOT / "engines" / "sandbox" / "deob.js"
with tempfile.TemporaryDirectory(prefix="stackfid_") as td:
    src = Path(td) / "probe.lua"
    src.write_text(PROBE)
    out = Path(td) / "probe_out.lua"
    subprocess.run([node, str(deob), str(src), "-o", str(out), "--no-devirt"], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=600, check=False)
    text = out.read_text(errors="replace") if out.exists() else ""
check('print("depth", 198, false)' in text,
      'recursion __index : "C stack overflow" a 198 niveaux, comme un script Roblox (' +
      (next((l.strip() for l in text.splitlines() if '"depth"' in l), "aucune sortie")) + ")")
check('print("lvl2", "nil")' in text, 'rien au-dessus du code principal du script (debug.info(2, "f") == nil)')

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : pile C fidele a Roblox")
