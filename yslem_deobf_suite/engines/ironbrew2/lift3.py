"""IronBrew2 -> bytecode Lua 5.1, version generique : les micro-operations sont classees par grammaire d'operandes
(grammar.py), les noms de variables par roles (ib2gen.roles). Un opcode dont une micro-operation est inconnue ne
fait echouer le lift QUE s'il apparait reellement dans le flux (echec explicite, jamais de sortie inventee)."""
import re, sys
from luaparser import ast
import dispatch as D, microops as M, classify as C, ib2gen as G, grammar as GR
import writer as W
import capture as LF

ARITH = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD", "^": "POW"}

# ---------------------------------------------------------------- classification des handlers
_LEX = re.compile(r"--\[(=*)\[.*?\]\1\]|--[^\n]*|\[(=*)\[.*?\]\2\]|\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'", re.S)

def shrink_strings(src):
    """Remplace les longs litteraux (donnees chiffrees/compressees : centaines de Ko) par une chaine courte : l'analyse de
    la VM n'en a pas besoin et le parseur y passait l'essentiel de son temps. Decoupage lexical (commentaires, chaines,
    crochets longs) pour que chaque debut de jeton soit correct."""
    def rep(m):
        t = m.group(0)
        if len(t) > 200 and t[0] in "'\"":
            return "'#'"
        return t
    return _LEX.sub(rep, src)

_ESC = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, "\\": 92, '"': 34, "'": 39, "\n": 10}

def _lua_strlen(body):
    """Longueur (en octets) d'un litteral Lua deja prive de ses guillemets : gere \\n, \\ddd, \\xhh."""
    n, i = 0, 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            d = body[i + 1]
            if d.isdigit():
                j = i + 1
                while j < len(body) and j < i + 4 and body[j].isdigit():
                    j += 1
                i = j
            elif d == "x":
                i += 4
            else:
                i += 2
            n += 1
            continue
        n += 1
        i += 1
    return n

_STRLEN = re.compile(r"#\(\s*(?:\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)')\s*\)")

def _count_table(src, start):
    """src[start] == '{' : renvoie (nombre d'elements de premier niveau, index apres la '}') ou None si non simple."""
    depth, i, n_items, has_item = 0, start, 0, False
    while i < len(src):
        c = src[i]
        if c in "\"'":
            q, j = c, i + 1
            while j < len(src) and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            i, has_item = j + 1, True
            continue
        if c == "{":
            depth += 1
            if depth > 1:
                has_item = True
        elif c == "}":
            depth -= 1
            if depth == 0:
                return n_items + (1 if has_item else 0), i + 1
        elif depth == 1 and c in ",;":
            n_items += 1 if has_item else 0
            has_item = False
        elif depth == 1 and not c.isspace():
            if src.startswith("...", i) or c in "[=":
                return None
            has_item = True
        i += 1
    return None

def fold_lengths(src):
    """Replie les constantes ecrites comme longueurs : #("abc") -> 3 ; #{{1;2};} -> 1 (AztupBrew et autres forks)."""
    src = _STRLEN.sub(lambda m: str(_lua_strlen(m.group(1) if m.group(1) is not None else m.group(2))), src)
    out, i = [], 0
    while True:
        j = src.find("#{", i)
        if j < 0:
            out.append(src[i:]); break
        r = _count_table(src, j + 1)
        if r is None:
            out.append(src[i:j + 2]); i = j + 2; continue
        out.append(src[i:j]); out.append(str(r[0])); i = r[1]
    return "".join(out)

def kinds_for(src):
    src = fold_lengths(shrink_strings(src))
    tree = ast.parse(src)
    r = G.roles(tree, src)
    t = D.table(tree, opv=r["opv"], maxn=1024)
    kinds, unknown, cache = {}, {}, {}
    for N in range(1024):
        leaf = t.get(N)
        if leaf is None:
            continue
        if id(leaf) in cache:
            kinds[N] = cache[id(leaf)]
            continue
        specs = []
        for mo in M.split(leaf, pc=r["pc"], ins=r["ins"]):
            key = C.micro_key(mo, rec=r["rec"], protect=(r["pc"], r["ins"]))
            spec = GR.classify(key, r)
            if spec is None:
                spec = GR.classify_raw(C.micro_raw(mo), r)
            if spec is None:
                unknown.setdefault(key, set()).add(N)
                spec = {"kind": "UNKNOWN", "key": key}
            specs.append(spec)
        cache[id(leaf)] = specs
        kinds[N] = specs
    return r, kinds, unknown

# ---------------------------------------------------------------- execution d'un handler
def _f(slot, operand):
    return slot[operand[1] - 1]

def _rk(slot, operand):
    v = slot[operand[1] - 1]
    return ("R", v) if operand[0] == "R" else ("K", v)

def exec_block(proto, s, kinds):
    slots = proto["slots"]
    op = slots[s - 1][0]
    if not isinstance(op, int) or op not in kinds:
        raise ValueError(f"opcode invalide {op!r} au slot {s}")
    ops, succ, term = [], [], False
    extra = []                      # successeurs supplementaires d'un bloc qui continue (ex. sortie de boucle)
    cur = s
    opslots = []                    # slot d'origine de chaque op (pour la table de lignes de debogage)
    prev_cur = s
    for sp in kinds[op]:
        while len(opslots) < len(ops):
            opslots.append(prev_cur)
        prev_cur = cur
        r = slots[cur - 1]
        k = sp["kind"]
        step = 1
        if k == "UNKNOWN":
            raise ValueError(f"micro-operation inconnue (opcode {op}, slot {cur}) : {sp['key'][:110]}")
        if k == "JMP":
            ops.append(("JUMP", r[2] + 1)); succ.append(r[2] + 1); term = True; break
        if k == "RET0":
            ops.append(("RETURN", 0, 1)); term = True; break
        if k == "RET1":
            ops.append(("RETURN", _f(r, sp["a"]), 2)); term = True; break
        if k == "RET2":
            ops.append(("RETURN", _f(r, sp["a"]), 3)); term = True; break
        if k == "RETFIX":
            ops.append(("RETURN", _f(r, sp["a"]), _f(r, sp["b"]) + 2)); term = True; break
        if k == "RETTOP":
            ops.append(("RETURN", _f(r, sp["a"]), 0)); term = True; break
        if k == "NEWTABLE":
            ops.append(("NEWTABLE", _f(r, sp["a"])))
        elif k == "MOVE":
            ops.append(("MOVE", _f(r, sp["a"]), _f(r, sp["b"])))
        elif k == "LOADK":
            v = _f(r, sp["b"])
            ops.append(("LOADNIL", _f(r, sp["a"]), _f(r, sp["a"])) if v is None else ("LOADK", _f(r, sp["a"]), v))
        elif k in ("GETGLOBAL", "SETGLOBAL"):
            name = _f(r, sp["b"])
            if not isinstance(name, str):
                raise ValueError(f"{k} sans nom (slot {cur})")
            ops.append((k, _f(r, sp["a"]), name))
        elif k in ("GETUPVAL", "SETUPVAL"):
            ops.append((k, _f(r, sp["a"]), _f(r, sp["b"])))
        elif k == "LOADBOOL":
            ops.append(("LOADBOOL", _f(r, sp["a"]), _f(r, sp["b"]) not in (0, None, False)))
        elif k == "GETTABLE":
            ops.append(("GETTABLE", _f(r, sp["a"]), _f(r, sp["b"]), _rk(r, sp["c"])))
        elif k == "SETTABLE":
            ops.append(("SETTABLE", _f(r, sp["a"]), _rk(r, sp["b"]), _rk(r, sp["c"])))
        elif k == "ARITH":
            ops.append(("ARITH", ARITH[sp["op"]], _f(r, sp["a"]), _rk(r, sp["b"]), _rk(r, sp["c"])))
        elif k in ("LEN", "NOT", "UNM"):
            ops.append(("UNARY", k, _f(r, sp["a"]), _f(r, sp["b"])))
        elif k == "SELF":
            ops.append(("SELF", _f(r, sp["a"]), _f(r, sp["b"]), _rk(r, sp["c"])))
        elif k == "CONCAT":
            ops.append(("CONCAT", _f(r, sp["a"]), _f(r, sp["b"]), _f(r, sp["c"])))
        elif k == "SETLIST":
            a = _f(r, sp["a"])
            n = _f(r, sp["b"]) - a
            if n > 50:
                raise ValueError("SETLIST de plus de 50 elements (non gere)")
            ops.append(("SETLIST", a, n, 1))
        elif k == "SETLIST_TOP":
            ops.append(("SETLIST", _f(r, sp["a"]), 0, 1))
        elif k == "LOADNIL":
            ops.append(("LOADNIL", _f(r, sp["a"]), _f(r, sp["b"])))
        elif k == "CLOSE":
            ops.append(("CLOSE", _f(r, sp["a"])))
        elif k == "CLOSE_NOOP":
            pass
        elif k == "NOP":
            pass
        elif k == "FORLOOP":
            jt = r[2] + 1
            ops.append(("FORLOOP", r[1], jt))
            extra.append(jt)
        elif k == "FORCHECK":
            exit_t = r[2] + 1
            ops.append(("FORCHECK", r[1], exit_t))
            extra.append(exit_t)
        elif k == "VARARG":
            ops.append(("VARARG", _f(r, sp["a"]), 0))
        elif k == "VARARG_FIX":
            a_ = _f(r, sp["a"])
            ops.append(("VARARG", a_, _f(r, sp["b"]) - a_ + 2))
        elif k == "CLOSURE0":
            ops.append(("CLOSURE", _f(r, sp["a"]), _f(r, sp["b"]), []))
        elif k == "CLOSURE":
            nups = _f(r, sp["c"])
            caps = []
            for j in range(1, nups + 1):
                pr = slots[cur + j - 1]
                is_local = (pr[0] == sp["capk"]) == sp["eq_local"]
                caps.append(("MOVE", pr[2]) if is_local else ("GETUPVAL", pr[2]))
            ops.append(("CLOSURE", _f(r, sp["a"]), _f(r, sp["b"]), caps))
            step = 1 + nups
        elif k == "CALL":
            a = r[1]
            ar = sp["args"]
            B = ar[1] + 1 if ar[0] == "n" else (r[2] - a + 1 if ar[0] == "bound_field3" else 0)
            res = sp["results"]
            if res == "tail":
                ops.append(("CALL", a, B, 0)); ops.append(("RETURN", a, 0)); term = True; break
            C_ = {"none": 1, "one": 2, "multret": 0}.get(res)
            if res == "fixed":
                C_ = r[3] - a + 2
            ops.append(("CALL", a, B, C_))
        elif k == "TFORLOOP":
            jump_t, skip_t = r[2] + 1, cur + 2
            ops.append(("CONDTFOR", r[1], r[3], jump_t, skip_t))
            succ += [jump_t, skip_t]
            term = True
            break
        elif k in ("CMP", "TEST", "TESTSET"):
            jump_t, skip_t = r[2] + 1, cur + 2
            tt = jump_t if sp["true"] == "jump" else skip_t
            ff = jump_t if sp["false"] == "jump" else skip_t
            if k == "CMP":
                ops.append(("CONDCMP", sp["op"], _rk(r, sp["x"]), _rk(r, sp["y"]), ff, tt))
            elif k == "TEST":
                # cond = (non neg) -> R truthy ; (neg) -> R falsy.   Lua 5.1 : on saute le JMP faux (cond VRAIE) si bool(R) != C
                ops.append(("CONDTEST", 1 if sp["neg"] else 0, _f(r, sp["x"]), ff, tt))
            else:
                # TESTSET : la branche « jump » fait R[a]=R[c] ; elle est prise quand bool(R[c]) == C
                if sp["true"] == "jump":      # if [not] tmp then SET+JUMP else SKIP
                    C_ = 0 if sp["neg"] else 1
                else:                          # if [not] tmp then SKIP else SET+JUMP
                    C_ = 1 if sp["neg"] else 0
                ops.append(("CONDTESTSET", C_, _f(r, sp["a"]), _f(r, sp["c"]), jump_t, skip_t))
            succ += [jump_t, skip_t]
            term = True
            break
        else:
            raise ValueError(f"genre non gere : {k}")
        cur += step
    while len(opslots) < len(ops):
        opslots.append(prev_cur)
    if not term:
        succ = [cur] + extra + succ
    exec_block.last_opslots = opslots
    return ops, succ, term

# ---------------------------------------------------------------- lowering
class Chunk(LF.Chunk):
    uses_vararg = False

def lower_proto(proto, idx, kinds, pad=None):
    ch = Chunk(proto, idx, kinds)
    ch.caps_max = {}
    ch.lines = []
    todo, blocks = [1], {}
    while todo:
        s = todo.pop()
        if s in blocks:
            continue
        if s < 1 or s > len(proto["slots"]):
            raise ValueError(f"saut hors du flux : slot {s}")
        ops, succ, term = exec_block(proto, s, kinds)
        blocks[s] = (ops, succ, term, list(exec_block.last_opslots))
        todo.extend(x for x in succ if x not in blocks)
    # Emulation de la variable « top » de la VM (initialisee a -1, modifiee seulement par un appel multi-resultats ou VARARG) :
    # un consommateur ouvert (RETURN A 0 / CALL ... B=0) qui ne suit pas un producteur ouvert, dans une fonction sans AUCUN
    # producteur, voit top = -1 -> « aucune valeur ». Lua 5.1 renverrait sinon les registres jusqu'au sommet de pile.
    def _opens(op):
        return (op[0] == "CALL" and op[3] == 0) or (op[0] == "VARARG")
    has_producer = any(_opens(op) for (ops_, _, _, _) in blocks.values() for op in ops_)
    for s_, (ops_, succ_, term_, sl_) in list(blocks.items()):
        for i_, op in enumerate(ops_):
            prev_open = i_ > 0 and _opens(ops_[i_ - 1])
            if op[0] == "RETURN" and op[2] == 0 and not prev_open and not has_producer:
                ops_[i_] = ("RETURN", 0, 1)
            elif op[0] == "CALL" and op[2] == 0 and not prev_open and not has_producer:
                ops_[i_] = ("CALL", op[1], 1, op[3])
    order = sorted(blocks)
    code, labels = [], {}
    J = lambda t: ("JMP", ("LBL", t))
    for pos, s in enumerate(order):
        ops, succ, term, opslots = blocks[s]
        labels[s] = len(code)
        nxt = order[pos + 1] if pos + 1 < len(order) else None
        for oi, op in enumerate(ops):
            start_len = len(code)
            kd = op[0]
            if kd == "CONDCMP":
                _, c, x, y, ff, tt = op
                rkx, rky = ch.rk(x), ch.rk(y)
                # (code Lua, A pour « saute le JMP quand la condition est VRAIE »)
                base = {"<": ("LT", rkx, rky, 0), "<=": ("LE", rkx, rky, 0), ">": ("LT", rky, rkx, 0),
                        ">=": ("LE", rky, rkx, 0), "==": ("EQ", rkx, rky, 0), "~=": ("EQ", rkx, rky, 1)}[c]
                nm, b_, c_, a_true = base
                if tt == ff:
                    code.append(J(tt))
                elif tt == nxt:                       # cond VRAIE : on tombe sur le bloc suivant ; FAUSSE : JMP
                    code += [(nm, a_true, b_, c_), J(ff)]
                elif ff == nxt:                       # cond FAUSSE : on tombe ; VRAIE : JMP
                    code += [(nm, 1 - a_true, b_, c_), J(tt)]
                else:
                    code += [(nm, a_true, b_, c_), J(ff), J(tt)]
            elif kd == "CONDTEST":
                _, c, a, ff, tt = op
                if tt == ff:
                    code.append(J(tt))
                elif tt == nxt:
                    code += [("TEST", ch.reg(a), c), J(ff)]
                elif ff == nxt:
                    code += [("TEST", ch.reg(a), 1 - c), J(tt)]
                else:
                    code += [("TEST", ch.reg(a), c), J(ff), J(tt)]
            elif kd == "FORLOOP":
                _, a, jt = op
                ch.maxreg = max(ch.maxreg, a + 3)
                code.append(("FORLOOP", ch.reg(a), ("LBL", jt)))
            elif kd == "FORCHECK":
                _, a, exit_t = op
                rs, rl, ri, rv = ch.reg(a + 2), ch.reg(a + 1), ch.reg(a), ch.reg(a + 3)
                k0 = 256 + ch.k(0.0)
                # pas > 0 : sort si limite < indice ; sinon sort si indice < limite ; ensuite R[A+3] = indice
                code += [("LT", 1, k0, rs), ("JMP", 3),                    # pas > 0  -> branche positive
                         ("LT", 1, ri, rl), J(exit_t), ("JMP", 2),         # pas <= 0 : indice < limite -> sortie ; sinon corps
                         ("LT", 1, rl, ri), J(exit_t),                     # pas > 0  : limite < indice -> sortie
                         ("MOVE", rv, ri)]
            elif kd == "CONDTFOR":
                _, a, c_, jt, st = op
                ch.maxreg = max(ch.maxreg, a + c_ + 5)        # luaG_checkcode : checkreg(a+c+5)
                code += [("TFORLOOP", ch.reg(a), 0, c_), J(jt)] if st == nxt else [("TFORLOOP", ch.reg(a), 0, c_), J(jt), J(st)]
            elif kd == "CONDTESTSET":
                _, c, a, b, jt, st = op
                if st == nxt:
                    code += [("TESTSET", ch.reg(a), ch.reg(b), c), J(jt)]
                else:
                    code += [("TESTSET", ch.reg(a), ch.reg(b), c), J(jt), J(st)]
            elif kd == "JUMP":
                if op[1] != nxt:
                    code.append(J(op[1]))
            elif kd == "RETURN":
                code.append(("RETURN", ch.reg(op[1]), op[2]))
            elif kd == "MOVE":
                code.append(("MOVE", ch.reg(op[1]), ch.reg(op[2])))
            elif kd == "LOADK":
                v = op[2]
                code.append(("LOADBOOL", ch.reg(op[1]), 1 if v else 0, 0) if isinstance(v, bool)
                            else ("LOADK", ch.reg(op[1]), ch.k(v)))
            elif kd == "LOADBOOL":
                code.append(("LOADBOOL", ch.reg(op[1]), 1 if op[2] else 0, 0))
            elif kd == "LOADNIL":
                ch.reg(op[1]); ch.reg(op[2])
                code.append(("LOADNIL", op[1], op[2]))
            elif kd in ("GETGLOBAL", "SETGLOBAL"):
                code.append((kd, ch.reg(op[1]), ch.k(op[2])))
            elif kd in ("GETUPVAL", "SETUPVAL"):
                code.append((kd, ch.reg(op[1]), op[2]))
            elif kd == "GETTABLE":
                code.append(("GETTABLE", ch.reg(op[1]), ch.reg(op[2]), ch.rk(op[3])))
            elif kd == "SETTABLE":
                code.append(("SETTABLE", ch.reg(op[1]), ch.rk(op[2]), ch.rk(op[3])))
            elif kd == "NEWTABLE":
                code.append(("NEWTABLE", ch.reg(op[1]), 0, 0))
            elif kd == "ARITH":
                code.append((op[1], ch.reg(op[2]), ch.rk(op[3]), ch.rk(op[4])))
            elif kd == "UNARY":
                code.append((op[1], ch.reg(op[2]), ch.reg(op[3])))
            elif kd == "SELF":
                code.append(("SELF", ch.reg(op[1]), ch.reg(op[2]), ch.rk(op[3])))
                ch.maxreg = max(ch.maxreg, op[1] + 1)
            elif kd == "CONCAT":
                code.append(("CONCAT", ch.reg(op[1]), ch.reg(op[2]), ch.reg(op[3])))
            elif kd == "SETLIST":
                code.append(("SETLIST", ch.reg(op[1]), op[2], op[3]))
                ch.maxreg = max(ch.maxreg, op[1] + op[2])
            elif kd == "VARARG":
                code.append(("VARARG", ch.reg(op[1]), op[2]))
                ch.uses_vararg = True
            elif kd == "CLOSE":
                code.append(("CLOSE", ch.reg(op[1]), 0, 0))
            elif kd == "CALL":
                _, a, b, c = op
                code.append(("CALL", ch.reg(a), b, c))
                if b > 0:
                    ch.maxreg = max(ch.maxreg, a + b - 1)
                if c > 1:
                    ch.maxreg = max(ch.maxreg, a + c - 2)
            elif kd == "CLOSURE":
                _, a, pidx, caps = op
                ch.caps_max[pidx] = max(ch.caps_max.get(pidx, 0), len(caps))
                if pad:                                   # meme nombre de captures pour toutes les instances d'un proto
                    caps = list(caps) + [("MOVE", 0)] * max(0, pad.get(pidx, 0) - len(caps))
                code.append(("CLOSURE", ch.reg(a), pidx, caps))
                ch.caps_of_children[pidx] = len(caps)
            else:
                raise ValueError(f"IR inconnu {kd}")
            ch.lines += [opslots[oi] if oi < len(opslots) else s] * (len(code) - start_len)
        if not term:
            nxt = succ[0]
            if not (pos + 1 < len(order) and order[pos + 1] == nxt):
                code.append(J(nxt))
                ch.lines.append(s)
    if not code or code[-1][0] != "RETURN":       # exigence du verificateur Lua 5.1 : la fonction finit par RETURN
        code.append(("RETURN", 0, 1))
        ch.lines.append(0)
    pcs, pc = [], 0
    for ins in code:
        pcs.append(pc)
        pc += 1 + (len(ins[3]) if ins[0] == "CLOSURE" else 0)
    lbl_pc = {s: (pcs[labels[s]] if labels[s] < len(pcs) else pc) for s in order}
    out = []
    for i, ins in enumerate(code):
        if ins[0] == "JMP" and isinstance(ins[1], tuple):
            out.append(("JMP", lbl_pc[ins[1][1]] - (pcs[i] + 1)))
        elif ins[0] == "FORLOOP":
            out.append(("FORLOOP", ins[1], lbl_pc[ins[2][1]] - (pcs[i] + 1)))
        else:
            out.append(ins)
    return out, ch

# ---------------------------------------------------------------- pilote
def _need(code):
    """Nombre d'upvalues dont la fonction a besoin : usage direct (GETUPVAL/SETUPVAL) et captures GETUPVAL des CLOSURE."""
    n = 0
    for ins in code:
        if ins[0] in ("GETUPVAL", "SETUPVAL"):
            n = max(n, ins[2] + 1)
        elif ins[0] == "CLOSURE":
            for ck, b in ins[3]:
                if ck == "GETUPVAL":
                    n = max(n, b + 1)
    return n

def _analyse(proto, kinds):
    code, ch = lower_proto(proto, 0, kinds)
    return {"need": _need(code), "caps_max": ch.caps_max, "children": [_analyse(c, kinds) for c in proto["protos"]]}

def _write(proto, an, nups, is_main, kinds, path="0"):
    pad = {i: max(an["children"][i]["need"], an["caps_max"].get(i, 0)) for i in range(len(proto["protos"]))}
    code, ch = lower_proto(proto, 0, kinds, pad)
    children = [_write(c, an["children"][i], pad[i], False, kinds, f"{path}.{i}") for i, c in enumerate(proto["protos"])]
    maxstack = max(ch.maxreg + 2, proto["numparams"] + 2)
    if maxstack > 250:
        raise ValueError(f"maxstack {maxstack} > 250 (non gere)")
    return W.function_bytes(code, ch.consts, children, nups, proto["numparams"], maxstack, is_main or ch.uses_vararg,
                            lines=ch.lines if DEBUG_LINES[0] else None, source=("=" + path) if DEBUG_LINES[0] else None)

DEBUG_LINES = [False]

def lift_file(path, out_path, debug_lines=False):
    DEBUG_LINES[0] = debug_lines
    src = open(path, encoding="latin-1").read()
    src2 = G.tail_rewrite(src)
    r, kinds, unknown = kinds_for(src)
    proto = LF.capture_text(src2)
    an = _analyse(proto, kinds)
    data = W.chunk_bytes(_write(proto, an, an["need"], True, kinds))
    open(out_path, "wb").write(data)
    return r, len(data), unknown

if __name__ == "__main__":
    r, n, unk = lift_file(sys.argv[1], sys.argv[2], debug_lines=("--lines" in sys.argv))
    print("roles", r, "octets", n, "formes inconnues (non utilisees)", len(unk))
