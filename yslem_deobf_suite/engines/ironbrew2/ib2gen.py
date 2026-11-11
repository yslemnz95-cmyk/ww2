"""IronBrew2 generique : detecte les roles (noms de variables) dans la VM de chaque sample, puis classe les
micro-operations avec des motifs parametres. Ne suppose plus les noms de f1b685 (n, e, l, t, c, a, J, ...)."""
import re
from luaparser import ast, astnodes as A
import dispatch as D
import microops as M

TAIL_RX = re.compile(r"return (\w+)\((\w+)\(\),\{\},(\w+)\(\)\)\(\);?")
TAIL_TRUE_RX = re.compile(r"return (\w+)\(true,\{\},(\w+)\(\)\)\(\);?")   # AztupBrew : la fabrique appelle le deserialiseur

def tail_rewrite(src):
    m = list(TAIL_RX.finditer(src))
    if len(m) == 1:
        return src[:m[0].start()] + f"return __cap({m[0].group(2)}());" + src[m[0].end():]
    t = list(TAIL_TRUE_RX.finditer(src))
    if len(t) == 1:
        fac = t[0].group(1)
        fm = re.search(r"local function " + re.escape(fac) + r"\((\w+),\w+,\w+\)\s*\1\s*=\s*\(\s*\1\s*==\s*true\s*and\s*(\w+)\(\)\)", src)
        if not fm:
            raise ValueError("queue `(true,{},env)` : deserialiseur introuvable")
        return src[:t[0].start()] + f"return __cap({fm.group(2)}());" + src[t[0].end():]
    raise ValueError(f"queue d'appel : {len(m)} correspondance(s)")

def _find_factory(tree):
    """`local function F(p1,p2,p3) ... return function(...) ... end end` : renvoie (p1,p2,p3, closure_body)."""
    for n in ast.walk(tree):
        if isinstance(n, A.LocalFunction) or (isinstance(n, A.Function) and getattr(n, "name", None)):
            args = [getattr(a, "id", None) for a in n.args] if hasattr(n, "args") else []
            if len(args) != 3 or None in args:
                continue
            for r in ast.walk(n):
                if isinstance(r, A.Return) and r.values and isinstance(r.values[0], A.AnonymousFunction):
                    return args, r.values[0]
    raise ValueError("fabrique de VM introuvable")

def roles(tree, src):
    """Noms utilises par la VM de CE sample (src = texte source, tree = AST)."""
    flat = re.sub(r"\s+", "", src)
    m = re.search(r"(\w+)=(\w+)\[(\w+)\];(\w+)=\1\[1\]", flat)
    if not m:
        raise ValueError("boucle de dispatch introuvable")
    rec, ins, pc, opv = m.group(1), m.group(2), m.group(3), m.group(4)
    params, body = _find_factory(tree)
    m = re.search(r"else(\w+)\[\w+\]=\w+\[\w+\+1\]", flat)
    reg = m.group(1) if m else None
    protos = None
    spaced = re.sub(r"\s+", " ", src)
    for rx in (rf"\w+\((\w+)\[{re.escape(rec)}\[3\]\],nil,{re.escape(params[2])}\)",
               rf"(?:local )?\w+ ?= ?(\w+)\[{re.escape(rec)}\[3\]\];.{{0,80}}?\{{ ?\}}, ?\{{ ?__index"):
        m = re.search(rx, flat if rx.startswith(r"\w+\(") else spaced)
        if m:
            protos = m.group(1)
            break
    return {"rec": rec, "ins": ins, "pc": pc, "opv": opv, "upv": params[1], "env": params[2],
            "reg": reg, "protos": protos}

def role_regexes(r):
    """Motifs parametres par les roles. {R}=registres {E}=enregistrement {P}=pc {UP}=upvalues {ENV}=env {PR}=protos."""
    return [
        ("JMP",        r"^{P}={E}\[3\]$"),
        ("RET0",       r"^doreturnend$"),
        ("RET1",       r"^doreturn{R}\[{E}\[2\]\]end$"),
        ("RETCALL",    r"^doreturn{R}\[{E}\[2\]\]\(\)end$"),
        ("RETMULTI",   r"^doreturn\w+\({R},{E}\[2\],\w+\)end$"),
        ("NEWTABLE",   r"^{R}\[{E}\[2\]\]=\{\}$"),
        ("CALL0",      r"^{R}\[{E}\[2\]\]\(\)$"),
        ("CALLSET0",   r"^{R}\[{E}\[2\]\]={R}\[{E}\[2\]\]\(\)$"),
        ("LOADK",      r"^{R}\[{E}\[2\]\]={E}\[3\]$"),
        ("SETUPVAL",   r"^{UP}\[{E}\[3\]\]={R}\[{E}\[2\]\]$"),
        ("GETGLOBAL",  r"^{R}\[{E}\[2\]\]={ENV}\[{E}\[3\]\]$"),
        ("GETUPVAL",   r"^{R}\[{E}\[2\]\]={UP}\[{E}\[3\]\]$"),
        ("MOVE",       r"^{R}\[{E}\[2\]\]={R}\[{E}\[3\]\]$"),
        ("LOADBOOL",   r"^{R}\[{E}\[2\]\]=\({E}\[3\]~=0\)$"),
        ("SETTABLE_K", r"^{R}\[{E}\[2\]\]\[{E}\[3\]\]={E}\[4\]$"),
        ("SETTABLE_R", r"^{R}\[{E}\[2\]\]\[{E}\[3\]\]={R}\[{E}\[4\]\]$"),
        ("GETTABLE",   r"^{R}\[{E}\[2\]\]={R}\[{E}\[3\]\]\[{E}\[4\]\]$"),
        ("CLOSURE0",   r"^{R}\[{E}\[2\]\]=\w+\({PR}\[{E}\[3\]\],nil,\w+\)$"),
        ("CLOSURE",    r"^\w+={PR}\[{E}\[3\]\];.*for\w*=?\w+,{E}\[4\]do.*{R}\[{E}\[2\]\]=\w+\(\w+,\w+,\w+\)$"),
        ("CALLSET_ARG1", r"^{R}\[{E}\[2\]\]={R}\[{E}\[2\]\]\({R}\[{E}\[2\]\+1\]\)$"),
        ("CALL_ARG1",  r"^{R}\[{E}\[2\]\]\({R}\[{E}\[2\]\+1\]\)$"),
        ("CALLSET_DTOP", r"^{R}\[{E}\[2\]\]={R}\[{E}\[2\]\]\(\w+\({R},{E}\[2\]\+1,\w+\)\)$"),
        ("CALLSET_D",  r"^{R}\[{E}\[2\]\]={R}\[{E}\[2\]\]\(\w+\({R},{E}\[2\]\+1,{E}\[3\]\)\)$"),
        ("CALL_D",     r"^{R}\[{E}\[2\]\]\(\w+\({R},{E}\[2\]\+1,{E}\[3\]\)\)$"),
        ("MULTI_CALL", r"\w+\({R}\[{E}\[2\]\]\(\w+\({R},{E}\[2\]\+1,{E}\[3\]\)\)\)"),
        ("FIXED_MULTI", r"^\w+=\{{R}\[{E}\[2\]\]\({R}\[{E}\[2\]\+1\]\),\}"),
        ("CONCAT",     r"^(\w+)={R}\[{E}\[3\]\];for(\w+)={E}\[3\]\+1,{E}\[4\]do\1=\1\.\.{R}\[\2\];end;{R}\[{E}\[2\]\]=\1$"),
        ("SELF",       r"^(\w+)={R}\[{E}\[3\]\];{R}\[{E}\[2\]\+1\]=\1;{R}\[{E}\[2\]\]=\1\[{E}\[4\]\]$"),
        ("EQ0",        r"^if\({R}\[{E}\[2\]\]=={E}\[4\]\)then{P}={P}\+1;else{P}={E}\[3\];end$"),
        ("NE",         r"^if\({R}\[{E}\[2\]\]~={E}\[4\]\)then{P}={P}\+1;else{P}={E}\[3\];end$"),
        ("TRUTHY",     r"^if{R}\[{E}\[2\]\]then{P}={P}\+1;else{P}={E}\[3\];end$"),
        ("FALSY",      r"^ifnot{R}\[{E}\[2\]\]then{P}={P}\+1;else{P}={E}\[3\];end$"),
    ]

def compile_patterns(r):
    subs = {"R": r["reg"], "E": r["rec"], "P": r["pc"], "UP": r["upv"], "ENV": r["env"], "PR": r["protos"]}
    out = []
    for kind, pat in role_regexes(r):
        p = pat
        for k, v in subs.items():
            p = p.replace("{" + k + "}", re.escape(v) if v else r"\w+")
        out.append((kind, re.compile(p)))
    return out

def classify_with(compiled, key):
    hits = [k for k, rx in compiled if rx.search(key)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        return None
    raise ValueError(f"forme ambigue {hits}: {key[:120]}")
