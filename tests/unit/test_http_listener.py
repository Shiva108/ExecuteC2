"""Unit tests for HTTPListener plugin."""

import base64
import os
from unittest.mock import AsyncMock

import msgpack
import pytest

from executec2.listeners.http_listener import HTTPListener, _aes_decrypt, _aes_encrypt, _hkdf_derive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_master_key() -> bytes:
    return os.urandom(32)


def make_beat_header(master_key: bytes, agent_type: str, agent_id: str, beat_data: dict) -> str:
    beat_key = _hkdf_derive(master_key, b"beat", b"beat-encryption")
    agent_type_bytes = agent_type.encode()
    agent_id_bytes = agent_id.encode()
    payload = (
        len(agent_type_bytes).to_bytes(4, "big")
        + agent_type_bytes
        + agent_id_bytes
        + msgpack.packb(beat_data)
    )
    encrypted = _aes_encrypt(beat_key, payload)
    return base64.b64encode(encrypted).decode()


def make_raw_http_request(
    path: str,
    beat_header_name: str,
    beat_header_value: str,
    extra_headers: dict | None = None,
) -> bytes:
    headers = f"POST {path} HTTP/1.1\r\nHost: example.com\r\n"
    headers += f"{beat_header_name}: {beat_header_value}\r\n"
    if extra_headers:
        for k, v in extra_headers.items():
            headers += f"{k}: {v}\r\n"
    headers += "\r\n"
    return headers.encode()


def make_teamserver_mock(agent_id: str = "abcd1234") -> AsyncMock:
    ts = AsyncMock()
    ts.agent_checkin = AsyncMock()
    ts.agent_get_pending_tasks = AsyncMock(return_value=[])
    ts.get_session_key = AsyncMock(return_value=os.urandom(32))
    return ts


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------


def test_validate_config_passes():
    listener = HTTPListener()
    key = os.urandom(32).hex()
    cfg = listener.validate_config({
        "port_bind": 8080,
        "callback_addresses": ["127.0.0.1:8080"],
        "encrypt_key": key,
        "uris": ["/check"],
        "beat_header": "X-Beat",
    })
    assert cfg["host_bind"] == "0.0.0.0"
    assert cfg["ssl"] is False


def test_validate_config_missing_field():
    listener = HTTPListener()
    with pytest.raises(ValueError, match="Missing required field"):
        listener.validate_config({
            "port_bind": 8080,
            "callback_addresses": [],
            "encrypt_key": "a" * 64,
            "uris": ["/x"],
            # beat_header missing
        })


def test_validate_config_bad_key_length():
    listener = HTTPListener()
    with pytest.raises(ValueError, match="64 hex chars"):
        listener.validate_config({
            "port_bind": 8080,
            "callback_addresses": ["127.0.0.1"],
            "encrypt_key": "aabbcc",
            "uris": ["/x"],
            "beat_header": "X-Beat",
        })


def test_validate_config_bad_key_hex():
    listener = HTTPListener()
    with pytest.raises(ValueError, match="valid hex"):
        listener.validate_config({
            "port_bind": 8080,
            "callback_addresses": ["127.0.0.1"],
            "encrypt_key": "z" * 64,
            "uris": ["/x"],
            "beat_header": "X-Beat",
        })


# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------


def test_aes_roundtrip():
    key = os.urandom(32)
    pt = b"hello world"
    ct = _aes_encrypt(key, pt)
    assert _aes_decrypt(key, ct) == pt


def test_hkdf_derive_deterministic():
    master = os.urandom(32)
    k1 = _hkdf_derive(master, b"salt", b"info")
    k2 = _hkdf_derive(master, b"salt", b"info")
    assert k1 == k2


def test_hkdf_different_info():
    master = os.urandom(32)
    k1 = _hkdf_derive(master, b"beat", b"beat-encryption")
    k2 = _hkdf_derive(master, b"session", b"session-encryption")
    assert k1 != k2


# ---------------------------------------------------------------------------
# HTTP request processing
# ---------------------------------------------------------------------------


@pytest.fixture
def listener_config():
    key = os.urandom(32)
    return {
        "port_bind": 18080,
        "callback_addresses": ["127.0.0.1:18080"],
        "encrypt_key": key.hex(),
        "uris": ["/check"],
        "beat_header": "X-Beat",
        "host_bind": "0.0.0.0",
        "ssl": False,
        "http_method": "POST",
        "user_agents": [],
        "host_headers": [],
        "request_headers": {},
        "response_headers": {},
        "trust_x_forwarded_for": False,
        "page_error": "<html>404</html>",
        "page_payload": "<html><<<PAYLOAD_DATA>>></html>",
        "listener_name": "test-http",
    }, key


async def test_process_valid_request(listener_config):
    cfg, key = listener_config
    listener = HTTPListener()
    listener.config = cfg
    listener.teamserver = make_teamserver_mock()
    listener._master_key = key
    listener._beat_key = _hkdf_derive(key, b"beat", b"beat-encryption")

    agent_id = "abcd1234"
    beat_header_val = make_beat_header(key, "python", agent_id, {"hostname": "box"})
    raw = make_raw_http_request("/check", "x-beat", beat_header_val)

    response = await listener._process_http_request(raw)
    assert b"HTTP/1.1 200" in response
    listener.teamserver.agent_checkin.assert_called_once()


async def test_process_invalid_uri(listener_config):
    cfg, key = listener_config
    listener = HTTPListener()
    listener.config = cfg
    listener.teamserver = make_teamserver_mock()
    listener._master_key = key
    listener._beat_key = _hkdf_derive(key, b"beat", b"beat-encryption")

    beat_header_val = make_beat_header(key, "python", "abcd1234", {})
    raw = make_raw_http_request("/wrong-path", "x-beat", beat_header_val)

    response = await listener._process_http_request(raw)
    assert b"404" in response
    listener.teamserver.agent_checkin.assert_not_called()


async def test_process_paused_listener(listener_config):
    cfg, key = listener_config
    listener = HTTPListener()
    listener.config = cfg
    listener.paused = True
    listener.teamserver = make_teamserver_mock()
    listener._master_key = key
    listener._beat_key = _hkdf_derive(key, b"beat", b"beat-encryption")

    beat_header_val = make_beat_header(key, "python", "abcd1234", {})
    raw = make_raw_http_request("/check", "x-beat", beat_header_val)

    response = await listener._process_http_request(raw)
    assert b"HTTP/1.1 200" in response
    listener.teamserver.agent_checkin.assert_not_called()


async def test_process_user_agent_whitelist(listener_config):
    cfg, key = listener_config
    cfg["user_agents"] = ["GoodAgent/1.0"]
    listener = HTTPListener()
    listener.config = cfg
    listener.teamserver = make_teamserver_mock()
    listener._master_key = key
    listener._beat_key = _hkdf_derive(key, b"beat", b"beat-encryption")

    beat_header_val = make_beat_header(key, "python", "abcd1234", {})

    # Bad UA
    raw = make_raw_http_request("/check", "x-beat", beat_header_val,
                                 extra_headers={"User-Agent": "BadAgent"})
    response = await listener._process_http_request(raw)
    assert b"404" in response

    # Good UA
    raw2 = make_raw_http_request("/check", "x-beat", beat_header_val,
                                  extra_headers={"User-Agent": "GoodAgent/1.0"})
    response2 = await listener._process_http_request(raw2)
    assert b"HTTP/1.1 200" in response2


async def test_process_bad_beat_header(listener_config):
    cfg, key = listener_config
    listener = HTTPListener()
    listener.config = cfg
    listener.teamserver = make_teamserver_mock()
    listener._master_key = key
    listener._beat_key = _hkdf_derive(key, b"beat", b"beat-encryption")

    raw = make_raw_http_request("/check", "x-beat", "not-valid-base64!@#$")
    response = await listener._process_http_request(raw)
    assert b"404" in response


# ---------------------------------------------------------------------------
# Plugin loader
# ---------------------------------------------------------------------------


def test_listener_plugin_loader():
    from executec2.listeners import get_listener_class, list_listener_types, load_listeners
    load_listeners(["executec2.listeners.http_listener"])
    cls = get_listener_class("http")
    assert cls is HTTPListener
    assert "http" in list_listener_types()
