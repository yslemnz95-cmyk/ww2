"""capture.py -- capture du proto desassemble par la VM IronBrew2 (sans executer le reste du script) + conteneur Chunk."""
from lupa import lua51 as L


def capture_text(src):
    """src : source deja reecrite pour que `return __cap(DESERIALISEUR())` soit executee."""
    lua = L.LuaRuntime(unpack_returned_tuples=True, register_eval=False, encoding="latin-1")   # octets <-> str 1 pour 1
    # sandbox : l'echantillon est du code non fiable ; on retire tout acces systeme avant de l'executer
    lua.execute("os = nil; io = nil; debug = nil; package = nil; dofile = nil; loadfile = nil; require = nil")
    box = {}
    lua.globals().__cap = lambda d: box.setdefault("d", d)
    lua.execute(src)
    return _proto(box["d"])

def _n(x):
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x

def _proto(p):
    f, o = p[1], p[2]
    n = 0
    while f[n + 1] is not None:
        n += 1
    slots = []
    for i in range(1, n + 1):
        e = f[i]
        slots.append([_n(e[1]), _n(e[2]), _n(e[3]), _n(e[4])])
    protos = []
    k = 0
    while o[k] is not None:
        protos.append(_proto(o[k]))
        k += 1
    return {"slots": slots, "numparams": int(_n(p[3])), "protos": protos}



class Chunk:
    """Un proto en cours de compilation vers Lua 5.1."""
    def __init__(self, proto, idx, kinds):
        self.proto, self.idx, self.kinds = proto, idx, kinds
        self.consts = []
        self.cmap = {}
        self.maxreg = 0
        self.caps_of_children = {}

    def k(self, v):
        key = ("nil", None) if v is None else (type(v).__name__ if not isinstance(v, bool) else "bool", v if not isinstance(v, bool) else bool(v))
        if key not in self.cmap:
            self.cmap[key] = len(self.consts)
            self.consts.append(v)
        return self.cmap[key]

    def rk(self, operand):
        tag, v = operand
        if tag == "R":
            self.maxreg = max(self.maxreg, v)
            return v
        idx = self.k(v)
        if idx > 255:
            raise ValueError("plus de 255 constantes dans un proto (non gere)")
        return 256 + idx

    def reg(self, r):
        self.maxreg = max(self.maxreg, r)
        return r

