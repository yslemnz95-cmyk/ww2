"""
stats_store.py -- statistiques d'utilisation du bot (module pur). Persistant : <suite>/data/stats.json (DEOBF_DATA_DIR).

  record(kind, user_id, name, status, engine, elapsed)   kind : analyse | deobf | get
  snapshot()                                             totaux, temps moyen, utilisateurs, dernieres operations

Ecriture au plus toutes les 3 s (puis a l'arret via flush()) pour ne pas user le disque ; ecriture atomique.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

from settings_store import data_dir

# Une SEULE instance de ce module, qu'il soit importe sous « stats_store » (cogs de la suite) ou sous « yslem_deobf_suite.stats_store »
# (bot.py) : sinon deux copies gardent chacune leur etat en memoire et s'ecrasent mutuellement dans le fichier.
import sys as _sys
for _alias in ("stats_store", "yslem_deobf_suite.stats_store"):
    _sys.modules.setdefault(_alias, _sys.modules[__name__])

HISTORY_MAX = 50
FLUSH_EVERY = 3.0
STATUSES = ("success", "partial", "failed", "cancelled", "info")


class StatsStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else data_dir() / "stats.json"
        self._lock = threading.RLock()
        self._last_write = 0.0
        self._dirty = False
        self.d: dict = {"analyses": 0, "deobf": 0, "gets": 0, "success": 0, "partial": 0, "failed": 0, "cancelled": 0,
                        "elapsed_sum": 0.0, "elapsed_n": 0, "users": [], "since": time.time(), "history": []}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in self.d:
                    if k in data and type(data[k]) is type(self.d[k]):
                        self.d[k] = data[k]
        except (OSError, ValueError):
            pass
        self.d["history"] = self.d["history"][-HISTORY_MAX:]

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(self.d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        self._last_write, self._dirty = time.monotonic(), False

    def flush(self) -> None:
        with self._lock:
            if self._dirty:
                try:
                    self._write()
                except OSError:
                    pass

    def record(self, kind: str, user_id: int, name: str, status: str, engine: Optional[str] = None, elapsed: float = 0.0) -> None:
        with self._lock:
            d = self.d
            if kind == "analyse":
                d["analyses"] += 1
            elif kind == "get":
                d["gets"] += 1
            if kind == "deobf":
                d["deobf"] += 1
                if status in ("success", "partial", "failed", "cancelled"):
                    d[status] += 1
                if status in ("success", "partial", "failed") and elapsed:
                    d["elapsed_sum"] += float(elapsed)
                    d["elapsed_n"] += 1
            uid = int(user_id or 0)
            if uid and uid not in d["users"]:
                d["users"].append(uid)
            d["history"].append({"t": int(time.time()), "kind": kind, "user": uid, "name": str(name)[:60],
                                 "status": status if status in STATUSES else "info", "engine": engine or "", "elapsed": round(float(elapsed), 1)})
            del d["history"][:-HISTORY_MAX]
            self._dirty = True
            if time.monotonic() - self._last_write >= FLUSH_EVERY:
                try:
                    self._write()
                except OSError:
                    pass

    def snapshot(self) -> dict:
        with self._lock:
            d = self.d
            n = d["elapsed_n"]
            return {"analyses": d["analyses"], "deobf": d["deobf"], "gets": d["gets"], "success": d["success"], "partial": d["partial"],
                    "failed": d["failed"], "cancelled": d["cancelled"], "avg_elapsed": (d["elapsed_sum"] / n) if n else 0.0,
                    "users": len(d["users"]), "since": d["since"], "history": list(d["history"])[::-1]}


_STATS: Optional[StatsStore] = None


def stats() -> StatsStore:
    global _STATS
    if _STATS is None:
        _STATS = StatsStore()
    return _STATS


def reset_stats_for_tests(path: Optional[Path] = None) -> StatsStore:
    global _STATS
    _STATS = StatsStore(path)
    return _STATS
