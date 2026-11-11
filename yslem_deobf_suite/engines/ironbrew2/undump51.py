"""Lecteur + verificateur de bytecode Lua 5.1 (reproduit luaG_checkcode/symbexec de ldebug.c)."""
import struct, sys

OPNAMES = ["MOVE","LOADK","LOADBOOL","LOADNIL","GETUPVAL","GETGLOBAL","GETTABLE","SETGLOBAL","SETUPVAL","SETTABLE","NEWTABLE",
           "SELF","ADD","SUB","MUL","DIV","MOD","POW","UNM","NOT","LEN","CONCAT","JMP","EQ","LT","LE","TEST","TESTSET","CALL",
           "TAILCALL","RETURN","FORLOOP","FORPREP","TFORLOOP","SETLIST","CLOSE","CLOSURE","VARARG"]
# mode : (format, Bmode, Cmode)  format: 'ABC' | 'ABx' | 'AsBx' ; modes : 'N' non utilise, 'U' utilise, 'R' registre, 'K' RK
MODES = {
 "MOVE":("ABC","R","N"),"LOADK":("ABx","K","N"),"LOADBOOL":("ABC","U","U"),"LOADNIL":("ABC","R","N"),"GETUPVAL":("ABC","U","N"),
 "GETGLOBAL":("ABx","K","N"),"GETTABLE":("ABC","R","K"),"SETGLOBAL":("ABx","K","N"),"SETUPVAL":("ABC","U","N"),
 "SETTABLE":("ABC","K","K"),"NEWTABLE":("ABC","U","U"),"SELF":("ABC","R","K"),"ADD":("ABC","K","K"),"SUB":("ABC","K","K"),
 "MUL":("ABC","K","K"),"DIV":("ABC","K","K"),"MOD":("ABC","K","K"),"POW":("ABC","K","K"),"UNM":("ABC","R","N"),
 "NOT":("ABC","R","N"),"LEN":("ABC","R","N"),"CONCAT":("ABC","R","R"),"JMP":("AsBx","R","N"),"EQ":("ABC","K","K"),
 "LT":("ABC","K","K"),"LE":("ABC","K","K"),"TEST":("ABC","R","U"),"TESTSET":("ABC","R","U"),"CALL":("ABC","U","U"),
 "TAILCALL":("ABC","U","U"),"RETURN":("ABC","U","N"),"FORLOOP":("AsBx","R","N"),"FORPREP":("AsBx","R","N"),
 "TFORLOOP":("ABC","N","U"),"SETLIST":("ABC","U","U"),"CLOSE":("ABC","N","N"),"CLOSURE":("ABx","U","N"),"VARARG":("ABC","U","N")}
TESTOPS = {"EQ","LT","LE","TEST","TESTSET","TFORLOOP"}

class R:
    def __init__(s, d): s.d, s.p = d, 0
    def u8(s): v = s.d[s.p]; s.p += 1; return v
    def i32(s): v = struct.unpack_from("<i", s.d, s.p)[0]; s.p += 4; return v
    def u32(s): v = struct.unpack_from("<I", s.d, s.p)[0]; s.p += 4; return v
    def u64(s): v = struct.unpack_from("<Q", s.d, s.p)[0]; s.p += 8; return v
    def f64(s): v = struct.unpack_from("<d", s.d, s.p)[0]; s.p += 8; return v
    def string(s):
        n = s.u64()
        if n == 0: return None
        b = s.d[s.p:s.p + n - 1]; s.p += n; return b

def undump(data):
    assert data[:4] == b"\x1bLua" and data[4] == 0x51, "pas du Lua 5.1"
    r = R(data); r.p = 12
    def fn():
        f = {}
        f["source"] = r.string(); f["line"] = r.i32(); f["last"] = r.i32()
        f["nups"], f["numparams"], f["vararg"], f["maxstack"] = r.u8(), r.u8(), r.u8(), r.u8()
        n = r.i32(); f["code"] = [r.u32() for _ in range(n)]
        k = r.i32(); consts = []
        for _ in range(k):
            t = r.u8()
            consts.append(None if t == 0 else (bool(r.u8()) if t == 1 else (r.f64() if t == 3 else r.string())))
            if t not in (0, 1, 3, 4): raise ValueError("type de constante inconnu")
        f["consts"] = consts
        p = r.i32(); f["protos"] = [fn() for _ in range(p)]
        for _ in range(r.i32()): r.i32()          # lineinfo
        for _ in range(r.i32()): r.string(); r.i32(); r.i32()   # locvars
        for _ in range(r.i32()): r.string()       # upvalue names
        return f
    return fn()

def dec(w):
    return (w & 63, (w >> 6) & 255, (w >> 23) & 511, (w >> 14) & 511, (w >> 14) & 0x3FFFF)

def verify(f, label="main"):
    errs = []
    code, k, ms = f["code"], f["consts"], f["maxstack"]
    n = len(code)
    def chk(c, msg):
        if not c: errs.append(f"{label}: {msg}")
    chk(n > 0 and dec(code[-1])[0] == OPNAMES.index("RETURN"), "pas de RETURN final")
    chk(ms <= 250, f"maxstack {ms} > 250")
    def checkreg(r, why):
        chk(0 <= r < ms, f"registre {r} >= maxstack {ms} ({why})")
    def argmode(v, mode, why):
        if mode == "R": checkreg(v, why)
        elif mode == "K":
            if v >= 256: chk(v - 256 < len(k), f"constante RK {v-256} >= {len(k)} ({why})")
            else: checkreg(v, why)
    def openop(pc):
        if pc + 1 >= n: return False
        o, a, b, c, bx = dec(code[pc + 1]); nm = OPNAMES[o]
        return nm in ("CALL", "TAILCALL", "RETURN", "SETLIST") and b == 0
    pc = 0
    while pc < n:
        o, a, b, c, bx = dec(code[pc]); nm = OPNAMES[o] if o < len(OPNAMES) else None
        if nm is None: chk(False, f"opcode {o} invalide"); break
        fmt, bm, cm = MODES[nm]
        chk(a < ms, f"A={a} >= maxstack ({nm} pc {pc})")
        if fmt == "ABC":
            if bm == "N": chk(b == 0, f"{nm}.B inutilise doit valoir 0 (vaut {b}) pc {pc}")
            if cm == "N": chk(c == 0, f"{nm}.C inutilise doit valoir 0 (vaut {c}) pc {pc}")
            argmode(b, bm, f"{nm}.B pc {pc}"); argmode(c, cm, f"{nm}.C pc {pc}")
        elif fmt == "ABx":
            if bm == "K": chk(bx < len(k), f"{nm} Bx {bx} >= {len(k)} pc {pc}")
        else:
            sbx = bx - 131071; dest = pc + 1 + sbx
            chk(0 <= dest < n, f"{nm} saut hors code pc {pc} -> {dest}")
        if nm in TESTOPS:
            chk(pc + 2 < n, f"{nm} pc {pc}: pas assez d'instructions apres")
            chk(pc + 1 < n and OPNAMES[dec(code[pc + 1])[0]] == "JMP", f"{nm} pc {pc} non suivi d'un JMP")
        if nm == "LOADBOOL": chk(c == 0 or pc + 2 < n, f"LOADBOOL saut pc {pc}")
        elif nm in ("GETUPVAL", "SETUPVAL"): chk(b < f["nups"], f"{nm} indice {b} >= nups {f['nups']} pc {pc}")
        elif nm in ("GETGLOBAL", "SETGLOBAL"): chk(bx < len(k) and isinstance(k[bx], (bytes, bytearray)), f"{nm} nom non-chaine pc {pc}")
        elif nm == "SELF": checkreg(a + 1, f"SELF pc {pc}")
        elif nm == "CONCAT": chk(b < c, f"CONCAT b>=c pc {pc}")
        elif nm == "TFORLOOP":
            chk(c >= 1, f"TFORLOOP c<1 pc {pc}"); checkreg(a + 2 + c, f"TFORLOOP pc {pc}")
        elif nm in ("FORLOOP", "FORPREP"): checkreg(a + 3, f"{nm} pc {pc}")
        elif nm in ("CALL", "TAILCALL"):
            if b != 0: checkreg(a + b - 1, f"CALL args pc {pc}")
            cc = c - 1
            if cc == -1: chk(openop(pc), f"CALL ouvert pc {pc} non suivi d'un consommateur")
            elif cc != 0: checkreg(a + cc - 1, f"CALL resultats pc {pc}")
        elif nm == "RETURN":
            bb = b - 1
            if bb > 0: checkreg(a + bb - 1, f"RETURN pc {pc}")
        elif nm == "SETLIST":
            if b > 0: checkreg(a + b, f"SETLIST pc {pc}")
            if c == 0: pc += 1
        elif nm == "CLOSURE":
            chk(bx < len(f["protos"]), f"CLOSURE proto {bx} >= {len(f['protos'])} pc {pc}")
            if bx < len(f["protos"]):
                nup = f["protos"][bx]["nups"]
                chk(pc + nup < n, f"CLOSURE pseudo hors code pc {pc}")
                for j in range(1, nup + 1):
                    if pc + j < n:
                        chk(OPNAMES[dec(code[pc + j])[0]] in ("GETUPVAL", "MOVE"), f"CLOSURE pseudo-instruction {j} invalide pc {pc}")
                pc += nup
        elif nm == "VARARG":
            chk((f["vararg"] & 2) and not (f["vararg"] & 4), f"VARARG dans une fonction non vararg pc {pc}")
            bb = b - 1
            if bb == -1: chk(openop(pc), f"VARARG ouvert pc {pc}")
            else: checkreg(a + bb - 1, f"VARARG pc {pc}")
        pc += 1
    for i, ch in enumerate(f["protos"]):
        errs += verify(ch, f"{label}.{i}")
    return errs

if __name__ == "__main__":
    for p in sys.argv[1:]:
        e = verify(undump(open(p, "rb").read()))
        print(p.split("/")[-1], "violations:", len(e))
        for x in e[:15]: print("   ", x)
