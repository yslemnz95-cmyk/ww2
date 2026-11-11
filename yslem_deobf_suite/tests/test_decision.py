#!/usr/bin/env python3
"""decision : detection du contenu + choix automatique du moteur (sans reseau, sans execution)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import decision as D  # noqa: E402

FAILS = []
S = ROOT / "tests" / "samples"


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def dec(name):
    return D.decide((S / name).read_bytes(), name)


# --- obfuscateurs connus : le bon moteur, sur preuve ---
d = dec("wearedevs.lua")
check(d.engine == "wearedevs" and d.supported and d.kind == "source" and d.version == "v1.0.0", f"WeAreDevs : moteur + version ({d.title}, {d.engine})")
check(any("wearedevs" in e for e in d.evidence), "indice technique fourni (regle + extrait)")
d = dec("moonsec_v2.lua")
check(d.engine == "moonsec_trace" and d.kind == "trace" and d.version == "V2", f"MoonSec V2 : trace, version V2 ({d.title})")
d = dec("moonsec_v3.lua")
check(d.engine == "moonsec_v3" and d.kind == "source" and d.version == "V3" and d.fallbacks[:1] == ["moonsec_trace"], f"MoonSec V3 : moteur de devirtualisation, secours trace ({d.title})")
d = dec("psu.lua")
check(d.engine == "psu_trace" and d.kind == "trace", "PSU : moteur de trace")
check("trace" in d.verdict and "partial" in d.verdict, "le verdict dit « résultat partiel : trace » (pas « reussi »)")
d = dec("legaxyobf.lua")
check(d.engine == "legaxyobf" and d.supported, "legaxyobf reconnu")
d = dec("ironbrew1.lua")
check(d.engine == "deobf_py" and d.obfuscator == "IronBrew 1", "IronBrew 1 reconnu")
d = dec("hercules_vm.lua")
check(d.engine == "hercules", "Hercules reconnu")
d = dec("ironveil.lua")
check(d.engine == "ironveil", "Ironveil reconnu")
d = dec("leakd_luaobfuscator.lua")
check(d.engine == "leakd_luaobfuscator" and d.supported, "LuaObfuscator.com reconnu")

# --- honnetete : moteur non fonctionnel ---
d = dec("centurion_v6.lua")
check(d.obfuscator == "Centurion v6" and not d.supported and d.kind == "unavailable", "Centurion : reconnu mais NON presente comme pris en charge")
check("not available" in d.verdict, "Centurion : le verdict dit indisponible")

# --- Luraph : retire, jamais pretendu supporte ---
d = D.decide(b'-- This file was protected using Luraph Obfuscator v14.4 [https://lura.ph/]\nreturn(function(...) end)()', "x.lua")
check(d.obfuscator == "Luraph" and not d.supported and d.kind == "unsupported", "Luraph : reconnu, NON pris en charge")

# --- protections d'acces : reconnues, jamais contournees ---
d = D.decide(b'getgenv().script_key = "abc"\nloadstring(game:HttpGet("https://api.luarmor.net/files/v3/loaders/abc.lua"))()', "l.lua")
check(d.kind == "gated" and d.gate == "Luarmor" and not d.supported and d.requires_key, "Luarmor : protection d'acces reconnue, non supportee")
d = D.decide(b'loadstring(game:HttpGet("https://flowauth.net/v1/loaders/e7ec.lua"))()', "f.lua")
check(d.kind == "gated" and d.gate == "FlowAuth", "FlowAuth : protection d'acces reconnue")
d = D.decide(b'loadstring(game:HttpGet("https://luaprotect.dev/loaders/abc"))()', "p.lua")
check(d.kind == "gated" and d.gate == "LuaProtect" and "does not bypass" in d.verdict, "LuaProtect : reconnu, aucun analyseur invente, non contourne")
d = D.decide(b'local key = getgenv().script_key\nprint("hi")\n', "k.lua")
check(d.requires_key and d.gate is None and any("clé" in n for n in d.notes), "systeme de cle du script : signale")

# --- contenu qui n'est pas un script ---
check(D.decide(b"", "e.lua").language == "empty" and D.decide(b"   \n", "e.lua").kind == "invalid", "reponse vide detectee")
d = D.decide(b"<!DOCTYPE html><html><head><title>404 Not Found</title></head><body>x</body></html>", "u.lua")
check(d.language == "html" and d.kind == "invalid" and "404" in d.notes[0], "page HTML (erreur) detectee")
check(D.decide(b'{"a": [1, 2, 3]}', "j.lua").language == "json", "JSON detecte")
check(D.decide(b"PK\x03\x04" + b"\x00" * 30, "z.zip").kind == "archive", "archive zip reconnue")
check(D.decide(b"\x1bLua\x51\x00" + bytes(range(1, 60)), "b.luac").language == "binary", "bytecode / binaire detecte")
check(D.decide(b"Bonjour tout le monde, ceci n'est pas du code.", "t.txt").language == "text", "texte sans syntaxe Lua")

# --- langage ---
check(dec("plain.lua").language in ("lua", "luau"), "script lisible : langage Lua")
d = dec("plain.lua")
check(d.kind == "plain" and not d.engine and "Nothing to deobfuscate" in d.verdict, "script lisible : « rien a deobfusquer », pas de moteur lance")
check(D.decide(b"local function f(a: number): string\n  local x: number = 1\n  x += 1\n  return tostring(x)\nend\nprint(f(1))\n", "l.lua").language == "luau", "Luau reconnu (types, +=)")
check(D.decide(b"local function f(a)\n return a + 1\nend\nprint(f(1))\n", "l.lua").language == "lua", "Lua reconnu")

# --- obfuscation non reconnue : moteur generique, sans pretendre reconnaitre ---
blob = ('local a="' + "\\123" * 200 + '"\nlocal b=getfenv()\nreturn loadstring(a)\n').encode()
d = D.decide(blob, "x.lua")
check(d.obfuscator is None and d.engine == "trace" and d.kind == "trace" and d.supported, "obfuscation non reconnue : moteur generique `trace`")
check(d.title == "not recognized", "obfuscateur affiche « non reconnu » (aucune invention)")

# --- liens ---
d = D.decide(b'local u="https://raw.githubusercontent.com/a/b/main/x.lua"\nloadstring(game:HttpGet(u))()\nprint("https://exemple.org/a")', "l.lua")
check(len(d.links) == 2 and d.links[0].startswith("https://raw.githubusercontent.com"), "liens externes releves")


# --- Boronide : son en-tete imite MoonSec V2 mais ce n'est pas du MoonSec : aucun moteur MoonSec
d = dec("boronide_v04.lua")
check(d.obfuscator == "Boronide" and d.kind == "unsupported" and d.engine is None, f"Boronide : reconnu, non pris en charge, pas classe MoonSec ({d.title})")
print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : decision")
