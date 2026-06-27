from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${salt_b64}${digest_b64}"


def is_password_hash(value: str) -> bool:
    parts = value.split("$")
    if len(parts) != 4 or parts[0] != PASSWORD_SCHEME:
        return False
    try:
        int(parts[1])
        base64.b64decode(parts[2].encode("ascii"), validate=True)
        base64.b64decode(parts[3].encode("ascii"), validate=True)
    except (ValueError, binascii.Error):
        return False
    return True


def verify_password(password: str, stored_value: str) -> bool:
    if not stored_value:
        return False
    if not is_password_hash(stored_value):
        return hmac.compare_digest(stored_value, password)
    _, iterations_text, salt_b64, digest_b64 = stored_value.split("$", 3)
    iterations = int(iterations_text)
    salt = base64.b64decode(salt_b64.encode("ascii"))
    expected_digest = base64.b64decode(digest_b64.encode("ascii"))
    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)
