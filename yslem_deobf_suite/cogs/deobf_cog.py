"""
deobf_cog.py -- /deobf, /deobf_engines, /deobf_moi (discord.py 2.x).

/deobf detecte l'obfuscateur d'un script Lua/Luau et lance le bon moteur (Hercules, Ironveil,
LuaObfuscator.com, Centurion v6, MoonSec v3, IronBrew1...). C'est EXACTEMENT le meme code que
/process (tools_cog.run_job) : meme routeur, meme moteur, meme resultat que
`python3 deobf_router.py run entree.lua sortie.lua` en ligne de commande. Le suivi (compte a rebours) et le resultat sont postes
dans le SALON de la commande (replis : reponse a la commande, MP, results/).

RESERVE au proprietaire du bot (+ les ID de allowed_ids.txt / DEOBF_ALLOWED_IDS) : le garde-fou est
`owner_only()` (un vrai `app_commands.check`, defini dans tools_cog.py). Ne JAMAIS le remplacer par le
decorateur is_owner() des commandes prefixees : sur une slash command il n'est pas applique (cmd.checks == []).

Pourquoi owner-only : les moteurs executent le script soumis dans un bac a sable Luau (proxys qui journalisent
HttpGet/writefile/... au lieu de les executer), mais ce n'est PAS une isolation systeme.

Installation : aucune etape manuelle. Node.js et le Luau patche sont fournis automatiquement par
bootstrap.py au premier usage (pre-chauffage en tache de fond au chargement du cog).
    await bot.load_extension("yslem_deobf_suite.bot_extension")     # charge les deux cogs
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

try:                                    # charge comme sous-module du paquet yslem_deobf_suite.cogs
    from .tools_cog import (_find_suite, JOB_TIMEOUT_DEFAULT, NOT_AUTHORIZED_MSG,
                            is_authorized, owner_only, quick_findings, run_job, send_last_results,
                            status_text, cancel_current, _fetch_url, _MAX_BYTES)
except ImportError:                     # charge a plat (load_extension("deobf_cog") avec les deux fichiers cote a cote)
    from tools_cog import (_find_suite, JOB_TIMEOUT_DEFAULT, NOT_AUTHORIZED_MSG,  # type: ignore
                       is_authorized, owner_only, quick_findings, run_job, send_last_results,
                       status_text, cancel_current, _fetch_url, _MAX_BYTES)

SUITE_DIR = _find_suite()
ROUTER = SUITE_DIR / "deobf_router.py"
__all__ = ["DeobfCog", "quick_findings", "setup"]


class PrefixInteraction:
    """Fait passer un message `.deobf` (commande a prefixe) pour une interaction : les memes fonctions (menu de choix du
    moteur, run_job, /analyse...) servent donc aux commandes slash ET aux commandes a prefixe. Pas de reponse « ephemere »
    possible dans un message : tout est envoye dans le salon (en reponse au message)."""

    class _Response:
        def __init__(self, ctx) -> None:
            self._ctx, self._done = ctx, False
            self.message = None

        def is_done(self) -> bool:
            return self._done

        async def defer(self, **_kw) -> None:
            self._done = True

        async def send_message(self, content=None, **kw) -> None:
            self._done = True
            kw.pop("ephemeral", None)
            kw.pop("wait", None)
            self.message = await self._ctx.reply(content, mention_author=False, **kw)

    class _Followup:
        def __init__(self, ctx) -> None:
            self._ctx = ctx

        async def send(self, content=None, **kw):
            kw.pop("ephemeral", None)
            kw.pop("wait", None)
            return await self._ctx.reply(content, mention_author=False, **kw)

    def __init__(self, ctx: commands.Context) -> None:
        self._ctx = ctx
        self.user = ctx.author
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.channel_id = getattr(ctx.channel, "id", None)
        self.client = ctx.bot
        self._state = getattr(ctx, "_state", None)
        self.response = self._Response(ctx)
        self.followup = self._Followup(ctx)

    async def delete_original_response(self) -> None:       # rien d'« original » a retirer : la commande est un message
        return None

    async def original_response(self):
        """Le message envoye par la reponse (ou None) : meme contrat que Interaction.original_response()."""
        return self.response.message

    async def edit_original_response(self, **kw):
        msg = self.response.message
        if msg is None:
            return None
        kw.pop("ephemeral", None)
        return await msg.edit(**kw)


PREFIX_COMMANDS = ("deobf", "analyse")


def _prefix_args(ctx: commands.Context, args: tuple) -> tuple[Optional[str], Optional[discord.Attachment], str]:
    url = next((a for a in args if a.lower().startswith(("http://", "https://"))), None)
    moteur = next((a for a in args if a != url), "auto")
    fichier = ctx.message.attachments[0] if ctx.message.attachments else None
    return url, fichier, moteur


async def _deobf_channel_cmd(ctx: commands.Context, rest: tuple) -> None:
    """`.deobf channel` : reserve les commandes de deobfuscation a ce salon. `.deobf channel off` : leve la restriction."""
    from yslem_deobf_suite import settings_store
    if ctx.guild is None:
        await ctx.reply("This command only works in a server.", mention_author=False)
        return
    perms = getattr(ctx.author, "guild_permissions", None)
    if not ((perms is not None and (perms.manage_guild or perms.administrator)) or await is_authorized(PrefixInteraction(ctx))):
        await ctx.reply("You need the « Manage Server » permission to set this.", mention_author=False)
        return
    st = settings_store.store()
    if rest and rest[0].lower() in ("off", "none", "reset"):
        st.set_deobf_channel(ctx.guild.id, None)
        await ctx.reply("Deobfuscation commands now work in every channel.", mention_author=False)
        return
    st.set_deobf_channel(ctx.guild.id, ctx.channel.id)
    await ctx.reply(
        f"Deobfuscation commands now only work in {ctx.channel.mention}. "
        "Other messages there are deleted; type `.help` for the list of commands.",
        mention_author=False, allowed_mentions=discord.AllowedMentions.none())


def install_prefix_commands(bot: commands.Bot) -> list[str]:
    """`.deobf [moteur] [lien]` + fichier joint, et `.analyse` : memes fonctions que les commandes slash. Si le bot avait deja
    une commande a prefixe du meme nom (ancienne version), elle est REMPLACEE par celle-ci (DEOBF_PREFIX=0 : ne rien installer ;
    DEOBF_KEEP_PREFIX=1 : ne pas remplacer une commande existante)."""
    if os.environ.get("DEOBF_PREFIX", "1") == "0":
        return []
    installed = []
    keep = os.environ.get("DEOBF_KEEP_PREFIX", "0") == "1"

    @commands.command(name="deobf", aliases=["deobfuscate"])
    async def deobf_prefix(ctx: commands.Context, *args: str) -> None:
        cog = bot.get_cog("DeobfCog")
        inter = PrefixInteraction(ctx)
        if cog is None:
            await ctx.reply("Deobfuscation module not loaded.", mention_author=False)
            return
        if args and args[0].lower() in ("channel", "salon"):
            await _deobf_channel_cmd(ctx, args[1:])
            return
        url, fichier, moteur = _prefix_args(ctx, args)
        if not url and not fichier:
            await ctx.reply("Attach a file (.lua/.txt/.zip) or give a link: `.deobf [engine] [link]`. "
                            "Engines: `auto` or a name from `/deobf_engines`.", mention_author=False)
            return
        try:
            await cog.deobf.callback(cog, inter, url, fichier, moteur, None, False)
        except Exception as exc:  # noqa: BLE001
            await ctx.reply(f"❌ Erreur inattendue : `{exc}`", mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="analyse", aliases=["analyze"])
    @commands.cooldown(1, 20, commands.BucketType.user)
    async def analyse_prefix(ctx: commands.Context, *args: str) -> None:
        cog = bot.get_cog("ToolsCog")
        if cog is None:
            await ctx.reply("Analysis module not loaded.", mention_author=False)
            return
        url, fichier, _ = _prefix_args(ctx, args)
        if not url and not fichier:
            await ctx.reply("Attach a file or give a link: `.analyse [link]`.", mention_author=False)
            return
        try:
            await cog.analyse.callback(cog, PrefixInteraction(ctx), url, fichier)
        except Exception as exc:  # noqa: BLE001
            await ctx.reply(f"❌ Erreur inattendue : `{exc}`", mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none())

    for cmd in (deobf_prefix, analyse_prefix):
        old = bot.get_command(cmd.name)
        if old is not None:
            if keep:
                continue
            bot.remove_command(cmd.name)
            print(f"[deobf_cog] commande a prefixe existante `{cmd.name}` remplacee (DEOBF_KEEP_PREFIX=1 pour la garder)")
        for alias in cmd.aliases:
            if bot.get_command(alias) is not None and not keep:
                bot.remove_command(alias)
        try:
            bot.add_command(cmd)
            installed.append(cmd.name)
        except commands.CommandRegistrationError as exc:
            print(f"[deobf_cog] commande a prefixe `{cmd.name}` non installee : {exc}")
    return installed


def remove_prefix_commands(bot: commands.Bot) -> None:
    for name in PREFIX_COMMANDS:
        cmd = bot.get_command(name)
        if cmd is not None and getattr(cmd.callback, "__module__", "") == __name__:
            bot.remove_command(name)


PICKER_TIMEOUT = 180            # secondes pour choisir un moteur


class EnginePicker(discord.ui.View):
    """Interface « quel moteur utiliser ? » affichee APRES l'analyse (detecteur de la suite + avis du modele) et AVANT la
    deobfuscation. Reservee a ceux qui ont le droit de lancer /deobf."""

    def __init__(self, engines: list[tuple[str, str]], recommended: Optional[str], launch) -> None:
        super().__init__(timeout=PICKER_TIMEOUT)
        self._launch = launch
        self.message: Optional[discord.Message] = None
        opts = [discord.SelectOption(label="auto — the bot decides", value="auto",
                                     description="automatic detection (like /process)", emoji="🤖")]
        for name, label in engines[:24]:
            opts.append(discord.SelectOption(label=name[:100], value=name, description=label[:100],
                                             emoji="⭐" if name == recommended else None))      # recommande = ⭐ seulement, JAMAIS preselectionne
        select = discord.ui.Select(placeholder="Quel moteur utiliser ?", min_values=1, max_values=1, options=opts)
        select.callback = self._chosen
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def _chosen(self, interaction: discord.Interaction) -> None:
        choice = interaction.data["values"][0]
        self.stop()
        try:
            await interaction.response.edit_message(content=f"✅ Engine chosen: **{choice}** — deobfuscation started.",
                                                    embed=None, view=None)
        except discord.HTTPException:
            pass
        await self._launch(interaction, choice)

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(content="⌛ No engine chosen: run `/deobf` again.", embed=None, view=None)
            except discord.HTTPException:
                pass


class DeobfCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._prewarm: Optional[asyncio.Task] = None

    async def cog_load(self) -> None:
        """Pre-chauffage : telecharge Node.js / installe le Luau patche en tache de fond, sans bloquer le bot."""
        self._prewarm = asyncio.create_task(self._prepare())

    async def cog_unload(self) -> None:
        if self._prewarm and not self._prewarm.done():
            self._prewarm.cancel()

    async def _prepare(self) -> None:
        try:
            sys.path.insert(0, str(SUITE_DIR))
            try:
                import bootstrap  # noqa: WPS433
            finally:
                if sys.path and sys.path[0] == str(SUITE_DIR):
                    sys.path.pop(0)
            await asyncio.to_thread(bootstrap.ensure_ready, lambda m: print(f"[deobf_cog] {m}"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - le premier job retentera et affichera l'erreur
            print(f"[deobf_cog] preparation automatique non terminee : {exc}")

    @app_commands.command(name="deobf", description="Deobfuscate a script or a .zip (in parallel), progress and results in the channel")
    @app_commands.describe(url="Direct link to the script", fichier="File .lua/.luau/.txt, or .zip of scripts (up to 100, processed in parallel)",
                           moteur="auto (defaut : analyse puis choix du moteur) ou un moteur precis (voir /deobf_engines)",
                           timeout_min="Delai max en minutes (defaut 25, allonge automatiquement si la machine est lente)",
                           recalculer="Refaire le calcul meme si ce script a deja ete deobfusque (cache)")
    async def deobf(self, interaction: discord.Interaction, url: Optional[str] = None,
                    fichier: Optional[discord.Attachment] = None, moteur: Optional[str] = "auto",
                    timeout_min: Optional[app_commands.Range[int, 1, 180]] = None, recalculer: Optional[bool] = False) -> None:
        timeout = min(3 * 3600, (timeout_min * 60) if timeout_min else JOB_TIMEOUT_DEFAULT)
        moteur = (moteur or "auto").strip()
        if (url or fichier) and moteur == "auto" and os.environ.get("DEOBF_PICKER", "0") == "1":      # l'ancien menu « quel moteur ? » : desactive par defaut, le bot choisit seul
            if await self._pick_then_run(interaction, url, fichier, moteur, timeout, bool(recalculer)):
                return
        await run_job(interaction, url=url, fichier=fichier, moteur=moteur,
                      timeout_s=timeout, force=bool(recalculer))

    async def _pick_then_run(self, interaction: discord.Interaction, url, fichier, family: str, timeout: int,
                             force: bool) -> bool:
        """Analyse (detecteur + avis du modele), puis selecteur de moteur. True = pris en charge ; False = comportement
        d'origine (zip, fichier illisible, analyse impossible) : l'appelant lance run_job normalement."""
        name = (fichier.filename if fichier is not None else (url or "")).lower()
        if name.endswith(".zip"):
            return False                                   # un zip = plusieurs scripts : detection automatique de chacun
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            if fichier is not None:
                if fichier.size and fichier.size > _MAX_BYTES:
                    return False
                raw = await fichier.read()
                fname = fichier.filename
            else:
                fname, raw = await _fetch_url(url)
            if not raw or raw[:4] == b"PK\x03\x04":
                return False
            text = raw.decode("utf-8", "replace")
            sys.path.insert(0, str(SUITE_DIR))
            try:
                import obf_identify  # noqa: WPS433
                import deobf_router  # noqa: WPS433
                ident = await asyncio.wait_for(asyncio.to_thread(obf_identify.identify, text, True, True), timeout=75)
                engines = [(e.name, e.label) for e in deobf_router.load_engines() if e.safe]
            finally:
                if sys.path and sys.path[0] == str(SUITE_DIR):
                    sys.path.pop(0)
        except Exception:  # noqa: BLE001 -- l'analyse est une aide : sans elle on retombe sur le mode automatique
            return False
        rec = ident.get("recommended")
        rec_name = rec[0] if rec and rec[0] in dict(engines) else None
        embed = discord.Embed(title=f"🔎 Analyse — {fname}"[:250], description=ident["summary"][:1800], color=0x2B6CB0)
        if rec_name:
            embed.add_field(name="⭐ Recommended engine",
                            value=f"`{rec_name}` (based on {'the suite detector' if rec[1] == 'detecteur' else 'Gemini'})", inline=False)
        else:
            embed.add_field(name="⭐ Recommended engine", value="none — pick one, or \"auto\"", inline=False)
        embed.set_footer(text=f"Pick an engine below ({PICKER_TIMEOUT} s). The script only runs in the sandbox.")

        async def launch(inter: discord.Interaction, choice: str) -> None:
            await run_job(inter, url=url, fichier=fichier, moteur=choice, timeout_s=timeout, force=force)

        view = EnginePicker(engines, rec_name, launch)
        view.message = await interaction.followup.send(embed=embed, view=view, ephemeral=True, wait=True)
        return True

    @deobf.autocomplete("moteur")
    async def _moteur_autocomplete(self, interaction: discord.Interaction, current: str):
        names = ["auto"] + self._engine_names()
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    def _engine_names(self) -> list[str]:
        try:
            sys.path.insert(0, str(SUITE_DIR))
            import deobf_router  # noqa: WPS433
            return [e.name for e in deobf_router.load_engines()]
        except Exception:  # noqa: BLE001
            return []
        finally:
            if sys.path and sys.path[0] == str(SUITE_DIR):
                sys.path.pop(0)

    def _engines_report(self) -> str:
        try:
            sys.path.insert(0, str(SUITE_DIR))
            import deobf_router  # noqa: WPS433
            lines = []
            for e in deobf_router.load_engines():
                miss = e.missing_requirements()
                lines.append(f"{'OK ' if not miss else 'KO '} {e.name:22} {'sur' if e.safe else 'NON SUR':8} {e.label}"
                             + (f"  [manque: {', '.join(miss)} -- installe automatiquement au 1er job]" if miss else ""))
            return "\n".join(lines) or "No engine found."
        except Exception as exc:  # noqa: BLE001
            return f"Erreur : {exc}"
        finally:
            if sys.path and sys.path[0] == str(SUITE_DIR):
                sys.path.pop(0)

    @app_commands.command(name="deobf_engines", description="[Owner only] Installed deobfuscation engines and their status")
    @owner_only()
    async def deobf_engines(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)          # la verification lance `node --version` : < 3 s non garanti
        body = await asyncio.to_thread(self._engines_report)
        await interaction.followup.send(f"```\n{body[:1900]}\n```", ephemeral=True)

    @app_commands.command(name="deobf_dernier", description="[Owner only] Resend the last saved result(s) (DMs closed, job too long)")
    @app_commands.describe(nombre="How many results to send back (default 1)")
    @owner_only()
    async def deobf_dernier(self, interaction: discord.Interaction,
                            nombre: Optional[app_commands.Range[int, 1, 5]] = 1) -> None:
        await send_last_results(interaction, nombre or 1)

    @app_commands.command(name="deobf_etat", description="[Owner only] Diagnostics: requirements, running job, recent jobs, write test")
    @owner_only()
    async def deobf_etat(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        body = await status_text(interaction)
        await interaction.followup.send(f"```\n{body[:1900]}\n```", ephemeral=True)

    @app_commands.command(name="deobf_annuler", description="[Owner only] Stop running jobs (all, or those whose name contains...)")
    @app_commands.describe(nom="Part of the file name to cancel (empty = all running jobs)")
    @owner_only()
    async def deobf_annuler(self, interaction: discord.Interaction, nom: Optional[str] = None) -> None:
        await cancel_current(interaction, nom)

    @app_commands.command(name="deobf_roles", description="[Owner only] Add, remove or list the roles allowed to use the owner-only deobf commands")
    @app_commands.describe(action="add, remove or list", role="The role to add or remove")
    @app_commands.choices(action=[app_commands.Choice(name="add", value="add"),
                                  app_commands.Choice(name="remove", value="remove"),
                                  app_commands.Choice(name="list", value="list")])
    @owner_only()
    async def deobf_roles(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                          role: Optional[discord.Role] = None) -> None:
        from yslem_deobf_suite import settings_store
        if interaction.guild is None:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        st = settings_store.store()
        gid = interaction.guild.id
        if action.value == "list":
            roles = st.deobf_roles(gid)
            text = ", ".join(f"<@&{r}>" for r in roles) if roles else "none"
            await interaction.response.send_message(f"Roles allowed to use the deobf commands: {text}", ephemeral=True)
            return
        if role is None:
            await interaction.response.send_message("Pick a `role`.", ephemeral=True)
            return
        if action.value == "add":
            st.add_deobf_role(gid, role.id)
            msg = f"Role {role.mention} can now use the deobf commands."
        else:
            st.remove_deobf_role(gid, role.id)
            msg = f"Role {role.mention} can no longer use the owner-only deobf commands."
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="deobf_moi", description="Affiche ton ID Discord et si tu peux utiliser /process et /deobf")
    async def deobf_moi(self, interaction: discord.Interaction) -> None:
        ok = await is_authorized(interaction)
        await interaction.response.send_message(
            f"Ton ID : `{interaction.user.id}` -- acces a /process et /deobf : **{'oui' if ok else 'non'}**."
            + ("" if ok else "\nPour t'autoriser : ajoute cet ID dans `allowed_ids.txt` (dossier yslem_deobf_suite) "
                             "ou dans la variable d'environnement `DEOBF_ALLOWED_IDS`."),
            ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            msg = NOT_AUTHORIZED_MSG
        else:
            msg = f"Erreur inattendue : `{error}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DeobfCog(bot))
    install_prefix_commands(bot)
