"""Password hashing (Argon2id via argon2-cffi), opaque session tokens, and login throttling."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
# Verified against when the email is unknown so response timing does not reveal accounts.
_DUMMY_HASH = _hasher.hash("marketops-timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def derive_csrf_token(session_token: str) -> str:
    """CSRF token bound to the session token (one-way), stable for the session's lifetime.

    Readers of the CSRF token cannot recover the HttpOnly session token, and cross-site pages
    cannot compute it without that token. The server stores only its SHA-256 digest.
    """
    return hashlib.sha256(f"marketops-csrf:{session_token}".encode()).hexdigest()


def digest_matches(token: str, digest: str) -> bool:
    return hmac.compare_digest(token_digest(token), digest)


class LoginThrottle:
    """In-process sliding-window limiter keyed by (email, client address).

    Single-worker limitation (ADR 0002): counters are per process and reset on restart.
    """

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def retry_after(self, key: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        q = self._prune(key, now)
        if len(q) < self.max_failures:
            return 0
        return max(1, int(self.window - (now - q[0])))

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
