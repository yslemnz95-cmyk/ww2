#!/usr/bin/env python3
"""
Chargeurs `loadstring(game:HttpGet("https://..."))()` : le routeur suit la chaine (serveur HTTP local), traite le script
recupere, s'arrete devant un service de protection (Luarmor) SANS le contacter, et refuse les adresses internes.

Usage : python3 tests/test_loader_chain.py
"""
import http.server
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import deobf_router as R  # noqa: E402
import loader_chain as LC  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


# -- le serveur local : /a -> chargeur vers /b, /b -> script en clair, /forge -> LuauForge, /loop -> lui-meme, /big -> 9 Mo
import test_luauforge as TF  # noqa: E402  (fabrique des scripts LuauForge ; ses propres verifications passent d'abord)

PORT = [0]
HITS = []
PLAIN = 'print("script final")\nreturn 42\n'
FORGED = TF.blank_layer(TF.dict_layer(TF.INNER))


def loader(path):
    return 'loadstring(game:HttpGet("http://127.0.0.1:%d%s"))()' % (PORT[0], path)


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        HITS.append(self.path)
        body = {"/a": loader("/b"), "/b": PLAIN, "/forge": FORGED, "/c": loader("/forge"), "/loop": loader("/loop"),
                "/big": "x" * (9 * 1024 * 1024), "/empty": " ", "/n1": loader("/n2"), "/n2": loader("/n3"), "/n3": loader("/n4"),
                "/n4": loader("/n5"), "/n5": loader("/n6"), "/n6": PLAIN}.get(self.path)
        if self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode("latin-1")
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
PORT[0] = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# -- 1. reconnaissance des chargeurs --------------------------------------------------------------------------
URL = "https://raw.githubusercontent.com/u/r/main/X"
for form, text in (("simple", f'loadstring(game:HttpGet("{URL}"))()'),
                   ("avec true", f"loadstring(game:HttpGet('{URL}', true))()"),
                   ("parentheses", f'loadstring(game:HttpGet(("{URL}")))()'),
                   ("HttpGetAsync", f'loadstring(game:HttpGetAsync("{URL}"))()'),
                   ("avec reglages avant", f'getgenv().Key = "abc"\ngetgenv().Settings = {{Fast = true}}\nloadstring(game:HttpGet("{URL}"))()\n')):
    check(LC.find_target(text) == URL, f"chargeur reconnu : {form}")
check(LC.find_target(f'loadstring(game:HttpGet("{URL}"))()\nloadstring(game:HttpGet("{URL}2"))()') is None,
      "deux adresses differentes : pas un simple chargeur")
check(LC.find_target(f'local r = game:HttpGet("https://evil.example/x")\nloadstring(game:HttpGet("{URL}"))()') is None,
      "un autre telechargement dans le script : pas un simple chargeur")
check(LC.find_target('print("x")') is None and LC.find_target("x" * 9000) is None, "script ordinaire ou trop long : rien a suivre")

# -- 2. garde-fous (par defaut, 127.0.0.1 est interdit) -------------------------------------------------------
for u in (f"http://127.0.0.1:{PORT[0]}/a", "http://localhost/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/",
          "file:///etc/passwd", "http://10.0.0.1/", "https://example.com:22/"):
    try:
        LC.fetch(u)
        check(False, f"adresse refusee : {u}")
    except LC.FetchError:
        check(True, f"adresse refusee : {u}")
check(not HITS, "le serveur local n'a recu AUCUNE requete pendant ces refus")

# -- 3. a partir d'ici le serveur local est autorise (127.0.0.1 seulement) ---------------------------------------
real_unsafe = LC._is_unsafe_ip
LC._is_unsafe_ip = lambda ip: ip != "127.0.0.1" and real_unsafe(ip)
LC.ALLOWED_PORTS = LC.ALLOWED_PORTS | {PORT[0]}          # le serveur de test ecoute sur un port aleatoire
with tempfile.TemporaryDirectory() as td:
    td = Path(td)

    def run(first):
        src, out = td / "in.lua", td / "out.lua"
        src.write_text(loader(first))
        out.unlink(missing_ok=True)
        res = R.deobfuscate(src, out)
        return res, (out.read_text("utf-8", "replace") if out.exists() else "")

    res, text = run("/a")
    check(res.get("ok") and res.get("engine") == "loader_chain" and len(res.get("chain", [])) == 2 and not res.get("protected"),
          f"chaine /a -> /b suivie ({res.get('engine')}, {len(res.get('chain', []))} niveau(x))")
    check(PLAIN in text and "code en clair" in text and "Chaine de chargement : 2 niveau(x)" in text,
          "le script final (en clair) est livre avec la chaine en en-tete")
    res, text = run("/c")
    check(res.get("ok") and res.get("engine") == "loader_chain+luauforge" and TF.INNER in text,
          f"chargeur -> script obfusque : defait par le bon moteur ({res.get('engine')})")
    res, text = run("/loop")
    check(res.get("ok") is not None and "boucle" in text, "boucle d'adresses : arret signale")
    res, text = run("/n1")
    check(len(res.get("chain", [])) == LC.MAX_DEPTH, f"profondeur limitee a {LC.MAX_DEPTH} niveaux ({len(res.get('chain', []))})")
    res, text = run("/nexiste-pas")
    check(not res.get("ok") and "HTTP 404" in res.get("log", ""), "adresse introuvable : echec clair (HTTP 404)")
    res, text = run("/redir")
    check(not res.get("ok") and ("non publique" in res.get("log", "") or "refuse" in res.get("log", "")),
          "redirection vers 169.254.169.254 refusee")
    try:
        LC.fetch(f"http://127.0.0.1:{PORT[0]}/big")
        check(False, "fichier de 9 Mo refuse")
    except LC.FetchError as exc:
        check("trop gros" in str(exc), "fichier de 9 Mo refuse")
    try:
        LC.fetch(f"http://127.0.0.1:{PORT[0]}/empty")
        check(False, "reponse vide refusee")
    except LC.FetchError:
        check(True, "reponse vide refusee")

    # -- 4. Luarmor : jamais contacte -------------------------------------------------------------------------------
    calls = []
    chain = LC.resolve('loadstring(game:HttpGet("https://api.luarmor.net/files/v4/loaders/abc.lua"))()',
                       fetcher=lambda u: calls.append(u) or b"x")
    check(chain and chain["protected"] == "Luarmor" and not calls and chain["next"].endswith("abc.lua"),
          "adresse Luarmor : reconnue et NON telechargee")
    calls.clear()
    chain = LC.resolve(f'loadstring(game:HttpGet("{URL}"))()',
                       fetcher=lambda u: calls.append(u) or b'loadstring(game:HttpGet("https://api.luarmor.net/files/v4/loaders/abc.lua"))()')
    check(chain["protected"] == "Luarmor" and len(calls) == 1 and len(chain["levels"]) == 1,
          "GitHub -> Luarmor : un seul telechargement (le 1er niveau), arret devant Luarmor")
    src, out = td / "lm.lua", td / "lm_out.lua"
    src.write_text('loadstring(game:HttpGet("https://api.luarmor.net/files/v4/loaders/abc.lua"))()')
    res = R.deobfuscate(src, out)
    text = out.read_text("utf-8", "replace")
    check(res.get("ok") and res.get("protected") == "Luarmor" and "PROTEGE PAR LUARMOR" in text and "NON TELECHARGE" in text,
          "le fichier livre explique la protection Luarmor")

    # -- 4b. LuauForge (couches + machine virtuelle) -> programme reel = chargeur -> script final, de bout en bout --------------
    src, out = td / "vmchain.lua", td / "vmchain_out.lua"
    src.write_bytes(TF.blank_layer(TF.dict_layer(TF.vm_like(f"http://127.0.0.1:{PORT[0]}/b"))).encode("latin-1"))
    res = R.deobfuscate(src, out, timeout=900)
    text = out.read_text("utf-8", "replace") if out.exists() else ""
    check(res.get("ok") and res.get("engine", "").startswith("luauforge+loader_chain") and len(res.get("chain", [])) == 1,
          f"LuauForge -> machine virtuelle -> chargeur suivi ({res.get('engine')})")
    check("Programme reel de vmchain.lua" in text and PLAIN in text and "Chaine de chargement" in text,
          "le fichier livre contient le programme reel ET le script final")
    check(f"/b" in str(res.get("chain")) and "bytes" in res["chain"][0], "la chaine est rapportee au bot (res['chain'])")

    # -- 5. interrupteur ------------------------------------------------------------------------------------------
    import os
    os.environ["DEOBF_FOLLOW_LOADERS"] = "0"
    try:
        check(LC.resolve(loader("/a")) is None, "DEOBF_FOLLOW_LOADERS=0 : aucun chargeur suivi")
    finally:
        os.environ.pop("DEOBF_FOLLOW_LOADERS")
    # un script ordinaire court : le routeur dit toujours « aucun obfuscateur reconnu »
    src = td / "plain.lua"
    src.write_text('print("bonjour")\n')
    res = R.deobfuscate(src, td / "plain_out.lua")
    check(not res.get("ok") and "aucun obfuscateur" in res.get("log", ""), "script ordinaire court : comportement inchange")
LC._is_unsafe_ip = real_unsafe
srv.shutdown()

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : chargeurs suivis, garde-fous et Luarmor verifies")
