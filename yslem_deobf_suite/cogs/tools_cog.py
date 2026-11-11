"""
tools_cog.py -- /analyse (public) et /process (proprietaire), plus tout ce que partagent les deux cogs.

  /analyse  (public, cooldown 20 s)
      Triage d'un script Lua/Luau : heuristiques statiques (entropie, bannieres d'obfuscateurs, signaux de
      VM, chaines suspectes en clair, signatures connues) + trace de comportement dans le bac a sable
      lua_sandbox.py (Luau patche ; fichiers <= 384 Ko). Les jetons de webhook sont masques.
      Avertissement affiche : analyse automatisee, pas une preuve d'innocuite.

  /process  [proprietaire / allowed_ids.txt -- owner_only(), un vrai app_commands.check]
      Deobfuscation via deobf_router.py (detection automatique + bon moteur) : meme code que /deobf
      (run_job) et que `python3 deobf_router.py run`. Suivi en direct + resultat dans le SALON de la commande.

Protection reseau (les deux commandes) :
  - IP litterale dans l'URL bloquee avant connexion ; noms d'hotes resolus via un resolveur qui refuse les IP
    privees/loopback/cloud au moment de la connexion (pas de fenetre DNS-rebinding) ; ports sensibles refuses ;
    redirections re-verifiees a chaque saut ; telechargement par blocs, plafonne a 7 Mo.

Aucun prerequis a installer : voir bootstrap.py (Node.js + Luau patche prepares automatiquement).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import ipaddress
import json
import math
import os
import re
import shutil
import socket
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from yarl import URL


_ALLOWED_ENV = "DEOBF_ALLOWED_IDS"      # ex. "123456789012345678, 987654321098765432"
_ALLOW_GUILD_ADMINS_ENV = "DEOBF_ALLOW_GUILD_ADMINS"   # "1" : les administrateurs du serveur sont aussi acceptes


def _allowed_ids() -> set[int]:
    """ID Discord autorises EN PLUS du proprietaire de l'application : variable d'environnement
    DEOBF_ALLOWED_IDS et/ou fichier allowed_ids.txt (un ID par ligne, # = commentaire) dans le dossier
    de la suite. Relu a chaque appel : on peut l'editer sans redemarrer le bot."""
    ids: set[int] = set()
    raw = os.environ.get(_ALLOWED_ENV, "")
    try:
        f = _find_suite() / "allowed_ids.txt"
        if f.is_file():
            raw += "\n" + f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    for line in raw.splitlines():
        for tok in re.split(r"[,\s;]+", line.split("#", 1)[0]):
            if tok.isdigit():
                ids.add(int(tok))
    return ids


async def is_authorized(interaction: discord.Interaction) -> bool:
    """Proprietaire de l'application (ou membre de son equipe), ID liste dans DEOBF_ALLOWED_IDS /
    allowed_ids.txt, et -- seulement si DEOBF_ALLOW_GUILD_ADMINS=1 -- administrateur du serveur."""
    user = interaction.user
    if user.id in _allowed_ids():
        return True
    is_owner = getattr(interaction.client, "is_owner", None)
    if is_owner is not None:
        try:
            if await is_owner(user):
                return True
        except Exception:  # noqa: BLE001 - API Discord indisponible : on retombe sur les autres regles
            pass
    guild = getattr(interaction, "guild", None)
    user_roles = getattr(user, "roles", None)
    if guild is not None and user_roles:
        try:
            from yslem_deobf_suite import settings_store
        except ImportError:
            try:
                import settings_store  # type: ignore
            except ImportError:
                settings_store = None
        if settings_store is not None:
            allowed_roles = set(settings_store.store().deobf_roles(guild.id))
            if allowed_roles and any(r.id in allowed_roles for r in user_roles):
                return True
    if os.environ.get(_ALLOW_GUILD_ADMINS_ENV) == "1":
        perms = getattr(user, "guild_permissions", None)
        if interaction.guild is not None and perms is not None and perms.administrator:
            return True
    return False


def owner_only():
    """Vrai garde-fou « proprietaire / administrateurs autorises » pour une commande SLASH.

    IMPORTANT : le decorateur is_owner() du framework de commandes prefixees pose sur une commande
    `app_commands` n'est PAS applique par discord.py (il ne remplit que `__commands_checks__`, que seules
    les commandes prefixees lisent : `cmd.checks == []`, verifie sur discord.py 2.7.1). N'importe qui
    pouvait donc lancer la commande. `app_commands.check` est le seul mecanisme reellement evalue pour les
    slash commands ; il leve `app_commands.CheckFailure` quand le predicat est faux.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        return await is_authorized(interaction)
    return app_commands.check(predicate)


NOT_AUTHORIZED_MSG = ("This command is reserved to the bot owner (or the IDs listed in allowed_ids.txt / "
                      "DEOBF_ALLOWED_IDS). Use /deobf_moi to see your ID.")

# ── configuration ─────────────────────────────────────────────────────────────

_MAX_BYTES         = 7 * 1024 * 1024   # 7 Mo — refus si plus grand
_SANDBOX_MAX_BYTES = 384 * 1024        # 384 Ko — au-delà, sandbox sautée
_SANDBOX_TIMEOUT   = 60                # secondes avant kill du sous-processus (demarrage de Node inclus)
_DOWNLOAD_TIMEOUT  = 30
_MAX_REDIRECTS     = 5
_COOLDOWN_SECS     = 20
_SCAN_HEAD         = 1_500_000         # analyse regex : debut + fin seulement (un fichier de 7 Mo
_SCAN_TAIL         = 400_000           # gelait la boucle d'evenements -> deconnexion de la gateway)
_DISCORD_MAX_UPLOAD = 8 * 1024 * 1024  # limite sure d'un serveur sans boost (cumul des pieces jointes)
_TOKEN_LIFETIME    = 14 * 60           # un jeton d'interaction expire apres 15 min
_MAX_CONCURRENT    = 3
_SEM_WAIT          = 5
_ANALYSE_DEADLINE  = 120               # secondes : echeance globale de /analyse (puis message explicite)
_IDENT_TIMEOUT     = 70                # secondes : identification de l'obfuscateur (detecteur local + avis du modele)

# ── livraison des resultats ────────────────────────────────────────────────────



def _pack_files(items: list[tuple[str, bytes]], limit: int = _DISCORD_MAX_UPLOAD) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Fait tenir les pieces jointes sous la limite Discord : compresse (gzip) les plus grosses, sinon les omet.
    Retourne (pieces, notes)."""
    import gzip
    out, notes = list(items), []
    if sum(len(b) for _, b in out) <= limit:
        return out, notes
    for i in sorted(range(len(out)), key=lambda k: -len(out[k][1])):
        if sum(len(b) for _, b in out) <= limit:
            break
        name, data = out[i]
        out[i] = (name + ".gz", gzip.compress(data, 9))
        notes.append(f"`{name}` compressed to gzip (too big for Discord)")
    while sum(len(b) for _, b in out) > limit and out:
        i = max(range(len(out)), key=lambda k: len(out[k][1]))
        notes.append(f"`{out[i][0]}` omitted ({len(out[i][1]) // 1024} KB, too big for Discord)")
        out.pop(i)
    return out, notes


async def _deliver(interaction: discord.Interaction, content: Optional[str] = None, *,
                   embed: Optional[discord.Embed] = None,
                   files: Optional[list[tuple[str, bytes]]] = None, ephemeral: bool = True) -> str:
    """Envoie la reponse finale d'un job. Un jeton d'interaction expire apres 15 minutes (or un job peut
    durer 25 min) : dans ce cas, ou si l'envoi echoue, repli en message prive a l'utilisateur.
    Retourne « followup », « dm » ou « echec »."""
    files, notes = _pack_files(files or [])
    if notes:
        content = (content or "") + "\n" + "\n".join(notes)

    def build():
        kw: dict = {}
        if content:
            kw["content"] = content[:1990]
        if embed is not None:
            kw["embed"] = embed
        if files:
            kw["files"] = [discord.File(io.BytesIO(b), filename=n) for n, b in files]
        return kw

    try:
        await interaction.followup.send(ephemeral=ephemeral, **build())
        return "followup"
    except (discord.HTTPException, discord.NotFound):
        pass
    try:
        await interaction.user.send(**build())
        return "dm"
    except Exception:  # noqa: BLE001 - DM fermes, etc.
        return "echec"



# ── envoi des resultats en MESSAGE PRIVE (fiable) ──────────────────────────────

_DM_ATTEMPTS = 4


async def _dm_send(user, *, content: Optional[str] = None,
                   files: Optional[list[tuple[str, bytes]]] = None) -> tuple[bool, str]:
    """Envoie un MP a `user`. Reessaie sur les erreurs transitoires (5xx, reseau, timeout) avec attente
    croissante ; ne reessaie PAS si les MP sont fermes (403) ou si la piece jointe est trop grosse (413).
    Retourne (ok, raison_si_echec). Les pieces jointes sont reconstruites a chaque tentative."""
    last = "inconnu"
    for attempt in range(_DM_ATTEMPTS):
        try:
            channel = user.dm_channel or await user.create_dm()
            kw: dict = {}
            if content:
                kw["content"] = content[:1990]
            if files:
                kw["files"] = [discord.File(io.BytesIO(b), filename=n) for n, b in files]
            await channel.send(**kw)
            return True, ""
        except discord.Forbidden:
            return False, "tes messages prives sont fermes (Parametres > Confidentialite : autoriser les MP des membres du serveur)"
        except discord.HTTPException as exc:
            last = f"HTTP {exc.status}: {getattr(exc, 'text', '') or exc}"
            if exc.status in (400, 413):          # requete invalide / fichier trop gros : inutile de reessayer
                return False, last
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(min(2 ** attempt, 15))
    return False, last


async def _notify(interaction: discord.Interaction, text: str) -> bool:
    """Message ephemere court sur l'interaction ; sans erreur si le jeton a expire (15 min)."""
    try:
        await interaction.followup.send(text[:1990], ephemeral=True)
        return True
    except (discord.HTTPException, discord.NotFound):
        return False


_KEEP_RESULTS = 20


def _save_result(name: str, data: bytes) -> Optional[Path]:
    """Copie du resultat sur disque (results/ de la suite) : filet de securite si l'envoi echoue.
    Garde les 20 plus recents."""
    try:
        d = _find_suite() / "results"
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.\-]", "_", name)[:60] or "result"
        path = d / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}"
        path.write_bytes(data)
        keep = [p for p in d.iterdir() if p.is_file() and p.name != "journal.json"]
        for old in sorted(keep, key=lambda p: p.stat().st_mtime, reverse=True)[_KEEP_RESULTS:]:
            try:
                old.unlink()
            except OSError:
                pass
        return path
    except OSError:
        return None


_WEBHOOK_MASK = re.compile(r"(https?://(?:[\w-]+\.)?discord(?:app)?\.com/api/webhooks/\d+/)[\w-]+", re.I)


def _mask_hooks(text: str) -> str:
    """Jeton de webhook -> *** (fonction a part : un backslash est interdit dans une f-string avant Python 3.12)."""
    return _WEBHOOK_MASK.sub(r"\1***", text)
_URL_FIND = re.compile(r"https?://[^\s\"'<>)\]]{6,}", re.I)
_DANGER_QUICK = [
    (re.compile(r"\bloadstring\s*\("), "loadstring (execution de code dynamique)"),
    (re.compile(r"\bgame:HttpGet\s*\(|\bHttpGetAsync\s*\("), "HttpGet (telechargement de code/donnees)"),
    (re.compile(r"\bsyn\.request\s*\(|\bhttp_request\s*\(|\brequest\s*\(\s*\{"), "requete HTTP executor"),
    (re.compile(r"\bWebSocket\b"), "WebSocket (canal distant)"),
    (re.compile(r"\bsetclipboard\s*\("), "setclipboard"),
    (re.compile(r"\bwritefile\s*\(|\breadfile\s*\(|\bappendfile\s*\("), "lecture/ecriture de fichiers"),
    (re.compile(r"\bhookfunction\s*\(|\bhookmetamethod\s*\("), "hookfunction/hookmetamethod"),
    (re.compile(r"\bqueue_on_teleport\s*\("), "queue_on_teleport (persistance)"),
    (re.compile(r"ROBLOSECURITY", re.I), "cookie de session Roblox"),
]


def quick_findings(text: str) -> str:
    """Resume de securite d'un resultat : webhooks (jeton masque), URLs, APIs sensibles."""
    text = _clip(text)
    out: list[str] = []
    hooks = sorted({m.group(0) for m in _WEBHOOK_RE.finditer(text)})
    if hooks:
        out.append(f"Webhooks Discord en dur : {len(hooks)} (jeton masque)")
        for h in hooks[:5]:
            out.append("  - " + _mask_hooks(h))
    urls: list[str] = []
    for u in _URL_FIND.findall(text):
        if _WEBHOOK_RE.match(u) or u in urls:
            continue
        urls.append(u)
    if urls:
        out.append(f"URLs ({len(urls)}) :")
        for u in urls[:15]:
            out.append("  - " + re.sub(r"(token=)[\w-]+", r"\1***", u)[:140])
    dang = [label for pat, label in _DANGER_QUICK if pat.search(text)]
    if dang:
        out.append("APIs sensibles : " + "; ".join(dang))
    markers = len(re.findall(r'error\("devirt:', text))
    if markers:
        out.append(f"Blocs non reconstruits : {markers} (marqueurs error(\"devirt:...))")
    return "\n".join(out) if out else "Rien de notable repere."


_RUNNING: set = set()      # sous-processus de jobs en cours (tues a l'annulation et au dechargement du cog)
_BG: set = set()           # taches de fond (renvois differes des resultats)
_RETRY_DELAYS = (60, 300, 900, 3600, 3 * 3600)    # renvois differes du MP si rien n'a pu etre livre


# ── journal et logs (pour comprendre ce qui s'est passe APRES coup) ─────────────

def _results_dir() -> Path:
    d = _find_suite() / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _suite_mod(name: str):
    """Importe un module de la suite (decision, result_tools, settings_store, stats_store, secure_log, ratelimit...)."""
    import importlib
    root = str(Path(__file__).resolve().parent.parent)      # les modules d'aide sont ceux de CE paquet (meme si DEOBF_SUITE_DIR pointe ailleurs)
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module(name)


def _mask(text) -> str:
    """Retire jetons / cles / secrets d'un texte (journaux, messages d'erreur) ; sans effet si le module manque."""
    try:
        return _suite_mod("secure_log").mask(text)
    except Exception:  # noqa: BLE001
        return str(text)


def _stats():
    try:
        return _suite_mod("stats_store").stats()
    except Exception:  # noqa: BLE001
        return None


def _record_stat(kind: str, user_id: int, name: str, status: str, engine: Optional[str] = None, elapsed: float = 0.0) -> None:
    st = _stats()
    if st is not None:
        try:
            st.record(kind, user_id, name, status, engine, elapsed)
        except Exception as exc:  # noqa: BLE001 - les statistiques ne doivent jamais faire echouer une operation
            print(f"[deobf] statistiques indisponibles : {exc}", flush=True)


def _log(msg: str) -> None:
    """Console + logs/deobf.log (jamais d'exception). Les secrets (jetons, cles) sont masques."""
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {_mask(msg)}"
    print(f"[deobf] {line}", flush=True)
    try:
        d = _find_suite() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "deobf.log"
        if f.exists() and f.stat().st_size > 1_000_000:
            f.replace(d / "deobf.log.1")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


_JOBS: list[dict] = []
_JOBS_LOADED = False


def _load_jobs() -> None:
    """Charge l'historique du disque UNE fois (sinon la premiere ecriture l'ecraserait)."""
    global _JOBS_LOADED
    if not _JOBS_LOADED:
        _JOBS_LOADED = True
        _JOBS[:0] = _journal_load()


def _journal_save() -> None:
    try:
        rows = [{k: v for k, v in j.items() if not k.startswith("_")} for j in _JOBS[-30:]]
        (_results_dir() / "journal.json").write_text(json.dumps(rows, ensure_ascii=False, default=str), encoding="utf-8")
    except OSError:
        pass


def _journal_load() -> list[dict]:
    try:
        return json.loads((_results_dir() / "journal.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _bootstrap():
    """Le module bootstrap de la suite (importe a la demande)."""
    suite = str(_find_suite())
    added = suite not in sys.path
    if added:
        sys.path.insert(0, suite)
    try:
        import bootstrap  # noqa: WPS433
        return bootstrap
    finally:
        if added and sys.path and sys.path[0] == suite:
            sys.path.pop(0)


def _kill_group(proc) -> None:
    """Arrete le routeur ET tout ce qu'il a lance (Node, Luau, lifteurs...), meme dans une autre session."""
    _kill_tree(proc.pid)


def _router_blocking(cmd: list, cwd: str, timeout: int, on_line, holder: list,
                     on_start=None, env: Optional[dict] = None) -> tuple[list, bool, Optional[int]]:
    """Lance le routeur et attend SA FIN (waitpid), pas la fermeture du tube : asyncio.Process.wait() de
    Python <= 3.11 attend aussi que tous les tubes soient fermes -- un petit-enfant orphelin qui les garde ouverts
    bloquait donc le job jusqu'au delai (25 min) alors que le resultat etait pret. Un thread lit la sortie ligne
    a ligne (etape en cours) ; apres la fin, le groupe de processus est tue (aucun orphelin)."""
    import subprocess
    import threading
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True, env=env)
    holder.append(proc)
    _RUNNING.add(proc)
    if on_start is not None:
        try:
            on_start(proc)
        except Exception:  # noqa: BLE001
            pass
    lines: list[str] = []
    size = [0]

    def reader() -> None:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\n")
            lines.append(line)
            size[0] += len(line)
            while size[0] > 2_000_000 and len(lines) > 1:
                size[0] -= len(lines.pop(0))
            if on_line is not None:
                try:
                    on_line(line)
                except Exception:  # noqa: BLE001
                    pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout + 120)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        proc.wait()
    finally:
        _kill_group(proc)
        _RUNNING.discard(proc)
    t.join(timeout=5)
    return lines, timed_out, proc.returncode


async def _run_router(src: Path, dst: Path, engine: Optional[str], timeout: int, on_line=None, on_start=None,
                      env_extra: Optional[dict] = None) -> dict:
    """deobf_router.py run ... --json dans un sous-processus (voir _router_blocking). Groupe de processus tue au
    timeout, a l'annulation de la commande et au dechargement du cog."""
    cmd = [sys.executable, "-I", str(_find_suite() / "deobf_router.py"), "run", str(src), str(dst), "--json",
           "--timeout", str(timeout)]
    if engine and engine != "auto":
        cmd += ["--engine", engine]
    holder: list = []
    try:
        lines, timed_out, rc = await asyncio.to_thread(_router_blocking, cmd, str(_find_suite()), timeout, on_line, holder, on_start,
                                                   {**os.environ, **env_extra} if env_extra else None)
    except BaseException:                       # annulation (arret du bot...) : ne laisser aucun orphelin
        for p in holder:
            _kill_group(p)
        raise
    if timed_out:
        return {"ok": False, "engine": engine, "log": f"timeout global ({timeout}s) -- processus tue"}
    for line in reversed(lines):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    return {"ok": False, "engine": engine, "code": rc,
            "log": "\n".join(lines)[-2000:] or f"routeur sans reponse (code {rc})"}


JOB_TIMEOUT_DEFAULT = 25 * 60
JOB_TIMEOUT_MAX = 60 * 60
PREVIEW_CHARS = 1400
GAMEGATE_RE = re.compile(rb'Kick\(\s*"[^"\n]*(?:not supported|unsupported|not available)[^"\n]*"', re.I)


# ── suivi dans le SALON : message editable avec compte a rebours ───────────────

_TICK = 5                  # secondes entre deux mises a jour du message de suivi
STAGES = [                 # (libelle, avancement atteint au DEBUT de l'etape)
    ("Preparation (detection, Node.js, Luau)", 0.02),
    ("Execution du script dans le bac a sable", 0.08),
    ("Analyse du code de la VM (calcul lourd, silencieux)", 0.14),
    ("Devirtualisation", 0.22),
    ("Reconstruction du code (tentatives du lifteur)", 0.60),
    ("Mise en forme", 0.93),
    ("Envoi du resultat", 0.98),
]


def _fmt_duration(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f"{sec // 60} min {sec % 60:02d} s" if sec >= 60 else f"{sec} s"


def _stage_of(line: str) -> Optional[tuple[int, str]]:
    """Etape (indice dans STAGES, detail) deduite d'une ligne de sortie du routeur / du moteur."""
    low = line.lower()
    m = re.search(r"lift attempt (\d+)", low)
    if m:
        return 4, f"tentative {m.group(1)}"
    if "lift:" in low:
        return 4, ""
    if "devirtualizing" in low or re.search(r"\d+ functions, \d+ unlifted", low):
        return 3, ""
    if "constants decoded" in low:
        return 2, ""
    if "tracing" in low or "loadstring'd" in low or "path2d" in low:
        return 1, ""
    if "run status" in low or "[+] result" in low or low.startswith("postprocess") or "[engine:" in low:
        return 5, ""
    if line.startswith("[router]") and ("second etage" in low or "second(s) etage" in low):
        return 5, "second etage (code charge par loadstring)"
    if line.startswith("[router]") or line.startswith("[bootstrap]"):
        return 0, line.split("]", 1)[-1].strip()[:80]
    return None


# ── CPU reellement disponible (un conteneur peut etre BRIDE a une fraction de coeur) ─────────────────────

def _parse_cpu_max(text: str) -> Optional[float]:
    """cgroup v2 `cpu.max` : « 25000 100000 » -> 0.25 coeur ; « max 100000 » -> None."""
    parts = text.split()
    try:
        if len(parts) >= 2 and parts[0] != "max":
            return int(parts[0]) / int(parts[1])
    except (ValueError, ZeroDivisionError):
        pass
    return None


def _cpu_limits() -> dict:
    """{"cores": visibles, "affinity": autorises, "quota": limite cgroup en coeurs ou None, "effective": utilisables}."""
    cores = os.cpu_count() or 1
    try:
        aff = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        aff = cores
    quota = None
    try:
        quota = _parse_cpu_max(Path("/sys/fs/cgroup/cpu.max").read_text())
    except OSError:
        pass
    if quota is None:                                            # cgroup v1
        try:
            q = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
            pr = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
            if q > 0 and pr > 0:
                quota = q / pr
        except (OSError, ValueError):
            pass
    eff = min(aff, quota) if quota else float(aff)
    out = {"cores": cores, "affinity": aff, "quota": quota, "effective": max(0.05, eff), "forced": False}
    forced = os.environ.get("DEOBF_FORCE_CPU", "").strip()
    if forced:                                     # l'hebergeur annonce un quota faux : on impose le nombre de coeurs
        try:
            out.update(effective=max(0.05, float(forced.replace(",", "."))), forced=True)
        except ValueError:
            pass
    return out


def _cpu_factor(cpu: dict) -> float:
    """Combien de fois plus lent qu'une machine de 4 coeurs (le modele de duree)."""
    return max(1.0, 4.0 / cpu["effective"])


def _estimate_seconds(kb: int, raw_head: bytes, engine: Optional[str]) -> float:
    """Duree totale estimee : ~20 s, corrigee par l'historique SEULEMENT si on a au moins 2 jobs reussis de taille
    comparable (0,5x a 2x) ; jamais en dessous de 40 % du modele."""
    model = 20.0
    past = [j["elapsed"] for j in _JOBS + _journal_load()
            if j.get("status") == "ok" and j.get("elapsed", 0) > 0 and j.get("kb")
            and 0.5 <= j["kb"] / max(kb, 1) <= 2]
    if len(past) >= 2:
        past.sort()
        return max(model * 0.4, float(past[len(past) // 2]) * 1.15)
    return model


def _channel_of(interaction: discord.Interaction):
    """Le salon ou ecrire. `interaction.channel` peut etre None (salon absent du cache, pas d'intent guilds) alors
    que `channel_id` est toujours la : on construit alors un PartialMessageable, qui sait envoyer et editer."""
    ch = getattr(interaction, "channel", None)
    if ch is not None:
        return ch
    cid = getattr(interaction, "channel_id", None)
    if not cid:
        return None
    try:
        return interaction.client.get_partial_messageable(cid)
    except Exception:  # noqa: BLE001
        try:
            return discord.PartialMessageable(state=interaction._state, id=cid)
        except Exception:  # noqa: BLE001
            return None


class _Reporter:
    """Ou parler : le SALON de la commande (message de suivi editable sans limite de duree, fichier du resultat),
    sinon la reponse a l'interaction (valable 15 min), sinon les MP. Rien n'est jamais perdu en silence."""

    def __init__(self, interaction: discord.Interaction) -> None:
        self.i = interaction
        self.msg = None
        self.mode = "aucun"
        self.last_error = ""
        self.channel_failed = False

    async def start(self, text: str, embed: Optional[discord.Embed] = None) -> str:
        ch = _channel_of(self.i)
        kw: dict = {}
        if text:
            kw["content"] = text[:1990]
        if embed is not None:
            kw["embed"] = embed
        if ch is not None:
            try:
                self.msg = await ch.send(allowed_mentions=discord.AllowedMentions.none(), **kw)
                self.mode = "salon"
                return self.mode
            except (discord.HTTPException, AttributeError, TypeError) as exc:
                self.channel_failed = True
                _log(f"ecriture dans le salon impossible : {exc}")
        try:
            self.msg = await self.i.followup.send(wait=True, ephemeral=True, **kw)
            self.mode = "interaction"
        except (discord.HTTPException, discord.NotFound):
            self.msg, self.mode = None, "aucun"
        return self.mode

    async def delete(self) -> bool:
        """Retire le message de suivi (une fois le resultat livre : une seule trace par operation)."""
        if self.msg is None:
            return False
        try:
            await self.msg.delete()
            self.msg = None
            return True
        except (discord.HTTPException, AttributeError):
            return False

    async def edit(self, text: str, embed: Optional[discord.Embed] = None) -> bool:
        """Modifie le message de suivi. Retourne False (et garde la raison dans last_error) si Discord refuse."""
        if self.msg is None:
            self.last_error = "aucun message de suivi"
            return False
        try:
            if embed is not None:
                await self.msg.edit(content=(text[:1990] if text else None), embed=embed)
            else:
                await self.msg.edit(content=text[:1990])
            self.last_error = ""
            return True
        except discord.HTTPException as exc:
            self.last_error = f"HTTP {exc.status}, code Discord {getattr(exc, 'code', '?')} : {getattr(exc, 'text', '') or exc}"[:200]
        except (AttributeError, aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
        return False

    async def post(self, content: str, files: Optional[list[tuple[str, bytes]]] = None, mention: bool = True,
                   embed: Optional[discord.Embed] = None) -> str:
        """Nouveau message (avec fichiers) : salon -> interaction -> MP. Retourne l'endroit utilise ou « »."""
        files = files or []

        def build() -> dict:
            kw: dict = {"allowed_mentions": (discord.AllowedMentions(users=[self.i.user]) if mention
                                             else discord.AllowedMentions.none())}
            if content:
                kw["content"] = content[:1990]
            if embed is not None:
                kw["embed"] = embed
            if files:
                kw["files"] = [discord.File(io.BytesIO(b), filename=n) for n, b in files]
            return kw

        ch = _channel_of(self.i)
        if ch is not None and not self.channel_failed:
            for attempt in range(3):
                try:
                    await ch.send(**build())
                    return "salon"
                except discord.Forbidden:
                    self.channel_failed = True
                    break
                except discord.HTTPException as exc:
                    if exc.status in (400, 413):
                        break
                    await asyncio.sleep(2 ** attempt)
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                    await asyncio.sleep(2 ** attempt)
        try:
            kw = build()
            kw.pop("allowed_mentions", None)
            await self.i.followup.send(ephemeral=True, **kw)
            return "interaction"
        except (discord.HTTPException, discord.NotFound):
            pass
        ok, _ = await _dm_send(self.i.user, content=content or (embed.title if embed is not None else ""), files=files)
        return "MP" if ok else ""


# ── surveillance : le bot dit CE QUI NE VA PAS au lieu de se taire ──────────────

_STALL_WARN = int(os.environ.get("DEOBF_STALL_WARN", "60"))     # secondes sans activite avant l'avertissement
_STALL_KILL = int(os.environ.get("DEOBF_STALL_KILL", "240"))    # ... avant d'arreter le job (bloque pour de bon)


def _proc_table() -> dict[int, dict]:
    """Tous les processus (Linux : /proc) : pid -> {ppid, pgrp, name, state, cpu (s, enfants termines inclus), rss (Mo)}."""
    table: dict[int, dict] = {}
    if not os.path.isdir("/proc"):
        return table
    try:
        tick = os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError, AttributeError):
        tick = 100
    try:
        page = os.sysconf("SC_PAGE_SIZE") or 4096
    except (ValueError, OSError, AttributeError):
        page = 4096
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "rb") as fh:
                raw = fh.read().decode("utf-8", "replace")
            name = raw[raw.index("(") + 1:raw.rindex(")")]
            rest = raw[raw.rindex(")") + 2:].split()
            if rest[0] == "Z":
                continue
            table[int(entry)] = {"pid": int(entry), "ppid": int(rest[1]), "pgrp": int(rest[2]), "name": name, "state": rest[0],
                                 "cpu": (int(rest[11]) + int(rest[12]) + int(rest[13]) + int(rest[14])) / tick,
                                 "rss": int(rest[21]) * page / 1048576}
        except (OSError, ValueError, IndexError):
            continue
    return table


def _tree_snapshot(root: Optional[int]) -> list[dict]:
    """Le processus `root` ET tous ses descendants. Le moteur est lance dans sa PROPRE session (start_new_session) :
    surveiller seulement le groupe du routeur ne voyait que le routeur (« python, CPU 0 % ») et jamais Node/Luau."""
    if not root:
        return []
    table = _proc_table()
    if root not in table:
        return []
    kids: dict[int, list[int]] = {}
    for p in table.values():
        kids.setdefault(p["ppid"], []).append(p["pid"])
    out, todo = [], [root]
    while todo:
        pid = todo.pop()
        if pid in table:
            out.append(table[pid])
            todo.extend(kids.get(pid, []))
    return out


def _kill_tree(root: Optional[int]) -> None:
    """SIGKILL du processus et de tous ses descendants, y compris ceux d'autres sessions/groupes."""
    import signal
    if not root:
        return
    victims = _tree_snapshot(root)
    for p in reversed(victims):                     # les plus profonds d'abord
        try:
            os.kill(p["pid"], signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    for pg in {p["pgrp"] for p in victims} | {root}:
        try:
            os.killpg(pg, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _mem_available_mb() -> Optional[int]:
    try:
        with open("/proc/meminfo", encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _diagnose(job: dict, snap: list[dict], idle: float) -> str:
    """Phrase qui dit pourquoi le job semble bloque (ou qu'il ne l'est pas)."""
    parts = [f"Aucune activite depuis {_fmt_duration(idle)}"]
    names = ", ".join(f"{p['name']}[{p['state']}]" for p in snap[:6])
    last = job.get("step", "")
    low = last.lower()
    comp = {"git", "cmake", "make", "g++", "cc1plus", "ld", "gcc", "c++"}
    if not snap:
        parts.append("le moteur n'a plus aucun processus actif (il s'est arrete sans rien dire)")
    else:
        parts.append(f"processus : {names}")
        if any(p["name"] in comp for p in snap):
            parts.append("compilation de Luau en cours (lente sur une petite machine, une seule fois)")
        elif "telecharg" in low or "node.js absent" in low:
            parts.append("telechargement de Node.js sans donnees : reseau lent ou bloque")
        elif all(p["state"] in ("S", "D") for p in snap):
            parts.append("tous les processus attendent (reseau, disque ou verrou d'un autre processus)")
        mem = sum(p["rss"] for p in snap)
        if mem > 0:
            parts.append(f"memoire du moteur : {int(mem)} Mo")
    avail = _mem_limits()["avail_mb"]
    if avail is not None and avail < 300:
        parts.append(f"MEMOIRE QUASI PLEINE ({avail} Mo libres) : le systeme va tuer le moteur")
    if last:
        parts.append(f"derniere etape connue : {last[:100]}")
    return " ; ".join(parts) + "."


def _explain_failure(res: dict, elapsed: float, job: dict) -> str:
    """Cause d'un echec, en une phrase lisible (au lieu d'un journal brut)."""
    log = (res.get("log") or "")
    low = log.lower()
    code = res.get("code")
    if job.get("stalled"):
        return f"Job arrete car bloque : {job['stalled']}"
    if "timeout" in low and ("global" in low or "apres" in low):
        return f"Temps maximal depasse ({_fmt_duration(elapsed)}) : le moteur ne finit pas sur ce script ou la machine est trop lente."
    if code in (-9, 137) or "killed" in low:
        return "Le systeme a TUE le moteur (code 9) : presque certainement memoire insuffisante sur la machine du bot."
    if "preparation automatique impossible" in low or "prerequis manquants" in low:
        m = re.search(r"(preparation automatique impossible[^\n]*|prerequis manquants[^\n]*)", log, re.I)
        return m.group(1) if m else "Prerequis manquants."
    if "aucun obfuscateur reconnu" in low:
        return "Aucun obfuscateur reconnu dans ce script (utilise /deobf avec moteur: pour en forcer un)."
    if "moteur inconnu" in low:
        return "Moteur inconnu (voir /deobf_engines)."
    if "entree trop grosse" in low:
        return "Fichier trop gros pour le moteur."
    tb = re.findall(r"^(?:\w+\.)*\w*(?:Error|Exception)[^\n]*$", log, re.M)
    if "traceback" in low and tb:
        return f"Erreur dans le moteur : {tb[-1][:200]}"
    if "node" in low and ("not found" in low or "introuvable" in low):
        return "Node.js introuvable sur la machine du bot."
    tail = [l.strip() for l in log.splitlines() if l.strip()][-3:]
    return "Le moteur a echoue" + (f" (code {code})" if code is not None else "") + (" : " + " | ".join(tail)[:300] if tail else " sans message.")


def _mem_limits() -> dict:
    """Memoire REELLEMENT utilisable : la limite du conteneur (cgroup) si elle existe -- /proc/meminfo montre la RAM de
    la machine hote, pas celle du conteneur (le bot affichait « 10 Go libres » alors que le conteneur pouvait n'avoir
    que 512 Mo et faire tuer le moteur)."""
    limit = used = None
    for lim_f, use_f in (("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),
                         ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "/sys/fs/cgroup/memory/memory.usage_in_bytes")):
        try:
            raw = Path(lim_f).read_text().strip()
            if raw != "max" and int(raw) < (1 << 50):
                limit = int(raw) // 1048576
                used = int(Path(use_f).read_text().strip()) // 1048576
                break
        except (OSError, ValueError):
            continue
    host = _mem_available_mb()
    avail = (limit - used) if limit is not None and used is not None else host
    if host is not None and avail is not None:
        avail = min(avail, host)
    return {"limit_mb": limit, "used_mb": used, "avail_mb": avail}


WEAK_LIFT_S = 2400          # machine faible, mode complet : jusqu'a 40 min de tentatives du lifteur (arret des qu'une reussit)


def _plan_resources(n_active: int, timeout_s: Optional[int] = None, explicit_timeout: bool = False) -> dict:
    """Part de CPU / memoire d'un nouveau job, compte tenu des jobs deja en cours (ils tournent EN MEME TEMPS).

    Machine faible (< 1 coeur par job) : deux modes, `DEOBF_WEAK_MODE` =
      - « complet » (defaut) : toutes les tentatives du lifteur (32), sur un budget de temps long (WEAK_LIFT_S) ; le job
        dure plus longtemps mais finit COMPLET dans la grande majorite des cas (une tentative sur ~10 reussit) ;
      - « rapide » : peu de tentatives et duree plafonnee -> un resultat vite, souvent PARTIEL.
    Le lifteur peut depasser son budget de 50 % (les tentatives en cours finissent) : budget borne par le delai du job."""
    cpu = _cpu_limits()
    mem = _mem_limits()
    share = cpu["effective"] / max(1, n_active)
    parallel = max(1, min(4, int(share)))
    if mem["avail_mb"] is not None:                      # ~350 Mo par tentative du lifteur en parallele
        parallel = max(1, min(parallel, int(mem["avail_mb"] // 350) or 1))
    slow = max(1.0, 1.0 / share)
    weak = share < 1.0
    fast = weak and os.environ.get("DEOBF_WEAK_MODE", "complet").strip().lower() in ("rapide", "fast")
    env = {"DEOB_LIFT_PARALLEL": str(parallel),
           "LURAPH_BUDGET": str(int(120 * min(slow, 10))), "LURAPH_TIMEOUT": str(int(300 * min(slow, 10))),
           "DEOB_LIFT_RETRIES": str(max(2, min(32, int(share * 12)))) if fast else "32",
           "DEOB_LIFT_BUDGET": str(int(min(600 * slow, 1500))) if fast else str(WEAK_LIFT_S if weak else 600)}
    lift = int(env["DEOB_LIFT_BUDGET"])
    trace = int(env["LURAPH_BUDGET"])                    # l'execution du script (trace) passe avant le lifteur
    needed = None
    if weak and not fast and not explicit_timeout:
        needed = int((trace + 1.5 * lift) / 0.9)         # delai du job qui laisse le temps aux tentatives
    elif timeout_s:
        lift = max(60, min(lift, int((timeout_s * 0.9 - trace) / 1.5)))
    env["DEOB_LIFT_BUDGET"] = str(lift)
    env["DEOB_LIFT_GRACE"] = str(lift // 2)
    return {"cpu": cpu, "mem": mem, "share": share, "slow": slow, "weak": weak, "fast": fast, "env": env,
            "parallel": parallel, "timeout_needed": needed}


async def _monitor(job: dict) -> None:
    """Surveille UN job (sans ecrire sur Discord : le tableau de bord du salon s'en charge) : activite reelle (CPU,
    memoire de tout l'arbre de processus), inactivite -> diagnostic, puis arret au bout de _STALL_KILL s."""
    last_cpu = 0.0
    last_progress = job["started"]
    announced = False
    try:
        while True:
            t_before = time.monotonic()
            await asyncio.sleep(_TICK)
            lag = time.monotonic() - t_before - _TICK
            now = time.time()
            if lag > 3:
                job["lag"] = round(lag)
            snap = await asyncio.to_thread(_tree_snapshot, job.get("pid"))
            cpu = sum(p["cpu"] for p in snap)
            dt = max(now - job.get("_snap_t", now - _TICK), 0.1)
            pct_cpu = max(0.0, (cpu - job.get("_snap_cpu", cpu)) / dt * 100) if snap else 0.0
            job["_snap_t"], job["_snap_cpu"] = now, cpu
            if snap:
                top = max(snap, key=lambda p: p["rss"])
                job["activity"] = (f"{top['name']} · CPU {pct_cpu:.0f} % · {int(sum(p['rss'] for p in snap))} Mo"
                                   + (f" · {len(snap)} processus" if len(snap) > 1 else ""))
            elif job.get("pid"):
                job["activity"] = "aucun processus du moteur actif"
            if cpu > last_cpu + 0.15 or job.get("last_line_at", 0) > last_progress:
                last_progress = now
            last_cpu = max(cpu, last_cpu) if snap else last_cpu
            idle = now - last_progress
            job["idle"] = round(idle)
            job["warn"] = ""
            if idle >= _STALL_WARN and job["stage"] < len(STAGES) - 1:
                job["warn"] = _diagnose(job, snap, idle)
                if not announced:
                    announced = True
                    _log(f"job {job['id']} : {job['warn']}")
            if idle >= _STALL_KILL and job["stage"] < len(STAGES) - 1:
                job["stalled"] = _diagnose(job, snap, idle)
                _log(f"job {job['id']} BLOQUE, arret : {job['stalled']}")
                _kill_tree(job.get("pid"))
                return
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - la surveillance ne doit jamais faire tomber le job, mais doit le dire
        import traceback
        _log(f"job {job['id']} : la surveillance a plante :\n{traceback.format_exc()}")


def _spawn(coro) -> None:
    task = asyncio.ensure_future(coro)
    _BG.add(task)
    task.add_done_callback(_BG.discard)


async def _retry_dm_later(user, items: list[tuple[str, bytes]], content: str, job: dict) -> None:
    """Rien n'a pu etre livre (salon, interaction et MP en echec) : on retente le MP plus tard (le resultat reste de
    toute facon recuperable avec /deobf_dernier)."""
    for delay in _RETRY_DELAYS:
        await asyncio.sleep(delay)
        ok, why = await _dm_send(user, content=content, files=items)
        _log(f"renvoi differe du MP (job {job['id']}) : {'ok' if ok else why}")
        if ok:
            job["delivered"] = "MP (renvoi differe)"
            _journal_save()
            return


# ── cache des resultats (meme script -> reponse instantanee) ────────────────────────────────────────────

CACHE_VERSION = "v2"           # a changer si les moteurs changent (invalide le cache)
_CACHE_MAX = 200


def _cache_path(sha: str, moteur: Optional[str]) -> Path:
    d = _results_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{CACHE_VERSION}_{sha}_{re.sub(r'[^A-Za-z0-9_]', '', moteur or 'auto')}.lua"


def _cache_get(sha: str, moteur: Optional[str]) -> Optional[tuple[bytes, dict]]:
    """Cache local (results/cache), puis cache LIVRE avec la suite (cache_seed/ : resultats verifies, ex. Spicy3)."""
    p = _cache_path(sha, moteur)
    seed = _find_suite() / "cache_seed" / p.name
    for cand in (p, seed):
        try:
            meta = json.loads(cand.with_suffix(".json").read_text(encoding="utf-8"))
            return cand.read_bytes(), meta
        except (OSError, ValueError):
            continue
    return None


def _cache_put(sha: str, moteur: Optional[str], data: bytes, meta: dict) -> None:
    """Seulement les resultats COMPLETS (0 bloc non reconstruit) : un resultat partiel doit pouvoir etre retente."""
    try:
        p = _cache_path(sha, moteur)
        p.write_bytes(data)
        p.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        files = sorted(p.parent.glob("*.lua"), key=lambda f: f.stat().st_mtime, reverse=True)
        for old in files[_CACHE_MAX:]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)
    except OSError as exc:
        _log(f"cache : ecriture impossible ({exc})")


# ── jobs SIMULTANES + un tableau de bord par salon ────────────────────────────────────────────────────────

_ACTIVE: dict[int, dict] = {}          # jobs en cours (tous en meme temps, aucune file d'attente)
_BOARDS: dict = {}                     # salon -> _Board
_INFLIGHT: dict = {}                   # (sha, moteur) -> Future : le meme script envoye 2 fois n'est calcule qu'1 fois
_JOB_SEQ = [0]
_MAX_ZIP_FILES = 100
_MAX_ZIP_TOTAL = 64 * 1024 * 1024


def _ui():
    """cogs/ui_kit (embeds), importe comme sous-module du paquet ou a plat."""
    try:
        from . import ui_kit
    except ImportError:
        import ui_kit  # type: ignore
    return ui_kit


def _job_line(job: dict) -> str:
    """Une ligne (ou deux) du tableau de bord pour un job."""
    name = f"`{job['name'][:40]}`"
    st = job.get("status")
    if st == "ok":
        v = job.get("verdict") or "success"
        el = "cache" if job.get("result") == "cache" else _fmt_duration(job.get("elapsed", 0))
        icon = {"success": "✅", "partial": "⚠️"}.get(v, "✅")
        if job.get("protected"):
            return f"🔒 {name} · protégé par {job['protected']}"
        tail = ""
        return f"{icon} {name} · {el}{tail}"
    if st == "echec":
        return f"❌ {name} · {str(job.get('error', ''))[:110]}"
    if st == "annule":
        return f"⛔ {name} annule"
    est = job.get("est") or 60
    el = time.time() - job["started"]
    idx = job.get("stage", 0)
    frac = max(STAGES[idx][1], min(0.95, el / est if est else 0))
    job["pct"] = max(job.get("pct", 0), frac)
    pct = job["pct"]
    bar = "▓" * int(round(pct * 10)) + "░" * (10 - int(round(pct * 10)))
    rem = est - el
    if idx >= 3 and STAGES[idx][1] > 0 and rem > 0:
        rem = min(rem, el * (1 - STAGES[idx][1]) / STAGES[idx][1])
    now = time.time()
    end = job.get("eta_end")
    if rem > 0:
        # le compte a rebours ne remonte JAMAIS : une fois arrive a zero on ne le relance pas (sinon « reste ~0 s »
        # puis « reste ~45 s » quand l'estimation change d'etape) -- le tableau dit alors « plus long que prevu »
        if end is None:
            end = now + rem
        elif end > now:
            end = min(end, now + rem)
        job["eta_end"] = end
        rem = end - now
    eta = f"reste ~{_fmt_duration(rem)}" if rem > 0 else "plus long que prevu, je continue"
    label = STAGES[idx][0].split(" (")[0] + (f" ({job['detail']})" if job.get("detail") else "")
    line = (f"⏳ {name} {job['kb']} Ko · Etape {idx + 1}/{len(STAGES)} {label}\n"
            f"　{bar} {int(pct * 100)} % · {_fmt_duration(el)}")
    if job.get("warn"):
        line += f"\n　⚠️ {job['warn'][:220]}"
    return line


class _Board:
    """UN message par salon qui suit tous les jobs en cours (au lieu d'un message par job : avec 100 jobs, Discord
    limiterait les modifications). Mis a jour toutes les _TICK s tant qu'un job tourne."""

    def __init__(self, key, interaction: discord.Interaction) -> None:
        self.key = key
        self.rep = _Reporter(interaction)
        self.jobs: list[dict] = []
        self.task: Optional[asyncio.Future] = None
        self.note = ""
        self.fails = 0
        self._start_lock = asyncio.Lock()      # 30 jobs ajoutes en meme temps -> UN seul message de suivi

    def render_embed(self) -> discord.Embed:
        """Le meme suivi, en embed : couleur selon l'etat, une ou deux lignes par fichier, rien d'autre."""
        ui = _ui()
        running = [j for j in self.jobs if j.get("status") == "en cours"]
        done = [j for j in self.jobs if j.get("status") != "en cours"]
        if running:
            status, title = "running", f"Deobfuscation · {len(running)} running" + (f", {len(done)} finished" if done else "")
        else:
            bad = any(j.get("status") == "echec" for j in done)
            part = any(j.get("missing") or j.get("verdict") == "partial" for j in done)
            status = "failed" if bad and all(j.get("status") == "echec" for j in done) else ("partial" if bad or part else "success")
            title = f"Deobfuscation finished · {len(done)} file(s)"
        e = ui.embed(status, title)
        parts, budget, shown = [], 3800, 0
        for j in running + done[::-1]:
            ln = _job_line(j)
            if len(ln) + 1 > budget:
                break
            parts.append(ln)
            budget -= len(ln) + 1
            shown += 1
        if shown < len(self.jobs):
            parts.append(f"… et {len(self.jobs) - shown} autre(s)")
        e.description = "\n".join(parts)
        if self.note:
            e.set_footer(text=self.note.strip()[:200])
        return e

    def render(self) -> str:
        running = [j for j in self.jobs if j.get("status") == "en cours"]
        done = [j for j in self.jobs if j.get("status") != "en cours"]
        head = (f"🧩 **Deobfuscation** -- {len(running)} en cours, {len(done)} termine(s)" if running
                else f"🧩 **Deobfuscation terminee** -- {len(done)} job(s)")
        parts = [head]
        budget = 1900 - len(head) - len(self.note)
        shown = 0
        for j in running + done[::-1]:
            ln = _job_line(j)
            if len(ln) + 1 > budget:
                break
            parts.append(ln)
            budget -= len(ln) + 1
            shown += 1
        if shown < len(self.jobs):
            parts.append(f"… et {len(self.jobs) - shown} autre(s) (voir /deobf_etat)")
        return "\n".join(parts) + self.note

    async def add(self, job: dict) -> None:
        self.jobs.append(job)
        job["_board"] = self
        async with self._start_lock:
            if self.rep.msg is None:
                await self.rep.start("", embed=self.render_embed())
        if self.task is None or self.task.done():
            self.task = asyncio.ensure_future(self._loop())

    async def flush(self) -> None:
        """Met le message a jour tout de suite (sans attendre le prochain tick)."""
        try:
            if self.rep.msg is not None:
                await self.rep.edit("", embed=self.render_embed())
        except Exception:  # noqa: BLE001 - un echec d'affichage ne doit jamais faire echouer le job
            pass

    async def _nap(self) -> None:
        """Attend _TICK s, mais se reveille des que le DERNIER job se termine : le message passe alors tout de suite a
        « termine » (sinon il restait sur « en cours » jusqu'a 5 s apres la livraison du fichier)."""
        end = time.monotonic() + _TICK
        while time.monotonic() < end:
            await asyncio.sleep(min(0.2, max(0.0, end - time.monotonic())))
            if not any(j.get("status") == "en cours" for j in self.jobs):
                return

    async def _loop(self) -> None:
        try:
            while True:
                await self._nap()
                running = any(j.get("status") == "en cours" for j in self.jobs)
                ok = await self.rep.edit("", embed=self.render_embed())
                if ok:
                    self.fails = 0
                else:
                    self.fails += 1
                    if self.fails == 3:
                        _log(f"tableau de bord : modification impossible : {self.rep.last_error}")
                        await self.rep.start("", embed=self.render_embed())      # nouveau message de suivi (l'ancien n'est plus modifiable)
                        self.fails = 0
                if not running:
                    if not ok:
                        await self.rep.edit("", embed=self.render_embed())      # derniere chance d'afficher « termine »
                    break
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            import traceback
            _log("tableau de bord : erreur\n" + traceback.format_exc())
        finally:
            if _BOARDS.get(self.key) is self and not any(j.get("status") == "en cours" for j in self.jobs):
                _BOARDS.pop(self.key, None)


def _board_for(interaction: discord.Interaction) -> "_Board":
    key = getattr(interaction, "channel_id", None) or getattr(getattr(interaction, "channel", None), "id", None) or id(interaction)
    b = _BOARDS.get(key)
    if b is None or b.rep.channel_failed or not any(j.get("status") == "en cours" for j in b.jobs):
        # un nouveau lot ne reutilise jamais le message d'un lot deja termine (il serait tout en haut du salon)
        b = _BOARDS[key] = _Board(key, interaction)
    return b


def _unzip_scripts(raw: bytes) -> list[tuple[str, bytes]]:
    """Scripts d'une archive .zip (jusqu'a 100) : .lua / .luau / .txt, sans chemins ni bombes de decompression."""
    import zipfile
    out: list[tuple[str, bytes]] = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for info in z.infolist():
            if info.is_dir() or not re.search(r"\.(lua|luau|txt)$", info.filename, re.I):
                continue
            if len(out) >= _MAX_ZIP_FILES:
                break
            if info.file_size > _MAX_BYTES or total + info.file_size > _MAX_ZIP_TOTAL:
                continue
            data = z.read(info)[: _MAX_BYTES + 1]
            if len(data) > _MAX_BYTES or not data.strip():
                continue
            total += len(data)
            out.append((Path(info.filename).name or f"script{len(out) + 1}.lua", data))
    return out


async def run_job(interaction: discord.Interaction, *, url: Optional[str] = None,
                  fichier: Optional[discord.Attachment] = None, moteur: Optional[str] = "auto",
                  timeout_s: int = JOB_TIMEOUT_DEFAULT, force: bool = False) -> None:
    """/process et /deobf : meme code, meme resultat que `python3 deobf_router.py run ...`.

    Les jobs tournent TOUS EN MEME TEMPS (aucune file d'attente) : chacun recoit une part du CPU / de la memoire.
    Un .zip est decoupe en ses scripts (jusqu'a 100), traites en parallele. Le suivi se fait dans UN message du salon
    (tableau de bord, mis a jour toutes les 5 s) ; chaque resultat est poste dans le salon des qu'il est pret.
    Aucun message « en arriere-plan » : la reponse ephemere de la commande est supprimee des que le suivi est poste."""
    if not url and not fichier:
        await interaction.response.send_message("Provide `url:` or `file:` (a script or a .zip of scripts).", ephemeral=True)
        return
    router = _find_suite() / "deobf_router.py"
    if not router.exists():
        await interaction.response.send_message(
            f"Routeur introuvable : `{router}` (dossier yslem_deobf_suite absent ? variable DEOBF_SUITE_DIR).", ephemeral=True)
        return
    if moteur and not re.fullmatch(r"[A-Za-z0-9_]{1,40}", moteur):
        await interaction.response.send_message("Nom de moteur invalide.", ephemeral=True)
        return
    if not interaction.response.is_done():          # deja « defer » / repondu quand le selecteur de moteur de /deobf l'a appele
        await interaction.response.defer(thinking=True, ephemeral=True)
    _load_jobs()

    # -- 1. le(s) script(s)
    try:
        if fichier is not None:
            if fichier.size and fichier.size > _MAX_ZIP_TOTAL:
                raise ValueError("file too large")
            raw = await fichier.read()
            name = Path(fichier.filename).name or "input.lua"
        else:
            name, raw = await _fetch_url(url)
        if not raw:
            raise ValueError("empty file")
        if raw[:4] == b"PK\x03\x04" or name.lower().endswith(".zip"):
            items = _unzip_scripts(raw)
            if not items:
                raise ValueError("no .lua/.luau/.txt script in the zip")
        else:
            if len(raw) > _MAX_BYTES:
                raise ValueError(f"file too large (max {_MAX_BYTES // (1024 * 1024)} Mo)")
            items = [(name, raw)]
    except Exception as exc:  # noqa: BLE001
        await _notify(interaction, f"Echec de recuperation : `{exc}`")
        return

    await run_items(interaction, items, moteur, timeout_s, force)


async def run_items(interaction: discord.Interaction, items: list[tuple[str, bytes]], moteur: Optional[str] = "auto",
                    timeout_s: int = JOB_TIMEOUT_DEFAULT, force: bool = False) -> None:
    """Traite des scripts DEJA recuperes (nom, octets) : utilise par run_job et par `.get` (bouton « Oui »).
    Meme suivi, meme resultat. Une seule trace par operation : le message de suivi est retire une fois le resultat livre
    (sauf avec plusieurs fichiers, ou il reste comme recapitulatif)."""
    _load_jobs()
    board = _board_for(interaction)
    n_before = len(board.jobs)
    await asyncio.gather(*(_process_one(interaction, board, n, r, moteur, timeout_s, force) for n, r in items),
                         return_exceptions=True)
    await board.flush()                        # l'etat final de CES jobs est affiche avant la fin de la commande
    mine = board.jobs[n_before:]
    if (board.rep.mode == "salon" and len(mine) == 1 and len(board.jobs) == 1
            and mine[0].get("delivered") not in ("non", "", None) and mine[0].get("status") in ("ok", "echec")):
        await board.rep.delete()               # le resultat est livre dans son propre message : plus de doublon de suivi
    if board.rep.mode == "salon":
        try:                                   # pas de message « en arriere-plan » : on retire la reponse ephemere
            await interaction.delete_original_response()
        except (discord.HTTPException, discord.NotFound, AttributeError):
            pass


async def _process_one(interaction: discord.Interaction, board: "_Board", name: str, raw: bytes,
                       moteur: Optional[str], timeout_s: int, force: bool) -> None:
    user = interaction.user
    ui = _ui()
    _JOB_SEQ[0] += 1
    job = {"id": int(time.time() * 1000) + _JOB_SEQ[0], "user": getattr(user, "id", 0), "name": name, "kb": len(raw) // 1024,
           "started": time.time(), "step": "recu", "stage": 0, "detail": "", "status": "en cours", "delivered": "non",
           "error": "", "result": "", "elapsed": 0, "verdict": "",
           "channel_id": getattr(interaction, "channel_id", None) or getattr(getattr(interaction, "channel", None), "id", None),
           "msg_id": None, "last_line_at": time.time()}
    sha = hashlib.sha256(raw).hexdigest()
    job["sha"] = sha
    safe_stem = re.sub(r"[^\w.\-]", "_", Path(name).stem)[:60] or "script"
    rep = board.rep
    _JOBS.append(job)
    _log(f"job {job['id']} recu de {job['user']} : {name} ({job['kb']} Ko)")
    guild = getattr(interaction, "guild", None)
    try:
        ping = bool(_suite_mod("settings_store").store().option(getattr(guild, "id", None), "mention_result"))
    except Exception:  # noqa: BLE001
        ping = True

    def make_embed(info: dict) -> discord.Embed:
        return ui.result_embed(name, info.get("status", "success"), info.get("reason", ""), info.get("engine", ""),
                               info.get("obfuscator", ""), info.get("elapsed", 0.0), bool(info.get("cached")), info.get("details"))

    async def deliver(data: bytes, info: dict) -> str:
        files, notes = _pack_files([(f"deobfuscated_{safe_stem}.lua", data)])
        embed = make_embed(info)
        if notes:
            embed.add_field(name="File", value="\n".join(notes)[:300], inline=False)
        who = getattr(user, "mention", "") if ping else ""
        where = await rep.post(who, files, mention=ping, embed=embed)
        if not where:
            saved = _save_result(f"{Path(name).stem}.deobf.lua", data)
            _log(f"job {job['id']} : resultat non livre ; copie : {saved}")
            _spawn(_retry_dm_later(user, files, f"Resultat pour {name}", job))
        return where

    async def fail(cause: str, engine: str = "", obfuscator: str = "", status: str = "failed") -> None:
        """Un seul message court, en embed ; le detail technique reste dans les logs administrateur."""
        job.update(status="echec", error=cause, verdict="failed")
        embed = ui.result_embed(name, "failed", cause, engine, obfuscator, time.time() - job["started"])
        who = getattr(user, "mention", "") if ping else ""
        await rep.post(who, None, mention=ping, embed=embed)

    # -- 0. deja calcule ? reponse instantanee
    hit = None if force else _cache_get(sha, moteur)
    if hit is not None:
        data, meta = hit
        job.update(status="ok", result="cache", elapsed=0, verdict=meta.get("status", "success"))
        await board.add(job)
        info = {"status": meta.get("status", "success"), "reason": meta.get("reason", ""), "engine": meta.get("engine", ""),
                "obfuscator": meta.get("obfuscator", ""), "cached": True, "details": meta.get("details")}
        where = await deliver(data, info)
        job["delivered"] = (where or "disk") + " (cache)"
        _record_stat("deobf", job["user"], name, job["verdict"], meta.get("engine"), 0.0)
        _journal_save()
        return

    # -- 1. que contient ce fichier ? le bot decide seul (obfuscateur, moteur, protection d'acces...)
    dec = None
    if (not moteur or moteur == "auto") and os.environ.get("DEOBF_DECIDE", "1") != "0":
        try:
            dec = await asyncio.wait_for(asyncio.to_thread(_suite_mod("decision").decide, raw, name), timeout=60)
        except Exception as exc:  # noqa: BLE001 - la decision est une aide : sans elle le routeur choisit lui-meme
            _log(f"job {job['id']} decision indisponible : {exc}")
    if dec is not None:
        _log(f"job {job['id']} decision : {dec.as_log()}")
        job["protection"] = dec.title if dec.obfuscator else ""
        if dec.kind in ("invalid", "gated", "unsupported", "unavailable"):
            await board.add(job)
            reason = dec.verdict if dec.kind != "invalid" else (dec.notes[0] if dec.notes else "contenu invalide")
            if dec.kind == "unsupported" and dec.notes:
                reason = dec.notes[0]
            if dec.kind == "unavailable" and dec.notes:
                reason = f"{dec.obfuscator} : {dec.notes[0]}"
            if dec.kind == "gated":
                job["protected"] = dec.gate
            await fail(reason, "", dec.title if dec.obfuscator else "")
            _record_stat("deobf", job["user"], name, "failed", None, time.time() - job["started"])
            _journal_save()
            return
        if dec.kind == "plain":
            await board.add(job)
            data = raw.decode("utf-8", "replace").encode("utf-8")
            job.update(status="ok", result="", elapsed=int(time.time() - job["started"]), verdict="success")
            job["delivered"] = await deliver(data, {"status": "success", "reason": "aucune obfuscation détectée : fichier renvoyé tel quel",
                                                    "engine": "", "obfuscator": "", "elapsed": time.time() - job["started"]}) or "disk"
            _record_stat("deobf", job["user"], name, "success", None, time.time() - job["started"])
            _journal_save()
            return
    engine_arg = "trace" if (dec is not None and dec.kind == "trace" and dec.engine == "trace" and not dec.obfuscator) else moteur

    # -- meme script deja en cours de calcul (envoye 2 fois) : on attend CE calcul au lieu d'en lancer un 2e
    key = (sha, moteur or "auto")
    if not force and key in _INFLIGHT:
        await board.add(job)
        job.update(step="meme script deja en calcul : je partage son resultat", detail="partage")
        try:
            data, info = await asyncio.shield(_INFLIGHT[key])
        except Exception as exc:  # noqa: BLE001
            job.update(status="echec", error=f"le calcul partage a echoue : {exc}", verdict="failed")
            return
        if data is None:
            job.update(status="echec", error=str(info), verdict="failed")
            return
        job.update(status="ok", elapsed=int(time.time() - job["started"]), verdict=info.get("status", "success"))
        job["delivered"] = await deliver(data, dict(info, cached=False, details=list(info.get("details") or []) + ["shared computation"])) or "disk"
        _journal_save()
        return
    fut = asyncio.get_running_loop().create_future()
    _INFLIGHT[key] = fut

    plan = _plan_resources(len(_ACTIVE) + 1, timeout_s, explicit_timeout=timeout_s != JOB_TIMEOUT_DEFAULT)
    _ACTIVE[job["id"]] = job
    est = _estimate_seconds(job["kb"], raw[:400], engine_arg) * (max(1.0, 4.0 / plan["share"]) if plan["share"] < 4 else 1.0)
    job["est"] = est
    timeout_s = int(min(3 * 3600, max(timeout_s, est * 1.6, plan["timeout_needed"] or 0)))
    if plan["weak"]:
        who_cpu = f"{plan['cpu']['effective']:.2f} coeur" + (" (impose)" if plan["cpu"].get("forced") else "")
        _log(f"machine faible : {who_cpu} ; mode {'rapide' if plan['fast'] else 'complet'} ; budget {plan['env'].get('DEOB_LIFT_BUDGET')} s")
    await board.add(job)
    monitor = asyncio.ensure_future(_monitor(job))
    workdir: Optional[Path] = None
    prereq_warning: Optional[str] = None
    final_status = "failed"
    final_engine: Optional[str] = None
    try:
        job["step"] = "verification des prerequis"
        try:
            pf = await asyncio.wait_for(asyncio.to_thread(_bootstrap().preflight), timeout=60)
        except Exception as exc:  # noqa: BLE001
            pf = {"ready": True, "steps": [], "blocker": None, "slow": False}
            _log(f"preflight indisponible : {exc}")
        if pf.get("blocker"):
            # Ne PAS refuser d'emblee : beaucoup de moteurs n'ont besoin ni de Luau ni de Node. Un moteur qui en a besoin
            # echoue lui-meme ("prerequis manquant : ...") et la cause de l'echec rappelle alors ce blocage.
            prereq_warning = pf["blocker"]
            _log(f"prerequis incomplets (non bloquant tant que le moteur choisi n'en a pas besoin) : {prereq_warning}")
        if pf.get("steps"):
            job["detail"] = "premiere utilisation : " + " ; ".join(pf["steps"])[:80]
        job["msg_id"] = getattr(rep.msg, "id", None)
        _journal_save()
        if job.get("cancelled"):
            job.update(status="annule", error=f"annule par {job['cancelled']}")
            final_status = "cancelled"
            return
        workdir = Path(tempfile.mkdtemp(prefix="deobf_job_"))
        src, dst = workdir / "input.lua", workdir / "output.deobf.lua"
        src.write_bytes(raw)

        def on_line(line: str) -> None:
            job["last_line_at"] = time.time()
            stg = _stage_of(line)
            if stg is not None:
                idx, detail = stg
                if idx >= job["stage"]:
                    job["stage"] = idx
                    job["detail"] = detail
            elif line.startswith("[*] processing") and job["stage"] < 1:
                job["stage"], job["detail"] = 1, ""
            if line.startswith(("[*]", "[router]", "[bootstrap]", "[engine")):
                job["step"] = line[:140]

        t0 = time.monotonic()
        res = await _run_router(src, dst, engine_arg, timeout_s, on_line, lambda p: job.update(pid=p.pid), plan["env"])
        elapsed = time.monotonic() - t0
        job["elapsed"] = int(elapsed)
        job["engine"] = res.get("engine")
        final_engine = res.get("engine")
        if job.get("cancelled"):
            job.update(status="annule", error=f"annule par {job['cancelled']}")
            final_status = "cancelled"
            return
        full_log = res.get("log") or ""
        _save_job_log(job, res)
        if res.get("ok") and dst.exists():
            rt = _suite_mod("result_tools")
            text_out = dst.read_bytes().decode("utf-8", "replace")
            clean, meta = rt.clean_output(text_out)
            verdict = rt.classify(res, clean, meta)
            data = clean.encode("utf-8")
            job["missing"] = clean.count('error("devirt:')
            job["verdict"] = verdict.status
            job["reason"] = verdict.reason
            obf = job.get("protection") or ""
            if not obf and res.get("detected"):
                obf = str(res["detected"][0][2]).split(" (")[0][:50]
            details = list(verdict.details)
            if res.get("chain"):
                hops = ", ".join((urlparse(lv["url"]).hostname or "?") for lv in res["chain"])
                details.append(f"chargeur suivi : {hops}")
                if res.get("protected"):
                    job["protected"] = res["protected"]
            if res.get("stage2"):
                details.append(f"{res['stage2']} second stage(s)")
            if GAMEGATE_RE.search(data[:4_000_000]):
                details.append("script limited to certain games (the sandbox simulates game 0)")
            info = {"status": verdict.status, "reason": verdict.reason, "engine": res.get("engine") or "", "obfuscator": obf,
                    "elapsed": elapsed, "details": details}
            job["status_info"] = info
            if verdict.status == "success" and not res.get("chain") and verdict.kind != "trace":
                _cache_put(sha, moteur, data, {"engine": res.get("engine"), "elapsed": int(elapsed), "time": time.time(), "name": name,
                                               "status": verdict.status, "reason": verdict.reason, "obfuscator": obf, "details": details})
            findings = quick_findings(clean)
            saved = _save_result(f"{Path(name).stem}.deobf.lua", data)
            _log(f"job {job['id']} {verdict.status} ({verdict.reason or 'ok'}) moteur {res.get('engine')} en {int(elapsed)}s ; findings :\n{findings[:600]}")
            job.update(status="ok", result=saved.name if saved else "")
            final_status = verdict.status
            if not fut.done():
                fut.set_result((data, info))
            job["delivered"] = await deliver(data, info) or "disque (results/)"
        else:
            cause = _explain_failure(res, elapsed, job)
            if prereq_warning and prereq_warning not in cause:
                cause += f" -- prerequis manquant sur cette machine : {prereq_warning}"
            job.update(status="echec", error=cause, verdict="failed")
            if not fut.done():
                fut.set_result((None, cause))
            await fail(cause[:300], res.get("engine") or "", job.get("protection") or "")
        _log(f"job {job['id']} {job['status']} en {job['elapsed']}s, livraison : {job['delivered']}")
    except asyncio.CancelledError:
        job.update(status="annule", error="annule (arret du bot ?)")
        final_status = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001 - un job ne doit jamais rester sans reponse
        import traceback
        _log(f"job {job['id']} ERREUR :\n{traceback.format_exc()}")
        job.update(status="echec", error=_mask(f"{type(exc).__name__}: {exc}"), verdict="failed")
        embed = ui.result_embed(name, "failed", "internal error (details in the logs)", "", "", time.time() - job["started"])
        await rep.post(getattr(user, "mention", "") if ping else "", None, mention=ping, embed=embed)
    finally:
        monitor.cancel()
        _ACTIVE.pop(job["id"], None)
        if _INFLIGHT.get(key) is fut:
            _INFLIGHT.pop(key, None)
        if not fut.done():
            fut.set_result((None, job.get("error") or "echec"))
        job["finished"] = time.time()
        job.pop("_board", None)
        if job["status"] == "annule":
            final_status = "cancelled"
        elif job["status"] == "echec":
            final_status = "failed"
        _record_stat("deobf", job["user"], name, final_status, final_engine, time.time() - job["started"])
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)
        _journal_save()


def _save_job_log(job: dict, res: dict) -> None:
    """Journal technique complet d'un job (logs/jobs/<id>.log) : reserve a l'administrateur, secrets masques."""
    try:
        d = _find_suite() / "logs" / "jobs"
        d.mkdir(parents=True, exist_ok=True)
        keep = sorted(d.glob("*.log"), key=lambda p: p.stat().st_mtime)
        for old in keep[:-60]:
            try:
                old.unlink()
            except OSError:
                pass
        body = (f"job {job['id']} fichier {job['name']} moteur {res.get('engine')} code {res.get('code')} "
                f"ok {res.get('ok')}\ndetecte : {res.get('detected')}\n--- journal du moteur ---\n{res.get('log') or ''}\n")
        (d / f"{job['id']}.log").write_text(_mask(body), encoding="utf-8")
    except OSError:
        pass



async def cancel_current(interaction: discord.Interaction, nom: Optional[str] = None) -> None:
    """/deobf_annuler [nom] : arrete les jobs en cours (tous, ou ceux dont le nom contient `nom`) et leurs processus."""
    targets = [j for j in list(_ACTIVE.values()) if not nom or nom.lower() in j["name"].lower()]
    if not targets:
        await interaction.response.send_message("Aucun job en cours" + (f" correspondant a `{nom}`." if nom else "."), ephemeral=True)
        return
    who = getattr(interaction.user, "name", None) or str(getattr(interaction.user, "id", "?"))
    for j in targets:
        j["cancelled"] = who
        _kill_tree(j.get("pid"))
        _log(f"job {j['id']} annule par {who}")
    await interaction.response.send_message(f"{len(targets)} job(s) annule(s) : " + ", ".join(f"`{j['name']}`" for j in targets)[:1800],
                                            ephemeral=True)


# ── /deobf_dernier et /deobf_etat ──────────────────────────────────────────────

def _saved_results(count: int) -> list[Path]:
    d = _results_dir()
    files = [p for p in d.iterdir() if p.is_file() and p.name != "journal.json"]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:max(1, count)]


async def send_last_results(interaction: discord.Interaction, count: int = 1) -> None:
    """Renvoie les derniers resultats sauvegardes (results/) : en reponse a CETTE interaction (jeton neuf, donc
    ca marche meme si les MP sont fermes ou si le job a depasse 15 min) ET en MP si possible."""
    await interaction.response.defer(ephemeral=True)
    try:
        chosen = _saved_results(count)
    except OSError as exc:
        await interaction.followup.send(f"Cannot read results/: `{exc}`", ephemeral=True)
        return
    if not chosen:
        await interaction.followup.send("No saved result yet (no job finished since install).",
                                        ephemeral=True)
        return
    items = [(p.name, p.read_bytes()) for p in chosen]
    items, notes = _pack_files(items)
    listing = "\n".join(f"- `{p.name}` ({p.stat().st_size // 1024} Ko)" for p in chosen)
    try:
        await interaction.followup.send(
            f"Dernier(s) resultat(s) :\n{listing}" + ("\n" + "\n".join(notes) if notes else ""),
            files=[discord.File(io.BytesIO(b), filename=n) for n, b in items], ephemeral=True)
    except (discord.HTTPException, discord.NotFound) as exc:
        await interaction.followup.send(f"Envoi impossible : `{exc}`", ephemeral=True)
        return
    ok, why = await _dm_send(interaction.user, content="Copy of the latest results:\n" + listing, files=items)
    if not ok:
        await _notify(interaction, f"(Envoi en MP impossible : {why})")


async def status_text(interaction: discord.Interaction) -> str:
    """Rapport de diagnostic : machine, prerequis, job en cours, derniers jobs, test d'envoi de MP."""
    import platform
    lines = [f"discord.py {discord.__version__} | Python {platform.python_version()} | {platform.system()} {platform.machine()}"]
    try:
        bs = _bootstrap()
        st = await asyncio.to_thread(bs.status)
        pf = await asyncio.to_thread(bs.preflight)
        lines.append(f"Node : {st.get('node') or 'absent'} | Luau patche pret : {st.get('luau_ready')}")
        lines.append("Prerequis : " + ("OK" if pf["ready"] else
                                       ("BLOQUE : " + pf["blocker"] if pf["blocker"] else "a preparer : " + "; ".join(pf["steps"]))))
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Prerequis : verification impossible ({exc})")
    cpu = _cpu_limits()
    lines.append(f"CPU : {cpu['cores']} coeur(s) visibles, {cpu['affinity']} autorises, limite hebergeur "
                 f"{('%.2f coeur' % cpu['quota']) if cpu['quota'] else 'aucune'} -> utilisable : {cpu['effective']:.2f}"
                 + (" (impose par DEOBF_FORCE_CPU)" if cpu.get("forced") else "")
                 + (f"  ⚠️ machine ~{_cpu_factor(cpu):.0f}x plus lente que 4 coeurs" if cpu["effective"] < 1.5 else ""))
    if cpu["effective"] < 1.0:
        weak_fast = os.environ.get("DEOBF_WEAK_MODE", "complet").strip().lower() in ("rapide", "fast")
        lines.append("Machine faible : mode " + ("RAPIDE (tentatives limitees)" if weak_fast else
                     f"COMPLET (toutes les tentatives, jusqu'a {WEAK_LIFT_S // 60} min ; DEOBF_WEAK_MODE=rapide pour aller vite)"))
    lines.append(f"Dossier : {_find_suite()}")
    mem = _mem_limits()
    lines.append("Memoire : " + (f"limite du conteneur {mem['limit_mb']} Mo, utilisee {mem['used_mb']} Mo -> "
                                 if mem["limit_mb"] else "pas de limite de conteneur -> ")
                 + (f"disponible {mem['avail_mb']} Mo" if mem["avail_mb"] is not None else "inconnue"))
    act = list(_ACTIVE.values())
    lines.append(f"Jobs en cours : {len(act)}" + ("" if act else " (aucun)"))
    for j in act[:10]:
        lines.append(f"  `{j['name'][:30]}` depuis {int(time.time() - j['started'])} s -- {STAGES[j.get('stage', 0)][0]}"
                     + (f" -- {j['activity']}" if j.get("activity") else ""))
    history = (_JOBS[-5:] if _JOBS else _journal_load()[-5:])
    lines.append("Derniers jobs :" + ("" if history else " aucun"))
    for j in reversed(history):
        when = time.strftime("%d/%m %H:%M", time.localtime(j.get("started", 0)))
        lines.append(f"  {when} {j.get('name', '?')[:30]:30} {j.get('status', '?'):9} livraison={j.get('delivered', '?')} "
                     f"{j.get('elapsed', 0)}s" + (f" -- {j['error'][:80]}" if j.get("error") else ""))
    ch = _channel_of(interaction)
    try:
        probe = await ch.send("Bot write test in this channel (this message will be deleted).",
                              allowed_mentions=discord.AllowedMentions.none())
        try:
            await probe.delete()
        except discord.HTTPException:
            pass
        lines.append("Ecriture dans ce salon (suivi + fichier du resultat) : OK")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Ecriture dans ce salon : ECHEC -- {exc} (donne au bot les droits « Envoyer des messages » et "
                     "« Joindre des fichiers » ici ; sinon le suivi passe par la reponse de la commande)")
    ok, why = await _dm_send(interaction.user, content="DM test: if you can read this, direct messages work.")
    lines.append("Test d'envoi de MP (secours) : " + ("OK (message recu)" if ok else f"ECHEC -- {why}"))
    try:
        lines.append(f"Resultats sauvegardes : {len(_saved_results(10 ** 6)) if any(_results_dir().iterdir()) else 0} (/deobf_dernier)")
    except OSError:
        pass
    return "\n".join(lines)


_BOT_DIR   = Path(__file__).parent


def _find_suite() -> Path:
    """Dossier de la suite de moteurs (celui qui contient deobf_router.py) :
    $DEOBF_SUITE_DIR, le dossier parent de ce fichier (cogs/ dans la suite),
    puis ./yslem_deobf_suite a cote du bot."""
    cands = [os.environ.get("DEOBF_SUITE_DIR"), _BOT_DIR.parent, _BOT_DIR / "yslem_deobf_suite",
             Path.cwd() / "yslem_deobf_suite"]
    for c in cands:
        if c and (Path(c) / "deobf_router.py").exists():
            return Path(c)
    return _BOT_DIR / "yslem_deobf_suite"


_SUITE_DIR = _find_suite()
_ROUTER = _SUITE_DIR / "deobf_router.py"

# Ports refusés même si l'IP est publique.
_BLOCKED_PORTS = {22, 25, 2375, 2376, 3306, 5432, 6379, 9200, 27017}

# ── protection SSRF ────────────────────────────────────────────────────────────

def _is_unsafe_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


class _SSRFResolver(aiohttp.resolver.ThreadedResolver):
    async def resolve(self, host: str, port: int = 0,
                      family: socket.AddressFamily = socket.AF_INET):
        if port and port in _BLOCKED_PORTS:
            raise OSError(f"SSRF: port {port} blocked")
        records = await super().resolve(host, port, family)
        safe = [r for r in records if not _is_unsafe_ip(r["host"])]
        if not safe:
            raise OSError(f"SSRF: no public address for {host!r}")
        return safe


def _check_hop(parsed) -> None:
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL doit commencer par http(s)://")
    if not parsed.hostname:
        raise ValueError("invalid URL (no host)")
    if parsed.port and parsed.port in _BLOCKED_PORTS:
        raise ValueError(f"Port {parsed.port} blocked")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return  # nom de domaine : le résolveur filtre les IP à la connexion
    if _is_unsafe_ip(str(ip)):
        raise ValueError(f"non-public IP blocked ({ip})")


def _normalize_url(url: str) -> str:
    """Transforme les liens « page » courants en liens bruts (sinon on telechargerait du HTML).

    Plateformes supportees :
      GitHub blob, Pastebin, GitHub Gist, Hastebin, paste.ee, pastecode.io, rentry.co,
      sourceb.in, pastes.dev, discord CDN (direct, pas de conversion necessaire).
    """
    url = url.strip().strip("<>")
    # GitHub blob → raw.githubusercontent.com
    m = re.match(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/blob/(.+)$", url, re.I)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3).split('?')[0]}"
    # Pastebin → /raw/
    m = re.match(r"https?://(?:www\.)?pastebin\.com/(?!raw/)([A-Za-z0-9]+)/?$", url, re.I)
    if m:
        return f"https://pastebin.com/raw/{m.group(1)}"
    # GitHub Gist sans fichier specifique
    m = re.match(r"https?://gist\.github\.com/([^/]+)/([0-9a-f]+)/?$", url, re.I)
    if m:
        return f"https://gist.githubusercontent.com/{m.group(1)}/{m.group(2)}/raw"
    # Hastebin (hastebin.com/KEY ou hastebin.com/KEY.ext)
    m = re.match(r"https?://(?:www\.)?hastebin\.com/(?!raw/)([A-Za-z0-9]+)(?:\.\w{1,8})?/?$", url, re.I)
    if m:
        return f"https://hastebin.com/raw/{m.group(1)}"
    # paste.ee (paste.ee/p/KEY → paste.ee/r/KEY)
    m = re.match(r"https?://(?:www\.)?paste\.ee/p/([A-Za-z0-9]+)/?$", url, re.I)
    if m:
        return f"https://paste.ee/r/{m.group(1)}"
    # pastecode.io (pastecode.io/s/KEY → pastecode.io/raw/KEY)
    m = re.match(r"https?://(?:www\.)?pastecode\.io/s/([A-Za-z0-9]+)/?$", url, re.I)
    if m:
        return f"https://pastecode.io/raw/{m.group(1)}"
    # rentry.co (rentry.co/KEY → rentry.co/KEY/raw)
    m = re.match(r"https?://(?:www\.)?rentry\.co/([A-Za-z0-9_-]+)/?$", url, re.I)
    if m:
        return f"https://rentry.co/{m.group(1)}/raw"
    # sourceb.in (sourceb.in/KEY → sourceb.in/KEY/raw)
    m = re.match(r"https?://(?:www\.)?sourceb\.in/([A-Za-z0-9]+)/?$", url, re.I)
    if m:
        return f"https://sourceb.in/{m.group(1)}/raw"
    # pastes.dev (pastes.dev/KEY → api.pastes.dev/KEY)
    m = re.match(r"https?://(?:www\.)?pastes\.dev/([A-Za-z0-9]+)/?$", url, re.I)
    if m:
        return f"https://api.pastes.dev/{m.group(1)}"
    return url


_PASTE_HINT: dict[str, str] = {
    "hastebin.com": "hastebin.com/raw/KEY",
    "paste.ee": "paste.ee/r/KEY",
    "pastecode.io": "pastecode.io/raw/KEY",
    "rentry.co": "rentry.co/KEY/raw",
    "sourceb.in": "sourceb.in/KEY/raw",
    "pastes.dev": "api.pastes.dev/KEY",
    "pastebin.com": "pastebin.com/raw/KEY",
    "github.com": "raw.githubusercontent.com/…",
    "gist.github.com": "gist.githubusercontent.com/…/raw",
}


_HTTP_SEM: Optional[asyncio.Semaphore] = None
_HTTP_PARALLEL = 4                         # telechargements simultanes (protege la machine et les serveurs distants)
_FETCH_CACHE: dict = {}                    # url normalisee -> (heure, nom, donnees, info)
_FETCH_TTL = 120
_FETCH_CACHE_MAX_BYTES = 24 * 1024 * 1024


def _http_sem() -> asyncio.Semaphore:
    global _HTTP_SEM
    if _HTTP_SEM is None:                  # cree dans la boucle en marche (Python < 3.10 lie le semaphore a la boucle)
        _HTTP_SEM = asyncio.Semaphore(_HTTP_PARALLEL)
    return _HTTP_SEM


def _fetch_cache_put(key: str, name: str, data: bytes, info: dict) -> None:
    now = time.monotonic()
    for k in [k for k, v in _FETCH_CACHE.items() if now - v[0] > _FETCH_TTL]:
        _FETCH_CACHE.pop(k, None)
    _FETCH_CACHE[key] = (now, name, data, dict(info))
    while len(_FETCH_CACHE) > 8 or sum(len(v[2]) for v in _FETCH_CACHE.values()) > _FETCH_CACHE_MAX_BYTES:
        _FETCH_CACHE.pop(min(_FETCH_CACHE, key=lambda k: _FETCH_CACHE[k][0]), None)


async def _fetch_url(url: str, info: Optional[dict] = None, cache: bool = False) -> tuple[str, bytes]:
    """Telecharge `url` (garde-fous SSRF, 7 Mo, redirections re-verifiees, 4 telechargements simultanes au plus).
    `info` (facultatif) recoit : status, redirects (hotes traverses), final_url, content_type. `cache=True` : 2 min de cache."""
    url = _normalize_url(url)
    if cache and url in _FETCH_CACHE and time.monotonic() - _FETCH_CACHE[url][0] <= _FETCH_TTL:
        _, name, data, cached_info = _FETCH_CACHE[url]
        if info is not None:
            info.update(cached_info, cached=True)
        return name, data
    async with _http_sem():
        name, data = await _fetch_url_unlimited(url, info)
    if cache:
        _fetch_cache_put(url, name, data, info or {})
    return name, data


async def _fetch_url_unlimited(url: str, info: Optional[dict] = None) -> tuple[str, bytes]:
    info = info if info is not None else {}
    info.update(status=None, redirects=[], final_url=url, content_type="")
    timeout   = aiohttp.ClientTimeout(total=_DOWNLOAD_TIMEOUT)
    connector = aiohttp.TCPConnector(resolver=_SSRFResolver())
    current   = url

    _UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    async with aiohttp.ClientSession(timeout=timeout, connector=connector,
                                     headers={"User-Agent": _UA, "Accept": "text/plain,*/*"}) as session:
        for _ in range(_MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            _check_hop(parsed)
            async with session.get(current, allow_redirects=False) as resp:
                info["status"] = resp.status
                if resp.status in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("Location")
                    if not loc:
                        raise ValueError(f"Redirection {resp.status} sans Location")
                    current = str(resp.url.join(URL(loc)))
                    info["redirects"].append(urlparse(current).hostname or "?")
                    info["final_url"] = current
                    continue
                info["content_type"] = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if resp.status != 200:
                    raise ValueError(f"server replied {resp.status}")
                # Une page HTML = l'utilisateur a envoye un lien de navigation, pas un lien brut.
                # On le dit clairement plutot que de lui livrer du HTML comme si c'etait un script.
                if info["content_type"].startswith("text/html"):
                    host = urlparse(current).hostname or ""
                    hint = next((v for k, v in _PASTE_HINT.items() if k in host), None)
                    msg = "URL returned an HTML page — use the direct raw link"
                    if hint:
                        msg += f" (expected format: {hint})"
                    raise ValueError(msg)
                # NB : StreamReader.read(n) rend ce qui est deja arrive (souvent < 64 Ko) et PAS n octets :
                # l'ancien code tronquait silencieusement les gros fichiers. On lit jusqu'a la fin.
                buf = bytearray()
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    buf += chunk
                    if len(buf) > _MAX_BYTES:
                        raise ValueError(f"Fichier > {_MAX_BYTES // (1024*1024)} Mo")
                data = bytes(buf)
                if not data:
                    raise ValueError("Reponse vide")
                fname = re.sub(r"[^\w.\-]", "_", parsed.path.rsplit("/", 1)[-1])[:80] or "distant.lua"
                return fname, data

    raise ValueError("Trop de redirections")


# ── analyse heuristique statique ───────────────────────────────────────────────

_BANNERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Luraph Obfuscator v([\d.]+)", re.I), "Luraph v{0}"),
    (re.compile(r"lura\.ph",                   re.I), "Luraph (lura.ph)"),
    (re.compile(r"MoonSec",                    re.I), "MoonSec"),
    (re.compile(r"Prometheus",                 re.I), "Prometheus"),
    (re.compile(r"IronBrew",                   re.I), "IronBrew"),
    (re.compile(r"Konstant",                   re.I), "Konstant"),
    (re.compile(r"Vigilant",                   re.I), "Vigilant"),
    (re.compile(r"PSU[\s_-]?obfuscator",       re.I), "PSU Obfuscator"),
]

_VM_SIGNALS: list[tuple[re.Pattern, str, int]] = [
    (re.compile(r"bit32\.(bxor|band|bor|btest|lshift|rshift)"),
     "bit32.* — arithmétique opaque", 1),
    (re.compile(r"buffer\.(readu?8|readu?16|readu?32|writeu?8|writeu?16|writeu?32|fromstring|copy|create)"),
     "buffer.* — bytecode Luau v15+", 2),
    (re.compile(r"\bgetfenv\s*\(|\bsetfenv\s*\("),
     "getfenv/setfenv — cible executor (pas le jeu)", 2),
    (re.compile(r"__iter\b"),
     "__iter — Luau uniquement, souvent anti-décompilation", 2),
    (re.compile(r"setmetatable\(\{.{0,40}\}\s*,\s*\{.{0,80}\}\)\s*:[A-Za-z_]\w*\(\)\s*\("),
     "auto-invocation setmetatable({},{...}):X()(…)", 3),
    (re.compile(r"while\s+true\s+do\s+if\s+\w+\s*[<>]=?"),
     "boucle dispatch à variable d'état (control-flow flattening)", 2),
    (re.compile(r"loadstring\s*\("),
     "loadstring() imbriqué — possible stage 2 caché", 1),
]

_SUSPICIOUS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"discord(app)?\.com/api/webhooks",      re.I), "exfiltration", "webhook Discord en clair"),
    (re.compile(r"\bROBLOSECURITY\b",                   re.I), "exfiltration", "cookie de session Roblox"),
    (re.compile(r"\bsetclipboard\s*\(",                  re.I), "exfiltration", "setclipboard()"),
    (re.compile(r"\bwritefile\s*\(|\breadfile\s*\(",     re.I), "filesystem",   "writefile/readfile"),
    (re.compile(r"\bgetgenv\s*\(|\bgetrenv\s*\(",        re.I), "executor-api", "getgenv/getrenv"),
    (re.compile(r"\bhookfunction\s*\(|\bhookmetamethod\s*\(", re.I), "hooking", "hookfunction/hookmetamethod"),
    (re.compile(r"\bqueue_on_teleport\s*\(",             re.I), "persistence",  "queue_on_teleport"),
    (re.compile(r"https?://[^\s\"')]+",                  re.I), "network",      "URL en clair"),
    (re.compile(r"\bgame:HttpGet\s*\(|\brequest\s*\{|\bsyn\.request\s*\(", re.I),
     "network", "appel réseau direct"),
]


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    c = Counter(data)
    t = len(data)
    return -sum((v / t) * math.log2(v / t) for v in c.values())


def _clip(text: str) -> str:
    if len(text) <= _SCAN_HEAD + _SCAN_TAIL:
        return text
    return text[:_SCAN_HEAD] + "\n--[[ ... truncated for analysis ... ]]\n" + text[-_SCAN_TAIL:]


def _heuristic(text: str, raw: bytes, filename: str) -> dict:
    text    = _clip(text)
    lines   = text.splitlines() or [""]
    longest = max(len(l) for l in lines)
    banners, vm_hits, sus_hits, vm_score = [], [], [], 0

    for pat, label in _BANNERS:
        m = pat.search(text[:2000]) or pat.search(text[-2000:])
        if m:
            try:
                banners.append(label.format(*m.groups()))
            except (IndexError, KeyError):
                banners.append(label)

    for pat, label, weight in _VM_SIGNALS:
        count = len(pat.findall(text))
        if count:
            vm_hits.append((f"{label} (×{count})", weight))
            vm_score += weight

    for pat, cat, label in _SUSPICIOUS:
        for m in pat.finditer(text):
            snippet = text[max(0, m.start() - 20):m.end() + 20].replace("\n", " ")
            sus_hits.append((label, cat, snippet))
            if len(sus_hits) >= 15:
                break

    exfil = any(c in ("exfiltration", "hooking") for _, c, _ in sus_hits)
    if exfil:
        verdict = "⚠️ Signaux suspects en clair — vérification manuelle requise"
    elif vm_score >= 5:
        verdict = "🔒 Obfuscation VM lourde — contenu réel opaque à l'analyse statique"
    elif banners or vm_score >= 2:
        verdict = "🔍 Obfuscation probable — analyse de surface seulement"
    else:
        verdict = "ℹ️ Pas de signal fort (ne garantit pas l'innocuité)"

    return {
        "filename": filename,
        "size": len(raw),
        "lines": len(lines),
        "longest_ratio": round(longest / max(len(text), 1), 3),
        "entropy": round(_entropy(raw[:2_000_000]), 2),
        "banners": banners,
        "vm_hits": vm_hits,
        "vm_score": vm_score,
        "sus_hits": sus_hits,
        "verdict": verdict,
        "exfil": exfil,
    }


# ── lua_scanner (fusionné depuis lua_scanner.py) ───────────────────────────────
# Signatures d'obfuscateurs connus + API dangereuses + webhooks/tokens en
# clair. Pure analyse statique par motifs — pas d'exécution.

_SIGS = [
    # (id, display_name, pattern_list) – any one match ⇒ detected
    ("luraph",      "Luraph",
     [r'LPH[A-Za-z0-9+/!#$%&()*\-;<=>?@^_`{|}~]{20,}',
      r'UGiZrsFzK|setfenv.*Luraph',
      r'ConstantsOffset|PrototypesOffset|InstructionsOffset']),

    ("moonsec2",    "MoonSec v2",
     [r'_MOONSEC_|_0x[0-9a-f]{4}_',
      r'local\s+_\s*=\s*\{.*#_\s*==',
      r'\bMoonSec\b']),

    ("moonsec3",    "MoonSec v3",
     [r'__LUAUW|_LUAU_',
      r'local\s+\w+\s*=\s*\{\s*\[0\]\s*=']),

    ("ironbrew",    "IronBrew 2",
     [r'--\s*IronBrew\s*2|IB2_',
      r'local\s+\w+\s*=\s*"[A-Za-z0-9+/=]{500,}".*Deserialize']),

    ("bytec",       "ByteCode Custom VM",
     [r'local\s+\w+\s*=\s*\{[0-9,\s]{300,}\}',
      r'Bytecode|bytecode|BYTECODE']),

    ("xor_enc",     "XOR / string.char chain",
     [r'string\.char\s*\([^)]{40,}\)',
      r'\\x[0-9a-fA-F]{2}(?:\\x[0-9a-fA-F]{2}){15,}']),

    ("loadstr_b64", "loadstring + Base64",
     [r'loadstring\s*\(\s*(?:game\.)?(?:HttpGet|http\.request)',
      r'loadstring\s*\([^)]*base64[^)]*\)',
      r'require\s*\(\s*[0-9]{6,}\s*\)']),
]

# Ce ne sont pas des obfuscateurs : juste l'API d'un executor précis. Un
# script qui les utilise est écrit POUR cet executor, ce qui ne dit rien
# sur sa malveillance (contrairement à "synapse" qu'on avait à tort rangé
# avec les vrais obfuscateurs ci-dessus, ce qui le faisait aussi compter
# dans le score de suspicion pour rien).
_EXECUTOR_SIGS = [
    ("synapse",     "Synapse X",
     [r'Synapse\s*X|syn\.(?:request|protect_gui|is_cached)',
      r'getsynasset|getcallingscript']),
]

_DANGER_PATS = [
    ("http_get",     r'\b(?:game:HttpGet|HttpService:GetAsync|http\.request|syn\.request|request)\s*\(',
     "Requête HTTP (peut exfiltrer des données)"),
    ("http_post",    r'\bHttpService:PostAsync\s*\(',
     "HTTP POST (envoi de données vers serveur externe)"),
    ("loadstring",   r'\bloadstring\s*\(',
     "loadstring (exécution de code dynamique)"),
    ("getgenv",      r'\bgetgenv\s*\(\)',
     "getgenv (accès aux globals de l'executor)"),
    ("syn_protect",  r'\bsyn\.(?:protect_gui|get_thread_identity|get_hidden_gui)\b',
     "Synapse API avancée (cache l'interface)"),
    ("remote_exec",  r'\bRemoteEvent:FireServer|RemoteFunction:InvokeServer',
     "Appel réseau Roblox (peut contourner serveur)"),
    ("clipboard",    r'\bsetclipboard\s*\(',
     "Copie dans le presse-papiers (vol de données)"),
    ("environ",      r'\bgetfenv\s*\(0\)|setfenv\s*\(0',
     "Manipulation de l'environnement global"),
    ("decompile",    r'\bdecompile\s*\(',
     "Décompilation de scripts"),
    ("kill_game",    r'\bgame:Shutdown\b|\bPlayers\.LocalPlayer:Kick\b',
     "Kick/shutdown forcé"),
    ("obf_self",     r'\bloadstring\s*\(\s*[\'"][A-Za-z0-9+/=]{200,}',
     "Auto-déchiffrement (payload caché dans le code)"),
]

_URL_RE      = re.compile(r'https?://[^\s\'")\]>]{8,}', re.I)
_WEBHOOK_RE  = re.compile(
    r'https?://(?:discord(?:app)?\.com/api/webhooks|canary\.discord\.com/api/webhooks)/[0-9]+/[A-Za-z0-9_-]+',
    re.I)
_TOKEN_RE    = re.compile(
    r'\b(?:token|Token|TOKEN)\s*[=:]\s*["\'][A-Za-z0-9._-]{50,}["\']|\b[A-Za-z0-9]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}')


def _decode_strchar(code: str) -> list[str]:
    """Decode string.char(n,n,...) sequences."""
    found = []
    for m in re.finditer(r'string\.char\s*\(([0-9,\s]+)\)', code):
        try:
            nums = [int(x.strip()) for x in m.group(1).split(',') if x.strip()]
            decoded = bytes(n for n in nums if 0 < n < 256).decode('utf-8', errors='replace')
            if len(decoded) >= 4:
                found.append(decoded)
        except Exception:
            pass
    return found


def _decode_b64_blobs(code: str) -> list[str]:
    """Try to base64-decode suspicious long strings."""
    decoded = []
    for m in re.finditer(r'["\']([A-Za-z0-9+/=]{60,})["\']', code):
        s = m.group(1)
        try:
            padded = s + '=' * ((-len(s)) % 4)
            raw = base64.b64decode(padded, validate=True)
            text = raw.decode('utf-8', errors='replace')
            if text.isprintable() and len(text) > 10:
                decoded.append(text[:300])
        except Exception:
            pass
    return decoded


@dataclass
class ScanResult:
    obfuscators: list[str]   = field(default_factory=list)
    executors: list[str]     = field(default_factory=list)   # executor cible (pas un signal de malveillance)
    dangers: list[tuple]     = field(default_factory=list)   # (id, description)
    urls: list[str]          = field(default_factory=list)
    webhooks: list[str]      = field(default_factory=list)
    tokens_found: bool       = False
    decoded_strings: list[str] = field(default_factory=list)
    verdict: str             = "✅ PROPRE"
    verdict_level: int       = 0   # 0=clean 1=suspect 2=dangerous


def scan(code: str) -> ScanResult:
    r = ScanResult()
    code = _clip(code)

    # 1. Obfuscator detection
    for obf_id, name, pats in _SIGS:
        for p in pats:
            if re.search(p, code, re.I | re.S):
                if name not in r.obfuscators:
                    r.obfuscators.append(name)
                break

    # 1b. Executor targeting (séparé : pas un signal de malveillance)
    for exec_id, name, pats in _EXECUTOR_SIGS:
        for p in pats:
            if re.search(p, code, re.I | re.S):
                if name not in r.executors:
                    r.executors.append(name)
                break

    # 2. Danger APIs
    seen_ids = set()
    for did, pat, desc in _DANGER_PATS:
        if did not in seen_ids and re.search(pat, code, re.I | re.S):
            r.dangers.append((did, desc))
            seen_ids.add(did)

    # 3. URLs
    all_urls = _URL_RE.findall(code)
    r.webhooks = list({m for m in _WEBHOOK_RE.findall(code)})
    r.urls = list({u for u in all_urls if u not in r.webhooks})[:20]

    # 4. Token patterns
    r.tokens_found = bool(_TOKEN_RE.search(code))

    # 5. String decoding
    r.decoded_strings = (_decode_strchar(code) + _decode_b64_blobs(code))[:10]

    # 6. Verdict
    score = 0
    if r.webhooks:
        score += 3
    if r.tokens_found:
        score += 3
    if any(d[0] in ("http_get", "http_post") for d in r.dangers):
        score += 1
    if any(d[0] == "loadstring" for d in r.dangers):
        score += 1
    if r.obfuscators:
        score += 1
    if any(d[0] == "getgenv" for d in r.dangers):
        score += 1

    if score >= 4:
        r.verdict = "🔴 DANGEREUX"
        r.verdict_level = 2
    elif score >= 2:
        r.verdict = "🟠 SUSPECT"
        r.verdict_level = 1
    else:
        r.verdict = "🟢 PROPRE"
        r.verdict_level = 0

    return r


def _report_txt(h: dict, static, box: dict | None, rc: int, ident: dict | None = None) -> str:
    """Full text report attached to the Discord reply."""
    lines = [
        f"=== Rapport d'analyse — {h['filename']} ===",
        f"Taille : {h['size']} o  |  Lignes : {h['lines']}  |  "
        f"Ratio max-ligne : {h['longest_ratio']}  |  Entropie : {h['entropy']}/8.0",
        "",
        "── Obfuscateurs détectés ─────────────────────────",
    ]
    lines += [f"  • {b}" for b in h["banners"]] or ["  (aucune bannière — peut être retirée)"]
    if ident:
        lines += ["", "── Identification (détecteur de la suite + avis facultatif d'un modèle) ──"]
        lines += ["  " + l for l in ident["summary"].splitlines()]
    lines += ["", f"── Signaux VM (score {h['vm_score']}) ─────────────────"]
    lines += [f"  • {l} [poids {w}]" for l, w in h["vm_hits"]] or ["  (aucun)"]
    lines += ["", "── Chaînes suspectes en clair ──────────────────────"]
    lines += [f"  [{c}] {l} :: …{s}…" for l, c, s in h["sus_hits"]] or \
              ["  (aucune — dans un script bien obfusqué elles sont chiffrées)"]
    lines += ["", f"Verdict heuristique : {h['verdict']}", ""]

    # lua_scanner
    if static is not None:
        lines += ["── lua_scanner (signatures connues) ──────────────"]
        lines.append(f"  Verdict : {static.verdict}")
        if getattr(static, "obfuscators", []):
            lines.append(f"  Obfuscateurs : {', '.join(static.obfuscators)}")
        if getattr(static, "executors", []):
            lines.append(f"  Executor ciblé (pas un obfuscateur) : {', '.join(static.executors)}")
        if getattr(static, "urls", []):
            lines.append("  URLs :")
            lines += [f"    {u}" for u in static.urls[:10]]
        if getattr(static, "webhooks", []):
            lines.append("  Webhooks :")
            lines += [f"    {w}" for w in static.webhooks]
        lines.append("")

    # sandbox
    lines += ["── Sandbox ─────────────────────────────────────────"]
    if box is None:
        lines.append("  Non exécuté (fichier trop grand pour le sandbox).")
    elif rc in (-9, -24):
        lines.append("  TUÉS — dépassement mémoire ou CPU.")
    elif not box.get("ok") and box.get("error"):
        lines.append(f"  Erreur : {box['error'][:300]}")
    else:
        lines.append("  Exécution terminée normalement.")
        calls = box.get("calls", [])
        if calls:
            lines.append(f"  Appels interceptés ({len(calls)}) :")
            for c in calls[:20]:
                if c.get("type") == "http":
                    lines.append(f"    🌐 {c.get('method','GET')} → {c.get('url','')[:120]}")
                    if c.get("body_preview"):
                        lines.append(f"       body : {c['body_preview'][:80]}")
                elif c.get("type") == "loadstring":
                    lines.append(f"    🔁 loadstring → {c.get('preview','')[:80]}")
                elif c.get("type") == "clipboard":
                    lines.append(f"    📋 setclipboard → {c.get('value','')[:80]}")
                elif c.get("type") == "file":
                    lines.append(f"    💾 {c.get('op','?')} → {c.get('path','')[:80]}")
        out = box.get("output", [])
        if out:
            lines.append(f"  Sortie print ({len(out)} lignes) :")
            lines += [f"    {l}" for l in out[:15]]

    lines += [
        "",
        "─────────────────────────────────────────────────────────",
        "⚠ AVERTISSEMENT : ceci est une analyse automatisée (heuristiques statiques + sandbox).",
        "   Elle ne décode pas les constantes chiffrées, ne décompile pas une VM privée",
        "   et ne remplace pas une revue manuelle du code source réel.",
        "   L'absence de signal n'est PAS une preuve que le script est sûr.",
    ]
    # /analyse est PUBLIC : le rapport ne doit jamais contenir un jeton de webhook en clair
    return _mask_hooks("\n".join(lines))


# ── sandbox helper ─────────────────────────────────────────────────────────────

async def _run_sandbox(code: str) -> tuple[dict | None, int]:
    """Trace de comportement (HttpGet, loadstring, requetes, fichiers...) via lua_sandbox.py de la suite :
    le script tourne dans le Luau patche du harnais, JAMAIS dans le processus du bot, avec limite CPU et
    arret du groupe de processus au timeout. Contrat : code Lua sur stdin -> un objet JSON sur stdout."""
    import signal
    sandbox = next((str(d / "lua_sandbox.py") for d in (_find_suite(), _BOT_DIR, _BOT_DIR.parent)
                    if (d / "lua_sandbox.py").exists()), None)
    if sandbox is None:
        return {"ok": False, "error": "lua_sandbox.py introuvable (dossier yslem_deobf_suite absent ?)"}, 0
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", sandbox,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(Path(sandbox).parent),
            start_new_session=True,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(input=code.encode("utf-8", "replace")),
                timeout=_SANDBOX_TIMEOUT,
            )
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            await proc.wait()
            return {"ok": False, "error": f"Timeout ({_SANDBOX_TIMEOUT}s)"}, -24
        rc  = proc.returncode or 0
        if not stdout.strip():
            return {"ok": False, "error": f"le bac a sable n'a rien repondu (code {rc})"}, rc
        return json.loads(stdout.decode(errors="replace")), rc
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}, 0


# ── embed builder ──────────────────────────────────────────────────────────────

def _build_embed(h: dict, static, box: dict | None, rc: int, ident: dict | None = None) -> discord.Embed:
    killed = rc in (-9, -24)
    exfil  = h["exfil"]

    if killed or exfil or h["vm_score"] >= 5:
        color = 0xFF0000   # rouge vif — danger/kill
    elif h["vm_score"] >= 2 or h["banners"] or (box and box.get("error")):
        color = 0xB22222   # rouge brique — suspect
    else:
        color = 0x8B0000   # rouge sombre — OK

    embed = discord.Embed(
        title=f"🔍 Analyse — {h['filename']}"[:250],
        description=h["verdict"],
        color=color,
    )

    # Structure
    embed.add_field(
        name="📊 Structure",
        value=f"`{h['size']}` o · `{h['lines']}` lignes · entropie `{h['entropy']}/8.0`",
        inline=False,
    )

    # Obfuscateurs
    ob_val = "\n".join(h["banners"])
    if ident:                                   # detecteur de la suite (+ avis du modele si une cle est fournie)
        ob_val = (ob_val + "\n" if ob_val else "") + ident["summary"]
    embed.add_field(
        name="🧩 Obfuscator(s) detected",
        value=_mask_hooks(ob_val or "No banner found")[:1024],
        inline=False,
    )

    # Signaux VM
    vm_lines = "\n".join(l for l, _ in h["vm_hits"][:6]) or "Aucun signal"
    embed.add_field(name=f"⚙️ Signaux VM (score {h['vm_score']})", value=vm_lines[:1024], inline=False)

    # Chaînes suspectes en clair
    sus_lines = "\n".join(f"[{c}] {l}" for l, c, _ in h["sus_hits"][:6]) or "Aucune"
    embed.add_field(name="🚨 Suspicious plain-text strings", value=sus_lines[:1024], inline=False)

    # lua_scanner
    if static is not None:
        sc_val = static.verdict
        if getattr(static, "obfuscators", []):
            sc_val += f"\n{', '.join(static.obfuscators)}"
        if getattr(static, "executors", []):
            sc_val += f"\nExecutor ciblé : {', '.join(static.executors)}"
        if getattr(static, "webhooks", []):
            sc_val += f"\n⚠️ Webhooks : {', '.join(_mask_hooks(w) for w in static.webhooks[:3])}"
        embed.add_field(name="🔬 lua_scanner", value=sc_val[:1024], inline=False)

    # Sandbox
    if box is None:
        sb_val = "Non exécuté (fichier > 384 Ko)"
    elif killed:
        sb_val = "💥 Tué — mémoire ou CPU dépassé" if rc == -9 else "⏱️ Tué — timeout CPU"
    elif not box.get("ok") and box.get("error"):
        sb_val = f"⚠️ Erreur :\n```{str(box['error'])[:200]}```"
    else:
        calls = box.get("calls", [])
        sb_val = f"✅ Terminé — {len(calls)} appel(s) intercepté(s)"
        http_urls = [c["url"] for c in calls if c.get("type") == "http" and c.get("url")]
        if http_urls:
            sb_val += "\n" + "\n".join(f"`{_mask_hooks(u)[:80]}`" for u in http_urls[:4])
    embed.add_field(name="⚡ Sandbox", value=sb_val[:1024], inline=False)

    embed.set_footer(
        text=(
            "⚠️  Analyse automatisée — ne remplace pas une revue manuelle. "
            "L'absence de signal ne prouve pas qu'un script est sûr."
        )
    )
    return embed


# ── cog ────────────────────────────────────────────────────────────────────────

async def recover_interrupted(bot, wait_ready: bool = True) -> int:
    """Au demarrage : un job reste « en cours » dans le journal = le bot s'est arrete pendant (redemarrage de
    l'hebergeur, crash, memoire...). On le DIT dans le salon, sur le message de suivi qui sinon resterait fige."""
    if wait_ready:
        for _ in range(900):                       # le cog peut etre charge AVANT la connexion du bot
            try:
                await bot.wait_until_ready()
                break
            except RuntimeError:
                await asyncio.sleep(2)
        else:
            return 0
    _load_jobs()
    n = 0
    for j in _JOBS:
        if j.get("status") != "en cours" or j.get("recovered"):
            continue
        j.update(status="interrompu", recovered=True, error="le bot s'est arrete pendant ce job")
        n += 1
        text = (f"⚠️ **Job interrupted** -- `{j.get('name', '?')}`: the bot stopped or restarted during the deobfuscation "
                "(redemarrage de l'hebergeur, plantage ou memoire insuffisante). Relance la commande ; "
                "/deobf_etat montre l'etat de la machine.")
        _log(f"job {j.get('id')} marque interrompu (redemarrage du bot)")
        try:
            ch = bot.get_partial_messageable(int(j["channel_id"]))
            if j.get("msg_id"):
                await ch.get_partial_message(int(j["msg_id"])).edit(content=text)
            else:
                await ch.send(text, allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:  # noqa: BLE001 - salon supprime, droits retires...
            _log(f"impossible de prevenir le salon du job interrompu : {exc}")
    if n:
        _journal_save()
    return n


class ToolsCog(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._sem = asyncio.Semaphore(_MAX_CONCURRENT)

    async def cog_load(self) -> None:
        async def _safe() -> None:
            try:
                await recover_interrupted(self.bot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                _log(f"reprise des jobs interrompus impossible : {exc}")
        self._recovery = asyncio.create_task(_safe())

    async def cog_unload(self) -> None:
        if getattr(self, "_recovery", None) and not self._recovery.done():
            self._recovery.cancel()
        for proc in list(_RUNNING):
            _kill_group(proc)
        for task in list(_BG):
            task.cancel()

    # ── /analyse ──────────────────────────────────────────────────────────────

    async def _analyse_core(self, text: str, raw: bytes, filename: str):
        """Heuristique + signatures + identification de l'obfuscateur + bac a sable -> (embed, rapport texte).
        Le calcul (regex) tourne dans un thread, l'identification (reseau eventuel) et le bac a sable EN PARALLELE."""
        def _static():
            h = _heuristic(text, raw, filename)
            try:
                st = scan(text)
            except Exception:       # noqa: BLE001 -- erreur cote scanner : on continue sans
                st = None
            return h, st

        async def _ident():
            try:
                suite = str(_find_suite())
                if suite not in sys.path:
                    sys.path.insert(0, suite)
                import obf_identify
                return await asyncio.wait_for(asyncio.to_thread(obf_identify.identify, text), timeout=_IDENT_TIMEOUT)
            except Exception:       # noqa: BLE001 -- l'identification ne doit jamais faire echouer /analyse
                return None

        async def _box():
            if len(raw) <= _SANDBOX_MAX_BYTES:
                return await _run_sandbox(text)
            return None, 0

        (h, static), ident, (box, rc) = await asyncio.gather(asyncio.to_thread(_static), _ident(), _box())
        return _build_embed(h, static, box, rc, ident), _report_txt(h, static, box, rc, ident)

    @app_commands.command(
        name="analyse",
        description="Analyse heuristique statique + sandbox d'un script Lua/Luau",
    )
    @app_commands.describe(
        url="Lien direct vers le script (raw GitHub, etc.)",
        fichier="Fichier .lua ou .txt joint",
    )
    @app_commands.checks.cooldown(1, _COOLDOWN_SECS, key=lambda i: i.user.id)
    async def analyse(
        self,
        interaction: discord.Interaction,
        url: Optional[str] = None,
        fichier: Optional[discord.Attachment] = None,
    ) -> None:
        if not url and not fichier:
            await interaction.response.send_message(
                "❌ Provide `url:` (direct link) or `file:` (attached .lua/.txt).",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=_SEM_WAIT)
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "⏳ Trop d'analyses en cours — réessaie dans quelques secondes."
            )
            return

        try:
            # ── Récupération du code source ──
            try:
                if fichier is not None:
                    if fichier.size > _MAX_BYTES:
                        await interaction.followup.send(
                            f"❌ Fichier trop grand (max {_MAX_BYTES // (1024*1024)} Mo)."
                        )
                        return
                    raw      = await fichier.read()
                    filename = fichier.filename
                else:
                    filename, raw = await _fetch_url(url)
            except Exception as exc:
                await interaction.followup.send(f"❌ Fetch failed: `{exc}`",
                                                allowed_mentions=discord.AllowedMentions.none())
                return

            if not raw.strip():
                await interaction.followup.send("❌ The file is empty.")
                return

            text = raw.decode("utf-8", errors="replace")

            # ── Analyse (echeance globale : l'utilisateur ne reste JAMAIS sur « reflechit... ») ──
            try:
                embed, report = await asyncio.wait_for(self._analyse_core(text, raw, filename), timeout=_ANALYSE_DEADLINE)
            except asyncio.TimeoutError:
                await interaction.followup.send(
                    f"⏱️ L'analyse a dépassé {_ANALYSE_DEADLINE} s et a été arrêtée (script trop lourd pour le bac à sable). "
                    "Pour un fichier volumineux, utilise `/process` (déobfuscation complète, suivie dans le salon).")
                return
            _record_stat("analyse", getattr(interaction.user, "id", 0), filename, "info", None, 0.0)
            f_txt  = discord.File(
                io.BytesIO(report.encode("utf-8")),
                filename="rapport_" + (re.sub(r"[^\w.\-]", "_", filename)[:60] or "script") + ".txt",
            )
            await interaction.followup.send(embed=embed, file=f_txt, allowed_mentions=discord.AllowedMentions.none())

        finally:
            self._sem.release()

    @analyse.error
    async def analyse_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"⏳ Cooldown — réessaie dans {error.retry_after:.0f} s.",
                    ephemeral=True,
                )
            return
        msg = f"❌ Erreur inattendue : `{error}`"
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:                       # deja « defer » : sans ceci l'utilisateur voit « reflechit... » sans fin
            try:
                await interaction.followup.send(msg, ephemeral=True)
            except discord.HTTPException:
                pass

    # ── /process ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="process",
        description="Deobfuscate a script or a .zip (in parallel), progress and results in the channel",
    )
    @app_commands.describe(
        url="Lien direct vers le script",
        fichier="Fichier .lua/.txt, ou .zip de scripts (jusqu'a 100, traites en parallele)",
    )
    async def process(
        self,
        interaction: discord.Interaction,
        url: Optional[str] = None,
        fichier: Optional[discord.Attachment] = None,
    ) -> None:
        # Garde-fou : owner_only() (app_commands.check, evalue pour de vrai) -- jamais un mot de passe
        # en dur ni le decorateur is_owner() des commandes prefixees (sans effet sur une slash command).
        await run_job(interaction, url=url, fichier=fichier, moteur="auto")

    @process.error
    async def process_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            msg = NOT_AUTHORIZED_MSG
        else:
            msg = f"❌ Erreur : `{error}`"
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            try:
                await interaction.followup.send(msg, ephemeral=True)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ToolsCog(bot))
