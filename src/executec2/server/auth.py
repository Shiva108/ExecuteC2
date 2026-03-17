"""Authentication: JWT management, OTP store, rate limiting."""

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import jwt

from executec2.server.models import OTPEntry, OTPType, TokenClaims

_ALGORITHM = "HS256"


class JWTManager:
    """Issue and verify HMAC-SHA256 JWTs."""

    def __init__(self, access_ttl_hours: int = 24, refresh_ttl_hours: int = 168):
        self._secret = secrets.token_bytes(32)
        self._access_ttl = timedelta(hours=access_ttl_hours)
        self._refresh_ttl = timedelta(hours=refresh_ttl_hours)

    def create_access_token(self, username: str) -> str:
        now = datetime.now(UTC)
        payload = {
            "username": username,
            "token_type": "access",
            "iat": now,
            "exp": now + self._access_ttl,
        }
        return jwt.encode(payload, self._secret, algorithm=_ALGORITHM)

    def create_refresh_token(self, username: str) -> str:
        now = datetime.now(UTC)
        payload = {
            "username": username,
            "token_type": "refresh",
            "iat": now,
            "exp": now + self._refresh_ttl,
        }
        return jwt.encode(payload, self._secret, algorithm=_ALGORITHM)

    def verify_token(self, token: str, expected_type: str = "access") -> TokenClaims:
        """Verify token and return claims. Raises jwt.PyJWTError on failure."""
        payload = jwt.decode(token, self._secret, algorithms=[_ALGORITHM])
        if payload.get("token_type") != expected_type:
            raise jwt.InvalidTokenError(f"Expected token_type={expected_type!r}")
        return TokenClaims(
            username=payload["username"],
            exp=datetime.fromtimestamp(payload["exp"], UTC),
            iat=datetime.fromtimestamp(payload["iat"], UTC),
            token_type=payload["token_type"],
        )

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def verify_password(username: str, password: str, operators: dict[str, str]) -> bool:
        """Compare SHA256(plaintext) vs stored plaintext (hashed at compare time)."""
        stored = operators.get(username)
        if stored is None:
            return False
        return hashlib.sha256(password.encode()).hexdigest() == hashlib.sha256(stored.encode()).hexdigest()


class OTPStore:
    """Single-use, time-limited one-time passwords."""

    TTL_SECONDS = 60

    def __init__(self):
        self._store: dict[str, OTPEntry] = {}

    def generate(self, username: str, otp_type: OTPType) -> str:
        otp = secrets.token_hex(16)
        self._store[otp] = OTPEntry(otp=otp, otp_type=otp_type, username=username)
        return otp

    def validate(self, otp: str, expected_type: OTPType | None = None) -> OTPEntry | None:
        """Return and consume OTP entry if valid; None otherwise."""
        self._evict_expired()
        entry = self._store.pop(otp, None)
        if entry is None:
            return None
        if expected_type is not None and entry.otp_type != expected_type:
            return None
        return entry

    def _evict_expired(self) -> None:
        now = datetime.now(UTC)
        expired = [
            k for k, v in self._store.items()
            if (now - v.created).total_seconds() > self.TTL_SECONDS
        ]
        for k in expired:
            del self._store[k]


class RateLimiter:
    """Sliding-window per-IP rate limiter."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._history: dict[str, deque] = defaultdict(deque)

    def is_allowed(self, ip: str) -> bool:
        now = time.monotonic()
        window_start = now - self._window
        dq = self._history[ip]
        while dq and dq[0] < window_start:
            dq.popleft()
        if len(dq) >= self._max:
            return False
        dq.append(now)
        return True
