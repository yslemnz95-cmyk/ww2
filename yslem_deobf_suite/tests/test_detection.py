#!/usr/bin/env python3
"""
Detection et second etage (Luraph n'est plus pris en charge : aucune de ses formes ne doit etre reconnue).

  1. aucune forme Luraph (v14 / v15, avec ou sans en-tete) n'est reconnue par un moteur ;
  2. les autres familles restent reconnues (IronBrew1, legaxyobf), un script en clair ne l'est pas ;
  3. le routeur dit clairement que Luraph n'est plus pris en charge ;
  4. second etage : un morceau charge par loadstring est ajoute au resultat (code en clair) et la VM
     interne du meme moteur est ignoree.

Usage : python3 tests/test_detection.py
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import deobf_router as R  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def top(text):
    d = R.detect_text(text)
    return d[0][:2] if d else (None, 0.0)


V14 = ("return({Iy=function(G,R,e,y,Y,C,x)if not(y<=0X27)then return-2,Y,y,R;end;return nil,Y,y;end,"
       "QT=bit32.lshift,NT=bit32.band,Y={61158,2257908990},m=true}):R()(...);\n")
V15 = ('_bsdata0={1793536246,7057464,"\\4\\233"};\n'
       'superflow_bytecode={"\\62\\233" .. _bsdata0[3]};  \n'
       "return setmetatable({aO=function(r,x,H)return 1;end,[83]=type,[10]=Vector3.new,"
       "[126]=coroutine.wrap},{}):Tp()(...);\n\n\n")
V15_HEADER = "-- This file was protected using Luraph Obfuscator v15.1 [https://lura.ph/]\n\nreturn setmetatable({[18]=buffer.readu8,[102]=buffer.copy,M=function(U)end},{}):A()(...);"
V14_HEADER = "-- This file was protected using Luraph Obfuscator v14.7 [https://lura.ph/]\n\nreturn({au=function(H)end}):X()(...);"
PLAIN = 'local Players = game:GetService("Players")\nprint(Players.LocalPlayer.Name)\nreturn({a=function() end}):b()\n'
IRONBREW = "-- This file was generated using IronBrew1\nreturn(function(a,b)end)()\n"
LEGAXY = "-- protected by legaxyobf\nreturn 1\n"

for label, text in (("Luraph v14 sans en-tete", V14), ("Luraph v15 sans en-tete", V15),
                    ("en-tete Luraph v15.1", V15_HEADER), ("en-tete Luraph v14.7", V14_HEADER)):
    check(top(text)[1] < R.MIN_CONFIDENCE, f"{label} : plus reconnu par aucun moteur ({top(text)})")
check(top(PLAIN)[1] < R.MIN_CONFIDENCE, "script en clair : rien de reconnu")
check(top(IRONBREW)[0] == "deobf_py" and top(IRONBREW)[1] >= R.MIN_CONFIDENCE, "IronBrew1 toujours reconnu (deobf_py)")
check(top(LEGAXY)[0] == "legaxyobf", "legaxyobf toujours reconnu")

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "lur.lua"
    p.write_text(V15_HEADER)
    res = R.run_router(p, Path(td) / "out.lua", None, None, False) if hasattr(R, "run_router") else None
    if res is None:
        import subprocess
        out = subprocess.run([sys.executable, "-I", str(ROOT / "deobf_router.py"), "run", str(p), str(Path(td) / "o.lua"), "--json"],
                             capture_output=True, text=True, timeout=120).stdout.strip().splitlines()[-1]
        import json
        res = json.loads(out)
    check(res.get("ok") is False and "Luraph n'est plus pris en charge" in res.get("log", ""),
          "fichier Luraph : message clair « n'est plus pris en charge »")

    # second etage (moteur de reference : legaxyobf)
    s2 = Path(td) / "s2"
    s2.mkdir()
    (s2 / "00000040_a.lua").write_text('print("second etage en clair")\nreturn 1\n')
    (s2 / "00000041_b.lua").write_text(LEGAXY)                   # la VM interne : deja traitee par le meme moteur
    (s2 / "00000042_c.lua").write_text('print("second etage en clair")\nreturn 1\n')   # doublon
    secs = R._stage2_sections(s2, "legaxyobf", 0, time.monotonic() + 600, False)
    check(len(secs) == 1 and 'print("second etage en clair")' in secs[0] and "code en clair" in secs[0],
          "second etage : code en clair ajoute, VM interne et doublon ignores")
    # un second etage non reconnu mais illisible (une ligne de 200 Ko) : signale, pas recopie
    (s2 / "00000044_e.lua").write_text("local a=" + "{" * 1 + ",".join(str(i) for i in range(40000)) + "}")
    secs = R._stage2_sections(s2, "legaxyobf", 0, time.monotonic() + 600, False)
    check(len(secs) == 2 and "non recopies" in secs[1] and len(secs[1]) < 300,
          "second etage : code illisible non reconnu signale sans etre recopie")
    body = secs[0] + "\n-- premier etage\nreturn 2\n" if secs else ""
    import subprocess
    ast_bin = ROOT / "runtime" / "bin" / "linux-x86_64" / "luau-ast"
    if ast_bin.exists():
        def parses(code):
            f = Path(td) / "chk.luau"
            f.write_text(code)
            return subprocess.run([str(ast_bin), str(f)], capture_output=True).returncode == 0
        check(not parses("return 2\nprint(1)\n"), "controle : luau-ast refuse du code invalide")
        check(parses(body), "le resultat avec second etage (premier etage terminant par return) reste du Luau valide")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : detection (sans Luraph) et second etage verifies")
