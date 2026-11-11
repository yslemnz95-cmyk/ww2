#!/usr/bin/env python3
"""settings_store (prefixes + options persistants), stats_store, secure_log, ratelimit : modules purs."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import decision as D  # noqa: E402
import ratelimit  # noqa: E402
import secure_log  # noqa: E402
import settings_store as SS  # noqa: E402
import stats_store as ST  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def raises(fn, *a):
    try:
        fn(*a)
    except ValueError as e:
        return str(e)
    return None


with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "settings.json"
    s = SS.SettingsStore(p)
    check(s.prefixes(1) is None, "aucun prefixe defini -> defaut du bot (None)")
    check(s.add_prefix(1, "!", ["."]) == [".", "!"], "ajout : part des prefixes par defaut du bot + le nouveau")
    check(raises(s.add_prefix, 1, "!") is not None, "doublon refuse")
    check(raises(s.add_prefix, 1, "") is not None and raises(s.add_prefix, 1, "a b") is not None, "prefixe vide / avec espace refuse")
    check(raises(s.add_prefix, 1, "abcdef") is not None, "prefixe trop long refuse")
    check(raises(s.add_prefix, 1, "@") is not None and raises(s.add_prefix, 1, "/") is not None, "caracteres interdits (@, /) refuses")
    check(s.edit_prefix(1, "!", "?") == [".", "?"], "modification d'un prefixe")
    check(raises(s.edit_prefix, 1, "?", ".") is not None, "modification vers un doublon refusee")
    check(raises(s.edit_prefix, 1, "zz", "y") is not None, "modification d'un prefixe inexistant refusee")
    check(s.add_prefix(2, "$") == ["$"] and s.prefixes(1) == [".", "?"], "prefixes independants par serveur")
    # persistance : un autre objet (= redemarrage) relit le fichier
    s2 = SS.SettingsStore(p)
    check(s2.prefixes(1) == [".", "?"] and s2.prefixes(2) == ["$"], "persistance apres redemarrage")
    check(s2.remove_prefix(1, "?") == ["."], "suppression")
    check(raises(s2.remove_prefix, 1, ".") is not None, "le dernier prefixe ne se supprime pas (reinitialiser)")
    s2.reset_prefixes(1)
    check(SS.SettingsStore(p).prefixes(1) is None, "reinitialisation -> retour au defaut, persistante")
    for i in range(SS.MAX_PREFIXES):
        try:
            s2.add_prefix(3, f"p{i}")
        except ValueError:
            break
    check(len(s2.prefixes(3)) == SS.MAX_PREFIXES and raises(s2.add_prefix, 3, "zz") is not None, "plafond de prefixes par serveur")
    # options
    check(s2.option(5, "mention_result") is True, "option : valeur par defaut")
    s2.set_option(5, "mention_result", False)
    check(SS.SettingsStore(p).option(5, "mention_result") is False, "option : persistante")
    s2.reset_options(5)
    check(SS.SettingsStore(p).option(5, "mention_result") is True, "options reinitialisees")
    # fichier corrompu : le bot repart proprement, l'ancien est mis de cote
    p.write_text("{pas du json", encoding="utf-8")
    s3 = SS.SettingsStore(p)
    check(s3.prefixes(1) is None and p.with_name("settings.json.corrupt").exists(), "fichier corrompu : repart par defaut, ancien conserve")
    check(not list(Path(td).glob("*.tmp")), "aucun fichier temporaire oublie (ecriture atomique)")

with tempfile.TemporaryDirectory() as td:
    sp = Path(td) / "stats.json"
    st = ST.StatsStore(sp)
    st.record("deobf", 10, "a.lua", "success", "leakd_luaobfuscator", 4.0)
    st.record("deobf", 11, "b.lua", "partial", "moonsec_trace", 8.0)
    st.record("deobf", 10, "c.lua", "failed", None, 2.0)
    st.record("analyse", 12, "d.lua", "info")
    st.record("get", 10, "e.lua", "info")
    sn = st.snapshot()
    check(sn["deobf"] == 3 and sn["success"] == 1 and sn["partial"] == 1 and sn["failed"] == 1, "compteurs de deobfuscation")
    check(sn["analyses"] == 1 and sn["gets"] == 1 and sn["users"] == 3, "analyses, .get, utilisateurs distincts")
    check(abs(sn["avg_elapsed"] - 14 / 3) < 0.01, "temps moyen d'execution")
    check(sn["history"][0]["name"] == "e.lua" and len(sn["history"]) == 5, "historique : le plus recent d'abord")
    st.flush()
    st2 = ST.StatsStore(sp)
    check(st2.snapshot()["deobf"] == 3 and st2.snapshot()["users"] == 3, "statistiques persistantes")
    for i in range(80):
        st.record("deobf", 1, f"x{i}.lua", "success", "e", 1.0)
    check(len(st.snapshot()["history"]) == ST.HISTORY_MAX, "historique plafonne (pas de fuite memoire)")

# masquage des secrets
tok = "FAKE_BOT_TOKEN_FOR_TESTING.GaBcDe.abcdefghijklmnopqrstuvwxyz0123456"
check("FAKE_BOT_TOKEN" not in secure_log.mask(f"login avec {tok} ok"), "jeton de bot Discord masque")
check("SECRETHOOK" not in secure_log.mask("https://discord.com/api/webhooks/123456/SECRETHOOK_abc-DEF"), "jeton de webhook masque")
check("AIzaSyAbcdefghijklmnopqrstuvwxyz1234567" not in secure_log.mask("key=AIzaSyAbcdefghijklmnopqrstuvwxyz1234567"), "cle d'API Google masquee")
check("sk-ant-abcdefghijklmnopqrstuvwxyz" not in secure_log.mask("sk-ant-abcdefghijklmnopqrstuvwxyz"), "cle Anthropic/OpenAI masquee")
check("hunter2hunter2" not in secure_log.mask("Authorization: Bearer hunter2hunter2"), "en-tete Authorization masque")
import os  # noqa: E402
os.environ["DISCORD_TOKEN"] = "valeur-secrete-12345"
check("valeur-secrete-12345" not in secure_log.mask("erreur avec valeur-secrete-12345 dedans"), "valeur de DISCORD_TOKEN masquee meme sans motif connu")
del os.environ["DISCORD_TOKEN"]
check(secure_log.mask("job 12 termine en 4 s") == "job 12 termine en 4 s", "un message normal n'est pas modifie")

# anti-spam
g = ratelimit.SpamGuard(limit=3, per=10)
res = [g.check(1, now=100 + i)[0] for i in range(5)]
check(res == [True, True, True, False, False], "anti-spam : au-dela de la limite -> refus")
check(g.check(2, now=101)[0], "anti-spam : par utilisateur (un autre n'est pas touche)")
ok, retry = g.check(1, now=105)
check(not ok and 0 < retry <= 10, f"anti-spam : delai d'attente indique ({retry:.1f} s)")
check(g.check(1, now=125)[0], "anti-spam : la fenetre se libere")
check(all(g.check(7, privileged=True, now=300 + i * 0.1)[0] for i in range(20)), "proprietaire / autorises : limite elevee")

# chargeur : pas pris pour un script lisible
d = D.decide(b'loadstring(game:HttpGet("https://raw.githubusercontent.com/a/b/main/x.lua"))()', "l.lua")
check(d.kind == "loader" and d.supported and d.engine == "loader_chain", "chargeur loadstring/HttpGet : suivi par le routeur, pas « rien a deobfusquer »")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : modules de base")
