"""
panel_cog.py -- interface Discord du bot : tableau de bord /panel, prefixes, statistiques et commande /get.

  /panel   (.help, .menu)      menu principal : Prefixes · Deobfuscation · Moteurs · Statistiques · Parametres
  /prefix  (.prefix)            panneau des prefixes (ajouter, modifier, supprimer, reinitialiser) -- par serveur, persistant
  /stats   (.stats)             statistiques (proprietaire / ID autorises)
  /get     (.get)               recupere un script (lien ou fichier), l'analyse, reconnait l'obfuscateur, et propose Oui / Non

Les commandes slash et a prefixe appellent EXACTEMENT les memes fonctions : memes interfaces, memes boutons, memes resultats.
Composants natifs Discord : boutons, menus deroulants, fenetres modales. Rien n'est execute ici : la deobfuscation passe par
tools_cog.run_items (meme code que /deobf et /process), qui choisit seul le moteur (decision.py).
"""
from __future__ import annotations

import asyncio
import re
import sys
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

try:
    from . import ui_kit
    from .tools_cog import (NOT_AUTHORIZED_MSG, _fetch_url, _log, _MAX_BYTES, _record_stat, _suite_mod, cancel_current, is_authorized,
                            JOB_TIMEOUT_DEFAULT, owner_only, run_items, send_last_results)
    from .deobf_cog import PrefixInteraction
except ImportError:                                   # charge a plat (fichiers cote a cote)
    import ui_kit  # type: ignore
    from tools_cog import (NOT_AUTHORIZED_MSG, _fetch_url, _log, _MAX_BYTES, _record_stat, _suite_mod, cancel_current,  # type: ignore
                           is_authorized, JOB_TIMEOUT_DEFAULT, owner_only, run_items, send_last_results)
    from deobf_cog import PrefixInteraction  # type: ignore

PANEL_TIMEOUT = 300
GET_TIMEOUT = 120
_GUARD = None


def _guard():
    global _GUARD
    if _GUARD is None:
        _GUARD = _suite_mod("ratelimit").SpamGuard()
    return _GUARD


def _gid(interaction) -> Optional[int]:
    g = getattr(interaction, "guild", None)
    return getattr(g, "id", None)


async def can_manage(interaction) -> bool:
    """Gerer les reglages d'un serveur : « Gerer le serveur » ou proprietaire / ID autorises."""
    perms = getattr(interaction.user, "guild_permissions", None)
    if perms is not None and (perms.manage_guild or perms.administrator):
        return True
    return await is_authorized(interaction)


async def _allowed(interaction) -> bool:
    """Anti-spam par utilisateur. Repond (ephemere, court) et renvoie False si la limite est depassee."""
    ok, retry = _guard().check(interaction.user.id, privileged=await is_authorized(interaction))
    if ok:
        return True
    await _say(interaction, f"⏳ Too many commands. Try again in {retry:.0f} s.", ephemeral=True)
    return False


async def _say(interaction, text: str, ephemeral: bool = True) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text[:1900], ephemeral=ephemeral)
        else:
            await interaction.response.send_message(text[:1900], ephemeral=ephemeral)
    except (discord.HTTPException, discord.NotFound):
        pass


async def _send(interaction, *, embed: discord.Embed, view: Optional[discord.ui.View] = None, ephemeral: bool = False):
    """Envoie embed (+ vue) et renvoie le message (necessaire pour retirer les boutons a l'expiration)."""
    kw: dict = {"embed": embed}
    if view is not None:
        kw["view"] = view
    if interaction.response.is_done():
        return await interaction.followup.send(ephemeral=ephemeral, wait=True, **kw)
    await interaction.response.send_message(ephemeral=ephemeral, **kw)
    try:
        return await interaction.original_response()
    except (discord.HTTPException, AttributeError):
        return None


class _View(discord.ui.View):
    """Vue de base : seul celui qui l'a ouverte peut s'en servir ; boutons retires a l'expiration."""

    def __init__(self, invoker_id: int, timeout: float = PANEL_TIMEOUT) -> None:
        super().__init__(timeout=timeout)
        self.invoker_id = invoker_id
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await _say(interaction, "This panel belongs to someone else: open your own with `/panel`.", ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except (discord.HTTPException, AttributeError):
                pass


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
#  Prefixes
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

class PrefixModal(discord.ui.Modal):
    def __init__(self, title: str, apply, default: str = "") -> None:
        super().__init__(title=title[:45], timeout=PANEL_TIMEOUT)
        self._apply = apply
        self.value = discord.ui.TextInput(label="Prefix (1 to 5 characters)", min_length=1, max_length=5, required=True,
                                          default=default or None)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._apply(interaction, str(self.value.value).strip())


async def prefix_embed(bot, interaction) -> discord.Embed:
    mod = _suite_mod("prefix_manager")
    mgr = bot.command_prefix if isinstance(bot.command_prefix, mod.PrefixManager) else None
    gid = _gid(interaction)
    e = ui_kit.embed("info", "Prefixes")
    if gid is None:
        e.description = "In private messages the bot's default prefixes apply (per-server setting only)."
        return e
    if mgr is None:
        e.description = "Prefix management is not installed."
        return e
    active, custom = await mgr.active(bot, gid)
    shown = " ".join(f"`{p}`" for p in active) if active else "*set by the bot (not displayable)*"
    e.add_field(name="Active on this server", value=shown, inline=False)
    e.add_field(name="Origin", value="custom" if custom else "bot default", inline=True)
    ex = active[0] if active else "."
    e.add_field(name="Example", value=f"`{ex}get <link>`", inline=True)
    return e


class PrefixView(_View):
    def __init__(self, bot, invoker_id: int, gid: Optional[int], editable: bool) -> None:
        super().__init__(invoker_id)
        self.bot, self.gid, self.editable = bot, gid, editable
        if not editable:
            for it in self.children:
                if getattr(it, "custom_id", None) != "back":
                    it.disabled = True

    def _mgr(self):
        return self.bot.command_prefix if isinstance(self.bot.command_prefix, _suite_mod("prefix_manager").PrefixManager) else None

    async def _refresh(self, interaction, note: str = "") -> None:
        """Met a jour le PANNEAU (et non le petit menu de choix ephemere dont l'interaction peut venir)."""
        e = await prefix_embed(self.bot, interaction)
        if note:
            e.set_footer(text=note[:200])
        view = PrefixView(self.bot, self.invoker_id, self.gid, self.editable)
        view.message = self.message
        self.stop()
        if self.message is not None:
            if not interaction.response.is_done():
                await interaction.response.defer()
            await self.message.edit(embed=e, view=view)
        else:
            await interaction.response.edit_message(embed=e, view=view)

    async def _guarded(self, interaction) -> bool:
        if await can_manage(interaction):
            return True
        await _say(interaction, "You need the \"Manage Server\" permission to change prefixes.", ephemeral=True)
        return False

    async def _do(self, interaction, fn, note: str) -> None:
        store = _suite_mod("settings_store").store()
        try:
            fn(store)
        except ValueError as exc:
            await _say(interaction, f"❌ {exc}", ephemeral=True)
            return
        await self._refresh(interaction, note)

    async def _defaults(self) -> list[str]:
        mgr = self._mgr()
        return await mgr.defaults(self.bot) if mgr else []

    @discord.ui.button(label="Add", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guarded(interaction):
            return
        defaults = await self._defaults()

        async def apply(inter, value):
            note = f"prefix `{value}` added" + ("" if defaults else " (the bot's original prefixes are replaced)")
            await self._do(inter, lambda st: st.add_prefix(self.gid, value, defaults), note)
        await interaction.response.send_modal(PrefixModal("Add a prefix", apply))

    @discord.ui.button(label="Edit", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guarded(interaction):
            return
        await self._pick(interaction, "edit")

    @discord.ui.button(label="Remove", emoji="🗑️", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guarded(interaction):
            return
        await self._pick(interaction, "remove")

    @discord.ui.button(label="Reset", emoji="♻️", style=discord.ButtonStyle.secondary, row=0)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guarded(interaction):
            return
        await self._do(interaction, lambda st: st.reset_prefixes(self.gid), "default prefixes restored")

    @discord.ui.button(label="Menu", emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="back", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await show_main(interaction, self.bot, self.invoker_id, edit=True)

    async def _pick(self, interaction, mode: str) -> None:
        """Drop-down of custom (or default) prefixes to pick which one to edit or remove."""
        store = _suite_mod("settings_store").store()
        cur = store.prefixes(self.gid) or await self._defaults()
        if not cur:
            await _say(interaction, "No prefix to change: add one first.", ephemeral=True)
            return
        sel = discord.ui.Select(placeholder="Which prefix?" if mode == "edit" else "Which prefix to remove?",
                                options=[discord.SelectOption(label=p, value=p) for p in cur[:25]])

        async def chosen(inter: discord.Interaction) -> None:
            old = inter.data["values"][0]
            if mode == "remove":
                def op(st):
                    if st.prefixes(self.gid) is None:
                        st.set_prefixes(self.gid, cur)          # on part des prefixes par defaut du bot
                    st.remove_prefix(self.gid, old)
                try:
                    await inter.response.edit_message(content="✔️ Pris en compte.", view=None)
                except discord.HTTPException:
                    pass
                await self._do(inter, op, f"prefix `{old}` removed")
                return

            async def apply(i2, value):
                def op(st):
                    if st.prefixes(self.gid) is None:
                        st.set_prefixes(self.gid, cur)
                    st.edit_prefix(self.gid, old, value)
                await self._do(i2, op, f"`{old}` → `{value}`")
            await inter.response.send_modal(PrefixModal("Edit the prefix", apply, default=old))

        sel.callback = chosen
        v = _View(self.invoker_id)
        v.add_item(sel)
        await interaction.response.send_message("Choose:", view=v, ephemeral=True)


async def show_prefixes(interaction, bot, *, edit: bool = False) -> None:
    e = await prefix_embed(bot, interaction)
    editable = _gid(interaction) is not None and await can_manage(interaction)
    if _gid(interaction) is not None and not editable:
        e.set_footer(text="read only: \"Manage Server\" permission required to change")
    view = PrefixView(bot, interaction.user.id, _gid(interaction), editable)
    if edit:
        await interaction.response.edit_message(embed=e, view=view)
        view.message = getattr(interaction, "message", None)
    else:
        view.message = await _send(interaction, embed=e, view=view, ephemeral=_private(interaction))


def _private(interaction) -> bool:
    """Les panneaux sont prives par defaut (option par serveur) ; en commande a prefixe, un message ne peut pas etre ephemere."""
    if isinstance(interaction, PrefixInteraction):
        return False
    try:
        return bool(_suite_mod("settings_store").store().option(_gid(interaction), "private_panels"))
    except Exception:  # noqa: BLE001
        return True


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
#  Moteurs, statistiques, parametres, deobfuscation
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

def _engines_info() -> list[dict]:
    R, D = _suite_mod("deobf_router"), _suite_mod("decision")
    out = []
    for e in R.load_engines():
        ok, why = D.engine_usable(e)
        meta = D.engine_meta(e)
        out.append({"name": e.name, "display": meta["display"], "kind": meta["kind"], "ok": ok, "why": why, "label": e.label,
                    "notes": (e.notes or "")[:300], "timeout": e.timeout})
    return out


def _engine_icon(i: dict) -> str:
    return "⛔" if not i["ok"] else ("🧭" if i["kind"] == "trace" else "✅")


async def engines_embed() -> discord.Embed:
    infos = await asyncio.to_thread(_engines_info)
    e = ui_kit.embed("info", "Obfuscator supported")
    lines = [f"{_engine_icon(i)} **{i['display']}** · `{i['name']}`" for i in infos if i["ok"]]
    e.description = "\n".join(lines)[:3900] or "No supported obfuscator is available right now."
    e.set_footer(text="✅ source code · 🧭 execution trace · the bot picks the right tool automatically")
    return e


async def stats_embed() -> discord.Embed:
    sn = _suite_mod("stats_store").stats().snapshot()
    e = ui_kit.embed("info", "Statistics")
    done = sn["success"] + sn["partial"] + sn["failed"]
    e.add_field(name="Deobfuscations", value=f"{sn['deobf']}", inline=True)
    e.add_field(name="✅ Successful", value=str(sn["success"]), inline=True)
    e.add_field(name="⚠️ Other", value=str(sn["partial"]), inline=True)
    e.add_field(name="❌ Failed", value=str(sn["failed"]), inline=True)
    e.add_field(name="Analyses / .get", value=f"{sn['analyses']} / {sn['gets']}", inline=True)
    e.add_field(name="Users", value=str(sn["users"]), inline=True)
    e.add_field(name="Average time", value=ui_kit.fmt_duration(sn["avg_elapsed"]) if done else "—", inline=True)
    hist = sn["history"][:8]
    if hist:
        icon = {"success": "✅", "partial": "⚠️", "failed": "❌", "cancelled": "⛔", "info": "🔎"}
        e.add_field(name="Latest operations", value="\n".join(
            f"{icon.get(h['status'], '•')} `{h['name'][:28]}` · {h['kind']}" + (f" · {h['engine']}" if h['engine'] else "")
            + (f" · {ui_kit.fmt_duration(h['elapsed'])}" if h['elapsed'] else "") + f" · <t:{h['t']}:R>" for h in hist)[:1000], inline=False)
    return e


def settings_embed(gid: Optional[int]) -> discord.Embed:
    st = _suite_mod("settings_store").store()
    e = ui_kit.embed("info", "Settings")
    if gid is None:
        e.description = "Per-server settings: not available in private messages."
        return e
    on = lambda k: "✅ on" if st.option(gid, k) else "❌ off"       # noqa: E731
    e.add_field(name="Private panels", value=on("private_panels"), inline=True)
    e.add_field(name="Mention on result", value=on("mention_result"), inline=True)
    return e


class SettingsView(_View):
    def __init__(self, bot, invoker_id: int, gid: Optional[int], editable: bool) -> None:
        super().__init__(invoker_id)
        self.bot, self.gid = bot, gid
        if not editable:
            for it in self.children:
                if getattr(it, "custom_id", None) != "back":
                    it.disabled = True

    async def _toggle(self, interaction, key: str) -> None:
        if not await can_manage(interaction):
            await _say(interaction, "You need the \"Manage Server\" permission.", ephemeral=True)
            return
        st = _suite_mod("settings_store").store()
        st.set_option(self.gid, key, not st.option(self.gid, key))
        view = SettingsView(self.bot, self.invoker_id, self.gid, True)
        view.message = self.message
        self.stop()
        await interaction.response.edit_message(embed=settings_embed(self.gid), view=view)

    @discord.ui.button(label="Private panels", emoji="🔒", style=discord.ButtonStyle.primary, row=0)
    async def private_panels(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._toggle(interaction, "private_panels")

    @discord.ui.button(label="Mention on result", emoji="🔔", style=discord.ButtonStyle.primary, row=0)
    async def mention_result(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._toggle(interaction, "mention_result")

    @discord.ui.button(label="Reset", emoji="♻️", style=discord.ButtonStyle.secondary, row=0)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await can_manage(interaction):
            await _say(interaction, "You need the \"Manage Server\" permission.", ephemeral=True)
            return
        _suite_mod("settings_store").store().reset_options(self.gid)
        view = SettingsView(self.bot, self.invoker_id, self.gid, True)
        view.message = self.message
        self.stop()
        await interaction.response.edit_message(embed=settings_embed(self.gid), view=view)

    @discord.ui.button(label="Menu", emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="back", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await show_main(interaction, self.bot, self.invoker_id, edit=True)


class LinkModal(discord.ui.Modal):
    def __init__(self, cog) -> None:
        super().__init__(title="Analyze a link", timeout=PANEL_TIMEOUT)
        self.cog = cog
        self.url = discord.ui.TextInput(label="Script link", placeholder="https://raw.githubusercontent.com/…", min_length=8, max_length=500)
        self.add_item(self.url)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.get_flow(interaction, url=str(self.url.value).strip())


class DeobfView(_View):
    def __init__(self, bot, cog, invoker_id: int) -> None:
        super().__init__(invoker_id)
        self.bot, self.cog = bot, cog

    async def _admin(self, interaction) -> bool:
        if await is_authorized(interaction):
            return True
        await _say(interaction, NOT_AUTHORIZED_MSG, ephemeral=True)
        return False

    @discord.ui.button(label="Analyze a link", emoji="🔗", style=discord.ButtonStyle.primary, row=0)
    async def link(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(LinkModal(self.cog))

    @discord.ui.button(label="Send a file", emoji="📂", style=discord.ButtonStyle.secondary, row=0)
    async def file(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _say(interaction, "Discord can't send a file from a panel: use `/get` or `/deobf` with the "
                                "`file` field, or `.get` / `.deobf` with the file attached.", ephemeral=True)

    @discord.ui.button(label="Latest results", emoji="🕘", style=discord.ButtonStyle.secondary, row=0)
    async def last(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if await self._admin(interaction):
            await send_last_results(interaction, 1)

    @discord.ui.button(label="Cancel jobs", emoji="⛔", style=discord.ButtonStyle.danger, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if await self._admin(interaction):
            await cancel_current(interaction, None)

    @discord.ui.button(label="Menu", emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="back", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await show_main(interaction, self.bot, self.invoker_id, edit=True)


class EnginesView(_View):
    def __init__(self, bot, invoker_id: int, infos: list[dict]) -> None:
        super().__init__(invoker_id)
        self.bot, self.infos = bot, {i["name"]: i for i in infos}
        sel = discord.ui.Select(placeholder="Obfuscator details…", row=0,
                                options=[discord.SelectOption(label=i["display"][:100], value=i["name"], emoji=_engine_icon(i),
                                                              description=i["label"][:100]) for i in infos[:25]])
        sel.callback = self._detail
        self.add_item(sel)

    async def _detail(self, interaction: discord.Interaction) -> None:
        i = self.infos.get(interaction.data["values"][0])
        if i is None:
            await _say(interaction, "Unknown obfuscator.", ephemeral=True)
            return
        e = ui_kit.embed("info" if i["ok"] else "failed", i["display"])
        e.add_field(name="Tool", value=f"`{i['name']}`", inline=True)
        e.add_field(name="Delivers", value="execution trace" if i["kind"] == "trace" else "source code", inline=True)
        e.add_field(name="State", value="available" if i["ok"] else i["why"], inline=True)
        if i["notes"]:
            e.add_field(name="Notes", value=i["notes"][:500], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Menu", emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="back", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await show_main(interaction, self.bot, self.invoker_id, edit=True)


class StatsView(_View):
    def __init__(self, bot, invoker_id: int) -> None:
        super().__init__(invoker_id)
        self.bot = bot

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await stats_embed(), view=self)

    @discord.ui.button(label="Menu", emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="back", row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await show_main(interaction, self.bot, self.invoker_id, edit=True)


# ── menu principal ────────────────────────────────────────────────────────────────────────────────────────────────────

def main_embed() -> discord.Embed:
    e = ui_kit.embed("info", "Dashboard")
    e.description = ("Send a script with `/get` (or `.get`): the bot analyses it, recognises the obfuscator and picks the engine.\n"
                     "Pick a panel below.")
    return e


class MainView(_View):
    OPTIONS = [("deobf", "Deobfuscation", "Link, latest results, cancel", "🧩"),
               ("engines", "Obfuscator supported", "Obfuscators the bot can deobfuscate", "🛠️"),
               ("stats", "Statistics", "Operations, successes, failures (administrators)", "📊"),
               ("settings", "Settings", "Server options", "🔧")]

    def __init__(self, bot, cog, invoker_id: int) -> None:
        super().__init__(invoker_id)
        self.bot, self.cog = bot, cog
        sel = discord.ui.Select(placeholder="Open a panel…", options=[
            discord.SelectOption(label=lbl, value=key, description=desc, emoji=emo) for key, lbl, desc, emo in self.OPTIONS])
        sel.callback = self._open
        self.add_item(sel)

    async def _open(self, interaction: discord.Interaction) -> None:
        key = interaction.data["values"][0]
        uid, gid = self.invoker_id, _gid(interaction)
        if key == "prefix":
            e = await prefix_embed(self.bot, interaction)
            editable = gid is not None and await can_manage(interaction)
            if gid is not None and not editable:
                e.set_footer(text="read only: \"Manage Server\" permission required to change")
            view = PrefixView(self.bot, uid, gid, editable)
        elif key == "deobf":
            e = ui_kit.embed("info", "Deobfuscation")
            e.description = ("`/get` or `.get` + link or file: analysis, then **Yes / No** to start.\n"
                             "`/deobf` or `.deobf` starts directly (the engine is chosen automatically).")
            view = DeobfView(self.bot, self.cog, uid)
        elif key == "engines":
            e = await engines_embed()
            view = EnginesView(self.bot, uid, [i for i in await asyncio.to_thread(_engines_info) if i["ok"]])
        elif key == "stats":
            if not await is_authorized(interaction):
                await _say(interaction, "Statistics are reserved to the bot owner (or allowed IDs).", ephemeral=True)
                return
            e, view = await stats_embed(), StatsView(self.bot, uid)
        else:
            e = settings_embed(gid)
            view = SettingsView(self.bot, uid, gid, gid is not None and await can_manage(interaction))
        view.message = self.message
        self.stop()
        await interaction.response.edit_message(embed=e, view=view)


    @discord.ui.button(label="Deobfuscation", emoji="🧩", style=discord.ButtonStyle.primary, row=1)
    async def deobf_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        e = ui_kit.embed("info", "Deobfuscation")
        e.description = ("`/get` or `.get` + link or file: analyse, then **Yes / No** to run.\n"
                         "`/deobf` or `.deobf` runs directly (the engine is chosen automatically).")
        view = DeobfView(self.bot, self.cog, self.invoker_id)
        view.message = self.message
        self.stop()
        await interaction.response.edit_message(embed=e, view=view)

async def show_main(interaction, bot, invoker_id: int, *, edit: bool = False) -> None:
    cog = bot.get_cog("PanelCog")
    view = MainView(bot, cog, invoker_id)
    if edit:
        view.message = getattr(interaction, "message", None)
        await interaction.response.edit_message(embed=main_embed(), view=view)
    else:
        view.message = await _send(interaction, embed=main_embed(), view=view, ephemeral=_private(interaction))


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
#  .get : recuperer, analyser, proposer Oui / Non
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

def _fetch_error(exc: Exception) -> str:
    """Message court et comprehensible pour un echec de recuperation (jamais de trace Python)."""
    s = str(exc)
    low = s.lower()
    if "reponse vide" in low or "empty response" in low:
        return "empty response: the server sent no content"
    m = re.search(r"(?:serveur a répondu|server replied) (\d+)", s, re.I)
    if m:
        return f"the server replied {m.group(1)} (content not found or refused)"
    if "ssrf" in low or "non publique" in low or "bloqu" in low or "no public address" in low or "blocked" in low:
        return "address refused (internal network or port not allowed)"
    if "url" in low and ("http" in low or "invalide" in low):
        return "invalid address: it must start with http:// or https://"
    if "redirection" in low or "redirect" in low:
        return "too many redirects or an invalid redirect"
    if "fichier >" in low or "trop volumineux" in low or "too large" in low:
        return s[:120]
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timeout" in low or "timed out" in low:
        return "timed out: the server does not respond"
    return "fetch failed (" + type(exc).__name__ + ")"


class ConfirmView(_View):
    """Yes / No after the `.get` analysis. Yes: starts deobfuscation with the tool picked by the bot; No: cancels and keeps the analysis."""

    def __init__(self, invoker_id: int, name: str, raw: bytes, base: discord.Embed, started_by) -> None:
        super().__init__(invoker_id, timeout=GET_TIMEOUT)
        self.name, self.raw, self.base, self.started_by = name, raw, base, started_by
        self.decided: Optional[str] = None

    def _final(self, text: str, status: Optional[str] = None) -> discord.Embed:
        e = discord.Embed.from_dict(self.base.to_dict())
        if status:
            e.color = ui_kit.COLORS[status]
        e.set_footer(text=text[:200])
        return e

    @discord.ui.button(label="Yes", emoji="✅", style=discord.ButtonStyle.success, row=0)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.decided:
            await _say(interaction, "Already handled.", ephemeral=True)
            return
        self.decided = "yes"
        self.stop()
        raw, self.raw = self.raw, b""
        await interaction.response.edit_message(embed=self._final("deobfuscation started…", "running"), view=None)
        try:
            await run_items(interaction, [(self.name, raw)], "auto", JOB_TIMEOUT_DEFAULT, False)
        except Exception as exc:  # noqa: BLE001 - une erreur ne doit pas laisser l'utilisateur sans reponse
            _log(f"get/oui : erreur : {type(exc).__name__}: {exc}")
            await _say(interaction, "❌ Deobfuscation impossible (details in the logs).", ephemeral=True)
            return
        try:
            await interaction.edit_original_response(embed=self._final("deobfuscation finished", None), view=None)
        except (discord.HTTPException, AttributeError):
            pass

    @discord.ui.button(label="No", emoji="❌", style=discord.ButtonStyle.secondary, row=0)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.decided:
            await _say(interaction, "Already handled.", ephemeral=True)
            return
        self.decided = "no"
        self.stop()
        self.raw = b""
        await interaction.response.edit_message(embed=self._final("deobfuscation cancelled — analysis kept", "cancelled"), view=None)

    async def on_timeout(self) -> None:
        if self.decided is None and self.message is not None:
            try:
                await self.message.edit(embed=self._final("timed out — no deobfuscation started", "cancelled"), view=None)
            except (discord.HTTPException, AttributeError):
                pass
        self.raw = b""


def build_get_embed(name: str, dec, info: dict, elapsed: float) -> tuple[discord.Embed, bool]:
    """(embed d'analyse, proposer Oui/Non ?). Court : langage, taille, protection, statut, et seulement ce qui compte."""
    can_run = bool(dec.supported and dec.kind in ("source", "trace", "loader", "archive"))
    status = {"gated": "failed", "invalid": "failed", "unavailable": "failed", "unsupported": "cancelled"}.get(dec.kind, "info")
    notes: list[str] = []
    if info.get("redirects"):
        notes.append("redirected via " + " → ".join(dict.fromkeys(info["redirects"][:3])))
    if info.get("status") and info["status"] != 200:
        notes.append(f"HTTP {info['status']}")
    if dec.requires_key and dec.kind != "gated":
        notes.append("asks for a key")
    notes += [n for n in dec.notes if n not in notes][:2]
    protection = dec.title
    if dec.kind in ("source", "trace") and dec.obfuscator:
        protection = dec.title
    e = ui_kit.analysis_embed(name, dec.size, dec.language, protection, dec.verdict, status, links=len(dec.links),
                              note=" · ".join(notes), elapsed=elapsed)
    if can_run:
        e.set_footer(text="Start the deobfuscation?")
    return e, can_run


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
#  Cog
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

class PanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_unload(self) -> None:
        st = _suite_mod("stats_store").stats()
        st.flush()

    # -- logique partagee (appelee par les commandes slash ET a prefixe) ---------------------------------------------------
    async def panel_flow(self, interaction) -> None:
        if await _allowed(interaction):
            await show_main(interaction, self.bot, interaction.user.id)

    async def prefix_flow(self, interaction) -> None:
        if await _allowed(interaction):
            await show_prefixes(interaction, self.bot)

    async def stats_flow(self, interaction) -> None:
        if not await is_authorized(interaction):
            await _say(interaction, NOT_AUTHORIZED_MSG, ephemeral=True)
            return
        view = StatsView(self.bot, interaction.user.id)
        view.message = await _send(interaction, embed=await stats_embed(), view=view, ephemeral=_private(interaction))

    async def get_flow(self, interaction, url: Optional[str] = None, fichier: Optional[discord.Attachment] = None) -> None:
        if not url and not fichier:
            await _say(interaction, "Give a link or attach a file: `/get link:<url>` or `.get <url>`.", ephemeral=True)
            return
        if not await _allowed(interaction):
            return
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        t0 = time.monotonic()
        info: dict = {}
        try:
            if fichier is not None:
                if fichier.size and fichier.size > _MAX_BYTES:
                    raise ValueError(f"Fichier > {_MAX_BYTES // (1024 * 1024)} Mo")
                raw, name = await fichier.read(), fichier.filename
            else:
                name, raw = await asyncio.wait_for(_fetch_url(url, info, cache=True), timeout=45)
        except Exception as exc:  # noqa: BLE001
            msg = _fetch_error(exc)
            _log(f"get : recuperation echouee ({type(exc).__name__}: {exc})")
            _record_stat("get", interaction.user.id, str(url or getattr(fichier, "filename", "?"))[:60], "failed", None, time.monotonic() - t0)
            e = ui_kit.embed("failed", "Fetch failed", msg)
            await _send(interaction, embed=e)
            return
        try:
            dec = await asyncio.wait_for(asyncio.to_thread(_suite_mod("decision").decide, raw, name), timeout=60)
        except Exception as exc:  # noqa: BLE001
            _log(f"get : analyse impossible ({type(exc).__name__}: {exc})")
            _record_stat("get", interaction.user.id, name, "failed", None, time.monotonic() - t0)
            await _send(interaction, embed=ui_kit.embed("failed", "Analysis failed", "see the admin logs"))
            return
        _log(f"get {interaction.user.id} {name} : {dec.as_log()}")
        embed, can_run = build_get_embed(name, dec, info, time.monotonic() - t0)
        _record_stat("get", interaction.user.id, name, "info", dec.engine, time.monotonic() - t0)
        if can_run:
            view = ConfirmView(interaction.user.id, name, raw, embed, interaction.user)
            view.message = await _send(interaction, embed=embed, view=view)
        else:
            await _send(interaction, embed=embed)

    # -- commandes slash ----------------------------------------------------------------------------------------------------
    @app_commands.command(name="panel", description="Dashboard: prefixes, deobfuscation, obfuscators, statistics, settings")
    async def panel(self, interaction: discord.Interaction) -> None:
        await self.panel_flow(interaction)

    @app_commands.command(name="prefix", description="Manage this server's command prefixes")
    async def prefix(self, interaction: discord.Interaction) -> None:
        await self.prefix_flow(interaction)

    @app_commands.command(name="stats", description="[Owner only] Bot statistics")
    @owner_only()
    async def stats(self, interaction: discord.Interaction) -> None:
        await self.stats_flow(interaction)

    @app_commands.command(name="get", description="Fetch a script, analyse it, recognise the obfuscator and offer to deobfuscate it")
    @app_commands.describe(url="Lien direct vers le script", fichier="Fichier .lua/.luau/.txt")
    async def get(self, interaction: discord.Interaction, url: Optional[str] = None, fichier: Optional[discord.Attachment] = None) -> None:
        await self.get_flow(interaction, url=url, fichier=fichier)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        msg = NOT_AUTHORIZED_MSG if isinstance(error, app_commands.CheckFailure) else "❌ Unexpected error (details in the logs)."
        if not isinstance(error, app_commands.CheckFailure):
            _log(f"commande {getattr(interaction.command, 'name', '?')} : {type(error).__name__}: {error}")
        await _say(interaction, msg, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
#  Commandes a prefixe : memes fonctions que les commandes slash
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

PREFIX_COMMANDS = ("get", "help", "panel", "prefix", "stats", "process", "deobf_engines", "deobf_etat", "deobf_dernier", "deobf_annuler", "deobf_moi", "deobf_roles")


def _first_url(args) -> Optional[str]:
    return next((a.strip("<>") for a in args if a.lower().lstrip("<").startswith(("http://", "https://"))), None)


def install_prefix_commands(bot: commands.Bot) -> list[str]:
    """Installe les commandes a prefixe equivalentes aux commandes slash : memes interfaces, memes boutons, memes resultats.
    DEOBF_PREFIX=0 : rien n'est installe ; DEOBF_KEEP_PREFIX=1 : une commande existante du meme nom est conservee."""
    import os
    if os.environ.get("DEOBF_PREFIX", "1") == "0":
        return []
    keep = os.environ.get("DEOBF_KEEP_PREFIX", "0") == "1"
    installed: list[str] = []

    def guarded(name: str, cog_name: str, admin: bool = False):
        """Decorateur : cog present, anti-spam, droits (commandes reservees), erreurs courtes."""
        def deco(fn):
            async def wrapper(ctx: commands.Context, *args: str) -> None:
                cog = bot.get_cog(cog_name)
                inter = PrefixInteraction(ctx)
                if admin and not await is_authorized(inter):        # d'abord les droits : un inconnu ne voit rien d'autre
                    await ctx.reply(NOT_AUTHORIZED_MSG, mention_author=False)
                    return
                if cog is None:
                    await ctx.reply("Module not loaded.", mention_author=False)
                    return
                try:
                    await fn(ctx, inter, cog, args)
                except Exception as exc:  # noqa: BLE001
                    _log(f"commande a prefixe {name} : {type(exc).__name__}: {exc}")
                    await ctx.reply("❌ Unexpected error (details in the logs).", mention_author=False,
                                    allowed_mentions=discord.AllowedMentions.none())
            wrapper.__name__ = f"{name}_prefix"
            return wrapper
        return deco

    def attach(ctx):
        return ctx.message.attachments[0] if ctx.message.attachments else None

    @guarded("get", "PanelCog")
    async def get_cmd(ctx, inter, cog, args):
        await cog.get_flow(inter, url=_first_url(args), fichier=attach(ctx))

    @guarded("help", "PanelCog")
    async def panel_cmd(ctx, inter, cog, args):
        await cog.panel_flow(inter)

    @guarded("prefix", "PanelCog")
    async def prefix_cmd(ctx, inter, cog, args):
        await cog.prefix_flow(inter)

    @guarded("stats", "PanelCog", admin=True)
    async def stats_cmd(ctx, inter, cog, args):
        await cog.stats_flow(inter)

    @guarded("process", "ToolsCog", admin=True)
    async def process_cmd(ctx, inter, cog, args):
        if not _first_url(args) and attach(ctx) is None:
            await ctx.reply("Attach a file or give a link: `process <link>`.", mention_author=False)
            return
        await cog.process.callback(cog, inter, _first_url(args), attach(ctx))

    @guarded("deobf_engines", "DeobfCog", admin=True)
    async def engines_cmd(ctx, inter, cog, args):
        await cog.deobf_engines.callback(cog, inter)

    @guarded("deobf_etat", "DeobfCog", admin=True)
    async def etat_cmd(ctx, inter, cog, args):
        await cog.deobf_etat.callback(cog, inter)

    @guarded("deobf_dernier", "DeobfCog", admin=True)
    async def dernier_cmd(ctx, inter, cog, args):
        n = next((int(a) for a in args if a.isdigit()), 1)
        await cog.deobf_dernier.callback(cog, inter, max(1, min(5, n)))

    @guarded("deobf_annuler", "DeobfCog", admin=True)
    async def annuler_cmd(ctx, inter, cog, args):
        await cog.deobf_annuler.callback(cog, inter, " ".join(args) or None)

    @guarded("deobf_roles", "DeobfCog", admin=True)
    async def roles_cmd(ctx, inter, cog, args):
        act = args[0].lower() if args else "list"
        if act not in ("add", "remove", "list"):
            await ctx.reply("Usage: `deobf_roles add|remove|list [@role]`.", mention_author=False)
            return
        role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        await cog.deobf_roles.callback(cog, inter, app_commands.Choice(name=act, value=act), role)

    @guarded("deobf_moi", "DeobfCog")
    async def moi_cmd(ctx, inter, cog, args):
        await cog.deobf_moi.callback(cog, inter)

    table = [("get", get_cmd, ["recuperer"]), ("panel", panel_cmd, ["menu"]), ("help", panel_cmd, []),
             ("prefix", prefix_cmd, ["prefixes", "prefixe"]),
             ("stats", stats_cmd, []), ("process", process_cmd, []), ("deobf_engines", engines_cmd, ["engines", "moteurs"]),
             ("deobf_etat", etat_cmd, ["etat"]), ("deobf_dernier", dernier_cmd, ["dernier"]), ("deobf_annuler", annuler_cmd, ["annuler"]),
             ("deobf_moi", moi_cmd, ["moi"]), ("deobf_roles", roles_cmd, ["roles"])]
    for name, fn, aliases in table:
        cmd = commands.Command(fn, name=name, aliases=aliases)
        if name == "help" and bot.get_command("help") is not None:
            continue            # le bot hote a deja son propre `help` (menu d'aide general) : on ne le remplace JAMAIS ; le tableau de bord est `panel`
        for n in [name] + aliases:
            old = bot.get_command(n)
            if old is not None:
                if keep:
                    break
                bot.remove_command(n)
                print(f"[panel_cog] commande a prefixe existante `{n}` remplacee (DEOBF_KEEP_PREFIX=1 pour la garder)")
        else:
            try:
                bot.add_command(cmd)
                installed.append(name)
            except commands.CommandRegistrationError as exc:
                print(f"[panel_cog] commande a prefixe `{name}` non installee : {exc}")
    return installed


def remove_prefix_commands(bot: commands.Bot) -> None:
    for name in PREFIX_COMMANDS:
        cmd = bot.get_command(name)
        if cmd is not None and getattr(cmd.callback, "__module__", "") == __name__:
            bot.remove_command(name)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PanelCog(bot))
    install_prefix_commands(bot)
