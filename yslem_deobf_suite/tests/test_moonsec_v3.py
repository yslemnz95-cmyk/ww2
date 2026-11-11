#!/usr/bin/env python3
"""
Moteur `moonsec_v3` : devirtualisation (MoonsecDeobfuscator C#) + decompilation (decom.lua / LuaDec), de bout en bout.
Le runtime .NET 9 est celui du systeme ou celui que bootstrap telecharge (SHA-512 verifie) : le test le dit s'il est absent.

Usage : python3 tests/test_moonsec_v3.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bootstrap  # noqa: E402
import deobf_router as R  # noqa: E402
import result_tools as RT  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


S = ROOT / "tests" / "samples"
M = ROOT / "engines" / "moonsec"

# -- fichiers livres
check((M / "bin" / "MoonsecDeobfuscator.dll").is_file() and (M / "decom.lua").is_file() and (M / "luadec_run.py").is_file(),
      "binaire C# pre-compile, decom.lua et luadec_run.py livres")

# -- bootstrap : pas d'archive sans SHA-512, versions figees
for key, (suffix, sha) in bootstrap.DOTNET_ARCHIVES.items():
    check(len(sha) == 128 and all(c in "0123456789abcdef" for c in sha), f".NET {suffix} : SHA-512 fige (128 hex)")
check(bootstrap.DOTNET_VERSION == "9.0.0", "version .NET figee")

# -- archive piegee refusee
import io, tarfile  # noqa: E402,E401
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w") as tf:
    ti = tarfile.TarInfo("../evil.txt"); ti.size = 1; tf.addfile(ti, io.BytesIO(b"x"))
buf.seek(0)
with tempfile.TemporaryDirectory() as td, tarfile.open(fileobj=buf) as tf:
    try:
        list(bootstrap._safe_tar_members(tf, Path(td)))
        check(False, "archive .NET avec chemin '..' refusee")
    except bootstrap.BootstrapError:
        check(True, "archive .NET avec chemin '..' refusee")

# -- detection / decision
text = (S / "moonsec_v3.lua").read_text("latin-1")
d = R.detect_text(text)
check(d[0][0] == "moonsec_v3" and d[0][1] > d[1][1], f"detection : moonsec_v3 avant moonsec_trace ({d[:2]})")
check(not R.load_engines() == [] and [e for e in R.load_engines() if e.name == "moonsec_v3"][0].missing_requirements() == [],
      "prerequis du moteur satisfaits (ou telechargeables)")

# -- bout en bout (le runtime .NET peut etre telecharge au premier passage)
with tempfile.TemporaryDirectory() as td:
    out = Path(td) / "o.lua"
    p = subprocess.run([sys.executable, "-I", str(ROOT / "deobf_router.py"), "run", str(S / "moonsec_v3.lua"), str(out), "--json"],
                       capture_output=True, text=True, timeout=300)
    res = json.loads(p.stdout.strip().splitlines()[-1])
    body = out.read_text("utf-8") if out.exists() else ""
    check(res["ok"] and res["engine"] == "moonsec_v3", f"routeur -> moonsec_v3, ok ({res.get('engine')}, {str(res.get('log'))[-120:]})")
    check(body.startswith("-- MoonSec V3 [decompile]"), "sortie decompilee, etiquetee")
    check("loadstring(game:HttpGet(" in body and "KeySys" in body, "le source recupere contient le vrai script (HttpGet, KeySys)")
    check("This file was protected with MoonSec" not in body, "la couche MoonSec n'est plus la")
    clean, meta = RT.clean_output(body)
    v = RT.classify(res, clean, meta)
    check(clean.startswith("local ") and meta.get("moonsec") == "decompile", "en-tetes du moteur et de LuaDec retires du fichier livre")
    check(v.status == "partial" and "upval" in v.reason, f"classement honnete : PARTIEL tant que des upval_N subsistent ({v.status}: {v.reason})")

# -- classement
V = lambda t, m=None, eng="moonsec_v3": RT.classify({"ok": True, "engine": eng, "log": ""}, t, m or {})  # noqa: E731
check(V("print(1)\n", {"moonsec": "decompile"}).status == "success", "decompile sans upval_N : REUSSI")
check(V("x = upval_3\n", {"moonsec": "decompile"}).status == "partial", "decompile avec upval_N : PARTIEL")
check(V("GETGLOBAL ...\n", {"moonsec": "desassemblage"}).status == "partial", "desassemblage seul : PARTIEL")

# -- decompilation isolee : aucun acces systeme depuis decom.lua
sys.path.insert(0, str(M))
import luadec_run  # noqa: E402
try:
    from lupa import lua51 as _L  # noqa: F401
    have = True
except ImportError:
    have = False
if have:
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "bad.luac"; bad.write_bytes(b"\x1bLua" + b"\x00" * 3)
        r = subprocess.run([sys.executable, str(M / "luadec_run.py"), str(bad), str(Path(td) / "o.lua")], capture_output=True, text=True, timeout=60)
        check(r.returncode == 7 and not (Path(td) / "o.lua").exists(), "bytecode invalide : echec propre (code 7), aucun fichier")
        r = subprocess.run([sys.executable, str(M / "luadec_run.py"), str(Path(td) / "absent.luac"), str(Path(td) / "o.lua")], capture_output=True, text=True, timeout=60)
        check(r.returncode != 0, "fichier absent : echec")
    lua = __import__("lupa.lua51", fromlist=["x"]).LuaRuntime(encoding=None, unpack_returned_tuples=True, register_eval=False, register_builtins=False)
    lua.globals().__DATA, lua.globals().__OUT = b"", lua.eval("{}")
    lua.execute(luadec_run.SHIM)
    check(lua.eval("io.popen == nil and os.execute == nil and os.getenv == nil and require == nil and debug == nil and package == nil"),
          "shim Lua : ni io.popen, ni os.execute, ni require/debug/package")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : moteur moonsec_v3 verifie")
