#!/usr/bin/env python3
"""Moteur `ironbrew2` (IronBrew2 et forks : KrystekYT, SFG, NCDev, AztupBrew, moonstrike, V2 sans en-tete) : detection,
bytecode leve, decompilation, comportement identique a la VM d'origine (scenarios stricts + permissif), polarite des
conditions Lua 5.1, refus propre d'un script qui n'est pas une VM IronBrew2.
Usage : python3 tests/test_ironbrew2.py"""
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests")); sys.path.insert(0, str(ROOT / "engines" / "ironbrew2"))
import decision as D, result_tools as RT  # noqa: E402

FAILS = []
def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label, flush=True)
    if not cond:
        FAILS.append(label)

S = ROOT / "tests" / "samples" / "ironbrew2_krystek.lua"
d = D.decide(S.read_bytes(), S.name)
check(d.engine == "ironbrew2" and d.kind == "source" and d.supported, f"detection : moteur ironbrew2 ({d.title}, {d.engine})")

with tempfile.TemporaryDirectory() as td:
    out = Path(td) / "o.lua"
    p = subprocess.run([sys.executable, "-I", str(ROOT / "deobf_router.py"), "run", str(S), str(out), "--json"],
                       capture_output=True, text=True, timeout=300)
    res = json.loads(p.stdout.strip().splitlines()[-1])
    body = out.read_text("utf-8") if out.exists() else ""
    check(res["ok"] and res["engine"] == "ironbrew2", f"routeur -> ironbrew2 ok ({res.get('engine')})")
    check(Path(str(out) + ".luac").exists(), "bytecode Lua 5.1 ecrit a cote")
    clean, meta = RT.clean_output(body)
    v = RT.classify(res, clean, meta)
    check('loadstring(game:HttpGet("http://ksdteam.ovh' in clean and "KeySys" in clean, "le chargeur d'origine est dans la sortie")
    check(not clean.startswith("-- IronBrew2") and "IronBrew2 [decompile]" not in clean, "bandeau du moteur retire du fichier livre")
    check(v.status == "partial", f"classement honnete : PARTIEL ({v.status}: {v.reason})")

import ib2_behaviour as BEH  # noqa: E402

# -- polarite des conditions (EQ/LT/LE/TEST/TESTSET) sur un VRAI interpreteur Lua 5.1
p = subprocess.run([sys.executable, str(ROOT / "tests" / "ib2_semantics51_test.py")], capture_output=True, text=True, timeout=120)
check(p.returncode == 0, "polarite EQ/LT/LE/TEST/TESTSET (Lua 5.1) : " + (p.stdout.strip().splitlines() or ["?"])[-1][:80])

# -- tous les forks : detection, bytecode charge par Lua 5.1 + verifie, comportement identique a la VM d'origine
import lift3, undump51  # noqa: E402
from lupa import lua51 as L  # noqa: E402
FORKS = ROOT / "tests" / "samples" / "ib2_forks"
# 0-7 : bits d'environnement (strict) ; >= 8 : globaux inconnus = proxys (va plus loin dans le script, mais peut boucler
# longtemps sur les gros scripts : mode permissif reserve aux petits fichiers)
STRICT = (0, 1, 2, 3)
PERMISSIVE = {"sfg_small.lua": (8, 15), "aztupbrew.lua": (8, 15), "v2_noheader.lua": (8, 15), "v2_other.lua": (8, 15)}
for f in sorted(FORKS.glob("*.lua")):
    dd = D.decide(f.read_bytes(), f.name)
    check(dd.engine == "ironbrew2" and dd.supported, f"{f.name} : detection ({dd.title})")
    with tempfile.TemporaryDirectory() as td:
        luac = Path(td) / "k.luac"
        r, n, unk = lift3.lift_file(str(f), str(luac))
        data = luac.read_bytes()
        lua = L.LuaRuntime(unpack_returned_tuples=True); lua.globals().__D = data
        check(lua.eval("loadstring(__D) ~= nil"), f"{f.name} : bytecode charge par Lua 5.1 ({n} o)")
        check(len(undump51.verify(undump51.undump(data))) == 0, f"{f.name} : verificateur Lua 5.1 : 0 violation")
        same = 0
        SCEN = STRICT + PERMISSIVE.get(f.name, ())
        for scen in SCEN:
            o, eo = BEH.run_original(str(f), scen)
            l, el = BEH.run_lifted_env(str(luac), scen)
            same += (o == l and eo == el and len(o) > 5)
        check(same == len(SCEN), f"{f.name} : comportement identique a la VM d'origine ({same}/{len(SCEN)} scenarios)")

# -- le krystek aussi (sample historique), strict
with tempfile.TemporaryDirectory() as td:
    luac = Path(td) / "k.luac"
    lift3.lift_file(str(S), str(luac))
    for scen in range(4):
        o, eo = BEH.run_original(str(S), scen)
        l, el = BEH.run_lifted_env(str(luac), scen)
        check(o == l and eo == el and len(o) > 20, f"krystek scenario {scen} : identique a la VM ({len(o)} evenements)")

# -- un script qui n'est PAS une VM IronBrew2 : refus explicite (code 5), aucune sortie
with tempfile.TemporaryDirectory() as td:
    bad = Path(td) / "bad.lua"; bad.write_text("local a=string.byte;local I=string.char;print(1)\nreturn I(B(),{},s())()")
    out = Path(td) / "o.lua"
    p = subprocess.run([sys.executable, str(ROOT / "engines" / "ironbrew2" / "run.py"), str(bad), str(out)],
                       capture_output=True, text=True, timeout=200)
    check(p.returncode == 5 and not out.exists() and "non prise en charge" in p.stdout, f"non-IronBrew : refus propre (code {p.returncode})")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : moteur ironbrew2 verifie")
