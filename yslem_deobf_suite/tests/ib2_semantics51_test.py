"""Verifie, avec un VRAI interpreteur Lua 5.1 (lupa), que le schema [CMP][JMP faux][JMP vrai] a la bonne polarite
pour EQ / LT / LE / TEST / TESTSET, avec registre ou constante pour chaque operande."""
import sys, itertools
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engines", "ironbrew2"))
from lupa import lua51 as L
import writer as W

def build(code, consts, nregs=6):
    fn = W.function_bytes(code, consts, [], 0, 0, nregs + 2, True)
    return W.chunk_bytes(fn)

def run(code, consts, regs):
    """regs : valeurs initiales des registres 0..n ; renvoie ce que retourne la fonction."""
    lua = L.LuaRuntime(unpack_returned_tuples=True)
    data = build(code, consts)
    lua.globals().__D = data
    f = lua.eval("loadstring(__D)")
    # les registres initiaux sont passes par l'intermediaire de LOADK en tete de code : voir cas()
    return f()

def cond_case(cmp_ins, kvals, expect_true):
    # R0 = k0 ; R1 = k1 ; [CMP] [JMP -> FAUX] [JMP -> VRAI] ; FAUX: return 'F' ; VRAI: return 'T'
    consts = kvals + ["T", "F"]
    kT, kF = len(kvals), len(kvals) + 1
    code = [("LOADK", 0, 0), ("LOADK", 1, 1)] + cmp_ins + [("JMP", 2), ("JMP", 0)]
    # pc: 0,1 loadk ; 2 cmp ; 3 JMP faux ; 4 JMP vrai ; 5 loadk F ; 6 return ; 7 loadk T ; 8 return
    # JMP faux (pc3) -> pc5 : offset 5-4 = 1 ; JMP vrai (pc4) -> pc7 : offset 7-5 = 2
    code = [("LOADK", 0, 0), ("LOADK", 1, 1)] + cmp_ins + [("JMP", 1), ("JMP", 2),
            ("LOADK", 2, kF), ("RETURN", 2, 2), ("LOADK", 2, kT), ("RETURN", 2, 2)]
    return run(code, consts, None)

ok = True
def check(label, got, want):
    global ok
    good = got == want
    ok &= good
    print(("OK   " if good else "FAIL ") + label + ("" if good else f"  (obtenu {got!r}, attendu {want!r})"))

# EQ A B C : saute le JMP faux (=> VRAI) si (RK(B)==RK(C)) ~= A ... nous voulons : cond VRAIE <=> on atteint VRAI
for a, b in ((1, 1), (1, 2), (2, 1)):
    consts = [a, b]
    check(f"EQ  0 R0 R1 avec {a},{b}", cond_case([("EQ", 0, 0, 1)], consts, None), "T" if a == b else "F")
    check(f"EQ  1 (~=) avec {a},{b}", cond_case([("EQ", 1, 0, 1)], consts, None), "T" if a != b else "F")
    check(f"LT  0 R0 R1 avec {a},{b}", cond_case([("LT", 0, 0, 1)], consts, None), "T" if a < b else "F")
    check(f"LE  0 R0 R1 avec {a},{b}", cond_case([("LE", 0, 0, 1)], consts, None), "T" if a <= b else "F")
    check(f"LT  0 R1 R0 (>) avec {a},{b}", cond_case([("LT", 0, 1, 0)], consts, None), "T" if a > b else "F")
    check(f"LE  0 R1 R0 (>=) avec {a},{b}", cond_case([("LE", 0, 1, 0)], consts, None), "T" if a >= b else "F")

# TEST A C : cond VRAIE si truthy -> C=0 ; cond VRAIE si falsy -> C=1
for v in (True, False, 0, "x"):
    truthy = v is not False
    consts = [v, 0]
    check(f"TEST truthy (C=0) avec {v!r}", cond_case([("TEST", 0, 0)], consts, None), "T" if truthy else "F")
    check(f"TEST falsy  (C=1) avec {v!r}", cond_case([("TEST", 0, 1)], consts, None), "F" if truthy else "T")


# TESTSET A B C : R(A):=R(B) puis saut si bool(R(B))==C ; sinon on saute le JMP
for v in (True, False, "x"):
    for C_ in (0, 1):
        truthy = v is not False
        assign = (truthy == bool(C_))
        consts = ["init", v, "S"]
        # pc0 LOADK R0 init ; pc1 LOADK R1 v ; pc2 TESTSET R0 R1 C ; pc3 JMP -> ASSIGN(pc6) ; pc4 JMP -> SKIP(pc7)
        # pc5 : (inaccessible) ; pc6 RETURN R0 ; pc7 LOADK R2 S ; pc8 RETURN R2
        code = [("LOADK", 0, 0), ("LOADK", 1, 1), ("TESTSET", 0, 1, C_), ("JMP", 2), ("JMP", 2),
                ("RETURN", 0, 2), ("RETURN", 0, 2), ("LOADK", 2, 2), ("RETURN", 2, 2)]
        got = run(code, consts, None)
        check(f"TESTSET C={C_} avec {v!r}", got, v if assign else "S")
print("TOUT OK" if ok else "ECHEC")
sys.exit(0 if ok else 1)
