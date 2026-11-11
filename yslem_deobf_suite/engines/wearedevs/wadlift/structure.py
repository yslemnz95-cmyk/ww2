"""Structuration du graphe de blocs : if/else, boucles, break/continue ; repli en machine a etats."""
import collections
from .emit import *

class Ctx:
    def __init__(self, loops=(), stops=frozenset()):
        self.loops = loops      # pile de (header, follow, bodyset)
        self.stops = stops
    def with_stop(self, j): return Ctx(self.loops, self.stops | {j})
    def with_loop(self, h, f, body): return Ctx(self.loops + ((h, f, body),), frozenset())

class Structurer:
    def __init__(self, fe):
        self.fe = fe; F = fe.F
        self.entry = F.entry_bid
        self.succ = fe.succ; self.pred = fe.pred
        self.plans = {b: fe.plan_block(b) for b in F.bids}
        self.compute_orders()
        self.compute_dom()
        self.compute_postdom()
        self.find_loops()
        self.emitted = 0
        self.budget = 6 * len(fe.F.bids) + 60

    # ---- ordres, dominateurs ----
    def compute_orders(self):
        seen = set(); post = []
        stack = [(self.entry, iter(self.succ[self.entry]))]; seen.add(self.entry)
        self.dfs_stack = set([self.entry]); self.retreat = []
        onstack = {self.entry}
        while stack:
            n, it = stack[-1]
            for s in it:
                if s in onstack: self.retreat.append((n, s))
                elif s not in seen:
                    seen.add(s); onstack.add(s); stack.append((s, iter(self.succ[s]))); break
            else:
                stack.pop(); onstack.discard(n); post.append(n)
        self.rpo = list(reversed(post)); self.rpo_idx = {b: i for i, b in enumerate(self.rpo)}

    def compute_dom(self):
        idom = {self.entry: self.entry}
        changed = True
        def inter(a, b):
            while a != b:
                while self.rpo_idx[a] > self.rpo_idx[b]: a = idom[a]
                while self.rpo_idx[b] > self.rpo_idx[a]: b = idom[b]
            return a
        while changed:
            changed = False
            for b in self.rpo[1:]:
                ps = [p for p in self.pred[b] if p in idom]
                if not ps: continue
                n = ps[0]
                for p in ps[1:]: n = inter(p, n)
                if idom.get(b) != n: idom[b] = n; changed = True
        self.idom = idom
    def dominates(self, a, b):
        while True:
            if a == b: return True
            if b == self.entry: return False
            b = self.idom[b]

    def compute_postdom(self):
        # graphe inverse avec sortie virtuelle X = -1
        X = -1
        nodes = list(self.rpo)
        succ = {b: list(self.succ[b]) or [X] for b in nodes}
        pred = collections.defaultdict(list)
        for b in nodes:
            for s in succ[b]: pred[s].append(b)
        # ordre inverse : DFS sur le graphe inverse depuis X
        seen = {X}; post = []; stack = [(X, iter(pred[X]))]
        while stack:
            n, it = stack[-1]
            for s in it:
                if s not in seen: seen.add(s); stack.append((s, iter(pred[s]))); break
            else: stack.pop(); post.append(n)
        rpo = list(reversed(post)); idx = {b: i for i, b in enumerate(rpo)}
        ip = {X: X}
        def inter(a, b):
            while a != b:
                while idx[a] > idx[b]: a = ip[a]
                while idx[b] > idx[a]: b = ip[b]
            return a
        changed = True
        while changed:
            changed = False
            for b in rpo[1:]:
                ps = [s for s in succ[b] if s in ip]
                if not ps: continue
                n = ps[0]
                for p in ps[1:]: n = inter(p, n)
                if ip.get(b) != n: ip[b] = n; changed = True
        self.ipdom = ip
        self.X = X

    # ---- boucles ----
    def find_loops(self):
        self.loops = {}
        for (u, h) in self.retreat:
            if not self.dominates(h, u): raise Unstructurable('graphe irreductible')
        for u in self.fe.F.bids:
            for h in self.succ[u]:
                if h in self.rpo_idx and u in self.rpo_idx and self.dominates(h, u):
                    body = self.loops.setdefault(h, {h})
                    stack = [u]
                    while stack:
                        n = stack.pop()
                        if n in body: continue
                        body.add(n)
                        stack.extend(p for p in self.pred[n] if p in self.rpo_idx)
        self.headers = set(self.loops)

    def reach_from(self, start, forbid):
        seen = set(); st = [start]
        while st:
            n = st.pop()
            if n in seen or n in forbid: continue
            seen.add(n); st.extend(self.succ[n])
        return seen

    # ---- emission ----
    def build(self):
        return self.seq(self.entry, Ctx())

    def jump(self, t, ctx):
        """instructions pour aller en t ; (liste, suite) ; suite = bloc a continuer en ligne ou None"""
        if t in ctx.stops: return [], None
        if ctx.loops:
            h, f, body = ctx.loops[-1]
            if t == h: return [('continue',)], None
            if f is not None and t == f: return [('break',)], None
            for (h2, f2, b2) in ctx.loops[:-1]:
                if t == h2 or t == f2: raise Unstructurable('saut vers une boucle englobante')
        return [], t

    def seq(self, b, ctx):
        out = []
        while True:
            if b in self.headers and not (ctx.loops and ctx.loops[-1][0] == b):
                stm, nxt = self.loop(b, ctx)
                out += stm
                if nxt is None: return out
                b = nxt
                j, cont = self.jump(b, ctx)
                if cont is None: return out + j
                continue
            ops, term = self.plans[b]
            self.emitted += 1
            if self.emitted > self.budget: raise Unstructurable('duplication excessive')
            if ops: out.append(('blk', ops))
            if term[0] == 'exit':
                out.append(('return', term[1])); return out
            if term[0] == 'goto':
                j, cont = self.jump(term[1], ctx)
                out += j
                if cont is None: return out
                b = cont; continue
            # branche
            C, t, f = term[1], term[2], term[3]
            if f is None:
                # faux -> sortie (retour de d)
                f = 'RET'
            stm, nxt = self.branch(b, C, t, f, ctx)
            out += stm
            if nxt is None: return out
            j, cont = self.jump(nxt, ctx)
            out += j
            if cont is None: return out
            b = cont

    def arm(self, t, ctx):
        if t == 'RET':
            return [('return_none',)]
        j, cont = self.jump(t, ctx)
        if cont is None: return j
        return self.seq(cont, ctx)

    def branch(self, b, C, t, f, ctx):
        ip = self.ipdom.get(b)
        merge = None
        if ip is not None and ip != self.X and ip != b:
            merge = ip
            # un vrai point de jonction doit etre dans la boucle courante
            if ctx.loops:
                h, fo, body = ctx.loops[-1]
                if merge not in body or merge == h: merge = None
        # si le merge est deja un stop englobant, ne rien ajouter
        c2 = ctx.with_stop(merge) if merge is not None and merge not in ctx.stops else ctx
        thn = self.arm(t, c2); els = self.arm(f, c2) if f != 'RET' else [('return_none',)]
        stm = [('if', C, thn, els)]
        return stm, merge

    def loop(self, h, ctx):
        body = self.loops[h]
        exits = []
        for n in body:
            for s in self.succ[n]:
                if s not in body and s not in exits: exits.append(s)
        # suite de la boucle : parmi les sorties, celle qui mene a la fin de la fonction et couvre le plus de blocs ;
        # les autres (retours isoles, pieges sans issue) sont recopiees sur place
        follow = None
        if len(exits) == 1: follow = exits[0]
        elif exits:
            best = None
            for s_ in exits:
                r = self.reach_from(s_, set())
                reaches_end = any(not self.succ[n] for n in r)
                key = (1 if reaches_end else 0, len(r))
                if best is None or key > best[0]: best = (key, s_)
            follow = best[1]
        c2 = ctx.with_loop(h, follow, body)
        # sorties independantes autres que follow : on les inline (code duplique) via 'jump' -> cont
        inner = self.seq(h, c2)
        # nettoyage : retirer un 'continue' final
        while inner and inner[-1] == ('continue',): inner.pop()
        stm = [('while', ('const', True), inner)]
        return stm, follow
