"""
settings_store.py -- reglages persistants du bot (prefixes par serveur, options par serveur). Module pur (pas de Discord).

Fichier JSON : <suite>/data/settings.json (dossier modifiable : DEOBF_DATA_DIR). Ecriture atomique (fichier temporaire puis
os.replace) : un arret brutal ne laisse jamais un fichier a moitie ecrit ; un fichier illisible est mis de cote
(settings.json.corrupt) et le bot repart avec les valeurs par defaut au lieu de planter.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

# Une SEULE instance de ce module, qu'il soit importe sous « settings_store » (cogs de la suite) ou sous « yslem_deobf_suite.settings_store »
# (bot.py) : sinon deux copies gardent chacune leur etat en memoire et s'ecrasent mutuellement dans le fichier.
import sys as _sys
for _alias in ("settings_store", "yslem_deobf_suite.settings_store"):
    _sys.modules.setdefault(_alias, _sys.modules[__name__])

HERE = Path(__file__).resolve().parent
MAX_PREFIXES = 8
MAX_PREFIX_LEN = 5
SCHEMA = 1

# options par serveur et valeur par defaut
DEFAULT_OPTIONS = {
    "private_panels": True,     # les panneaux /panel ne sont visibles que par celui qui les ouvre
    "mention_result": True,     # mentionner l'utilisateur quand son resultat est livre
}


def data_dir() -> Path:
    d = Path(os.environ.get("DEOBF_DATA_DIR") or (HERE / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate_prefix(p: str) -> tuple[bool, str]:
    """(ok, raison). Un prefixe : 1 a 5 caracteres, sans espace, sans caractere de controle ni de mention."""
    if not isinstance(p, str) or not p:
        return False, "préfixe vide"
    if p != p.strip() or any(c.isspace() for c in p):
        return False, "pas d'espace dans un préfixe"
    if len(p) > MAX_PREFIX_LEN:
        return False, f"{MAX_PREFIX_LEN} caractères maximum"
    if any(ord(c) < 32 or ord(c) == 127 for c in p):
        return False, "caractère de contrôle interdit"
    if any(c in p for c in "@#<>\\`*_~|"):
        return False, "caractère interdit (@ # < > \\ ` * _ ~ |)"
    if p.startswith("/"):
        return False, "« / » est réservé aux commandes slash"
    return True, ""


class SettingsStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else data_dir() / "settings.json"
        self._lock = threading.RLock()
        self._data: dict = {"schema": SCHEMA, "guilds": {}}
        self._load()

    # ── persistance ───────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            return
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get("guilds", {}), dict):
                raise ValueError("structure inattendue")
            data.setdefault("schema", SCHEMA)
            data.setdefault("guilds", {})
            self._data = data
        except ValueError:
            try:
                self.path.replace(self.path.with_name(self.path.name + ".corrupt"))
            except OSError:
                pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def _guild(self, gid: int, create: bool = False) -> dict:
        g = self._data["guilds"].get(str(gid))
        if g is None and create:
            g = self._data["guilds"][str(gid)] = {}
        return g if g is not None else {}

    # ── prefixes ──────────────────────────────────────────────────────────────
    def prefixes(self, gid: Optional[int]) -> Optional[list[str]]:
        """Prefixes definis pour ce serveur, ou None (= prefixes par defaut du bot)."""
        if gid is None:
            return None
        with self._lock:
            p = self._guild(gid).get("prefixes")
            return list(p) if p else None

    def set_prefixes(self, gid: int, prefixes: list[str]) -> list[str]:
        clean: list[str] = []
        for p in prefixes:
            ok, why = validate_prefix(p)
            if not ok:
                raise ValueError(f"préfixe {p!r} refusé : {why}")
            if p in clean:
                raise ValueError(f"préfixe {p!r} en double")
            clean.append(p)
        if not clean:
            raise ValueError("au moins un préfixe est nécessaire (ou « réinitialiser »)")
        if len(clean) > MAX_PREFIXES:
            raise ValueError(f"{MAX_PREFIXES} préfixes maximum")
        with self._lock:
            self._guild(gid, True)["prefixes"] = clean
            self._save()
        return clean

    def add_prefix(self, gid: int, p: str, current_default: Optional[list[str]] = None) -> list[str]:
        ok, why = validate_prefix(p)
        if not ok:
            raise ValueError(f"préfixe {p!r} refusé : {why}")
        with self._lock:
            cur = self.prefixes(gid) or list(current_default or [])
            if p in cur:
                raise ValueError(f"le préfixe {p!r} existe déjà")
            return self.set_prefixes(gid, cur + [p])

    def remove_prefix(self, gid: int, p: str) -> list[str]:
        with self._lock:
            cur = self.prefixes(gid)
            if cur is None or p not in cur:
                raise ValueError(f"le préfixe {p!r} n'est pas défini pour ce serveur")
            if len(cur) == 1:
                raise ValueError("c'est le dernier préfixe : utilise « réinitialiser » pour revenir aux préfixes par défaut")
            return self.set_prefixes(gid, [x for x in cur if x != p])

    def edit_prefix(self, gid: int, old: str, new: str) -> list[str]:
        with self._lock:
            cur = self.prefixes(gid)
            if cur is None or old not in cur:
                raise ValueError(f"le préfixe {old!r} n'est pas défini pour ce serveur")
            if new != old and new in cur:
                raise ValueError(f"le préfixe {new!r} existe déjà")
            return self.set_prefixes(gid, [new if x == old else x for x in cur])

    def reset_prefixes(self, gid: int) -> None:
        with self._lock:
            g = self._guild(gid)
            if "prefixes" in g:
                del g["prefixes"]
                self._save()

    # ── options ───────────────────────────────────────────────────────────────
    def option(self, gid: Optional[int], key: str) -> bool:
        if key not in DEFAULT_OPTIONS:
            raise KeyError(key)
        if gid is None:
            return DEFAULT_OPTIONS[key]
        with self._lock:
            return bool(self._guild(gid).get("options", {}).get(key, DEFAULT_OPTIONS[key]))

    def set_option(self, gid: int, key: str, value: bool) -> None:
        if key not in DEFAULT_OPTIONS:
            raise KeyError(key)
        with self._lock:
            self._guild(gid, True).setdefault("options", {})[key] = bool(value)
            self._save()

    def deobf_channel(self, gid: Optional[int]) -> Optional[int]:
        """Salon reserve aux commandes de deobfuscation (None = pas de restriction)."""
        if gid is None:
            return None
        with self._lock:
            c = self._guild(gid).get("deobf_channel")
            return int(c) if c else None

    def set_deobf_channel(self, gid: int, channel_id: Optional[int]) -> None:
        with self._lock:
            g = self._guild(gid, True)
            if channel_id is None:
                g.pop("deobf_channel", None)
            else:
                g["deobf_channel"] = int(channel_id)
            self._save()

    def deobf_roles(self, gid: Optional[int]) -> list[int]:
        """Roles Discord (IDs) autorises a utiliser les commandes de deobfuscation sur ce serveur."""
        if gid is None:
            return []
        with self._lock:
            return [int(r) for r in self._guild(gid).get("deobf_roles", [])]

    def add_deobf_role(self, gid: int, role_id: int) -> list[int]:
        with self._lock:
            g = self._guild(gid, True)
            roles = [int(r) for r in g.get("deobf_roles", [])]
            if int(role_id) not in roles:
                roles.append(int(role_id))
            g["deobf_roles"] = roles
            self._save()
            return roles

    def remove_deobf_role(self, gid: int, role_id: int) -> list[int]:
        with self._lock:
            g = self._guild(gid, True)
            roles = [int(r) for r in g.get("deobf_roles", []) if int(r) != int(role_id)]
            g["deobf_roles"] = roles
            self._save()
            return roles

    def reset_options(self, gid: int) -> None:
        with self._lock:
            g = self._guild(gid)
            if "options" in g:
                del g["options"]
                self._save()


_STORE: Optional[SettingsStore] = None


def store() -> SettingsStore:
    """Instance partagee (creee a la demande)."""
    global _STORE
    if _STORE is None:
        _STORE = SettingsStore()
    return _STORE


def reset_store_for_tests(path: Optional[Path] = None) -> SettingsStore:
    global _STORE
    _STORE = SettingsStore(path)
    return _STORE
