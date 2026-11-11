"""Verifications de coherence du bytecode produit (equivalent partiel de luaG_checkcode de Lua 5.1)."""
import sys
sys.path.insert(0, "/tmp/ms/ib2/lift")
from luaparser import ast
import lift3, ib2gen as G, lift as LF

def check_proto(code, nups_declared, maxstack, nconsts, label):
    errs = []
    n = len(code)
    pcs, pc = [], 0
    for ins in code:
        pcs.append(pc); pc += 1 + (len(ins[3]) if ins[0] == "CLOSURE" else 0)
    total = pc
    def reg(r, what):
        if not (0 <= r < maxstack): errs.append(f"{label}: registre {r} hors pile ({what})")
    for i, ins in enumerate(code):
        k = ins[0]
        nxt = code[i + 1] if i + 1 < n else None
        if k == "CALL":
            reg(ins[1], "CALL")
            if ins[3] == 0 and not (nxt and ((nxt[0] == "CALL" and nxt[2] == 0) or (nxt[0] == "RETURN" and nxt[2] == 0) or (nxt[0] == "SETLIST" and nxt[2] == 0))):
                errs.append(f"{label}: CALL ouvert (C=0) a l'instr {i} non suivi d'un consommateur ({nxt[:3] if nxt else None})")
        if k == "VARARG" and ins[2] == 0 and not (nxt and ((nxt[0] == "CALL" and nxt[2] == 0) or (nxt[0] == "RETURN" and nxt[2] == 0) or (nxt[0] == "SETLIST" and nxt[2] == 0))):
            errs.append(f"{label}: VARARG ouvert a l'instr {i} non suivi d'un consommateur ({nxt[:3] if nxt else None})")
        if k in ("GETUPVAL", "SETUPVAL") and ins[2] >= nups_declared:
            errs.append(f"{label}: {k} indice {ins[2]} >= nups {nups_declared} (instr {i})")
        if k == "JMP":
            tgt = pcs[i] + 1 + ins[1]
            if not (0 <= tgt < total): errs.append(f"{label}: JMP hors code (instr {i}, cible pc {tgt}/{total})")
        if k in ("EQ", "LT", "LE", "TEST", "TESTSET", "TFORLOOP"):
            if not (nxt and nxt[0] == "JMP"): errs.append(f"{label}: {k} (instr {i}) non suivi d'un JMP ({nxt[:2] if nxt else None})")
        if k in ("GETTABLE","SETTABLE","SELF","EQ","LT","LE","ADD","SUB","MUL","DIV","MOD","POW"):
            for x in ins[2:]:
                if isinstance(x, int) and x >= 256 and x - 256 >= nconsts: errs.append(f"{label}: constante RK {x-256} >= {nconsts}")
    if not code or code[-1][0] != "RETURN":
        errs.append(f"{label}: le code ne finit pas par RETURN (finit par {code[-1][0] if code else None})")
    return errs

def check_file(path):
    src = open(path, encoding="latin-1").read()
    r, kinds, unk = lift3.kinds_for(src)
    proto = LF.capture_text(G.tail_rewrite(src))
    errs = []
    def walk(p, label, nups):
        code, ch = lift3.lower_proto(p, 0, kinds)
        errs.extend(check_proto(code, nups, max(ch.maxreg + 2, p["numparams"] + 2), len(ch.consts), label))
        for i, c in enumerate(p["protos"]):
            walk(c, f"{label}.{i}", ch.caps_of_children.get(i, 0))
    walk(proto, "main", 0)
    return errs

if __name__ == "__main__":
    for f in sys.argv[1:]:
        e = check_file(f)
        print(f.split("/")[-1][:16], "violations:", len(e))
        for x in e[:12]: print("   ", x)
