#!/usr/bin/env python3
"""
Charge l'extension dans un VRAI commands.Bot de discord.py (sans connexion a Discord) :

    await bot.load_extension("yslem_deobf_suite.bot_extension")

et verifie : les 5 commandes slash sont enregistrees, leur description JSON respecte les limites Discord
(nom <= 32, description <= 100, <= 25 options), les cogs se dechargent proprement, charger deux fois ne plante pas.
Usage : python3 tests/test_extension_load.py
"""
import asyncio
import sys
from pathlib import Path

import discord
from discord.ext import commands

SUITE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE.parent))
EXPECTED = {"analyse", "process", "deobf", "deobf_engines", "deobf_moi", "deobf_dernier", "deobf_etat", "deobf_annuler", "get", "panel", "prefix", "stats", "deobf_roles"}
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


async def main() -> None:
    sys.path.insert(0, str(SUITE))                 # le cog importe `bootstrap` depuis le dossier de la suite
    import bootstrap as bs
    calls = []
    bs.ensure_ready = lambda log=None, **kw: calls.append(1) or {}        # pas de telechargement dans ce test

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    await bot.load_extension("yslem_deobf_suite.bot_extension")
    await asyncio.sleep(0.2)                                              # laisse tourner le pre-chauffage
    names = {c.name for c in bot.tree.get_commands()}
    check(names == EXPECTED, f"commandes enregistrees : {sorted(names)}")
    check(bool(calls), "pre-chauffage (bootstrap) lance au chargement du cog")
    for c in bot.tree.get_commands():
        try:
            d = c.to_dict(bot.tree)            # discord.py >= 2.5
        except TypeError:
            d = c.to_dict()                    # discord.py 2.3 / 2.4
        ok = (len(d["name"]) <= 32 and 1 <= len(d["description"]) <= 100 and len(d.get("options", [])) <= 25
              and all(1 <= len(o["description"]) <= 100 for o in d.get("options", [])))
        check(ok, f"/{c.name} : nom/description/options conformes aux limites Discord")
    owner_only = {"deobf_engines", "deobf_dernier", "deobf_etat", "deobf_annuler", "stats", "deobf_roles"}
    check(all(bool(c.checks) for c in bot.tree.get_commands() if c.name in owner_only), "commandes owner-only : check effectif present")
    check(not any(c.checks for c in bot.tree.get_commands() if c.name == "deobf_moi"), "/deobf_moi : ouverte a tous")
    # parite slash / prefixe : CHAQUE commande slash a sa commande a prefixe (nom ou alias), meme fonction
    pref = {c.name for c in bot.commands}
    prefn = pref | {a for c in bot.commands for a in c.aliases}
    check(all(n in prefn for n in names), f"parite : chaque commande slash a son equivalent a prefixe (manque : {sorted(n for n in names if n not in prefn)})")
    check({"get", "panel", "prefix", "stats", "deobf", "analyse"} <= pref, "commandes a prefixe installees (.get .panel .prefix .stats .deobf .analyse)")
    from prefix_manager import PrefixManager
    check(isinstance(bot.command_prefix, PrefixManager), "prefixes par serveur : gestionnaire installe")
    await bot.unload_extension("yslem_deobf_suite.bot_extension")
    check(bot.command_prefix == "!", "dechargement : l'ancien command_prefix est restaure")
    left = [c.name for c in bot.commands if c.name != "help"]
    check(not bot.tree.get_commands() and not left, f"dechargement : plus aucune commande (slash ni prefixe) {left}")
    await bot.load_extension("yslem_deobf_suite.bot_extension")
    check({c.name for c in bot.tree.get_commands()} == EXPECTED, "rechargement apres dechargement")
    await bot.close()


asyncio.run(main())
print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : l'extension se charge dans un vrai commands.Bot")
