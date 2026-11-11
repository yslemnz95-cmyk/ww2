#!/usr/bin/env python3
"""
Moteur wearedevs : WeAreDevs obfuscator / Prometheus (machine a etats aplatie).

    python3 run.py entree.lua sortie.lua

Reconstruit un Lua EQUIVALENT (pas le fichier d'origine : les noms de variables sont perdus) en relevant la machine a etats :
blocs, graphe de flot, variables, fermetures, chaines chiffrees (dechiffrees par execution dans le bac a sable).
Verifie ensuite le resultat (compilation + trace du bac a sable comparee a celle de l'original). Si le releve est impossible
ou donne un resultat pire que l'original, livre la TRACE du bac a sable, etiquetee comme telle.
Codes : 0 ok, 1 echec, 2 entree invalide, 3 timeout, 4 prerequis.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = HERE.parent.parent
SANDBOX = SUITE / "engines" / "sandbox"
TRACE_RUN = SANDBOX / "trace_run.py"
MAX_INPUT = int(os.environ.get("ENGINE_MAX_INPUT", 16 * 1024 * 1024))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SUITE))


def say(ok, msg, t0):
    print("[engine:wearedevs] %s %s (%.1fs)" % ("ok" if ok else "fail", msg, time.time() - t0), file=sys.stderr, flush=True)


def one_line(text):
    return " ".join("\n".join(l for l in text.split("\n") if not l.strip().startswith("--")).split("\n"))


def run_trace(path, title, timeout=90):
    """trace du bac a sable : texte de la trace ('' si impossible)"""
    work = tempfile.mkdtemp(prefix="wadv_")
    out = Path(work) / "t.txt"
    env = dict(os.environ, ENGINE_TIMEOUT=str(timeout + 30))
    try:
        subprocess.run([sys.executable, "-I", str(TRACE_RUN), str(path), str(out), title], capture_output=True, text=True, timeout=timeout + 60, env=env)
        return out.read_text("utf-8", "replace") if out.exists() else ""
    except subprocess.TimeoutExpired:
        return ""
    finally:
        shutil.rmtree(work, ignore_errors=True)


def trace_body(t):
    return [l for l in t.splitlines() if not l.startswith(("-- TRACE", "-- Ce n", "-- warning", "-- (la trace", "-- (le script"))]


def status_of(t):
    m = re.search(r"Statut d'execution dans le bac a sable : (.*)", t)
    return m.group(1).strip() if m else ""


def fallback_trace(src, dst, why, t0):
    p = subprocess.run([sys.executable, "-I", str(TRACE_RUN), str(src), str(dst), "WeAreDevs obfuscator"], capture_output=True, text=True)
    if p.returncode != 0 or not Path(dst).exists():
        sys.stderr.write(p.stderr)
        say(False, "ni releve ni trace (%s)" % why, t0)
        return p.returncode or 1
    body = Path(dst).read_text("utf-8", "replace").split("\n")
    note = "-- (le releve de la machine a etats n'a pas abouti : %s ; trace du bac a sable livree a la place)" % why.replace("\n", " ")[:200]
    Path(dst).write_text("\n".join(body[:1] + [note] + body[1:]), "utf-8")
    say(True, "trace de repli (%s)" % why[:100], t0)
    return 0


def main(argv):
    t0 = time.time()
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, dst = Path(argv[1]).resolve(), Path(argv[2]).resolve()
    if not src.is_file() or src.stat().st_size == 0 or src.stat().st_size > MAX_INPUT:
        say(False, "entree invalide", t0)
        return 2
    try:
        import bootstrap
        node = bootstrap.ensure_ready(lambda m: None)["node"]
    except Exception as exc:  # noqa: BLE001
        say(False, "prerequis manquant : %s" % exc, t0)
        return 4
    from wadlift import api

    work = Path(tempfile.mkdtemp(prefix="wadlift_"))
    try:
        def runner(text):
            p = work / "dec.lua"
            p.write_text(one_line(text), "utf-8")
            return run_trace(p, "dechiffrement", 60)

        try:
            lua, info = api.lift(src, node, runner)
        except Exception as exc:  # noqa: BLE001
            return fallback_trace(src, dst, "%s: %s" % (type(exc).__name__, exc), t0)
        lifted = work / "lifted.lua"
        lifted.write_text(lua, "utf-8")
        ast_bin = SANDBOX / "bin" / "luau-ast"
        if ast_bin.exists():
            r = subprocess.run([str(ast_bin), str(lifted)], capture_output=True)
            if r.returncode != 0:
                return fallback_trace(src, dst, "le Lua reconstruit ne compile pas", t0)
        # verification : memes actions dans le bac a sable
        one = work / "one.lua"
        one.write_text(one_line(lua), "utf-8")
        ta, tb = run_trace(src, "original"), run_trace(one, "reconstruit")
        verdict = "non verifie (trace de l'original indisponible)"
        if ta and tb:
            sa, sb = status_of(ta), status_of(tb)
            if trace_body(ta) == trace_body(tb):
                verdict = "VERIFIE : le bac a sable observe exactement les memes actions que pour le fichier d'origine"
            elif sa.startswith("finished") and not sb.startswith("finished"):
                return fallback_trace(src, dst, "le reconstruit se comporte moins bien que l'original (%s)" % sb[:60], t0)
            elif sa.startswith("finished") and sb.startswith("finished"):
                verdict = "les deux terminent dans le bac a sable mais les traces different (le script utilise peut-etre de l'aleatoire ou du temps)"
            elif not sa.startswith("finished") and sb.startswith("finished"):
                verdict = "l'original plante dans le bac a sable (%s), le reconstruit va jusqu'au bout" % sa[:60]
            else:
                verdict = "les deux plantent dans le bac a sable (%s / %s)" % (sa[:40], sb[:40])
        head = ["-- Source RECONSTRUIT (WeAreDevs obfuscator) : Lua equivalent obtenu en relevant la machine a etats,",
                "-- PAS le fichier d'origine : les noms de variables sont perdus (v1.., t1.., r_x), la structure est reconstruite.",
                "-- Chaines chiffrees : %d / %d dechiffrees. Fonctions : %d, blocs : %d / %d."
                % (info.get("decrypted", 0), info.get("decrypt_total", 0), info.get("functions", 0), info.get("blocks", 0), info.get("blocks_total", 0)),
                "-- Verification : %s." % verdict,
                "-- Le fichier contient aussi le code parasite de l'obfuscateur (anti-alteration, dechiffrement) : il fait partie du script.", ""]
        dst.write_text("\n".join(head) + lua, "utf-8")
        say(True, "reconstruit : %d lignes ; %s" % (lua.count("\n"), verdict[:60]), t0)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def guarded():
    """pile et recursion elargies (les AST d'un fichier de 700 Ko sont tres profonds) ; jamais de trace Python a l'utilisateur"""
    import threading
    box = {"rc": 1}

    def target():
        try:
            box["rc"] = main(sys.argv)
        except BaseException as exc:  # noqa: BLE001
            print("[engine:wearedevs] fail erreur inattendue : %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
            box["rc"] = 1

    sys.setrecursionlimit(60000)
    threading.stack_size(512 * 1024 * 1024)
    th = threading.Thread(target=target)
    th.start()
    th.join()
    return box["rc"]


if __name__ == "__main__":
    sys.exit(guarded())
