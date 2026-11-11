"""Ecriture du Lua final a partir de l'arbre structure."""
import re, collections
from .structure import *
from .lua_ast import lua_str, fmt_num

KEYWORDS = {'and','break','do','else','elseif','end','false','for','function','if','in','local','nil','not','or','repeat','return','then','true','until','while','continue'}
IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
PREC = {'or':1,'and':2,'<':3,'>':3,'<=':3,'>=':3,'~=':3,'==':3,'..':5,'+':6,'-':6,'*':7,'/':7,'%':7,'^':10}
RIGHT = {'..','^'}

def fe_reason(r, F):
    return r.fcache[F.entry][3]

def st_entry(fe):
    return fe.F.entry_bid

class Renderer:
    def __init__(self, M, hoist=None, decmap=None, inject=None):
        self.M = M
        self.decmap = decmap or {}
        self.decpair = None
        self.inject = inject or {}     # id de variable -> code a ecrire apres son affectation
        self.cands = collections.defaultdict(set)
        self.varnames = {}
        self.hoist = hoist if hoist is not None else set()
        self.fcache = {}
        self.cur = []       # pile de (F, params)
        self.problems = []
        self.nvars = 0
        self.spill = set()        # entrees de fonctions dont les variables passent par une table
        self.force_hoist = set()  # fonctions en machine a etats
        self.owner_map = {}
        for ent, F in M.funcs.items():
            for b in F.bids:
                for si, st in enumerate(F.blocks[b][0]):
                    if st[0] == 'set' and st[2][0] == 'alloc': self.owner_map[st[2][1]] = ent

    def vname(self, vid):
        if vid not in self.varnames:
            self.nvars += 1
            own = self.owner_map.get(vid)
            self.varnames[vid] = ('V%d.v%d' % (own, self.nvars)) if own in self.spill else 'v%d' % self.nvars
        return self.varnames[vid]

    def sd(self, x):
        """remplace v15[v16("..", cle)] par la chaine dechiffree si connue"""
        if self.decmap and x[0] == 'index' and x[2][0] == 'call':
            c = x[2]
            if len(c[2]) == 2 and c[2][0][0] == 'const' and c[2][1][0] == 'const':
                v = self.decmap.get((c[2][0][1], c[2][1][1]))
                if v is not None: return ('const', v)
        return x

    # ---------- expressions ----------
    def e(self, x, parent=0):
        x = self.sd(x)
        k = x[0]
        if k == 'const':
            v = x[1]
            if v is None: return 'nil'
            if v is True: return 'true'
            if v is False: return 'false'
            if isinstance(v, str): return lua_str(v)
            s = fmt_num(v)
            return '(' + s + ')' if s.startswith('-') and parent >= 8 else s
        if k == 'rvar': return 'r_' + x[1]
        if k == 'tmp':
            if self.cur and self.cur[-1][0].entry in self.spill: return 'V%d.%s' % (self.cur[-1][0].entry, x[1])
            return x[1]
        if k == 'ref': return self.vname(x[1])
        if k == 'varget':
            r = x[1]
            if r[0] == 'ref': return self.vname(r[1])
            self.problems.append('varget non resolu'); return 'VAR[%s]' % self.e(r)
        if k == 'upget': self.problems.append('upvalue non resolu'); return 'UPV[%d]' % x[1]
        if k == 'upref': self.problems.append('upref'); return 'UPREF[%d]' % x[1]
        if k == 'role': self.problems.append('role ' + x[1]); return '__' + x[1]
        if k == 'arg':
            F, params = self.cur[-1]
            if F.arity == -1: return 'select(%d, ...)' % x[1]
            if x[1] <= F.arity: return 'p%d' % x[1]
            return 'nil'
        if k == 'args':
            F, params = self.cur[-1]
            return '{...}' if F.arity == -1 else '{' + ', '.join('p%d' % i for i in range(1, F.arity + 1)) + '}'
        if k == 'global':
            kk = x[1]
            if kk[0] == 'const' and isinstance(kk[1], str) and IDENT.match(kk[1]) and kk[1] not in KEYWORDS: return kk[1]
            return 'getfenv()[%s]' % self.e(kk)
        if k == 'index':
            b = x[1]; kk = self.sd(x[2])
            bs = self.e(b, 99)
            if b[0] in ('const', 'bin', 'un', 'and', 'or', 'tbl', 'closure'): bs = '(' + bs + ')'
            if kk[0] == 'const' and isinstance(kk[1], str) and IDENT.match(kk[1]) and kk[1] not in KEYWORDS: return bs + '.' + kk[1]
            return bs + '[' + self.e(kk) + ']'
        if k == 'call': return self.call(x)
        if k == 'unpack':
            a = x[1]
            if a[0] == 'args':
                F, _ = self.cur[-1]
                if F.arity == -1: return '...'
            if a[0] == 'tbl' and len(a[1]) == 1 and a[1][0][0] in ('call', 'unpack'): return self.e(a[1][0])
            return 'unpack(' + self.e(a) + ')'
        if k == 'tbl':
            parts = []
            for it in x[1]:
                if it[0] == 'kv':
                    kk = self.sd(it[1])
                    if kk[0] == 'const' and isinstance(kk[1], str) and IDENT.match(kk[1]) and kk[1] not in KEYWORDS: parts.append(kk[1] + ' = ' + self.e(it[2]))
                    else: parts.append('[' + self.e(kk) + '] = ' + self.e(it[2]))
                else: parts.append(self.e(it))
            return '{' + ', '.join(parts) + '}'
        if k in ('bin', 'and', 'or'):
            if k == 'bin': op, a, b = x[1], x[2], x[3]
            else: op, a, b = k, x[1], x[2]
            p = PREC[op]
            s = self.e(a, p + (1 if op in RIGHT else 0)) + ' ' + op + ' ' + self.e(b, p + (0 if op in RIGHT else 1))
            return '(' + s + ')' if p < parent else s
        if k == 'un':
            a = self.e(x[2], 8)
            s = ('not ' + a) if x[1] == 'not' else ('-' + ('(' + a + ')' if a.startswith('-') else a) if x[1] == '-' else '#' + a)
            return '(' + s + ')' if parent > 8 else s
        if k == 'closure': return self.closure(x)
        if k == 'release': return 'nil'
        if k == 'alloc':
            self.problems.append('alloc residuel')
            self.alloc_ids = getattr(self, 'alloc_ids', {})
            return str(self.alloc_ids.setdefault(x[1], 90000 + len(self.alloc_ids)))
        raise ValueError('expr ' + k)

    def args(self, lst):
        out = []
        for i, a in enumerate(lst):
            last = i == len(lst) - 1
            if a[0] == 'unpack' and a[1][0] == 'tbl' and len(a[1][1]) == 1 and a[1][1][0][0] in ('call', 'unpack') and not last:
                out.append('(' + self.e(a) + ')')
            else: out.append(self.e(a))
        return ', '.join(out)

    def call(self, x):
        f, a = x[1], x[2]
        if f[0] == 'index': f = ('index', f[1], self.sd(f[2]))
        if f[0] == 'index' and f[2][0] == 'const' and isinstance(f[2][1], str) and IDENT.match(f[2][1]) and f[2][1] not in KEYWORDS \
                and a and a[0] == f[1] and f[1][0] in ('tmp', 'rvar', 'ref', 'varget', 'global'):
            return self.e(f[1], 99) + ':' + f[2][1] + '(' + self.args(a[1:]) + ')'
        fs = self.e(f, 99)
        if f[0] in ('const', 'bin', 'un', 'and', 'or', 'tbl', 'closure'): fs = '(' + fs + ')'
        return fs + '(' + self.args(a) + ')'

    # ---------- fonctions ----------
    def closure(self, x):
        arity, entry = x[1], x[2]
        if entry not in self.M.funcs:
            return 'function() --[[ entree %d non atteinte ]] end' % entry
        F = self.M.funcs[entry]
        params = ', '.join('p%d' % i for i in range(1, arity + 1)) if arity >= 0 else '...'
        body = self.func_body(F, 1)
        return 'function(' + params + ')\n' + body + 'end'

    def func_body(self, F, ind=0):
        key = F.entry
        if key not in self.fcache:
            fe = FuncEmit(self.M, F, {}); fe.prepare()
            fe.decmap = self.decmap; fe.decpair = self.decpair
            fe.plans_cache = {b: fe.plan_block(b) for b in F.bids}
            fe.plan_block = lambda b, fe=fe: fe.plans_cache[b]
            try:
                st = Structurer(fe); tree = st.build(); fb = False
            except Unstructurable as ex:
                tree = None; fb = str(ex); st = None
            self.fcache[key] = (fe, st, tree, fb)
        fe, st, tree, fb = self.fcache[key]
        self.cur.append((F, None))
        try:
            owned = [v for v, o in self.owner_map.items() if o == F.entry]
            nloc = 0
            def cnt(t):
                n = 0
                for x in t:
                    if x[0] == 'blk': n += sum(1 for o in x[1] if o[0] in ('local', 'mlocal'))
                    elif x[0] == 'if': n += cnt(x[2]) + cnt(x[3])
                    elif x[0] == 'while': n += cnt(x[2])
                return n
            if tree is not None: nloc = cnt(tree)
            cross = sorted(fe.cross - {self.M.vname})
            if tree is None:
                self.force_hoist.add(F.entry)
                if len(owned) + len(cross) > 150: self.spill.add(F.entry)
                return self.state_machine(fe, st, F, owned, cross)
            if len(owned) + len(cross) + nloc > 150:
                self.spill.add(F.entry)
            body = self.block(self.peephole(tree, F.entry in self.spill), 0)
            hdr = ''
            inits = getattr(self.M, 'reg_init_ast', {})
            plain = [c for c in cross if c not in inits]
            if plain: hdr = 'local ' + ', '.join('r_' + c for c in plain) + '\n'
            for c in cross:
                if c in inits:
                    from .ir import conv
                    hdr += 'local r_%s = %s\n' % (c, self.e(conv(self.M, inits[c], self.M.regset)))
            if F.entry in self.spill: hdr += 'local V%d = {}\n' % F.entry
            return hdr + body
        finally:
            self.cur.pop()

    def owner(self, vid):
        return self.var_owner.get(vid) if hasattr(self, 'var_owner') else None

    def indent(self, text, n):
        pad = '  ' * n
        return ''.join((pad + l if l.strip() else l) for l in text.splitlines(True)) if text and not text.endswith('\n') is None else ''.join((pad + l if l.strip() else l) for l in text.splitlines(True))

    def state_machine(self, fe, st, F, owned, cross):
        lines = ['-- structure non reconstruite (%s) : machine a etats\n' % fe_reason(self, F)]
        names = ['r_' + c for c in cross]
        if F.entry in self.spill:
            lines.append('local V%d = {}\n' % F.entry)
        else:
            names += [self.vname(v) for v in sorted(owned, key=str)]
        if names: lines.append('local ' + ', '.join(names) + '\n')
        lines.append('local state = %d\n' % st_entry(fe))
        lines.append('while true do\n')
        first = True
        for b in fe.F.bids:
            ops, term = fe.plans_cache[b] if hasattr(fe, 'plans_cache') else fe.plan_block(b)
            lines.append(('if' if first else 'elseif') + ' state == %d then\n' % b)
            first = False
            lines.append(self.block([('blk', ops)], 1))
            if term[0] == 'goto': lines.append('state = %d\n' % term[1])
            elif term[0] == 'branch':
                lines.append('if %s then state = %d else state = %s end\n' % (self.e(term[1]), term[2], term[3] if term[3] is not None else '-1'))
            else:
                E = term[1]
                if E[0] == 'tbl': lines.append('do return' + (' ' + self.args(E[1]) if E[1] else '') + ' end\n')
                elif E[0] == 'const' and E[1] is None: lines.append('do return end\n')
                else: lines.append('do return unpack(' + self.e(E) + ') end\n')
        lines.append('else\nreturn\nend\nend\n')
        return ''.join(lines)

    # ---------- arbre ----------
    def mentions(self, node, vid):
        r = [False]
        def g(x):
            if isinstance(x, tuple):
                if len(x) == 2 and x[0] == 'ref' and x[1] == vid: r[0] = True
                for y in x: g(y)
            elif isinstance(x, list):
                for y in x: g(y)
        g(node)
        return r[0]

    def merge_decls(self, tree):
        tree = list(tree)
        i = 0
        while i < len(tree):
            n = tree[i]
            if n[0] == 'op' and n[1][0] == 'decl':
                vid = n[1][1]
                j = i + 1
                while j < len(tree) and not self.mentions(tree[j], vid): j += 1
                if j < len(tree):
                    m = tree[j]
                    if m[0] == 'op' and m[1][0] == 'varset' and m[1][1] == ('ref', vid) and not self.mentions(m[1][2], vid):
                        tree[j] = ('op', ('localvar', vid, m[1][2]))
                        del tree[i]
                        continue
            i += 1
        return tree

    def strip_tail_continue(self, body):
        if body and body[-1] == ('continue',): return body[:-1]
        if body and body[-1][0] == 'if':
            n = body[-1]
            return body[:-1] + [('if', n[1], self.strip_tail_continue(n[2]), self.strip_tail_continue(n[3]))]
        return body

    def peephole(self, tree, spill=False):
        if not spill:
            flat = []
            for n in tree:
                if n[0] == 'blk': flat += [('op', o) for o in n[1]]
                else: flat.append(n)
            tree = self.merge_decls(flat)
        out = []
        for n in tree:
            if n[0] == 'if':
                thn = self.peephole(n[2], spill); els = self.peephole(n[3], spill)
                out.append(('if', n[1], thn, els))
            elif n[0] == 'while':
                body = self.strip_tail_continue(self.peephole(n[2], spill))
                cond = n[1]
                if body and body[0][0] == 'if' and body[0][2] == [('break',)] and not body[0][3]:
                    cond = ('un', 'not', body[0][1]) if not (body[0][1][0] == 'un' and body[0][1][1] == 'not') else body[0][1][2]
                    body = body[1:]
                    out.append(('while', cond, body))
                else:
                    out.append(('while', cond, body))
            else: out.append(n)
        return out

    def semi(self, text, pad, prev):
        """un enonce qui commence par '(' doit etre precede d'un ';' (sinon il se colle a la ligne precedente), sauf en tete de bloc"""
        if prev and text.lstrip().startswith('('): return pad + ';' + text.lstrip()
        return text

    def block(self, tree, ind):
        pad = '  ' * ind
        out = []
        for n in tree:
            k = n[0]
            prev = bool(out)
            if k == 'op': out.append(self.semi(self.op(n[1], pad, ind), pad, prev))
            elif k == 'blk':
                parts = []
                for o in n[1]:
                    parts.append(self.semi(self.op(o, pad, ind), pad, bool(out) or bool(parts)))
                out.append(''.join(parts))
            elif k == 'return':
                E = n[1]
                if E[0] == 'tbl':
                    items = E[1]
                    out.append(pad + 'return' + (' ' + self.args(items) if items else '') + '\n')
                elif E[0] == 'const' and E[1] is None: out.append(pad + 'return\n')
                else: out.append(pad + 'return unpack(' + self.e(E) + ')\n')
            elif k == 'return_none': out.append(pad + 'return\n')
            elif k == 'break': out.append(pad + 'break\n')
            elif k == 'continue': out.append(pad + 'continue\n')
            elif k == 'if':
                C, thn, els = n[1], n[2], n[3]
                if not thn and els: C = ('un', 'not', C) if not (C[0] == 'un' and C[1] == 'not') else C[2]; thn, els = els, []
                if not thn and not els: out.append(pad + '-- (condition sans effet) ' + self.e(C) + '\n'); continue
                out.append(pad + 'if ' + self.e(C) + ' then\n' + self.block(thn, ind + 1))
                while els and len(els) == 1 and els[0][0] == 'if':
                    e2 = els[0]
                    out.append(pad + 'elseif ' + self.e(e2[1]) + ' then\n' + self.block(e2[2], ind + 1))
                    els = e2[3]
                if els: out.append(pad + 'else\n' + self.block(els, ind + 1))
                out.append(pad + 'end\n')
            elif k == 'while':
                out.append(pad + 'while ' + self.e(n[1]) + ' do\n' + self.block(n[2], ind + 1) + pad + 'end\n')
        return ''.join(out)

    def op(self, o, pad, ind):
        base = self.op_inner(o, pad, ind)
        base = base
        if self.inject:
            k = o[0]
            vid = o[1][1] if k == 'varset' and o[1][0] == 'ref' else (o[1] if k == 'localvar' else None)
            if vid in self.inject and ((k == 'varset' and o[2][0] == 'closure') or (k == 'localvar' and o[2][0] == 'closure')): base += self.inject[vid]
        return base

    def op_inner(self, o, pad, ind):
        k = o[0]
        ent = self.cur[-1][0].entry if self.cur else None
        hoisted = ent in self.spill or ent in self.force_hoist
        if k == 'decl':
            return '' if hoisted else pad + 'local ' + self.vname(o[1]) + '\n'
        if k == 'mlocal':
            if ent in self.spill:
                return pad + ', '.join(('V%d.junk' % ent if n == '_' else self.e(('tmp', n))) for n in o[1]) + ' = ' + self.e(o[2]) + '\n'
            return pad + 'local ' + ', '.join(o[1]) + ' = ' + self.e(o[2]) + '\n'
        if k == 'localvar': return pad + ('' if hoisted else 'local ') + self.vname(o[1]) + ' = ' + self.e(o[2]) + '\n'
        if k == 'local':
            if ent in self.spill: return pad + self.e(('tmp', o[1])) + ' = ' + self.e(o[2]) + '\n'
            return pad + 'local ' + o[1] + ' = ' + self.e(o[2]) + '\n'
        if k == 'expr':
            E = o[1]
            if E[0] in ('call',): return pad + self.e(E) + '\n'
            return pad + 'local _ = ' + self.e(E) + '\n'
        if k == 'set': return pad + 'r_' + o[1][1] + ' = ' + self.e(o[2]) + '\n'
        if k == 'varset':
            r = o[1]
            if r[0] != 'ref': self.problems.append('varset non resolu'); return pad + 'VAR[%s] = %s\n' % (self.e(r), self.e(o[2]))
            return pad + self.vname(r[1]) + ' = ' + self.e(o[2]) + '\n'
        if k == 'iset':
            b, kk = o[1], self.sd(o[2])
            bs = self.e(b, 99)
            if b[0] in ('const', 'bin', 'un', 'and', 'or', 'tbl', 'closure'): bs = '(' + bs + ')'
            tgt = (bs + '.' + kk[1]) if kk[0] == 'const' and isinstance(kk[1], str) and IDENT.match(kk[1]) and kk[1] not in KEYWORDS else bs + '[' + self.e(kk) + ']'
            return pad + tgt + ' = ' + self.e(o[3]) + '\n'
        if k == 'gset':
            kk = o[1]
            tgt = kk[1] if kk[0] == 'const' and isinstance(kk[1], str) and IDENT.match(kk[1]) and kk[1] not in KEYWORDS else 'getfenv()[' + self.e(kk) + ']'
            return pad + tgt + ' = ' + self.e(o[2]) + '\n'
        if k == 'upset': self.problems.append('upset'); return pad + 'UPV[%d] = %s\n' % (o[1], self.e(o[2]))
        raise ValueError('op ' + k)

def reindent(text):
    out = []; level = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line: out.append(''); continue
        # retire chaines et commentaires pour compter
        t = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
        t = re.sub(r'--.*$', '', t)
        words = re.findall(r'[A-Za-z_]+', t)
        lead = 0
        first = words[0] if words else ''
        if first in ('end', 'else', 'elseif', 'until'): lead = 1
        opens = sum(1 for w in words if w in ('function', 'do', 'repeat')) + (1 if 'then' in words and first != 'elseif' and 'if' in words else 0)
        if first == 'elseif': opens = 1 if 'then' in words else 0
        if first == 'else': opens = 1
        closes = sum(1 for w in words if w in ('end', 'until'))
        if first in ('else', 'elseif'): closes += 1
        out.append('  ' * max(0, level - lead) + line)
        level += opens - closes
        if first == 'else' or first == 'elseif': level -= 0
        level = max(level, 0)
    return '\n'.join(out) + '\n'

SANDBOX_TRACE = None   # chemin de trace_run.py (defini par le moteur)

def run_decrypt(M, pair, pairs, decvar_id, B, F, runner):
    """execute le debut du script relifte dans le bac a sable pour obtenir les chaines dechiffrees"""
    lst = ', '.join('{%s, %s}' % (lua_str(s), fmt_num(k)) for s, k in pairs)
    return lst

def collect_cands(rd):
    c = collections.defaultdict(set)
    for ent, (fe, st, tree, fb) in rd.fcache.items():
        for k, v in fe.cands.items(): c[k] |= v
    return c

def build(M, runner=None):
    """-> (texte lua, rendu final, infos)"""
    main = M.funcs[M.main_entry]
    r1 = Renderer(M)
    text1 = reindent(r1.func_body(main))
    info = {'problems': sorted(set(r1.problems)), 'decrypted': 0, 'decrypt_total': 0}
    cands = collect_cands(r1)
    best = None
    for key, vals in cands.items():
        if best is None or len(vals) > len(cands[best]): best = key
    if best is not None and len(cands[best]) >= 3 and runner is not None:
        bid, fid = best
        pairs = sorted(cands[best], key=lambda p: (p[1], p[0]))
        r2 = Renderer(M)
        r2.inject = {fid: '__INJECT__'}
        t2 = r2.func_body(main)
        bname = r2.vname(bid); fname = r2.vname(fid)
        lstr = ', '.join('{%s, %s}' % (lua_str(s), fmt_num(k)) for s, k in pairs)
        code = ('do local __o = {} for __i, __p in ipairs({%s}) do local __ok, __v = pcall(function() return %s[%s(__p[1], __p[2])] end) '
                '__o[__i] = (__ok and type(__v) == "string") and (string.gsub(__v, ".", function(c) return string.format("%%02x", string.byte(c)) end)) or "-" end '
                'error("__DEC__" .. table.concat(__o, ",")) end\n') % (lstr, bname, fname)
        res = runner(reindent(t2.replace('__INJECT__', code)))
        m = re.search(r'__DEC__([0-9a-f,\-]*)', res or '')
        decmap = {}
        if m:
            parts = m.group(1).split(',')
            if len(parts) == len(pairs):
                for p, h in zip(pairs, parts):
                    if h != '-': decmap[p] = bytes.fromhex(h).decode('latin-1')
        info['decrypt_total'] = len(pairs); info['decrypted'] = len(decmap)
        if decmap:
            r3 = Renderer(M, decmap=decmap); r3.decpair = best
            text3 = reindent(r3.func_body(main))
            info['problems'] = sorted(set(r3.problems))
            return text3, r3, info
    return text1, r1, info

def lift_to_lua(M):
    main = M.funcs[M.main_entry]
    r = Renderer(M)
    return reindent(r.func_body(main)), r
