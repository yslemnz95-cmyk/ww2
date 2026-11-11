"""Conversion AST -> IR (expressions en tuples) et evaluation abstraite."""
import math
from .machine import *

# Expressions IR :
#  ('const', v)            v : str / int / float / bool / None
#  ('reg', name)
#  ('alloc', site)         z() : nouvelle variable locale (site = (entree, bloc, idx))
#  ('upref', k)            h[k]
#  ('ref', varid)          identifiant de variable resolu
#  ('varget', R) ('upget', k)   y[R] / y[h[k]]   (R : expr IR)
#  ('arg', k) ('args',)    U[k] / U
#  ('global', K)           Y[K]
#  ('index', B, K) ('call', F, [args]) ('bin', op, A, B) ('un', op, A)
#  ('tbl', [items])        items : expr IR ; un item ('multi', callexpr) = appel deplie
#  ('closure', arity, entry, [regs]) ('unpack', X) ('release', X)
#  ('and', A, B) ('or', A, B)

def conv(M, e, regs):
    t = e['type']
    if t == 'NumericLiteral': return ('const', e['value'])
    if t == 'StringLiteral': return ('const', e['value'])
    if t == 'BooleanLiteral': return ('const', bool(e['value']))
    if t == 'NilLiteral': return ('const', None)
    if t == 'Identifier':
        n = e['name']
        if n in regs: return ('reg', n)
        return ('role', n)
    if t == 'IndexExpression':
        b, k = e['base'], e['index']
        if b['type'] == 'Identifier':
            bn = b['name']
            if bn in getattr(M, 'scalar_tables', ()) and k['type'] == 'NumericLiteral': return ('reg', '%s_%d' % (bn, int(k['value'])))
            if bn == M.store and bn not in regs:
                if k['type'] == 'IndexExpression' and k['base']['type'] == 'Identifier' and k['base']['name'] == M.upname and k['index']['type'] == 'NumericLiteral':
                    return ('upget', int(k['index']['value']))
                return ('varget', conv(M, k, regs))
            if bn == M.upname and k['type'] == 'NumericLiteral': return ('upref', int(k['value']))
            if bn == M.argname:
                if k['type'] == 'NumericLiteral': return ('arg', int(k['value']))
                return ('index', ('args',), conv(M, k, regs))
            if bn == M.envname and bn not in regs: return ('global', conv(M, k, regs))
        return ('index', conv(M, b, regs), conv(M, k, regs))
    if t == 'CallExpression':
        b = e['base']; args = e['arguments']
        if b['type'] == 'Identifier' and b['name'] not in regs:
            bn = b['name']
            if bn == M.alloc: return ('alloc', None)
            if bn in M.creators and len(args) == 2 and args[0]['type'] == 'NumericLiteral' and args[1]['type'] == 'TableConstructorExpression':
                caps = [conv(M, f['value'], regs) for f in args[1]['fields']]
                return ('closure', M.creators[bn], int(args[0]['value']), caps)
            if bn == M.unpackname and len(args) == 1: return ('unpack', conv(M, args[0], regs))
            if bn == M.refs or bn == M.store: pass
            # liberation : R(x)
            if bn in M.release_names and len(args) == 1: return ('release', conv(M, args[0], regs))
        return ('call', conv(M, b, regs), [conv(M, a, regs) for a in args])
    if t in ('BinaryExpression', 'LogicalExpression'):
        op = e['operator']
        if op in ('and', 'or'): return (op, conv(M, e['left'], regs), conv(M, e['right'], regs))
        return ('bin', op, conv(M, e['left'], regs), conv(M, e['right'], regs))
    if t == 'UnaryExpression': return ('un', e['operator'], conv(M, e['argument'], regs))
    if t == 'TableConstructorExpression':
        items = []
        for f in e['fields']:
            if f['type'] == 'TableValue':
                v = conv(M, f['value'], regs)
                items.append(v)
            elif f['type'] == 'TableKey': items.append(('kv', conv(M, f['key'], regs), conv(M, f['value'], regs)))
            else: items.append(('kv', ('const', f['key']['name']), conv(M, f['value'], regs)))
        return ('tbl', items)
    if t == 'FunctionDeclaration': return ('rawfn', e)
    raise LiftError('expr IR ' + t)

def assign_to(M, tg, e, regs):
    if tg['type'] == 'Identifier':
        if tg['name'] not in regs: raise LiftError('cible non registre ' + tg['name'])
        return [('set', tg['name'], e)]
    ce = conv(M, tg, regs)
    if ce[0] == 'reg': return [('set', ce[1], e)]
    if ce[0] == 'varget': return [('varset', ce[1], e)]
    if ce[0] == 'upget': return [('upset', ce[1], e)]
    if ce[0] == 'index': return [('iset', ce[1], ce[2], e)]
    if ce[0] == 'global': return [('gset', ce[1], e)]
    raise LiftError('cible inconnue ' + ce[0])

def conv_block(M, body, regs):
    """-> liste de ('set', reg, E) ('varset', Rexpr, E) ('upset', k, E) ('iset', B, K, E) ('expr', E)"""
    out = []
    vn = M.vname
    for s in body:
        if s['type'] == 'AssignmentStatement' and len(s['variables']) > 1:
            nv, ni = len(s['variables']), len(s['init'])
            if ni == 1 and all(v['type'] == 'Identifier' and v['name'] in regs for v in s['variables']):
                out.append(('mset', [v['name'] for v in s['variables']], conv(M, s['init'][0], regs)))
            elif nv == ni:
                tmps = []
                for k, e in enumerate(s['init']):
                    nm = '$p%d_%d' % (len(out), k)
                    out.append(('set', nm, conv(M, e, regs))); tmps.append(nm)
                for tg, nm in zip(s['variables'], tmps):
                    out.extend(assign_to(M, tg, ('reg', nm), regs))
            else:
                raise LiftError('affectation multiple non geree')
        elif s['type'] == 'AssignmentStatement':
            out.extend(assign_to(M, s['variables'][0], conv(M, s['init'][0], regs), regs))
        elif s['type'] == 'CallStatement':
            out.append(('expr', conv(M, s['expression'], regs)))
        else: raise LiftError('instruction ' + s['type'])
    return out

# ---------- evaluation abstraite ----------
TOP = None
def lua_truthy(v): return not (v is None or v is False)

def fold_bin(op, a, b):
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
    try:
        if op in ('+', '-', '*', '/', '%', '^'):
            if not (num(a) and num(b)): return TOP
            if op == '+': r = a + b
            elif op == '-': r = a - b
            elif op == '*': r = a * b
            elif op == '/':
                if b == 0: return TOP
                r = a / b
            elif op == '%':
                if b == 0: return TOP
                r = a - math.floor(a / b) * b
            else: r = float(a) ** b
            if isinstance(r, float) and r == int(r) and abs(r) < 2 ** 53: r = int(r)
            return ('c', r)
        if op == '..':
            ok = lambda x: isinstance(x, str) or num(x)
            if not (ok(a) and ok(b)): return TOP
            f = lambda x: x if isinstance(x, str) else (str(int(x)) if float(x) == int(x) else repr(x))
            return ('c', f(a) + f(b))
        if op == '==': return ('c', a == b and type(a) == type(b) or (num(a) and num(b) and a == b))
        if op == '~=': return ('c', not (a == b and type(a) == type(b) or (num(a) and num(b) and a == b)))
        if op in ('<', '<=', '>', '>='):
            if num(a) and num(b) or (isinstance(a, str) and isinstance(b, str)):
                return ('c', {'<': a < b, '<=': a <= b, '>': a > b, '>=': a >= b}[op])
    except Exception:
        return TOP
    return TOP

def ev(e, env, upvals):
    """abstrait : ('c', v) | ('r', varid) | None"""
    k = e[0]
    if k == 'const': return ('c', e[1])
    if k == 'reg': return env.get(e[1], ('c', None))
    if k == 'ref': return ('r', e[1])
    if k == 'alloc': return ('r', e[1])
    if k == 'upref':
        if upvals is not None and e[1] < len(upvals): return upvals[e[1]]
        return TOP
    if k == 'bin':
        a = ev(e[2], env, upvals); b = ev(e[3], env, upvals)
        if a and b and a[0] == 'c' and b[0] == 'c': return fold_bin(e[1], a[1], b[1])
        return TOP
    if k == 'un':
        a = ev(e[2], env, upvals)
        if a and a[0] == 'c':
            if e[1] == 'not': return ('c', not lua_truthy(a[1]))
            if e[1] == '-' and isinstance(a[1], (int, float)) and not isinstance(a[1], bool): return ('c', -a[1])
            if e[1] == '#' and isinstance(a[1], str): return ('c', len(a[1]))
        return TOP
    if k in ('and', 'or'):
        a = ev(e[1], env, upvals)
        if a and a[0] == 'c':
            t = lua_truthy(a[1])
            if k == 'and': return ev(e[2], env, upvals) if t else a
            return a if t else ev(e[2], env, upvals)
        if a and a[0] == 'r' and False: pass
        b = ev(e[2], env, upvals)
        if a and a[0] == 'r':  # une reference est toujours vraie
            return b if k == 'and' else a
        return TOP
    return TOP
