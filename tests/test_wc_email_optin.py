"""WC-EMAIL — opt-in multi-user World Cup emails.

The WC digest is opt-IN: notify_wc defaults to 0 (off), users enable it in Settings,
and the WC pipeline emails only the opted-in users. Tests cover the default, the
recipient query, the dispatcher loop (per-user isolation), and the source-level wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.db import Base
from src.database.models import User
import src.world_cup.alerts as alerts

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, expire_on_commit=False)()
    yield sess
    sess.close()


def _user(session, **kw):
    u = User(name=kw.pop("name", "u"), **kw)
    session.add(u)
    session.commit()
    session.refresh(u)   # populate server-side defaults (notify_wc)
    return u


def test_notify_wc_defaults_off():
    # A brand-new user is unsubscribed from the WC digest by default.
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    u = _user(s, email="a@b.c")
    assert u.notify_wc == 0
    s.close()


def test_notifiable_user_ids_only_opted_in_active_with_email(session):
    opted_in = _user(session, name="in", email="in@x.com", is_active=1, notify_wc=1)
    _user(session, name="off", email="off@x.com", is_active=1, notify_wc=0)        # not opted in
    _user(session, name="inactive", email="ix@x.com", is_active=0, notify_wc=1)    # inactive
    _user(session, name="noemail", email=None, is_active=1, notify_wc=1)           # no email
    _user(session, name="blank", email="", is_active=1, notify_wc=1)               # blank email

    ids = alerts._wc_notifiable_user_ids(session=session)
    assert ids == [opted_in.id]


def test_morning_dispatcher_loops_and_isolates_failures(monkeypatch):
    monkeypatch.setattr(alerts, "_wc_notifiable_user_ids", lambda: [1, 2, 3])
    seen = []

    def fake_send(uid, target_date=None):
        seen.append(uid)
        if uid == 2:
            raise RuntimeError("smtp down")   # one user's send blows up
        return True

    monkeypatch.setattr(alerts, "send_wc_morning_email", fake_send)
    sent = alerts.send_wc_morning_email_to_all()
    assert seen == [1, 2, 3]      # every user attempted despite #2 raising
    assert sent == 2              # 1 and 3 succeeded; failure isolated


def test_evening_dispatcher_counts_only_real_sends(monkeypatch):
    monkeypatch.setattr(alerts, "_wc_notifiable_user_ids", lambda: [7, 8])
    # send returns False (e.g. no finished matches) → not counted as sent
    monkeypatch.setattr(alerts, "send_wc_evening_email", lambda uid, target_date=None: False)
    assert alerts.send_wc_evening_email_to_all() == 0


def test_no_opted_in_users_sends_nothing(monkeypatch):
    monkeypatch.setattr(alerts, "_wc_notifiable_user_ids", lambda: [])
    calls = []
    monkeypatch.setattr(alerts, "send_wc_morning_email",
                        lambda uid, target_date=None: calls.append(uid))
    assert alerts.send_wc_morning_email_to_all() == 0 and calls == []


# --- source-level wiring -----------------------------------------------------

def test_wc_pipeline_uses_the_multiuser_dispatchers():
    src = (ROOT / "src" / "world_cup" / "pipeline.py").read_text()
    assert "send_wc_morning_email_to_all" in src
    assert "send_wc_evening_email_to_all" in src


def test_migration_registered_for_notify_wc():
    db_src = (ROOT / "src" / "database" / "db.py").read_text()
    assert '"users", "notify_wc"' in db_src
    assert "DEFAULT 0" in db_src        # existing users start unsubscribed


def test_settings_exposes_and_persists_the_toggle():
    src = (ROOT / "src" / "delivery" / "views" / "settings.py").read_text()
    assert '"notify_wc": user.notify_wc' in src            # surfaced in load_current_user
    assert 'save_user_setting(user_data["id"], "notify_wc"' in src   # persisted on change
    assert "World Cup Digest" in src


# --- all email types opt-in (default off) ------------------------------------

def test_all_notification_flags_default_off(session):
    # A brand-new user is unsubscribed from EVERY email type by default.
    u = _user(session, email="new@x.com")
    assert (u.notify_morning, u.notify_evening, u.notify_weekly, u.notify_wc) == (0, 0, 0, 0)


def test_settings_league_toggles_are_functional_and_opt_in():
    src = (ROOT / "src" / "delivery" / "views" / "settings.py").read_text()
    # load_current_user surfaces all four flags so the toggles can reflect state
    for f in ("notify_morning", "notify_evening", "notify_weekly", "notify_wc"):
        assert f'"{f}": user.{f}' in src
    # each league toggle now PERSISTS (functional), not a hardcoded placeholder
    for f in ("notify_morning", "notify_evening", "notify_weekly"):
        assert f'"{f}", 1 if' in src
    assert 'value=True,\n            key="notif_morning"' not in src   # placeholder gone


def test_onboarding_notification_toggles_default_off():
    src = (ROOT / "src" / "delivery" / "views" / "onboarding.py").read_text()
    for key in ("ob_notif_morning", "ob_notif_evening", "ob_notif_weekly"):
        idx = src.index(f'key="{key}"')
        assert "value=False" in src[idx - 120:idx], f"{key} should default off"
    assert 'st.session_state.get("ob_notif_morning", False)' in src
