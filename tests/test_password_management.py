"""Invite hardening — password management & forced first-login change.

Covers the (a)+(b) work:
  (a) every owner-driven account-creation path produces a *usable* login
      (no NULL-password dead accounts) and forces a first-login change;
  (b) self-service password change + the auth primitives behind both the
      forced screen and the Settings change form.

DB-touching tests patch ``db._engine`` / ``db._SessionFactory`` to an in-memory
SQLite engine (the same pattern as test_e34_integration.py); the pure auth
helpers and the view/dashboard wiring are checked directly / via source+AST.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.database.db as db_mod  # noqa: E402
from src import auth  # noqa: E402
from src.auth import (  # noqa: E402
    MIN_PASSWORD_LENGTH,
    _TEMP_PW_ALPHABET,
    change_own_password,
    generate_temp_password,
    hash_password,
    set_user_password,
    user_must_change_password,
    validate_new_password,
    verify_password,
)
from src.database.db import Base  # noqa: E402
from src.database.models import User  # noqa: E402


# ============================================================================
# Fixtures — in-memory DB patched into the db module globals
# ============================================================================

@pytest.fixture
def patched_db():
    """Yield a sessionmaker bound to a fresh in-memory SQLite DB and route the
    db module's ``get_session()`` / ``get_engine()`` at it for the test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    orig_engine, orig_factory = db_mod._engine, db_mod._SessionFactory
    db_mod._engine, db_mod._SessionFactory = engine, Session
    try:
        yield Session
    finally:
        db_mod._engine, db_mod._SessionFactory = orig_engine, orig_factory


def _make_user(Session, **kw):
    """Insert a user with sensible defaults; return its id."""
    fields = dict(name="Tester", email="tester@example.com", role="viewer")
    fields.update(kw)
    with Session() as s:
        u = User(**fields)
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


# ============================================================================
# generate_temp_password
# ============================================================================

def test_generate_temp_password_composition_and_alphabet():
    pw = generate_temp_password()
    assert len(pw) >= 12
    assert all(c in _TEMP_PW_ALPHABET for c in pw), "only safe alphabet chars"
    assert any(c.isalpha() for c in pw), "must contain a letter"
    assert any(c.isdigit() for c in pw), "must contain a digit"
    # Unambiguous alphabet excludes the confusable characters.
    assert not any(c in pw for c in "0O1lI"), "no ambiguous characters"


def test_generate_temp_password_clamps_to_minimum():
    assert len(generate_temp_password(3)) == MIN_PASSWORD_LENGTH


def test_generate_temp_password_is_random():
    assert generate_temp_password() != generate_temp_password()


# ============================================================================
# validate_new_password (pure)
# ============================================================================

def test_validate_rejects_empty_and_short():
    assert validate_new_password("", "")[0] is False
    assert validate_new_password("short", "short")[0] is False  # < 8 chars


def test_validate_rejects_mismatch():
    ok, msg = validate_new_password("abcd1234", "abcd9999")
    assert ok is False and "match" in msg.lower()


def test_validate_blocks_reuse_of_current():
    h = hash_password("abcd1234")
    ok, msg = validate_new_password("abcd1234", "abcd1234", current_hash=h)
    assert ok is False and "different" in msg.lower()


def test_validate_accepts_good_password():
    ok, msg = validate_new_password("abcd1234", "abcd1234")
    assert ok is True and msg == ""
    # A different password is fine even when a current hash is supplied.
    h = hash_password("oldpass12")
    assert validate_new_password("newpass34", "newpass34", current_hash=h)[0] is True


# ============================================================================
# user_must_change_password (pure predicate)
# ============================================================================

def test_user_must_change_password_predicate():
    from types import SimpleNamespace
    assert user_must_change_password(SimpleNamespace(must_change_password=1)) is True
    assert user_must_change_password(SimpleNamespace(must_change_password=0)) is False
    # Missing attribute must NOT trap the user.
    assert user_must_change_password(SimpleNamespace()) is False


# ============================================================================
# Column default
# ============================================================================

def test_new_user_defaults_to_no_forced_change(patched_db):
    uid = _make_user(patched_db, email="default@example.com")
    with patched_db() as s:
        assert s.get(User, uid).must_change_password == 0


# ============================================================================
# set_user_password
# ============================================================================

def test_set_user_password_sets_hash_and_clears_flag(patched_db):
    uid = _make_user(
        patched_db, email="setpw@example.com",
        password_hash=hash_password("temp1234"), must_change_password=1,
    )
    assert set_user_password(uid, "brandnew12") is True
    with patched_db() as s:
        u = s.get(User, uid)
        assert verify_password("brandnew12", u.password_hash) is True
        assert u.must_change_password == 0


def test_set_user_password_missing_user_returns_false(patched_db):
    assert set_user_password(99999, "whatever12") is False


# ============================================================================
# change_own_password
# ============================================================================

def test_change_own_password_wrong_current_rejected(patched_db):
    uid = _make_user(
        patched_db, email="cur@example.com",
        password_hash=hash_password("rightpass"),
    )
    ok, msg = change_own_password(uid, "wrongpass", "newpass12", "newpass12")
    assert ok is False and "incorrect" in msg.lower()


def test_change_own_password_success_clears_flag(patched_db):
    uid = _make_user(
        patched_db, email="ok@example.com",
        password_hash=hash_password("rightpass"), must_change_password=1,
    )
    ok, _ = change_own_password(uid, "rightpass", "newpass12", "newpass12")
    assert ok is True
    with patched_db() as s:
        u = s.get(User, uid)
        assert verify_password("newpass12", u.password_hash) is True
        assert u.must_change_password == 0


def test_change_own_password_null_hash_allows_first_set(patched_db):
    """An account with no password yet (emergency-owner case) can set one
    without supplying a current password."""
    uid = _make_user(patched_db, email="null@example.com", password_hash=None)
    ok, _ = change_own_password(uid, "", "firstpass1", "firstpass1")
    assert ok is True
    with patched_db() as s:
        assert verify_password("firstpass1", s.get(User, uid).password_hash) is True


def test_change_own_password_blocks_reuse(patched_db):
    uid = _make_user(
        patched_db, email="reuse@example.com",
        password_hash=hash_password("samepass1"),
    )
    ok, msg = change_own_password(uid, "samepass1", "samepass1", "samepass1")
    assert ok is False and "different" in msg.lower()


def test_change_own_password_mismatch_rejected(patched_db):
    uid = _make_user(
        patched_db, email="mm@example.com",
        password_hash=hash_password("rightpass"),
    )
    ok, msg = change_own_password(uid, "rightpass", "newpass12", "nope")
    assert ok is False and "match" in msg.lower()


# ============================================================================
# Account creation paths — no dead accounts, forced change
# ============================================================================

def test_create_user_with_password_forces_first_login_change(patched_db):
    from src.delivery.views.admin import create_user_with_password
    uid = create_user_with_password(
        name="Admin Made", email="ADMIN@made.com", password="adminpass1",
        role="viewer",
    )
    assert uid is not None
    with patched_db() as s:
        u = s.get(User, uid)
        assert u.must_change_password == 1
        assert verify_password("adminpass1", u.password_hash) is True


def test_create_viewer_user_is_loginable_not_a_dead_account(patched_db):
    from src.delivery.views.settings import create_viewer_user
    result = create_viewer_user("Jane Doe", "Jane@Example.com")
    assert result is not None, "invite must succeed"
    uid, temp_pw = result
    assert isinstance(uid, int)
    assert len(temp_pw) >= MIN_PASSWORD_LENGTH
    with patched_db() as s:
        u = s.get(User, uid)
        # The whole point of the fix: a real, usable password hash (not NULL).
        assert u.password_hash is not None
        assert verify_password(temp_pw, u.password_hash) is True
        assert u.must_change_password == 1
        assert u.has_onboarded == 0
        assert u.role == "viewer"
        assert u.email == "jane@example.com"  # normalised


# ============================================================================
# Schema migration
# ============================================================================

def test_migration_adds_must_change_password_column():
    engine = create_engine("sqlite:///:memory:")
    # Minimal pre-migration schema (the tables the migration list touches). In real
    # init_db, create_all builds these before _apply_schema_migrations runs.
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"))
        c.execute(text("CREATE TABLE wc_lineups (id INTEGER PRIMARY KEY)"))
        c.execute(text("CREATE TABLE wc_matches (id INTEGER PRIMARY KEY)"))  # WC-ACC-02
    db_mod._apply_schema_migrations(engine)
    cols = [col["name"] for col in inspect(engine).get_columns("users")]
    assert "must_change_password" in cols
    # Idempotent: a second run must not raise (column already present).
    db_mod._apply_schema_migrations(engine)


# ============================================================================
# View + dashboard wiring (source / AST — views render st.* at import)
# ============================================================================

def test_forced_password_change_view_structure():
    src = (ROOT / "src" / "delivery" / "views" / "password_change.py").read_text()
    tree = ast.parse(src)
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "render_forced_password_change" in funcs
    assert "_load_user_credentials" in funcs
    # The user-supplied display name must be escaped before going into markup.
    assert "html.escape" in src
    # The screen must block reuse of the temp password (passes current_hash).
    assert "current_hash" in src
    # Module compiles.
    compile(src, "password_change.py", "exec")


def test_dashboard_gate_runs_before_onboarding():
    src = (ROOT / "src" / "delivery" / "dashboard.py").read_text()
    assert "def needs_password_change" in src
    assert "render_forced_password_change" in src
    # The forced-change gate statement must appear BEFORE the onboarding gate
    # statement in main() so the password is set first.
    assert "if needs_password_change():" in src
    assert "if not check_onboarding():" in src
    assert src.index("if needs_password_change():") < src.index("if not check_onboarding():"), \
        "password gate must run before onboarding gate"
