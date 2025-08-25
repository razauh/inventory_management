# inventory_management/utils/auth.py
from __future__ import annotations

import os
import hmac
import hashlib
from typing import Union

try:
    import bcrypt  # optional dependency but recommended
except Exception:  # pragma: no cover
    bcrypt = None  # fall back to PBKDF2-only if bcrypt missing

# ---- PBKDF2 settings (legacy support) ----
_PBKDF2_PREFIX = "pbkdf2_sha256$"
_PBKDF2_DEFAULT_ITERS = 200_000  # keep your existing default

def _hash_pbkdf2(password: str, iterations: int = _PBKDF2_DEFAULT_ITERS) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_PBKDF2_PREFIX}{iterations}${salt.hex()}${dk.hex()}"

def _verify_pbkdf2(password: str, encoded: str) -> bool:
    try:
        # expected format: pbkdf2_sha256$<iters>$<salt_hex>$<digest_hex>
        algo, iters, salt_hex, dk_hex = encoded.split("$", 3)
        if not algo.startswith("pbkdf2_sha256"):
            return False  # explicit check instead of ignoring 'algo'
        iters = int(iters)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(got, expected)
    except Exception:
        return False

# ---- bcrypt helpers (preferred) ----
def _hash_bcrypt(password: str) -> str:
    if bcrypt is None:
        # Library not available: fall back to PBKDF2 format
        return _hash_pbkdf2(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def _verify_bcrypt(password: str, encoded: Union[str, bytes]) -> bool:
    if bcrypt is None or not encoded:
        return False
    try:
        enc = encoded.encode("utf-8") if isinstance(encoded, str) else encoded
        return bcrypt.checkpw(password.encode("utf-8"), enc)
    except Exception:
        return False

# ---- public API ----
def hash_password(password: str, scheme: str = "bcrypt") -> str:
    """
    Hash `password` using the chosen scheme.
      - scheme="bcrypt" (default) if bcrypt is available, else PBKDF2 fallback.
      - scheme="pbkdf2" to force legacy format.
    """
    if password is None:
        raise ValueError("Password cannot be None")

    scheme = scheme.lower().strip()
    if scheme == "pbkdf2":
        return _hash_pbkdf2(password)
    # default to bcrypt when available
    return _hash_bcrypt(password)

def verify_password(password: str, stored_hash: Union[str, bytes]) -> bool:
    """
    Verify `password` against `stored_hash`.
    Supports:
      - PBKDF2: 'pbkdf2_sha256$...'
      - bcrypt: $2a$ / $2b$ / $2y$...
    """
    if not stored_hash or password is None:
        return False
    if isinstance(stored_hash, bytes):
        try:
            stored_hash = stored_hash.decode("utf-8")
        except Exception:
            return False

    # Route by prefix
    if stored_hash.startswith(_PBKDF2_PREFIX):
        return _verify_pbkdf2(password, stored_hash)

    if stored_hash.startswith("$2a$") or stored_hash.startswith("$2b$") or stored_hash.startswith("$2y$"):
        return _verify_bcrypt(password, stored_hash)

    # Unknown scheme
    return False

def needs_rehash(stored_hash: Union[str, bytes]) -> bool:
    """
    Policy hook: return True if the given stored hash should be upgraded.
    Current policy: upgrade all PBKDF2 hashes to bcrypt when possible.
    """
    if not stored_hash:
        return True
    if isinstance(stored_hash, bytes):
        try:
            stored_hash = stored_hash.decode("utf-8")
        except Exception:
            return True
    # Upgrade PBKDF2 → bcrypt
    return stored_hash.startswith(_PBKDF2_PREFIX)
