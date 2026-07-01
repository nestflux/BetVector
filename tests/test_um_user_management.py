"""UM — User Management Hardening.

Owner-side account-management utilities exercised over an in-memory DB: admin
password reset (UM-01), profile edit (UM-02), delete/clear covering the WC
bet-tracker tables (UM-03), role change (UM-04), last-login visibility (UM-05),
force-logout (UM-06), and feedback capture (UM-07). Each block is grouped by issue.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.database.db as db_mod  # noqa: E402
import src.database.models  # noqa: E402,F401  (register core tables on Base)
import src.world_cup.models  # noqa: E402,F401  (register wc_* tables on Base)
from src.auth import (  # noqa: E402
    admin_reset_password, hash_password, verify_password,
)
from src.database.db import Base  # noqa: E402
from src.database.models import User  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    orig_e, orig_f = db_mod._engine, db_mod._SessionFactory
    db_mod._engine, db_mod._SessionFactory = engine, Session
    try:
        yield Session
    finally:
        db_mod._engine, db_mod._SessionFactory = orig_e, orig_f


def _mk_user(db, name="Tester", email="tester@example.com", role="viewer",
             password="oldpass123", must_change=0, is_active=1):
    """Insert one user and return its id."""
    with db() as s:
        u = User(
            name=name, email=email, role=role,
            password_hash=hash_password(password) if password else None,
            must_change_password=must_change, is_active=is_active,
            starting_bankroll=500.0, current_bankroll=500.0,
            staking_method="flat", stake_percentage=0.02,
            kelly_fraction=0.25, edge_threshold=0.05, has_onboarded=1,
            created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00",
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


# ============================================================================
# UM-01 — Admin password reset
# ============================================================================

def test_admin_reset_password_returns_temp_and_forces_change(db):
    uid = _mk_user(db, password="oldpass123", must_change=0)
    temp = admin_reset_password(uid)
    assert temp and len(temp) >= 8               # a real temp password came back
    with db() as s:
        u = s.get(User, uid)
        assert u.must_change_password == 1        # re-armed: tester must change it
        assert verify_password(temp, u.password_hash)          # the new temp works
        assert not verify_password("oldpass123", u.password_hash)  # old invalidated


def test_admin_reset_password_arms_change_even_if_previously_clear(db):
    uid = _mk_user(db, must_change=0)
    assert admin_reset_password(uid)
    with db() as s:
        assert s.get(User, uid).must_change_password == 1


def test_admin_reset_password_unique_each_time(db):
    uid = _mk_user(db)
    a = admin_reset_password(uid)
    b = admin_reset_password(uid)
    assert a and b and a != b                    # fresh secret every reset


def test_admin_reset_password_missing_user(db):
    assert admin_reset_password(99999) is None


def test_admin_view_wires_password_reset():
    src = (ROOT / "src" / "delivery" / "views" / "admin.py").read_text()
    assert "admin_reset_password" in src
    assert "if not is_self:" in src              # your own account is excluded
    assert "st.code(temp_pw" in src              # one-time display of the temp password
    compile(src, "admin.py", "exec")


# ============================================================================
# UM-02 — Edit name & email
# ============================================================================
from src.delivery.views._user_ops import update_user_profile  # noqa: E402


def test_update_profile_rename(db):
    uid = _mk_user(db, name="Old Name")
    ok, _ = update_user_profile(uid, name="New Name")
    assert ok
    with db() as s:
        assert s.get(User, uid).name == "New Name"


def test_update_profile_email_lowercased(db):
    uid = _mk_user(db, email="old@example.com")
    ok, _ = update_user_profile(uid, email="  New@Example.COM ")
    assert ok
    with db() as s:
        assert s.get(User, uid).email == "new@example.com"     # trimmed + lowered


def test_update_profile_rejects_duplicate_email(db):
    a = _mk_user(db, name="A", email="a@example.com")          # noqa: F841
    b = _mk_user(db, name="B", email="b@example.com")
    ok, msg = update_user_profile(b, email="a@example.com")     # collides with A
    assert not ok and "already used" in msg.lower()
    with db() as s:
        assert s.get(User, b).email == "b@example.com"          # unchanged


def test_update_profile_rejects_invalid_email(db):
    uid = _mk_user(db, email="good@example.com")
    ok, msg = update_user_profile(uid, email="notanemail")
    assert not ok and "valid email" in msg.lower()
    with db() as s:
        assert s.get(User, uid).email == "good@example.com"     # unchanged


def test_update_profile_rejects_empty_name(db):
    uid = _mk_user(db, name="Keep")
    ok, msg = update_user_profile(uid, name="   ")
    assert not ok and "empty" in msg.lower()
    with db() as s:
        assert s.get(User, uid).name == "Keep"


def test_update_profile_partial_name_only_keeps_email(db):
    uid = _mk_user(db, name="A", email="keep@example.com")
    ok, _ = update_user_profile(uid, name="B")                 # email not passed
    assert ok
    with db() as s:
        u = s.get(User, uid)
        assert u.name == "B" and u.email == "keep@example.com"


def test_update_profile_missing_user(db):
    ok, msg = update_user_profile(99999, name="X")
    assert not ok and "not found" in msg.lower()


def test_admin_view_wires_profile_edit():
    src = (ROOT / "src" / "delivery" / "views" / "admin.py").read_text()
    assert "update_user_profile" in src and "Save profile" in src
    compile(src, "admin.py", "exec")
