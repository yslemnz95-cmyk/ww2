#!/usr/bin/env python3
"""
loader_chain.py -- suit les « chargeurs » d'une ligne : `loadstring(game:HttpGet("https://..."))()`.

Un script qui ne fait que telecharger puis executer un autre script n'est pas obfusque : le vrai code est a l'adresse
indiquee (et peut y etre obfusque a son tour). L'executeur Roblox ferait exactement ce telechargement ; ce module le
fait a sa place, de facon SURE, puis laisse le routeur traiter le script recupere.

Garde-fous (le bot telecharge une adresse ecrite par un tiers) :
  - seulement http(s), ports 80/443/8080/8443, aucune adresse privee / locale / reservee (verifiee a chaque redirection,
    y compris apres resolution DNS) ;
  - 5 redirections, 8 Mo, 20 s par telechargement, 4 niveaux de chargeurs, jamais deux fois la meme adresse ;
  - aucun en-tete d'executeur n'est imite : on ne cherche PAS a contourner la protection d'un service (voir Luarmor).
  - seul un script COURT (<= 8 Ko) dont le seul HttpGet est une adresse litterale est suivi ; `DEOBF_FOLLOW_LOADERS=0`
    desactive tout.

Services de protection reconnus : le contenu n'est servi qu'a un executeur autorise (cle / HWID) ; on s'arrete et on le dit.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

MAX_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_DEPTH = 4
TIMEOUT = float(os.environ.get("DEOBF_FETCH_TIMEOUT", "20"))
LOADER_MAX_SOURCE = 8 * 1024
ALLOWED_PORTS = {80, 443, 8080, 8443}
USER_AGENT = "Mozilla/5.0 (compatible; deobf-suite-loader-resolver)"

# services qui ne livrent le script qu'a un executeur autorise : (nom, regex sur l'hote ou le texte)
PROTECTORS = (
    ("Luarmor", re.compile(r"(^|\.)luarmor\.(net|io)$", re.I), re.compile(r"luarmor|ldrupd8m|v4_init_", re.I)),
    ("FlowAuth", re.compile(r"(^|\.)flowauth\.net$", re.I), re.compile(r"flowauth\.net", re.I)),
    ("LuaProtect", re.compile(r"(^|\.)luaprotect\.dev$", re.I), re.compile(r"luaprotect\.dev", re.I)),
)

_STR = r'(?:"([^"\n]{4,2000})"|\'([^\'\n]{4,2000})\')'
_HTTPGET = re.compile(
    r"loadstring\s*\(\s*\(?\s*(?:game|_G\.game|getfenv\(\)\.game)\s*[:.]\s*HttpGet(?:Async)?\s*\(\s*\(?\s*"
    + _STR + r"\s*\)?\s*(?:,\s*(?:true|false)\s*)?\)\s*\)?\s*\)?\s*(?:\(\s*\))?", re.I)
_HTTPGET_VAR = re.compile(
    r"(?:local\s+)?([A-Za-z_]\w*)\s*=\s*\(?\s*(?:game|_G\.game|getfenv\(\)\.game)\s*[:.]\s*HttpGet(?:Async)?\s*\(\s*\(?\s*"
    + _STR + r"\s*\)?\s*(?:,\s*(?:true|false)\s*)?\)", re.I)
_ANY_HTTPGET = re.compile(r"HttpGet(?:Async)?\b|HttpService|request\s*\(", re.I)


class FetchError(Exception):
    pass


def _is_unsafe_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
            or ip.is_unspecified)


def _check_url(url: str) -> urllib.parse.SplitResult:
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https"):
        raise FetchError("adresse non http(s)")
    if not p.hostname:
        raise FetchError("adresse sans hote")
    port = p.port or (443 if p.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise FetchError(f"port {port} refuse")
    try:
        literal = ipaddress.ip_address(p.hostname)
        if _is_unsafe_ip(str(literal)):
            raise FetchError(f"adresse IP non publique refusee ({literal})")
        return p
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        if urllib.request.getproxies():          # derriere un proxy c'est lui qui resout le nom
            return p
        raise FetchError(f"nom d'hote introuvable ({exc})")
    bad = [i[4][0] for i in infos if _is_unsafe_ip(i[4][0])]
    if bad or not infos:
        raise FetchError(f"{p.hostname} pointe vers une adresse non publique ({bad[0] if bad else '?'})")
    return p


class _Guard(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def normalize_url(url: str) -> str:
    """Liens « page » courants -> liens bruts.

    Synchronise avec tools_cog._normalize_url : toute plateforme ajoutee la-bas
    doit l'etre ici aussi, car le loader chain simule game:HttpGet() et les scripts
    Roblox pointent souvent vers ces sites.
    """
    url = url.strip().strip("<>")
    m = re.match(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/blob/(.+)$", url, re.I)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3).split('?')[0]}"
    m = re.match(r"https?://(?:www\.)?pastebin\.com/(?!raw/)([A-Za-z0-9]+)/?$", url, re.I)
    if m:
        return f"https://pastebin.com/raw/{m.group(1)}"
    m = re.match(r"https?://gist\.github\.com/([^/]+)/([0-9a-f]+)/?$", url, re.I)
    if m:
        return f"https://gist.githubusercontent.com/{m.group(1)}/{m.group(2)}/raw"
    m = re.match(r"https?://(?:www\.)?hastebin\.com/(?!raw/)([A-Za-z0-9]+)(?:\.\w{1,8})?/?$", url, re.I)
    if m:
        return f"https://hastebin.com/raw/{m.group(1)}"
    m = re.match(r"https?://(?:www\.)?paste\.ee/p/([A-Za-z0-9]+)/?$", url, re.I)
    if m:
        return f"https://paste.ee/r/{m.group(1)}"
    m = re.match(r"https?://(?:www\.)?pastecode\.io/s/([A-Za-z0-9]+)/?$", url, re.I)
    if m:
        return f"https://pastecode.io/raw/{m.group(1)}"
    m = re.match(r"https?://(?:www\.)?rentry\.co/([A-Za-z0-9_-]+)/?$", url, re.I)
    if m:
        return f"https://rentry.co/{m.group(1)}/raw"
    m = re.match(r"https?://(?:www\.)?sourceb\.in/([A-Za-z0-9]+)/?$", url, re.I)
    if m:
        return f"https://sourceb.in/{m.group(1)}/raw"
    m = re.match(r"https?://(?:www\.)?pastes\.dev/([A-Za-z0-9]+)/?$", url, re.I)
    if m:
        return f"https://api.pastes.dev/{m.group(1)}"
    return url


def fetch(url: str, timeout: float = TIMEOUT, max_bytes: int = MAX_BYTES) -> bytes:
    """Telecharge `url` (contrôles ci-dessus). Leve FetchError avec une raison lisible."""
    url = normalize_url(url)
    _check_url(url)
    opener = urllib.request.build_opener(_Guard)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        raise FetchError(f"connexion impossible ({getattr(exc, 'reason', exc)})")
    except (OSError, ValueError) as exc:
        raise FetchError(str(exc) or type(exc).__name__)
    if len(data) > max_bytes:
        raise FetchError(f"fichier trop gros (> {max_bytes // (1024 * 1024)} Mo)")
    if not data.strip():
        raise FetchError("reponse vide")
    return data


def strip_comments(text: str) -> str:
    """Le code sans les lignes de commentaire (les en-tetes d'un resultat de trace peuvent etre longs)."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("--"))


def find_target(text: str) -> Optional[str]:
    """L'adresse que ce script court telecharge et execute, ou None si ce n'est pas un simple chargeur.
    Deux formes : `loadstring(game:HttpGet("url"))()` et `local r = game:HttpGet("url")` puis `loadstring(r)()`."""
    code = strip_comments(text)
    if len(code) > LOADER_MAX_SOURCE:
        return None
    urls, used = set(), 0
    for m in _HTTPGET.finditer(code):
        urls.add(m.group(1) or m.group(2))
        used += 1
    for m in _HTTPGET_VAR.finditer(code):
        var = m.group(1)
        if re.search(r"(?:loadstring|load)\s*\(\s*%s\s*[,)]" % re.escape(var), code):
            urls.add(m.group(2) or m.group(3))
            used += 1
    if len(urls) != 1:
        return None
    if len(_ANY_HTTPGET.findall(code)) != used:
        return None                                   # un autre telechargement / une requete : ce n'est pas un simple chargeur
    return next(iter(urls))


def protector_of(url: str, text: str = "") -> Optional[str]:
    """Le service de protection que `url` (son hote) ou `text` (un script qui n'en suit plus d'autre) designe."""
    host = urllib.parse.urlsplit(url).hostname or ""
    for name, host_re, text_re in PROTECTORS:
        if host_re.search(host) or (text and text_re.search(text[:20000])):
            return name
    return None


def resolve(text: str, log: Callable[[str], None] = lambda m: None,
            fetcher: Callable[[str], bytes] = fetch, max_depth: int = MAX_DEPTH) -> Optional[dict]:
    """Suit la chaine de chargeurs de `text`. None si `text` n'est pas un chargeur.
    -> {"levels": [{"url","bytes","sha256","text"|"error"}], "final": texte du dernier script recupere,
        "protected": nom du service ou None, "error": raison de l'arret ou None}"""
    if os.environ.get("DEOBF_FOLLOW_LOADERS", "1") == "0":
        return None
    url = find_target(text)
    if not url:
        return None
    levels: list[dict] = []
    seen: set[str] = set()
    protected = None
    next_url = None
    error = None
    cur = text
    for _ in range(max_depth):
        url = find_target(cur)
        if not url:
            break
        url = normalize_url(url)
        if url in seen:
            error = "boucle : cette adresse a deja ete suivie"
            break
        seen.add(url)
        gate = protector_of(url)                      # l'adresse suivante est un service de protection : on n'y touche pas
        if gate:
            protected, next_url = gate, url
            log(f"[router] le chargeur pointe vers {gate} ({url}) : contenu reserve aux executeurs autorises, arret")
            break
        log(f"[router] chargeur -> {url}")
        try:
            data = fetcher(url)
        except FetchError as exc:
            levels.append({"url": url, "error": str(exc)})
            error = f"{url} : {exc}"
            break
        cur = data.decode("utf-8", "replace")
        levels.append({"url": url, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "text": cur})
        if find_target(cur) is None:                  # un script qui n'en suit plus d'autre : est-ce un chargeur protege ?
            protected = protector_of(url, cur)
            if protected:
                break
    if not levels and not protected:
        return None
    return {"levels": levels, "final": cur if levels and "error" not in levels[-1] else "", "protected": protected,
            "next": next_url, "error": error}


def _comment_block(text: str) -> str:
    n = 1
    while f"]{'=' * n}]" in text:
        n += 1
    return f"--[{'=' * n}[\n{text.rstrip()}\n]{'=' * n}]"


def render(source_name: str, chain: dict, final_code: Optional[str] = None, final_label: str = "",
           intro: Optional[tuple] = None) -> str:
    """Le fichier livre : la chaine de chargement, puis le script final (deobfusque s'il l'a ete).
    `intro` = (description, code) : le programme que `source_name` contenait vraiment (ex. apres LuauForge)."""
    out = [f"-- ===== Chaine de chargement : {len(chain['levels'])} niveau(x) ====="]
    out.append(f"-- 0. {source_name}  (" + (intro[0] if intro else "le script fourni : un simple chargeur") + ")")
    for i, lv in enumerate(chain["levels"], 1):
        if "error" in lv:
            out.append(f"-- {i}. {lv['url']}  -> IMPOSSIBLE A TELECHARGER : {lv['error']}")
        else:
            out.append(f"-- {i}. {lv['url']}  ({lv['bytes']} octets, sha256 {lv['sha256'][:16]})")
    if chain.get("protected"):
        if chain.get("next"):
            out.append(f"-- {len(chain['levels']) + 1}. {chain['next']}  -> service {chain['protected']} : NON TELECHARGE")
        out += ["--",
                f"-- PROTEGE PAR {chain['protected'].upper()} : le script reel n'est PAS dans cette chaine. Ce service ne le livre qu'a un",
                "-- executeur autorise (cle / HWID) via ses propres serveurs ; ce qui est telechargeable sans cela n'est qu'un chargeur",
                "-- ou un message d'erreur. Il n'existe rien a deobfusquer ici : le moteur s'arrete (on n'imite pas un executeur pour",
                "-- contourner la protection). Pour l'analyser il faut l'obtenir legitimement (cle valide) puis l'envoyer au bot."]
    elif chain.get("error"):
        out += ["--", f"-- ARRET : {chain['error']}"]
    out.append("-- =====")
    out.append("")
    if intro:
        out.append(f"-- ===== Programme reel de {source_name} =====")
        out.append(intro[1].rstrip())
        out.append("")
    for i, lv in enumerate(chain["levels"], 1):
        if "text" not in lv:
            continue
        is_last = i == len(chain["levels"])
        if is_last and final_code is not None and not chain.get("protected"):
            out.append(f"-- ===== Niveau {i} : script final ({final_label or 'code recupere'}) =====")
            out.append(final_code.rstrip())
        else:
            out.append(f"-- ===== Niveau {i} : source recue de {lv['url']} (en commentaire) =====")
            out.append(_comment_block(lv["text"]))
        out.append("")
    return "\n".join(out).rstrip() + "\n"
