"""
bot_extension.py -- point d'entree UNIQUE pour le bot :

    await bot.load_extension("yslem_deobf_suite.bot_extension")
    await bot.tree.sync()

Charge les trois cogs :
  /analyse /process            (ToolsCog)   analyse et deobfuscation
  /deobf /deobf_engines ...    (DeobfCog)   deobfuscation automatique (le bot choisit le moteur)
  /panel /prefix /stats /get   (PanelCog)   tableau de bord, prefixes par serveur, statistiques, analyse + Oui/Non
et installe les commandes a prefixe equivalentes (`.get`, `.panel`, `.prefix`, `.deobf`...) : memes interfaces que les slash.
Les prefixes par serveur sont persistants (data/settings.json). Rien d'autre a installer : Node.js et le Luau patche sont
prepares automatiquement (bootstrap.py).

Le dossier `yslem_deobf_suite/` doit etre importable depuis le dossier de lancement du bot (a cote du fichier principal).
`reload_extension` / `unload_extension` fonctionnent (teardown ci-dessous : l'ancien `command_prefix` est restaure).
"""
import sys
from pathlib import Path

from discord.ext import commands

from .cogs import deobf_cog, panel_cog, tools_cog

COG_NAMES = ("ToolsCog", "DeobfCog", "PanelCog")


def _root_modules():
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    import prefix_manager
    import settings_store
    import stats_store
    return prefix_manager, settings_store, stats_store


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(tools_cog.ToolsCog(bot), override=True)
    await bot.add_cog(deobf_cog.DeobfCog(bot), override=True)
    await bot.add_cog(panel_cog.PanelCog(bot), override=True)
    deobf_cog.install_prefix_commands(bot)          # `.deobf` et `.analyse` : memes fonctions que /deobf et /analyse
    panel_cog.install_prefix_commands(bot)          # `.get`, `.panel`, `.prefix`, `.stats`, `.process`... memes fonctions que les slash
    pm, ss, _ = _root_modules()
    pm.install(bot, ss.store())                     # prefixes par serveur (persistants) ; l'ancien command_prefix reste le defaut


async def teardown(bot: commands.Bot) -> None:
    pm, _, st = _root_modules()
    pm.uninstall(bot)
    st.stats().flush()
    panel_cog.remove_prefix_commands(bot)
    deobf_cog.remove_prefix_commands(bot)
    for name in COG_NAMES:
        await bot.remove_cog(name)
