# inventory_management/utils/auth.py
from __future__ import annotations

import os
import hmac
import hashlib
from typing import Union, Tuple

try:
    import bcrypt  # optional but recommended
except Exception:  # pragma: no cover
    bcrypt = None  # fall back to PBKDF2-only if bcrypt missing

# ---- PBKDF2 settings (legacy support) ----
_PBKDF2_PREFIX = "pbkdf2_sha256$"
_PBKDF2_DEFAULT_ITERS = 200_000  # keep your existing default
_PBKDF2_SALT_BYTES = 16

# ---- bcrypt defaults / policy ----
_BCRYPT_DEFAULT_ROUNDS = 12          # used when hashing
_BCRYPT_MIN_ACCEPTABLE_ROUNDS = 12   # rehash if lower than this


# --------------------------- PBKDF2 helpers ---------------------------

def _hash_pbkdf2(password: str, iterations: int = _PBKDF2_DEFAULT_ITERS) -> str:
    if not isinstance(iterations, int) or iterations < 50_000:
        # guard absurdly low iteration counts
        iterations = _PBKDF2_DEFAULT_ITERS
    salt = os.urandom(_PBKDF2_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_PBKDF2_PREFIX}{iterations}${salt.hex()}${dk.hex()}"

def _verify_pbkdf2(password: str, encoded: str) -> bool:
    try:
        # expected format: pbkdf2_sha256$<iters>$<salt_hex>$<digest_hex>
        if not encoded.startswith(_PBKDF2_PREFIX):
            return False
        _, iters_salt_dk = encoded.split(_PBKDF2_PREFIX, 1)
        iters_str, salt_hex, dk_hex = iters_salt_dk.split("$", 2)
        iters = int(iters_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


# ---------------------------- bcrypt helpers ----------------------------

def _hash_bcrypt(password: str, rounds: int = _BCRYPT_DEFAULT_ROUNDS) -> str:
    if bcrypt is None:
        # Library not available: fall back to PBKDF2 format
        return _hash_pbkdf2(password)
    try:
        rounds = int(rounds)
    except Exception:
        rounds = _BCRYPT_DEFAULT_ROUNDS
    if rounds < 4:
        rounds = _BCRYPT_DEFAULT_ROUNDS
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds)).decode("utf-8")

def _verify_bcrypt(password: str, encoded: Union[str, bytes]) -> bool:
    if bcrypt is None or not encoded:
        return False
    try:
        enc = encoded.encode("utf-8") if isinstance(encoded, str) else encoded
        return bcrypt.checkpw(password.encode("utf-8"), enc)
    except Exception:
        return False

def _parse_bcrypt_cost(hash_str: str) -> int | None:
    """
    Extract the cost from a bcrypt hash: $2b$12$...
    Returns None if not parseable.
    """
    try:
        parts = hash_str.split("$")
        # ['', '2b', '12', 'rest...']
        if len(parts) < 4:
            return None
        return int(parts[2])
    except Exception:
        return None


# ------------------------------- Public API -------------------------------

def hash_password(
    password: str,
    scheme: str = "bcrypt",
    *,
    bcrypt_rounds: int = _BCRYPT_DEFAULT_ROUNDS,
    pbkdf2_iterations: int = _PBKDF2_DEFAULT_ITERS,
) -> str:
    """
    Hash `password` using the chosen scheme.

    - scheme="bcrypt" (default) if bcrypt is available, else PBKDF2 fallback.
      You can override cost with `bcrypt_rounds` (default 12).
    - scheme="pbkdf2" to force the legacy format, with `pbkdf2_iterations`.

    The produced hash is always compatible with verify_password().
    """
    if password is None:
        raise ValueError("Password cannot be None")
    if not isinstance(password, str) or password == "":
        raise ValueError("Password must be a non-empty string")

    scheme = (scheme or "bcrypt").lower().strip()
    if scheme == "pbkdf2":
        return _hash_pbkdf2(password, iterations=pbkdf2_iterations)
    # default to bcrypt when available
    return _hash_bcrypt(password, rounds=bcrypt_rounds)

def verify_password(password: str, stored_hash: Union[str, bytes]) -> bool:
    """
    Verify `password` against `stored_hash`.
    Supports:
      - PBKDF2: 'pbkdf2_sha256$...'
      - bcrypt: $2a$ / $2b$ / $2y$...
    """
    if stored_hash is None or password is None:
        return False

    if isinstance(stored_hash, bytes):
        try:
            stored_hash = stored_hash.decode("utf-8")
        except Exception:
            return False

    stored_hash = stored_hash.strip()
    if not stored_hash:
        return False

    # Route by prefix
    if stored_hash.startswith(_PBKDF2_PREFIX):
        return _verify_pbkdf2(password, stored_hash)

    if stored_hash.startswith("$2a$") or stored_hash.startswith("$2b$") or stored_hash.startswith("$2y$"):
        return _verify_bcrypt(password, stored_hash)

    # Unknown scheme
    return False

def needs_rehash(
    stored_hash: Union[str, bytes],
    *,
    prefer_bcrypt: bool = True,
    bcrypt_min_rounds: int = _BCRYPT_MIN_ACCEPTABLE_ROUNDS,
    pbkdf2_min_iterations: int = _PBKDF2_DEFAULT_ITERS,
) -> bool:
    """
    Policy hook: return True if the given stored hash should be upgraded.

    Defaults:
      - Prefer migrating PBKDF2 → bcrypt when possible.
      - If hash is bcrypt but cost < bcrypt_min_rounds, rehash.
      - If hash is PBKDF2 with iterations < pbkdf2_min_iterations, rehash.
    """
    if not stored_hash:
        return True

    if isinstance(stored_hash, bytes):
        try:
            stored_hash = stored_hash.decode("utf-8")
        except Exception:
            return True

    h = stored_hash.strip()
    if not h:
        return True

    if h.startswith(_PBKDF2_PREFIX):
        if prefer_bcrypt:
            return True  # migrate PBKDF2 → bcrypt on next successful login
        # still consider iterations
        try:
            _, rest = h.split(_PBKDF2_PREFIX, 1)
            iters_str, _salt_hex, _dk_hex = rest.split("$", 2)
            iters = int(iters_str)
        except Exception:
            return True
        return iters < pbkdf2_min_iterations

    if h.startswith("$2a$") or h.startswith("$2b$") or h.startswith("$2y$"):
        cost = _parse_bcrypt_cost(h)
        return cost is None or cost < bcrypt_min_rounds

    # Unknown or malformed scheme → flag for rehash to current policy
    return True
