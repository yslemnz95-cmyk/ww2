"""Point d'entree : source WeAreDevs obfusque -> Lua reconstruit."""
import json, os, subprocess, tempfile
from pathlib import Path
from .machine import analyse, LiftError
from .prep import prepare
from .funcs import lift_all
from . import render

HERE = Path(__file__).resolve().parent.parent


def parse_ast(path, node, timeout=120):
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        p = subprocess.run([node, str(HERE / "parse.js"), str(path), tmp], capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            errs = [l for l in (p.stderr or "").splitlines() if "Error" in l]
            raise LiftError("analyse syntaxique impossible" + (" : " + errs[0].strip()[:160] if errs else ""))
        with open(tmp) as fh:
            return json.load(fh)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def lift(src_path, node, runner=None):
    """-> (texte Lua, infos). Leve LiftError (ou une autre exception) si le gabarit n'est pas reconnu."""
    text = Path(src_path).read_bytes().decode("latin-1")
    ast = parse_ast(src_path, node)
    prepare(text, ast, runner)
    M = analyse(ast)
    lift_all(M)
    lua, rd, info = render.build(M, runner)
    info["functions"] = len(M.funcs)
    info["blocks"] = sum(len(F.bids) for F in M.funcs.values())
    info["blocks_total"] = len(M.leaves)
    info["fallback_functions"] = sum(1 for ent, v in rd.fcache.items() if v[2] is None)
    return lua, info
