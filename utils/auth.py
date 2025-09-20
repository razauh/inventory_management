# inventory_management/utils/auth.py
from __future__ import annotations

import os
import hmac
import hashlib
from typing import Union, Tuple, Optional, Callable

try:
    import bcrypt  # optional but recommended
except Exception:  # pragma: no cover
    bcrypt = None  # fall back to PBKDF2-only if bcrypt missing

# ---- PBKDF2 settings (legacy support) ----
_PBKDF2_PREFIX = "pbkdf2_sha256$"
_PBKDF2_DEFAULT_ITERS = 200_000  # keep your existing default (min acceptable too)
_PBKDF2_SALT_BYTES = 16

# ---- bcrypt defaults / policy ----
_BCRYPT_DEFAULT_ROUNDS = 12          # used when hashing
_BCRYPT_MIN_ACCEPTABLE_ROUNDS = 12   # rehash if lower than this


# --------------------------- Exceptions / Policy ---------------------------

class SecurityPolicyError(Exception):
    """Raised when authentication succeeds but policy requires stricter storage."""


# --------------------------- PBKDF2 helpers ---------------------------

def _hash_pbkdf2(password: str, iterations: int = _PBKDF2_DEFAULT_ITERS) -> str:
    # Enforce a minimum equal to the current default
    try:
        iterations = int(iterations)
    except Exception:
        iterations = _PBKDF2_DEFAULT_ITERS
    if iterations < _PBKDF2_DEFAULT_ITERS:
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
        iters_str, salt_hex, dk_hex = iters_salt_dk.split("$", 3)
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
    # Enforce minimum acceptable cost
    if rounds < _BCRYPT_MIN_ACCEPTABLE_ROUNDS:
        rounds = _BCRYPT_MIN_ACCEPTABLE_ROUNDS
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
      You can override cost with `bcrypt_rounds` (default 12). We clamp to a
      minimum of _BCRYPT_MIN_ACCEPTABLE_ROUNDS.
    - scheme="pbkdf2" to force the legacy format, with `pbkdf2_iterations`.
      We clamp to a minimum of _PBKDF2_DEFAULT_ITERS.

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
      - Unknown/malformed hashes → True (rotate to current policy).
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


# ------------------------- Optional convenience API -------------------------

def is_hash_strong_enough(
    stored_hash: Union[str, bytes],
    *,
    bcrypt_min_rounds: int = _BCRYPT_MIN_ACCEPTABLE_ROUNDS,
    pbkdf2_min_iterations: int = _PBKDF2_DEFAULT_ITERS,
) -> bool:
    """
    Return True if `stored_hash` meets current minimums. Unlike needs_rehash(),
    this does NOT force PBKDF2→bcrypt migration; it only checks minimum strength.
    """
    if not stored_hash:
        return False
    if isinstance(stored_hash, bytes):
        try:
            stored_hash = stored_hash.decode("utf-8")
        except Exception:
            return False
    h = stored_hash.strip()
    if not h:
        return False

    if h.startswith(_PBKDF2_PREFIX):
        try:
            _, rest = h.split(_PBKDF2_PREFIX, 1)
            iters_str, _salt_hex, _dk_hex = rest.split("$", 2)
            iters = int(iters_str)
            return iters >= pbkdf2_min_iterations
        except Exception:
            return False

    if h.startswith("$2a$") or h.startswith("$2b$") or h.startswith("$2y$"):
        cost = _parse_bcrypt_cost(h)
        return cost is not None and cost >= bcrypt_min_rounds

    return False  # unknown/malformed


def verify_and_maybe_upgrade(
    password: str,
    stored_hash: Union[str, bytes],
    *,
    preferred_scheme: str = "bcrypt",
    bcrypt_rounds: int = _BCRYPT_DEFAULT_ROUNDS,
    pbkdf2_iterations: int = _PBKDF2_DEFAULT_ITERS,
    on_rehash: Optional[Callable[[str], None]] = None,
    strict_enforce: bool = False,
    bcrypt_min_rounds: int = _BCRYPT_MIN_ACCEPTABLE_ROUNDS,
    pbkdf2_min_iterations: int = _PBKDF2_DEFAULT_ITERS,
) -> Tuple[bool, Optional[str], bool]:
    """
    Verify the password and, if policy recommends, produce an upgraded hash.

    Returns: (ok, new_hash_or_None, did_rehash)

    - If verification fails → (False, None, False)
    - If verification succeeds and rehash is recommended → (True, new_hash, True)
      and calls on_rehash(new_hash) if provided.
    - If verification succeeds and no rehash is needed → (True, None, False)

    strict_enforce:
      If True and the stored hash is below minimum strength (see is_hash_strong_enough),
      authentication succeeds cryptographically but a SecurityPolicyError is raised
      to allow callers to block sign-in for high-risk roles until the hash is rotated.
      The new hash is still generated and passed to `on_rehash` when possible.
    """
    ok = verify_password(password, stored_hash)
    if not ok:
        return False, None, False

    # Optionally block weak-but-correct hashes for high-risk contexts
    strong_enough = is_hash_strong_enough(
        stored_hash,
        bcrypt_min_rounds=bcrypt_min_rounds,
        pbkdf2_min_iterations=pbkdf2_min_iterations,
    )

    # Decide if we should rehash at all (upgrade path)
    do_rehash = needs_rehash(
        stored_hash,
        prefer_bcrypt=(preferred_scheme or "bcrypt").lower().strip() == "bcrypt",
        bcrypt_min_rounds=bcrypt_min_rounds,
        pbkdf2_min_iterations=pbkdf2_min_iterations,
    )

    new_hash: Optional[str] = None
    did_rehash = False
    if do_rehash:
        new_hash = hash_password(
            password,
            scheme=preferred_scheme,
            bcrypt_rounds=bcrypt_rounds,
            pbkdf2_iterations=pbkdf2_iterations,
        )
        did_rehash = True
        if callable(on_rehash):
            try:
                on_rehash(new_hash)
            except Exception:
                # Callback errors should not break auth flow
                pass

    if strict_enforce and not strong_enough:
        # Caller wants to block login for weak hashes in sensitive contexts.
        # Raise after producing a new hash (so the caller can store it).
        raise SecurityPolicyError(
            "Password verified, but stored hash does not meet minimum strength "
            "requirements; please try signing in again."
        )

    return True, new_hash, did_rehash
