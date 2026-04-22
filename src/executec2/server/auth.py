"""Authentication and authorization helpers for ExecuteC2."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, status

from executec2.server.models import OTPEntry, OTPType, TokenClaims

_ALGORITHM = "HS256"

ROLE_VIEWER = "viewer"
ROLE_OPERATOR = "operator"
ROLE_ADMIN = "admin"

PROTECTED_COMMANDS = {"upload", "exit"}


class JWTManager:
    """Issue and verify HMAC-SHA256 JWTs."""

    def __init__(self, secret: bytes, access_ttl_hours: int = 24, refresh_ttl_hours: int = 168):
        self._secret = secret
        self._access_ttl = timedelta(hours=access_ttl_hours)
        self._refresh_ttl = timedelta(hours=refresh_ttl_hours)

    def create_access_token(self, username: str, roles: list[str]) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": username,
            "username": username,
            "roles": roles,
            "token_type": "access",
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + self._access_ttl,
        }
        return jwt.encode(payload, self._secret, algorithm=_ALGORITHM)

    def create_refresh_token(self, username: str, roles: list[str]) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": username,
            "username": username,
            "roles": roles,
            "token_type": "refresh",
            "jti": uuid.uuid4().hex,
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
            sub=payload.get("sub", payload["username"]),
            username=payload["username"],
            roles=list(payload.get("roles", [])),
            jti=payload.get("jti", ""),
            exp=datetime.fromtimestamp(payload["exp"], UTC),
            iat=datetime.fromtimestamp(payload["iat"], UTC),
            token_type=payload["token_type"],
        )

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def verify_password(username: str, password: str, operators: dict[str, dict[str, object]]) -> bool:
        """Compare SHA256(plaintext) vs configured plaintext in constant time."""
        entry = operators.get(username)
        if not entry:
            return False
        stored_password = str(entry.get("password", ""))
        lhs = hashlib.sha256(password.encode()).hexdigest()
        rhs = hashlib.sha256(stored_password.encode()).hexdigest()
        return secrets.compare_digest(lhs, rhs)


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
    """Sliding-window per-key rate limiter."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._history: dict[str, deque] = defaultdict(deque)

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self._window
        dq = self._history[key]
        while dq and dq[0] < window_start:
            dq.popleft()
        if len(dq) >= self._max:
            return False
        dq.append(now)
        return True


def has_any_role(claims: TokenClaims, allowed_roles: set[str]) -> bool:
    return any(role in allowed_roles for role in claims.roles)


def require_user(request: Request) -> TokenClaims:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer", "X-Code": "UNAUTHORIZED"},
        )
    token = auth.removeprefix("Bearer ")
    jwt_manager: JWTManager = request.app.state.jwt_manager
    try:
        claims = jwt_manager.verify_token(token, expected_type="access")
        return claims
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer", "X-Code": "UNAUTHORIZED"},
        )


def require_roles(*required_roles: str):
    required = set(required_roles)

    def _dep(claims: TokenClaims = Depends(require_user)) -> TokenClaims:
        if not has_any_role(claims, required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
                headers={"X-Code": "FORBIDDEN"},
            )
        return claims

    return _dep


def require_command_permission(command_name: str, claims: TokenClaims) -> None:
    if command_name in PROTECTED_COMMANDS and ROLE_ADMIN not in claims.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Command '{command_name}' requires admin role",
            headers={"X-Code": "FORBIDDEN"},
        )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_key_user_ip(request: Request, username: str) -> str:
    return f"{username}:{client_ip(request)}"


def enforce_limit(request: Request, limiter_name: str, key: str, detail: str = "Rate limit exceeded") -> None:
    limiter: RateLimiter = request.app.state.route_limiters[limiter_name]
    if not limiter.is_allowed(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"X-Code": "RATE_LIMITED"},
        )
