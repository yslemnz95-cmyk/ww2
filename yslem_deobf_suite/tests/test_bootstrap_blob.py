#!/usr/bin/env python3
"""
Regression : le deploiement du bot avait perdu runtime/bin/linux-x86_64/luau (« luau est absent » + « il manque git + cmake »).
Le bootstrap doit reconstruire les binaires depuis luau_blob_linux_x86_64.txt (SHA-256 verifie), sans compiler.

Usage : python3 tests/test_bootstrap_blob.py
"""
import hashlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bootstrap  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


if not bootstrap._is_linux_x86_64():
    print("SKIP : le blob ne concerne que Linux x86_64")
    sys.exit(0)

check(bootstrap.LUAU_BLOB.is_file(), "le blob texte est livre avec la suite")
with tempfile.TemporaryDirectory() as td:
    old = bootstrap.SHIPPED_BIN
    bootstrap.SHIPPED_BIN = Path(td) / "runtime" / "bin" / "linux-x86_64"
    try:
        msgs = []
        check(bootstrap.restore_shipped_from_blob(msgs.append), "restauration depuis le blob reussie")
        for name, sha in bootstrap.LUAU_SHA256.items():
            p = bootstrap.SHIPPED_BIN / name
            check(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == sha, f"{name} restaure, SHA-256 conforme")
        check(bootstrap._luau_works(bootstrap.SHIPPED_BIN / "luau"), "le binaire restaure fonctionne (patch vecteur inscriptible)")
        # un blob altere est refuse
        good = bootstrap.LUAU_BLOB
        bad = Path(td) / "bad.txt"
        txt = good.read_text().splitlines()
        i = next(k for k, l in enumerate(txt) if not l.startswith("#") and len(l) > 50 and k > 5)
        txt[i] = txt[i][:10] + ("A" if txt[i][10] != "A" else "B") + txt[i][11:]
        bad.write_text("\n".join(txt))
        bootstrap.LUAU_BLOB = bad
        for n in ("luau", "luau-ast"):
            (bootstrap.SHIPPED_BIN / n).unlink()
        check(not bootstrap.restore_shipped_from_blob(msgs.append), "un blob altere est refuse")
        check(not (bootstrap.SHIPPED_BIN / "luau").exists(), "aucun binaire douteux n'est ecrit")
        bootstrap.LUAU_BLOB = good
    finally:
        bootstrap.SHIPPED_BIN = old

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : restauration du Luau depuis le blob")
