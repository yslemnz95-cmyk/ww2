#!/usr/bin/env python3
"""
lua_sandbox.py -- trace de COMPORTEMENT d'un script Lua/Luau (utilise par /analyse).

    echo 'game:HttpGet("https://x")' | python3 lua_sandbox.py      # code sur stdin -> JSON sur stdout

Le script est execute dans le Luau PATCHE du harnais de engines/sandbox (`deob.js --no-devirt`) :
HttpGet, loadstring, requetes HTTP, presse-papiers, fichiers... sont des proxys qui JOURNALISENT l'appel au
lieu de le faire (aucun acces reseau / disque reel depuis Luau). Ce n'est pas une isolation systeme : limite
CPU (RLIMIT_CPU), dossier temporaire jetable, environnement epure, groupe de processus tue au timeout.

Sortie : {"ok": bool, "calls": [{"type": "http"|"loadstring"|"clipboard"|"file", ...}], "output": [lignes print],
          "status": "finished" | "script error: ...", "error": "..."(si le bac a sable lui-meme a echoue)}
Le script soumis n'est JAMAIS execute par le processus Python du bot.
"""
from __future__ import annotations

import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bootstrap  # noqa: E402

MAX_CODE = 2 * 1024 * 1024
RUN_TIMEOUT = int(os.environ.get("SANDBOX_RUN_TIMEOUT", "40"))     # secondes, tout compris


def _limits() -> None:
    os.setsid()
    resource.setrlimit(resource.RLIMIT_CPU, (RUN_TIMEOUT, RUN_TIMEOUT + 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))


_STR = r'"((?:[^"\\]|\\.)*)"'


def _unq(s: str) -> str:
    return (s.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\"))


def parse_trace(text: str) -> tuple[list[dict], list[str]]:
    """Le resultat du mode `--no-devirt` est le script de comportement observe (une instruction par appel
    journalise) : on en extrait les appels interessants."""
    calls: list[dict] = []
    output: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.search(r"(?:HttpGet|HttpGetAsync)\(\s*" + _STR, line)
        if m:
            calls.append({"type": "http", "method": "GET", "url": _unq(m.group(1))})
            continue
        if re.search(r"(?:request|http_request|syn\.request|http\.request|HttpService:RequestAsync|PostAsync)\b", line):
            url = re.search(r'[Uu]rl\s*=\s*' + _STR, line)
            meth = re.search(r'[Mm]ethod\s*=\s*' + _STR, line)
            body = re.search(r'[Bb]ody\s*=\s*' + _STR, line)
            if not url:
                url = re.search(r"PostAsync\(\s*" + _STR, line)
            if url:
                c = {"type": "http", "method": _unq(meth.group(1)) if meth else "POST" if "PostAsync" in line else "GET",
                     "url": _unq(url.group(1))}
                if body:
                    c["body_preview"] = _unq(body.group(1))[:200]
                calls.append(c)
                continue
        m = re.search(r"\bloadstring\(\s*(?:" + _STR + r"|([\w.]+))", line)
        if m:
            calls.append({"type": "loadstring", "preview": _unq(m.group(1))[:200] if m.group(1) is not None else (m.group(2) or "")})
            continue
        m = re.search(r"\b(?:setclipboard|toclipboard)\(\s*" + _STR, line)
        if m:
            calls.append({"type": "clipboard", "value": _unq(m.group(1))[:200]})
            continue
        m = re.search(r"\b(writefile|readfile|appendfile|delfile|makefolder|isfile|listfiles)\(\s*" + _STR, line)
        if m:
            calls.append({"type": "file", "op": m.group(1), "path": _unq(m.group(2))[:200]})
            continue
        m = re.match(r"(?:print|warn)\((.*)\)\s*$", line)
        if m:
            arg = m.group(1).strip()
            q = re.fullmatch(_STR, arg)
            output.append((_unq(q.group(1)) if q else arg)[:300])
    return calls[:200], output[:100]


def run(code: str) -> dict:
    try:
        node = bootstrap.ensure_ready(lambda m: None)["node"]
    except bootstrap.BootstrapError as exc:
        return {"ok": False, "error": f"preparation impossible : {exc}"}
    work = Path(tempfile.mkdtemp(prefix="sandbox_"))
    try:
        inp, out = work / "input.lua", work / "trace.lua"
        inp.write_bytes(code.encode("utf-8", "replace"))
        env = {"PATH": str(Path(node).parent) + os.pathsep + "/usr/local/bin:/usr/bin:/bin", "TMPDIR": str(work),
               "HOME": str(work), "LANG": os.environ.get("LANG", "C.UTF-8")}
        cmd = [node, "deob.js", str(inp), "-o", str(out), "--no-devirt",
               "--timeout", str(max(5, RUN_TIMEOUT - 10)), "--budget", "8"]
        proc = subprocess.Popen(cmd, cwd=str(HERE / "engines" / "sandbox"), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, preexec_fn=_limits)
        try:
            log, _ = proc.communicate(timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.communicate()
            return {"ok": False, "error": f"Timeout ({RUN_TIMEOUT}s)"}
        log_text = (log or b"").decode("utf-8", "replace")
        status = re.search(r"run status: (.*)", log_text)
        if not out.exists():
            if re.search(r"timed out after|Timeout", log_text):
                return {"ok": False, "error": f"délai dépassé : le script est trop lent à tracer dans le bac à sable "
                                              f"({max(5, RUN_TIMEOUT - 10)} s) -- typique d'une VM d'obfuscation lourde ; "
                                              "/process peut le déobfusquer"}
            return {"ok": False, "error": ("pas de trace produite : " + " ".join(log_text[-300:].split())).strip()}
        calls, output = parse_trace(out.read_text(encoding="utf-8", errors="replace"))
        return {"ok": True, "calls": calls, "output": output, "status": status.group(1).strip() if status else ""}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    data = sys.stdin.buffer.read(MAX_CODE + 1)
    if not data.strip():
        print(json.dumps({"ok": False, "error": "code vide"}))
        return 0
    if len(data) > MAX_CODE:
        print(json.dumps({"ok": False, "error": "code trop gros"}))
        return 0
    print(json.dumps(run(data.decode("utf-8", "replace")), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
