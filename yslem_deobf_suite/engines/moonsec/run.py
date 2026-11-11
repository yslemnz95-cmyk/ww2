#!/usr/bin/env python3
"""MoonSec V3 engine: python3 run.py <in.lua> <out.lua>

  1. MoonsecDeobfuscator (C#, livre pre-compile dans bin/) devirtualise le script en bytecode Lua 5.1 (-dev).
  2. decom.lua (LuaDec en Lua pur) decompile ce bytecode en source (luadec_run.py, interpreteur Lua isole).
  3. Si la decompilation echoue : on livre le DESASSEMBLAGE (-dis) et on le dit dans l'en-tete (resultat partiel).

Le runtime .NET 9 est fourni par bootstrap.ensure_dotnet() (systeme, sinon archive Microsoft verifiee par SHA-512).
Memoire : le tas .NET est plafonne (~100 Mo) pour tenir sur une petite VM.
Exit : 0 ok | 2 usage | 3 trop gros | 4 .NET indisponible | 5 devirtualisation impossible | 124 timeout."""
import os, re, shutil, signal, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE = os.path.abspath(os.path.join(HERE, "..", ".."))
DLL = os.path.join(HERE, "bin", "MoonsecDeobfuscator.dll")
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = int(os.environ.get("ENGINE_TIMEOUT", "150"))
HEAP_HEX = os.environ.get("MOONSEC_HEAP_HEX", "0x20000000")     # 512 Mo : 96 Mo laissait ~la moitie des echantillons en « Out of memory »


def get_dotnet():
    sys.path.insert(0, SUITE)
    try:
        import bootstrap
        return bootstrap.ensure_dotnet(lambda m: print("[moonsec] " + m, file=sys.stderr, flush=True)), None
    except Exception as exc:  # noqa: BLE001 - BootstrapError ou import : message lisible
        return None, str(exc)


def run(cmd, cwd, env, timeout):
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=max(5, timeout))
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        return 124, b"timeout"
    return p.returncode, out


def main():
    if len(sys.argv) != 3:
        print(__doc__); return 2
    src, dst = sys.argv[1], sys.argv[2]
    if os.path.getsize(src) > MAX_BYTES:
        print("input too large"); return 3
    if not os.path.isfile(DLL):
        print("MoonsecDeobfuscator.dll missing (engines/moonsec/bin)"); return 4
    dn, err = get_dotnet()
    if not dn:
        print(".NET 9 runtime unavailable: " + (err or "")[:300]); return 4
    droot = os.path.dirname(os.path.realpath(dn))
    env = {"PATH": os.environ.get("PATH", ""), "DOTNET_ROOT": droot, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1",
           "HOME": tempfile.gettempdir(), "DOTNET_gcServer": "0", "DOTNET_gcConcurrent": "0", "DOTNET_TieredPGO": "0",
           "DOTNET_GCHeapHardLimit": HEAP_HEX, "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1"}
    t_end = time.monotonic() + TIMEOUT
    tmp = tempfile.mkdtemp(prefix="moonsec_")
    try:
        shutil.copyfile(src, os.path.join(tmp, "in.lua"))
        rc, log = run([dn, DLL, "-dev", "-i", "in.lua", "-o", "out.luac"], tmp, env, t_end - time.monotonic())
        if rc == 124:
            print("timeout"); return 124
        luac = os.path.join(tmp, "out.luac")
        if not os.path.isfile(luac) or os.path.getsize(luac) < 12:
            print("MoonSec V3 devirtualization failed (not MoonSec V3, or unsupported variant): "
                  + log.decode("utf-8", "replace").strip()[:300]); return 5
        # -- decompilation
        res = os.path.join(tmp, "out.lua")
        rc2, log2 = run([sys.executable, os.path.join(HERE, "luadec_run.py"), luac, res], tmp,
                        {"PATH": os.environ.get("PATH", "")}, min(60, t_end - time.monotonic()))
        text, mode, why = None, "", ""
        if rc2 == 0 and os.path.isfile(res) and os.path.getsize(res) > 0:
            text, mode = open(res, "rb").read().decode("utf-8", "replace"), "decompile"
        else:
            why = log2.decode("utf-8", "replace").strip().splitlines()[-1][:120] if log2.strip() else f"exit {rc2}"
            rc3, _ = run([dn, DLL, "-dis", "-i", "in.lua", "-o", "out.txt"], tmp, env, max(10, t_end - time.monotonic()))
            dis = os.path.join(tmp, "out.txt")
            if os.path.isfile(dis) and os.path.getsize(dis) > 0:
                text, mode = open(dis, "rb").read().decode("utf-8", "replace"), "desassemblage"
        if text is None:
            print("MoonSec V3: bytecode recovered but neither decompilation nor disassembly worked: " + why); return 5
        head = f"-- MoonSec V3 [{mode}]" + (f" decompilation indisponible ({why})" if why else "") + "\n"
        with open(dst, "w", encoding="utf-8") as f:
            f.write(head + text)
        shutil.copyfile(luac, dst + ".luac")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
