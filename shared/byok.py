"""Bring-your-own-key: a visitor's Gemini key, scoped to one request.

The key arrives in the `X-Gemini-Key` header, lives in a context variable for
the duration of that request (chat model reads it), and
is never written to the database, the logs or the decision feed.
"""
from __future__ import annotations

import contextvars
import re
from collections.abc import Iterator
from contextlib import contextmanager

_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("gemini_key_override", default=None)
_server_disabled: contextvars.ContextVar[bool] = contextvars.ContextVar("disable_server_gemini_key", default=False)

# Google AI Studio keys look like "AIza" + 35 url-safe characters. Accept a
# slightly wider shape so a future format does not break the feature.
KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{30,64}$")


def valid(key: str | None) -> bool:
    return bool(key and KEY_RE.match(key))


def current() -> str | None:
    """The visitor's key for this request, or None (use the server's key)."""
    return _key.get()


def server_key_allowed() -> bool:
    """Whether server-side GEMINI_API_KEY may be spent in this context."""
    return not _server_disabled.get()


@contextmanager
def use(key: str | None) -> Iterator[None]:
    token = _key.set(key if valid(key) else None)
    try:
        yield
    finally:
        _key.reset(token)


@contextmanager
def disable_server_key() -> Iterator[None]:
    """Prevent spending the server's GEMINI_API_KEY inside this block."""
    token = _server_disabled.set(True)
    try:
        yield
    finally:
        _server_disabled.reset(token)
