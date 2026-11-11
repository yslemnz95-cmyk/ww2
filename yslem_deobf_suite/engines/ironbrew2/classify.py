"""Classe chaque micro-operation IronBrew2 en operation Lua 5.1 (forme normalisee, alias resolus)."""
import re
from luaparser import ast, astnodes as A
import dispatch as D
import microops as M

def _src(st):
    return re.sub(r"\s+", " ", M.src(st)).strip()

REC = ["e"]
PROTECT = [("l", "o")]

def norm_stmts(stmts):
    out, alias = [], {}
    for st in stmts:
        raw = _src(st)
        # declaration locale sans valeur : ignoree
        if re.fullmatch(r"local [\w, ]+", raw):
            continue
        m = re.fullmatch(r"(local )?(\w+) ?= ?(" + re.escape(REC[0]) + r" ?\[ ?\d ?\])", raw)
        if m and (m.group(1) or m.group(2) not in PROTECT[0]):
            alias[m.group(2)] = re.sub(r"\s+", "", m.group(3))
            continue
        s = re.sub(r"^local ", "", raw)
        for name, expr in alias.items():                 # substitution sur le texte ESPACE (« Y >= E then » -> pas « Ethen »)
            s = re.sub(r"(?<![\w.])%s(?![\w(])" % re.escape(name), expr, s)
        s = re.sub(r"\s+", "", s)
        out.append(s)
    return out

def micro_key(stmts, rec="e", protect=("l", "o")):
    REC[0] = rec
    PROTECT[0] = tuple(protect)
    return ";".join(norm_stmts(stmts))

if __name__ == "__main__":
    tree = ast.parse(open("/tmp/ms/ib2/ib2_a.lua", encoding="latin-1").read())
    t = D.table(tree)
    keys = {}
    for N in range(0, 80):
        for mo in M.split(t[N]):
            keys.setdefault(micro_key(mo), set()).add(N)
    for k in sorted(keys, key=lambda x: (len(x), x)):
        print(sorted(keys[k])[:4], k[:190])
    print("TOTAL", len(keys))


def micro_raw(stmts):
    """Texte brut de la micro-operation (sans substitution d'alias) : pour les handlers qui redefinissent leurs locaux."""
    out = []
    for st in stmts:
        raw = _src(st)
        if re.fullmatch(r"local [\w, ]+", raw):
            continue
        s = re.sub(r"\s+", "", raw)
        out.append(re.sub(r"^local", "", s))
    return ";".join(out)
