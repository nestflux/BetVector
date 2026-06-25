"""Hard-delete a viewer account + its bets; owner accounts protected.

delete_user is destructive and irreversible (unlike deactivate). It must remove
the user's bet_log rows (NOT NULL FK) and the user atomically, refuse owners,
and never touch another user's bets.
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
from src.database.db import Base  # noqa: E402
from src.database.models import BetLog, User  # noqa: E402
from src.delivery.views._user_ops import delete_user  # noqa: E402


@pytest.fixture
def patched_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    orig_e, orig_f = db_mod._engine, db_mod._SessionFactory
    db_mod._engine, db_mod._SessionFactory = engine, Session
    try:
        yield Session
    finally:
        db_mod._engine, db_mod._SessionFactory = orig_e, orig_f


def _mk_user(Session, role="viewer", email="v@example.com"):
    with Session() as s:
        u = User(name="Tester", email=email, role=role)
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


def _mk_bet(Session, user_id):
    with Session() as s:
        s.add(BetLog(
            user_id=user_id, match_id=1, date="2026-01-01", league="EPL",
            home_team="A", away_team="B", market_type="1X2", selection="Home",
            model_prob=0.5, bookmaker="Pinnacle", odds_at_detection=2.0,
            implied_prob=0.5, edge=0.05, stake=10.0, stake_method="flat",
            bet_type="user_placed", status="pending",
        ))
        s.commit()


def test_delete_viewer_removes_user_and_their_bets(patched_db):
    uid = _mk_user(patched_db, role="viewer")
    _mk_bet(patched_db, uid)
    _mk_bet(patched_db, uid)
    assert delete_user(uid) is True
    with patched_db() as s:
        assert s.get(User, uid) is None
        assert s.query(BetLog).filter(BetLog.user_id == uid).count() == 0


def test_delete_refuses_owner(patched_db):
    oid = _mk_user(patched_db, role="owner", email="owner@example.com")
    assert delete_user(oid) is False
    with patched_db() as s:
        assert s.get(User, oid) is not None  # owner left intact


def test_delete_missing_user_returns_false(patched_db):
    assert delete_user(99999) is False


def test_delete_does_not_touch_other_users_bets(patched_db):
    a = _mk_user(patched_db, email="a@example.com")
    b = _mk_user(patched_db, email="b@example.com")
    _mk_bet(patched_db, a)
    _mk_bet(patched_db, b)
    assert delete_user(a) is True
    with patched_db() as s:
        assert s.query(BetLog).filter(BetLog.user_id == a).count() == 0
        assert s.query(BetLog).filter(BetLog.user_id == b).count() == 1  # untouched
        assert s.get(User, b) is not None


# -- admin.py UI wiring + the form-reset fix (source-level; page runs st.* at import)

ADMIN_SRC = (ROOT / "src" / "delivery" / "views" / "admin.py").read_text()


def test_admin_wires_delete_and_form_resets():
    assert "delete_user" in ADMIN_SRC                 # imported + called
    assert "🗑️ Delete User" in ADMIN_SRC              # the delete button
    assert "admin_confirm_del_" in ADMIN_SRC          # two-step confirm checkbox
    assert 'u["role"] == "owner"' in ADMIN_SRC        # owner-protection guard in UI
    assert "clear_on_submit=True" in ADMIN_SRC        # create-form reset fix
    compile(ADMIN_SRC, "admin.py", "exec")
