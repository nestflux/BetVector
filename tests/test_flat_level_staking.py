"""Flat = level staking (owner reconcile decision, 2026-06-25).

After the "fix the copy or the code" call, FLAT staking is true LEVEL staking — a
fixed amount = stake_percentage of the user's STARTING bankroll — and is genuinely
distinct from PERCENTAGE staking (stake_percentage of the CURRENT bankroll). These
tests lock that in: with starting != current the two methods produce different
stakes, and flat degrades safely to current if a starting value is ever missing.
"""
from unittest.mock import patch

from src.betting.bankroll import BankrollManager


def _user(method, starting=1000.0, current=500.0, pct=0.02):
    return {
        "id": 1,
        "starting_bankroll": starting,
        "current_bankroll": current,
        "staking_method": method,
        "stake_percentage": pct,
        "kelly_fraction": 0.25,
        "edge_threshold": 0.05,
    }


_SAFETY_OK = {
    "daily_limit_hit": False,
    "drawdown_warning": False,
    "min_bankroll_hit": False,
    "message": "OK",
}


def _stake(user):
    mgr = BankrollManager()
    with (
        patch.object(BankrollManager, "_get_user", return_value=user),
        patch.object(BankrollManager, "check_safety_limits", return_value=_SAFETY_OK),
        patch.object(BankrollManager, "_get_daily_staked", return_value=0.0),
    ):
        # league=None → no per-league override; uses the user's own method.
        return mgr.calculate_stake(user_id=1, model_prob=0.55, odds=2.10).stake


def test_flat_uses_starting_bankroll_level_stake():
    # starting $1000, current $500 → flat = 2% of STARTING = $20 (NOT $10).
    assert _stake(_user("flat")) == 20.0


def test_percentage_uses_current_bankroll():
    # same balances → percentage = 2% of CURRENT = $10.
    assert _stake(_user("percentage")) == 10.0


def test_flat_and_percentage_differ_when_drawn_down():
    # The whole point of the reconcile: the two methods are no longer identical.
    assert _stake(_user("flat")) != _stake(_user("percentage"))


def test_flat_equals_percentage_before_any_swing():
    # When current == starting (a fresh bankroll) the two coincide — as expected.
    assert _stake(_user("flat", starting=1000.0, current=1000.0)) == \
           _stake(_user("percentage", starting=1000.0, current=1000.0))


def test_flat_falls_back_to_current_if_starting_missing():
    # Defensive: a user dict without starting_bankroll must not yield $0.
    u = _user("flat")
    u.pop("starting_bankroll")
    assert _stake(u) == 10.0   # falls back to current $500 × 2%
