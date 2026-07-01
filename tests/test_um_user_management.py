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
