"""
mock_discord.py -- faux serveur HTTP de l'API Discord pour tester le code du bot avec la VRAIE bibliotheque
discord.py (creation de MP, envoi multipart de fichiers, reponses d'interaction, jetons expires, 403/429/500).

    server = MockDiscord(); await server.start(); ...; await server.stop()
    bot, make_interaction = await make_bot(server)

Aucune connexion a discord.com : discord.http.Route.BASE est redirige vers 127.0.0.1.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time
from typing import Optional

import aiohttp
from aiohttp import web
import discord
from discord import http as dhttp
from discord.ext import commands

BOT_ID = "999000000000000001"
USER_ID = "111000000000000001"
APP_ID = BOT_ID

_ids = itertools.count(5_000_000_000_000_000)


def _snow() -> str:
    return str(next(_ids))


def _user_json(uid: str, name: str, bot: bool = False) -> dict:
    return {"id": uid, "username": name, "discriminator": "0", "avatar": None, "global_name": name, "bot": bot}


def jr(data, status: int = 200, headers: Optional[dict] = None) -> web.Response:
    """Reponse JSON avec l'en-tete EXACT « application/json » (discord.py compare l'egalite stricte, sans charset)."""
    return web.Response(body=json.dumps(data).encode(), status=status, headers=headers or {}, content_type="application/json")


class MockDiscord:
    def __init__(self) -> None:
        self.dm_script: list = []            # un element par envoi de MP : None = ok, (status, code, message) = erreur
        self.webhook_expired = False         # jeton d'interaction expire : tous les webhooks -> 401
        self.dm_messages: list[dict] = []    # {"content", "files": {nom: octets}}
        self.channel_script: list = []       # erreurs a renvoyer pour l'envoi dans le SALON (comme dm_script pour les MP)
        self.channel_messages: list[dict] = []   # messages postes dans le salon 55 : {"id","content","files"}
        self.edits: list[dict] = []          # modifications de messages : {"id","content"}
        self.deleted: list[str] = []
        self.edit_script: list = []          # erreurs a renvoyer pour les modifications de messages (PATCH)
        self.followups: list[dict] = []
        self.callbacks: list[str] = []
        self.cdn: dict[str, bytes] = {}
        self.rate_limited_once = False
        self._runner: Optional[web.AppRunner] = None
        self.port = 0

    # ------------------------------------------------------------------ HTTP
    @staticmethod
    def _embed_text(payload: dict) -> str:
        parts = []
        for e in payload.get("embeds") or []:
            parts += [e.get("title", ""), e.get("description", "")]
            parts += [f"{f['name']} {f['value']}" for f in e.get("fields", [])]
            parts += [(e.get("footer") or {}).get("text", "")]
        return "\n".join(p for p in parts if p)

    async def _read_message(self, request: web.Request) -> dict:
        content, payload, files = None, {}, {}
        if request.content_type.startswith("multipart/"):
            reader = await request.multipart()
            async for part in reader:
                if part.name == "payload_json":
                    payload = json.loads((await part.read()).decode())
                    content = payload.get("content")
                elif part.filename:
                    files[part.filename] = bytes(await part.read())
        else:
            payload = await request.json()
            content = payload.get("content")
        emb = self._embed_text(payload)
        if emb:                                  # le texte des embeds est ajoute au contenu enregistre (les tests lisent « content »)
            content = ((content + "\n") if content else "") + emb
        return {"content": content, "payload": payload, "files": files}

    @staticmethod
    def _message_json(channel_id: str, msg: dict, flags: int = 0) -> dict:
        return {
            "id": _snow(), "channel_id": channel_id, "author": _user_json(BOT_ID, "bot", True),
            "content": msg["content"] or "", "timestamp": "2026-11-01T00:00:00.000000+00:00", "edited_timestamp": None,
            "tts": False, "mention_everyone": False, "mentions": [], "mention_roles": [], "pinned": False, "type": 0,
            "flags": flags, "embeds": [],
            "attachments": [{"id": _snow(), "filename": n, "size": len(b), "url": f"http://x/{n}", "proxy_url": f"http://x/{n}"}
                            for n, b in msg["files"].items()],
        }

    async def h_login(self, request):                                   # GET /users/@me
        return jr(_user_json(BOT_ID, "bot", True))

    async def h_appinfo(self, request):                                 # GET /oauth2/applications/@me
        return jr({"id": APP_ID, "name": "bot", "description": "", "bot_public": True, "bot_require_code_grant": False,
                   "verify_key": "00", "flags": 0, "icon": None, "owner": _user_json(USER_ID, "owner"),
                   "team": None, "summary": ""})

    async def h_create_dm(self, request):                               # POST /users/@me/channels
        body = await request.json()
        return jr({"id": "777000000000000001", "type": 1,
                                  "recipients": [_user_json(str(body["recipient_id"]), "owner")]})

    async def h_channel_message(self, request):                         # POST /channels/{id}/messages
        msg = await self._read_message(request)
        is_dm = request.match_info["cid"] == "777000000000000001"
        script = self.dm_script if is_dm else self.channel_script
        if script:
            err = script.pop(0)
            if err is not None:
                status, code, text = err
                headers = {"Retry-After": "1"} if status == 429 else {}
                body = {"message": text, "code": code}
                if status == 429:
                    body.update({"retry_after": 0.2, "global": False})
                return jr(body, status=status, headers=headers)
        out = self._message_json(request.match_info["cid"], msg)
        if is_dm:
            self.dm_messages.append({"content": msg["content"], "files": msg["files"]})
        else:
            self.channel_messages.append({"id": out["id"], "content": msg["content"], "files": msg["files"]})
        return jr(out)

    async def h_edit(self, request):                                    # PATCH /channels/{cid}/messages/{mid} ou webhook
        msg = await self._read_message(request)
        if self.edit_script:
            err = self.edit_script.pop(0)
            if err is not None:
                status, code, text = err
                return jr({"message": text, "code": code}, status=status)
        if "token" in request.match_info and self.webhook_expired:
            return jr({"message": "Invalid Webhook Token", "code": 50027}, status=401)
        self.edits.append({"id": request.match_info["mid"], "content": msg["content"]})
        out = self._message_json(request.match_info.get("cid", "55"), msg)
        out["id"] = request.match_info["mid"]
        return jr(out)

    async def h_delete_original(self, request):                       # DELETE /webhooks/{app}/{token}/messages/@original
        self.deleted.append("@original")
        return web.Response(status=204)

    async def h_delete(self, request):
        self.deleted.append(request.match_info["mid"])
        return web.Response(status=204)

    async def h_webhook(self, request):                                 # POST /webhooks/{app}/{token}
        if self.webhook_expired:
            return jr({"message": "Invalid Webhook Token", "code": 50027}, status=401)
        msg = await self._read_message(request)
        self.followups.append({"content": msg["content"], "files": msg["files"],
                               "flags": msg["payload"].get("flags", 0), "embeds": msg["payload"].get("embeds", [])})
        return jr(self._message_json("55", msg, flags=msg["payload"].get("flags", 0)))

    async def h_callback(self, request):                                # POST /interactions/{id}/{token}/callback
        body = await request.json()
        self.callbacks.append(f"type={body.get('type')}")
        if request.query.get("with_response"):                           # discord.py >= 2.5
            return jr({"interaction": {"id": request.match_info["iid"], "type": 2, "activity_instance_id": None,
                                       "response_message_id": None, "response_message_loading": True,
                                       "response_message_ephemeral": bool((body.get("data") or {}).get("flags", 0) & 64)},
                       "resource": {"type": body.get("type"), "activity_instance": None, "message": None}})
        return web.Response(status=204)

    async def h_cdn(self, request):
        data = self.cdn.get(request.match_info["name"])
        return web.Response(body=data) if data is not None else web.Response(status=404)

    async def start(self) -> None:
        app = web.Application(client_max_size=64 * 1024 * 1024)
        app.add_routes([
            web.get("/api/v10/users/@me", self.h_login),
            web.get("/api/v10/oauth2/applications/@me", self.h_appinfo),
            web.post("/api/v10/users/@me/channels", self.h_create_dm),
            web.post("/api/v10/channels/{cid}/messages", self.h_channel_message),
            web.post("/api/v10/webhooks/{app}/{token}", self.h_webhook),
            web.patch("/api/v10/channels/{cid}/messages/{mid}", self.h_edit),
            web.delete("/api/v10/channels/{cid}/messages/{mid}", self.h_delete),
            web.delete("/api/v10/webhooks/{app}/{token}/messages/@original", self.h_delete_original),
            web.patch("/api/v10/webhooks/{app}/{token}/messages/{mid}", self.h_edit),
            web.post("/api/v10/interactions/{iid}/{token}/callback", self.h_callback),
            web.get("/cdn/{name}", self.h_cdn),
        ])
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        dhttp.Route.BASE = f"http://127.0.0.1:{self.port}/api/v10"

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    # --------------------------------------------------------------- objets discord.py reels
    def attachment(self, bot: commands.Bot, filename: str, data: bytes) -> discord.Attachment:
        self.cdn[filename] = data
        url = f"http://127.0.0.1:{self.port}/cdn/{filename}"
        return discord.Attachment(data={"id": _snow(), "filename": filename, "size": len(data), "url": url,
                                        "proxy_url": url, "content_type": "text/plain"}, state=bot._connection)


async def make_bot(server: MockDiscord) -> tuple[commands.Bot, callable]:
    """Un vrai commands.Bot connecte (login HTTP seulement) au faux serveur, et une fabrique d'interactions reelles."""
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none(), application_id=int(APP_ID))
    await bot.login("A" * 24 + "." + "B" * 6 + "." + "C" * 27)

    def make_interaction(user_id: str = USER_ID, name: str = "process", guild: bool = True) -> discord.Interaction:
        """Interaction REELLE telle que Discord l'envoie : en serveur (member + guild_id + channel) ou en MP."""
        payload = {
            "id": _snow(), "application_id": APP_ID, "type": 2, "token": "tok" + _snow(), "version": 1,
            "locale": "fr", "app_permissions": "0", "entitlements": [], "authorizing_integration_owners": {},
            "context": 0, "attachment_size_limit": 10485760,
            "data": {"id": _snow(), "name": name, "type": 1},
        }
        if guild:
            payload.update({
                "guild_id": "88", "guild": {"id": "88", "locale": "fr", "features": []},
                "channel": {"id": "55", "type": 0, "name": "general", "guild_id": "88", "permissions": "8", "position": 0, "nsfw": False,
                            "topic": None, "rate_limit_per_user": 0, "parent_id": None, "last_message_id": None, "flags": 0},
                "channel_id": "55", "member": {"user": _user_json(user_id, "owner"), "roles": [], "nick": None,
                                                "joined_at": "2024-01-01T00:00:00.000000+00:00", "permissions": "8",
                                                "flags": 0, "deaf": False, "mute": False},
            })
        else:
            payload.update({"channel": {"id": "777000000000000001", "type": 1, "recipients": [_user_json(user_id, "owner")]},
                            "channel_id": "777000000000000001", "user": _user_json(user_id, "owner")})
        return discord.Interaction(data=payload, state=bot._connection)

    return bot, make_interaction
