"""
prefix_manager.py -- prefixes de commandes dynamiques par serveur (discord.ext.commands).

PrefixManager remplace `bot.command_prefix` par un appelable qui renvoie :
  - les prefixes PERSONNALISES du serveur (settings_store), plus la mention du bot, s'il y en a ;
  - sinon les prefixes PAR DEFAUT du bot (ceux qu'il avait avant l'installation : chaine, liste ou fonction), y compris en MP.
Rien n'est perdu : teardown remet exactement l'ancien `command_prefix`.
"""
from __future__ import annotations

import inspect
import types
from typing import Any, Optional

from discord.ext import commands

# Une SEULE instance de ce module, qu'il soit importe sous « prefix_manager » (cogs de la suite) ou sous « yslem_deobf_suite.prefix_manager »
# (bot.py) : sinon deux copies gardent chacune leur etat en memoire et s'ecrasent mutuellement dans le fichier.
import sys as _sys
for _alias in ("prefix_manager", "yslem_deobf_suite.prefix_manager"):
    _sys.modules.setdefault(_alias, _sys.modules[__name__])


async def _call_original(original: Any, bot: commands.Bot, message: Any) -> Any:
    if callable(original):
        r = original(bot, message)
        if inspect.isawaitable(r):
            r = await r
        return r
    return original


def _as_list(p: Any) -> list[str]:
    if p is None:
        return []
    if isinstance(p, str):
        return [p]
    return [str(x) for x in p]


class PrefixManager:
    def __init__(self, store, original: Any) -> None:
        self.store = store
        self.original = original

    async def __call__(self, bot: commands.Bot, message: Any):
        gid = getattr(getattr(message, "guild", None), "id", None)
        custom = self.store.prefixes(gid)
        if custom:
            return _as_list(commands.when_mentioned(bot, message)) + custom
        return await _call_original(self.original, bot, message)

    async def defaults(self, bot: commands.Bot) -> list[str]:
        """Prefixes par defaut du bot, pour l'affichage (sans les mentions). Vide si le bot les calcule d'une facon opaque."""
        fake = types.SimpleNamespace(guild=None, author=None, content="", channel=None)
        try:
            raw = _as_list(await _call_original(self.original, bot, fake))
        except Exception:  # noqa: BLE001 - un prefixe calcule peut dependre du message : pas affichable
            return []
        me = str(getattr(getattr(bot, "user", None), "id", ""))
        return [p for p in raw if not (p.startswith("<@") and me and me in p)]

    async def active(self, bot: commands.Bot, guild_id: Optional[int]) -> tuple[list[str], bool]:
        """(prefixes actifs, personnalises ?)."""
        custom = self.store.prefixes(guild_id)
        if custom:
            return list(custom), True
        return await self.defaults(bot), False


def install(bot: commands.Bot, store) -> PrefixManager:
    """Installe le gestionnaire (idempotent : un second appel ne re-enveloppe pas)."""
    cur = bot.command_prefix
    if isinstance(cur, PrefixManager):
        cur.store = store
        return cur
    mgr = PrefixManager(store, cur)
    bot.command_prefix = mgr
    return mgr


def uninstall(bot: commands.Bot) -> None:
    cur = bot.command_prefix
    if isinstance(cur, PrefixManager):
        bot.command_prefix = cur.original
