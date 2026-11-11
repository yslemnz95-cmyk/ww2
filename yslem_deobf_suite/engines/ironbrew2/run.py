#!/usr/bin/env python3
"""IronBrew2 engine: python3 run.py <in.lua> <out.lua>

Forks pris en charge (VM = interpreteur Lua 5.1 ecrit en Lua) : IronBrew2 (KrystekYT), SFG ENCRYPTED, NCDev Team Evolution,
AztupBrew, moonstrike.cc, IronBrew2 « V2 » sans en-tete. Le dispatch de la VM est lu dans le script lui-meme (AST), pas dans
une table fixe :
  1. capture   : le deserialiseur de la VM tourne (sandbox, sans le reste du script) et rend le proto.
  2. lift3     : chaque handler est classe par la FORME de ses micro-operations (grammar.py) ; le flux est reconstruit en
                 bytecode Lua 5.1 (verifie par checkcode/undump51).
  3. decom.lua : LuaDec (engines/moonsec) decompile ce bytecode.
Forme de handler inconnue -> echec explicite (exit 5), jamais de sortie inventee.
Exit : 0 ok | 2 usage | 3 trop gros | 5 non reconnu / echec | 124 timeout."""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
MAX_BYTES = 2 * 1024 * 1024
LUADEC = os.path.join(HERE, "..", "moonsec", "luadec_run.py")


def main():
    if len(sys.argv) != 3:
        print(__doc__); return 2
    src, dst = sys.argv[1], sys.argv[2]
    if os.path.getsize(src) > MAX_BYTES:
        print("input too large"); return 3
    tmp = tempfile.mkdtemp(prefix="ib2_")
    try:
        import lift3
        luac = os.path.join(tmp, "out.luac")
        try:
            roles, nbytes, unknown = lift3.lift_file(src, luac)
        except Exception as exc:  # noqa: BLE001 - message lisible, pas de trace
            print(f"IronBrew2 : variante non prise en charge ({type(exc).__name__}: {str(exc)[:200]})"); return 5
        out = os.path.join(tmp, "out.lua")
        p = subprocess.run([sys.executable, LUADEC, luac, out], capture_output=True, text=True, timeout=180,
                           stdin=subprocess.DEVNULL)
        if p.returncode != 0 or not os.path.isfile(out):
            print("IronBrew2 : bytecode leve, decompilation impossible : " + (p.stdout + p.stderr).strip()[-200:]); return 5
        body = open(out, encoding="utf-8", errors="replace").read()
        with open(dst, "w", encoding="utf-8") as f:
            f.write("-- IronBrew2 [decompile]\n" + body)
        shutil.copyfile(luac, dst + ".luac")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
