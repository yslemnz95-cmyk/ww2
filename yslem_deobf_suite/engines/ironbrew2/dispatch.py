"""Extrait la table opcode N -> bloc (AST) de la VM IronBrew2, a partir de l'AST Lua (luaparser)."""
from luaparser import ast, astnodes as A

OPS = {A.LessOrEqThanOp: "<=", A.GreaterOrEqThanOp: ">=", A.EqToOp: "==", A.LessThanOp: "<", A.GreaterThanOp: ">", A.NotEqToOp: "~="}

OPV = ["t"]

def _cond(test):
    op = OPS.get(type(test))
    if op is None or not isinstance(test.left, A.Name) or test.left.id != OPV[0]:
        return None
    if not isinstance(test.right, A.Number):
        return None
    return op, int(test.right.n)

def _ok(c, N):
    op, v = c
    return {"<=": N <= v, ">=": N >= v, "==": N == v, "<": N < v, ">": N > v, "~=": N != v}[op]

IFS = (A.If, A.ElseIf)

def dispatch_root(tree):
    for w in ast.walk(tree):
        if isinstance(w, A.While):
            for s in w.body.body:
                if isinstance(s, A.If) and _cond(s.test):
                    return s
    raise RuntimeError("dispatch introuvable")

def _inner_dispatch(block):
    """Si le bloc ne contient qu'un if de dispatch (sur t), le renvoie ; sinon None."""
    if isinstance(block, IFS) and _cond(block.test):
        return block
    if isinstance(block, A.Block):
        ifs = [s for s in block.body if isinstance(s, IFS) and _cond(s.test)]
        others = [s for s in block.body if not (isinstance(s, IFS) and _cond(s.test)) and type(s).__name__ != "SemiColon"]
        if len(ifs) == 1 and not others:
            return ifs[0]
    return None

def leaf_for(root, N):
    """Descend l'arbre if/elseif/else pour l'opcode N. Renvoie le Block feuille (sans dispatch imbrique)."""
    node = root
    while True:
        if isinstance(node, IFS):
            c = _cond(node.test)
            if c is None:
                raise RuntimeError("cond non dispatch")
            node = node.body if _ok(c, N) else node.orelse
            continue
        if node is None:
            return None
        nxt = _inner_dispatch(node)
        if nxt is None:
            return node
        node = nxt

def table(tree, opv="t", maxn=1024):
    OPV[0] = opv
    root = dispatch_root(tree)
    out = {}
    for N in range(0, maxn):
        leaf = leaf_for(root, N)
        if leaf is None:
            continue
        # garde-fou : une feuille ne doit plus contenir de dispatch
        out[N] = leaf
    return out

if __name__ == "__main__":
    import sys
    src = open(sys.argv[1], encoding="latin-1").read()
    tree = ast.parse(src)
    t = table(tree)
    print("opcodes couverts:", len(t), "min", min(t), "max", max(t))
