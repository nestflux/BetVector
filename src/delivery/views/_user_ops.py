"""
BetVector — Shared User Operation Helpers
==========================================
Pure database functions for user management: bankroll reset, bet history
clear, activate/deactivate.  Extracted into a separate module so that
``admin.py`` can import them **without** triggering the Streamlit rendering
code in ``settings.py`` (Python executes all module-level code in a file
the first time it is imported, so importing from ``settings.py`` would
render the entire Settings page inside the Admin page).

Imported by:
- ``src/delivery/views/admin.py``   — owner admin page
- ``src/delivery/views/settings.py`` — user settings page (Danger Zone)

No Streamlit imports — this file is safe to import from any context,
including modules that run before Streamlit's page context is established.

Master Plan refs: MP §6 Schema (users, bet_log tables)
"""

from datetime import datetime

from src.database.db import get_session
from src.database.models import BetLog, User


def reset_bankroll(user_id: int) -> bool:
    """Reset the user's current bankroll to their starting bankroll.

    E29-04: This is a "fresh start" — the bankroll counter resets but all
    historical bet data (BetLog) is preserved.  This lets the user restart
    their bankroll tracking without losing performance history.

    Parameters
    ----------
    user_id : int
        The user's database ID.

    Returns
    -------
    bool
        True if the reset succeeded, False otherwise.
    """
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return False
            user.current_bankroll = user.starting_bankroll
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


def clear_bet_history(user_id: int) -> int:
    """Delete all user_placed BetLog rows for the given user.

    E34-04: Clears the user's personal bet history while preserving system
    picks.  System picks (bet_type='system_pick') record model performance
    and are global — never scoped to or deleted by a single user.

    Parameters
    ----------
    user_id : int
        The user whose personal bet log entries should be deleted.

    Returns
    -------
    int
        Number of rows deleted, or -1 on failure.
    """
    try:
        with get_session() as session:
            deleted = (
                session.query(BetLog)
                .filter(
                    BetLog.user_id == user_id,
                    BetLog.bet_type == "user_placed",
                )
                .delete(synchronize_session=False)
            )
            session.commit()
            return deleted
    except Exception:
        return -1


def reset_everything(user_id: int) -> bool:
    """Atomically reset the bankroll AND clear bet history for the user.

    E34-04: Both operations (bankroll reset + bet history clear) execute
    in a single database transaction.  If either fails, both roll back so
    the data is never left in a partially-reset state.  System picks are
    always preserved.

    Parameters
    ----------
    user_id : int
        The user to fully reset.

    Returns
    -------
    bool
        True if both operations committed successfully, False otherwise.
    """
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return False
            # 1. Reset bankroll counter
            user.current_bankroll = user.starting_bankroll
            user.updated_at = datetime.utcnow().isoformat()
            # 2. Clear personal bet history (system picks untouched)
            session.query(BetLog).filter(
                BetLog.user_id == user_id,
                BetLog.bet_type == "user_placed",
            ).delete(synchronize_session=False)
            # Both changes committed in one atomic transaction
            session.commit()
        return True
    except Exception:
        return False


def deactivate_user(user_id: int) -> bool:
    """Deactivate a user account (set is_active=0).

    The owner's account (role='owner') cannot be deactivated — the check
    ensures there is always at least one owner who can log in.

    Parameters
    ----------
    user_id : int
        The user to deactivate.

    Returns
    -------
    bool
        True on success, False if user not found or user is an owner.
    """
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user or user.role == "owner":
                return False
            user.is_active = 0
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


def reactivate_user(user_id: int) -> bool:
    """Reactivate a previously deactivated user account.

    Parameters
    ----------
    user_id : int
        The user to reactivate.

    Returns
    -------
    bool
        True on success, False if user not found.
    """
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return False
            user.is_active = 1
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


def update_user_profile(user_id, name=None, email=None):
    """Owner-driven edit of an existing account's display name and/or login email
    (UM-02).  Only the fields that are passed change.

    Validation:
    - ``name`` (if given): non-empty after stripping.
    - ``email`` (if given): looks like an address AND is not already used by
      ANOTHER user — email IS the login, so a collision would let two accounts
      claim the same sign-in.  Stored lowercased/trimmed, matching account creation.

    Returns ``(ok, message)`` — ``message`` is a user-facing error when ``ok`` is
    False, or a short success note otherwise.  Never raises.
    """
    new_name = name.strip() if name is not None else None
    new_email = email.strip().lower() if email is not None else None

    if new_name is not None and not new_name:
        return False, "Name can't be empty."
    if new_email is not None:
        # Light structural check (an "@" with a dotted domain) — mirrors the
        # admin create form; the real guard is the uniqueness check below.
        domain = new_email.split("@")[-1] if "@" in new_email else ""
        if "@" not in new_email or "." not in domain:
            return False, "Please enter a valid email address."

    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if user is None:
                return False, "User not found."
            if new_email is not None:
                clash = (
                    session.query(User)
                    .filter(User.email == new_email, User.id != user_id)
                    .first()
                )
                if clash is not None:
                    return False, "That email is already used by another account."
                user.email = new_email
            if new_name is not None:
                user.name = new_name
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True, "Profile updated."
    except Exception:
        return False, "Could not update the profile — please try again."


def delete_user(user_id: int) -> bool:
    """Permanently delete a viewer account and all its bet history.

    DESTRUCTIVE and irreversible — unlike deactivate_user (which just sets
    is_active=0 and keeps everything).  Refuses to delete an owner account
    (role='owner'), mirroring deactivate_user, so the owner can never be removed
    and lock everyone out; only viewers/testers can be deleted.

    bet_log.user_id is a NOT NULL foreign key to users.id, so the user's bets
    must be removed BEFORE the user row or the delete violates the constraint.
    Both happen in one atomic transaction — if either fails, neither commits.
    Bets belonging to OTHER users (e.g. the owner's system picks) are untouched.

    Parameters
    ----------
    user_id : int
        The viewer account to permanently delete.

    Returns
    -------
    bool
        True on success; False if the user is missing, is an owner, or the
        transaction fails.
    """
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user or user.role == "owner":
                return False
            # Remove this user's bet_log rows first (NOT NULL FK to users.id),
            # then the user — all in one transaction.
            session.query(BetLog).filter(
                BetLog.user_id == user_id,
            ).delete(synchronize_session=False)
            session.delete(user)
            session.commit()
        return True
    except Exception:
        return False
