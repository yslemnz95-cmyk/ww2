#!/usr/bin/env python3
"""result_tools : nettoyage des bannieres de moteurs, conservation des vrais commentaires, statut honnete (reussi / partiel / echec)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import result_tools as RT  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


# --- nettoyage ---
leak = "-- Deоbfuѕсаtеԁ by LeakD | discord.gg/qteAQmfJmP\n\nlocal function main()\n  print('x')\nend\nmain()\n"
out, meta = RT.clean_output(leak)
check(out.startswith("local function main()") and "LeakD" not in out and "discord.gg" not in out, "banniere LeakD retiree")
check(meta["removed"] == 1, "une seule ligne retiree")

ib = ("-- Why do i love gpt 5.6 sol high the reason is below.\n-- dsc.gg/oxyenv \n"
      "-- Local names are inferred from use (the original names are not in the bytecode)\n\nlocal v = request\nprint(v)\n")
out, meta = RT.clean_output(ib)
check(out.startswith("local v = request") and "oxyenv" not in out and "Local names" not in out, "bannieres IronBrew retirees")

real = "-- Auteur : Jean\n-- Ce script ouvre une porte\nlocal x = 1\n--[[ bloc ]]\nprint(x)\n"
out, meta = RT.clean_output(real)
check(out == real, "les vrais commentaires du code sont CONSERVES (aucune ligne retiree)")
check(meta["removed"] == 0, "rien de retire quand il n'y a pas de banniere")

mixed = "-- discord.gg/abc\n-- Auteur : Jean\nlocal x = 1\n-- discord.gg/dans_le_code\nprint(x)\n"
out, meta = RT.clean_output(mixed)
check(out.startswith("-- Auteur : Jean") and "-- discord.gg/dans_le_code" in out, "seule la tete est nettoyee : le reste du fichier n'est pas touche")

trace = ("-- TRACE (WeAreDevs obfuscator) : ce que le script fait dans le bac a sable, sur UN chemin d'execution.\n"
         "-- Ce n'est PAS le code source d'origine : les branches et boucles non executees manquent.\n"
         "-- Statut d'execution dans le bac a sable : finished\n"
         "-- warning: 2 unknown global(s) were answered by ever-callable proxies (guessed behaviour): a, b\n"
         "setclipboard('x')\n")
out, meta = RT.clean_output(trace)
check(out == "setclipboard('x')\n" and meta["trace"] and meta["sandbox"] == "finished", "en-tete de trace retire, statut conserve dans meta")

wad = ("-- Source RECONSTRUIT (WeAreDevs obfuscator) : Lua equivalent obtenu en relevant la machine a etats,\n"
       "-- PAS le fichier d'origine : les noms de variables sont perdus (v1.., t1.., r_x), la structure est reconstruite.\n"
       "-- Chaines chiffrees : 70 / 70 dechiffrees. Fonctions : 16, blocs : 92 / 101.\n"
       "-- Verification : VERIFIE : le bac a sable observe exactement les memes actions que pour le fichier d'origine.\n"
       "-- Le fichier contient aussi le code parasite de l'obfuscateur (anti-alteration, dechiffrement) : il fait partie du script.\n\n"
       "local v1 = true\n")
out, meta = RT.clean_output(wad)
check(out == "local v1 = true\n" and meta["reconstructed"] and meta["decrypted"] == 70 and meta["verification"].startswith("VERIFIE"),
      "en-tete WeAreDevs retire, verification et chaines lues")

out, _ = RT.clean_output("local a = 1\x00\x01\r\nlocal b = 2   \r\n")
check(out == "local a = 1\nlocal b = 2\n", "caracteres de controle, CRLF et espaces de fin nettoyes")

# --- classement ---
def V(res, text, clean=True):
    out, meta = RT.clean_output(text) if clean else (text, {})
    return RT.classify(res, out, meta)

v = V({"ok": True, "engine": "leakd_luaobfuscator", "log": "ok in=1 out=2"}, leak)
check(v.status == RT.SUCCESS, "LeakD complet -> REUSSI")
v = V({"ok": True, "engine": "leakd_luaobfuscator", "log": "ok partial=1 (opcode map unresolved: 3)"}, leak)
check(v.status == RT.PARTIAL, "LeakD avec opcodes non resolus -> PARTIEL, jamais reussi")
v = V({"ok": True, "engine": "wearedevs", "log": ""}, trace)
check(v.status == RT.PARTIAL and v.kind == "trace", "trace d'execution -> PARTIEL (kind=trace)")
v = V({"ok": True, "engine": "moonsec_trace", "log": ""}, "print(1)\n", clean=False)
check(v.status == RT.PARTIAL, "moteur de trace sans en-tete -> PARTIEL quand meme")
v = V({"ok": True, "engine": "wearedevs", "log": ""}, wad)
check(v.status == RT.SUCCESS and any("vérifié" in d for d in v.details), "WeAreDevs reconstruit et verifie -> REUSSI")
wad_enc = wad + 'print(r_G[r_F("\\003\\151\\023\\205\\008p=\\128", 5269281311125)])\n'
v = V({"ok": True, "engine": "wearedevs", "log": ""}, wad_enc)
check(v.status == RT.PARTIAL and "chiffrée" in v.reason, "WeAreDevs avec chaine encore chiffree -> PARTIEL")
v = V({"ok": True, "engine": "deobf_py", "log": ""}, ib + 'error("devirt: symbolic key store")\n')
check(v.status == RT.PARTIAL and "1 bloc" in v.reason, "blocs devirt non reconstruits -> PARTIEL")
v = V({"ok": True, "engine": "deobf_py", "log": ""}, "-- run status: script error: Script:3: boom\nprint(1)\n")
check(v.status == RT.PARTIAL, "arret dans le bac a sable -> PARTIEL")
v = V({"ok": True, "engine": "loader_chain", "protected": "Luarmor", "log": ""}, "-- chargeur\n")
check(v.status == RT.FAILED and v.kind == "protected" and "clé" in v.reason, "script protege (Luarmor) -> ECHEC, rien n'est contourne")
v = V({"ok": False, "engine": None, "log": "aucun obfuscateur reconnu avec assez de confiance"}, "")
check(v.status == RT.FAILED and "aucun obfuscateur" in v.reason, "echec : raison courte")
v = V({"ok": True, "engine": "hercules", "log": ""}, "local x = 1\nprint(x)\n")
check(v.status == RT.SUCCESS, "moteur de source sans signal d'incompletude -> REUSSI")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : result_tools")
