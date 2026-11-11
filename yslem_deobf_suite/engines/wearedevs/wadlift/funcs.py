from .ssa import *

class Func:
    def __init__(self, entry, arity, upvals):
        self.entry = entry; self.arity = arity; self.upvals = upvals
        self.bids = []; self.blocks = {}; self.entry_bid = None

def site_stmt(bid, si): return ('z', bid, si)

def run_block(M, blk, entry_env, upvals, subst):
    """evalue le bloc sous un environnement d'entree ; renvoie (env_sortie (par nom), stmts_reecrites, abstraits locaux)"""
    local = {}
    g = getreg_env(entry_env, local)
    out = []
    for si, s in enumerate(blk.stmts):
        k = s[0]
        if k == 'set':
            e = s[2]
            if e[0] == 'alloc': e = ('alloc', site_stmt(blk.id, si))
            a = ev(e, g, upvals)
            if e[0] == 'release': a = ('c', None)
            local[s[1]] = a
            out.append(('set', s[1], rewrite(e, g, upvals) if subst else e))
        elif k == 'mset':
            for t in s[1]: local[t] = TOP
            out.append(('mset', s[1], rewrite(s[2], g, upvals) if subst else s[2]))
        elif k == 'upset':
            a = upvals[s[1] - 1] if upvals is not None and 1 <= s[1] <= len(upvals) else None
            if subst and a and a[0] == 'r': out.append(('varset', ('ref', a[1]), rewrite(s[2], g, upvals)))
            else: out.append(('upset', s[1], rewrite(s[2], g, upvals) if subst else s[2]))
        else:
            out.append((k,) + tuple(rewrite(x, g, upvals) if subst else x for x in s[1:]))
    env = dict(entry_env)
    for name, ver in blk.final.items(): env[name] = local.get((name, ver), TOP)
    return env, out, g

def join(a, b):
    out = {}
    for k in set(a) | set(b):
        x = a.get(k, ('c', None)); y = b.get(k, ('c', None))
        out[k] = x if x == y else TOP
    return out

def analyse_function(M, blocks, F):
    eb = leaf_index(M, F.entry); F.entry_bid = eb
    ins = {eb: {n: TOP for n in getattr(M, 'reg_init_ast', {})}}; work = [eb]; guard = 0
    def succs(blk, g):
        t = blk.term
        if t[0] == 'goto': return [t[1]]
        if t[0] == 'branch':
            c = ev(t[1], g, F.upvals)
            if c is not None and c[0] == 'c': return [x for x in [t[2] if lua_truthy(c[1]) else t[3]] if x is not None]
            if c is not None and c[0] == 'r': return [t[2]]
            return [x for x in [t[2], t[3]] if x is not None]
        return []
    while work:
        guard += 1
        if guard > 300000: raise LiftError('propagation sans fin')
        b = work.pop(); blk = blocks[b]
        env, _, g = run_block(M, blk, ins[b], F.upvals, False)
        for s in succs(blk, g):
            new = join(ins[s], env) if s in ins else dict(env)
            if s not in ins or new != ins[s]:
                ins[s] = new; work.append(s)
    for b in sorted(ins):
        blk = blocks[b]
        env, stmts, g = run_block(M, blk, ins[b], F.upvals, True)
        t = blk.term
        if t[0] == 'goto': nt = t
        elif t[0] == 'branch':
            c = ev(t[1], g, F.upvals)
            if c is not None and (c[0] == 'r' or c[0] == 'c'):
                truth = True if c[0] == 'r' else lua_truthy(c[1])
                dest = t[2] if truth else t[3]
                nt = ('goto', dest) if dest is not None else ('exit', rewrite(t[1] if False else ('reg', M.retreg, blk.final.get(M.retreg, 0)), g, F.upvals))
            else: nt = ('branch', rewrite(t[1], g, F.upvals), t[2], t[3])
        else:
            nt = ('exit', rewrite(t[1], g, F.upvals))
        F.blocks[b] = (stmts, nt, ins[b], env)
    F.bids = sorted(F.blocks)

def lift_all(M):
    blocks = build_blocks(M); M.blocks = blocks
    funcs = {}
    queue = [(M.main_entry, M.creators[M.main_creator], [])]
    while queue:
        entry, arity, upv = queue.pop(0)
        if entry in funcs: continue
        F = Func(entry, arity, upv); funcs[entry] = F
        analyse_function(M, blocks, F)
        def scan(e):
            if isinstance(e, tuple):
                if e and e[0] == 'closure':
                    queue.append((e[2], e[1], [('r', c[1]) if c[0] == 'ref' else TOP for c in e[3]]))
                for x in e: scan(x)
            elif isinstance(e, list):
                for x in e: scan(x)
        for b in F.bids:
            for s in F.blocks[b][0]: scan(s)
    M.funcs = funcs
    return funcs
