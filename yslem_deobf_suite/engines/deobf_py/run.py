#!/usr/bin/env python3
"""
Wrapper uniforme du moteur `deobf_py` (IronBrew1).

    python3 run.py <input.lua> <output.lua>

Codes de sortie : 0 ok, 1 echec de l'outil / pas de sortie, 2 entree invalide,
3 timeout, 4 prerequis manquant (python3/luau).
Variables : ENGINE_MAX_INPUT (defaut 16 Mo), ENGINE_TIMEOUT (defaut 900 s),
LURAPH_LUAU / LURAPH_LUAU_AST (chemins Luau si absents de deobf/bin).
Le script cible ne s'execute que dans le VM Luau (bac a sable envlog.luau) ;
ce wrapper ne l'execute jamais autrement.
"""
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEOBF = os.path.join(HERE, "deobf")
MAX_INPUT = int(os.environ.get("ENGINE_MAX_INPUT", 16 * 1024 * 1024))
TIMEOUT = int(os.environ.get("ENGINE_TIMEOUT", 900))


def status(ok, msg, t0):
    print("[engine:deobf_py] %s %s (%.1fs)" % ("ok" if ok else "fail", msg, time.time() - t0), file=sys.stderr)


def find_luau(name):
    env = os.environ.get("LURAPH_LUAU" if name == "luau" else "LURAPH_LUAU_AST")
    if env and os.path.exists(env):
        return env
    local = os.path.join(DEOBF, "bin", name)
    if os.path.exists(local):
        return local
    return shutil.which(name)


def limits():
    os.setsid()
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main(argv):
    t0 = time.time()
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, dst = os.path.abspath(argv[1]), os.path.abspath(argv[2])
    if not os.path.isfile(src):
        status(False, "entree introuvable", t0)
        return 2
    size = os.path.getsize(src)
    if size == 0 or size > MAX_INPUT:
        status(False, "taille d'entree invalide (%d octets, max %d)" % (size, MAX_INPUT), t0)
        return 2
    luau, ast = find_luau("luau"), find_luau("luau-ast")
    if not luau or not ast:
        status(False, "prerequis manquant : luau / luau-ast (voir engine.json 'requires')", t0)
        return 4
    # les binaires doivent se trouver dans deobf/bin/ pour que le paquet les trouve
    for name, path in (("luau", luau), ("luau-ast", ast)):
        local = os.path.join(DEOBF, "bin", name)
        if not os.path.exists(local):
            os.makedirs(os.path.dirname(local), exist_ok=True)
            os.symlink(path, local)

    with open(src, "rb") as f:
        data = f.read()
    work = tempfile.mkdtemp(prefix="deobf_py_")
    try:
        inp = os.path.join(work, "input.lua")
        shutil.copyfile(src, inp)
        out = os.path.join(work, "output.lua")
        env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
        env["HOME"] = work
        env["TMPDIR"] = work
        if os.environ.get("DEOBF_STAGE2_OUT"):          # second etage (code loadstring'd) : voir deobf_router.py
            env["DEOBF_CHUNKS_DIR"] = os.environ["DEOBF_STAGE2_OUT"]
        rc, tail = 1, ""
        for _ in (0,):
            cmd = [sys.executable, "-I", os.path.join(DEOBF, "deob.py"), inp, "-o", out, "--no-pypy"]
            if os.path.exists(out):
                os.remove(out)
            left = TIMEOUT - (time.time() - t0)
            if left < 30:
                break
            proc = subprocess.Popen(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, preexec_fn=limits)
            try:
                log, _ = proc.communicate(timeout=left)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    proc.kill()
                proc.communicate()
                status(False, "timeout apres %ds" % TIMEOUT, t0)
                return 3
            tail = log.decode("utf-8", "replace")[-1500:]
            rc = proc.returncode
            if rc == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
                break
        if rc != 0 or not os.path.isfile(out) or os.path.getsize(out) == 0:
            sys.stderr.write(tail)
            status(False, "outil en echec (code %s)" % rc, t0)
            return 1
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(out, dst)
        status(True, "deob.py -> %d octets" % os.path.getsize(dst), t0)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
