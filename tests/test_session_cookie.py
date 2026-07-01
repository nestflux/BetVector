"""Persistent-login signed session cookie — token integrity + wiring.

The token helpers (make/verify) are pure and unit-tested directly. The
Streamlit cookie integration in dashboard.py / password_change.py runs ``st.*``
at import time, so it is verified at SOURCE level (grep + compile) rather than
imported — the same pattern used for the other view tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.auth import (  # noqa: E402
    SESSION_COOKIE_NAME,
    _cookie_secret,
    make_session_token,
    verify_session_token,
)

SECRET = "unit-test-secret-key"
NOW = 1_700_000_000.0  # fixed reference instant so expiry tests are deterministic


# --------------------------------------------------------------- round-trip
def test_roundtrip_returns_user_id():
    tok = make_session_token(42, 7, secret=SECRET, now_ts=NOW)
    assert tok is not None
    assert verify_session_token(tok, secret=SECRET, now_ts=NOW) == 42


def test_token_shape_is_four_parts():
    # UM-06 added the session epoch: "<user_id>.<session_epoch>.<expiry>.<signature>".
    tok = make_session_token(1, 7, secret=SECRET, now_ts=NOW)
    assert tok.count(".") == 3


def test_distinct_users_distinct_tokens():
    a = make_session_token(1, 7, secret=SECRET, now_ts=NOW)
    b = make_session_token(2, 7, secret=SECRET, now_ts=NOW)
    assert a != b
    assert verify_session_token(a, secret=SECRET, now_ts=NOW) == 1
    assert verify_session_token(b, secret=SECRET, now_ts=NOW) == 2


# ----------------------------------------------- no secret => feature inert
def test_make_returns_none_with_empty_secret():
    assert make_session_token(1, 7, secret="", now_ts=NOW) is None


def test_verify_returns_none_with_empty_secret():
    tok = make_session_token(1, 7, secret=SECRET, now_ts=NOW)
    assert verify_session_token(tok, secret="", now_ts=NOW) is None


# --------------------------------------------------- tamper / forge rejection
def test_tampered_user_id_rejected():
    # Try to escalate to user 999 while keeping user 1's signature.
    tok = make_session_token(1, 7, secret=SECRET, now_ts=NOW)
    _uid, epoch, exp, sig = tok.split(".")   # UM-06: 4-part token
    forged = f"999.{epoch}.{exp}.{sig}"
    assert verify_session_token(forged, secret=SECRET, now_ts=NOW) is None


def test_tampered_signature_rejected():
    tok = make_session_token(1, 7, secret=SECRET, now_ts=NOW)
    uid, epoch, exp, sig = tok.split(".")   # UM-06: 4-part token
    assert verify_session_token(f"{uid}.{epoch}.{exp}.{'0' * len(sig)}",
                                secret=SECRET, now_ts=NOW) is None


def test_token_from_a_different_secret_rejected():
    tok = make_session_token(1, 7, secret=SECRET, now_ts=NOW)
    assert verify_session_token(tok, secret="another-secret", now_ts=NOW) is None


# ------------------------------------------------------------------- expiry
def test_expired_token_rejected():
    tok = make_session_token(1, 1, secret=SECRET, now_ts=NOW)   # valid for 1 day
    assert verify_session_token(tok, secret=SECRET, now_ts=NOW + 2 * 86400) is None


def test_token_valid_just_before_expiry():
    tok = make_session_token(1, 1, secret=SECRET, now_ts=NOW)
    assert verify_session_token(tok, secret=SECRET, now_ts=NOW + 86400 - 10) == 1


# ---------------------------------------------------------------- malformed
@pytest.mark.parametrize("bad", ["", None, "abc", "1.2", "1.2.3.4", "x.y.z", "1.notint.sig"])
def test_malformed_tokens_rejected(bad):
    assert verify_session_token(bad, secret=SECRET, now_ts=NOW) is None


# --------------------------------------------------- _cookie_secret resolution
def test_cookie_secret_reads_env(monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECRET", "from-env")
    assert _cookie_secret() == "from-env"


def test_cookie_secret_none_when_unset(monkeypatch):
    monkeypatch.delenv("SESSION_COOKIE_SECRET", raising=False)
    # With no env var and no Streamlit secrets file, the feature is disabled.
    assert _cookie_secret() is None


# ---------------------------------------- source-level wiring (st.* at import)
DASH = (ROOT / "src" / "delivery" / "dashboard.py").read_text()
PWC = (ROOT / "src" / "delivery" / "views" / "password_change.py").read_text()
REQ = (ROOT / "requirements.txt").read_text()
YAML = (ROOT / "config" / "settings.yaml").read_text()


def test_dashboard_wires_all_cookie_paths():
    assert "verify_session_token" in DASH and "make_session_token" in DASH
    assert "_rehydrate_from_cookie(jar)" in DASH          # rehydrate in the gate
    assert "persist_login_cookie(_cookie_jar()" in DASH   # set cookie on login
    assert "clear_login_cookie(_cookie_jar())" in DASH    # cookie expired in the deferred-logout handler
    assert "_pending_logout" in DASH                      # deferred-logout flag handled in the gate
    assert "_load_active_user" in DASH                    # DB re-validation on rehydrate
    compile(DASH, "dashboard.py", "exec")


def test_password_change_logout_defers_to_gate():
    # Logout defers to the gate (sets _pending_logout); the gate clears the
    # session and expires the cookie on a completing run so it actually deletes.
    assert "_pending_logout" in PWC
    compile(PWC, "password_change.py", "exec")


def test_dependency_and_config_present():
    assert "streamlit-cookies-controller" in REQ
    assert "session_cookie_days" in YAML
    assert SESSION_COOKIE_NAME == "bv_session"
