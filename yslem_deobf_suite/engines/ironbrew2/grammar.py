"""Classifieur par GRAMMAIRE d'operandes pour les micro-operations IronBrew2 (toutes variantes).

Un operande est soit un REGISTRE (`R[E[k]]`) soit un LITTERAL (`E[k]`). Chaque famille combine ces operandes avec
un operateur ; le classifieur renvoie une spec structuree {kind, ...} (operandes = ("R", k) ou ("K", k)) et non plus
un simple nom. Un seul jeu de regles couvre donc toutes les combinaisons registre/constante des forks."""
import re

def _ex(tpl, roles):
    """Developpe les modeles : {R}{E}{P}{UP}{ENV}{PR} -> noms ; <rx:n> registre ; <kx:n> litteral ; <ox:n> registre|litteral."""
    R, E = re.escape(roles["reg"]), re.escape(roles["rec"])
    t = tpl
    t = re.sub(r"<rx:(\w+)>", lambda m: rf"{R}\[{E}\[(?P<{m.group(1)}_r>\d)\]\]", t)
    t = re.sub(r"<kx:(\w+)>", lambda m: rf"{E}\[(?P<{m.group(1)}_k>\d)\]", t)
    t = re.sub(r"<ox:(\w+)>", lambda m: rf"(?:{R}\[{E}\[(?P<{m.group(1)}_r>\d)\]\]|{E}\[(?P<{m.group(1)}_k>\d)\])", t)
    shadow = {roles.get("reg"), roles.get("rec"), roles.get("pc"), roles.get("ins")}
    for k, v in (("R", "reg"), ("E", "rec"), ("P", "pc"), ("UP", "upv"), ("ENV", "env"), ("PR", "protos")):
        name = roles.get(v)
        if k in ("UP", "ENV", "PR") and name in shadow:      # masque dans la fermeture par un autre role : ne peut pas y etre reference
            t = t.replace("{" + k + "}", "(?!)")
        else:
            t = t.replace("{" + k + "}", re.escape(name) if name else r"\w+")
    return t

def _operand(m, name):
    r, k = m.groupdict().get(name + "_r"), m.groupdict().get(name + "_k")
    if r is not None:
        return ("R", int(r))
    if k is not None:
        return ("K", int(k))
    return None

# (genre, modele, {nom_spec: nom_groupe_operande})
SIMPLE = [
    ("JMP",        r"^{P}={E}\[3\]$", {}),
    ("RET0",       r"^doreturnend$", {}),
    ("RET1",       r"^doreturn<rx:a>end$", {"a": "a"}),
    ("RET2",       r"^doreturn<rx:a>,{R}\[{E}\[\d\]\+1\]end$", {"a": "a"}),
    ("RETFIX",     r"^doreturn\w+\({R},<kx:a>,{E}\[(?P=a_k)\]\+<kx:b>\)end$", {"a": "a", "b": "b"}),
    ("RETTOP",     r"^doreturn\w+\({R},<kx:a>,\w+\)end$", {"a": "a"}),
    ("VARARG_FIX", r"^for(?P<lv>\w+)=<kx:a>,<kx:b>do{R}\[(?P=lv)\]=\w+\[(?P=lv)-{E}\[(?P=a_k)\]\];?end$", {"a": "a", "b": "b"}),
    ("NEWTABLE",   r"^<rx:a>=\{\}$", {"a": "a"}),
    ("MOVE",       r"^<rx:a>=<rx:b>$", {"a": "a", "b": "b"}),
    ("LOADK",      r"^<rx:a>=<kx:b>$", {"a": "a", "b": "b"}),
    ("GETGLOBAL",  r"^<rx:a>={ENV}\[<kx:b>\]$", {"a": "a", "b": "b"}),
    ("GETUPVAL",   r"^<rx:a>={UP}\[<kx:b>\]$", {"a": "a", "b": "b"}),
    ("SETUPVAL",   r"^{UP}\[<kx:b>\]=<rx:a>$", {"a": "a", "b": "b"}),
    ("SETGLOBAL",  r"^{ENV}\[<kx:b>\]=<rx:a>$", {"a": "a", "b": "b"}),
    ("LOADBOOL",   r"^<rx:a>=\(<kx:b>~=0\)$", {"a": "a", "b": "b"}),
    ("GETTABLE",   r"^<rx:a>=<rx:b>\[<ox:c>\]$", {"a": "a", "b": "b", "c": "c"}),
    ("SETTABLE",   r"^<rx:a>\[<ox:b>\]=<ox:c>$", {"a": "a", "b": "b", "c": "c"}),
    ("ARITH",      r"^<rx:a>=<ox:b>(?P<op>[-+*/%^])<ox:c>$", {"a": "a", "b": "b", "c": "c"}),
    ("LEN",        r"^<rx:a>=#<rx:b>$", {"a": "a", "b": "b"}),
    ("NOT",        r"^<rx:a>=\(?not<rx:b>\)?$", {"a": "a", "b": "b"}),
    ("UNM",        r"^<rx:a>=-<rx:b>$", {"a": "a", "b": "b"}),
    ("SELF",       r"^(?P<tmp>\w+)=<rx:b>;{R}\[{E}\[(?P<a_r>\d)\]\+1\]=(?P=tmp);{R}\[{E}\[(?P=a_r)\]\]=(?P=tmp)\[<ox:c>\]$", {"a": "a", "b": "b", "c": "c"}),
    ("CONCAT",     r"^(?P<acc>\w+)=<rx:b>;for(?P<lv>\w+)=<kx:b2>\+1,<kx:c>do(?P=acc)=(?P=acc)\.\.{R}\[(?P=lv)\];end;<rx:a>=(?P=acc)$", {"a": "a", "b": "b", "c": "c"}),
    ("SETLIST",    r"^(?P<tb>\w+)=<rx:a>;for(?P<lv>\w+)=<kx:a2>\+1,<kx:b>do\w+\((?P=tb),{R}\[(?P=lv)\]\)end$", {"a": "a", "b": "b"}),
    ("SETLIST_TOP", r"^(?P<tb>\w+)=<rx:a>;for(?P<lv>\w+)=<kx:a2>\+1,(?P<top>[A-Za-z_]\w*)do\w+\((?P=tb),{R}\[(?P=lv)\]\)end$", {"a": "a"}),
    ("FORCHECK",   r"^(?P<i>\w+)={R}\[{E}\[2\]\];(?P<s>\w+)={R}\[{E}\[2\]\+2\];if\((?P=s)>0\)thenif\((?P=i)>{R}\[{E}\[2\]\+1\]\)then{P}={E}\[3\];else{R}\[{E}\[2\]\+3\]=(?P=i);endelseif\((?P=i)<{R}\[{E}\[2\]\+1\]\)then{P}={E}\[3\];else{R}\[{E}\[2\]\+3\]=(?P=i);end$", {}),
    ("FORLOOP",    r"^(?P<s>\w+)={R}\[{E}\[2\]\+2\];(?P<n>\w+)={R}\[{E}\[2\]\]\+(?P=s);{R}\[{E}\[2\]\]=(?P=n);if\((?P=s)>0\)thenif\((?P=n)<={R}\[{E}\[2\]\+1\]\)then{P}={E}\[3\];{R}\[{E}\[2\]\+3\]=(?P=n);endelseif\((?P=n)>={R}\[{E}\[2\]\+1\]\)then{P}={E}\[3\];{R}\[{E}\[2\]\+3\]=(?P=n);end$", {}),
    ("NOP",        r"^$", {}),
    ("CLOSE",      r"^(?P<t>\w+)=\{\};for\w+=1,#\w+do.*>=<kx:a>then.*end$", {"a": "a"}),
    ("CLOSE_NOOP", r"^(?P<t>\w+)=\{\};for\w+=1,#\w+do(?:(?!>=).)*end$", {}),
    ("VARARG",     r"^(?P<top>\w+)=<kx:a>\+\w+-1;for(?P<lv>\w+)=<kx:a2>,(?P=top)do\w+=\w+\[(?P=lv)-<kx:a3>\];{R}\[(?P=lv)\]=\w+;?end$", {"a": "a"}),
    ("LOADNIL",    r"^for(?P<lv>\w+)=<kx:a>,<kx:b>do{R}\[(?P=lv)\]=nil;?end$", {"a": "a", "b": "b"}),
    ("CLOSURE0",   r"^<rx:a>=\w+\({PR}\[<kx:b>\],nil,\w+\)$", {"a": "a", "b": "b"}),
    ("CLOSURE",    r"^\w+={PR}\[<kx:b>\];.*for\w*=?\w+,<kx:c>do.*<rx:a>=\w+\(\w+,\w+,\w+\)$", {"a": "a", "b": "b", "c": "c"}),
]

# polarite d'une conditionnelle : quelle branche est « saute » (E[3]) et laquelle est « passe » (pc+1)
_SKIP = r"{P}={P}\+1"
_JUMP = r"{P}={E}\[3\]"
COND = [
    # comparaison (<ox:x> op <ox:y>)
    ("CMP", rf"^if\(<ox:x>(?P<op><=|>=|==|~=|<|>)<ox:y>\)then(?P<t>{_SKIP}|{_JUMP});else(?P<f>{_SKIP}|{_JUMP});end$"),
    ("TEST", rf"^if(?P<neg>not)?<rx:x>then(?P<t>{_SKIP}|{_JUMP});else(?P<f>{_SKIP}|{_JUMP});end$"),
    ("TESTSET", rf"^(?P<tmp>\w+)=<rx:c>;if(?P<neg>not)?(?P=tmp)then(?P<t>{_SKIP});else<rx:a>=(?P=tmp);(?P<f>{_JUMP});end$"),
    ("TESTSET", rf"^(?P<tmp>\w+)=<rx:c>;if(?P<neg>not)?(?P=tmp)then<rx:a>=(?P=tmp);(?P<t>{_JUMP});else(?P<f>{_SKIP});end$"),
]

def classify(key, roles):
    """Renvoie une spec {'kind': ..., ...} ou None. Leve ValueError si ambigu."""
    hits = []
    for kind, tpl, names in SIMPLE:
        m = re.search(_ex(tpl, roles), key)
        if m:
            spec = {"kind": kind}
            for sname, g in names.items():
                spec[sname] = _operand(m, g)
            if kind == "ARITH":
                spec["op"] = m.group("op")
            if kind == "CLOSURE":
                # constante qui distingue « capture d'un registre local » de « capture d'un upvalue du parent » (propre a chaque fork)
                cm = re.search(re.escape(roles["rec"]) + r"\[1\]==(\d+)then\w+\[\w+-1\]=\{" + r"(\w+),", key)
                if not cm:
                    continue
                spec["capk"] = int(cm.group(1))
                spec["eq_local"] = cm.group(2) == roles["reg"]
            hits.append(spec)
    for kind, tpl in COND:
        m = re.search(_ex(tpl, roles), key)
        if m:
            t, f = m.group("t"), m.group("f")
            jt = "jump" if re.search(roles["rec"] + r"\[3\]", t) else "skip"
            jf = "jump" if re.search(roles["rec"] + r"\[3\]", f) else "skip"
            if jt == jf:
                continue
            spec = {"kind": kind, "true": jt, "false": jf}
            for g in ("x", "y", "c", "a"):
                if (g + "_r") in m.groupdict() or (g + "_k") in m.groupdict():
                    spec[g] = _operand(m, g)
            if kind == "CMP":
                spec["op"] = m.group("op")
            else:
                spec["neg"] = bool(m.group("neg"))
            hits.append(spec)
    c = call_spec(key, roles)
    if c:
        hits.append(c)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        return None
    raise ValueError(f"forme ambigue {[h['kind'] for h in hits]}: {key[:100]}")

# ---------------------------------------------------------------- appels
def call_spec(key, roles):
    """Famille CALL : appelant R[E[2]] ; arguments : aucun / inline / unpack(R,E[2]+1,borne) ; resultats :
    aucun / un / fixes jusqu'a E[4] / multiples (top). `doreturn ... end` = appel en queue (suivi d'un RETURN)."""
    R, E = re.escape(roles["reg"]), re.escape(roles["rec"])
    callee = rf"{R}\[{E}\[2\]\]"
    inl = rf"(?:{R}\[{E}\[2\]\+\d\])"
    args = rf"(?P<args>|{inl}(?:,{inl})*|\w+\({R},{E}\[2\]\+1,(?P<bound>{E}\[3\]|\w+)\))"
    call = rf"{callee}\({args}\)"
    tail = False
    k = key
    if k.startswith("doreturn") and k.endswith("end"):
        tail, k = True, k[len("doreturn"):-3]
        m = re.fullmatch(call, k)
        if not m:
            return None
        return _call_out(m, roles, results="tail", tail=True)
    # sans resultat
    m = re.fullmatch(call, k)
    if m:
        return _call_out(m, roles, results="none")
    # un resultat
    m = re.fullmatch(rf"{callee}={call}", k)
    if m:
        return _call_out(m, roles, results="one")
    # resultats fixes : T={call};...;for X=E[2],E[4]do ...end
    m = re.fullmatch(rf"(?:\w+=)?\w+=\{{{call},?\}};\w+=0;for\w+={E}\[2\],{E}\[4\]do[^;]*;[^;]*;end", k) or \
        re.fullmatch(rf"\w+=\{{{call},?\}};\w+=0;for\w+={E}\[2\],{E}\[4\]do[^;]*;[^;]*;end", k)
    if m:
        return _call_out(m, roles, results="fixed")
    # resultats multiples (top) : A,B=F(call);i=B+E[2]-1;...for ... do ... end
    m = re.fullmatch(rf"(?:\w+,\w+)=\w+\({call}\);\w+=\w+\+{E}\[2\]-1;(?:\w+=0;)?for[^;]*;[^;]*;end", k)
    if m:
        return _call_out(m, roles, results="multret")
    return None

def _call_out(m, roles, results, tail=False):
    d = m.groupdict()
    a = d.get("args") or ""
    bound = d.get("bound")
    if bound is not None:
        argspec = ("bound_field3",) if roles["rec"] + "[3]" in bound else ("top",)
    elif a == "":
        argspec = ("n", 0)
    else:
        argspec = ("n", a.count(","))  if False else ("n", len(re.findall(r"\+\d", a)))
    return {"kind": "CALL", "args": argspec, "results": results}


# regles sur le texte BRUT (handlers qui redefinissent leurs variables locales ou reutilisent le nom du registre d'instruction)
RAW = [
    ("VARARG_FIX", r"^(?P<al>\w+)={E}\[(?P<a_r>\d)\];(?P<bl>\w+)={E}\[(?P<b_r>\d)\];for(?P<lv>\w+)=(?P=al),(?P=bl)do{R}\[(?P=lv)\]=\w+\[(?P=lv)-(?P=al)\];?end$", {"a": "a", "b": "b"}),
    ("CALLFIX0", r"^(?P<al>\w+)={E}\[2\];(?P<tb>\w+)=\{{R}\[(?P=al)\]\(\),\};(?P<cn>\w+)={E}\[4\];(?P<c>\w+)=0;for(?P<lv>\w+)=(?P=al),(?P=cn)do(?P=c)=(?P=c)\+1;?{R}\[(?P=lv)\]=(?P=tb)\[(?P=c)\];?end$", {}),
    ("VARARG", r"^(?P<al>\w+)={E}\[(?P<a_r>\d)\];(?P<top>\w+)=(?P=al)\+\w+-1;for(?P<lv>\w+)=(?P=al),(?P=top)do(?:local)?(?P<el>\w+)=\w+\[(?P=lv)-(?P=al)\];?{R}\[(?P=lv)\]=(?P=el);?end$", {"a": "a"}),
    ("SETLIST_TOP", r"^(?P<al>\w+)={E}\[(?P<a_r>\d)\];(?P<tb>\w+)={R}\[(?P=al)\];for(?P<lv>\w+)=(?P=al)\+1,(?P<top>[A-Za-z_]\w*)do\w+\((?P=tb),{R}\[(?P=lv)\]\)end$", {"a": "a"}),
    ("SETLIST", r"^(?P<al>\w+)={E}\[(?P<a_r>\d)\];(?P<tb>\w+)={R}\[(?P=al)\];for(?P<lv>\w+)=(?P=al)\+1,<kx:b>do\w+\((?P=tb),{R}\[(?P=lv)\]\)end$", {"a": "a", "b": "b"}),
    ("TFORLOOP", r"^(?P<ca>\w+)={E}\[2\];(?P<cn>\w+)={E}\[4\];(?P<n>\w+)=(?P=ca)\+2;(?P=ca)=\{{R}\[(?P=ca)\]\({R}\[(?P=ca)\+1\],{R}\[(?P=n)\]\),\};for(?P<lv>\w+)=1,(?P=cn)do{R}\[(?P=n)\+(?P=lv)\]=(?P=ca)\[(?P=lv)\];end;(?P=ca)=(?P=ca)\[1\];if(?P=ca)then{R}\[(?P=n)\]=(?P=ca);?{P}={E}\[3\];else{P}={P}\+1;end$", {}),
    ("VARARG", r"^(?P<top>\w+)={E}\[(?P<a_r>\d)\]\+\w+-1;for(?P<lv>\w+)={E}\[(?P=a_r)\],(?P=top)do(?:local)?(?P<el>\w+)=\w+\[(?P=lv)-{E}\[(?P=a_r)\]\];?{R}\[(?P=lv)\]=(?P=el)\[2\];?end$", {"a": "a"}),
    ("SETLIST_TOP", r"^(?P<tb>\w+)={R}\[{E}\[(?P<a_r>\d)\]\];for(?P<lv>\w+)={E}\[(?P=a_r)\]\+1,(?P<top>[A-Za-z_]\w*)do\w+\((?P=tb),{R}\[(?P=lv)\]\)end$", {"a": "a"}),
    ("SETLIST", r"^(?P<tb>\w+)={R}\[{E}\[(?P<a_r>\d)\]\];for(?P<lv>\w+)={E}\[(?P=a_r)\]\+1,<kx:b>do\w+\((?P=tb),{R}\[(?P=lv)\]\)end$", {"a": "a", "b": "b"}),
]

def classify_raw(raw, roles):
    for kind, tpl, names in RAW:
        m = re.search(_ex(tpl, roles), raw)
        if m:
            spec = {"kind": kind}
            for sname, gname in names.items():
                spec[sname] = _operand(m, gname)
            if kind == "CALLFIX0":
                spec = {"kind": "CALL", "args": ("n", 0), "results": "fixed"}
            return spec
    return None
