"""Decoupe chaque handler IronBrew2 en micro-operations (une par emplacement d'instruction)."""
import re, hashlib
from luaparser import ast, astnodes as A
import dispatch as D

def src(node):
    return re.sub(r"\s+", " ", ast.to_lua_source(node)).strip()

def stmts_of(block):
    return [s for s in block.body if type(s).__name__ != "SemiColon"]

import re as _re
def _norm(s):
    return _re.sub(r"\s+", "", src(s))

def is_advance(s, pc="l"):
    # PC = PC + 1
    return type(s).__name__ == "Assign" and _norm(s) == f"{pc}={pc}+1"

def is_fetch(s, pc="l", ins="o"):
    # X = INS[PC]  (X quelconque)
    return type(s).__name__ == "Assign" and _re.fullmatch(rf"\w+={ins}\[{pc}\]", _norm(s)) is not None

def split(block, pc="l", ins="o"):
    """-> liste de micro-ops : chaque micro-op = liste de statements (sans 'PC=PC+1' et 'X=INS[PC]')."""
    ss = stmts_of(block)
    ops, cur = [], []
    i = 0
    while i < len(ss):
        s = ss[i]
        if is_advance(s, pc):
            ops.append(cur); cur = []
            # saute le 'e = o[l]' qui suit
            if i + 1 < len(ss) and is_fetch(ss[i+1], pc, ins):
                i += 2; continue
            i += 1; continue
        cur.append(s)
        i += 1
    ops.append(cur)
    return ops

if __name__ == "__main__":
    tree = ast.parse(open("/tmp/ms/ib2/ib2_a.lua", encoding="latin-1").read())
    t = D.table(tree)
    seen = {}
    for N in range(0, 80):
        h = hashlib.md5(src(t[N]).encode()).hexdigest()[:8]
        seen.setdefault(h, []).append(N)
    for h, ns in seen.items():
        ops = split(t[ns[0]])
        print(f"== opcodes {ns}  ({len(ops)} micro-op(s))")
        for k, mo in enumerate(ops):
            txt = " ; ".join(src(s) for s in mo)
            print(f"   [{k}] {txt[:230]}")
