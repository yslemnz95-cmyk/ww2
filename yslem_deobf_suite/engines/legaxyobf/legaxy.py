#!/usr/bin/env python3
"""legaxyobf : dechiffre l'enveloppe (ChaCha20-Poly1305, cle dans le fichier), lit le conteneur RBXO, desassemble."""
import re, struct, sys

def lua_unescape(body: str) -> bytes:
    out = bytearray(); i = 0; n = len(body)
    simple = {'n':10,'t':9,'r':13,'a':7,'b':8,'f':12,'v':11,'\\':92,'"':34,"'":39,'\n':10}
    while i < n:
        c = body[i]
        if c != '\\': out += c.encode('latin-1'); i += 1; continue
        i += 1; c = body[i]
        if c.isdigit():
            j = i
            while j < n and j < i+3 and body[j].isdigit(): j += 1
            out.append(int(body[i:j]) & 255); i = j
        elif c == 'x': out.append(int(body[i+1:i+3],16)); i += 3
        elif c in simple: out.append(simple[c]); i += 1
        else: raise ValueError("escape inconnu \\"+c)
    return bytes(out)

M32 = 0xFFFFFFFF
def rotl(x, n): return ((x << n) | (x >> (32-n))) & M32
def qr(s,a,b,c,d):
    s[a]=(s[a]+s[b])&M32; s[d]=rotl(s[d]^s[a],16); s[c]=(s[c]+s[d])&M32; s[b]=rotl(s[b]^s[c],12)
    s[a]=(s[a]+s[b])&M32; s[d]=rotl(s[d]^s[a],8);  s[c]=(s[c]+s[d])&M32; s[b]=rotl(s[b]^s[c],7)
def chacha_block(key, counter, nonce):
    # constantes du fichier : xor des paires = "expand 32-byte k"
    c = [0x80a6e7de^0xe1d69fbb, 0x0047bf85^0x3367dbeb, 0xe8288d79^0x914aa04b, 0x77b8f3cd^0x1c9896b9]
    s = c + list(struct.unpack('<8I', bytes(key))) + [counter] + list(struct.unpack('<3I', bytes(nonce)))
    w = s[:]
    for _ in range(10):
        qr(w,0,4,8,12); qr(w,1,5,9,13); qr(w,2,6,10,14); qr(w,3,7,11,15)
        qr(w,0,5,10,15); qr(w,1,6,11,12); qr(w,2,7,8,13); qr(w,3,4,9,14)
    return struct.pack('<16I', *[(w[i]+s[i])&M32 for i in range(16)])
def poly1305(key32, msg):
    r = int.from_bytes(key32[:16],'little') & 0x0ffffffc0ffffffc0ffffffc0fffffff
    s = int.from_bytes(key32[16:],'little'); p = (1<<130)-5; a = 0
    for i in range(0, len(msg), 16):
        blk = msg[i:i+16]; a = ((a + int.from_bytes(blk+b'\x01','little')) * r) % p
    return ((a + s) & ((1<<128)-1)).to_bytes(16,'little')
def decrypt(env: bytes, key):
    assert env[:4] == b'RBXE' and len(env) >= 49
    ct_len = int.from_bytes(env[29:33],'little')     # octets 30..33 (1-indexe)
    assert 49 + ct_len == len(env), (49+ct_len, len(env))
    aad = env[:17] + env[29:33]; nonce = env[17:29]; ct = env[33:33+ct_len]; tag = env[33+ct_len:]
    otk = chacha_block(key, 0, nonce)[:32]
    pad = lambda b: b + b'\x00' * (-len(b) % 16)
    mac = pad(aad) + pad(ct) + struct.pack('<QQ', len(aad), len(ct))
    ok = poly1305(otk, mac) == tag
    pt = bytearray()
    for i in range(0, ct_len, 64):
        blk = chacha_block(key, 1 + i//64, nonce)
        pt += bytes(x ^ y for x, y in zip(ct[i:i+64], blk))
    return bytes(pt), ok

if __name__ == "__main__":
    src = open(sys.argv[1], encoding='latin-1').read()
    m = re.search(r'local _z\d+_\w+ = "((?:[^"\\]|\\.)*)"\n', src, re.S)
    env = lua_unescape(m.group(1))
    km = re.search(r'local _z\d+_\w+ = \{([\d,]+)\}', src)
    key = bytes(int(x) for x in km.group(1).split(','))
    print("enveloppe", len(env), "octets, cle", len(key), "octets", file=sys.stderr)
    pt, ok = decrypt(env, key)
    print("etiquette Poly1305 valide :", ok, "| clair", len(pt), "octets | debut", pt[:12], file=sys.stderr)
    open(sys.argv[2], 'wb').write(pt)
