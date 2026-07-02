"""FB — Feedback Experience.

FB-01: config-driven questionnaire + normalized survey storage
(``feedback_survey`` / ``feedback_answer``), verified over an in-memory DB with FK
enforcement on so the delete-cascade is genuinely exercised.
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
import src.database.models  # noqa: E402,F401
import src.world_cup.models  # noqa: E402,F401  (delete_user references wc_* tables)
from src.auth import hash_password  # noqa: E402
from src.database.db import Base  # noqa: E402
from src.database.models import (  # noqa: E402
    FeedbackAnswer, FeedbackSurvey, User,
)
from src.delivery.views._feedback_ops import (  # noqa: E402
    load_feedback_questions, load_survey_aggregates, load_text_answers,
    submit_survey, survey_count,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _rec):  # noqa: ANN001
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


def _mk_user(db, name="Tester", email="tester@example.com", role="viewer"):
    with db() as s:
        u = User(name=name, email=email, role=role,
                 password_hash=hash_password("pw12345678"),
                 starting_bankroll=500.0, current_bankroll=500.0,
                 staking_method="flat", stake_percentage=0.02,
                 kelly_fraction=0.25, edge_threshold=0.05, is_active=1,
                 created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00")
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


# ---- config question set ----------------------------------------------------

def test_load_feedback_questions_from_config():
    qs = load_feedback_questions()
    by_key = {q["key"]: q for q in qs}
    assert {"keep_using", "most_useful", "trust_model", "frequency",
            "confusing"} <= set(by_key)
    assert by_key["keep_using"]["type"] == "scale"
    assert by_key["keep_using"]["min"] == 0 and by_key["keep_using"]["max"] == 10
    assert by_key["most_useful"]["type"] == "multiselect"
    assert "World Cup tracker" in by_key["most_useful"]["options"]
    assert by_key["trust_model"]["type"] == "select"
    assert by_key["confusing"]["type"] == "text"


# ---- submit + storage -------------------------------------------------------

def test_submit_survey_stores_normalized(db):
    uid = _mk_user(db)
    ok = submit_survey(uid, {
        "keep_using": 8,
        "most_useful": ["World Cup tracker", "Deep dive"],
        "trust_model": "Somewhat",
        "confusing": "the bankroll page",
    })
    assert ok
    with db() as s:
        assert s.query(FeedbackSurvey).count() == 1
        # 1 (keep_using) + 2 (most_useful) + 1 (trust) + 1 (confusing) = 5 rows
        assert s.query(FeedbackAnswer).count() == 5
        mu = [a.answer for a in s.query(FeedbackAnswer)
              .filter_by(question_key="most_useful").all()]
        assert set(mu) == {"World Cup tracker", "Deep dive"}
        assert (s.query(FeedbackAnswer)
                .filter_by(question_key="keep_using").one().answer) == "8"


def test_submit_survey_rejects_empty(db):
    uid = _mk_user(db)
    assert submit_survey(uid, {}) is False
    assert submit_survey(uid, {"keep_using": "  ", "most_useful": []}) is False
    with db() as s:
        assert s.query(FeedbackSurvey).count() == 0


# ---- aggregation ------------------------------------------------------------

def test_load_survey_aggregates_groups(db):
    uid = _mk_user(db)
    submit_survey(uid, {"trust_model": "Yes",
                        "most_useful": ["Deep dive", "Bankroll"]})
    submit_survey(uid, {"trust_model": "Yes", "most_useful": ["Deep dive"]})
    agg = load_survey_aggregates()
    assert agg["trust_model"]["Yes"] == 2
    assert agg["most_useful"]["Deep dive"] == 2   # per option, across submissions
    assert agg["most_useful"]["Bankroll"] == 1


def test_survey_count(db):
    uid = _mk_user(db)
    assert survey_count() == 0
    submit_survey(uid, {"keep_using": 5})
    assert survey_count() == 1


def test_load_text_answers(db):
    uid = _mk_user(db)
    submit_survey(uid, {"confusing": "first note"})
    submit_survey(uid, {"confusing": "second note"})
    assert set(load_text_answers("confusing")) == {"first note", "second note"}


# ---- delete-user cascade (FK enforced) --------------------------------------

def test_delete_user_removes_their_surveys(db):
    from src.delivery.views._user_ops import delete_user
    keep = _mk_user(db, name="K", email="k@x.com", role="owner")   # owner survives
    victim = _mk_user(db, name="V", email="v@x.com", role="viewer")
    submit_survey(victim, {"keep_using": 9, "most_useful": ["Bankroll"]})
    submit_survey(keep, {"keep_using": 7})
    assert delete_user(victim) is True
    with db() as s:
        assert s.query(FeedbackSurvey).filter_by(user_id=victim).count() == 0
        assert s.query(FeedbackAnswer).count() == 1   # only keep's one answer
        assert s.query(FeedbackSurvey).filter_by(user_id=keep).count() == 1


# ============================================================================
# FB-02 — dedicated Feedback page (open form + questionnaire) + wiring
# ============================================================================

def test_submit_survey_skips_none_answers(db):
    uid = _mk_user(db)
    # an unanswered st.radio yields None → it must be skipped, not stored as "None"
    assert submit_survey(uid, {"trust_model": None, "keep_using": 7}) is True
    with db() as s:
        keys = [a.question_key for a in s.query(FeedbackAnswer).all()]
        assert keys == ["keep_using"]                 # the None answer was dropped


def test_feedback_page_wires_both_channels():
    src = (ROOT / "src" / "delivery" / "views" / "feedback.py").read_text()
    assert "submit_feedback(" in src and "submit_survey(" in src
    assert "load_feedback_questions(" in src
    for widget in ("st.slider(", "st.radio(", "st.multiselect(", "st.text_input("):
        assert widget in src                          # every question type rendered
    compile(src, "feedback.py", "exec")


def test_feedback_page_registered_in_nav():
    src = (ROOT / "src" / "delivery" / "dashboard.py").read_text()
    assert '"views/feedback.py"' in src


def test_settings_links_to_feedback_page_without_inline_form():
    src = (ROOT / "src" / "delivery" / "views" / "settings.py").read_text()
    assert 'st.switch_page("views/feedback.py")' in src   # links to the page
    assert 'st.form("feedback_form"' not in src           # the inline form was removed
    compile(src, "settings.py", "exec")
