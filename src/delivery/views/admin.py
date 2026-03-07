"""
BetVector — Owner Admin Page (E34-05)
=======================================
Administrative interface for the owner to manage all user accounts.
Visible only to users with ``role='owner'`` — viewers see an access
denied message and cannot reach any data.

Sections:
1. User table — all accounts with status, bankroll, and action buttons
2. Create user — name + email + temporary password → new User row with
   hashed password; owner shares credentials out-of-band
3. Per-user actions — reset bankroll, clear bet history (with confirmation),
   deactivate / reactivate

Security model:
- Role gate at render time: non-owners see "Access Denied" and no data.
- Owner's own account cannot be deactivated (enforced in deactivate_user()).
- All destructive actions (history clear) require a per-user confirmation
  checkbox before the action button is enabled.

Master Plan refs: MP §9 Dashboard, MP §6 Schema (users table)
"""

from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st

from src.auth import get_session_user_id, get_session_user_role, hash_password
from src.database.db import get_session
from src.database.models import BetLog, User

# Import shared persistence helpers from _user_ops (not settings.py).
# settings.py has module-level Streamlit rendering code — importing from it
# would execute that code in the admin page's context, corrupting the layout.
# _user_ops.py contains only pure DB operations with no Streamlit imports.
from src.delivery.views._user_ops import (
    clear_bet_history,
    deactivate_user,
    reactivate_user,
    reset_bankroll,
)


# ============================================================================
# Design tokens (MP §8)
# ============================================================================

COLOURS = {
    "bg": "#0D1117",
    "surface": "#161B22",
    "border": "#30363D",
    "text": "#E6EDF3",
    "text_secondary": "#8B949E",
    "green": "#3FB950",
    "red": "#F85149",
    "yellow": "#D29922",
    "blue": "#58A6FF",
    "purple": "#BC8CFF",
}


# ============================================================================
# Data Loading
# ============================================================================

def load_all_users_admin() -> List[Dict]:
    """Load all users with full details for the admin table.

    Returns more fields than the settings.py ``load_all_users()`` —
    specifically includes ``current_bankroll``, ``starting_bankroll``, and
    a formatted ``created_at`` string for display.

    Returns
    -------
    list of dict
        Each dict: id, name, email, role, is_active, current_bankroll,
        starting_bankroll, created_at
    """
    with get_session() as session:
        users = session.query(User).order_by(User.id).all()
        return [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email or "—",
                "role": u.role,
                "is_active": bool(u.is_active),
                "current_bankroll": u.current_bankroll or 0.0,
                "starting_bankroll": u.starting_bankroll or 0.0,
                # Format as YYYY-MM-DD; fall back gracefully if NULL or malformed.
                "created_at": (u.created_at or "")[:10] or "—",
                # Flag whether a password has been set (None → no login possible)
                "has_password": u.password_hash is not None,
            }
            for u in users
        ]


def get_user_placed_count(user_id: int) -> int:
    """Count user_placed BetLog rows for a given user.

    Used to show how many bet records would be deleted before the owner
    confirms the clear action.
    """
    try:
        with get_session() as session:
            return (
                session.query(BetLog)
                .filter(
                    BetLog.user_id == user_id,
                    BetLog.bet_type == "user_placed",
                )
                .count()
            )
    except Exception:
        return 0


def create_user_with_password(
    name: str,
    email: str,
    password: str,
    role: str = "viewer",
) -> Optional[int]:
    """Create a new user account with a hashed password.

    The owner shares the temporary password out-of-band.  The new user
    can log in immediately once the account is created (is_active=1).

    Parameters
    ----------
    name : str
        Display name shown in the sidebar and notification emails.
    email : str
        Login email address (normalised to lowercase).
    password : str
        Temporary plaintext password chosen by the owner.  Stored as a
        PBKDF2-SHA256 hash — never stored in plaintext.
    role : str
        ``"viewer"`` (default) or ``"owner"``.  Additional owners are
        rare; the UI defaults to viewer.

    Returns
    -------
    int or None
        The new user's database ID, or None on failure (e.g. duplicate email).
    """
    normalised_email = email.strip().lower()
    password_hash = hash_password(password)
    try:
        with get_session() as session:
            new_user = User(
                name=name.strip(),
                email=normalised_email,
                role=role,
                password_hash=password_hash,
                starting_bankroll=500.0,
                current_bankroll=500.0,
                staking_method="flat",
                stake_percentage=0.02,
                kelly_fraction=0.25,
                edge_threshold=0.05,
                is_active=1,
                has_onboarded=0,
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
            )
            session.add(new_user)
            session.commit()
            session.refresh(new_user)
            return new_user.id
    except Exception:
        return None


# ============================================================================
# Page Layout
# ============================================================================

# ---- Role gate ----
# Non-owner users must not see any admin data.  This is enforced here AND
# in get_pages() (the page is not even added to the navigation for viewers),
# providing defence in depth.
if get_session_user_role() != "owner":
    st.markdown(
        f'<div style="text-align: center; padding: 60px 20px;">'
        f'<div style="font-size: 48px; margin-bottom: 16px;">🔒</div>'
        f'<div style="font-family: Inter, sans-serif; font-size: 20px; '
        f'font-weight: 600; color: {COLOURS["text"]};">Access Denied</div>'
        f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
        f'color: {COLOURS["text_secondary"]}; margin-top: 8px;">'
        f'This page is only available to the account owner.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# ---- Page header ----
st.markdown(
    '<div class="bv-page-title">Admin</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">User account management — owner only</p>',
    unsafe_allow_html=True,
)
st.divider()

# ---- Load all users ----
all_users = load_all_users_admin()

# ============================================================================
# Section 1: User Table
# ============================================================================

st.markdown(
    '<div class="bv-section-header">All Users</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<p style="font-family: Inter, sans-serif; font-size: 13px; '
    f'color: {COLOURS["text_secondary"]}; margin-bottom: 16px;">'
    f'{len(all_users)} user(s) registered. Deactivated users cannot log in.'
    f'</p>',
    unsafe_allow_html=True,
)

# Column headers
header_cols = st.columns([2, 2, 1, 1, 1, 1])
header_style = (
    f'font-family: Inter, sans-serif; font-size: 11px; '
    f'font-weight: 600; color: {COLOURS["text_secondary"]}; '
    f'text-transform: uppercase; letter-spacing: 0.5px;'
)
with header_cols[0]:
    st.markdown(f'<span style="{header_style}">Name / Email</span>', unsafe_allow_html=True)
with header_cols[1]:
    st.markdown(f'<span style="{header_style}">Bankroll</span>', unsafe_allow_html=True)
with header_cols[2]:
    st.markdown(f'<span style="{header_style}">Role</span>', unsafe_allow_html=True)
with header_cols[3]:
    st.markdown(f'<span style="{header_style}">Status</span>', unsafe_allow_html=True)
with header_cols[4]:
    st.markdown(f'<span style="{header_style}">Password</span>', unsafe_allow_html=True)
with header_cols[5]:
    st.markdown(f'<span style="{header_style}">Actions</span>', unsafe_allow_html=True)

st.markdown(
    f'<hr style="border-color: {COLOURS["border"]}; margin: 4px 0 8px 0;">',
    unsafe_allow_html=True,
)

for u in all_users:
    is_self = (u["id"] == get_session_user_id())
    name_colour = COLOURS["text"] if u["is_active"] else COLOURS["text_secondary"]
    role_colour = COLOURS["purple"] if u["role"] == "owner" else COLOURS["blue"]
    active_colour = COLOURS["green"] if u["is_active"] else COLOURS["red"]
    active_label = "Active" if u["is_active"] else "Inactive"
    bankroll_colour = (
        COLOURS["green"] if u["current_bankroll"] >= u["starting_bankroll"]
        else COLOURS["red"]
    )

    row_cols = st.columns([2, 2, 1, 1, 1, 1])

    with row_cols[0]:
        st.markdown(
            f'<div style="padding: 4px 0;">'
            f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
            f'font-weight: 600; color: {name_colour};">{u["name"]}</div>'
            f'<div style="font-family: JetBrains Mono, monospace; font-size: 11px; '
            f'color: {COLOURS["text_secondary"]};">{u["email"]}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with row_cols[1]:
        st.markdown(
            f'<div style="padding: 4px 0;">'
            f'<div style="font-family: JetBrains Mono, monospace; font-size: 13px; '
            f'color: {bankroll_colour};">${u["current_bankroll"]:.2f}</div>'
            f'<div style="font-family: JetBrains Mono, monospace; font-size: 11px; '
            f'color: {COLOURS["text_secondary"]};">start: ${u["starting_bankroll"]:.2f}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with row_cols[2]:
        st.markdown(
            f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
            f'color: {role_colour};">{u["role"]}</span>',
            unsafe_allow_html=True,
        )

    with row_cols[3]:
        st.markdown(
            f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
            f'color: {active_colour};">{active_label}</span>',
            unsafe_allow_html=True,
        )

    with row_cols[4]:
        pwd_label = "✅ Set" if u["has_password"] else "⚠️ None"
        pwd_colour = COLOURS["green"] if u["has_password"] else COLOURS["yellow"]
        st.markdown(
            f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
            f'color: {pwd_colour};">{pwd_label}</span>',
            unsafe_allow_html=True,
        )

    with row_cols[5]:
        # Deactivate / Reactivate — owner cannot be deactivated
        if not is_self and u["role"] != "owner":
            if u["is_active"]:
                if st.button(
                    "Deactivate",
                    key=f"admin_deact_{u['id']}",
                    type="secondary",
                    use_container_width=True,
                ):
                    if deactivate_user(u["id"]):
                        st.toast(f"Deactivated {u['name']}", icon="✅")
                        st.rerun()
                    else:
                        st.error("Failed to deactivate user.")
            else:
                if st.button(
                    "Reactivate",
                    key=f"admin_react_{u['id']}",
                    type="secondary",
                    use_container_width=True,
                ):
                    if reactivate_user(u["id"]):
                        st.toast(f"Reactivated {u['name']}", icon="✅")
                        st.rerun()
                    else:
                        st.error("Failed to reactivate user.")
        elif is_self:
            st.markdown(
                f'<span style="font-family: Inter, sans-serif; font-size: 11px; '
                f'color: {COLOURS["text_secondary"]};">you</span>',
                unsafe_allow_html=True,
            )

    # Per-user action expander — reset bankroll + clear history
    # Placed below the row columns so it doesn't push the layout sideways.
    placed_count = get_user_placed_count(u["id"])
    with st.expander(f"⚙️ Manage {u['name']}", expanded=False):
        action_col1, action_col2 = st.columns(2)

        # -- Reset Bankroll --
        with action_col1:
            st.markdown(
                f'<div style="font-family: Inter, sans-serif; font-size: 13px; '
                f'font-weight: 600; color: {COLOURS["text"]}; margin-bottom: 4px;">'
                f'Reset Bankroll</div>'
                f'<div style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text_secondary"]}; margin-bottom: 8px;">'
                f'Resets to ${u["starting_bankroll"]:.2f} (starting amount).</div>',
                unsafe_allow_html=True,
            )
            confirm_br_admin = st.checkbox(
                "Confirm bankroll reset",
                key=f"admin_confirm_br_{u['id']}",
            )
            if st.button(
                "Reset Bankroll",
                key=f"admin_reset_br_{u['id']}",
                type="secondary",
                disabled=not confirm_br_admin,
                use_container_width=True,
            ):
                if reset_bankroll(u["id"]):
                    st.toast(
                        f"Reset {u['name']}'s bankroll to ${u['starting_bankroll']:.2f}",
                        icon="✅",
                    )
                    st.rerun()
                else:
                    st.error("Failed to reset bankroll.")

        # -- Clear Bet History --
        with action_col2:
            st.markdown(
                f'<div style="font-family: Inter, sans-serif; font-size: 13px; '
                f'font-weight: 600; color: {COLOURS["text"]}; margin-bottom: 4px;">'
                f'Clear Bet History</div>'
                f'<div style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text_secondary"]}; margin-bottom: 8px;">'
                f'Deletes {placed_count} user_placed record(s). System picks preserved.</div>',
                unsafe_allow_html=True,
            )
            confirm_hist_admin = st.checkbox(
                "Confirm history clear",
                key=f"admin_confirm_hist_{u['id']}",
            )
            if st.button(
                "Clear Bet History",
                key=f"admin_clear_hist_{u['id']}",
                type="secondary",
                disabled=not confirm_hist_admin,
                use_container_width=True,
            ):
                deleted = clear_bet_history(u["id"])
                if deleted >= 0:
                    st.toast(
                        f"Cleared {deleted} bet record(s) for {u['name']}",
                        icon="✅",
                    )
                    st.rerun()
                else:
                    st.error("Failed to clear bet history.")

    st.markdown(
        f'<div style="border-bottom: 1px solid {COLOURS["border"]}; '
        f'margin: 2px 0 8px 0;"></div>',
        unsafe_allow_html=True,
    )

st.divider()

# ============================================================================
# Section 2: Create New User
# ============================================================================

st.markdown(
    '<div class="bv-section-header">Create New User</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<p style="font-family: Inter, sans-serif; font-size: 13px; '
    f'color: {COLOURS["text_secondary"]}; margin-bottom: 16px;">'
    f'New accounts start with a $500.00 bankroll and flat 2% staking. '
    f'Share the temporary password with the new user out-of-band — '
    f'they can change it once logged in via Settings.'
    f'</p>',
    unsafe_allow_html=True,
)

with st.form("create_user_form", border=False):
    form_col1, form_col2 = st.columns(2)

    with form_col1:
        new_name = st.text_input(
            "Full Name",
            placeholder="e.g. Alex Smith",
            key="admin_new_name",
        )
        new_email = st.text_input(
            "Email Address",
            placeholder="alex@example.com",
            key="admin_new_email",
        )

    with form_col2:
        new_password = st.text_input(
            "Temporary Password",
            type="password",
            placeholder="Minimum 8 characters",
            key="admin_new_password",
        )
        new_role = st.selectbox(
            "Role",
            options=["viewer", "owner"],
            index=0,
            key="admin_new_role",
            help="Viewer: sees picks, tracks own bankroll. Owner: full admin access.",
        )

    create_submitted = st.form_submit_button(
        "Create User",
        type="primary",
        use_container_width=False,
    )

if create_submitted:
    # Validate inputs
    if not new_name or not new_name.strip():
        st.warning("Please enter a name.")
    elif not new_email or "@" not in new_email:
        st.warning("Please enter a valid email address.")
    elif not new_password or len(new_password) < 8:
        st.warning("Password must be at least 8 characters.")
    else:
        new_id = create_user_with_password(
            name=new_name.strip(),
            email=new_email.strip(),
            password=new_password,
            role=new_role,
        )
        if new_id:
            st.success(
                f"✅ Created **{new_name.strip()}** (ID: {new_id}) as **{new_role}**. "
                f"They can log in with email `{new_email.strip().lower()}` and the "
                f"temporary password you set."
            )
            st.rerun()
        else:
            st.error(
                "Failed to create user. The email address may already be in use."
            )
