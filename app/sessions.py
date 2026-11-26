"""Signed cookie sessions (demo-grade, no passwords).

Two cookies:
  session  {customer_id, session_id, role, vid}, issued at sign-in. The role
           lives here, so no message can change it.
  kp_vid   a random visitor id for this browser. It survives profile switches,
           so the free-request budget, uploads and the live feed belong to the
           visitor, not to one sign-in.
"""
from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer

from app.settings import SETTINGS

_serializer = URLSafeSerializer(SETTINGS.session_secret, salt="session")
_visitor = URLSafeSerializer(SETTINGS.session_secret, salt="visitor")


def make_cookie(customer_id: int, session_id: str, role: str = "user", vid: str | None = None) -> str:
    return _serializer.dumps({"customer_id": customer_id, "session_id": session_id, "role": role,
                              "vid": vid or session_id})


def read_cookie(value: str) -> dict | None:
    try:
        return _serializer.loads(value)
    except BadSignature:
        return None


def make_visitor(vid: str) -> str:
    return _visitor.dumps(vid)


def read_visitor(value: str | None) -> str | None:
    if not value:
        return None
    try:
        v = _visitor.loads(value)
        return v if isinstance(v, str) else None
    except BadSignature:
        return None
