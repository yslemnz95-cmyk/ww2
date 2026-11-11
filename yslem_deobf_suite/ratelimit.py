"""
ratelimit.py -- protection contre l'abus de commandes : fenetre glissante par utilisateur (module pur).

    guard = SpamGuard()
    ok, retry = guard.check(user_id, privileged=False)   # ok False => trop de commandes, retry = secondes a attendre
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

# Une SEULE instance de ce module, qu'il soit importe sous « ratelimit » (cogs de la suite) ou sous « yslem_deobf_suite.ratelimit »
# (bot.py) : sinon deux copies gardent chacune leur etat en memoire et s'ecrasent mutuellement dans le fichier.
import sys as _sys
for _alias in ("ratelimit", "yslem_deobf_suite.ratelimit"):
    _sys.modules.setdefault(_alias, _sys.modules[__name__])


class SpamGuard:
    def __init__(self, limit: int = 6, per: float = 30.0, privileged_limit: int = 30) -> None:
        self.limit, self.per, self.privileged_limit = limit, per, privileged_limit
        self._hits: dict[int, deque] = defaultdict(deque)

    def check(self, user_id: int, privileged: bool = False, now: float | None = None) -> tuple[bool, float]:
        now = time.monotonic() if now is None else now
        q = self._hits[user_id]
        while q and now - q[0] > self.per:
            q.popleft()
        cap = self.privileged_limit if privileged else self.limit
        if len(q) >= cap:
            return False, max(0.1, self.per - (now - q[0]))
        q.append(now)
        if len(self._hits) > 5000:                      # pas de fuite memoire : on oublie les utilisateurs inactifs
            for uid in [u for u, h in self._hits.items() if not h or now - h[-1] > self.per][:2000]:
                self._hits.pop(uid, None)
        return True, 0.0
