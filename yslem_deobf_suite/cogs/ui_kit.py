"""
ui_kit.py -- identite visuelle du bot : embeds courts, couleur et icone selon le statut, barre de progression.
Aucune logique metier ici : uniquement de la presentation (discord.Embed).
"""
from __future__ import annotations

from typing import Optional

import discord

COLORS = {"running": 0xB22222, "success": 0x8B0000, "partial": 0xCD5C5C, "failed": 0xFF0000,
          "cancelled": 0x4A0404, "info": 0xDC143C}
ICONS = {"running": "⏳", "success": "✅", "partial": "⚠️", "failed": "❌", "cancelled": "⛔", "info": "🔎"}
TITLES = {"running": "Running", "success": "Deobfuscation successful", "partial": "Deobfuscation finished",
          "failed": "Failed", "cancelled": "Cancelled", "info": "Analysis"}


def fmt_duration(sec: float) -> str:
    sec = max(0, int(round(sec)))
    if sec < 60:
        return f"{sec} s"
    m, s = divmod(sec, 60)
    return f"{m} min {s:02d} s" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def progress_bar(frac: float, width: int = 10) -> str:
    frac = min(1.0, max(0.0, frac))
    n = int(round(frac * width))
    return "▓" * n + "░" * (width - n)


def embed(status: str, title: Optional[str] = None, description: Optional[str] = None) -> discord.Embed:
    st = status if status in COLORS else "info"
    return discord.Embed(title=f"{ICONS[st]} {title or TITLES[st]}"[:250], description=(description or None), color=COLORS[st])


def result_embed(name: str, status: str, reason: str = "", engine: str = "", obfuscator: str = "", elapsed: float = 0.0,
                 cached: bool = False, details: Optional[list[str]] = None) -> discord.Embed:
    """Resultat d'une deobfuscation : statut en titre, fichier, protection detectee, moteur, duree. Rien d'autre."""
    e = embed(status)
    e.add_field(name="File", value=f"`{name[:60]}`", inline=True)
    if obfuscator:
        e.add_field(name="Protection", value=obfuscator[:60], inline=True)
    if engine:
        e.add_field(name="Engine", value=f"`{engine[:40]}`", inline=True)
    e.add_field(name="Duration", value=("⚡ cache" if cached else fmt_duration(elapsed)), inline=True)
    note = reason
    if details:
        note = (note + " · " if note else "") + " · ".join(details)
    if note:
        e.add_field(name="Status", value=note[:300], inline=False)
    return e


def analysis_embed(name: str, size: int, language: str, protection: str, verdict: str, status: str = "info",
                   links: int = 0, note: str = "", elapsed: float = 0.0) -> discord.Embed:
    e = embed(status, f"{name[:80]}", None)
    e.add_field(name="Language", value={"lua": "Lua", "luau": "Luau", "json": "JSON", "html": "HTML", "zip": "ZIP", "binary": "binary",
                                       "text": "text", "empty": "empty"}.get(language, language), inline=True)
    e.add_field(name="Size", value=f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B", inline=True)
    e.add_field(name="Protection", value=protection[:60] or "—", inline=True)
    e.add_field(name="Status", value=verdict[:300], inline=False)
    if links:
        e.add_field(name="External links", value=str(links), inline=True)
    if note:
        e.add_field(name="Note", value=note[:300], inline=False)
    if elapsed:
        e.set_footer(text=f"analysed in {fmt_duration(elapsed)}")
    return e
