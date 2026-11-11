#!/usr/bin/env python3
"""
Regression : une extraction de zip qui perd le bit d'execution ne doit PAS pousser le bot a recompiler Luau (git + cmake absents
-> « le Luau livre ne tourne pas sur Linux x86_64 et il manque git + cmake »). Le bootstrap remet le bit et installe le binaire livre.

Usage : python3 tests/test_bootstrap_noexec.py
"""
import shutil
import stat
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


src = bootstrap.SHIPPED_BIN
if not (src / "luau").exists():
    print("SKIP : pas de binaire livre pour cette plateforme")
    sys.exit(0)

with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    for name in ("luau", "luau-ast"):
        shutil.copy2(src / name, d / name)
        (d / name).chmod(0o644)       # bit d'execution perdu, comme apres certaines extractions
    check(not (d / "luau").stat().st_mode & stat.S_IXUSR, "binaire copie sans bit d'execution")
    check(bootstrap._luau_works(d / "luau"), "le test du binaire remet le bit d'execution et reussit")
    check(bool(d.joinpath("luau").stat().st_mode & stat.S_IXUSR), "le bit d'execution est revenu")
    # raison lisible quand le binaire est absent
    check(not bootstrap._luau_works(d / "absent") and "absent" in bootstrap._LUAU_WHY, "raison de l'echec renseignee (binaire absent)")
    # fichier qui n'est pas un binaire : raison lisible, pas d'exception
    (d / "faux").write_text("pas un binaire")
    (d / "faux").chmod(0o755)
    check(not bootstrap._luau_works(d / "faux") and bootstrap._LUAU_WHY != "", f"binaire invalide : raison lisible ({bootstrap._LUAU_WHY[:70]})")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : bootstrap sans bit d'execution")
