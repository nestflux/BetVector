"""
BetVector — Forced Password Change (invite hardening)
=====================================================
Full-screen gate shown to a user who is on an owner-assigned *temporary*
password (``users.must_change_password = 1``).  It blocks the rest of the app —
including onboarding — until the user sets their own password.

Flow
----
1. The owner creates an account (admin "Create User" or Settings "Invite User").
   Both set ``must_change_password = 1`` and store a temporary password hash.
2. The user logs in with the temporary password.  ``dashboard.main()`` sees the
   flag and routes here instead of onboarding / the dashboard.
3. The user picks a new password (which must differ from the temporary one).
   ``set_user_password`` stores it and clears the flag; the next rerun falls
   through to onboarding.

The user is already authenticated when they reach this screen, so only the new
password + confirmation are required (no current-password prompt).  Reuse of the
temporary password is blocked via ``validate_new_password(current_hash=...)``.

Master Plan refs: MP §6 (users table), MP §8 Design System
"""

from __future__ import annotations

import html

import streamlit as st

from src.auth import (
    get_session_user_id,
    set_user_password,
    validate_new_password,
)
from src.database.db import get_session
from src.database.models import User

# Design tokens (MP §8) — kept local so this gate has no cross-view imports.
_TEXT = "#E6EDF3"
_TEXT_SECONDARY = "#8B949E"


def _load_user_credentials(user_id: int):
    """Return ``(display_name, password_hash)`` for the user, or ``(None, None)``.

    Read-only — used to greet the user and to block reuse of the temporary
    password.  Never raises: any DB error degrades to ``(None, None)`` so the
    screen still renders and the user can still set a password.
    """
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if user is None:
                return None, None
            return user.name, user.password_hash
    except Exception:
        return None, None


def render_forced_password_change() -> None:
    """Render the forced first-login password-change screen."""
    user_id = get_session_user_id()
    name, current_hash = _load_user_credentials(user_id)

    # Centre the card the same way the login gate / onboarding wizard do.
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown(
            f'<div style="text-align:center; font-family: Inter, sans-serif; '
            f'color:{_TEXT}; font-size:22px; font-weight:700; margin: 8px 0 4px;">'
            f'🔒 Set your password</div>',
            unsafe_allow_html=True,
        )
        # Greeting name is user-supplied → escape to prevent HTML injection.
        greeting = f"Welcome, {html.escape(name)}. " if name else "Welcome. "
        st.markdown(
            f'<p style="text-align:center; font-family: Inter, sans-serif; '
            f'color:{_TEXT_SECONDARY}; font-size:14px; margin-bottom:18px;">'
            f"{greeting}You're using a temporary password. Choose your own to "
            f"continue — you'll use it every time you log in."
            f'</p>',
            unsafe_allow_html=True,
        )

        with st.form("forced_password_change_form", border=False):
            new_pw = st.text_input(
                "New password", type="password", key="fpc_new",
                placeholder="At least 8 characters",
            )
            confirm_pw = st.text_input(
                "Confirm new password", type="password", key="fpc_confirm",
            )
            submitted = st.form_submit_button(
                "Set password & continue",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            ok, msg = validate_new_password(
                new_pw, confirm_pw, current_hash=current_hash,
            )
            if not ok:
                st.warning(msg)
            elif set_user_password(user_id, new_pw):
                st.success("Password set. Loading your dashboard…")
                st.rerun()
            else:
                st.error(
                    "Something went wrong saving your password. Please try again."
                )

        # Escape hatch so a confused user is never trapped on this screen.
        st.divider()
        if st.button("Log out", key="fpc_logout", use_container_width=True):
            # Defer the session-clear + cookie-expire to the login gate
            # (dashboard.check_password) so the expire-cookie component fires on a
            # completing run; clearing it here then st.rerun would leave the
            # cookie behind and silently re-hydrate the session.
            st.session_state["_pending_logout"] = True
            st.rerun()
