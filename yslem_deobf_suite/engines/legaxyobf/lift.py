"""Lifteur RBXO -> Lua : evaluation symbolique (les registres gardent leur expression), blocs `if` structures,
predicats opaques connus retires. Les appels et les ecritures dans un bloc `if` deviennent des instructions."""
import re
from rbxo import constants, decode_ins


def q(k):
    if isinstance(k, str):
        return '"' + k.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'
    if k is None:
        return 'nil'
    if isinstance(k, bool):
        return 'true' if k else 'false'
    return str(int(k)) if isinstance(k, float) and k == int(k) else repr(k)


def ident(k):
    return k[1:-1] if k[:1] == '"' and k[1:-1].isidentifier() else None


OPAQUE = [  # (motif de la condition sans espaces, explication) : conditions toujours fausses
    (re.compile(r"^\(*\(*2\*bit32\.band\((\w+),(\d+)\)\)*\+bit32\.bxor\(\1,\2\)\)*~=\(*\1\+\2\)*$"),
     "a + b == 2*(a & b) + (a ~ b)"),
    (re.compile(r"^\(*\(*(\w+)\*\1\)*%4\)*==[23]$"), "un carre modulo 4 vaut 0 ou 1"),
]


def lift(c, p):
    K = [q(k) for k in constants(c, p)]
    I = [decode_ins(c, v) for v in p["raw"]]
    out, notes = [], []
    st = {}                    # registre -> expression
    n_tmp = [0]
    defs = {}

    def tmp():
        n_tmp[0] += 1
        return f"v{n_tmp[0]}"

    def get(r):
        return st.get(r, f"r{r}")

    def paren(e):
        return e if re.fullmatch(r"[\w.\"'\[\]]+|\w+\(.*\)", e) else f"({e})"

    # registres ecrits dans [i, end) et relus apres end : declares avant le bloc
    def writes(i, end):
        w = set()
        for d in I[i:end]:
            op = d["op"]
            if op in (0, 1, 4, 5, 6, 7, 8, 9, 10, 11, 15, 16, 17, 20, 21, 26, 27, 2, 3, 19):
                w.add(d["a"])
            if op in (13, 18, 22, 23, 24, 25, 19):
                w.add(d["b"])
            if op in (19, 23):
                w.add(d["c"])
        return w

    def run(i, end, ind, st):
        while i < end:
            d = I[i]
            op, a, b, c_ = d["op"], d["a"], d["b"], d["c"]
            pad = "  " * ind
            g = lambda r: st.get(r, f"r{r}")
            if op in (0, 7, 15):
                nm = ident(K[b]); st[a] = nm or f"_G[{K[b]}]"
            elif op in (1, 8, 16):
                st[a] = K[b]
            elif op in (4, 9, 17):
                k = ident(g(c_) if False else st.get(c_, "")) if st.get(c_, "").startswith('"') else None
                st[a] = f"{paren(g(b))}.{k}" if k else f"{paren(g(b))}[{g(c_)}]"
            elif op in (5, 26, 27):
                st[a] = g(b)
            elif op == 6: st[a] = f"{paren(g(b))} * {paren(g(c_))}"
            elif op == 10: st[a] = f"{paren(g(b))} + {paren(g(c_))}"
            elif op == 11: st[a] = f"{paren(g(b))} ~= {paren(g(c_))}"
            elif op == 20: st[a] = f"{paren(g(b))} % {paren(g(c_))}"
            elif op == 21: st[a] = f"{paren(g(b))} == {paren(g(c_))}"
            elif op in (13, 18, 22): st[b] = f"{paren(g(c_))} * {K[a]}"
            elif op == 19: st[a] = st[c_] = g(b)
            elif op == 23: st[b] = g(a); st[c_] = f"{paren(g(a))} * {paren(g(a))}"
            elif op == 24: st[b] = f"{paren(g(c_))} % {K[a]}"
            elif op == 25: st[b] = f"{paren(g(c_))} == {K[a]}"
            elif op == 2:
                if b < 0: st[a] = "..."; st["_open"] = a
                else:
                    for j in range(b): st[a + j] = f"(select({j + 1}, ...))"
            elif op == 3:
                f = g(a)
                opn = st.get("_open", a + 1)
                if b < 0:                          # arguments : r[a+1 .. ouvert-1] puis la valeur ouverte (`...` ou resultat d'appel)
                    argl = [g(a + 1 + j) for j in range(max(opn - a - 1, 0))] + [g(opn)]
                else:
                    argl = [g(a + 1 + j) for j in range(b)]
                if f.endswith('.HttpGet') and b >= 1 and argl and argl[0] == f.rsplit('.', 1)[0]:   # game.HttpGet(game, url) -> game:HttpGet(url)
                    call = f"{f.rsplit('.', 1)[0]}:HttpGet(" + ", ".join(argl[1:]) + ")"
                else:
                    call = f"{paren(f)}({', '.join(argl)})"
                if c_ == 0:
                    out.append(pad + call)
                else:                      # resultat(s) : evalue une seule fois, garde sa valeur dans une variable temporaire
                    if re.fullmatch(r"(\w+)\((.*)\)", call) is None and c_ != 1:
                        pass
                    if c_ == 1 or c_ < 0:
                        st[a] = call if c_ < 0 else call
                        if c_ == 1:
                            # appel imbrique dans l'expression : sans effet de bord visible ici -> on garde l'expression
                            # si elle est utilisee une fois, sinon on la nomme
                            v = tmp(); out.append(pad + f"local {v} = {call}"); st[a] = v; defs[v] = call
                        else:
                            st[a] = call; st["_open"] = a
                    else:
                        vs = [tmp() for _ in range(c_)]
                        out.append(pad + "local " + ", ".join(vs) + f" = {call}")
                        for j, v in enumerate(vs): st[a + j] = v
            elif op == 12:
                end_if = b
                body_end = end_if
                if I[end_if - 1]["op"] == 14 and I[end_if - 1]["a"] == end_if:
                    body_end = end_if - 1
                cond = g(a)
                norm = cond
                for _ in range(4):
                    norm = re.sub(r"\bv\d+\b", lambda m: defs[m.group(0)] if defs.get(m.group(0), "").startswith("bit32.") else m.group(0), norm)
                norm = norm.replace(" ", "")
                dead = next((why for rx, why in OPAQUE if rx.match(norm)), None)
                if dead:
                    notes.append(f"bloc mort retire (predicat opaque : {dead}) : if {cond} then ... end")
                else:
                    out.append(pad + f"if {cond} then")
                    inner = dict(st)
                    run(i + 1, body_end, ind + 1, inner)
                    out.append(pad + "end")
                    for r in writes(i + 1, body_end): st[r] = f"r{r}"
                i = end_if
                continue
            elif op == 14:
                out.append(pad + f"-- saut vers {a} (non structure)")
            elif op == 28:
                out.append(pad + ("return " + ", ".join(g(a + j) for j in range(max(b, 0))) if b >= 0 else f"return {g(a)}").rstrip())
            else:
                out.append(pad + f"-- op inconnu {op}")
            i += 1

    run(0, len(I), 0, st)
    # temporaire declare puis utilise UNE fois, sur la ligne suivante : on l'insere
    changed = True
    while changed:
        changed = False
        for i, line in enumerate(out[:-1]):
            m = re.match(r"\s*local (v\d+) = (.*)$", line)
            if m and len(re.findall(r"\b%s\b" % m.group(1), "\n".join(out))) == 2 \
                    and re.search(r"\b%s\b" % m.group(1), out[i + 1]):
                out[i + 1] = re.sub(r"\b%s\b" % m.group(1), lambda _: m.group(2), out[i + 1], count=1)
                del out[i]; changed = True; break
    # appels purs (select / bit32.*) dont le resultat n'est plus lu nulle part (il alimentait les blocs morts) : retires
    changed = True
    while changed:
        changed = False
        text = "\n".join(out)
        for i, line in enumerate(out):
            m = re.match(r"\s*local (v\d+) = (?:select|bit32\.\w+)\(.*\)$", line)
            if m and len(re.findall(r"\b%s\b" % m.group(1), text)) == 1:
                del out[i]; changed = True; break
    return "\n".join(out), notes
