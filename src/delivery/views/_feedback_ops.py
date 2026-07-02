"""
BetVector — Feedback Questionnaire Operations (FB-01)
=====================================================
Config-driven questionnaire + NORMALIZED survey storage, separate from the open-text
``user_feedback`` message (UM-07). Questions come from ``config/settings.yaml``
(``feedback.questions``); each answer is stored as its own ``feedback_answer`` row
(one row per multi-select choice) keyed by ``question_key``, so responses aggregate
with a ``GROUP BY`` and the question set can change in config without a migration.

No Streamlit imports — safe to import from any context (mirrors ``_user_ops.py``).
"""

from datetime import datetime

import yaml
from sqlalchemy import func

from src.config import PROJECT_ROOT
from src.database.db import get_session
from src.database.models import FeedbackAnswer, FeedbackSurvey

# Question types the renderer understands. A malformed question (missing key/prompt or
# an unknown type) is dropped rather than crashing the page.
_VALID_TYPES = {"scale", "select", "multiselect", "text"}


def load_feedback_questions() -> list:
    """The configured questionnaire as a list of dicts
    ``{key, prompt, type, options?, min?, max?}`` (FB-01), read from
    ``config/settings.yaml`` ``feedback.questions``. Returns ``[]`` when unset or
    malformed; only well-formed questions (a key, a prompt, a known type) are kept."""
    try:
        with open(PROJECT_ROOT / "config" / "settings.yaml") as f:
            data = yaml.safe_load(f) or {}
        raw = (data.get("feedback") or {}).get("questions") or []
    except Exception:
        return []
    out = []
    for q in raw:
        if not isinstance(q, dict):
            continue
        key, prompt, qtype = q.get("key"), q.get("prompt"), q.get("type")
        if not key or not prompt or qtype not in _VALID_TYPES:
            continue
        item = {"key": str(key), "prompt": str(prompt), "type": qtype}
        if qtype in ("select", "multiselect"):
            item["options"] = [str(o) for o in (q.get("options") or [])]
        if qtype == "scale":
            # Tolerate bad bounds → fall back to 0..10.
            try:
                item["min"] = int(q.get("min", 0))
                item["max"] = int(q.get("max", 10))
            except (TypeError, ValueError):
                item["min"], item["max"] = 0, 10
        out.append(item)
    return out


def submit_survey(user_id, answers) -> bool:
    """Store a questionnaire submission (FB-01). ``answers`` maps ``question_key`` →
    a value (str / int) or a list (multi-select). Blank answers are skipped; a
    submission with NO non-blank answers is rejected. One ``feedback_answer`` row per
    answer value, all under one ``feedback_survey`` in a single transaction. Returns
    True on success, False otherwise. Never raises."""
    if not answers:
        return False
    rows = []
    for key, val in answers.items():
        values = val if isinstance(val, (list, tuple, set)) else [val]
        for v in values:
            s = str(v).strip()
            if s:
                rows.append((str(key), s))
    if not rows:
        return False
    try:
        with get_session() as session:
            survey = FeedbackSurvey(
                user_id=user_id, created_at=datetime.utcnow().isoformat(),
            )
            session.add(survey)
            session.flush()   # assign survey.id for the answer FKs
            for key, value in rows:
                session.add(FeedbackAnswer(
                    survey_id=survey.id, question_key=key, answer=value,
                ))
            session.commit()
        return True
    except Exception:
        return False


def survey_count() -> int:
    """Number of questionnaire submissions (FB-04 empty-state check). 0 on error."""
    try:
        with get_session() as session:
            return session.query(FeedbackSurvey).count()
    except Exception:
        return 0


def load_survey_aggregates() -> dict:
    """Answer counts per question for the owner view (FB-01/FB-04):
    ``{question_key: {answer: count}}``. Multi-select is counted per chosen option.
    Suited to scale / select / multiselect questions (text answers are unique — list
    them with :func:`load_text_answers` instead). ``{}`` on error / no responses."""
    try:
        with get_session() as session:
            rows = (
                session.query(
                    FeedbackAnswer.question_key,
                    FeedbackAnswer.answer,
                    func.count().label("n"),
                )
                .group_by(FeedbackAnswer.question_key, FeedbackAnswer.answer)
                .all()
            )
    except Exception:
        return {}
    out: dict = {}
    for key, answer, n in rows:
        out.setdefault(key, {})[answer] = n
    return out


def load_text_answers(question_key, limit: int = 100) -> list:
    """Raw free-text answers for one question, newest first (FB-04). [] on error."""
    try:
        with get_session() as session:
            rows = (
                session.query(FeedbackAnswer.answer)
                .join(FeedbackSurvey, FeedbackAnswer.survey_id == FeedbackSurvey.id)
                .filter(FeedbackAnswer.question_key == question_key)
                .order_by(FeedbackSurvey.created_at.desc())
                .limit(limit)
                .all()
            )
            return [r[0] for r in rows]
    except Exception:
        return []
