#!/usr/bin/env python3
"""Uniform sandboxed wrapper: python3 run.py <input.lua> <output.lua>
Hard timeout (process group SIGKILL), input size cap, throwaway cwd, scrubbed env,
CPU/file-size rlimits. Exit 0 only if a non-empty output was produced.
Exit codes: 0 ok, 1 tool failed / no output, 2 usage/bad input, 3 timeout."""
import os, re, resource, shutil, signal, subprocess, sys, tempfile, time

NAME = 'hercules'
HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = int(os.environ.get("ENGINE_TIMEOUT", "120"))
MAX_INPUT = int(os.environ.get("ENGINE_MAX_INPUT", str(16 * 1024 * 1024)))
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def build_cmd(inp, out):
    return [sys.executable, "-I", os.path.join(HERE, "deobfhercules.py"), inp, out]


def limits():
    os.setsid()
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT + 5, TIMEOUT + 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 << 20, 256 << 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))


def status(ok, msg):
    print("[engine:%s] %s %s" % (NAME, "ok" if ok else "fail", msg), file=sys.stderr)


def main():
    if len(sys.argv) != 3:
        status(False, "usage: run.py <input.lua> <output.lua>")
        return 2
    src, dst = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    try:
        size = os.path.getsize(src)
    except OSError as e:
        status(False, "cannot stat input: %s" % e.strerror)
        return 2
    if size == 0 or size > MAX_INPUT:
        status(False, "input size %d outside 1..%d" % (size, MAX_INPUT))
        return 2
    work = tempfile.mkdtemp(prefix="engine_%s_" % NAME)
    t0 = time.time()
    try:
        inp, out = os.path.join(work, "input.lua"), os.path.join(work, "output.lua")
        shutil.copyfile(src, inp)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": work, "TMPDIR": work, "LANG": "C.UTF-8"}
        p = subprocess.Popen(build_cmd(inp, out), cwd=work, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, preexec_fn=limits)
        try:
            log, _ = p.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.communicate()
            status(False, "timeout after %ds (process group killed)" % TIMEOUT)
            return 3
        text = ANSI.sub("", log.decode("utf-8", "replace"))
        if p.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            why = next((l for l in reversed(lines) if re.search(r"fail|error|not |incomplete|unsupported|\[!\]|\[FAIL\]", l, re.I)),
                       lines[-1] if lines else "no output")
            status(False, "rc=%s %s" % (p.returncode, why.replace(work, "<tmp>")[:200]))
            return 1
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copyfile(out, dst)
        extra = ""

        status(True, "in=%d out=%d t=%.1fs%s" % (size, os.path.getsize(dst), time.time() - t0, extra))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
