"""Ecriture du bytecode Lua 5.1 (format luac 5.1, x86_64 little-endian)."""
import struct

OP = dict(MOVE=0, LOADK=1, LOADBOOL=2, LOADNIL=3, GETUPVAL=4, GETGLOBAL=5, GETTABLE=6, SETGLOBAL=7, SETUPVAL=8, SETTABLE=9,
          NEWTABLE=10, SELF=11, ADD=12, SUB=13, MUL=14, DIV=15, MOD=16, POW=17, UNM=18, NOT=19, LEN=20, CONCAT=21, JMP=22,
          EQ=23, LT=24, LE=25, TEST=26, TESTSET=27, CALL=28, RETURN=30, FORLOOP=31, TFORLOOP=33, SETLIST=34, CLOSE=35, CLOSURE=36, VARARG=37)
HEADER = b"\x1bLua\x51\x00\x01\x04\x08\x04\x08\x00"

def _enc(op, a=0, b=0, c=0):
    return (op | (a << 6) | (c << 14) | (b << 23)) & 0xFFFFFFFF

def _encbx(op, a, bx):
    return (op | (a << 6) | (bx << 14)) & 0xFFFFFFFF

def _encsbx(op, a, sbx):
    return _encbx(op, a, sbx + 131071)

def encode(ins):
    """instructions abstraites (voir lift.lower_proto) -> liste de mots 32 bits."""
    out = []
    k = ins[0]
    if k == "EQ":
        out.append(_enc(OP["EQ"], ins[1], ins[2], ins[3]))
    elif k == "TEST":
        out.append(_enc(OP["TEST"], ins[1], 0, ins[2]))
    elif k == "JMP":
        out.append(_encsbx(OP["JMP"], 0, ins[1]))
    elif k == "RETURN":
        out.append(_enc(OP["RETURN"], ins[1], ins[2], 0))
    elif k == "MOVE":
        out.append(_enc(OP["MOVE"], ins[1], ins[2], 0))
    elif k == "LOADK":
        out.append(_encbx(OP["LOADK"], ins[1], ins[2]))
    elif k == "LOADBOOL":
        out.append(_enc(OP["LOADBOOL"], ins[1], ins[2], ins[3]))
    elif k == "GETGLOBAL":
        out.append(_encbx(OP["GETGLOBAL"], ins[1], ins[2]))
    elif k == "GETUPVAL":
        out.append(_enc(OP["GETUPVAL"], ins[1], ins[2], 0))
    elif k == "SETUPVAL":
        out.append(_enc(OP["SETUPVAL"], ins[1], ins[2], 0))
    elif k == "GETTABLE":
        out.append(_enc(OP["GETTABLE"], ins[1], ins[2], ins[3]))
    elif k == "SETTABLE":
        out.append(_enc(OP["SETTABLE"], ins[1], ins[2], ins[3]))
    elif k == "NEWTABLE":
        out.append(_enc(OP["NEWTABLE"], ins[1], 0, 0))
    elif k == "SELF":
        out.append(_enc(OP["SELF"], ins[1], ins[2], ins[3]))
    elif k == "CALL":
        out.append(_enc(OP["CALL"], ins[1], ins[2], ins[3]))
    elif k == "CONCAT":
        out.append(_enc(OP["CONCAT"], ins[1], ins[2], ins[3]))
    elif k == "CLOSURE":
        out.append(_encbx(OP["CLOSURE"], ins[1], ins[2]))
        for cap_kind, b in ins[3]:
            out.append(_enc(OP["MOVE"] if cap_kind == "MOVE" else OP["GETUPVAL"], 0, b, 0))
    elif k in ("CLOSE", "TFORLOOP", "LT", "LE", "TESTSET", "SETLIST", "LOADNIL", "VARARG", "ADD", "SUB", "MUL", "DIV", "MOD", "POW", "UNM", "NOT", "LEN"):
        out.append(_enc(OP[k], ins[1], ins[2] if len(ins) > 2 else 0, ins[3] if len(ins) > 3 else 0))
    elif k == "FORLOOP":
        out.append(_encsbx(OP["FORLOOP"], ins[1], ins[2]))
    elif k == "SETGLOBAL":
        out.append(_encbx(OP["SETGLOBAL"], ins[1], ins[2]))
    else:
        raise ValueError(f"encodage inconnu {k}")
    return out

def _str(s):
    if s is None:
        return struct.pack("<Q", 0)
    b = s.encode("latin-1") if isinstance(s, str) else bytes(s)
    return struct.pack("<Q", len(b) + 1) + b + b"\x00"

def _const(v):
    if v is None:
        return b"\x00"
    if isinstance(v, bool):
        return b"\x01" + (b"\x01" if v else b"\x00")
    if isinstance(v, (int, float)):
        return b"\x03" + struct.pack("<d", float(v))
    if isinstance(v, str):
        return b"\x04" + _str(v)
    raise ValueError(f"constante non gerable : {v!r}")

def function_bytes(code_ins, consts, children, nups, numparams, maxstack, is_main, lines=None, source=None):
    words = []
    for ins in code_ins:
        words.extend(encode(ins))
    out = bytearray()
    out += _str(source)                            # source (nom de debogage « =chemin » ; absente sinon)
    out += struct.pack("<ii", 0, 0)                # lignes
    out += struct.pack("<BBBB", nups, numparams, 2 if is_main else 0, maxstack)
    out += struct.pack("<i", len(words)) + b"".join(struct.pack("<I", w) for w in words)
    out += struct.pack("<i", len(consts)) + b"".join(_const(c) for c in consts)
    out += struct.pack("<i", len(children)) + b"".join(children)
    if lines is not None:                           # table de lignes de debogage : une ligne (= slot IronBrew2) par mot
        per_word = []
        for ins, ln in zip(code_ins, lines):
            per_word += [ln] * (1 + (len(ins[3]) if ins[0] == "CLOSURE" else 0))
        out += struct.pack("<i", len(per_word)) + b"".join(struct.pack("<i", x) for x in per_word)
        out += struct.pack("<ii", 0, 0)
    else:
        out += struct.pack("<iii", 0, 0, 0)        # infos de debogage vides
    return bytes(out)

def chunk_bytes(main_fn_bytes):
    return HEADER + main_fn_bytes
