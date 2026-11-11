#!/usr/bin/env python3
"""
Teste que les commandes reservees au proprietaire le sont VRAIMENT (discord.py
reel, sans connexion Discord) :

  1. demonstration du defaut d'origine : le decorateur is_owner() des
     commandes prefixees, pose sur une slash command, laisse `cmd.checks`
     vide -> la commande est ouverte a tout le monde ;
  2. chaque commande owner-only des cogs livres a un check app_commands
     reel, qui REFUSE un utilisateur quelconque (CheckFailure) et ACCEPTE le
     proprietaire.

Usage : python3 tests/test_owner_guard.py    (necessite discord.py >= 2.0)
"""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

COGS = Path(__file__).resolve().parent.parent / "cogs"
OWNER_ID = 111
STRANGER_ID = 222
OWNER_ONLY_COMMANDS = {"deobf_engines", "deobf_dernier", "deobf_etat", "deobf_annuler"}   # noms de commandes slash


class FakeClient:
    async def is_owner(self, user):
        return user.id == OWNER_ID


def fake_interaction(user_id: int):
    return types.SimpleNamespace(client=FakeClient(), user=types.SimpleNamespace(id=user_id),
                                 command=None, namespace=None)


def load_cog_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod      # requis par dataclasses / annotations differees
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    return mod


async def run_checks(cmd, interaction) -> bool:
    """True si toutes les checks passent, False si CheckFailure."""
    try:
        return bool(await cmd._check_can_run(interaction))
    except app_commands.CheckFailure:
        return False


async def main_async() -> int:
    failures = []

    class Demo(commands.Cog):
        @app_commands.command(name="bad", description="x")
        @commands.is_owner()
        async def bad(self, interaction):  # noqa: D401
            pass

    demo_bad = Demo.bad
    print(f"[demo defaut] checks effectifs avec is_owner() prefixe : {demo_bad.checks!r}  "
          f"(vide = commande OUVERTE A TOUS)")
    if demo_bad.checks:
        print("  (inattendu : ce discord.py applique is_owner(); le garde-fou reste valide)")

    checked = 0
    for path in sorted(COGS.glob("*.py")):
        try:
            mod = load_cog_module(path)
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] {path.name}: import impossible ({type(exc).__name__}: {exc})")
            continue
        for obj in vars(mod).values():
            if not (isinstance(obj, type) and issubclass(obj, commands.Cog) and obj is not commands.Cog):
                continue
            for cmd in obj.__cog_app_commands__:
                if cmd.name not in OWNER_ONLY_COMMANDS:
                    continue
                checked += 1
                if not cmd.checks:
                    failures.append(f"{path.name}:/{cmd.name} -> AUCUN check effectif (ouvert a tous)")
                    continue
                stranger_ok = await run_checks(cmd, fake_interaction(STRANGER_ID))
                owner_ok = await run_checks(cmd, fake_interaction(OWNER_ID))
                status = "OK" if (not stranger_ok and owner_ok) else "ECHEC"
                print(f"[{status}] {path.name}:/{cmd.name}  inconnu_autorise={stranger_ok} proprietaire_autorise={owner_ok}")
                if stranger_ok or not owner_ok:
                    failures.append(f"{path.name}:/{cmd.name} -> inconnu_autorise={stranger_ok}, proprietaire_autorise={owner_ok}")

    if checked == 0:
        failures.append("aucune commande owner-only trouvee dans cogs/")
    print()
    if failures:
        print("ECHEC :")
        for f in failures:
            print("  -", f)
        return 1
    print(f"TOUT OK : {checked} commande(s) owner-only verifiee(s).")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
