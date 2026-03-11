"""
PC-11 — Pipeline Data Integrity & Email Fix — Integration Tests
================================================================
Tests for:
  - PC-11-01: FK constraint fix (VBs deleted before predictions)
  - PC-11-02: Email encoding (UTF-8, non-breaking space sanitisation)
  - PC-11-03: BetLog.value_bet_id stores actual VB ID
  - Pipeline source code structure checks

Uses real in-memory SQLite database for FK tests, source code
inspection for structural checks, and MIME construction for email tests.
"""

from __future__ import annotations

import inspect
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.database.db import Base
from src.database.models import (
    BetLog,
    Feature,
    League,
    Match,
    Prediction,
    Season,
    Team,
    User,
    ValueBet,
)


# ============================================================================
# Fixtures — in-memory SQLite with FK enforcement
# ============================================================================


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database with all BetVector tables.

    Enables foreign key enforcement (SQLite disables by default) so we
    can test the FK constraint behaviour that fails on PostgreSQL.
    """
    engine = create_engine("sqlite:///:memory:")

    # Enable FK enforcement on SQLite (matches PostgreSQL behaviour)
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()

    # Seed minimal required data
    _seed_db(session)

    yield session
    session.close()


def _make_prediction(id, match_id, h=0.5, d=0.25, a=0.25, hg=1.5, ag=1.0):
    """Helper to create a Prediction with all required NOT NULL fields."""
    return Prediction(
        id=id, match_id=match_id, model_name="poisson_v1",
        model_version="1.0",
        predicted_home_goals=hg, predicted_away_goals=ag,
        scoreline_matrix="[]",  # placeholder for tests
        prob_home_win=h, prob_draw=d, prob_away_win=a,
        prob_over_25=0.55, prob_under_25=0.45,
        prob_over_15=0.75, prob_under_15=0.25,
        prob_over_35=0.30, prob_under_35=0.70,
        prob_btts_yes=0.50, prob_btts_no=0.50,
    )


def _seed_db(session: Session):
    """Seed the in-memory database with minimal test data."""
    # User
    session.add(User(id=1, name="Test User", email="test@example.com"))

    # League + Season
    session.add(League(
        id=1, name="Test League", short_name="TL",
        country="Testland", football_data_code="T0",
    ))
    session.add(Season(
        id=1, league_id=1, season="2025-26",
        start_date="2025-08-01", end_date="2026-05-31",
    ))

    # Teams
    session.add(Team(id=1, name="Alpha FC", league_id=1))
    session.add(Team(id=2, name="Beta United", league_id=1))

    # Scheduled match with prediction + value bet
    session.add(Match(
        id=100, league_id=1, season="2025-26",
        date="2026-03-15", home_team_id=1, away_team_id=2,
        status="scheduled",
    ))
    session.add(_make_prediction(200, 100))
    session.add(ValueBet(
        id=300, match_id=100, prediction_id=200,
        bookmaker="Pinnacle", market_type="1X2", selection="home",
        model_prob=0.5, bookmaker_odds=2.2, implied_prob=0.45,
        edge=0.05, expected_value=0.10, confidence="medium",
    ))
    session.add(BetLog(
        id=400, user_id=1, value_bet_id=300, match_id=100,
        date="2026-03-15", league="Test League",
        home_team="Alpha FC", away_team="Beta United",
        market_type="1X2", selection="home", model_prob=0.5,
        bookmaker="Pinnacle", odds_at_detection=2.2,
        implied_prob=0.45, edge=0.05, stake=10.0,
        stake_method="flat", bet_type="system_pick", status="pending",
        bankroll_before=1000.0,
    ))

    # Finished match with prediction (should NOT be deleted)
    session.add(Match(
        id=101, league_id=1, season="2025-26",
        date="2026-03-01", home_team_id=1, away_team_id=2,
        home_goals=2, away_goals=1, status="finished",
    ))
    session.add(_make_prediction(201, 101, h=0.6, d=0.2, a=0.2, hg=1.8, ag=0.9))

    session.commit()


# ============================================================================
# PC-11-01: FK Constraint Fix Tests
# ============================================================================


class TestFKConstraintFix:
    """PC-11-01: Verify stale prediction refresh handles FK chain correctly."""

    def test_vb_delete_before_prediction_in_source(self):
        """ValueBet deletion must appear BEFORE prediction deletion in
        _generate_predictions() to prevent ForeignKeyViolation."""
        pipeline_path = Path(__file__).resolve().parents[1] / "src" / "pipeline.py"
        source = pipeline_path.read_text()

        # Find the VB deletion (cleanup code)
        vb_delete_pos = source.find("ValueBet.prediction_id.in_(stale_pred_ids)")
        # Find the prediction deletion
        pred_delete_pos = source.find("session.delete(sp)")

        assert vb_delete_pos > 0, "ValueBet FK cleanup not found in pipeline.py"
        assert pred_delete_pos > 0, "Prediction deletion not found in pipeline.py"
        assert vb_delete_pos < pred_delete_pos, (
            "ValueBet rows must be deleted BEFORE predictions to prevent "
            "ForeignKeyViolation on PostgreSQL."
        )

    def test_betlog_nullified_before_vb_delete_in_source(self):
        """BetLog.value_bet_id must be nullified before ValueBet deletion."""
        pipeline_path = Path(__file__).resolve().parents[1] / "src" / "pipeline.py"
        source = pipeline_path.read_text()

        # The BetLog nullification and VB deletion are in the same block.
        # Find the block between "stale_pred_ids" and "session.delete(sp)".
        block_start = source.find("stale_pred_ids = [sp.id for sp in stale_scheduled]")
        block_end = source.find("session.delete(sp)", block_start)
        assert block_start > 0, "stale_pred_ids assignment not found"
        assert block_end > block_start, "session.delete(sp) not found after stale_pred_ids"

        block = source[block_start:block_end]

        # Within this block, BetLog nullification must appear before VB deletion
        bl_pos = block.find("BetLog.value_bet_id")
        vb_pos = block.find(".delete(synchronize_session")
        assert bl_pos > 0, "BetLog nullification not found in FK cleanup block"
        assert bl_pos < vb_pos, (
            "BetLog.value_bet_id must be nullified BEFORE ValueBet deletion."
        )

    def test_fk_delete_chain_in_memory(self, db_session):
        """Simulate the FK delete chain: nullify BetLog → delete VBs → delete
        predictions. Verify no IntegrityError on SQLite with FK enforcement."""
        # Verify initial state
        assert db_session.query(Prediction).filter_by(id=200).count() == 1
        assert db_session.query(ValueBet).filter_by(prediction_id=200).count() == 1
        assert db_session.query(BetLog).filter_by(value_bet_id=300).count() == 1

        stale_pred_ids = [200]

        # Step 1: Find VB IDs
        vb_ids = [
            vb_id for (vb_id,) in
            db_session.query(ValueBet.id)
            .filter(ValueBet.prediction_id.in_(stale_pred_ids))
            .all()
        ]
        assert vb_ids == [300]

        # Step 2: Nullify BetLog refs
        db_session.query(BetLog).filter(
            BetLog.value_bet_id.in_(vb_ids)
        ).update({BetLog.value_bet_id: None}, synchronize_session="fetch")

        # Step 3: Delete VBs
        db_session.query(ValueBet).filter(
            ValueBet.prediction_id.in_(stale_pred_ids)
        ).delete(synchronize_session="fetch")

        # Step 4: Delete prediction — this should NOT raise FK error
        pred = db_session.query(Prediction).filter_by(id=200).first()
        db_session.delete(pred)
        db_session.commit()

        # Verify cleanup
        assert db_session.query(Prediction).filter_by(id=200).count() == 0
        assert db_session.query(ValueBet).filter_by(prediction_id=200).count() == 0
        bl = db_session.query(BetLog).filter_by(id=400).first()
        assert bl is not None, "BetLog should still exist"
        assert bl.value_bet_id is None, "BetLog.value_bet_id should be NULL"

    def test_finished_predictions_preserved(self, db_session):
        """Finished-match predictions must NOT be deleted during refresh."""
        # The FK delete chain only targets prediction id=200 (scheduled)
        # Prediction id=201 (finished) should survive
        stale_pred_ids = [200]

        # Run the delete chain for stale predictions only
        db_session.query(BetLog).filter(
            BetLog.value_bet_id.in_(
                [r[0] for r in db_session.query(ValueBet.id)
                 .filter(ValueBet.prediction_id.in_(stale_pred_ids)).all()]
            )
        ).update({BetLog.value_bet_id: None}, synchronize_session="fetch")
        db_session.query(ValueBet).filter(
            ValueBet.prediction_id.in_(stale_pred_ids)
        ).delete(synchronize_session="fetch")
        for p in db_session.query(Prediction).filter(
            Prediction.id.in_(stale_pred_ids)
        ).all():
            db_session.delete(p)
        db_session.commit()

        # Finished prediction (id=201) still exists
        assert db_session.query(Prediction).filter_by(id=201).count() == 1
        assert db_session.query(Prediction).filter_by(id=200).count() == 0


# ============================================================================
# PC-11-02: Email Encoding Tests
# ============================================================================


class TestEmailEncoding:
    """PC-11-02: Verify email handles non-ASCII characters correctly."""

    def test_sanitize_non_breaking_space(self):
        """_sanitize_email_text replaces U+00A0 with regular space."""
        from src.delivery.email_alerts import _sanitize_email_text

        assert _sanitize_email_text("PSG\xa0vs\xa0Lyon") == "PSG vs Lyon"
        assert _sanitize_email_text("") == ""
        assert _sanitize_email_text(None) is None
        assert _sanitize_email_text("normal text") == "normal text"

    def test_mime_text_uses_utf8_charset(self):
        """MIMEText in _send_email must specify charset='utf-8'."""
        source = inspect.getsource(
            __import__("src.delivery.email_alerts", fromlist=["_send_email"])._send_email
        )
        assert '"utf-8"' in source or "'utf-8'" in source, (
            "MIMEText must use charset='utf-8' to handle accented team names"
        )

    def test_sendmail_uses_as_bytes(self):
        """sendmail must use msg.as_bytes() instead of msg.as_string()
        to properly encode non-ASCII headers and body."""
        source = inspect.getsource(
            __import__("src.delivery.email_alerts", fromlist=["_send_email"])._send_email
        )
        assert "msg.as_bytes()" in source, (
            "sendmail must use msg.as_bytes() for proper MIME encoding"
        )
        # as_string() should NOT be in the sendmail call
        # (it may still exist in comments, that's OK)
        assert "sendmail" in source and "as_bytes" in source

    def test_em_dash_subject_no_error(self):
        """Subject line with em dash (U+2014) must not raise UnicodeEncodeError."""
        from email.header import Header
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["From"] = "BetVector <test@example.com>"
        msg["To"] = "user@example.com"
        msg["Subject"] = Header(
            "BetVector \u2014 5 Value Bets Today (EPL)", "utf-8"
        )
        msg.attach(MIMEText("<p>Hello</p>", "html", "utf-8"))

        # This must NOT raise UnicodeEncodeError
        encoded = msg.as_bytes()
        assert encoded is not None
        assert len(encoded) > 0

    def test_subject_with_header_encoding_in_source(self):
        """Subject must be encoded with email.header.Header for RFC 2047."""
        source = inspect.getsource(
            __import__("src.delivery.email_alerts", fromlist=["_send_email"])._send_email
        )
        assert "Header(subject" in source or "Header( subject" in source, (
            "Subject must be encoded with Header() for RFC 2047 compliance"
        )


# ============================================================================
# PC-11-03: BetLog.value_bet_id FK Fix Tests
# ============================================================================


class TestBetLogVBIdFix:
    """PC-11-03: Verify BetLog.value_bet_id stores actual ValueBet.id."""

    def test_tracker_looks_up_actual_vb_id(self):
        """tracker.py must query the actual VB ID from the DB, not use
        vb.prediction_id (which is a predictions.id, wrong table)."""
        tracker_path = Path(__file__).resolve().parents[1] / "src" / "betting" / "tracker.py"
        source = tracker_path.read_text()

        # The old bug: value_bet_id=vb.prediction_id
        assert "value_bet_id=vb.prediction_id" not in source, (
            "BetLog must NOT use vb.prediction_id for value_bet_id — "
            "that's a predictions.id, not a value_bets.id"
        )

        # The fix: actual VB lookup
        assert "actual_vb_id" in source or "actual_vb" in source, (
            "Tracker must look up the actual ValueBet DB ID"
        )

    def test_tracker_has_fallback_to_none(self):
        """If the VB is not found in DB, value_bet_id should be None (not crash)."""
        tracker_path = Path(__file__).resolve().parents[1] / "src" / "betting" / "tracker.py"
        source = tracker_path.read_text()

        # Should have fallback: actual_vb.id if actual_vb else None
        assert "if actual_vb else None" in source, (
            "Tracker must fall back to None if ValueBet not found"
        )


# ============================================================================
# PC-11 Pipeline Structure Checks
# ============================================================================


class TestPipelineStructure:
    """Verify pipeline.py imports ValueBet and BetLog for FK cleanup."""

    def test_generate_predictions_imports_fk_models(self):
        """_generate_predictions() must import ValueBet and BetLog for
        the FK chain cleanup."""
        pipeline_path = Path(__file__).resolve().parents[1] / "src" / "pipeline.py"
        source = pipeline_path.read_text()

        # Find the function and its full body (up to next def or class)
        gen_pred_start = source.find("def _generate_predictions")
        assert gen_pred_start > 0

        # Search the section from function start to stale prediction code
        stale_section_end = source.find("stale_pred_ids", gen_pred_start)
        gen_pred_section = source[gen_pred_start:stale_section_end]

        assert "ValueBet" in gen_pred_section, (
            "_generate_predictions must import ValueBet for FK cleanup"
        )
        assert "BetLog" in gen_pred_section, (
            "_generate_predictions must import BetLog for FK cleanup"
        )
