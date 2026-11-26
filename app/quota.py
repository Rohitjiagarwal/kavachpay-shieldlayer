"""Free-request budget for the public demo.

Counts model-backed requests (chat messages and uploads) per visitor, per
network address and per day. A request is allowed only while all three have
room. Visitors who attach their own Gemini key are not counted.

Kept in memory on purpose: the hosted demo is a single process, and a restart
also resets the demo data. The provider-side quota on the Gemini key is the
hard ceiling; this module makes sure one visitor cannot spend it all.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class Status:
    limit: int
    used: int
    remaining: int
    reason: str = ""  # why remaining is 0: visitor | network | daily


class Quota:
    def __init__(self, per_visitor: int, per_ip: int, per_day: int):
        self.per_visitor = per_visitor
        self.per_ip = per_ip
        self.per_day = per_day
        self._lock = threading.Lock()
        self._visitor: dict[str, int] = {}
        self._ip: dict[str, int] = {}
        self._day = ("", 0)
        self._hits: dict[str, deque] = {}

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def _day_used(self) -> int:
        day, n = self._day
        return n if day == self._today() else 0

    def _status(self, visitor: str, ip: str) -> Status:
        v = self._visitor.get(visitor, 0)
        room = {
            "visitor": self.per_visitor - v,
            "network": self.per_ip - self._ip.get(ip, 0),
            "daily": self.per_day - self._day_used(),
        }
        reason = min(room, key=lambda k: room[k])
        remaining = max(0, room[reason])
        return Status(limit=self.per_visitor, used=v, remaining=remaining,
                      reason=reason if remaining == 0 else "")

    def status(self, visitor: str, ip: str) -> Status:
        with self._lock:
            return self._status(visitor, ip)

    def spend(self, visitor: str, ip: str) -> Status:
        """Use one request if there is room. Returns the status *after* the
        attempt; `remaining` is -1 when the request was refused."""
        with self._lock:
            st = self._status(visitor, ip)
            if st.remaining <= 0:
                return Status(st.limit, st.used, -1, st.reason)
            self._visitor[visitor] = self._visitor.get(visitor, 0) + 1
            self._ip[ip] = self._ip.get(ip, 0) + 1
            self._day = (self._today(), self._day_used() + 1)
            return self._status(visitor, ip)

    def throttle(self, key: str, limit: int, per_s: float) -> bool:
        """Sliding-window rate limit for free, CPU-only endpoints. True = allowed."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > per_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True
