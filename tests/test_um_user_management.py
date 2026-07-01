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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.database.db as db_mod  # noqa: E402
import src.database.models  # noqa: E402,F401  (register core tables on Base)
import src.world_cup.models  # noqa: E402,F401  (register wc_* tables on Base)
from src.auth import (  # noqa: E402
    admin_reset_password, hash_password, record_login, verify_password,
)
from src.database.db import Base  # noqa: E402
from src.database.models import User  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    # Enforce foreign keys in SQLite (off by default) so the delete-order tests
    # genuinely exercise the FK constraints that fail on PostgreSQL/Neon — the exact
    # condition UM-03 fixes. Without this, SQLite would silently orphan child rows and
    # the test would pass even against the old, buggy delete.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

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


# ============================================================================
# UM-03 — Delete / Clear / Reset cover the WC bet-tracker tables (FK bug fix)
# ============================================================================
from src.delivery.views._user_ops import (  # noqa: E402
    clear_bet_history, delete_user, reset_everything,
)
from src.world_cup.models import (  # noqa: E402
    WCAccaLeg, WCAccumulator, WCBetLog, WCMatch, WCTeam,
)


def _seed_wc_match(db, mid=1):
    """A minimal WC match (+ its two teams) so WC bet rows satisfy the match FK."""
    with db() as s:
        if s.get(WCTeam, 1) is None:
            s.add(WCTeam(id=1, name="Alpha", fifa_code="ALP",
                         confederation="UEFA", group_letter="A"))
            s.add(WCTeam(id=2, name="Beta", fifa_code="BET",
                         confederation="UEFA", group_letter="A"))
        s.add(WCMatch(id=mid, date="2026-07-05", stage="round_of_32",
                      home_team_id=1, away_team_id=2, status="scheduled"))
        s.commit()


def _add_wc_bets(db, user_id, match_id=1):
    """Give a user one single WC bet + one 2-leg accumulator."""
    with db() as s:
        s.add(WCBetLog(user_id=user_id, match_id=match_id, market_type="1X2",
                       selection="home", odds=2.0, stake=10.0, status="pending"))
        acc = WCAccumulator(user_id=user_id, stake=5.0, combined_odds=4.0,
                            status="pending")
        s.add(acc)
        s.flush()
        s.add(WCAccaLeg(accumulator_id=acc.id, match_id=match_id,
                        market_type="1X2", selection="home", odds=2.0,
                        status="pending"))
        s.add(WCAccaLeg(accumulator_id=acc.id, match_id=match_id,
                        market_type="BTTS", selection="yes", odds=2.0,
                        status="pending"))
        s.commit()


def test_delete_user_removes_wc_bets_and_spares_others(db):
    _seed_wc_match(db)
    keep = _mk_user(db, name="Keep", email="keep@x.com")
    victim = _mk_user(db, name="Victim", email="victim@x.com")
    _add_wc_bets(db, keep)
    _add_wc_bets(db, victim)

    # With FK enforcement ON this is exactly the case that failed before UM-03.
    assert delete_user(victim) is True
    with db() as s:
        assert s.get(User, victim) is None
        # victim's WC rows all gone — no orphans
        assert s.query(WCBetLog).filter_by(user_id=victim).count() == 0
        assert s.query(WCAccumulator).filter_by(user_id=victim).count() == 0
        # only keep's two legs remain (victim's were removed with the accumulator)
        assert s.query(WCAccaLeg).count() == 2
        # keep is fully intact
        assert s.get(User, keep) is not None
        assert s.query(WCBetLog).filter_by(user_id=keep).count() == 1
        assert s.query(WCAccumulator).filter_by(user_id=keep).count() == 1


def test_clear_history_removes_wc_bets(db):
    _seed_wc_match(db)
    uid = _mk_user(db)
    _add_wc_bets(db, uid)
    n = clear_bet_history(uid)
    assert n == 2                                 # 1 single + 1 accumulator
    with db() as s:
        assert s.query(WCBetLog).filter_by(user_id=uid).count() == 0
        assert s.query(WCAccumulator).filter_by(user_id=uid).count() == 0
        assert s.query(WCAccaLeg).count() == 0    # legs went with the accumulator


def test_reset_everything_removes_wc_bets(db):
    _seed_wc_match(db)
    uid = _mk_user(db)
    _add_wc_bets(db, uid)
    assert reset_everything(uid) is True
    with db() as s:
        assert s.query(WCBetLog).filter_by(user_id=uid).count() == 0
        assert s.query(WCAccumulator).filter_by(user_id=uid).count() == 0
        assert s.query(WCAccaLeg).count() == 0


# ============================================================================
# UM-04 — Change user role
# ============================================================================
from src.delivery.views._user_ops import set_user_role  # noqa: E402


def test_set_role_promote_viewer_to_owner(db):
    uid = _mk_user(db, role="viewer")
    assert set_user_role(uid, "owner") is True
    with db() as s:
        assert s.get(User, uid).role == "owner"


def test_set_role_demote_owner_when_another_owner_exists(db):
    owner1 = _mk_user(db, name="O1", email="o1@x.com", role="owner")  # noqa: F841
    owner2 = _mk_user(db, name="O2", email="o2@x.com", role="owner")
    assert set_user_role(owner2, "viewer") is True                    # o1 still owner
    with db() as s:
        assert s.get(User, owner2).role == "viewer"


def test_set_role_blocks_last_owner_demotion(db):
    only_owner = _mk_user(db, name="Solo", email="solo@x.com", role="owner")
    _mk_user(db, name="V", email="v@x.com", role="viewer")            # viewers don't count
    assert set_user_role(only_owner, "viewer") is False              # refused
    with db() as s:
        assert s.get(User, only_owner).role == "owner"               # unchanged


def test_set_role_rejects_invalid_role(db):
    uid = _mk_user(db, role="viewer")
    assert set_user_role(uid, "superadmin") is False
    with db() as s:
        assert s.get(User, uid).role == "viewer"


def test_set_role_missing_user(db):
    assert set_user_role(99999, "owner") is False


def test_admin_view_wires_role_change():
    src = (ROOT / "src" / "delivery" / "views" / "admin.py").read_text()
    assert "set_user_role" in src and "Update role" in src
    compile(src, "admin.py", "exec")


# ============================================================================
# UM-05 — Last-login + never-logged-in visibility
# ============================================================================

def test_record_login_stamps_timestamp(db):
    uid = _mk_user(db)
    with db() as s:
        assert s.get(User, uid).last_login_at is None       # not signed in yet
    record_login(uid)
    with db() as s:
        stamped = s.get(User, uid).last_login_at
        assert stamped is not None and "T" in stamped       # ISO timestamp


def test_record_login_missing_user_is_noop(db):
    record_login(99999)                                     # must not raise


def test_new_user_reads_as_never_logged_in(db):
    # _mk_user gives a password but never logs in — exactly the never-logged-in
    # condition the admin table flags (has_password AND last_login_at is NULL).
    uid = _mk_user(db, password="secret123")
    with db() as s:
        u = s.get(User, uid)
        assert u.password_hash is not None and u.last_login_at is None


def test_admin_view_wires_last_login():
    src = (ROOT / "src" / "delivery" / "views" / "admin.py").read_text()
    assert "last_login_at" in src and "never_logged_in" in src
    assert "never logged in" in src
    compile(src, "admin.py", "exec")


def test_dashboard_records_login_on_every_entry_path():
    src = (ROOT / "src" / "delivery" / "dashboard.py").read_text()
    # credential login + cookie rehydrate + emergency owner fallback
    assert src.count("record_login(") >= 3


# ============================================================================
# UM-06 — Force logout / "sign out everywhere" (session epoch)
# ============================================================================
import hashlib as _hashlib  # noqa: E402
import hmac as _hmac  # noqa: E402

from src.auth import (  # noqa: E402
    bump_session_epoch, get_session_epoch, make_session_token,
    session_token_epoch, verify_session_token,
)

_SECRET = "unit-test-cookie-secret"


def test_token_roundtrip_with_epoch():
    tok = make_session_token(7, 7, secret=_SECRET, now_ts=1000.0, epoch=3)
    assert tok and tok.count(".") == 3                # uid.epoch.expiry.sig
    assert verify_session_token(tok, secret=_SECRET, now_ts=1000.0) == 7
    assert session_token_epoch(tok) == 3


def test_legacy_3part_token_still_verifies():
    # A token minted the OLD way (uid.expiry.sig) must still verify, as epoch 0,
    # so existing cookies keep working across the UM-06 deploy.
    expiry = 20000
    msg = f"5.{expiry}"
    sig = _hmac.new(_SECRET.encode(), msg.encode(), _hashlib.sha256).hexdigest()
    legacy = f"{msg}.{sig}"
    assert verify_session_token(legacy, secret=_SECRET, now_ts=1000.0) == 5
    assert session_token_epoch(legacy) == 0


def test_token_tamper_and_expiry_rejected():
    tok = make_session_token(7, 7, secret=_SECRET, now_ts=1000.0, epoch=1)
    assert verify_session_token(tok + "x", secret=_SECRET, now_ts=1000.0) is None   # tampered
    assert verify_session_token(tok, secret=_SECRET, now_ts=10**12) is None          # expired


def test_session_token_epoch_parses_safely():
    assert session_token_epoch(None) == 0
    assert session_token_epoch("garbage") == 0
    assert session_token_epoch("1.2.3.sig") == 2


def test_bump_and_get_session_epoch(db):
    uid = _mk_user(db)
    assert get_session_epoch(uid) == 0
    assert bump_session_epoch(uid) is True
    assert get_session_epoch(uid) == 1
    assert bump_session_epoch(uid) is True
    assert get_session_epoch(uid) == 2


def test_bump_session_epoch_missing_user(db):
    assert bump_session_epoch(99999) is False


def test_sign_out_everywhere_makes_old_token_stale(db):
    uid = _mk_user(db)
    tok = make_session_token(uid, 7, secret=_SECRET, now_ts=1000.0,
                             epoch=get_session_epoch(uid))
    # Before the bump: token is valid AND its epoch matches the user's current epoch,
    # so the rehydrate epoch-check passes.
    assert verify_session_token(tok, secret=_SECRET, now_ts=1000.0) == uid
    assert session_token_epoch(tok) == get_session_epoch(uid)      # 0 == 0
    # "Sign out everywhere" bumps the epoch. The token still passes integrity, but its
    # embedded epoch is now stale vs the user's — the dashboard rehydrate rejects it.
    bump_session_epoch(uid)
    assert session_token_epoch(tok) != get_session_epoch(uid)      # 0 != 1


def test_admin_view_wires_signout():
    src = (ROOT / "src" / "delivery" / "views" / "admin.py").read_text()
    assert "bump_session_epoch" in src and "Sign out everywhere" in src
    compile(src, "admin.py", "exec")


def test_dashboard_wires_epoch_check():
    src = (ROOT / "src" / "delivery" / "dashboard.py").read_text()
    assert "session_token_epoch(token)" in src and "get_session_epoch(" in src
