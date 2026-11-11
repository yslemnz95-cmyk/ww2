import json, sys, re
from .wad_strings import decode_strings
from .lua_ast import *
from .machine import walk, LiftError

def dynamic_strings(ast, runner):
    """execute le prelude (table de chaines + boucles de decodage) dans le bac a sable et recupere la table decodee"""
    root = ast['body'][0]
    call = root['arguments'][0] if root['type'] == 'ReturnStatement' else root.get('expression')
    fn = call['base']
    prelude = fn['body'][:-1]
    first = prelude[0]
    if first['type'] != 'LocalStatement': raise LiftError('prelude inattendu')
    tname = first['variables'][0]['name']
    code = block(prelude, 0) + (
        'local __t = %s\nlocal __o = {}\nfor __i = 1, #__t do local __v = __t[__i] if type(__v) == "string" then '
        '__o[__i] = (string.gsub(__v, ".", function(c) return string.format("%%02x", string.byte(c)) end)) else __o[__i] = "-" end end\n'
        'error("__DEC__" .. table.concat(__o, ","))\n') % tname
    res = runner(code)
    m = re.search(r'__DEC__([0-9a-f,\-]*)', res or '')
    if not m: raise LiftError('table de chaines non obtenue')
    out = []
    for p in m.group(1).split(','):
        out.append(b'' if p == '' else (b'' if p == '-' else bytes.fromhex(p)))
    return out

def resolve_strings(text, ast, runner=None):
    strs = None
    if runner is not None:
        try: strs = dynamic_strings(ast, runner)
        except Exception: strs = None
    if strs is None: strs = decode_strings(text)
    off = [None, None]
    def find(n):
        if n.get('type') == 'FunctionDeclaration' and n.get('isLocal') and len(n['parameters']) == 1 and len(n['body']) == 1 and n['body'][0]['type'] == 'ReturnStatement':
            a = n['body'][0]['arguments'][0]
            if a['type'] == 'IndexExpression' and a['index']['type'] == 'BinaryExpression' and a['index']['operator'] in ('+', '-'):
                l, r = a['index']['left'], a['index']['right']
                pn = n['parameters'][0]['name']
                if l['type'] == 'Identifier' and l['name'] == pn and r['type'] == 'NumericLiteral':
                    off[0] = n['identifier']['name']; off[1] = r['value'] if a['index']['operator'] == '+' else -r['value']
                elif a['index']['operator'] == '+' and r['type'] == 'Identifier' and r['name'] == pn and l['type'] == 'NumericLiteral':
                    off[0] = n['identifier']['name']; off[1] = l['value']
    walk(ast, find)
    name, o = off
    if name is None: raise LiftError('fonction de recherche de chaines introuvable')
    cnt = [0]
    def rep(e):
        if isinstance(e, list): return [rep(x) for x in e]
        if not isinstance(e, dict): return e
        for k, v in list(e.items()):
            if isinstance(v, (dict, list)): e[k] = rep(v)
        if e.get('type') == 'CallExpression' and e['base'].get('type') == 'Identifier' and e['base']['name'] == name and len(e['arguments']) == 1 and e['arguments'][0]['type'] == 'NumericLiteral':
            i = int(e['arguments'][0]['value'] + o - 1)
            if 0 <= i < len(strs):
                cnt[0] += 1
                return strlit(strs[i].decode('latin-1'))
        return e
    rep(ast)
    return cnt[0]

def prepare(text, ast_json, runner=None):
    fold(ast_json)
    n = resolve_strings(text, ast_json, runner)
    return n
