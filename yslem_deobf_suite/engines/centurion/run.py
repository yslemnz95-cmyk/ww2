#!/usr/bin/env python3
"""Centurion v6 engine wrapper: python3 run.py <in.lua> <out.lua>
Only the v6 'static' route yields output (partial: payload factories c3[N]); the v6.1 sandbox route
needs the author's patched Luau + live Roblox and returns verdict NEEDS -> exit 5.
Exit: 0 ok | 2 usage | 3 too large | 4 luau missing | 5 not deobfuscated / empty | 124 timeout."""
import json, os, shutil, signal, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "src")
MAX_BYTES = 3 * 1024 * 1024
TIMEOUT = int(os.environ.get("ENGINE_TIMEOUT", "120"))


def luau(prog):
    for d in (os.environ.get("ENGINE_LUAU_DIR"), os.path.join(HERE, "bin"), os.path.join(HERE, "..", "sandbox", "bin")):
        if d and os.path.isfile(os.path.join(d, prog)):
            return os.path.abspath(os.path.join(d, prog))
    import shutil as sh
    return sh.which(prog)


def main():
    if len(sys.argv) != 3:
        print(__doc__); return 2
    src, dst = sys.argv[1], sys.argv[2]
    if os.path.getsize(src) > MAX_BYTES:
        print("input too large"); return 3
    exe, ast, comp = luau("luau"), luau("luau-ast"), luau("luau-compile")
    if not (exe and ast and comp):
        print("luau / luau-ast / luau-compile not found (set ENGINE_LUAU_DIR)"); return 4
    tmp = tempfile.mkdtemp(prefix="cent_")
    try:
        # private copy: centurion.py writes _ast_tmp.txt next to itself
        for f in ["centurion.py"] + [x for x in os.listdir(TOOL) if x.endswith(".json")]:
            shutil.copyfile(os.path.join(TOOL, f), os.path.join(tmp, f))
        inp = os.path.join(tmp, "input.lua"); shutil.copyfile(src, inp)
        out = os.path.join(tmp, "out"); os.makedirs(out)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp, "CENT_SANDBOX": os.path.join(HERE, "sandbox"),
               "CENT_SAMPLES": tmp, "CENT_LUAU_LUAU": exe, "CENT_LUAU_LUAU_AST": ast, "CENT_LUAU_LUAU_COMPILE": comp}
        p = subprocess.Popen([sys.executable, "-I", "centurion.py", "deobfuscate", inp, "--out-dir", out], cwd=tmp, env=env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            log, _ = p.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL); p.wait(); print("timeout"); return 124
        stage = [f for f in os.listdir(out) if f.endswith("_deobf_stage1.lua")]
        if p.returncode != 0 or not stage or os.path.getsize(os.path.join(out, stage[0])) == 0:
            print("Centurion: not deobfuscated (verdict NEEDS or unknown family): " + log.decode("utf-8", "replace")[-300:]); return 5
        shutil.copyfile(os.path.join(out, stage[0]), dst)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
