#!/usr/bin/env python3
"""
deobf_router.py -- detecte l'obfuscateur d'un script Lua/Luau et lance le bon
moteur de deobfuscation (un sous-processus par moteur, timeout dur, taille
d'entree plafonnee). Aucun moteur n'est importe dans ce processus.

CLI
    python3 deobf_router.py list                              # moteurs + prerequis
    python3 deobf_router.py detect  <in.lua>                  # [(moteur, confiance)]
    python3 deobf_router.py run     <in.lua> <out.lua> [--engine NOM] [--json]
    python3 deobf_router.py selftest                          # detection sur les echantillons

Un moteur = un dossier engines/<nom>/ avec engine.json :
    {"name", "label", "detect": [{"regex", "confidence"}], "cmd": [...],
     "timeout": 120, "safe_for_untrusted": true, "requires": [...], "notes": ""}
`cmd` contient {in} et {out} ; il est lance avec cwd = dossier du moteur.

Securite : un moteur marque safe_for_untrusted=false n'est JAMAIS choisi
automatiquement et ne tourne que si ENGINE_ALLOW_UNSAFE=1 (a n'utiliser que
dans un conteneur/VM sans reseau ni secrets).
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bootstrap  # noqa: E402  (Node.js + Luau patche : fournis automatiquement)
import loader_chain  # noqa: E402  (suit `loadstring(game:HttpGet(url))()`)

ENGINES_DIR = Path(os.environ.get("DEOBF_ENGINES_DIR", HERE / "engines"))
MAX_INPUT_BYTES = int(os.environ.get("DEOBF_MAX_INPUT", 16 * 1024 * 1024))
MIN_CONFIDENCE = float(os.environ.get("DEOBF_MIN_CONFIDENCE", "0.5"))
DETECT_SCAN_BYTES = 8 * 1024 * 1024
OUTPUT_TAIL = 3000


@dataclass
class Engine:
    name: str
    label: str
    path: Path
    detect: list = field(default_factory=list)
    cmd: list = field(default_factory=list)
    timeout: int = 120
    safe: bool = True
    requires: list = field(default_factory=list)
    notes: str = ""
    order: int = 0

    def missing_requirements(self) -> list[str]:
        """Prerequis binaires manquants (python3 / node / dotnet / luau)."""
        missing = []
        for req in self.requires:
            tool = req.split()[0].split("-")[0] if isinstance(req, str) else ""
            if tool in ("node", "dotnet", "python3", "luau") and not self._have(tool):
                missing.append(req)
        return missing

    def _have(self, tool: str) -> bool:
        if tool == "node":
            return bootstrap.node_exe() is not None
        if tool == "luau":
            return any((self.path / sub / "luau").exists() for sub in ("bin", "deobf/bin")) \
                or (self.path.parent / "sandbox" / "bin" / "luau").exists() \
                or bool(shutil.which("luau")) or bool(os.environ.get("LURAPH_LUAU"))
        if tool == "dotnet":
            # runtime .NET 9 : present, ou telechargeable par bootstrap.ensure_dotnet() (archive officielle connue pour cette machine)
            return bootstrap.dotnet_exe() is not None or (platform.system(), platform.machine()) in bootstrap.DOTNET_ARCHIVES
        return bool(shutil.which(tool))


def load_engines(engines_dir: Path = ENGINES_DIR) -> list[Engine]:
    engines: list[Engine] = []
    if not engines_dir.is_dir():
        return engines
    for i, d in enumerate(sorted(p for p in engines_dir.iterdir() if p.is_dir())):
        cfg_path = d / "engine.json"
        if not cfg_path.exists():
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cmd = cfg.get("cmd") or ["python3", "run.py", "{in}", "{out}"]
        if isinstance(cmd, str):
            cmd = cmd.split()
        engines.append(Engine(
            name=cfg.get("name", d.name), label=cfg.get("label", d.name), path=d,
            detect=cfg.get("detect") or [], cmd=cmd, timeout=int(cfg.get("timeout", 120)),
            safe=bool(cfg.get("safe_for_untrusted", True)), requires=cfg.get("requires") or [],
            notes=cfg.get("notes", ""), order=i,
        ))
    return engines


def read_text(path: Path) -> str:
    """Le debut du fichier (8 Mo) ; pour un plus gros fichier, + sa fin (les regles ancrees sur \\Z la voient)."""
    with open(path, "rb") as f:
        head = f.read(DETECT_SCAN_BYTES)
        if len(head) < DETECT_SCAN_BYTES:
            return head.decode("latin-1")
        f.seek(-8192, os.SEEK_END)
        return (head + b"\n" + f.read()).decode("latin-1")


def detect_text(text: str, engines: Optional[list[Engine]] = None) -> list[tuple[str, float, str]]:
    """[(engine, confidence, label)] triee par confiance decroissante."""
    engines = engines if engines is not None else load_engines()
    found = []
    for e in engines:
        best = 0.0
        for rule in e.detect:
            try:
                if re.search(rule["regex"], text):
                    best = max(best, float(rule.get("confidence", 0.5)))
            except re.error:
                continue
        if best > 0:
            found.append((e.name, best, e.label, e.order))
    found.sort(key=lambda x: (-x[1], x[3]))
    return [(n, c, l) for n, c, l, _ in found]


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


LURAPH_UNSUPPORTED_RE = re.compile(r"protected using Luraph Obfuscator|lura\.ph", re.I)


def run_engine(engine: Engine, src: Path, dst: Path, timeout: Optional[int] = None, stream: bool = False,
               stage2_dir: Optional[Path] = None) -> dict:
    """Lance un moteur sur src -> dst. Retourne un dict de resultat (jamais d'exception)."""
    src, dst = Path(src).resolve(), Path(dst).resolve()   # le moteur tourne avec cwd = son dossier
    t0 = time.monotonic()
    res = {"engine": engine.name, "label": engine.label, "ok": False, "code": None,
           "elapsed": 0.0, "out_bytes": 0, "log": ""}
    if not engine.safe and os.environ.get("ENGINE_ALLOW_UNSAFE") != "1":
        res["log"] = f"moteur '{engine.name}' non sur pour du contenu non fiable (ENGINE_ALLOW_UNSAFE=1 requis)"
        res["code"] = 6
        return res
    # Node.js / Luau patche : fournis automatiquement au premier usage (voir bootstrap.py)
    needs = " ".join(engine.requires)
    try:
        bootstrap.ensure_ready(log=lambda m: print("[router] " + m, file=sys.stderr, flush=True),
                               need_node=bool(re.search(r"\bnode\b", needs)),
                               need_luau=bool(re.search(r"\bluau\b", needs)))
    except bootstrap.BootstrapError as exc:
        res["log"] = f"preparation automatique impossible : {exc}"
        res["code"] = 4
        return res
    missing = engine.missing_requirements()
    if missing:
        res["log"] = "prerequis manquants : " + ", ".join(missing)
        res["code"] = 4
        return res
    cmd = [a.replace("{in}", str(src)).replace("{out}", str(dst)) for a in engine.cmd]
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "LURAPH_LUAU",
                                      "LURAPH_LUAU_AST", "DOTNET_ROOT", "ENGINE_ALLOW_UNSAFE",
                                      "ENGINE_TIMEOUT", "CENT_LUAU_LUAU", "CENT_LUAU_LUAU_AST",
                                      "CENT_LUAU_LUAU_COMPILE", "PYTHON_BIN", "LURAPH_TIMEOUT", "LURAPH_BUDGET",
                                      "DEOB_LIFT_RETRIES", "DEOB_LIFT_PARALLEL", "DEOB_LIFT_BUDGET",
                                      "DEOB_LIFT_GRACE", "DEOB_STALL_SECONDS") if k in os.environ}
    prefix = bootstrap.path_prefix()
    if prefix:
        env["PATH"] = prefix + os.pathsep + env.get("PATH", os.defpath)
    budget = int(timeout or engine.timeout)
    env["ENGINE_TIMEOUT"] = str(budget)
    if stage2_dir is not None:          # le moteur y depose le code complet de chaque loadstring (second etage)
        env["DEOBF_STAGE2_OUT"] = str(stage2_dir)
    # La sortie du moteur est lue ligne a ligne par un THREAD (et relayee en direct si stream=True : c'est ce qui
    # permet au bot d'afficher l'avancement reel) ; la fin du job = la fin du PROCESSUS (waitpid), jamais la
    # fermeture du tube : un petit-enfant orphelin qui la garderait ouverte ne peut plus retarder le resultat.
    import collections
    import threading
    try:
        proc = subprocess.Popen(cmd, cwd=str(engine.path), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as exc:
        res["log"] = f"impossible de lancer {cmd[0]}: {exc}"
        res["code"] = 127
        return res
    chunks: collections.deque = collections.deque()
    held = [0]

    def pump() -> None:
        for raw in iter(proc.stdout.readline, b""):
            chunks.append(raw)
            held[0] += len(raw)
            while held[0] > 4 * OUTPUT_TAIL and len(chunks) > 1:
                held[0] -= len(chunks.popleft())
            if stream:
                try:
                    sys.stdout.write(raw.decode("utf-8", "replace"))
                    sys.stdout.flush()
                except (OSError, ValueError):
                    pass

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=budget + 15)
        res["code"] = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        proc.wait()
        res["code"] = 124
        res["log"] = f"timeout apres {budget}s -- processus tue\n"
    finally:
        _kill_group(proc)                       # petits-enfants eventuels : aucun orphelin
    reader.join(timeout=5)
    out = b"".join(chunks)
    res["log"] += (out or b"").decode("utf-8", "replace")[-OUTPUT_TAIL:]
    res["elapsed"] = round(time.monotonic() - t0, 1)
    try:
        size = dst.stat().st_size if dst.exists() else 0
    except OSError:
        size = 0
    res["out_bytes"] = size
    res["ok"] = res["code"] == 0 and size > 0
    return res


def _follow_loader(src: Path, dst: Path, timeout: Optional[int], stream: bool) -> Optional[dict]:
    """Si `src` n'est qu'un chargeur (`loadstring(game:HttpGet("https://..."))()`), voir _chain_from_text.
    -> dict de resultat, ou None si `src` n'est pas un chargeur."""
    return _chain_from_text(src.read_bytes().decode("utf-8", "replace"), src.name, dst, timeout, stream)


def _chain_from_text(text: str, source_name: str, dst: Path, timeout: Optional[int], stream: bool,
                     intro: Optional[tuple] = None) -> Optional[dict]:
    """Si `text` n'est qu'un chargeur, telecharge l'adresse (voir loader_chain.py : garde-fous anti-SSRF, rien n'est
    execute), puis traite le script recupere comme n'importe quel script : deobfusque s'il est reconnu, sinon livre en
    clair. Le fichier rendu commence par la chaine de chargement. `intro` = (description, code) : le programme reel que
    `source_name` contenait (ex. sorti de la machine virtuelle LuauForge), place avant la chaine.
    -> dict de resultat, ou None si `text` n'est pas un chargeur."""
    t0 = time.monotonic()
    log = (lambda m: print(m, flush=True)) if stream else (lambda m: None)
    chain = loader_chain.resolve(text, log)
    if chain is None:
        return None
    levels = [{k: v for k, v in lv.items() if k != "text"} for lv in chain["levels"]]
    res = {"engine": "loader_chain", "label": "Chargeur (loadstring/HttpGet) suivi jusqu'au script reel", "code": 0,
           "detected": [], "chain": levels, "protected": chain["protected"], "log": ""}
    if not any("text" in lv for lv in chain["levels"]) and not chain["protected"]:
        res.update(ok=False, code=1, log=f"chargeur : {chain['error'] or 'rien a telecharger'}")
        return res
    final_code, label = None, ""
    if chain["final"] and not chain["protected"] and not chain["error"]:
        import tempfile as _tf
        with _tf.TemporaryDirectory(prefix="deobf_chain_") as td:
            tin, tout = Path(td) / "fetched.lua", Path(td) / "fetched_out.lua"
            tin.write_text(chain["final"], "utf-8")
            left = max(60, int((timeout or 1500) - (time.monotonic() - t0)))
            r = deobfuscate(tin, tout, None, left, stream, _depth=1)
            if r.get("ok") and tout.exists():
                final_code, label = tout.read_text("utf-8", "replace"), f"deobfusque par {r.get('engine')}"
                res["engine"] = f"loader_chain+{r.get('engine')}"
                res["log"] = r.get("log", "")
            else:
                final_code = chain["final"]
                label = ("code en clair, aucun obfuscateur reconnu" if not r.get("detected")
                         else f"obfusque ({r['detected'][0][0]}) mais non deobfusque")
                res["log"] = r.get("log", "")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(loader_chain.render(source_name, chain, final_code, label, intro), "utf-8")
    res.update(ok=True, out_bytes=dst.stat().st_size, elapsed=round(time.monotonic() - t0, 1))
    if chain["protected"]:
        log(f"[router] script protege par {chain['protected']} : contenu non recuperable, arret de la chaine")
    return res


def _chain_after_engine(r: dict, src: Path, dst: Path, timeout: Optional[int], stream: bool) -> None:
    """Apres un moteur qui livre un PROGRAMME (ex. luauforge : couches retirees puis machine virtuelle executee), si ce
    programme n'est lui-meme qu'un chargeur (`local r = game:HttpGet(url)` puis `loadstring(r)()`), on suit la chaine.
    Modifie `r` et `dst` en place ; en cas d'echec reseau le resultat du moteur est conserve tel quel."""
    try:
        program = dst.read_text("utf-8", "replace")
        if len(program) > 200_000 or not loader_chain.find_target(program):
            return
        keep = program
        res = _chain_from_text(program, src.name, dst, timeout, stream,
                               intro=("LuauForge : couches retirees, machine virtuelle executee dans le bac a sable", program))
        if res is None:
            return
        if not res.get("ok"):
            dst.write_text(keep, "utf-8")
            r["log"] = r.get("log", "") + "\n[router] chargeur non suivi : " + str(res.get("log", ""))[-200:]
            return
        r["engine"] = f"{r['engine']}+{res['engine']}"
        for k in ("chain", "protected"):
            r[k] = res.get(k)
        r["out_bytes"] = dst.stat().st_size
        r["log"] = r.get("log", "") + "\n[router] chargeur suivi : " + " -> ".join(lv["url"] for lv in res.get("chain", []))
    except Exception as exc:                            # le suivi ne doit jamais faire echouer un resultat deja obtenu
        r["log"] = r.get("log", "") + f"\n[router] chargeur ignore : {exc}"


STAGE2_MAX_BYTES = 4 * 1024 * 1024      # un second etage plus gros est ignore
STAGE2_MAX_COUNT = 8
STAGE2_DEPTH = 2                        # chargeur -> script -> script : au-dela, on n'insiste pas


def _stage2_sections(stage2_dir: Path, main_engine: str, depth: int, deadline: float, stream: bool) -> list[str]:
    """Le code que le script a charge par loadstring (sauve en entier par le moteur) : chaque morceau est
    deobfusque a son tour s'il est lui-meme obfusque (autre obfuscateur), sinon livre tel quel."""
    import hashlib
    out, seen = [], set()
    files = sorted(p for p in stage2_dir.glob("*.lua") if p.is_file()) if stage2_dir.is_dir() else []
    for f in files:
        if len(out) >= STAGE2_MAX_COUNT:
            break
        data = f.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        if not data.strip() or len(data) > STAGE2_MAX_BYTES or h in seen:
            continue
        seen.add(h)
        text = data.decode("latin-1")
        det = detect_text(text)
        top = det[0] if det else None
        if top and top[0] == main_engine and top[1] >= MIN_CONFIDENCE:
            continue                    # la VM interne deja traitee par ce moteur (ex. chunk Luraph v15)
        label = "code en clair"
        body = text
        lines = text.count("\n") + 1
        if not (top and top[1] >= MIN_CONFIDENCE) and (len(text) > 100_000 and len(text) / lines > 2000):
            # non reconnu ET illisible (des lignes de plusieurs Ko) : le recopier n'apporterait que du bruit
            out.append(f"-- ===== Second etage n{len(out) + 1} : {len(data)} octets charges par loadstring, obfusques par un "
                       f"outil non reconnu : non recopies (empreinte sha256 {h[:16]}) =====\n")
            continue
        if top and top[1] >= MIN_CONFIDENCE and depth < STAGE2_DEPTH:
            left = int(deadline - time.monotonic())
            if left > 60:
                with tempfile.TemporaryDirectory(prefix="deobf_stage2_") as td:
                    tin, tout = Path(td) / "stage2.lua", Path(td) / "stage2_out.lua"
                    tin.write_bytes(data)
                    if stream:
                        print(f"[router] second etage ({len(data)} octets) : {top[0]}", flush=True)
                    r = deobfuscate(tin, tout, None, left, stream, _depth=depth + 1)
                    if r.get("ok") and tout.exists():
                        body = tout.read_text("utf-8", "replace")
                        label = f"deobfusque par {r.get('engine')}"
                    else:
                        label = f"obfusque ({top[0]}), non deobfusque : {str(r.get('log', ''))[-200:]!r}"
            else:
                label = f"obfusque ({top[0]}), plus assez de temps pour le deobfusquer"
        n = len(out) + 1
        out.append(f"-- ===== Second etage n{n} : code charge par loadstring ({len(data)} octets, {label}) =====\n"
                   f"do local function second_etage_{n}(...)\n{body.rstrip()}\nend end\n")
    return out


def deobfuscate(src: Path, dst: Path, engine_name: Optional[str] = None,
                timeout: Optional[int] = None, stream: bool = False, _depth: int = 0) -> dict:
    """Detection (sauf --engine) puis execution. Retourne le dict de resultat. Le code charge par loadstring
    (second etage) est recupere en entier et ajoute en tete du resultat (deobfusque a son tour si besoin)."""
    engines = load_engines()
    by_name = {e.name: e for e in engines}
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if src.stat().st_size > MAX_INPUT_BYTES:
        return {"ok": False, "engine": None, "log": f"entree trop grosse (> {MAX_INPUT_BYTES} octets)"}
    if not engine_name and _depth == 0 and src.stat().st_size <= loader_chain.LOADER_MAX_SOURCE:
        res = _follow_loader(src, dst, timeout, stream)           # `loadstring(game:HttpGet(url))()` : le vrai code est la-bas
        if res is not None:
            return res
    detected = []
    if engine_name:
        if engine_name not in by_name:
            return {"ok": False, "engine": None, "log": f"moteur inconnu : {engine_name}"}
        chosen = [by_name[engine_name]]
    else:
        detected = detect_text(read_text(src), engines)
        chosen = [by_name[n] for n, c, _ in detected if c >= MIN_CONFIDENCE and by_name[n].safe]
        if not chosen:
            # Le detecteur local ne reconnait rien : un modele de langage (si une cle est fournie) nomme l'obfuscateur ;
            # son moteur n'est retenu que s'il est dans la liste fermee des moteurs installes et sur.
            hint = _model_engine(read_text(src), by_name, stream)
            if hint is not None:
                chosen = [hint[0]]
                detected = detected + [(hint[0].name, hint[1], "avis du modele : " + hint[2])]
        if not chosen and LURAPH_UNSUPPORTED_RE.search(read_text(src)[:65536]):
            return {"ok": False, "engine": None, "detected": detected,
                    "log": "Luraph n'est plus pris en charge par ce bot (support retire le 2026-11-09)."}
        if not chosen:
            return {"ok": False, "engine": None, "detected": detected,
                    "log": "aucun obfuscateur reconnu avec assez de confiance "
                           "(ou moteur reconnu non sur) -- utilisez --engine NOM pour forcer ; `--engine trace` "
                           "donne la trace du bac a sable (ce que le script fait), pas son source"}
    attempts = []
    deadline = time.monotonic() + int(timeout or max(e.timeout for e in chosen[:2]))
    for eng in chosen[:2]:
        if stream:
            conf = next((c for n, c, _ in detected if n == eng.name), None)
            print(f"[router] moteur : {eng.name}" + (f" (confiance {conf:.2f})" if conf is not None else " (impose)"),
                  flush=True)
        with tempfile.TemporaryDirectory(prefix="deobf_s2_") as s2:
            r = run_engine(eng, src, dst, timeout, stream, stage2_dir=Path(s2))
            if r["ok"]:
                try:
                    sections = _stage2_sections(Path(s2), eng.name, _depth, deadline, stream)
                except Exception as exc:                # le second etage ne doit jamais faire echouer le job
                    sections = []
                    r["log"] += f"\n[router] second etage ignore : {exc}"
                if sections:
                    main = dst.read_text("utf-8", "replace")
                    dst.write_text("".join(sections) + "\n-- ===== Script d'origine (premier etage) =====\n" + main,
                                   "utf-8")
                    r["stage2"] = len(sections)
                    r["out_bytes"] = dst.stat().st_size
                    msg = f"[router] {len(sections)} second(s) etage(s) (code charge par loadstring) ajoute(s) au resultat"
                    r["log"] += "\n" + msg
                    if stream:
                        print(msg, flush=True)
        r["detected"] = detected
        attempts.append(r)
        if r["ok"]:
            if eng.name == "luauforge" and _depth == 0 and os.environ.get("DEOBF_FOLLOW_LOADERS", "1") != "0":
                _chain_after_engine(r, src, dst, timeout, stream)
            r["attempts"] = [a["engine"] for a in attempts]
            return r
    # Repli : un moteur de SOURCE reconnu a echoue (variante non geree) -> la trace du bac a sable (partielle, jamais presentee
    # comme le source) vaut mieux qu'aucun resultat. Jamais si le moteur a ete impose, ni apres un moteur de trace.
    if not engine_name and _depth == 0 and "trace" in by_name and by_name["trace"].safe \
            and not any(a.get("engine") in ("trace", "moonsec_trace", "psu_trace") for a in attempts):
        r = run_engine(by_name["trace"], src, dst, timeout, stream)
        r["detected"] = detected
        attempts.append(r)
        if r["ok"]:
            r["log"] = "[router] repli sur la trace (le moteur de source a echoue)\n" + r.get("log", "")
            r["attempts"] = [a["engine"] for a in attempts]
            return r
    # Tous les moteurs reconnus ont echoue : on demande son avis au modele (un autre moteur que ceux deja essayes)
    if not engine_name and _depth == 0:
        tried = {a["engine"] for a in attempts}
        hint = _model_engine(read_text(src), by_name, stream, exclude=tried)
        if hint is not None:
            r = run_engine(hint[0], src, dst, timeout, stream)
            r["detected"] = detected + [(hint[0].name, hint[1], "avis du modele : " + hint[2])]
            attempts.append(r)
            if r["ok"]:
                r["attempts"] = [a["engine"] for a in attempts]
                return r
    last = attempts[-1]
    last["attempts"] = [a["engine"] for a in attempts]
    return last


def _model_engine(text: str, by_name: dict, stream: bool, exclude=()) -> Optional[tuple]:
    """(moteur, confiance, nom de l'obfuscateur) d'apres l'avis du modele, ou None. Jamais bloquant, jamais sans cle."""
    try:
        import obf_identify
        a = obf_identify.llm_identify(text)
    except Exception:       # noqa: BLE001 -- facultatif
        return None
    if not a or a.get("error"):
        if a and stream:
            print(f"[router] avis du modele indisponible ({a.get('error')})", flush=True)
        return None
    eng = by_name.get(a.get("engine"))
    if stream:
        print(f"[router] avis du modele ({a['provider']}) : {a['obfuscator']} -> moteur {a.get('engine')} "
              f"(confiance {a['confidence']:.2f}) {a['reason']}", flush=True)
    if eng is None or not eng.safe or eng.name in exclude or a["confidence"] < 0.5:
        return None
    return eng, a["confidence"], a["obfuscator"]


# ---------------------------------------------------------------------------

def _cmd_list(engines: list[Engine]) -> int:
    print(f"{'moteur':24} {'sur':4} {'prerequis':10} libelle")
    for e in engines:
        miss = e.missing_requirements()
        print(f"{e.name:24} {'oui' if e.safe else 'NON':4} {'ok' if not miss else 'MANQUE':10} {e.label}")
        if miss:
            print(f"{'':24} -> manque : {', '.join(miss)}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    cmd = argv[1]
    engines = load_engines()
    if cmd == "list":
        return _cmd_list(engines)
    if cmd == "detect" and len(argv) >= 3:
        for n, c, l in detect_text(read_text(Path(argv[2])), engines):
            print(f"{n}\t{c:.2f}\t{l}")
        return 0
    if cmd == "run" and len(argv) >= 4:
        want_json = "--json" in argv
        engine = argv[argv.index("--engine") + 1] if "--engine" in argv else None
        timeout = int(argv[argv.index("--timeout") + 1]) if "--timeout" in argv else None
        src, dst = Path(argv[2]), Path(argv[3])
        res = deobfuscate(src, dst, engine, timeout, stream=want_json)
        if want_json:
            print(json.dumps(res))
        else:
            print(f"[router] moteur={res.get('engine')} ok={res.get('ok')} octets={res.get('out_bytes')} "
                  f"{res.get('elapsed')}s", file=sys.stderr)
            if not res.get("ok"):
                print(res.get("log", ""), file=sys.stderr)
        return 0 if res.get("ok") else 1
    if cmd == "selftest":
        import importlib.util
        spec = importlib.util.spec_from_file_location("selftest", HERE / "selftest.py")
        if spec is None or spec.loader is None:
            print("selftest.py introuvable")
            return 2
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.main()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
