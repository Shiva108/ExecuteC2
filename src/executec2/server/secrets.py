"""Key derivation and envelope encryption helpers for server-side secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_ENV_PREFIX = b"EC2E1"


def _hkdf(master: bytes, info: bytes, length: int = 32) -> bytes:
    hkdf = HKDF(algorithm=SHA256(), length=length, salt=None, info=info)
    return hkdf.derive(master)


def is_envelope(blob: bytes) -> bool:
    return blob.startswith(_ENV_PREFIX)


def encrypt_envelope(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return _ENV_PREFIX + nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt_envelope(key: bytes, blob: bytes) -> bytes:
    if not is_envelope(blob):
        raise ValueError("not an EC2 envelope")
    nonce = blob[len(_ENV_PREFIX):len(_ENV_PREFIX) + 12]
    payload = blob[len(_ENV_PREFIX) + 12:]
    return AESGCM(key).decrypt(nonce, payload, None)


def decrypt_legacy_aesgcm(key: bytes, blob: bytes) -> bytes:
    """Legacy format: [12-byte nonce][ciphertext+tag]."""
    if len(blob) < 13:
        raise ValueError("legacy blob too short")
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)


@dataclass(frozen=True)
class SecretContext:
    """Derived long-lived keys scoped from EC2_MASTER_SECRET."""

    jwt_signing_key: bytes
    credential_key: bytes
    session_wrap_key: bytes
    legacy_credential_key: bytes

    @classmethod
    def from_master_secret(cls, master_secret: str) -> "SecretContext":
        if not master_secret:
            raise ValueError("master secret is required")
        master = master_secret.encode("utf-8")
        jwt_key = _hkdf(master, b"jwt-signing")
        cred_key = _hkdf(master, b"credential-at-rest")
        session_key = _hkdf(master, b"agent-session-wrap")
        # Backward-compatible key derivation path used by earlier credential code.
        legacy_cred = _hkdf(jwt_key, b"credential-at-rest")
        return cls(
            jwt_signing_key=jwt_key,
            credential_key=cred_key,
            session_wrap_key=session_key,
            legacy_credential_key=legacy_cred,
        )

