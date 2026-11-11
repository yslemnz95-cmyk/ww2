#!/usr/bin/env python3
"""
Le code du bot avec la VRAIE bibliotheque discord.py (HTTP multipart, edition de messages, interactions) branchee
sur un faux serveur Discord local (tests/mock_discord.py) : /process, /deobf, /analyse, /deobf_dernier, /deobf_etat,
/deobf_annuler sont appeles avec de vraies `discord.Interaction`, `discord.Attachment`, `discord.User`.

Verifie : UN tableau de bord par salon (edite, compte a rebours decroissant), resultats postes dans le salon, aucun
message « en arriere-plan » (la reponse ephemere est supprimee), jobs SIMULTANES (pas de file d'attente), .zip de
plusieurs scripts, meme script envoye 2 fois calcule 1 fois, 30 jobs en meme temps, machine faible, cache,
annulation, replis (salon interdit -> interaction -> MP -> disque), pannes simulees, redemarrage du bot.
Usage : python3 tests/test_discord_http.py
"""
import asyncio
import io
import os
os.environ["DEOBF_PICKER"] = "0"          # ces tests visent run_job ; le selecteur de moteur a son propre test (test_identify.py)
import re
import sys
import tempfile
import time
import types
import zipfile
from pathlib import Path

SUITE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUITE.parent))
sys.path.insert(0, str(SUITE / "tests"))
import mock_discord as M                                            # noqa: E402
from yslem_deobf_suite.cogs import deobf_cog, tools_cog as L  # noqa: E402

FAILS = []
FORBIDDEN = (403, 50013, "Missing Permissions")
DM_CLOSED = (403, 50007, "Cannot send messages to this user")
os.environ["DEOBF_DECIDE"] = "0"     # ces scenarios utilisent un moteur FACTICE : la decision automatique (scripts « lisibles » -> pas de moteur) est testee ailleurs
LAST_STUB: list = []
READY = types.SimpleNamespace(preflight=lambda: {"ready": True, "steps": [], "blocker": None, "slow": False})


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label, flush=True)
    if not cond:
        FAILS.append(label)


def files_of(msgs):
    return {n: b for m in msgs for n, b in m["files"].items()}


def has_result(msgs, needle=b'protected by legaxyobf'):
    return any(n.startswith("deobfuscated_") and needle in b for n, b in files_of(msgs).items())


def results(msgs):
    return [n for m in msgs for n in m["files"] if n.startswith("deobfuscated_")]


def reset(server):
    for lst in (server.dm_messages, server.followups, server.channel_messages, server.edits, server.dm_script,
                server.channel_script, server.deleted, server.edit_script):
        lst.clear()
    server.webhook_expired = False


def stub(code: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix="stub_suite_"))
    (d / "deobf_router.py").write_text(code)
    return d


def make_zip(entries) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in entries:
            z.writestr(n, b)
    return buf.getvalue()


async def main() -> None:
    server = M.MockDiscord()
    await server.start()
    bot, mk = await M.make_bot(server)
    tools = L.ToolsCog(bot)
    etc = deobf_cog.DeobfCog(bot)
    sample = (SUITE / "tests" / "samples" / "legaxyobf.lua").read_bytes()
    results_dir = SUITE / "results"
    pre_existing = set(results_dir.glob("*")) if results_dir.exists() else set()
    att = server.attachment(bot, "small.lua", sample)
    L._TICK = 0.4
    real_cache_get = L._cache_get
    L._cache_get = lambda sha, moteur: None          # chaque scenario refait le calcul (le cache a son propre test)
    real_bootstrap = L._bootstrap

    def cleanup():
        for p_ in set(results_dir.glob("*")) - pre_existing - {results_dir / "journal.json"}:
            if p_.is_file():
                p_.unlink()

    async def run_stub(code: str, warn=2, kill=6, tick=0.5, attachment=None):
        reset(server)
        d = stub(code)
        LAST_STUB[:] = [d]
        os.environ["DEOBF_SUITE_DIR"] = str(d)
        saved = (L._STALL_WARN, L._STALL_KILL, L._TICK)
        L._bootstrap = lambda: READY
        L._STALL_WARN, L._STALL_KILL, L._TICK = warn, kill, tick
        t = time.monotonic()
        try:
            await tools.process.callback(tools, mk(), None, attachment or att)
            await asyncio.sleep(tick * 2)            # derniere mise a jour du tableau de bord
        finally:
            os.environ.pop("DEOBF_SUITE_DIR")
            L._bootstrap = real_bootstrap
            L._STALL_WARN, L._STALL_KILL, L._TICK = saved
        texts = [e["content"] or "" for e in server.edits] + [m["content"] or "" for m in server.channel_messages]
        return " || ".join(texts), time.monotonic() - t

    SLOW_CODE = ("import time, json, sys\n"
                 "for line in ('[router] moteur : stub (confiance 0.99)', '[*] tracing x (run 1)...', "
                 "'[*] constants decoded on request: calls=0', '[*] devirtualizing (round 1)...', '[*] lift attempt 1: 0 unlifted'):\n"
                 "    print(line, flush=True)\n    time.sleep(1.3)\n"
                 "open(sys.argv[3], 'w').write('-- protected by legaxyobf\\nprint(1)\\n')\n"
                 "print(json.dumps({'ok': True, 'engine': 'stub', 'log': 'ok', 'out_bytes': 30}))\n")
    d_slow = stub(SLOW_CODE)

    def slow_on():
        os.environ["DEOBF_SUITE_DIR"] = str(d_slow)
        L._bootstrap = lambda: READY

    def slow_off():
        os.environ.pop("DEOBF_SUITE_DIR", None)
        L._bootstrap = real_bootstrap

    try:
        # 0. REGRESSION : prerequis (Luau) absent -> le job d'un moteur qui n'en a pas besoin doit quand meme aboutir
        BLOCKED = types.SimpleNamespace(preflight=lambda: {"ready": False, "steps": [], "slow": False,
                                                           "blocker": "le Luau livre ne tourne pas sur Linux x86_64 (luau est absent)"})
        reset(server)
        os.environ["DEOBF_SUITE_DIR"] = str(d_slow)
        L._bootstrap = lambda: BLOCKED
        try:
            await tools.process.callback(tools, mk(), None, att)
            await asyncio.sleep(1.2)
        finally:
            os.environ.pop("DEOBF_SUITE_DIR", None)
            L._bootstrap = real_bootstrap
        await asyncio.sleep(8)
        txt0 = " || ".join([e["content"] or "" for e in server.edits] + [m["content"] or "" for m in server.channel_messages])
        check(has_result(server.dm_messages + server.followups + server.channel_messages),
              "prerequis Luau absent : un moteur qui n'en a pas besoin livre quand meme son resultat")
        check("impossible de lancer le moteur" not in txt0, "prerequis Luau absent : plus de refus d'emblee « impossible de lancer le moteur »")

        # 1. chemin nominal : UN tableau de bord dans le salon, puis le resultat
        slow_on()
        reset(server)
        t0 = time.monotonic()
        await tools.process.callback(tools, mk(), None, att)
        await asyncio.sleep(1)
        board = server.channel_messages[0] if server.channel_messages else {"content": "", "id": ""}
        check("obfuscation" in (board["content"] or "").lower(), "salon : suivi poste (embed)")
        mine = [e for e in server.edits if e["id"] == board["id"]]
        eta = []
        for e in mine:
            m = re.search(r"reste ~(?:(\d+) min )?(\d+) s", e["content"] or "")
            if m:
                eta.append(int(m.group(2)) + 60 * int(m.group(1) or 0))
        check(len(eta) >= 3, f"tableau de bord EDITE regulierement ({len(eta)} mises a jour avec compte a rebours)")
        check(eta and all(a >= b for a, b in zip(eta, eta[1:])) and eta[0] > eta[-1], f"compte a rebours DECROIT ({eta[:1]} -> {eta[-1:]})")
        check(any("✅" in (e["content"] or "") and "small.lua" in (e["content"] or "") for e in mine),
              "suivi : la ligne du job passe a « ✅ »")
        res_msgs = [m for m in server.channel_messages if any(n.startswith("deobfuscated_") for n in m["files"])]
        check(bool(res_msgs) and has_result(res_msgs), f"resultat poste dans la conversation ({time.monotonic() - t0:.0f}s)")
        check(len(res_msgs[0]["files"]) == 1 and f"<@{M.USER_ID}>" in res_msgs[0]["content"], "fichier seul dans son message + mention")
        check(not any("findings.txt" in m["files"] for m in server.channel_messages),
              "pas de message parasite : le resume de securite reste dans les logs administrateur")
        check(not server.dm_messages, "aucun MP en fonctionnement normal")
        check(not server.followups and "@original" in server.deleted,
              "aucun message « en arriere-plan » : rien d'ephemere, la reponse de la commande est supprimee")

        slow_off()

        # 2. salon interdit -> la reponse de la commande ; 3. + jeton expire -> MP ; 4. rien -> disque + /deobf_dernier
        reset(server); server.channel_script = [FORBIDDEN] * 30
        await tools.process.callback(tools, mk(), None, att)
        check(has_result(server.followups) and not server.dm_messages, "salon interdit : resultat dans la reponse de la commande")
        reset(server); server.channel_script = [FORBIDDEN] * 30; server.webhook_expired = True
        await tools.process.callback(tools, mk(), None, att)
        check(has_result(server.dm_messages), "salon interdit + jeton expire : resultat en MP")
        cleanup()
        reset(server); server.channel_script = [FORBIDDEN] * 30; server.webhook_expired = True; server.dm_script = [DM_CLOSED] * 30
        L._RETRY_DELAYS = (0.5,)
        await tools.process.callback(tools, mk(), None, att)
        check(any(b'protected by legaxyobf' in p.read_bytes() for p in results_dir.glob("*.lua") if p.is_file()),
              "tout en echec : resultat conserve dans results/")
        server.webhook_expired = False
        server.followups.clear()
        await etc.deobf_dernier.callback(etc, mk(name="deobf_dernier"), 1)
        check(any(b'protected by legaxyobf' in b for b in files_of(server.followups).values()), "/deobf_dernier renvoie le resultat")
        server.dm_script.clear()
        await asyncio.sleep(2)
        check(has_result(server.dm_messages), "renvoi differe : le MP finit par arriver")
        cleanup()

        # 5. jeton d'interaction expire : le salon n'en depend pas
        reset(server); server.webhook_expired = True
        await tools.process.callback(tools, mk(), None, att)
        check(has_result(server.channel_messages), "jeton expire : resultat quand meme dans le salon")

        # 6. 500/502 sur l'envoi du resultat
        reset(server); server.channel_script = [None, (500, 0, "oops"), (502, 0, "bad gateway")]
        await tools.process.callback(tools, mk(), None, att)
        check(has_result(server.channel_messages), "500/502 : reessai automatique")

        # 7. avancement du moteur, en direct
        slow_on()
        reset(server)
        arrivals = {}
        orig_stage = L._stage_of

        def spy(line):
            r = orig_stage(line)
            if r is not None:
                arrivals.setdefault(r[0], time.monotonic())
            return r
        L._stage_of = spy
        await tools.process.callback(tools, mk(), None, att)
        t_end = time.monotonic()
        L._stage_of = orig_stage
        seen = " ".join(e["content"] or "" for e in server.edits)
        check({1, 2, 3, 4} <= set(arrivals) and t_end - arrivals[3] > 0.5,
              f"etapes du moteur EN DIRECT (devirtualisation vue {t_end - arrivals.get(3, t_end):.1f}s avant la fin)")
        check("CPU" in seen and "Mo" in seen, "activite reelle du moteur affichee")

        slow_off()

        # 8. JOBS SIMULTANES : 2 scripts en meme temps -> les deux tournent ensemble (pas de file d'attente)
        code_sleep = ("import time, json, sys\nprint('[*] tracing x (run 1)...', flush=True)\ntime.sleep(3)\n"
                      "open(sys.argv[3], 'w').write('print(\"blah blah\")')\n"
                      "print(json.dumps({'ok': True, 'engine': 'stub', 'log': 'ok', 'out_bytes': 1}))\n")
        d = stub(code_sleep)
        os.environ["DEOBF_SUITE_DIR"] = str(d)
        L._bootstrap = lambda: READY
        reset(server)
        att_b = server.attachment(bot, "autre.lua", b"print('b')\n" * 10)
        t0 = time.monotonic()
        await asyncio.gather(tools.process.callback(tools, mk(), None, att), tools.process.callback(tools, mk(), None, att_b))
        dt = time.monotonic() - t0
        check(len(results(server.channel_messages)) == 2 and dt < 5.5,
              f"2 jobs en meme temps : tous les deux termines en {dt:.1f}s (en serie ce serait >= 6 s)")
        check(any("2 en cours" in (e["content"] or "") for e in server.edits) and
              not any("file d'attente" in (m["content"] or "").lower() for m in server.channel_messages),
              "un seul tableau de bord montre « 2 en cours », aucune file d'attente")

        # 9. .zip de plusieurs scripts, dont 2 identiques (calcules UNE fois)
        reset(server)
        z = make_zip([("a.lua", b"print('a')\n"), ("b.txt", b"print('b')\n"), ("copie_de_a.lua", b"print('a')\n"),
                      ("readme.md", b"ignore")])
        t0 = time.monotonic()
        await tools.process.callback(tools, mk(), None, server.attachment(bot, "lot.zip", z))
        dt = time.monotonic() - t0
        got = results(server.channel_messages)
        check(sorted(got) == ["deobfuscated_a.lua", "deobfuscated_b.lua", "deobfuscated_copie_de_a.lua"] and dt < 5.5,
              f".zip : 3 scripts traites en parallele en {dt:.1f}s (le .md est ignore)")
        check(any("calcul partag" in (m["content"] or "") for m in server.channel_messages),
              "le meme script en double n'est calcule qu'une fois (« calcul partage »)")

        # 10. 30 jobs en meme temps (zip de 30 scripts differents)
        reset(server)
        z = make_zip([(f"s{i:02d}.lua", f"print({i})\n".encode()) for i in range(30)])
        t0 = time.monotonic()
        await tools.process.callback(tools, mk(), None, server.attachment(bot, "lot30.zip", z))
        dt = time.monotonic() - t0
        boards = {m["id"] for m in server.channel_messages if "obfuscation" in (m["content"] or "").lower() and not m["files"]}
        check(len(results(server.channel_messages)) == 30 and dt < 15 and len(boards) == 1,
              f"30 jobs simultanes : 30 resultats en {dt:.1f}s, UN seul tableau de bord")
        os.environ.pop("DEOBF_SUITE_DIR")
        L._bootstrap = real_bootstrap

        # 11. pannes : le bot DIT quel est le probleme
        text, dt = await run_stub("import time\nprint('[*] tracing x (run 1)...', flush=True)\ntime.sleep(600)\n")
        check("Aucune activite depuis" in text and "Job arrete car bloque" in text and dt < 30,
              f"moteur muet : diagnostic puis arret avec la cause ({dt:.0f}s)")
        text, dt = await run_stub("import os, signal\nprint('[*] tracing x (run 1)...', flush=True)\nos.kill(os.getpid(), signal.SIGKILL)\n")
        check("TUE le moteur" in text, "moteur tue (SIGKILL) : « memoire insuffisante probable »")
        text, dt = await run_stub("raise RuntimeError('boom du moteur')\n")
        check("RuntimeError: boom du moteur" in text, "exception du moteur citee")
        text, dt = await run_stub("import time, json\nprint('[*] tracing x (run 1)...', flush=True)\nend = time.time() + 5\n"
                                  "while time.time() < end: sum(range(20000))\nprint(json.dumps({'ok': False, 'engine': 'stub', 'log': 'fini'}))\n",
                                  warn=2, kill=4)
        check("Aucune activite" not in text and "Job arrete" not in text, "moteur occupe (CPU) : pas pris pour un blocage")
        text, dt = await run_stub("import subprocess, sys, time\nsubprocess.Popen(['sleep', '4343'], start_new_session=True)\n"
                                  "print('[*] tracing x (run 1)...', flush=True)\ntime.sleep(600)\n")
        await asyncio.sleep(0.5)
        left = os.popen("pgrep -f '[s]leep 4343' | wc -l").read().strip()
        check("Job arrete car bloque" in text and left == "0", f"moteur bloque dans une autre session : tout est arrete ({left} restant)")
        text, dt = await run_stub("import time, json\nprint('[router] Node.js absent : telechargement...', flush=True)\ntime.sleep(1.5)\n"
                                  "print('[router] telechargement de Node.js : 12 / 30 Mo', flush=True)\ntime.sleep(1.5)\n"
                                  "print(json.dumps({'ok': False, 'engine': 'stub', 'log': 'fini'}))\n", warn=30, kill=60)
        check("Etape 1/7 Preparation" in text and "Execution du script" not in text,
              "preparation longue : le tableau de bord dit « Preparation »")

        # 12. machine bridee a 0,25 coeur : le bot le dit. Mode COMPLET (defaut) : toutes les tentatives, budget long ;
        #     mode RAPIDE (DEOBF_WEAK_MODE=rapide) : peu de tentatives, duree plafonnee.
        STUB = ("import os, json\nenv = 'env budget=%s timeout=%s parallel=%s lift=%s retries=%s' % (os.environ.get('LURAPH_BUDGET'), "
                "os.environ.get('LURAPH_TIMEOUT'), os.environ.get('DEOB_LIFT_PARALLEL'), os.environ.get('DEOB_LIFT_BUDGET'), "
                "os.environ.get('DEOB_LIFT_RETRIES'))\nprint(json.dumps({'ok': False, 'engine': 'stub', 'log': env}))\n")

        def logs_of():
            # le detail technique n'est plus poste dans le salon : il est dans logs/jobs/ (administrateur)
            d_ = LAST_STUB[0] / "logs" / "jobs" if LAST_STUB else None
            return " ".join(p_.read_text("utf-8", "replace") for p_ in sorted(d_.glob("*.log"))[-1:]) if d_ and d_.exists() else ""
        real_cpu = L._cpu_limits
        L._cpu_limits = lambda: {"cores": 8, "affinity": 8, "quota": 0.25, "effective": 0.25, "forced": False}
        reset(server)
        text, dt = await run_stub(STUB, warn=30, kill=60)
        check("machine faible (0.25 coeur)" in text.lower() and "mode complet" in text.lower(),
              "machine faible : avertissement court « mode complet » dans le suivi")
        check("budget=480 timeout=1200 parallel=1 lift=2400 retries=32" in logs_of(),
              "machine faible (complet) : 32 tentatives, une a la fois, budget long (40 min)")
        plan = L._plan_resources(1, L.JOB_TIMEOUT_DEFAULT)
        check((plan["timeout_needed"] or 0) > 3600 and not plan["fast"],
              f"machine faible (complet) : delai du job allonge ({plan['timeout_needed']} s) pour laisser le temps aux tentatives")
        plan = L._plan_resources(1, 1800, explicit_timeout=True)
        check(plan["timeout_needed"] is None and int(plan["env"]["DEOB_LIFT_BUDGET"]) < 2400,
              "machine faible : un delai choisi par l'utilisateur (timeout_min) est respecte")
        os.environ["DEOBF_WEAK_MODE"] = "rapide"
        try:
            reset(server)
            text, dt = await run_stub(STUB, warn=30, kill=60)
            plan_fast = L._plan_resources(1, L.JOB_TIMEOUT_DEFAULT)
        finally:
            os.environ.pop("DEOBF_WEAK_MODE", None)
        check("mode rapide" in text.lower() and "budget=480 timeout=1200 parallel=1 lift=580 retries=3" in logs_of() and plan_fast["fast"],
              "machine faible (rapide) : 3 tentatives max, duree plafonnee")
        L._cpu_limits = real_cpu
        os.environ["DEOBF_FORCE_CPU"] = "3"
        try:
            c = L._cpu_limits()
            check(c["effective"] == 3.0 and c["forced"] and not L._plan_resources(1)["weak"],
                  "DEOBF_FORCE_CPU=3 : le nombre de coeurs est impose (machine non faible)")
        finally:
            os.environ.pop("DEOBF_FORCE_CPU", None)

        # 12b. chargeur protege (Luarmor) : le bot le dit clairement, livre la chaine et ne met RIEN en cache
        cache_dir = SUITE / "results" / "cache"
        before = set(cache_dir.glob("*")) if cache_dir.exists() else set()
        text, dt = await run_stub(
            "import sys, json\nopen(sys.argv[3], 'w').write('-- ===== Chaine de chargement : 1 niveau(x) =====\\n')\n"
            "print(json.dumps({'ok': True, 'engine': 'loader_chain', 'code': 0, 'detected': [], 'protected': 'Luarmor', 'log': '',\n"
            "  'chain': [{'url': 'https://raw.githubusercontent.com/a/b/main/X', 'bytes': 108, 'sha256': 'ab'}]}))\n")
        check("protégé par Luarmor" in text and "chargeur suivi" in text.lower() and "raw.githubusercontent.com" in text and "Échec" in text,
              "chargeur protege : le message dit « protégé par Luarmor », statut Échec (rien n'est contourne), montre la chaine")
        check("protégé par Luarmor" in text and (set(cache_dir.glob("*")) if cache_dir.exists() else set()) == before,
              "chargeur : aucun resultat mis en cache (le contenu distant peut changer)")

        # 13. cache : 2e envoi instantane ; recalculer:True refait le calcul
        L._cache_get = real_cache_get
        reset(server)
        await tools.process.callback(tools, mk(), None, att)
        reset(server)
        t0 = time.monotonic()
        await tools.process.callback(tools, mk(), None, att)
        dt = time.monotonic() - t0
        check(has_result(server.channel_messages) and any("cache" in (m["content"] or "") for m in server.channel_messages)
              and dt < 3, f"cache : resultat instantane ({dt:.1f}s)")
        reset(server)
        await etc.deobf.callback(etc, mk(name="deobf"), None, att, "auto", None, True)
        check(not any("⚡ cache" in (m["content"] or "") for m in server.channel_messages) and has_result(server.channel_messages),
              "cache : recalculer:True refait le calcul")
        L._cache_get = lambda sha, moteur: None

        # 14. /deobf_annuler : arrete les jobs en cours et tous leurs processus
        d = stub("import subprocess, time\nsubprocess.Popen(['sleep', '4545'], start_new_session=True)\n"
                 "print('[*] tracing x (run 1)...', flush=True)\ntime.sleep(120)\n")
        os.environ["DEOBF_SUITE_DIR"] = str(d)
        L._bootstrap = lambda: READY
        reset(server)

        async def cancel_later():
            await asyncio.sleep(1.5)
            await etc.deobf_annuler.callback(etc, mk(name="deobf_annuler"), None)
        t0 = time.monotonic()
        await asyncio.gather(tools.process.callback(tools, mk(), None, att), cancel_later())
        dt = time.monotonic() - t0
        await asyncio.sleep(1)
        left = os.popen("pgrep -f '[s]leep 4545' | wc -l").read().strip()
        check(any("annule" in (e["content"] or "") for e in server.edits) and dt < 15 and left == "0",
              f"/deobf_annuler : job arrete en {dt:.1f}s, « annule » affiche, aucun processus restant ({left})")
        os.environ.pop("DEOBF_SUITE_DIR")
        L._bootstrap = real_bootstrap

        # 15. Discord refuse de modifier le tableau de bord
        slow_on()
        reset(server)
        server.edit_script = [(404, 10008, "Unknown Message")] * 6
        await tools.process.callback(tools, mk(), None, att)
        n_boards = len([m for m in server.channel_messages if "obfuscation" in (m["content"] or "").lower() and not m["files"]])
        check(n_boards >= 2 and not any("Je n'arrive plus" in (m["content"] or "") for m in server.channel_messages),
              f"edition refusee : le suivi continue dans un nouveau message, sans bavardage ({n_boards} messages de suivi)")
        check(has_result(server.channel_messages), "edition refusee : le resultat arrive quand meme")
        slow_off()

        # 16. redemarrage pendant un job
        reset(server)
        L._JOBS.clear(); L._JOBS_LOADED = True
        L._JOBS.append({"id": 1, "name": "x.lua", "status": "en cours", "channel_id": 55, "msg_id": 424242})
        n = await L.recover_interrupted(bot, wait_ready=False)
        check(n == 1 and any("Job interrompu" in (e["content"] or "") and e["id"] == "424242" for e in server.edits),
              "redemarrage pendant un job : le salon est prevenu")
        L._JOBS.clear()

        # 17. diagnostic
        reset(server)
        await etc.deobf_etat.callback(etc, mk(name="deobf_etat"))
        text = " ".join(f["content"] or "" for f in server.followups)
        check("Memoire :" in text and "CPU :" in text and "Jobs en cours" in text and "Ecriture dans ce salon (suivi + fichier du resultat) : OK" in text,
              "/deobf_etat : CPU, memoire du conteneur, jobs en cours, test d'ecriture")

        # 18. petit-enfant qui garde le tube ouvert
        st = stub("import subprocess, sys, json\nsubprocess.Popen(['sleep', '4242'])\n"
                  "print(json.dumps({'ok': False, 'engine': 'stub', 'log': 'stub'}))\n")
        os.environ["DEOBF_SUITE_DIR"] = str(st)
        t1 = time.monotonic()
        res = await L._run_router(st / "a", st / "b", None, 30)
        os.environ.pop("DEOBF_SUITE_DIR")
        await asyncio.sleep(0.3)
        left = os.popen("pgrep -f '[s]leep 4242' | wc -l").read().strip()
        check(res.get("engine") == "stub" and time.monotonic() - t1 < 15 and left == "0", "tube garde ouvert par un orphelin : aucun blocage")

        # 19. /analyse
        reset(server)
        await tools.analyse.callback(tools, mk(name="analyse"), None,
                                     server.attachment(bot, "a.lua", b'print("x")\nlocal s = game:HttpGet("https://example.com/p.lua")\n'))
        check(bool(server.followups) and server.followups[0]["embeds"], "/analyse : embed envoye")
    finally:
        cleanup()
        await bot.close()
        await server.stop()


asyncio.run(main())
print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : jobs simultanes et livraison dans le salon verifies avec la vraie bibliotheque discord.py")
