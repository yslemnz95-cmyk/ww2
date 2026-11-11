"""Outils AST Lua (JSON de luaparse) : pliage de constantes et ecriture."""
import json, math, re

PREC = {'or':1,'and':2,'<':3,'>':3,'<=':3,'>=':3,'~=':3,'==':3,'..':5,'+':6,'-':6,'*':7,'/':7,'%':7,'^':10}
RIGHT = {'..','^'}

def num(v): return {"type":"NumericLiteral","value":v}
def strlit(s): return {"type":"StringLiteral","value":s}
def ident(n): return {"type":"Identifier","name":n}

def fmt_num(v):
    if isinstance(v,float) and v==int(v) and abs(v)<1e15: return str(int(v))
    if isinstance(v,float): return repr(v)
    return str(v)

def lua_str(s):
    # s est une chaine latin-1 (octets)
    out=['"']
    for ch in s:
        o=ord(ch)
        if ch=='"': out.append('\\"')
        elif ch=='\\': out.append('\\\\')
        elif ch=='\n': out.append('\\n')
        elif ch=='\r': out.append('\\r')
        elif ch=='\t': out.append('\\t')
        elif 32<=o<127: out.append(ch)
        else: out.append('\\%03d'%o)
    out.append('"')
    return ''.join(out)

def expr(e, parent=0, side=None):
    t=e['type']
    if t=='NumericLiteral':
        s=fmt_num(e['value'])
        return '('+s+')' if s.startswith('-') and parent>=8 else s
    if t=='StringLiteral': return lua_str(e['value'])
    if t=='BooleanLiteral': return 'true' if e['value'] else 'false'
    if t=='NilLiteral': return 'nil'
    if t=='VarargLiteral': return '...'
    if t=='Identifier': return e['name']
    if t=='IndexExpression':
        b=expr(e['base'],99); 
        if e['base']['type'] in ('StringLiteral','NumericLiteral','FunctionDeclaration','BinaryExpression','LogicalExpression','UnaryExpression'): b='('+b+')'
        return b+'['+expr(e['index'])+']'
    if t=='MemberExpression':
        b=expr(e['base'],99)
        if e['base']['type'] in ('StringLiteral','NumericLiteral','FunctionDeclaration','BinaryExpression','LogicalExpression','UnaryExpression','TableConstructorExpression'): b='('+b+')'
        return b+e['indexer']+e['identifier']['name']
    if t in ('CallExpression','StringCallExpression','TableCallExpression'):
        b=expr(e['base'],99)
        if e['base']['type'] in ('StringLiteral','NumericLiteral','FunctionDeclaration','BinaryExpression','LogicalExpression','UnaryExpression','TableConstructorExpression'): b='('+b+')'
        if t=='CallExpression': return b+'('+', '.join(expr(a) for a in e['arguments'])+')'
        if t=='StringCallExpression': return b+'('+expr(e['argument'])+')'
        return b+'('+expr(e['arguments'])+')'
    if t=='TableConstructorExpression':
        parts=[]
        for f in e['fields']:
            if f['type']=='TableKey': parts.append('['+expr(f['key'])+'] = '+expr(f['value']))
            elif f['type']=='TableKeyString': parts.append(f['key']['name']+' = '+expr(f['value']))
            else: parts.append(expr(f['value']))
        return '{'+', '.join(parts)+'}'
    if t in ('BinaryExpression','LogicalExpression'):
        op=e['operator']; p=PREC[op]
        l=expr(e['left'],p+(1 if op in RIGHT else 0)); r=expr(e['right'],p+(0 if op in RIGHT else 1))
        s=l+' '+op+' '+r
        return '('+s+')' if p<parent else s
    if t=='UnaryExpression':
        op=e['operator']; a=expr(e['argument'],8)
        s=(op+' '+a) if op=='not' else (op+a if not a.startswith('-') else op+' '+a)
        if op=='-' and a.startswith('-'): s='-('+a+')'
        return '('+s+')' if parent>8 else s
    if t=='FunctionDeclaration':
        return 'function('+', '.join(expr(p) for p in e['parameters'])+')\n'+block(e['body'],1)+'end'
    raise ValueError('expr '+t)

def block(body, ind=0):
    pad='  '*ind
    out=[]
    for s in body:
        out.append(stmt(s,ind))
    return ''.join(out)

def stmt(s,ind):
    pad='  '*ind; t=s['type']
    def sub(b): return block(b,ind+1)
    if t=='LocalStatement':
        r=pad+'local '+', '.join(v['name'] for v in s['variables'])
        if s['init']: r+=' = '+', '.join(expr(x) for x in s['init'])
        return r+'\n'
    if t=='AssignmentStatement':
        return pad+', '.join(expr(v) for v in s['variables'])+' = '+', '.join(expr(x) for x in s['init'])+'\n'
    if t=='CallStatement': return pad+expr(s['expression'])+'\n'
    if t=='ReturnStatement': return pad+'return'+(' '+', '.join(expr(a) for a in s['arguments']) if s['arguments'] else '')+'\n'
    if t=='BreakStatement': return pad+'break\n'
    if t=='DoStatement': return pad+'do\n'+sub(s['body'])+pad+'end\n'
    if t=='WhileStatement': return pad+'while '+expr(s['condition'])+' do\n'+sub(s['body'])+pad+'end\n'
    if t=='RepeatStatement': return pad+'repeat\n'+sub(s['body'])+pad+'until '+expr(s['condition'])+'\n'
    if t=='IfStatement':
        r=''
        for i,c in enumerate(s['clauses']):
            if c['type']=='IfClause': r+=pad+'if '+expr(c['condition'])+' then\n'
            elif c['type']=='ElseifClause': r+=pad+'elseif '+expr(c['condition'])+' then\n'
            else: r+=pad+'else\n'
            r+=sub(c['body'])
        return r+pad+'end\n'
    if t=='ForNumericStatement':
        r=pad+'for '+s['variable']['name']+' = '+expr(s['start'])+', '+expr(s['end'])
        if s['step']: r+=', '+expr(s['step'])
        return r+' do\n'+sub(s['body'])+pad+'end\n'
    if t=='ForGenericStatement':
        return pad+'for '+', '.join(v['name'] for v in s['variables'])+' in '+', '.join(expr(x) for x in s['iterators'])+' do\n'+sub(s['body'])+pad+'end\n'
    if t=='FunctionDeclaration':
        nm=expr(s['identifier']) if s['identifier'] else ''
        return pad+('local ' if s['isLocal'] else '')+'function '+nm+'('+', '.join(expr(p) for p in s['parameters'])+')\n'+sub(s['body'])+pad+'end\n'
    raise ValueError('stmt '+t)

def to_lua(chunk): return block(chunk['body'],0)

# ---- pliage de constantes ----
def _isnum(e): return e['type']=='NumericLiteral' and e.get('value') is not None
def fold(e):
    """Plie recursivement les constantes numeriques (modifie en place, renvoie le noeud)."""
    if isinstance(e,list):
        return [fold(x) for x in e]
    if not isinstance(e,dict): return e
    for k,v in list(e.items()):
        if isinstance(v,(dict,list)): e[k]=fold(v)
    t=e.get('type')
    if t=='UnaryExpression' and e['operator']=='-' and _isnum(e['argument']):
        return num(-e['argument']['value'])
    if t=='BinaryExpression' and _isnum(e['left']) and _isnum(e['right']):
        a=e['left']['value']; b=e['right']['value']; op=e['operator']
        try:
            if op=='+': r=a+b
            elif op=='-': r=a-b
            elif op=='*': r=a*b
            elif op=='/': r=a/b
            elif op=='%': r=a-math.floor(a/b)*b
            elif op=='^': r=float(a)**b
            else: return e
            if isinstance(r,float) and r==int(r) and abs(r)<2**53: r=int(r)
            return num(r)
        except Exception: return e
    return e
