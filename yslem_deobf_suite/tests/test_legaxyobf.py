#!/usr/bin/env python3
"""legaxyobf : detection + deobfuscation complete (enveloppe ChaCha20-Poly1305, VM RBXO) par le routeur. Sans reseau.
  python3 tests/test_legaxyobf.py"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


import deobf_router  # noqa: E402

src = ROOT / "tests" / "samples" / "legaxyobf.lua"
det = deobf_router.detect_text(deobf_router.read_text(src))
check(bool(det) and det[0][0] == "legaxyobf" and det[0][1] >= 0.9, "detection : legaxyobf (%s)" % (det[:1],))
# detection sans la ligne d'en-tete
body = "\n".join(src.read_text("latin-1").splitlines()[1:])
det2 = deobf_router.detect_text(body)
check(bool(det2) and det2[0][0] == "legaxyobf", "detection sans l'en-tete : par l'enveloppe RBXE")
with tempfile.TemporaryDirectory() as td:
    out = Path(td) / "out.lua"
    res = deobf_router.deobfuscate(src, out)
    text = out.read_text("utf-8") if out.exists() else ""
check(res.get("ok") and res.get("engine") == "legaxyobf", "routeur : moteur legaxyobf, ok")
check('loadstring(game:HttpGet("https://raw.githubusercontent.com/preexmon-collab/S2rHubByKhay/refs/heads/main/Gehlee_Hub_Stability_v10.lua"))()' in text,
      "programme reel : loadstring(game:HttpGet(<url>))()")
check(text.count("bloc mort retire") == 4 and "print(" not in text, "4 predicats opaques retires, plus aucun print mort")
check("etiquette valide" in text, "etiquette Poly1305 verifiee")
print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : legaxyobf deobfusque")
