"""
result_tools.py -- nettoyage et classement des resultats des moteurs (module pur : aucun import Discord).

  clean_output(texte)            retire les bannieres / en-tetes / remarques des moteurs en TETE du fichier, conserve tout
                                 commentaire qui fait partie du code, et renvoie aussi ce que ces en-tetes disaient (meta).
  classify(res, texte, meta)     statut honnete : REUSSI, PARTIEL ou ECHEC -- jamais « reussi » pour un resultat incomplet
                                 (trace d'execution, blocs non reconstruits, chaines encore chiffrees, script protege...).

Seules les lignes de commentaire du DEBUT du fichier qui correspondent a un motif connu de moteur sont retirees ; la
premiere ligne qui n'est ni vide ni un message de moteur arrete le nettoyage : le reste du fichier n'est pas touche.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

SUCCESS, PARTIAL, FAILED = "success", "partial", "failed"

# ── messages de moteurs, en tete de fichier ───────────────────────────────────────────────────────────────────────────
# (nom, motif sur la ligne de commentaire sans le « -- » initial)
_BANNER_RULES: list[tuple[str, re.Pattern]] = [
    # bannieres de publicite / signature
    ("signature", re.compile(r"(?:discord\.gg|dsc\.gg|discord\.com/invite)/\S+", re.I)),
    ("signature", re.compile(r"\bby\s+LeakD\b", re.I)),
    ("signature", re.compile(r"Why do i love gpt", re.I)),
    # deobf_py (IronBrew)
    ("deobf_py", re.compile(r"^Local names are inferred from use", re.I)),
    ("deobf_py", re.compile(r"^source:\s", re.I)),
    ("deobf_py", re.compile(r"^yeah this ran at runtime", re.I)),
    ("deobf_py", re.compile(r"^not gonna be full", re.I)),
    ("deobf_py", re.compile(r"^run status:", re.I)),
    ("deobf_py_raw", re.compile(r"^\s{2,}\S*(?:/|\\)\S+")),          # lignes de pile d'appels : « --   /tmp/x.lua:12 function f »
    # traces du bac a sable
    ("trace", re.compile(r"^TRACE\s*\(", re.I)),
    ("trace", re.compile(r"^Ce n'est PAS le code source", re.I)),
    ("trace", re.compile(r"^Statut d'execution dans le bac a sable", re.I)),
    ("trace", re.compile(r"^\(la trace s'arrete", re.I)),
    ("trace", re.compile(r"^\(le script a plante dans le bac", re.I)),
    ("trace", re.compile(r"^\(le script s'est termine", re.I)),
    ("trace", re.compile(r"^warning:\s*\d+\s+unknown global", re.I)),
    ("trace", re.compile(r"^\(le releve de la machine", re.I)),
    # releve WeAreDevs
    ("wearedevs", re.compile(r"^Source RECONSTRUIT", re.I)),
    ("wearedevs", re.compile(r"^PAS le fichier d'origine", re.I)),
    ("wearedevs", re.compile(r"^Chaines chiffrees\s*:", re.I)),
    ("wearedevs", re.compile(r"^Verification\s*:", re.I)),
    ("wearedevs", re.compile(r"^Le fichier contient aussi le code parasite", re.I)),
    # IronBrew 2 (fork KrystekYT) : bandeau du moteur ; le resultat est toujours partiel (voir classify)
    ("ironbrew2", re.compile(r"^IronBrew2 \[decompile\]", re.I)),
    # MoonSec V3 (devirtualisation + LuaDec) : bandeau du moteur et en-tete que LuaDec ajoute lui-meme
    ("moonsec", re.compile(r"^MoonSec V3 \[(?:decompile|desassemblage)\]", re.I)),
    ("moonsec", re.compile(r"^filename:\s*$", re.I)),
    ("moonsec", re.compile(r"^version:\s*lua5\d\s*$", re.I)),
    ("moonsec", re.compile(r"^line:\s*\[\d+,\s*\d+\]\s+id:\s*\d+\s*$", re.I)),
    # divers
    ("moteur", re.compile(r"^(?:deobfuscated|decompiled|deobfuscat\w+)\s+(?:by|with|using)\b", re.I)),
    ("moteur", re.compile(r"^-+\s*$")),
]

_STATUT_SANDBOX = re.compile(r"Statut d'execution dans le bac a sable\s*:\s*(.*)", re.I)
_VERIF = re.compile(r"Verification\s*:\s*(.*)", re.I)
_CHIFFREES = re.compile(r"Chaines chiffrees\s*:\s*(\d+)\s*/\s*(\d+)", re.I)
_RUN_STATUS = re.compile(r"run status:\s*(.*)", re.I)
_MOONSEC_MODE = re.compile(r"^MoonSec V3 \[(decompile|desassemblage)\]", re.I)
_UPVAL = re.compile(r"\bupval_\d+\b")

# appels de dechiffrement restes dans le code : f("....", 1234567890123) -- une cle numerique d'au moins 9 chiffres
_RESIDUAL_ENC = re.compile(r'\b[\w.]+\(\s*"(?:[^"\\\n]|\\.){1,400}"\s*,\s*\d{9,}\s*\)')
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _is_banner(line: str) -> Optional[str]:
    s = line.strip()
    if not s.startswith("--"):
        return None
    body = s[2:]
    if body.startswith("["):             # commentaire long --[[ ... ]] : c'est du vrai commentaire, on ne le retire jamais
        return None
    inner = body.strip()
    raw = line.lstrip()[2:]              # indentation d'apres « -- » conservee (lignes de pile d'appels)
    for name, pat in _BANNER_RULES:
        if pat.search(raw if name.endswith("_raw") else inner):
            return name.replace("_raw", "")
    return None


def clean_output(text: str) -> tuple[str, dict]:
    """-> (texte nettoye, meta). meta : sandbox (statut), verification, decrypted/decrypt_total, trace (bool),
    reconstructed (bool), run_status, removed (nombre de lignes retirees)."""
    meta: dict = {"removed": 0, "trace": False, "reconstructed": False}
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CTRL.sub("", text)
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        kind = _is_banner(ln)
        if kind is None:
            break
        s = ln.strip()[2:].strip()
        if kind == "trace" and s.upper().startswith("TRACE"):
            meta["trace"] = True
        m = _STATUT_SANDBOX.search(s)
        if m:
            meta["sandbox"] = m.group(1).strip()
        m = _VERIF.search(s)
        if m and kind == "wearedevs":
            meta["verification"] = m.group(1).strip().rstrip(".")
        if s.startswith("Source RECONSTRUIT"):
            meta["reconstructed"] = True
        m = _CHIFFREES.search(s)
        if m:
            meta["decrypted"], meta["decrypt_total"] = int(m.group(1)), int(m.group(2))
        m = _RUN_STATUS.search(s)
        if m:
            meta["run_status"] = m.group(1).strip()
        m = _MOONSEC_MODE.search(s)
        if m:
            meta["moonsec"] = m.group(1).lower()
        meta["removed"] += 1
        i += 1
    out = "\n".join(l.rstrip() for l in lines[i:])
    out = re.sub(r"\n{4,}", "\n\n\n", out).lstrip("\n")
    if out and not out.endswith("\n"):
        out += "\n"
    return out, meta


def residual_encrypted(text: str) -> int:
    """Nombre d'appels de dechiffrement de chaines encore presents (f("...", cle)) : le texte n'est alors pas lisible."""
    return len(_RESIDUAL_ENC.findall(text[:3_000_000]))


@dataclass
class Verdict:
    status: str                       # SUCCESS | PARTIAL | FAILED
    label: str                        # court, pour l'embed
    reason: str = ""                  # une phrase
    kind: str = "source"              # source | trace | protected | unchanged
    details: list[str] = field(default_factory=list)


_LABEL = {SUCCESS: "Successful", PARTIAL: "Partial", FAILED: "Failed"}


def classify(res: dict, text: str, meta: Optional[dict] = None) -> Verdict:
    """Statut du resultat d'un moteur. `res` = dict du routeur (engine, ok, log, chain, protected...), `text` = sortie
    (deja nettoyee ou non), `meta` = retour de clean_output. Regle : au moindre doute sur la completude -> PARTIEL."""
    meta = meta or {}
    engine = str(res.get("engine") or "")
    log = str(res.get("log") or "")
    if res.get("protected"):
        return Verdict(FAILED, "Protégé", f"script protégé par {res['protected']} : clé / autorisation requise, code non récupérable",
                       kind="protected")
    if not res.get("ok") or not text.strip():
        return Verdict(FAILED, _LABEL[FAILED], _short_error(res), kind="source")

    details: list[str] = []
    # -- trace d'execution : ce que le script fait, PAS son source
    if meta.get("trace") or engine in ("trace", "moonsec_trace", "psu_trace") or "trace d'execution (code non reconstruit)" in log:
        sb = meta.get("sandbox")
        if sb and not sb.lower().startswith("finished"):
            details.append(f"arrêt dans le bac à sable : {sb[:90]}")
        return Verdict(PARTIAL, _LABEL[PARTIAL], "trace d'exécution : le code source n'a pas été reconstruit", kind="trace", details=details)

    # -- IronBrew 2 : bytecode reconstitue (genres de micro-operations) puis decompile : structure et noms a verifier
    if engine == "ironbrew2":
        n = len(_UPVAL.findall(text[:3_000_000]))
        why = "décompilation du bytecode IronBrew 2 : structure et noms approximatifs"
        if n:
            why += f" ({n} `upval_N` non résolu(s))"
        return Verdict(PARTIAL, _LABEL[PARTIAL], why, kind="source")

    # -- MoonSec V3 : bytecode devirtualise puis decompile (LuaDec). Complet mais approximatif : les upvalues ne sont pas
    #    resolues (`upval_N`, variables non declarees) -> PARTIEL ; un simple desassemblage n'est pas du code source.
    if meta.get("moonsec") == "desassemblage":
        return Verdict(PARTIAL, _LABEL[PARTIAL], "bytecode disassembly: decompilation failed", kind="source")
    if meta.get("moonsec") == "decompile" or engine == "moonsec_v3":
        n = len(_UPVAL.findall(text[:3_000_000]))
        if n:
            return Verdict(PARTIAL, _LABEL[PARTIAL], f"approximate decompilation: {n} unresolved `upval_N` reference(s)", kind="source")
        return Verdict(SUCCESS, _LABEL[SUCCESS], "", kind="source", details=["decompiled from the MoonSec bytecode"])

    # -- blocs non reconstruits (IronBrew / LuauForge)
    missing = text.count('error("devirt:')
    if missing:
        return Verdict(PARTIAL, _LABEL[PARTIAL], f"{missing} bloc(s) non reconstruit(s)", kind="source")
    if "machine virtuelle NON executee" in log:
        return Verdict(PARTIAL, _LABEL[PARTIAL], "couches retirées mais machine virtuelle non exécutée", kind="source")
    if re.search(r"partial=1|opcode map unresolved", log, re.I):
        return Verdict(PARTIAL, _LABEL[PARTIAL], "opcodes non résolus : décompilation incomplète", kind="source")
    rs = meta.get("run_status", "")
    if rs and not rs.lower().startswith("finished"):
        return Verdict(PARTIAL, _LABEL[PARTIAL], f"le script s'est arrêté dans le bac à sable ({rs[:80]})", kind="source")

    # -- releve WeAreDevs
    if meta.get("reconstructed"):
        n, tot = meta.get("decrypted"), meta.get("decrypt_total")
        left = residual_encrypted(text)
        if left:
            return Verdict(PARTIAL, _LABEL[PARTIAL], f"{left} chaîne(s) encore chiffrée(s) dans le code", kind="source")
        verif = (meta.get("verification") or "").lower()
        if "plantent" in verif:
            return Verdict(PARTIAL, _LABEL[PARTIAL], "le Lua reconstruit n'a pas pu être validé dans le bac à sable", kind="source")
        if verif.startswith("non verifie"):
            details.append("non vérifié dans le bac à sable")
        elif verif.startswith("verifie"):
            details.append("vérifié dans le bac à sable")
        return Verdict(SUCCESS, _LABEL[SUCCESS], "", kind="source", details=details)

    left = residual_encrypted(text)
    if left >= 3:
        return Verdict(PARTIAL, _LABEL[PARTIAL], f"{left} chaîne(s) encore chiffrée(s) dans le code", kind="source")
    return Verdict(SUCCESS, _LABEL[SUCCESS], "", kind="source", details=details)


def _short_error(res: dict) -> str:
    log = str(res.get("log") or "").strip()
    if not log:
        return "aucun résultat produit"
    last = [l for l in log.splitlines() if l.strip()][-1]
    last = re.sub(r"^\[[\w:. -]+\]\s*", "", last)
    return last[:160]
