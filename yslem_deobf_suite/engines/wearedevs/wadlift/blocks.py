import json,sys,collections
def find_dispatcher(ast):
    """FunctionDeclaration a 4 parametres dont le corps contient `while v do` + arbre de comparaisons sur le premier parametre."""
    res=[]
    def walk(n):
        if isinstance(n,list):
            for x in n: walk(x)
        elif isinstance(n,dict):
            if n.get('type')=='FunctionDeclaration' and len(n['parameters'])==4:
                for s in n['body']:
                    if s['type']=='WhileStatement' and s['condition']['type']=='Identifier' and s['condition']['name']==n['parameters'][0]['name']:
                        res.append(n); break
            for v in n.values():
                if isinstance(v,(dict,list)): walk(v)
    walk(ast); return res
def state_cmp(cond, vname):
    """condition de repartition sur l'etat -> (op, N) avec l'etat a gauche, ou None"""
    if cond.get('type') != 'BinaryExpression' or cond['operator'] not in ('<', '>', '<=', '>='): return None
    l, r = cond['left'], cond['right']
    flip = {'<': '>', '>': '<', '<=': '>=', '>=': '<='}
    if l.get('type') == 'Identifier' and l['name'] == vname and r.get('type') == 'NumericLiteral' and r.get('value') is not None:
        return cond['operator'], r['value']
    if r.get('type') == 'Identifier' and r['name'] == vname and l.get('type') == 'NumericLiteral' and l.get('value') is not None:
        return flip[cond['operator']], l['value']
    return None

def is_state_if(s, vname):
    if s['type'] != 'IfStatement': return False
    for c in s['clauses']:
        if c['type'] == 'ElseClause': continue
        if state_cmp(c['condition'], vname) is None: return False
    return True

def extract(fn):
    vname = fn['parameters'][0]['name']
    wh = [s for s in fn['body'] if s['type'] == 'WhileStatement'][0]
    leaves = []
    def split(op, n, lo, hi):
        if op == '<': return (lo, min(hi, n)), (max(lo, n), hi)
        if op == '<=': return (lo, min(hi, n + 1)), (max(lo, n + 1), hi)
        if op == '>': return (max(lo, n + 1), hi), (lo, min(hi, n + 1))
        return (max(lo, n), hi), (lo, min(hi, n))
    def rec(body, lo, hi):
        if len(body) == 1 and is_state_if(body[0], vname):
            cur = (lo, hi)
            for c in body[0]['clauses']:
                if c['type'] == 'ElseClause':
                    if cur[0] < cur[1]: rec(c['body'], cur[0], cur[1])
                else:
                    op, n = state_cmp(c['condition'], vname)
                    (tl, th), el = split(op, n, cur[0], cur[1])
                    if tl < th: rec(c['body'], tl, th)
                    cur = el
        else:
            leaves.append((lo, hi, body))
    rec(wh['body'], float('-inf'), float('inf'))
    return leaves

if __name__=='__main__':
    from lua_ast import fold
    ast=json.load(open(sys.argv[1])); fold(ast)
    ds=find_dispatcher(ast); print(len(ds),"dispatchers")
    leaves=extract(ds[0]); print(len(leaves),"leaves")
    ty=collections.Counter()
    for lo,hi,b in leaves:
        for s in b: ty[s['type']]+=1
    print(ty)
