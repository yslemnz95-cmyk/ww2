#!/usr/bin/env python3
"""
Interfaces Discord : prefixes dynamiques par serveur (persistants), panneaux /panel, .get avec Oui / Non, parite slash / prefixe.
Vraie bibliotheque discord.py (vues, boutons, menus, modales) ; interactions simulees.

Usage : python3 tests/test_panel_get.py
"""
import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path

import discord
from discord.ext import commands

SUITE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE.parent))
sys.path.insert(0, str(SUITE))
TMP = tempfile.mkdtemp(prefix="panel_data_")
os.environ["DEOBF_DATA_DIR"] = TMP                                   # reglages et statistiques de test isoles
os.environ.pop("DEOBF_ALLOWED_IDS", None)
os.environ["DEOBF_DECIDE"] = "1"

import settings_store as SS  # noqa: E402
import stats_store as ST  # noqa: E402
from yslem_deobf_suite.cogs import panel_cog as P, tools_cog as L, deobf_cog  # noqa: E402
import prefix_manager as PM  # noqa: E402

FAILS = []
OWNER, STRANGER, ADMIN = 111, 222, 333


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label, flush=True)
    if not cond:
        FAILS.append(label)


# ── faux Discord minimal mais utilisant les VRAIS objets discord.ui ─────────────────────────────────────────────────
class FakeMsg:
    _n = 0

    def __init__(self, embed=None, view=None, content=None):
        FakeMsg._n += 1
        self.id, self.embed, self.view, self.content, self.edits = FakeMsg._n, embed, view, content, []
        self.deleted = False

    async def edit(self, embed=None, view=discord.utils.MISSING, content=discord.utils.MISSING, **kw):
        self.edits.append({"embed": embed, "view": view})
        if embed is not None:
            self.embed = embed
        if view is not discord.utils.MISSING:
            self.view = view

    async def delete(self):
        self.deleted = True


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, embed=None, files=None, view=None, **kw):
        m = FakeMsg(embed, view, content)
        m.files = {f.filename: f.fp.read() for f in (files or [])}
        self.sent.append(m)
        return m


class FakeResponse:
    def __init__(self, inter):
        self.inter, self.done, self.modal, self.kind = inter, False, None, None

    def is_done(self):
        return self.done

    async def defer(self, **kw):
        self.done = True
        self.kind = "defer"

    async def send_message(self, content=None, embed=None, view=None, ephemeral=False, **kw):
        self.done = True
        self.kind = "send"
        self.inter.sent.append({"content": content, "embed": embed, "view": view, "ephemeral": ephemeral})
        self.inter._orig = FakeMsg(embed, view, content)

    async def edit_message(self, content=None, embed=None, view=discord.utils.MISSING, **kw):
        self.done = True
        self.kind = "edit"
        self.inter.edited.append({"content": content, "embed": embed, "view": view})
        if self.inter.message is not None and embed is not None:
            self.inter.message.embed = embed
            if view is not discord.utils.MISSING:
                self.inter.message.view = view

    async def send_modal(self, modal):
        self.done = True
        self.kind = "modal"
        self.modal = modal


class FakeFollowup:
    def __init__(self, inter):
        self.inter = inter

    async def send(self, content=None, embed=None, view=None, ephemeral=False, wait=False, files=None, **kw):
        m = FakeMsg(embed, view, content)
        self.inter.sent.append({"content": content, "embed": embed, "view": view, "ephemeral": ephemeral})
        self.inter.followups.append(m)
        return m


class FakeClient:
    def __init__(self):
        self.user = types.SimpleNamespace(id=999)
        self.cogs = {}

    async def is_owner(self, user):
        return user.id == OWNER

    def get_cog(self, name):
        return self.cogs.get(name)


class FakeMember:
    def __init__(self, uid, manage=False):
        self.id, self.mention = uid, f"<@{uid}>"
        self.guild_permissions = types.SimpleNamespace(manage_guild=manage, administrator=False)


class FakeGuild:
    id = 4242
    name = "Serveur test"


class FakeInteraction:
    def __init__(self, user, guild=FakeGuild, data=None, message=None, channel=None):
        self.user, self.guild, self.data, self.message = user, guild, data or {}, message
        self.client = FakeClient()
        self.channel = channel or FakeChannel()
        self.channel_id = 55
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)
        self.sent, self.edited, self.followups, self._orig = [], [], [], None

    async def original_response(self):
        return self._orig

    async def edit_original_response(self, **kw):
        self.edited.append(kw)
        if self.message is not None and kw.get("embed") is not None:
            self.message.embed = kw["embed"]

    async def delete_original_response(self):
        pass


def txt(embed):
    if embed is None:
        return ""
    d = embed.to_dict()
    return "\n".join([d.get("title", ""), d.get("description", "")] + [f"{f['name']} {f['value']}" for f in d.get("fields", [])]
                     + [(d.get("footer") or {}).get("text", "")])


async def main() -> None:
    bot = commands.Bot(command_prefix=commands.when_mentioned_or("."), intents=discord.Intents.none())
    bot._connection.user = types.SimpleNamespace(id=999)           # bot « connecte » : necessaire a la mention
    store = SS.reset_store_for_tests(Path(TMP) / "settings.json")
    ST.reset_stats_for_tests(Path(TMP) / "stats.json")
    mgr = PM.install(bot, store)
    cog = P.PanelCog(bot)
    await bot.add_cog(cog)

    # ═══ 1. prefixes dynamiques ════════════════════════════════════════════════════════════════════════════════════════
    msg_g = types.SimpleNamespace(guild=FakeGuild, author=FakeMember(STRANGER), content="")
    msg_dm = types.SimpleNamespace(guild=None, author=FakeMember(STRANGER), content="")
    pre = await bot.get_prefix(msg_g)
    check("." in pre, f"prefixe par defaut du bot conserve ({pre})")
    store.add_prefix(FakeGuild.id, "!", ["."])
    pre = await bot.get_prefix(msg_g)
    check("!" in pre and "." in pre, f"prefixe ajoute pour le serveur : actifs {pre}")
    pre_dm = await bot.get_prefix(msg_dm)
    check("!" not in pre_dm and "." in pre_dm, "en MP : prefixes par defaut seulement (pas ceux du serveur)")
    other = types.SimpleNamespace(guild=types.SimpleNamespace(id=1), author=FakeMember(1), content="")
    check("!" not in await bot.get_prefix(other), "un autre serveur n'est pas touche")
    check(await mgr.active(bot, FakeGuild.id) == ([".", "!"], True), "affichage : prefixes actifs + « personnalises »")
    check(await mgr.defaults(bot) == ["."], "affichage : prefixes par defaut du bot (sans la mention)")
    store.reset_prefixes(FakeGuild.id)
    check(await mgr.active(bot, FakeGuild.id) == (["."], False), "reinitialisation : retour au defaut")

    # ═══ 2. panneau des prefixes (vraies vues, boutons, menus, modales) ═══════════════════════════════════════════════
    admin = FakeMember(ADMIN, manage=True)
    i = FakeInteraction(admin)
    await P.show_prefixes(i, bot)
    view = i._orig.view
    check(isinstance(view, P.PrefixView) and view.editable, "panneau prefixes : ouvert, modifiable avec « Gerer le serveur »")
    check("`.`" in txt(i._orig.embed) and "par défaut" in txt(i._orig.embed), "panneau : affiche les prefixes actifs et leur origine")
    check(i.sent[0]["ephemeral"] is True, "panneau prive (ephemere) par defaut")
    # ajouter via la modale
    i2 = FakeInteraction(admin, message=i._orig)
    view.message = i._orig
    await view.add.callback(i2)
    modal = i2.response.modal
    check(isinstance(modal, discord.ui.Modal) and modal.title.startswith("Add"), "bouton Ajouter : ouvre une fenetre modale")
    modal.value._value = "?"                                   # ce que l'utilisateur tape
    i3 = FakeInteraction(admin, message=i._orig)
    await modal.on_submit(i3)
    check(store.prefixes(FakeGuild.id) == [".", "?"], "modale : le prefixe est ajoute et SAUVEGARDE")
    check("`?`" in txt(i._orig.embed) or "`?`" in txt(i._orig.edits[-1]["embed"] if hasattr(i._orig, "edits") and i._orig.edits else None),
          "le panneau est mis a jour avec le nouveau prefixe")
    # doublon / invalide : message d'erreur, rien de sauvegarde
    for bad, label in (("?", "doublon"), ("a b", "espace"), ("/", "slash")):
        modal2 = (await _open_add(view, admin, i._orig))
        modal2.value._value = bad
        i4 = FakeInteraction(admin, message=i._orig)
        await modal2.on_submit(i4)
        check(store.prefixes(FakeGuild.id) == [".", "?"] and i4.sent and "❌" in (i4.sent[0]["content"] or ""), f"{label} refuse avec un message, rien de modifie")
    # modifier
    i5 = FakeInteraction(admin, message=i._orig)
    await view.edit.callback(i5)
    picker_view = i5.sent[0]["view"]
    sel = picker_view.children[0]
    i6 = FakeInteraction(admin, data={"values": ["?"]}, message=i._orig)
    await sel.callback(i6)
    m2 = i6.response.modal
    check(m2 is not None and m2.value.default == "?", "modifier : menu deroulant puis modale pre-remplie")
    m2.value._value = "$"
    await m2.on_submit(FakeInteraction(admin, message=i._orig))
    check(store.prefixes(FakeGuild.id) == [".", "$"], "modification sauvegardee")
    # supprimer
    i7 = FakeInteraction(admin, message=i._orig)
    await view.remove.callback(i7)
    sel2 = i7.sent[0]["view"].children[0]
    await sel2.callback(FakeInteraction(admin, data={"values": ["$"]}, message=i._orig))
    check(store.prefixes(FakeGuild.id) == ["."], "suppression sauvegardee")
    # reinitialiser
    await view.reset.callback(FakeInteraction(admin, message=i._orig))
    check(store.prefixes(FakeGuild.id) is None, "reinitialisation : prefixes par defaut restaures")
    # persistance apres redemarrage
    store.add_prefix(FakeGuild.id, "%", ["."])
    check(SS.SettingsStore(Path(TMP) / "settings.json").prefixes(FakeGuild.id) == [".", "%"], "persistance apres redemarrage du bot")
    store.reset_prefixes(FakeGuild.id)
    # droits : un membre sans « Gerer le serveur » est en lecture seule
    plain = FakeMember(STRANGER)
    i8 = FakeInteraction(plain)
    await P.show_prefixes(i8, bot)
    v2 = i8._orig.view
    check(not v2.editable and all(c.disabled for c in v2.children if getattr(c, "custom_id", "") != "back"), "sans permission : boutons desactives (lecture seule)")
    # seul le proprietaire du panneau s'en sert
    i9 = FakeInteraction(FakeMember(777))
    check(not await view.interaction_check(i9) and i9.sent, "le panneau d'un autre utilisateur est refuse")
    # en MP : pas de reglage par serveur
    i10 = FakeInteraction(plain, guild=None)
    await P.show_prefixes(i10, bot)
    check("par serveur" in txt(i10._orig.embed), "en MP : explication, pas de reglage")

    # ═══ 3. tableau de bord /panel ═══════════════════════════════════════════════════════════════════════════════════
    i = FakeInteraction(FakeMember(OWNER))
    await cog.panel_flow(i)
    main = i._orig.view
    check(isinstance(main, P.MainView) and "Dashboard" in txt(i._orig.embed), "/panel : menu principal")
    opts = [o.value for o in main.children[0].options]
    check(opts == ["prefix", "deobf", "engines", "stats", "settings"], f"menu : 5 panneaux ({opts})")
    for key, expect in (("deobf", "Deobfuscation"), ("engines", "Obfuscator supported"), ("stats", "Statistics"), ("settings", "Settings")):
        ii = FakeInteraction(FakeMember(OWNER, manage=True), data={"values": [key]}, message=i._orig)
        main.message = i._orig
        await main._open(ii)
        check(ii.edited and expect in txt(ii.edited[0]["embed"]), f"menu -> panneau « {expect} »")
        main = P.MainView(bot, cog, OWNER)
    # statistiques reservees
    ii = FakeInteraction(FakeMember(STRANGER), data={"values": ["stats"]}, message=i._orig)
    await P.MainView(bot, cog, STRANGER)._open(ii)
    check(not ii.edited and ii.sent and "réservées" in (ii.sent[0]["content"] or ""), "statistiques : refusees a un utilisateur non autorise")
    # moteurs : detail
    infos = await asyncio.to_thread(P._engines_info)
    ev = P.EnginesView(bot, OWNER, infos)
    ii = FakeInteraction(FakeMember(OWNER), data={"values": ["wearedevs"]})
    await ev._detail(ii)
    check(ii.sent and "WeAreDevs" in txt(ii.sent[0]["embed"]), "panneau Moteurs : detail d'un moteur")
    check(any(inf["name"] == "centurion_v6" and not inf["ok"] for inf in infos), "panneau Moteurs : Centurion presente comme indisponible")
    # parametres : bascule + persistance
    sv = P.SettingsView(bot, OWNER, FakeGuild.id, True)
    ii = FakeInteraction(FakeMember(OWNER, manage=True))
    await sv.mention_result.callback(ii)
    check(store.option(FakeGuild.id, "mention_result") is False and "désactivé" in txt(ii.edited[0]["embed"]), "parametres : bascule « mention du resultat » (sauvegardee)")
    store.reset_options(FakeGuild.id)

    # ═══ 4. .get : recuperation, analyse, Oui / Non ═══════════════════════════════════════════════════════════════════
    sample = (SUITE / "tests" / "samples" / "legaxyobf.lua").read_bytes()
    fetched = {}

    async def fake_fetch(url, info=None, cache=False):
        info = info if info is not None else {}
        info.update(status=200, redirects=["cdn.example.org"], final_url=url, content_type="text/plain")
        if "vide" in url:
            raise ValueError("Reponse vide")
        if "404" in url:
            info["status"] = 404
            raise ValueError("Serveur a répondu 404")
        if "interne" in url:
            raise OSError("SSRF: aucune adresse publique")
        if "html" in url:
            return "page.lua", b"<!DOCTYPE html><html><head><title>Not Found</title></head><body>x</body></html>"
        if "luarmor" in url:
            return "l.lua", b'getgenv().script_key="x"\nloadstring(game:HttpGet("https://api.luarmor.net/files/v3/loaders/a.lua"))()'
        if "luraph" in url:
            return "lu.lua", b"-- This file was protected using Luraph Obfuscator v14.4 [https://lura.ph/]\nreturn(function(...)end)()"
        return "legaxy.lua", sample

    real_fetch = P._fetch_url
    P._fetch_url = fake_fetch
    ran = []

    async def fake_run_items(interaction, items, moteur, timeout, force):
        ran.append((items[0][0], len(items[0][1]), moteur))

    real_run = P.run_items
    P.run_items = fake_run_items
    try:
        # slash et prefixe : MEME fonction, MEME interface
        i = FakeInteraction(FakeMember(OWNER))
        await cog.get_flow(i, url="https://x/legaxy.lua")
        msg = i.followups[0] if i.followups else i._orig
        check(isinstance(msg.view, P.ConfirmView), ".get : analyse + boutons Oui / Non pour un obfuscateur pris en charge")
        t = txt(msg.embed)
        check("legaxyobf" in t.lower() and "pris en charge" in t and "Lua" in t, f".get : fichier, protection et statut affiches\n{t}")
        check("redirigé" in t and "cdn.example.org" in t, ".get : redirection HTTP signalee")
        labels = [c.label for c in msg.view.children]
        check(labels == ["Yes", "No"], f"boutons : {labels}")
        # Non : rien n'est lance, l'analyse est conservee
        v = msg.view
        ino = FakeInteraction(FakeMember(OWNER), message=msg)
        await v.no.callback(ino)
        check(not ran and ino.edited and ino.edited[0]["view"] is None and "annulée" in txt(ino.edited[0]["embed"]) and "legaxyobf" in txt(ino.edited[0]["embed"]).lower(),
              "Non : annule, retire les boutons, CONSERVE l'analyse")
        # Oui
        i = FakeInteraction(FakeMember(OWNER))
        await cog.get_flow(i, url="https://x/legaxy.lua")
        msg = i.followups[0]
        iy = FakeInteraction(FakeMember(OWNER), message=msg)
        await msg.view.yes.callback(iy)
        check(ran == [("legaxy.lua", len(sample), "auto")], f"Oui : deobfuscation lancee avec le moteur automatique ({ran})")
        check(iy.edited and iy.edited[0]["view"] is None, "Oui : boutons retires")
        # Oui par quelqu'un qui n'a pas le droit
        ran.clear()
        i = FakeInteraction(FakeMember(OWNER))
        await cog.get_flow(i, url="https://x/legaxy.lua")
        msg = i.followups[0]
        ino = FakeInteraction(FakeMember(STRANGER), message=msg)
        await msg.view.yes.callback(ino)
        check(not ran and ino.sent and "reservee" in (ino.sent[0]["content"] or "").lower(), "Oui sans autorisation : refuse, rien de lance")
        # un autre utilisateur ne peut pas cliquer
        check(not await msg.view.interaction_check(FakeInteraction(FakeMember(777))), "les boutons ne sont utilisables que par celui qui a lance .get")
        # expiration
        msg.view.message = msg
        await msg.view.on_timeout()
        check(msg.edits and msg.edits[-1]["view"] is None and "délai" in txt(msg.edits[-1]["embed"]), "expiration : boutons retires, rien de lance")
        # non pris en charge : pas de boutons
        for url, expect in (("https://x/luraph", "non pris en charge"), ("https://x/luarmor", "Luarmor")):
            i = FakeInteraction(FakeMember(OWNER))
            await cog.get_flow(i, url=url)
            m = i.followups[0] if i.followups else i._orig
            t = txt(m.embed)
            check(m.view is None and expect in t, f".get {url.split('/')[-1]} : pas de boutons, « {expect} » affiche")
        check("clé" in t and "non contourné" in t, ".get Luarmor : cle requise signalee, aucune protection contournee")
        # erreurs HTTP / contenu
        for url, expect in (("https://x/vide", "réponse vide"), ("https://x/404", "404"), ("https://x/interne", "refusée"), ("https://x/html", "HTML")):
            i = FakeInteraction(FakeMember(OWNER))
            await cog.get_flow(i, url=url)
            m = i.followups[0] if i.followups else i._orig
            check(m.view is None and expect in txt(m.embed), f".get {url.split('/')[-1]} : message court « {expect} », pas de boutons")
        # sans argument
        i = FakeInteraction(FakeMember(OWNER))
        await cog.get_flow(i)
        check(i.sent and "lien" in (i.sent[0]["content"] or ""), ".get sans argument : aide courte")
    finally:
        P._fetch_url = real_fetch
        P.run_items = real_run

    # ═══ 5. statistiques et anti-spam ═══════════════════════════════════════════════════════════════════════════════
    sn = ST.stats().snapshot()
    check(sn["gets"] >= 5 and sn["users"] >= 1, f"statistiques : les .get sont comptes ({sn['gets']})")
    i = FakeInteraction(FakeMember(OWNER))
    await cog.stats_flow(i)
    check(isinstance(i._orig.view, P.StatsView) and "Statistiques" in txt(i._orig.embed), "/stats : panneau pour le proprietaire")
    i = FakeInteraction(FakeMember(STRANGER))
    await cog.stats_flow(i)
    check(i.sent and "reservee" in (i.sent[0]["content"] or "").lower() and not isinstance(getattr(i._orig, "view", None), P.StatsView), "/stats : refuse a un inconnu")
    P._GUARD = None
    blocked = 0
    for _ in range(12):
        i = FakeInteraction(FakeMember(555))
        await cog.panel_flow(i)
        if i.sent and "Trop de commandes" in (i.sent[0]["content"] or ""):
            blocked += 1
    check(blocked >= 5, f"anti-spam : {blocked} /panel refuses sur 12 pour un utilisateur ordinaire")
    P._GUARD = None

    # ═══ 6. PARITE : la commande a prefixe appelle la MEME fonction -> meme interface que la commande slash ═══════════
    P.install_prefix_commands(bot)

    class FakeCtx:
        def __init__(self, user, guild=FakeGuild):
            self.author, self.guild, self.bot = user, guild, bot
            self.channel = FakeChannel()
            self.message = types.SimpleNamespace(attachments=[])
            self.replies = []

        async def reply(self, content=None, embed=None, view=None, **kw):
            m = FakeMsg(embed, view, content)
            self.replies.append(m)
            return m

    P._fetch_url = fake_fetch
    P.run_items = fake_run_items
    ran.clear()
    try:
        slash = FakeInteraction(FakeMember(OWNER))
        await cog.get_flow(slash, url="https://x/legaxy.lua")
        sm = slash.followups[0]
        ctx = FakeCtx(FakeMember(OWNER))
        await bot.get_command("get").callback(ctx, "https://x/legaxy.lua")
        pm = ctx.replies[-1]
        check(isinstance(pm.view, P.ConfirmView) and [c.label for c in pm.view.children] == ["Yes", "No"], "parite .get : memes boutons Oui / Non")
        same = lambda a, b: "\n".join(x for x in txt(a).splitlines() if not x.startswith(("🔎",))) == "\n".join(x for x in txt(b).splitlines() if not x.startswith(("🔎",)))   # noqa: E731
        check(txt(sm.embed).split("\n")[1:] == txt(pm.embed).split("\n")[1:] or same(sm.embed, pm.embed), "parite .get : meme analyse affichee que /get")
        iy = FakeInteraction(FakeMember(OWNER), message=pm)
        await pm.view.yes.callback(iy)
        check(ran and ran[-1][0] == "legaxy.lua", "parite .get : « Oui » lance la deobfuscation comme avec /get")
        for name in ("panel", "prefix"):
            ctx = FakeCtx(FakeMember(OWNER, manage=True))
            await bot.get_command(name).callback(ctx)
            ref = FakeInteraction(FakeMember(OWNER, manage=True))
            await (cog.panel_flow(ref) if name == "panel" else cog.prefix_flow(ref))
            check(ctx.replies and type(ctx.replies[0].view) is type(ref._orig.view) and txt(ctx.replies[0].embed) == txt(ref._orig.embed),
                  f"parite .{name} : meme vue et meme embed que /{name}")
        ctx = FakeCtx(FakeMember(STRANGER))
        await bot.get_command("stats").callback(ctx)
        check(ctx.replies and "reservee" in (ctx.replies[0].content or "").lower(), "parite .stats : meme refus qu'avec /stats")
        ctx = FakeCtx(FakeMember(STRANGER))
        await bot.get_command("process").callback(ctx, "https://x/legaxy.lua")
        check(ctx.replies and "reservee" in (ctx.replies[0].content or "").lower(), "parite .process : reserve au proprietaire comme /process")
    finally:
        P._fetch_url = real_fetch
        P.run_items = real_run
    await bot.close()


async def _open_add(view, user, message):
    i = FakeInteraction(user, message=message)
    await view.add.callback(i)
    return i.response.modal


asyncio.run(main())
print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : prefixes, panneaux et .get (Oui/Non)")
