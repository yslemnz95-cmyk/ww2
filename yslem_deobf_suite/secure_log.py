"""
secure_log.py -- masque les secrets avant qu'un texte n'atterrisse dans un journal, un message d'erreur ou un embed.
Module pur. mask(texte) remplace : jetons de bot Discord, jetons de webhook, cles d'API (Google, OpenAI, Anthropic), en-tetes
Authorization/Bearer, ainsi que les VALEURS des variables d'environnement sensibles (DISCORD_TOKEN, DEOBF_LLM_API_KEY...).
"""
from __future__ import annotations

import os
import re

# Une SEULE instance de ce module, qu'il soit importe sous « secure_log » (cogs de la suite) ou sous « yslem_deobf_suite.secure_log »
# (bot.py) : sinon deux copies gardent chacune leur etat en memoire et s'ecrasent mutuellement dans le fichier.
import sys as _sys
for _alias in ("secure_log", "yslem_deobf_suite.secure_log"):
    _sys.modules.setdefault(_alias, _sys.modules[__name__])

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b[MNO][A-Za-z\d_-]{23,27}\.[\w-]{6}\.[\w-]{27,}\b"), "«jeton-discord»"),
    (re.compile(r"(https?://(?:[\w-]+\.)?discord(?:app)?\.com/api/(?:v\d+/)?webhooks/\d+/)[\w-]+", re.I), r"\1«masque»"),
    (re.compile(r"\bAIza[\w-]{30,}\b"), "«cle-api»"),
    (re.compile(r"\bsk-(?:ant-)?[\w-]{20,}\b"), "«cle-api»"),
    (re.compile(r"\bAQ\.[\w-]{30,}\b"), "«cle-api»"),
    (re.compile(r"(?i)\b(authorization|bearer|x-api-key|api[_-]?key|token|secret|password|mot[_ ]de[_ ]passe)(\s*[:=]\s*|\s+)(?!«)[^\s\"',;]{8,}"), r"\1\2«masque»"),
]

_SENSITIVE_ENV = ("DISCORD_TOKEN", "BOT_TOKEN", "TOKEN", "DEOBF_LLM_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def _secret_values() -> list[str]:
    vals = []
    for k in _SENSITIVE_ENV:
        v = os.environ.get(k, "").strip()
        if len(v) >= 8:
            vals.append(v)
    return vals


def mask(text: object) -> str:
    s = text if isinstance(text, str) else str(text)
    for v in _secret_values():
        if v in s:
            s = s.replace(v, "«masque»")
    for pat, rep in _PATTERNS:
        s = pat.sub(rep, s)
    return s
