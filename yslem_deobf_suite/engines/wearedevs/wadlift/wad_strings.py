"""Decodage statique des chaines constantes d'un fichier WeAreDevs obfuscator v1.x (sans rien executer)."""
import re

_NUM = re.compile(r'^[0-9+\-*()/ %^.]+$')


def _ev(expr):
    e = expr.strip()
    if not _NUM.match(e):
        raise ValueError(expr)
    return int(eval(e.replace('^', '**'), {"__builtins__": {}}, {}))  # noqa: S307 - expression restreinte (chiffres et + - * / % ^ ( ))


def _unesc(raw):
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == '\\':
            m = re.match(r'\\(\d{1,3})', raw[i:])
            if m:
                out.append(int(m.group(1)) & 255)
                i += m.end()
                continue
            m2 = {'n': 10, 'r': 13, 't': 9, '\\': 92, '"': 34, "'": 39}.get(raw[i + 1:i + 2])
            if m2 is not None:
                out.append(m2)
                i += 2
                continue
        out.append(ord(c) & 255)
        i += 1
    return bytes(out)


def _balanced(s, start):
    depth = 0
    for i in range(start, len(s)):
        if s[i] == '{':
            depth += 1
        elif s[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("accolade non fermee")


def decode_strings(text):
    """-> liste de chaines decodees (bytes) ; leve ValueError si le gabarit WeAreDevs v1 n'est pas reconnu."""
    mt = re.search(r'(?:return)?\s*\(function\(\.\.\.\)local \w+=(\{)"', text)
    if not mt:
        raise ValueError("gabarit WeAreDevs non reconnu (table de chaines)")
    a = mt.start(1)
    b = _balanced(text, a)
    table = text[a + 1:b]
    strs = [_unesc(m.group(1)) for m in re.finditer(r'"((?:\\\d{1,3}|\\.|[^"\\])*)"', table)]
    # 1) inversions de plages : for K,f in ipairs({{a;b},{a;b}}) do while f[x]<f[y] do ...
    mr = re.search(r'ipairs\(\{(\{.*?\})\}\)do while', text[b:b + 4000], re.S)
    if mr:
        pairs = re.findall(r'\{([^{}]+)\}', '{' + mr.group(1) + '}')
        for p in pairs:
            lo, hi = [_ev(x) for x in re.split(r'[;,](?![^()]*\))', p)][:2]
            lo -= 1
            hi -= 1
            while lo < hi:
                strs[lo], strs[hi] = strs[hi], strs[lo]
                lo += 1
                hi -= 1
    # 2) alphabet personnalise : local x={Q=expr;["\057"]=expr,...}
    ma = re.search(r'local \w+=(\{(?:(?:\["(?:\\\d{1,3}|[^"\\])+"\]|[A-Za-z])\s*=\s*[-+0-9() *%^.]+[;,]){40,})', text[b:b + 20000])
    if not ma:
        raise ValueError("alphabet personnalise introuvable")
    ax = b + ma.start(1)
    ae = _balanced(text, ax)
    alpha = {}
    body = text[ax + 1:ae]
    for m in re.finditer(r'(?:\["((?:\\\d{1,3}|[^"\\])+)"\]|([A-Za-z_]\w*))\s*=\s*([-+0-9() *%^.]+?)(?=[;,]|$)', body):
        key = _unesc(m.group(1)).decode('latin-1') if m.group(1) is not None else m.group(2)
        alpha[key] = _ev(m.group(3))
    if len(alpha) < 60:
        raise ValueError("alphabet incomplet (%d)" % len(alpha))
    # 3) decodage base64 a alphabet personnalise
    out = []
    for s in strs:
        t = s.decode('latin-1')
        acc, n, res = 0, 0, bytearray()
        i = 0
        while i < len(t):
            ch = t[i]
            if ch in alpha:
                acc += alpha[ch] * 64 ** (3 - n)
                n += 1
                if n == 4:
                    res += bytes([acc >> 16, (acc >> 8) & 255, acc & 255])
                    acc, n = 0, 0
            elif ch == '=':
                res += bytes([acc >> 16])
                if not (i + 1 < len(t) and t[i + 1] == '='):
                    res += bytes([(acc >> 8) & 255])
                break
            i += 1
        out.append(bytes(res))
    return out
