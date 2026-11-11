"""Forme a versions dans les blocs, terminateurs, propagation conditionnelle de constantes/references."""
import math
from .ir import conv, conv_block, fold_bin, lua_truthy, TOP
from .machine import *

def mapreg(e, fn):
    if isinstance(e, tuple):
        if e and e[0] == 'reg' and len(e) == 2: return fn(e[1])
        return tuple(mapreg(x, fn) for x in e)
    if isinstance(e, list): return [mapreg(x, fn) for x in e]
    return e

def regs_in(e, out):
    if isinstance(e, tuple):
        if e and e[0] == 'reg' and len(e) == 3: out.append((e[1], e[2])); return
        for x in e: regs_in(x, out)
    elif isinstance(e, list):
        for x in e: regs_in(x, out)

class Block:
    def __init__(self, bid, state):
        self.id = bid; self.state = state
        self.stmts = []; self.term = None; self.final = {}

def getreg_env(entry, local):
    def g(name, ver):
        if ver == 0: return entry.get(name, ('c', None))
        return local.get((name, ver), TOP)
    return g

def ev(e, g, upvals):
    k = e[0]
    if k == 'const': return ('c', e[1])
    if k == 'reg': return g(e[1], e[2])
    if k == 'ref': return ('r', e[1])
    if k == 'alloc': return ('r', e[1])
    if k == 'upref':
        if upvals is not None and 1 <= e[1] <= len(upvals): return upvals[e[1] - 1]
        return TOP
    if k == 'bin':
        a = ev(e[2], g, upvals); b = ev(e[3], g, upvals)
        if a and b and a[0] == 'c' and b[0] == 'c': return fold_bin(e[1], a[1], b[1])
        return TOP
    if k == 'un':
        a = ev(e[2], g, upvals)
        if a and a[0] == 'c':
            v = a[1]
            if e[1] == 'not': return ('c', not lua_truthy(v))
            if e[1] == '-' and isinstance(v, (int, float)) and not isinstance(v, bool): return ('c', -v)
            if e[1] == '#' and isinstance(v, str): return ('c', len(v))
        if a and a[0] == 'r' and e[1] == 'not': return ('c', False)
        return TOP
    if k in ('and', 'or'):
        a = ev(e[1], g, upvals)
        if a is not None and a[0] == 'c':
            t = lua_truthy(a[1])
            if k == 'and': return ev(e[2], g, upvals) if t else a
            return a if t else ev(e[2], g, upvals)
        if a is not None and a[0] == 'r':
            return ev(e[2], g, upvals) if k == 'and' else a
        return TOP
    return TOP

def rewrite(e, g, upvals):
    """remplace les valeurs abstraites connues (constantes, references) ; plie les operations constantes"""
    k = e[0]
    if k == 'reg':
        a = g(e[1], e[2])
        if a is not None: return ('const', a[1]) if a[0] == 'c' else ('ref', a[1])
        return e
    if k in ('const', 'ref', 'role', 'args', 'arg', 'alloc', 'rawfn'): return e
    if k == 'upref':
        a = upvals[e[1] - 1] if upvals is not None and 1 <= e[1] <= len(upvals) else None
        return ('ref', a[1]) if a and a[0] == 'r' else e
    if k == 'upget':
        a = upvals[e[1] - 1] if upvals is not None and 1 <= e[1] <= len(upvals) else None
        return ('varget', ('ref', a[1])) if a and a[0] == 'r' else e
    if k in ('and', 'or'):
        a = ev(e[1], g, upvals)
        if a is not None and a[0] == 'c':
            t = lua_truthy(a[1])
            if k == 'and': return rewrite(e[2], g, upvals) if t else ('const', a[1])
            return ('const', a[1]) if t else rewrite(e[2], g, upvals)
        if a is not None and a[0] == 'r':
            return rewrite(e[2], g, upvals) if k == 'and' else ('ref', a[1])
        return (k, rewrite(e[1], g, upvals), rewrite(e[2], g, upvals))
    if k in ('bin', 'un'):
        r = ev(e, g, upvals)
        if r is not None and r[0] == 'c': return ('const', r[1])
        if k == 'bin': return ('bin', e[1], rewrite(e[2], g, upvals), rewrite(e[3], g, upvals))
        if k == 'un': return ('un', e[1], rewrite(e[2], g, upvals))
        return (k, rewrite(e[1], g, upvals), rewrite(e[2], g, upvals))
    if k == 'closure': return ('closure', e[1], e[2], [rewrite(x, g, upvals) for x in e[3]])
    if k == 'tbl': return ('tbl', [rewrite(x, g, upvals) for x in e[1]])
    if k == 'kv': return ('kv', rewrite(e[1], g, upvals), rewrite(e[2], g, upvals))
    if k == 'call': return ('call', rewrite(e[1], g, upvals), [rewrite(x, g, upvals) for x in e[2]])
    if k in ('varget', 'global', 'unpack', 'release'): return (k, rewrite(e[1], g, upvals))
    if k == 'index': return ('index', rewrite(e[1], g, upvals), rewrite(e[2], g, upvals))
    return e

def build_blocks(M):
    regs = set(M.regs) | {M.vname, M.argname, M.upname, M.proxyname}
    M.regset = regs
    blocks = []
    for i, (lo, hi, body) in enumerate(M.leaves):
        b = Block(i, lo)
        ir = conv_block(M, body, regs)
        cur = {}; ctr = {}
        defs = {}
        out = []
        def ren(e): return mapreg(e, lambda n: ('reg', n, cur.get(n, 0)))
        for st in ir:
            k = st[0]
            if k == 'set':
                e = ren(st[2])
                ctr[st[1]] = ctr.get(st[1], 0) + 1
                cur[st[1]] = ctr[st[1]]
                tgt = (st[1], cur[st[1]])
                defs[tgt] = e
                out.append(('set', tgt, e))
            elif k == 'mset':
                e = ren(st[2]); tg = []
                for n in st[1]:
                    ctr[n] = ctr.get(n, 0) + 1; cur[n] = ctr[n]; tg.append((n, cur[n]))
                out.append(('mset', tg, e))
            else:
                out.append((k,) + tuple(ren(x) for x in st[1:]))
        b.stmts = out; b.final = dict(cur); b.defs = defs
        # terminateur : valeur finale de v
        vv = ('reg', M.vname, cur.get(M.vname, 0))
        def expand(e, depth=0):
            while e[0] == 'reg' and (e[1], e[2]) in defs and depth < 50:
                e = defs[(e[1], e[2])]; depth += 1
            return e
        def lconst(e, depth=0):
            """valeur litterale de e via les definitions locales (ou None)"""
            if depth > 60: return None
            if e[0] == 'const': return ('c', e[1])
            if e[0] == 'reg':
                if (e[1], e[2]) in defs: return lconst(defs[(e[1], e[2])], depth + 1)
                return None
            return None
        def tgt(e):
            c = lconst(e)
            if c and isinstance(c[1], (int, float)) and not isinstance(c[1], bool): return leaf_index(M, c[1])
            return None
        t = expand(vv)
        if t[0] == 'const' and tgt(t) is not None: b.term = ('goto', tgt(t))
        elif t[0] == 'or':
            a = expand(t[1]); n2 = tgt(t[2])
            if a[0] == 'and' and tgt(a[2]) is not None and n2 is not None:
                b.term = ('branch', a[1], tgt(a[2]), n2)
            else: b.term = ('exit', ('reg', M.retreg, cur.get(M.retreg, 0)))
        elif t[0] == 'and' and tgt(t[2]) is not None:
            b.term = ('branch', t[1], tgt(t[2]), None)
        else:
            b.term = ('exit', ('reg', M.retreg, cur.get(M.retreg, 0)))
        blocks.append(b)
    return blocks
