from __future__ import annotations

import hashlib
import hmac
import secrets


def create_integration_token() -> tuple[str, str, str]:
    plaintext = f"m1i_{secrets.token_urlsafe(32)}"
    return (
        plaintext,
        plaintext[:12],
        hashlib.sha256(plaintext.encode()).hexdigest(),
    )


def verify_integration_token(plaintext: str, expected_hash: str) -> bool:
    actual_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    return hmac.compare_digest(actual_hash, expected_hash)
