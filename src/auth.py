"""
BetVector — Authentication Module (E34-01)
==========================================
Password hashing/verification and Streamlit session state helpers for
the multi-user authentication system introduced in Epic 34.

Hashing scheme
--------------
PBKDF2-HMAC-SHA256 with a fresh 16-byte (128-bit) random salt per hash
and 260,000 iterations (OWASP recommendation as of 2023).

Stored format::

    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

The format is self-describing — algorithm name, iteration count, and salt
are all embedded in the string, so future algorithm upgrades can be handled
gracefully by inspecting the prefix without breaking existing hashes.

No external dependencies — uses only Python stdlib (``hashlib``, ``secrets``).

Session state contract
-----------------------
After a successful login the following keys are stored in ``st.session_state``:

- ``user_id``   (int)  — the authenticated user's database primary key
- ``user_role`` (str)  — ``"owner"`` or ``"viewer"``

Helper functions ``get_session_user_id()`` and ``get_session_user_role()``
default to ``1`` / ``"owner"`` respectively so that existing pages continue
to work without modification during the E34 migration.

Master Plan refs: MP §6 Database Schema (users table)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import datetime
from typing import Optional

import streamlit as st

from src.database.db import get_session
from src.database.models import User

logger = logging.getLogger(__name__)

# ============================================================================
# PBKDF2 Configuration
# ============================================================================

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 260_000   # OWASP recommendation (2023); increase over time as hardware improves
_SALT_BYTES = 16        # 128-bit salt — collision probability negligible for any realistic user count


# ============================================================================
# Password Hashing
# ============================================================================

def hash_password(plain: str) -> str:
    """Hash a plaintext password using PBKDF2-SHA256 with a random salt.

    A fresh random salt is generated for every call — two invocations with
    the same password will produce different hash strings.  This means
    identical passwords cannot be identified by comparing stored hashes.

    Parameters
    ----------
    plain : str
        The plaintext password chosen by (or assigned to) the user.

    Returns
    -------
    str
        A self-describing hash string::

            pbkdf2_sha256$260000$<32-char salt hex>$<64-char hash hex>
    """
    salt = secrets.token_hex(_SALT_BYTES)   # 16 bytes → 32 hex chars
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt.encode("utf-8"),
        _ITERATIONS,
    )
    return f"{_ALGORITHM}${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(plain: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored PBKDF2 hash.

    Timing-safe: uses ``secrets.compare_digest`` to prevent timing attacks
    where an attacker could measure response time to infer hash characters.

    Parameters
    ----------
    plain : str
        The plaintext password submitted at login.
    stored_hash : str
        The hash string previously returned by ``hash_password()``.

    Returns
    -------
    bool
        ``True`` if the password matches the stored hash, ``False`` otherwise.
        Returns ``False`` for any malformed hash string rather than raising.
    """
    try:
        algorithm, iterations_str, salt, stored_hex = stored_hash.split("$", 3)
    except (ValueError, AttributeError):
        logger.warning("verify_password: malformed hash string (wrong number of segments)")
        return False

    if algorithm != _ALGORITHM:
        logger.warning("verify_password: unsupported algorithm '%s'", algorithm)
        return False

    try:
        iterations = int(iterations_str)
    except ValueError:
        logger.warning("verify_password: non-integer iterations '%s'", iterations_str)
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    # compare_digest is constant-time regardless of where the strings first differ
    return secrets.compare_digest(digest.hex(), stored_hex)


# ============================================================================
# Password Management (invite hardening)
# ============================================================================

# Unambiguous alphabet for owner-generated temporary passwords — excludes the
# visually confusing characters (0/O, 1/l/I) so a temp password read off a
# screen and typed by hand isn't misheard.  Letters and digits only (no
# symbols) so it survives copy/paste and chat apps without escaping surprises.
_TEMP_PW_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"
_TEMP_PW_DIGITS = "23456789"
_TEMP_PW_ALPHABET = _TEMP_PW_LETTERS + _TEMP_PW_DIGITS

# Minimum password length, shared by every entry point (account creation,
# forced first-login change, self-service change) so the rule can't drift.
MIN_PASSWORD_LENGTH = 8


def generate_temp_password(length: int = 12) -> str:
    """Generate a random temporary password for an owner-created account.

    Uses ``secrets`` (cryptographically secure) over an unambiguous
    letters+digits alphabet, and guarantees at least one letter and one digit
    so the result always satisfies the basic strength check.  Length is clamped
    to a minimum of :data:`MIN_PASSWORD_LENGTH`.

    The plaintext is shown to the owner ONCE (to pass on out-of-band) and is
    stored only as a PBKDF2 hash — never persisted in plaintext.  The user is
    forced to replace it on first login (``must_change_password=1``).
    """
    length = max(length, MIN_PASSWORD_LENGTH)
    # Guarantee composition: one letter + one digit, then fill the remainder.
    chars = [secrets.choice(_TEMP_PW_LETTERS), secrets.choice(_TEMP_PW_DIGITS)]
    chars += [secrets.choice(_TEMP_PW_ALPHABET) for _ in range(length - 2)]
    # Shuffle so the guaranteed letter/digit aren't always in positions 0/1.
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def validate_new_password(
    new_password: str,
    confirm_password: str,
    current_hash: Optional[str] = None,
) -> tuple[bool, str]:
    """Validate a proposed new password.  Pure — no DB, no side effects.

    Rules:
    - non-empty and at least :data:`MIN_PASSWORD_LENGTH` characters
    - ``new_password`` and ``confirm_password`` must match
    - if ``current_hash`` is supplied, the new password must DIFFER from the
      current one (blocks "changing" to the same temporary password)

    Returns ``(ok, message)`` — ``message`` is a user-facing error when
    ``ok`` is False, or ``""`` when valid.
    """
    if not new_password:
        return False, "Please enter a new password."
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if new_password != confirm_password:
        return False, "The two passwords don't match."
    if current_hash and verify_password(new_password, current_hash):
        return False, "New password must be different from your current one."
    return True, ""


def set_user_password(user_id: int, new_password: str) -> bool:
    """Hash and store a new password for ``user_id``, clearing the
    forced-change flag.  Returns True on success, False on any error.

    This is the single writer for passwords outside account creation: the
    forced first-login screen and the Settings self-service change both end
    here.  Setting a password always clears ``must_change_password`` — once the
    user has chosen their own secret, the temporary-password state is over.
    """
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if user is None:
                return False
            user.password_hash = hash_password(new_password)
            user.must_change_password = 0
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
            return True
    except Exception:
        logger.exception("set_user_password failed for user_id=%s", user_id)
        return False


def admin_reset_password(user_id: int) -> Optional[str]:
    """Owner-driven password reset for ANOTHER user's account (UM-01).

    Generates a fresh temporary password, stores its PBKDF2 hash, and sets
    ``must_change_password=1`` so the user is force-routed to choose their own on
    next login — the owner never keeps their password.  Returns the plaintext temp
    password ONCE for the owner to pass on out-of-band, or None on failure / unknown
    user.

    This deliberately does NOT call :func:`set_user_password`: that helper *clears*
    the forced-change flag (it's the self-service path where the user has just chosen
    their own secret), whereas an admin reset must *re-arm* the forced change so the
    owner-set temporary password can't become permanent.  All in one transaction.
    """
    try:
        temp_password = generate_temp_password()
        with get_session() as session:
            user = session.get(User, user_id)
            if user is None:
                return None
            user.password_hash = hash_password(temp_password)
            user.must_change_password = 1
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
            return temp_password
    except Exception:
        logger.exception("admin_reset_password failed for user_id=%s", user_id)
        return None


def change_own_password(
    user_id: int,
    current_password: str,
    new_password: str,
    confirm_password: str,
) -> tuple[bool, str]:
    """Self-service password change for the logged-in user.

    Verifies the current password before allowing the change (defence against
    an unattended authenticated session).  If the account has NO password set
    yet (``password_hash`` is NULL — only possible for the owner who has been
    using the emergency ``DASHBOARD_PASSWORD`` fallback), the current-password
    check is skipped so they can set one for the first time.

    Returns ``(ok, message)`` — ``message`` is a success or error string.
    """
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            return False, "Account not found."
        stored = user.password_hash

    # Verify the current password unless none is set yet.
    if stored:
        if not current_password or not verify_password(current_password, stored):
            return False, "Your current password is incorrect."

    ok, msg = validate_new_password(new_password, confirm_password, current_hash=stored)
    if not ok:
        return False, msg

    if set_user_password(user_id, new_password):
        return True, "Password updated."
    return False, "Could not update password — please try again."


def user_must_change_password(user) -> bool:
    """Pure predicate: does this User row require a forced password change?

    Tolerates a missing attribute by defaulting to False, so older in-memory
    objects (or the emergency-owner fallback) never get trapped.  Centralised
    so the dashboard gate and the tests share one definition.
    """
    return bool(getattr(user, "must_change_password", 0))


# ============================================================================
# User Lookup
# ============================================================================

def get_user_by_email(email: str) -> Optional[User]:
    """Look up an active User by email address.

    Normalises the email (strip + lowercase) before querying.  Only returns
    active users (``is_active = 1``); deactivated accounts return ``None``.

    The returned ``User`` object is expelled from its session before returning
    so it is safe to use outside the ``with get_session()`` block.  All eager-
    loaded column values remain accessible; no lazy-loaded relationships are
    defined on ``User`` so there is no risk of DetachedInstanceError.

    Parameters
    ----------
    email : str
        Email address to look up.

    Returns
    -------
    User or None
        The matching active User, or ``None`` if not found / inactive.
    """
    normalised = email.strip().lower()
    with get_session() as session:
        user = (
            session.query(User)
            .filter(User.email == normalised, User.is_active == 1)
            .first()
        )
        if user is not None:
            # Expunge before the session closes so attributes remain readable
            session.expunge(user)
        return user


# ============================================================================
# Session State Helpers
# ============================================================================

def set_session_user(user_id: int, user_role: str) -> None:
    """Store authenticated user identity in Streamlit session state.

    Called immediately after a successful login.  Replaces the old boolean
    ``st.session_state["authenticated"]`` flag with structured identity data
    so every page can know *who* is logged in, not just *that* someone is.

    Parameters
    ----------
    user_id : int
        The authenticated user's database primary key.
    user_role : str
        The user's role — ``"owner"`` or ``"viewer"``.
    """
    st.session_state["user_id"] = user_id
    st.session_state["user_role"] = user_role


def clear_session_user() -> None:
    """Remove authentication state from session (logout).

    Safe to call even if the user was never authenticated — uses ``pop``
    with a default to avoid ``KeyError``.
    """
    st.session_state.pop("user_id", None)
    st.session_state.pop("user_role", None)


def is_authenticated() -> bool:
    """Return ``True`` if a user is currently authenticated in this session.

    Replaces the old ``st.session_state.get("authenticated", False)`` check.
    Authentication is determined by the presence of ``user_id`` in session
    state, which is only set by ``set_session_user()`` after a successful login.
    """
    return "user_id" in st.session_state


def get_session_user_id() -> int:
    """Return the logged-in user's database ID.

    Defaults to ``1`` so that dashboard pages not yet updated for E34-03
    continue to work correctly during the migration period.

    Returns
    -------
    int
        The ``user_id`` from session state, or ``1`` if not authenticated.
    """
    return st.session_state.get("user_id", 1)


def get_session_user_role() -> str:
    """Return the logged-in user's role string.

    Defaults to ``"owner"`` so that the emergency fallback (``DASHBOARD_PASSWORD``
    env var) retains full owner access for the account owner.

    Returns
    -------
    str
        ``"owner"`` or ``"viewer"``.
    """
    return st.session_state.get("user_role", "owner")


# ============================================================================
# Persistent Login — Signed Session Cookie
# ============================================================================
# Streamlit keeps ``st.session_state`` only for the life of a browser WebSocket
# connection, so a full page refresh starts a fresh session and the user
# appears logged out.  To survive a refresh we store a SIGNED, EXPIRING token in
# a browser cookie (set/read by the dashboard via streamlit-cookies-controller)
# and re-hydrate the session from it on load.
#
# Token format:  ``"<user_id>.<expiry_epoch>.<hmac_sha256>"``
# The HMAC is keyed on a server-side secret (SESSION_COOKIE_SECRET) so a client
# can neither forge nor tamper with a token — only the server can mint a valid
# one.  Without a secret configured the feature is INERT (both functions return
# ``None``), so the app safely degrades to session-only auth with no behaviour
# change and no error.

SESSION_COOKIE_NAME = "bv_session"


def _cookie_secret() -> Optional[str]:
    """Return the server-side HMAC secret for session cookies, or ``None``.

    Looks in the ``SESSION_COOKIE_SECRET`` environment variable first (local
    ``.env``), then Streamlit secrets (cloud).  Returns ``None`` if neither is
    set — callers treat that as "persistent login disabled", never an error.
    The secret value is never logged.
    """
    sec = os.environ.get("SESSION_COOKIE_SECRET")
    if not sec:
        try:
            sec = st.secrets.get("SESSION_COOKIE_SECRET")
        except Exception:
            # st.secrets raises when no secrets file exists — treat as unset.
            sec = None
    return sec or None


def make_session_token(
    user_id: int,
    days: int,
    *,
    secret: Optional[str] = None,
    now_ts: Optional[float] = None,
) -> Optional[str]:
    """Mint a signed session token for ``user_id`` valid for ``days`` days.

    Returns ``None`` if no signing secret is configured (feature disabled).
    ``secret`` and ``now_ts`` are injectable so the function is pure and unit
    testable; in production they default to :func:`_cookie_secret` and the wall
    clock.

    Parameters
    ----------
    user_id : int
        The authenticated user's database id to embed in the token.
    days : int
        Token lifetime in days (also used as the cookie max-age by the caller).
    """
    secret = secret if secret is not None else _cookie_secret()
    if not secret:
        return None
    now_ts = time.time() if now_ts is None else now_ts
    expiry = int(now_ts + days * 86400)
    message = f"{int(user_id)}.{expiry}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}.{signature}"


def verify_session_token(
    token: Optional[str],
    *,
    secret: Optional[str] = None,
    now_ts: Optional[float] = None,
) -> Optional[int]:
    """Validate a session token and return its ``user_id``, or ``None``.

    Rejects (returns ``None``) when: no secret is configured, the token is
    malformed, the signature doesn't match (tampered/forged), or it has expired.
    Uses :func:`hmac.compare_digest` for a constant-time signature comparison so
    it can't be timing-attacked.

    This proves the token's INTEGRITY and FRESHNESS only — the caller must still
    confirm the user is active in the database before trusting it, because a
    token stays cryptographically valid until its expiry even if the account was
    deactivated or deleted in the meantime.
    """
    if not token:
        return None
    secret = secret if secret is not None else _cookie_secret()
    if not secret:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    user_id_str, expiry_str, signature = parts
    message = f"{user_id_str}.{expiry_str}"
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    # Constant-time comparison — reject any tampered or forged signature.
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        expiry = int(expiry_str)
        user_id = int(user_id_str)
    except ValueError:
        return None
    now_ts = time.time() if now_ts is None else now_ts
    if expiry < now_ts:
        return None
    return user_id
