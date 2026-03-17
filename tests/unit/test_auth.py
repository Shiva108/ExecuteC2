"""Unit tests for JWT, OTP, and rate limiting."""

import time

import jwt as pyjwt
import pytest

from executec2.server.auth import JWTManager, OTPStore, RateLimiter
from executec2.server.models import OTPType

# ---------------------------------------------------------------------------
# JWTManager
# ---------------------------------------------------------------------------


def test_create_and_verify_access_token():
    mgr = JWTManager()
    token = mgr.create_access_token("alice")
    claims = mgr.verify_token(token, expected_type="access")
    assert claims.username == "alice"
    assert claims.token_type == "access"


def test_create_and_verify_refresh_token():
    mgr = JWTManager()
    token = mgr.create_refresh_token("bob")
    claims = mgr.verify_token(token, expected_type="refresh")
    assert claims.username == "bob"
    assert claims.token_type == "refresh"


def test_verify_wrong_type_raises():
    mgr = JWTManager()
    access = mgr.create_access_token("alice")
    with pytest.raises(pyjwt.PyJWTError):
        mgr.verify_token(access, expected_type="refresh")


def test_verify_invalid_token_raises():
    mgr = JWTManager()
    with pytest.raises(pyjwt.PyJWTError):
        mgr.verify_token("not.a.token")


def test_verify_tampered_token_raises():
    mgr = JWTManager()
    token = mgr.create_access_token("alice")
    tampered = token[:-4] + "xxxx"
    with pytest.raises(pyjwt.PyJWTError):
        mgr.verify_token(tampered)


def test_verify_password_correct():
    mgr = JWTManager()
    operators = {"admin": "secret123"}
    assert mgr.verify_password("admin", "secret123", operators) is True


def test_verify_password_wrong():
    mgr = JWTManager()
    operators = {"admin": "secret123"}
    assert mgr.verify_password("admin", "wrong", operators) is False


def test_verify_password_unknown_user():
    mgr = JWTManager()
    operators = {"admin": "secret123"}
    assert mgr.verify_password("nobody", "secret123", operators) is False


# ---------------------------------------------------------------------------
# OTPStore
# ---------------------------------------------------------------------------


def test_otp_generate_and_validate():
    store = OTPStore()
    otp = store.generate("alice", OTPType.CONNECT)
    entry = store.validate(otp)
    assert entry is not None
    assert entry.username == "alice"
    assert entry.otp_type == OTPType.CONNECT


def test_otp_single_use():
    store = OTPStore()
    otp = store.generate("alice", OTPType.CONNECT)
    store.validate(otp)
    assert store.validate(otp) is None


def test_otp_wrong_type_rejected():
    store = OTPStore()
    otp = store.generate("alice", OTPType.CONNECT)
    assert store.validate(otp, expected_type=OTPType.TUNNEL) is None


def test_otp_unknown_rejected():
    store = OTPStore()
    assert store.validate("nonexistent") is None


def test_otp_expiry(monkeypatch):
    """Expired OTPs are evicted during next validate call."""
    store = OTPStore()
    otp = store.generate("alice", OTPType.CONNECT)
    # Backdate the creation time
    from datetime import UTC, datetime, timedelta
    store._store[otp].created = datetime.now(UTC) - timedelta(seconds=61)
    assert store.validate(otp) is None


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


def test_rate_limiter_allows_within_limit():
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    for _ in range(5):
        assert limiter.is_allowed("1.2.3.4") is True


def test_rate_limiter_blocks_over_limit():
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.is_allowed("1.2.3.4")
    assert limiter.is_allowed("1.2.3.4") is False


def test_rate_limiter_different_ips_independent():
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    assert limiter.is_allowed("10.0.0.1") is True
    assert limiter.is_allowed("10.0.0.2") is True
    assert limiter.is_allowed("10.0.0.1") is False


def test_rate_limiter_window_slides(monkeypatch):
    limiter = RateLimiter(max_requests=2, window_seconds=1)
    limiter.is_allowed("1.2.3.4")
    limiter.is_allowed("1.2.3.4")
    assert limiter.is_allowed("1.2.3.4") is False
    # Sleep just over the window
    time.sleep(1.1)
    assert limiter.is_allowed("1.2.3.4") is True
