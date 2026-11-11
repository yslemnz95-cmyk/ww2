#!/usr/bin/env python3
"""Telechargement : protection SSRF, validation des URL, limite de telechargements simultanes, cache court, masquage des secrets."""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

SUITE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE.parent))
os.environ["DEOBF_DATA_DIR"] = tempfile.mkdtemp(prefix="fetch_data_")
from yslem_deobf_suite.cogs import tools_cog as L  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label, flush=True)
    if not cond:
        FAILS.append(label)


async def refused(url):
    try:
        await asyncio.wait_for(L._fetch_url(url), timeout=20)
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__ + ": " + str(exc)
    return None


async def main():
    # SSRF : adresses internes, locales, cloud, ports sensibles, schemas non http
    for url, label in (("http://127.0.0.1:8080/x", "loopback"), ("http://10.0.0.5/x", "reseau prive 10/8"), ("http://192.168.1.1/x", "reseau prive 192.168/16"),
                       ("http://169.254.169.254/latest/meta-data/", "metadonnees cloud"), ("http://[::1]/x", "IPv6 loopback"),
                       ("http://0.0.0.0/x", "adresse nulle"), ("https://example.com:22/x", "port sensible 22"),
                       ("ftp://example.com/x", "schema ftp"), ("file:///etc/passwd", "schema file"), ("javascript:alert(1)", "schema javascript")):
        r = await refused(url)
        check(r is not None, f"SSRF/URL : {label} refuse ({(r or '')[:60]})")
    r = await refused("http://localhost:8000/x")
    check(r is not None, f"SSRF : localhost refuse apres resolution DNS ({(r or '')[:60]})")

    # normalisation des liens « page »
    check(L._normalize_url("https://github.com/a/b/blob/main/x.lua") == "https://raw.githubusercontent.com/a/b/main/x.lua", "lien GitHub « blob » -> raw")
    check(L._normalize_url("https://pastebin.com/AbC123") == "https://pastebin.com/raw/AbC123", "lien pastebin -> raw")

    # limite de telechargements simultanes
    live, peak = [0], [0]

    async def slow(url, info=None):
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        await asyncio.sleep(0.15)
        live[0] -= 1
        return "x.lua", b"print(1)"

    real = L._fetch_url_unlimited
    L._fetch_url_unlimited = slow
    L._HTTP_SEM = None
    try:
        await asyncio.gather(*(L._fetch_url(f"https://example.com/{i}") for i in range(12)))
        check(peak[0] <= L._HTTP_PARALLEL, f"requetes HTTP simultanees limitees (pic {peak[0]} <= {L._HTTP_PARALLEL})")
        # cache court : le meme lien n'est pas retelecharge
        calls = [0]

        async def counted(url, info=None):
            calls[0] += 1
            if info is not None:
                info.update(status=200, redirects=["a.example"])
            return "c.lua", b"print(2)"
        L._fetch_url_unlimited = counted
        info1, info2 = {}, {}
        await L._fetch_url("https://example.com/cache", info1, cache=True)
        await L._fetch_url("https://example.com/cache", info2, cache=True)
        check(calls[0] == 1 and info2.get("cached") and info2.get("redirects") == ["a.example"], "cache de 2 min : pas de requete repetitive, infos conservees")
        await L._fetch_url("https://example.com/cache")                      # sans cache=True : telecharge vraiment
        check(calls[0] == 2, "sans cache demande : nouveau telechargement")
        L._FETCH_CACHE.clear()
        for i in range(20):
            L._fetch_cache_put(f"u{i}", "n", b"x" * 1000, {})
        check(len(L._FETCH_CACHE) <= 8, "cache borne (pas de fuite memoire)")
    finally:
        L._fetch_url_unlimited = real

    # masquage des secrets dans le journal
    tok = "FAKE_BOT_TOKEN_FOR_TESTING.GaBcDe.abcdefghijklmnopqrstuvwxyz0123456"
    L._log(f"test jeton {tok} et https://discord.com/api/webhooks/123/SECRETWEBHOOK_abc")
    log = (L._find_suite() / "logs" / "deobf.log").read_text(encoding="utf-8")
    check("FAKE_BOT_TOKEN" not in log and "SECRETWEBHOOK" not in log, "journal administrateur : jetons et webhooks masques")
    # une erreur contenant un secret n'est jamais renvoyee telle quelle
    check("FAKE_BOT_TOKEN" not in L._mask(f"erreur avec {tok}"), "messages d'erreur : secrets masques")


asyncio.run(main())
print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : telechargement sur et borne")
