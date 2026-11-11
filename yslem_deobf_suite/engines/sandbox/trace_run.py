#!/usr/bin/env python3
"""Trace du bac a sable, partagee par les moteurs `wearedevs`, `moonsec_trace`, `trace`... :

    python3 ../sandbox/trace_run.py entree.lua sortie.lua "<titre de la famille>"

(0 ok, 1 echec, 2 entree invalide, 3 timeout, 4 prerequis). Execute le script dans le bac a sable
(engines/sandbox/deob.js --no-devirt) et livre la TRACE, etiquetee comme telle.
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
from pathlib import Path

HERE = Path(__file__).resolve().parent
SANDBOX = HERE
SUITE = HERE.parent.parent
MAX_INPUT = int(os.environ.get("ENGINE_MAX_INPUT", 16 * 1024 * 1024))
TIMEOUT = int(os.environ.get("ENGINE_TIMEOUT", 150))


def say(ok, msg, t0):
    print("[engine:trace] %s %s (%.1fs)" % ("ok" if ok else "fail", msg, time.time() - t0), file=sys.stderr, flush=True)


def limits():
    os.setsid()
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main(argv):
    t0 = time.time()
    if len(argv) not in (3, 4):
        print(__doc__, file=sys.stderr)
        return 2
    src, dst = Path(argv[1]).resolve(), Path(argv[2]).resolve()
    title = argv[3] if len(argv) == 4 else "bac a sable"
    if not src.is_file() or src.stat().st_size == 0 or src.stat().st_size > MAX_INPUT:
        say(False, "entree invalide", t0)
        return 2
    sys.path.insert(0, str(SUITE))
    try:
        import bootstrap
        node = bootstrap.ensure_ready(lambda m: None)["node"]
    except Exception as exc:  # noqa: BLE001
        say(False, "prerequis manquant : %s" % exc, t0)
        return 4
    if not (SANDBOX / "deob.js").is_file():
        say(False, "bac a sable engines/sandbox absent", t0)
        return 4
    work = Path(tempfile.mkdtemp(prefix="trace_"))
    try:
        inp, out = work / "input.lua", work / "trace.lua"
        shutil.copyfile(src, inp)
        env = {"PATH": str(Path(node).parent) + os.pathsep + "/usr/local/bin:/usr/bin:/bin", "TMPDIR": str(work),
               "HOME": str(work), "LANG": os.environ.get("LANG", "C.UTF-8")}
        budget = max(10, TIMEOUT - 30)
        cmd = [node, "deob.js", str(inp), "-o", str(out), "--no-devirt", "--timeout", str(budget), "--budget", "30"]
        proc = subprocess.Popen(cmd, cwd=str(SANDBOX), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, preexec_fn=limits)
        try:
            log, _ = proc.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.communicate()
            say(False, "timeout apres %ds" % TIMEOUT, t0)
            return 3
        log_text = (log or b"").decode("utf-8", "replace")
        status = re.search(r"run status: (.*)", log_text)
        status = status.group(1).strip() if status else "inconnu"
        if not out.is_file():
            sys.stderr.write(log_text[-800:])
            say(False, "pas de trace produite", t0)
            return 1
        lines = [l for l in out.read_text("utf-8", "replace").splitlines() if l.strip() and not re.fullmatch(r"--\s*(?:Script:\d+)?", l.strip())]
        head = ["-- TRACE (%s) : ce que le script fait dans le bac a sable, sur UN chemin d'execution." % title,
                "-- Ce n'est PAS le code source d'origine : les branches et boucles non executees manquent.",
                "-- Statut d'execution dans le bac a sable : %s" % status]
        if status != "finished":
            head.append("-- (la trace s'arrete a l'erreur ci-dessus : la fin du script n'est pas visible)")
        if not lines:
            head.append("-- (le script s'est execute jusqu'au bout SANS aucun appel observable dans le bac a sable : rien a montrer)"
                        if status == "finished" else
                        "-- (le script a plante dans le bac a sable AVANT toute action observable : seule l'erreur ci-dessus est connue)")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("\n".join(head + lines) + "\n", "utf-8")
        say(True, "trace de %d ligne(s), statut : %s" % (len(lines), status), t0)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
