"""Du graphe de blocs a du Lua structure."""
import collections, re
from .ssa import regs_in, ev, rewrite
from .machine import *
from .lua_ast import lua_str, fmt_num

class Unstructurable(Exception): pass

# ---------------- classification des expressions ----------------
def walk_ir(e, fn):
    if isinstance(e, tuple):
        if e and isinstance(e[0], str): fn(e)
        for x in e: walk_ir(x, fn)
    elif isinstance(e, list):
        for x in e: walk_ir(x, fn)

def is_effectful(e):
    f = [False]
    def g(n):
        if n[0] in ('call', 'release'): f[0] = True
    walk_ir(e, g)
    return f[0]

def reads_eff(e):
    """(ensemble des categories lues, appel ?)"""
    r = set(); eff = [False]
    def g(n):
        k = n[0]
        if k in ('varget', 'upget'): r.add('var')
        elif k == 'global': r.add('global')
        elif k == 'index': r.add('heap')
        elif k in ('call', 'release'): eff[0] = True; r.update(('var', 'global', 'heap'))
    walk_ir(e, g)
    return r, eff[0]

def is_immutable(e):
    r = [True]
    def g(n):
        if n[0] in ('call', 'varget', 'global', 'index', 'upget', 'release', 'unpack', 'rawfn'): r[0] = False
    walk_ir(e, g)
    return r[0]

MULTI = ('call', 'unpack')

class FuncEmit:
    def __init__(self, M, F, fe_cache):
        self.M = M; self.F = F; self.cache = fe_cache
        self.tmp = 0
        self.cands = {}

    # ---------- liveness ----------
    def succs_of(self, term):
        if term[0] == 'goto': return [term[1]]
        if term[0] == 'branch': return [x for x in (term[2], term[3]) if x is not None]
        return []

    def prepare(self):
        F = self.F
        self.succ = {b: self.succs_of(F.blocks[b][1]) for b in F.bids}
        self.pred = collections.defaultdict(list)
        for b in F.bids:
            for s in self.succ[b]: self.pred[s].append(b)
        uses0 = {}; defined = {}
        for b in F.bids:
            stmts, term, ins, env = F.blocks[b]
            lst = []
            for s in stmts:
                if s[0] in ('set', 'mset'): regs_in(s[2], lst)
                else: regs_in(s[1:], lst)
            regs_in(term[1:], lst)
            uses0[b] = {n for (n, v) in lst if v == 0}
            defined[b] = {s[1][0] for s in stmts if s[0] == 'set'} | {t[0] for s in stmts if s[0] == 'mset' for t in s[1]}
        live_in = {b: set() for b in F.bids}; live_out = {b: set() for b in F.bids}
        changed = True
        while changed:
            changed = False
            for b in reversed(F.bids):
                lo = set()
                for s in self.succ[b]: lo |= live_in[s]
                li = uses0[b] | (lo - defined[b])
                if lo != live_out[b] or li != live_in[b]:
                    live_out[b] = lo; live_in[b] = li; changed = True
        self.live_out = live_out; self.live_in = live_in
        self.cross = set()
        for b in F.bids: self.cross |= live_in[b]
        self.cross.discard(self.M.vname)

    # ---------- reperage / remplacement des chaines chiffrees ----------
    def decrypt_pass(self, stmts, term):
        defs = {}
        for si, s in enumerate(stmts):
            if s[0] == 'set': defs[s[1]] = si
        def resolve(e):
            n = 0
            while e[0] == 'reg' and (e[1], e[2]) in defs and n < 30:
                e = stmts[defs[(e[1], e[2])]][2]; n += 1
            return e
        uses = collections.Counter()
        lst = []
        for s in stmts: regs_in(s[2] if s[0] in ('set', 'mset') else s[1:], lst)
        regs_in(term[1:], lst)
        for k in lst: uses[k] += 1
        dm = getattr(self, 'decmap', None); dp = getattr(self, 'decpair', None)
        for si, s in enumerate(stmts):
            if s[0] != 'set' or s[2][0] != 'index': continue
            A = resolve(s[2][1]); Bk = resolve(s[2][2])
            if Bk[0] != 'call' or len(Bk[2]) != 2: continue
            c1 = resolve(Bk[2][0]); c2 = resolve(Bk[2][1]); Fn = resolve(Bk[1])
            if c1[0] == 'const' and isinstance(c1[1], str) and c2[0] == 'const' and isinstance(c2[1], (int, float)) \
               and Fn[0] == 'varget' and Fn[1][0] == 'ref' and A[0] == 'varget' and A[1][0] == 'ref':
                pair = (A[1][1], Fn[1][1])
                self.cands.setdefault(pair, set()).add((c1[1], c2[1]))
                if dm and dp == pair and (c1[1], c2[1]) in dm:
                    stmts[si] = ('set', s[1], ('const', dm[(c1[1], c2[1])]))
                    # appel devenu inutile
                    kreg = s[2][2]
                    if kreg[0] == 'reg' and uses[(kreg[1], kreg[2])] == 1 and (kreg[1], kreg[2]) in defs:
                        j = defs[(kreg[1], kreg[2])]
                        stmts[j] = ('set', stmts[j][1], ('const', None))
        return stmts

    # ---------- planification d'un bloc ----------
    def newtmp(self):
        self.tmp += 1
        return 't%d' % self.tmp

    def plan_block(self, b):
        F = self.F; M = self.M
        stmts, term, ins, env = F.blocks[b]
        stmts = self.decrypt_pass(list(stmts), term)
        final = M.blocks[b].final
        moves = [(n, final[n]) for n in sorted(self.live_out[b]) if n in final and n != M.vname and final[n] != 0]
        defs = {}
        for si, s in enumerate(stmts):
            if s[0] == 'set': defs[s[1]] = si
        live = set(); work = []
        def need(e):
            lst = []; regs_in(e, lst)
            for k in lst:
                if k[1] != 0 and k in defs and defs[k] not in live:
                    live.add(defs[k]); work.append(defs[k])
        def drain():
            while work:
                si = work.pop(); s = stmts[si]
                need(s[2] if s[0] in ('set', 'mset') else s[1:])
        for si, s in enumerate(stmts):
            if s[0] != 'set' or s[2][0] == 'alloc' or (is_effectful(s[2]) and s[2][0] != 'release'):
                live.add(si); work.append(si)
        for name, ver in moves:
            if (name, ver) in defs and defs[(name, ver)] not in live: live.add(defs[(name, ver)]); work.append(defs[(name, ver)])
        need(term[1:]); drain()
        used = collections.Counter()
        def count(e):
            lst = []; regs_in(e, lst)
            for k in lst: used[k] += 1
        for si in sorted(live):
            s = stmts[si]; count(s[2] if s[0] in ('set', 'mset') else s[1:])
        count(term[1:])
        for k in moves: used[k] += 1
        ops = []
        pend = collections.OrderedDict()   # cle -> (expr, immutable)
        mat = {}
        def tmpname(k):
            if k not in mat: mat[k] = self.newtmp()
            return mat[k]
        def flush(k):
            expr = pend.pop(k)[0]
            ops.append(('local', tmpname(k), expr))
        def sub(e):
            if isinstance(e, tuple):
                if e and e[0] == 'reg' and len(e) == 3:
                    k = (e[1], e[2])
                    if k in pend: return pend.pop(k)[0]
                    if e[2] == 0: return ('const', None) if e[1] == M.vname else ('rvar', e[1])
                    return ('tmp', tmpname(k))
                return tuple(sub(x) for x in e)
            if isinstance(e, list): return [sub(x) for x in e]
            return e
        def mk(expr):
            rd, ef = reads_eff(expr)
            return (expr, is_immutable(expr), rd, ef)
        def take(raws, will_emit, writes=frozenset()):
            lst = []; regs_in(raws, lst)
            keys = [k for k in lst if k in pend]
            order = {k: i for i, k in enumerate(pend)}
            nonimm = [k for k in pend if not pend[k][1]]
            ref_nonimm = [k for k in keys if not pend[k][1]]
            bad = ref_nonimm != sorted(set(ref_nonimm), key=order.get) or len(set(ref_nonimm)) != len(ref_nonimm)
            op_reads = set()
            if will_emit:
                op_reads, op_eff = reads_eff(raws)
                for k in keys:
                    op_reads |= set(pend[k][2])
            def conflicts(k):
                ex, imm, rd, ef = pend[k]
                if not will_emit: return False
                if ef and (writes or op_reads or True): return True
                if writes and ('*' in writes and rd or (rd & writes)): return True
                return False
            unref = [k for k in nonimm if k not in keys and (conflicts(k) or not will_emit)]
            newest_unref = max([order[k] for k in unref], default=-1)
            for k in nonimm:
                if k in keys:
                    if bad or order[k] < newest_unref: flush(k)
                elif conflicts(k): flush(k)
        for si, s in enumerate(stmts):
            if si not in live: continue
            if s[0] == 'set':
                key = s[1]; E = s[2]
                if E[0] == 'alloc': ops.append(('decl', E[1])); continue
                if E[0] == 'release': continue
                n = used[key]
                if n == 1:
                    take(E, False)
                    pend[key] = mk(sub(E))
                    continue
                take(E, True, {'*'} if is_effectful(E) else frozenset())
                E2 = sub(E)
                if n == 0: ops.append(('expr', E2))
                else: ops.append(('local', tmpname(key), E2))
            elif s[0] == 'mset':
                take(s[2], True, frozenset({'*'}))
                E2 = sub(s[2])
                names = [tmpname(t) if used[t] > 0 else '_' for t in s[1]]
                ops.append(('mlocal', names, E2))
            else:
                wr = {'varset': {'var'}, 'upset': {'var'}, 'gset': {'global'}, 'iset': {'heap'}}.get(s[0], set())
                if any(is_effectful(x) for x in s[1:] if isinstance(x, tuple)): wr = wr | {'*'}
                take(list(s[1:]), True, frozenset(wr))
                args = [x if (s[0] == 'upset' and i == 0) else sub(x) for i, x in enumerate(s[1:])]
                ops.append((s[0],) + tuple(args))
        # terminateur puis mouvements (copie parallele)
        take([term[1:], [('reg', n, v) for n, v in moves]], True, frozenset({'*'}))
        tm = (term[0],) + tuple(sub(x) if isinstance(x, (tuple, list)) else x for x in term[1:])
        mv = [(n, sub(('reg', n, v))) for n, v in moves]
        moved = {n for n, _ in moves}
        def mentions_moved(e):
            r = [False]
            def g(x):
                if x[0] == 'rvar' and x[1] in moved: r[0] = True
            walk_ir(e, g)
            return r[0]
        if tm[0] == 'branch' and mv and mentions_moved(tm[1]):
            t = self.newtmp(); ops.append(('local', t, tm[1])); tm = ('branch', ('tmp', t), tm[2], tm[3])
        if tm[0] == 'exit' and mv:
            pass
        out_moves = []
        for n, e in mv:
            if mentions_moved(e) and not (e[0] == 'rvar' and e[1] == n):
                t = self.newtmp(); ops.append(('local', t, e)); e = ('tmp', t)
            out_moves.append(('set', ('rvar', n), e))
        ops += out_moves
        return ops, tm
