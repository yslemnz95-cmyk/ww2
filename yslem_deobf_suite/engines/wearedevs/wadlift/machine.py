"""Reconnaissance du gabarit WeAreDevs (machine a etats) : roles, blocs, entrees."""
import json, sys, collections
from .lua_ast import fold
from .blocks import find_dispatcher, extract

class LiftError(Exception): pass

def walk(n, fn):
    if isinstance(n, list):
        for x in n: walk(x, fn)
    elif isinstance(n, dict):
        fn(n)
        for v in n.values():
            if isinstance(v, (dict, list)): walk(v, fn)

def is_id(e, name=None):
    return isinstance(e, dict) and e.get('type') == 'Identifier' and (name is None or e['name'] == name)

class Machine:
    pass

def analyse(ast):
    M = Machine()
    ds = find_dispatcher(ast)
    if len(ds) != 1: raise LiftError("repartiteur introuvable (%d)" % len(ds))
    disp = ds[0]
    M.disp = disp
    M.vname, M.argname, M.upname, M.proxyname = [p['name'] for p in disp['parameters']]
    # affectation multiple du wrapper
    found = []
    def f(n):
        if n.get('type') == 'AssignmentStatement' and len(n['variables']) >= 8 and any(i is disp for i in n['init']):
            found.append(n)
    walk(ast, f)
    if len(found) != 1: raise LiftError("affectation des roles introuvable")
    asg = found[0]
    names = [v['name'] for v in asg['variables']]
    vals = asg['init']
    if len(names) != len(vals): raise LiftError("nombre de roles incoherent")
    M.creators = {}   # nom -> arite (-1 = vararg)
    M.alloc = None
    tables = []
    M.release = None
    M.release_names = set()
    for nm, val in zip(names, vals):
        if val is disp: M.dispname = nm
        elif val['type'] == 'FunctionDeclaration':
            ps = val['parameters']; b = val['body']
            if len(ps) == 2 and len(b) == 3 and b[0]['type'] == 'LocalStatement' and b[2]['type'] == 'ReturnStatement' \
               and b[1]['type'] == 'LocalStatement' and b[1]['init'] and b[1]['init'][0]['type'] == 'FunctionDeclaration':
                inner = b[1]['init'][0]
                M.creators[nm] = -1 if (inner['parameters'] and inner['parameters'][0]['type'] == 'VarargLiteral') else len(inner['parameters'])
                M.refinc = getattr(M, 'refinc', None) or b[0]['init'][0]['base']['name']
            elif len(ps) == 0 and len(b) == 3 and b[2]['type'] == 'ReturnStatement':
                M.alloc = nm
            elif len(ps) == 1:
                # liberation : i[Y]=i[Y]-1 ... y[Y]=nil
                for s in b:
                    if s['type'] == 'IfStatement':
                        for st in s['clauses'][0]['body']:
                            if st['type'] == 'AssignmentStatement' and len(st['variables']) == 2:
                                M.refs, M.store = st['variables'][0]['base']['name'], st['variables'][1]['base']['name']
                                M.release_names.add(nm)
        elif val['type'] == 'TableConstructorExpression':
            tables.append(nm)
    if not M.alloc or not hasattr(M, 'store'): raise LiftError("roles alloc/store introuvables")
    # parametres du wrapper : env, unpack, ...
    wrap = []
    def g(n):
        if n.get('type') == 'FunctionDeclaration' and any(s is asg for s in n['body']): wrap.append(n)
    walk(ast, g)
    if len(wrap) != 1: raise LiftError("wrapper introuvable")
    wp = [p['name'] for p in wrap[0]['parameters']]
    M.envname, M.unpackname = wp[0], wp[1]
    from .lua_ast import expr as _expr
    callers = []
    def g2(n):
        if n.get('type') == 'CallExpression' and n['base'] is wrap[0]: callers.append(n)
    walk(ast, g2)
    if callers:
        for pname, a in zip(wp, callers[0]['arguments']):
            try: txt = _expr(a)
            except Exception: continue
            if 'getfenv' in txt: M.envname = pname
            elif 'unpack' in txt: M.unpackname = pname
    # point d'entree : return A(entry,{})(Q(d))
    last = wrap[0]['body'][-1]
    if last['type'] != 'ReturnStatement': raise LiftError("return final introuvable")
    c = last['arguments'][0]
    inner = c['base']
    M.main_creator = inner['base']['name']
    M.main_entry = inner['arguments'][0]['value']
    if M.main_creator not in M.creators: raise LiftError("createur principal inconnu")
    # blocs
    leaves = extract(disp)
    M.leaves = leaves   # (lo, hi, body)
    M.leaves.sort(key=lambda t: t[0])
    M.los = [l[0] for l in M.leaves]
    # registres : LocalStatement de tete
    M.regs = [v['name'] for st in disp['body'] if st['type'] == 'LocalStatement' for v in st['variables']]
    M.reg_init_ast = {}
    for st in disp['body']:
        if st['type'] == 'LocalStatement' and st['init']:
            for v, e in zip(st['variables'], st['init']): M.reg_init_ast[v['name']] = e
    # tables-registres : `local BH = {}` indexee uniquement par des constantes numeriques -> pseudo-registres BH_1, BH_2...
    M.scalar_tables = set()
    cand = {n for n, e in getattr(M, 'reg_init_ast', {}).items() if e.get('type') == 'TableConstructorExpression' and not e.get('fields')} 
    if cand:
        total = collections.Counter(); scal = collections.Counter()
        def cnt(n):
            if n.get('type') == 'Identifier' and n['name'] in cand: total[n['name']] += 1
            if n.get('type') == 'IndexExpression' and n['base'].get('type') == 'Identifier' and n['base']['name'] in cand and n['index'].get('type') == 'NumericLiteral':
                scal[n['base']['name']] += 1
        for lo, hi, body in leaves: walk(body, cnt)
        M.scalar_tables = {n for n in cand if total[n] == scal[n]}
    # nom du registre de retour : return Q(d)
    ret = [s for s in disp['body'] if s['type'] == 'ReturnStatement'][0]
    M.retreg = ret['arguments'][0]['arguments'][0]['name']
    return M

def leaf_index(M, state):
    import bisect
    i = bisect.bisect_right(M.los, state) - 1
    lo, hi, _ = M.leaves[i]
    if not (lo <= state < hi): raise LiftError("etat hors intervalle %r" % state)
    return i
