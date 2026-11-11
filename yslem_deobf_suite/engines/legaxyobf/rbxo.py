import math, sys
from legaxy import M32

class R:
    def __init__(s, b, pos=0): s.b, s.pos = b, pos
    def u8(s): v = s.b[s.pos]; s.pos += 1; return v
    def u16(s): lo = s.u8(); return lo + s.u8()*256
    def uleb(s):
        r = 0; sh = 1
        while True:
            x = s.u8(); r += (x % 128) * sh
            if x < 128: return r
            sh *= 128
    def sleb(s):
        r = 0; sh = 1
        while True:
            x = s.u8(); r += (x % 128) * sh; sh *= 128
            if x < 128:
                if x % 128 >= 64: r -= sh
                return r
    def take(s, k): o = s.pos; s.pos += k; return o

def parse(pt):
    r = R(pt)
    assert bytes([r.u8(), r.u8(), r.u8(), r.u8()]) == b'RBXO' and r.u16() == 2
    fo = [r.u8() for _ in range(4)]; disp = r.u8()
    pool = []
    for _ in range(r.uleb()):
        ps = r.uleb(); plen = r.uleb(); pool.append((ps, r.take(plen), plen))
    nprotos = r.uleb()
    A = 2759742607
    for _ in range(11):
        A ^= (A << 13) & M32; A ^= A >> 17; A ^= (A << 5) & M32
    B = 2777233615
    for v in (3, 7, 13, 9, 5, 29, 33): B = (B ^ ((B << 5) & M32)) ^ v
    acc = 807661
    protos = []
    for gi in range(nprotos):
        p = {"start": r.pos, "sc": acc}
        p["np"] = r.uleb(); p["va"] = r.u8() != 0
        p["up"] = [(r.u8(), r.uleb()) for _ in range(r.uleb())]
        ks = []
        for _ in range(r.uleb()):
            tag = r.u8()
            if tag == 0: ks.append((0, None))
            elif tag == 1: ks.append((1, r.u8() != 0))
            elif tag == 2: n = r.uleb(); ks.append((2, (r.take(n), n)))
            elif tag == 3:
                ss = r.uleb(); rs = ss ^ acc; acc = (acc + rs) % 4294967296; n = r.uleb(); ks.append((3, (r.take(n), n, rs)))
            elif tag == 4: st = r.uleb(); n = r.uleb(); ks.append((4, (r.take(n), n, st)))
            elif tag == 5: ks.append((5, r.uleb()))
            else: raise ValueError("tag %d" % tag)
        p["ks"] = ks
        code = []
        for _ in range(r.uleb()):
            v = [r.uleb(), r.sleb(), r.sleb(), r.sleb()]
            A = (A ^ ((A << 5) & M32)) ^ v[0]
            code.append(v)
        p["raw"] = code; protos.append(p)
    assert r.pos == len(pt), (r.pos, len(pt))
    return dict(pt=pt, fo=fo, disp=disp, pool=pool, protos=protos, A=A, B=B)

def stream(pt, off, n, start, A, B):
    st = float(start); out = bytearray()
    m1 = float(2281984822 ^ (A ^ B)); m2 = float(1029071460 ^ (A ^ B))
    for i in range(n):
        st = math.fmod(st * m1 + m2, 4294967296.0)
        out.append(pt[off + i] ^ (int(st // 16777216) % 256))
    return bytes(out)

def tonum(t):
    t = t.decode('latin-1').replace('_', '')
    return int(t[2:], 2) if t[:2].lower() == '0b' else (float(t) if any(c in t for c in '.eE') else int(t))

def constants(c, p):
    pt = c["pt"]; out = []
    for tag, v in p["ks"]:
        if tag == 0: out.append(None)
        elif tag == 1: out.append(v)
        elif tag == 2: out.append(tonum(pt[v[0]:v[0]+v[1]]))
        elif tag == 3: out.append(stream(pt, v[0], v[1], v[2], c["A"], c["B"]).decode('latin-1'))
        elif tag == 4: out.append(tonum(stream(pt, v[0], v[1], v[2], c["A"], c["B"])))
        elif tag == 5: ps, off, ln = c["pool"][v]; out.append(stream(pt, off, ln, ps, c["A"], c["B"]).decode('latin-1'))
    return out

def decode_ins(c, v):
    fo = c["fo"]; return {"op": v[fo[3]], "a": v[fo[2]], "b": v[fo[1]], "c": v[fo[0]]}

if __name__ == "__main__":
    c = parse(open(sys.argv[1], 'rb').read())
    print("fo", c["fo"], "disp", c["disp"], "pool", len(c["pool"]), "protos", len(c["protos"]), "A", c["A"], "B", c["B"])
    for gi, p in enumerate(c["protos"]):
        K = constants(c, p)
        print(f"-- proto {gi}: np={p['np']} va={p['va']} up={len(p['up'])} K={len(K)} code={len(p['raw'])}")
        for i, k in enumerate(K): print(f"   K[{i}] = {k!r}")
        for i, v in enumerate(p["raw"]):
            d = decode_ins(c, v); print(f"   {i:3d}: op={d['op']:2d} a={d['a']} b={d['b']} c={d['c']}")
