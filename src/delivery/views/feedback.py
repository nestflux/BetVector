"""
BetVector — Feedback page (FB-02)
==================================
A visible, first-class feedback channel for every user:

- **💬 Send feedback** — an open free-text form (reuses UM-07's ``submit_feedback``),
  with a best-effort owner email notify.
- **📋 Quick questions** — a short structured questionnaire whose questions come from
  ``config/settings.yaml`` (FB-01), rendered dynamically by type.

Registered in the nav for all users; the owner reads submissions on the Admin page.
Read/write only touches the feedback tables — nowhere near the model/value path.
"""

import streamlit as st

from src.auth import get_session_user_id
from src.database.db import get_session
from src.database.models import User
from src.delivery.views._feedback_ops import load_feedback_questions, submit_survey
from src.delivery.views._user_ops import owner_user_id, submit_feedback

# Resolve the current user's id (+ name for the notify email). A tiny read; never
# import from settings.py (its module-level code renders the whole Settings page).
_uid = get_session_user_id()
try:
    with get_session() as _s:
        _u = _s.get(User, _uid)
        _uname = _u.name if _u else "a user"
except Exception:
    _uname = "a user"


def _notify_owner(category: str, message: str) -> None:
    """Best-effort: email the owner about a new open-form submission. Never raises,
    never blocks the submit (the message is already stored + on the Admin page)."""
    try:
        oid = owner_user_id()
        if oid:
            from src.delivery.email_alerts import send_alert
            send_alert(
                oid,
                f"BetVector feedback from {_uname}",
                f"[{category}]\n\n{message.strip()}",
            )
    except Exception:
        pass


# ---- Page header ------------------------------------------------------------
st.markdown('<div class="bv-page-title">Feedback</div>', unsafe_allow_html=True)
st.markdown(
    "<p class=\"text-muted\">Tell us what's working, what's not, and what you'd like "
    "to see next — it genuinely shapes where BetVector goes.</p>",
    unsafe_allow_html=True,
)
st.divider()

# ============================================================================
# 💬 Send feedback (open form)
# ============================================================================
st.markdown('<div class="bv-section-header">💬 Send feedback</div>',
            unsafe_allow_html=True)
with st.form("fb_page_open_form", border=False, clear_on_submit=True):
    fbp_category = st.selectbox(
        "Type", options=["Bug", "Idea", "Question", "Other"], key="fbp_category",
    )
    fbp_message = st.text_area(
        "Your feedback", key="fbp_message",
        placeholder="What happened, or what would you like to see?",
    )
    fbp_sent = st.form_submit_button("Send feedback", type="primary")

if fbp_sent:
    if not (fbp_message or "").strip():
        st.warning("Please enter a message before sending.")
    elif submit_feedback(_uid, fbp_message, fbp_category):
        _notify_owner(fbp_category, fbp_message)
        st.success("✅ Thanks — your feedback was sent.")
    else:
        st.error("Couldn't send your feedback — please try again.")

st.divider()

# ============================================================================
# 📋 Quick questions (structured questionnaire — config-driven)
# ============================================================================
st.markdown('<div class="bv-section-header">📋 Quick questions</div>',
            unsafe_allow_html=True)

_questions = load_feedback_questions()
if not _questions:
    st.caption("No questions configured right now.")
else:
    st.caption("A few quick, optional questions to help steer where BetVector "
               "goes next.")
    with st.form("fb_page_survey_form", border=False, clear_on_submit=True):
        _responses = {}
        for q in _questions:
            qtype = q["type"]
            wkey = f"fbq_{q['key']}"
            if qtype == "scale":
                _responses[q["key"]] = st.slider(
                    q["prompt"], min_value=q["min"], max_value=q["max"],
                    value=(q["min"] + q["max"]) // 2, key=wkey,
                )
            elif qtype == "select":
                # index=None → nothing pre-selected, so an unanswered question is
                # left out (submit_survey skips None).
                _responses[q["key"]] = st.radio(
                    q["prompt"], q["options"], index=None, key=wkey,
                )
            elif qtype == "multiselect":
                _responses[q["key"]] = st.multiselect(
                    q["prompt"], q["options"], key=wkey,
                )
            elif qtype == "text":
                _responses[q["key"]] = st.text_input(q["prompt"], key=wkey)
        _survey_sent = st.form_submit_button("Submit answers", type="primary")

    if _survey_sent:
        if submit_survey(_uid, _responses):
            st.success("✅ Thanks — your answers were recorded.")
        else:
            st.info("Add at least one answer before submitting.")
