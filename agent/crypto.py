"""Agent-side cryptography: HKDF-SHA256 key derivation + AES-256-GCM."""

import hmac
import os
from hashlib import sha256
from typing import Any

import msgpack
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _hkdf(master: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=SHA256(), length=32, salt=salt, info=info).derive(master)


class AgentCrypto:
    """Manages per-agent encryption keys derived from master key."""

    def __init__(self, master_key_hex: str, agent_id: str):
        master = bytes.fromhex(master_key_hex)
        agent_salt = agent_id.encode()
        self.session_key: bytes = _hkdf(master, agent_salt, b"session-encryption")
        self.beat_key: bytes = _hkdf(master, b"beat", b"beat-encryption")

    def encrypt(self, key: bytes, plaintext: bytes) -> bytes:
        """AES-256-GCM encrypt. Wire format: [12B nonce][ciphertext+16B tag]."""
        nonce = os.urandom(12)
        return nonce + AESGCM(key).encrypt(nonce, plaintext, None)

    def decrypt(self, key: bytes, data: bytes) -> bytes:
        """AES-256-GCM decrypt. Expects wire format from encrypt()."""
        return AESGCM(key).decrypt(data[:12], data[12:], None)

    def encrypt_beat(self, plaintext: bytes) -> bytes:
        return self.encrypt(self.beat_key, plaintext)

    def decrypt_response(self, data: bytes) -> bytes:
        return self.decrypt(self.session_key, data)

    def sign_envelope(
        self,
        *,
        kind: str,
        seq: int,
        payload: Any,
        task_id: str = "",
        session_id: str = "",
        channel: str = "",
    ) -> dict:
        envelope = {
            "kind": kind,
            "seq": int(seq),
            "task_id": task_id,
            "session_id": session_id,
            "channel": channel,
            "payload": payload,
        }
        envelope["mac"] = hmac.new(
            self.session_key,
            msgpack.packb(envelope, use_bin_type=True),
            sha256,
        ).digest()
        return envelope

    def verify_envelope(self, envelope: dict) -> bool:
        mac = envelope.get("mac")
        if not isinstance(mac, (bytes, bytearray)):
            return False
        candidate = dict(envelope)
        candidate.pop("mac", None)
        expected = hmac.new(
            self.session_key,
            msgpack.packb(candidate, use_bin_type=True),
            sha256,
        ).digest()
        return hmac.compare_digest(bytes(mac), expected)
