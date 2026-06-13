"""Shared transport helpers for agent communications."""

from __future__ import annotations

import hmac
import os
from hashlib import sha256
from typing import Any

import msgpack
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def hkdf_derive(master_key: bytes, salt: bytes, info: bytes) -> bytes:
    """Derive a 32-byte key from listener material."""
    hkdf = HKDF(algorithm=SHA256(), length=32, salt=salt, info=info)
    return hkdf.derive(master_key)


def derive_beat_key(master_key: bytes) -> bytes:
    return hkdf_derive(master_key, b"beat", b"beat-encryption")


def derive_session_key(master_key: bytes, agent_id: str) -> bytes:
    return hkdf_derive(master_key, agent_id.encode(), b"session-encryption")


def aes_encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def aes_decrypt(key: bytes, data: bytes) -> bytes:
    return AESGCM(key).decrypt(data[:12], data[12:], None)


def _signing_bytes(envelope: dict[str, Any]) -> bytes:
    payload = {
        "kind": envelope["kind"],
        "seq": int(envelope["seq"]),
        "task_id": envelope.get("task_id", ""),
        "session_id": envelope.get("session_id", ""),
        "channel": envelope.get("channel", ""),
        "payload": envelope.get("payload"),
    }
    return msgpack.packb(payload, use_bin_type=True)


def sign_envelope(
    *,
    key: bytes,
    kind: str,
    seq: int,
    payload: Any,
    task_id: str = "",
    session_id: str = "",
    channel: str = "",
) -> dict[str, Any]:
    envelope = {
        "kind": kind,
        "seq": int(seq),
        "task_id": task_id,
        "session_id": session_id,
        "channel": channel,
        "payload": payload,
    }
    envelope["mac"] = hmac.new(key, _signing_bytes(envelope), sha256).digest()
    return envelope


def verify_envelope(key: bytes, envelope: dict[str, Any]) -> bool:
    mac = envelope.get("mac")
    if not isinstance(mac, (bytes, bytearray)):
        return False
    candidate = dict(envelope)
    candidate.pop("mac", None)
    expected = hmac.new(key, _signing_bytes(candidate), sha256).digest()
    return hmac.compare_digest(bytes(mac), expected)

