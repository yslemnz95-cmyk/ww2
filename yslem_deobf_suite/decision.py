"""
decision.py -- detection du contenu et choix AUTOMATIQUE du moteur (module pur : aucun import Discord, aucun reseau).

    d = decide(raw_bytes, filename)

  d.language      lua | luau | json | html | zip | binary | text | empty
  d.obfuscator    nom lisible, ou None (rien reconnu avec une preuve technique suffisante)
  d.version       version quand une regle la donne reellement (jamais devinee)
  d.engine        moteur retenu (celui du detecteur de la suite), ou le moteur generique `trace`, ou None
  d.kind          source | trace | plain | unsupported | gated | unavailable | archive | invalid
  d.supported     True seulement si un moteur compatible existe et peut tourner
  d.gate          service de protection d'acces reconnu (cle / HWID / licence) : JAMAIS contourne
  d.evidence      les indices techniques (extraits courts) qui justifient l'identification
  d.fallbacks     autres moteurs reconnus, essayes par le routeur si le premier echoue

Principes : on ne dit « reconnu » que si une regle d'un moteur correspond (confiance >= DEOBF_MIN_CONFIDENCE) ; un moteur
indisponible n'est jamais presente comme pris en charge ; un script protege par une cle / licence est signale, pas contourne.
Pour ajouter un obfuscateur : un dossier engines/<nom>/engine.json avec ses regles `detect` -- rien d'autre a modifier ici
(champs facultatifs de engine.json : "display", "kind" = source|trace, "unavailable" = raison si le moteur ne peut pas tourner).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import deobf_router as R  # noqa: E402
import loader_chain  # noqa: E402

GENERIC_ENGINE = "trace"

# Connaissances sur les moteurs livres ; un nouveau moteur les declare dans son engine.json (display / kind / unavailable).
_FACTS: dict[str, dict] = {
    "wearedevs": {"display": "WeAreDevs / Prometheus", "kind": "source"},
    "leakd_luaobfuscator": {"display": "LuaObfuscator.com", "kind": "source"},
    "deobf_py": {"display": "IronBrew 1", "kind": "source"},
    "hercules": {"display": "Hercules", "kind": "source"},
    "ironveil": {"display": "Ironveil", "kind": "source"},
    "legaxyobf": {"display": "legaxyobf", "kind": "source"},
    "luauforge": {"display": "LuauForge", "kind": "source"},
    "moonsec_v3": {"display": "MoonSec V3", "kind": "source"},
    "ironbrew2": {"display": "IronBrew 2", "kind": "source"},
    "moonsec_trace": {"display": "MoonSec V2/V3", "kind": "trace"},
    "psu_trace": {"display": "PSU Obfuscator", "kind": "trace"},
    "centurion_v6": {"display": "Centurion v6", "kind": "unavailable",
                     "unavailable": "moteur non fonctionnel ici (luau-compile requis, et la v6.1 exige un vrai Roblox)"},
    GENERIC_ENGINE: {"display": "générique", "kind": "trace"},
}

# version : (regex, format) testee sur le debut du texte ; seulement quand la regle dit vraiment la version
_VERSION_RULES: dict[str, list[tuple[re.Pattern, str]]] = {
    "wearedevs": [(re.compile(r"\A\s*--\[\[\s*v(\d+(?:\.\d+)*)\s+https?://wearedevs\.net/obfuscator", re.I), "v{0}")],
    "moonsec_trace": [(re.compile(r"Protected_by_MoonSecV2"), "V2"),
                      (re.compile(r"This file was protected with MoonSec V3"), "V3")],
    "moonsec_v3": [(re.compile(r"This file was protected with MoonSec V3"), "V3")],
    "hercules": [(re.compile(r"Hercules[^\n]{0,40}?v?(\d+\.\d+(?:\.\d+)?)", re.I), "v{0}")],
    "ironveil": [(re.compile(r"Ironveil[^\n]{0,40}?v?(\d+(?:\.\d+)*)", re.I), "v{0}")],
    "centurion_v6": [(re.compile(r"Centurion[^\n]{0,40}?v?(6(?:\.\d+)?)", re.I), "v{0}")],
    "ironbrew2": [(re.compile(r"\A.{0,40}SFG ENCRYPTED", re.S), "fork SFG"),
                  (re.compile(r"\A.{0,40}NCDev Team Evolution", re.S), "fork NCDev"),
                  (re.compile(r"\A.{0,40}AztupBrew", re.S), "AztupBrew"),
                  (re.compile(r"\A.{0,40}moonstrike\.cc", re.S), "fork moonstrike"),
                  (re.compile(r"\A.{0,300}IronBrew2 Fork By KrystekYT", re.S), "fork KrystekYT")],
}

# services qui ne livrent le script qu'a un executeur autorise : on les reconnait, on ne les contourne pas
_GATES: list[tuple[str, re.Pattern]] = [
    ("Luarmor", re.compile(r"luarmor\.(?:net|io)|\bldrupd8m\b|\bv4_init_", re.I)),
    ("FlowAuth", re.compile(r"flowauth\.net", re.I)),
    ("LuaProtect", re.compile(r"luaprotect\.dev|\bluaprotect\b", re.I)),
]
_KEY_HINTS = re.compile(r"\bscript_key\s*=|getgenv\(\)\s*\.\s*(?:script_)?key\b|\bEnter\s+(?:your\s+)?key\b|\bkey\s*system\b", re.I)

_BORONIDE_RE = re.compile(r"Boronide™|Boronide\s*(?:Obfuscation|Premium|Free|,\s*v\d)|discord\.gg/boronide|discord\.gg/BZEjFbeUvk", re.I)

_URL = re.compile(r"https?://[^\s\"'<>)\]\\]{6,}", re.I)
_LUAU_HINTS = [re.compile(p) for p in (
    r"\blocal\s+\w+\s*:\s*(?:number|string|boolean|any|\{|[A-Z]\w+)\b", r"\bfunction\s*\w*\s*\([^)]*:\s*\w+", r"\)\s*:\s*\w+\s*(?:\n|$)",
    r"\bcontinue\b", r"[A-Za-z_\]\)]\s*(?:\+=|-=|\*=|/=)", r"\bexport\s+type\b", r"\btypeof\s*\(", r"`[^`\n]*\{[^}\n]+\}[^`\n]*`")]

_NOT_PLAIN = [re.compile(p) for p in (r"(?:\\\d{3}){12,}", r"\b_0x[0-9a-f]{3,}\b", r"\bgetfenv\s*\(\s*\)?", r"[A-Za-z0-9+/=]{300,}",
                                      r"(?:\bl{4,}|\bI{4,}|\b[Oo0]{4,})\w*\s*=", r"\bstring\.char\s*\((?:\s*\d+\s*,){10,}")]


@dataclass
class Decision:
    language: str = "text"
    size: int = 0
    obfuscator: Optional[str] = None
    version: Optional[str] = None
    engine: Optional[str] = None
    confidence: float = 0.0
    kind: str = "none"
    supported: bool = False
    gate: Optional[str] = None
    requires_key: bool = False
    links: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        """« Obfuscateur » lisible : nom + version, ou la raison pour laquelle il n'y en a pas."""
        if self.obfuscator:
            return self.obfuscator + (f" {self.version}" if self.version else "")
        return {"plain": "none (readable code)", "archive": ".zip archive", "invalid": "invalid content",
                "loader": "loader (loadstring/HttpGet)"}.get(self.kind, "not recognized")

    @property
    def verdict(self) -> str:
        """Une ligne : ce que le bot peut faire de ce contenu."""
        if self.kind == "gated":
            return (f"Protected by {self.gate}: a license key or authorization is required. "
                    "The bot does not bypass this protection. Send the unprotected source, or ask the script author.")
        if self.kind == "unsupported":
            return "Obfuscator recognized but not supported yet."
        if self.kind == "unavailable":
            return "Engine not available on this machine."
        if self.kind == "invalid":
            return self.notes[0] if self.notes else "Invalid content."
        if self.kind == "plain":
            return "Nothing to deobfuscate (readable code)."
        if self.kind == "archive":
            return "Each script in the archive will be analyzed."
        if self.kind == "loader":
            return "Loader: the remote script will be fetched, then analyzed."
        if self.kind == "trace":
            return f"Supported ({self.engine}) — partial result: execution trace"
        if self.supported:
            return f"Supported ({self.engine})"
        return "Not supported."

    def as_log(self) -> str:
        return (f"lang={self.language} obf={self.obfuscator!r} ver={self.version} engine={self.engine} kind={self.kind} "
                f"conf={self.confidence:.2f} gate={self.gate} supported={self.supported}")


# ── contenu ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def detect_language(raw: bytes, filename: str = "") -> tuple[str, list[str]]:
    """(langage, remarques). Reconnait aussi les reponses vides, HTML (page d'erreur), JSON, archives et binaires."""
    notes: list[str] = []
    head = raw[:4096]
    if not raw.strip():
        return "empty", ["réponse vide"]
    if head[:4] == b"PK\x03\x04":
        return "zip", []
    if head[:4] == b"\x1bLua" or head[:4] == b"\x1bLJ\x02" or head[:3] == b"\x1bLJ":
        return "binary", ["bytecode Lua compilé (pas du texte)"]
    nul = head.count(b"\x00")
    if nul > 4 or (head and sum(1 for b in head if b < 9 or 13 < b < 32) / len(head) > 0.05):
        return "binary", ["contenu binaire (pas du texte)"]
    text = raw[:200_000].decode("utf-8", "replace")
    low = text.lstrip().lower()
    if low.startswith(("<!doctype html", "<html", "<head", "<body")) or ("<html" in low[:600] and "</html>" in low):
        t = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
        return "html", ["page HTML, pas un script" + (f" ({t.group(1).strip()[:60]})" if t else "")]
    if low[:1] in "{[" and len(raw) < 2_000_000:
        try:
            json.loads(text if len(raw) <= 200_000 else raw.decode("utf-8", "replace"))
            return "json", ["JSON, pas un script"]
        except ValueError:
            pass
    luau = sum(1 for p in _LUAU_HINTS if p.search(text[:150_000]))
    lua_like = re.search(r"\b(?:local|function|end|then|game|print|require)\b", text) is not None
    if not lua_like:
        return "text", ["aucune syntaxe Lua reconnue"]
    return ("luau" if luau >= 2 else "lua"), notes


def find_links(text: str, limit: int = 20) -> list[str]:
    seen: dict[str, None] = {}
    for m in _URL.finditer(text[:3_000_000]):
        u = m.group(0).rstrip(".,;")
        seen.setdefault(u, None)
        if len(seen) >= limit:
            break
    return list(seen)


def detect_gate(text: str, links: list[str]) -> Optional[str]:
    """Service de protection d'acces reconnu dans le texte ou dans les adresses (Luarmor, FlowAuth, LuaProtect)."""
    for name, pat in _GATES:
        if pat.search(text[:300_000]) or any(pat.search(u) for u in links):
            return name
    return None


def _looks_obfuscated(text: str) -> bool:
    lines = text.splitlines() or [""]
    avg = len(text) / max(1, len(lines))
    longest = max(len(l) for l in lines)
    if longest > 3000 or avg > 400:
        return True
    return sum(1 for p in _NOT_PLAIN if p.search(text[:400_000])) >= 2


# ── moteurs ───────────────────────────────────────────────────────────────────────────────────────────────────────────

_META_CACHE: dict[str, dict] = {}


def engine_meta(e: "R.Engine") -> dict:
    """display / kind / unavailable : valeurs par defaut du code, surchargees par engine.json (nouveaux moteurs)."""
    key = f"{e.name}@{e.path}"
    if key in _META_CACHE:
        return _META_CACHE[key]
    meta = dict(_FACTS.get(e.name, {"display": e.label.split(" (")[0][:40], "kind": "source"}))
    try:
        cfg = json.loads((e.path / "engine.json").read_text(encoding="utf-8"))
        for k in ("display", "kind", "unavailable"):
            if cfg.get(k):
                meta[k] = cfg[k]
    except (OSError, ValueError):
        pass
    _META_CACHE[key] = meta
    return meta


def _evidence(e: "R.Engine", text: str) -> list[str]:
    out = []
    for rule in e.detect:
        try:
            m = re.search(rule["regex"], text)
        except re.error:
            continue
        if m:
            snip = re.sub(r"\s+", " ", m.group(0))[:70]
            snip = re.sub(r"[^\x20-\x7e]", "·", snip)
            out.append(f"règle {e.name} ({rule.get('confidence', '?')}) : « {snip} »")
    return out[:3]


def _version(engine: str, text: str) -> Optional[str]:
    for pat, fmt in _VERSION_RULES.get(engine, []):
        m = pat.search(text[:6000]) or pat.search(text[-3000:])
        if m:
            return fmt.format(*m.groups())
    return None


def engine_usable(e: "R.Engine") -> tuple[bool, str]:
    """(utilisable ?, raison). Node et Luau sont installes automatiquement au premier usage : leur absence ne bloque pas."""
    meta = engine_meta(e)
    if meta.get("kind") == "unavailable" or meta.get("unavailable"):
        return False, str(meta.get("unavailable") or "moteur indisponible")
    if not e.safe:
        return False, "moteur non sûr pour du contenu non fiable"
    miss = [m for m in e.missing_requirements() if not re.match(r"(node|luau|python3)\b", m)]
    if miss:
        return False, "prérequis manquant : " + ", ".join(miss)[:80]
    return True, ""


def decide(raw: bytes, filename: str = "", engines: Optional[list] = None) -> Decision:
    d = Decision(size=len(raw))
    d.language, d.notes = detect_language(raw, filename)
    if d.language in ("empty", "html", "json", "binary", "text"):
        d.kind = "invalid"
        return d
    if d.language == "zip":
        d.kind, d.supported = "archive", True
        return d
    text = raw.decode("latin-1")
    d.links = find_links(raw.decode("utf-8", "replace"))
    d.gate = detect_gate(text, d.links)
    d.requires_key = bool(d.gate) or bool(_KEY_HINTS.search(text[:300_000]))
    if d.requires_key and not d.gate:
        d.notes.append("le script demande une clé (système de clé du script lui-même)")
    engines = engines if engines is not None else R.load_engines()
    by_name = {e.name: e for e in engines}
    detected = [(n, c, l) for n, c, l in R.detect_text(text, engines) if c >= R.MIN_CONFIDENCE]

    if d.gate:                      # protection d'acces : on le dit, on ne la contourne pas
        d.kind = "gated"
        d.obfuscator = d.gate
        d.notes.append("la protection ne livre le code qu'à un exécuteur autorisé : rien à déobfusquer ici")
        return d

    if not detected and loader_chain.find_target(text):
        # `loadstring(game:HttpGet("https://..."))()` : le vrai code est a l'adresse indiquee, le routeur le recupere
        d.kind, d.engine, d.supported = "loader", "loader_chain", True
        d.obfuscator = None
        d.notes.append("chargeur : le script distant sera récupéré puis analysé")
        return d

    # Boronide : son en-tete imite « Protected_by_MoonSecV2 » (meme forme que MoonSec V2) ; il n'a pas de moteur ici.
    # Verifie avant toute detection MoonSec : ce n'est PAS du MoonSec.
    if _BORONIDE_RE.search(text[:400_000]):
        d.obfuscator, d.kind = "Boronide", "unsupported"
        d.evidence = ["signature « Boronide » (son en-tête imite MoonSec V2, ce n'est pas MoonSec)"]
        d.notes.append("Boronide : aucun moteur dans ce bot (pas de trace MoonSec, qui serait trompeuse)")
        return d

    if detected:
        top, conf, _label = detected[0]
        e = by_name[top]
        meta = engine_meta(e)
        d.obfuscator, d.confidence = meta["display"], conf
        d.version = _version(top, text)
        d.evidence = _evidence(e, text)
        d.fallbacks = [n for n, c, _ in detected[1:3] if n in by_name]
        ok, why = engine_usable(e)
        if not ok:
            d.kind, d.engine = "unavailable", top
            d.notes.append(why)
            return d
        d.engine, d.kind, d.supported = top, meta.get("kind", "source"), True
        if d.kind == "trace":
            d.notes.append("ce moteur livre la trace d'exécution, pas le code source")
        return d

    if R.LURAPH_UNSUPPORTED_RE.search(text[:65536]):
        d.obfuscator, d.kind = "Luraph", "unsupported"
        d.evidence = ["bannière « Luraph Obfuscator » / lura.ph"]
        d.notes.append("Luraph n'est plus pris en charge par ce bot")
        return d

    if not _looks_obfuscated(text):
        d.kind = "plain"
        return d

    # obfuscation probable mais aucun obfuscateur reconnu : moteur generique (trace du bac a sable)
    g = by_name.get(GENERIC_ENGINE)
    if g is not None and engine_usable(g)[0]:
        d.engine, d.kind, d.supported = GENERIC_ENGINE, "trace", True
        d.notes.append("obfuscateur non reconnu : moteur générique (trace d'exécution)")
    else:
        d.kind = "unsupported"
        d.notes.append("obfuscateur non reconnu et moteur générique indisponible")
    return d
