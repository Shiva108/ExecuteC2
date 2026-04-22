"""Unit tests for agent crypto and connector helpers."""

import base64
import os

import pytest

from agent.crypto import AgentCrypto

# ---------------------------------------------------------------------------
# AgentCrypto
# ---------------------------------------------------------------------------


def test_key_derivation_deterministic():
    master = os.urandom(32).hex()
    agent_id = "aabbccdd"
    c1 = AgentCrypto(master, agent_id)
    c2 = AgentCrypto(master, agent_id)
    assert c1.session_key == c2.session_key
    assert c1.beat_key == c2.beat_key


def test_different_agent_ids_different_keys():
    master = os.urandom(32).hex()
    c1 = AgentCrypto(master, "aabbccdd")
    c2 = AgentCrypto(master, "11223344")
    assert c1.session_key != c2.session_key


def test_encrypt_decrypt_roundtrip():
    master = os.urandom(32).hex()
    crypto = AgentCrypto(master, "aabbccdd")
    pt = b"hello world"
    ct = crypto.encrypt(crypto.session_key, pt)
    assert crypto.decrypt(crypto.session_key, ct) == pt


def test_beat_encrypt_decrypt():
    master = os.urandom(32).hex()
    crypto = AgentCrypto(master, "aabbccdd")
    pt = b"beat data"
    ct = crypto.encrypt_beat(pt)
    assert crypto.decrypt(crypto.beat_key, ct) == pt


def test_wire_format_has_12_byte_nonce():
    master = os.urandom(32).hex()
    crypto = AgentCrypto(master, "aabbccdd")
    pt = b"test"
    ct = crypto.encrypt(crypto.session_key, pt)
    # 12 nonce + len(pt) + 16 GCM tag
    assert len(ct) == 12 + len(pt) + 16


def test_decrypt_wrong_key_fails():
    master = os.urandom(32).hex()
    crypto = AgentCrypto(master, "aabbccdd")
    pt = b"secret"
    ct = crypto.encrypt(crypto.session_key, pt)
    wrong_key = os.urandom(32)
    with pytest.raises(Exception):
        crypto.decrypt(wrong_key, ct)


def test_different_masters_different_keys():
    m1 = os.urandom(32).hex()
    m2 = os.urandom(32).hex()
    c1 = AgentCrypto(m1, "aabbccdd")
    c2 = AgentCrypto(m2, "aabbccdd")
    assert c1.session_key != c2.session_key
    assert c1.beat_key != c2.beat_key


# ---------------------------------------------------------------------------
# HTTPConnector helpers
# ---------------------------------------------------------------------------


def test_parse_payload_present():
    from agent.connector_http import HTTPConnector
    conn = HTTPConnector({
        "callback_addresses": ["127.0.0.1:8080"],
        "uris": ["/check"],
        "beat_header": "X-Beat",
    })
    payload = base64.b64encode(b"hello").decode()
    html = f"<html><<<PAYLOAD_DATA>>>{payload}</html>".encode()
    result = conn.parse_payload(html)
    assert result == b"hello"


def test_parse_payload_missing_marker():
    from agent.connector_http import HTTPConnector
    conn = HTTPConnector({
        "callback_addresses": ["127.0.0.1:8080"],
        "uris": ["/check"],
        "beat_header": "X-Beat",
    })
    html = b"<html><body>Nothing here</body></html>"
    assert conn.parse_payload(html) is None


def test_connector_url_rotation():
    from agent.connector_http import HTTPConnector
    conn = HTTPConnector({
        "callback_addresses": ["10.0.0.1:80", "10.0.0.2:80"],
        "uris": ["/check"],
        "beat_header": "X-Beat",
    })
    url1 = conn._next_url()
    url2 = conn._next_url()
    # Should alternate between addresses
    assert "10.0.0.1" in url1 or "10.0.0.2" in url1
    assert url1 != url2 or len(conn.callback_addresses) == 1


def test_connector_backoff_increases():
    from agent.connector_http import HTTPConnector
    conn = HTTPConnector({
        "callback_addresses": ["127.0.0.1:8080"],
        "uris": ["/check"],
        "beat_header": "X-Beat",
    })
    conn._fail_count = 0
    b0 = conn._backoff()
    conn._fail_count = 5
    b5 = conn._backoff()
    assert b5 > b0


@pytest.mark.asyncio
async def test_connector_ssl_verify_requires_fingerprint():
    from agent.connector_http import HTTPConnector

    conn = HTTPConnector({
        "callback_addresses": ["127.0.0.1:8080"],
        "uris": ["/check"],
        "beat_header": "X-Beat",
        "ssl": True,
        "verify_ssl": True,
    })
    result = await conn.check_in("abc")
    assert result is None
