"""Backtester staking parity with the live BankrollManager (reconcile 2026-06-25).

After the live flat-staking reconcile, the backtester's flat must also be LEVEL
staking (a fixed amount off the STARTING bankroll), distinct from percentage (a % of
the CURRENT running bankroll). These pin _level_or_pct_stake — the helper the
walk-forward loop uses for the non-Kelly methods.
"""
from src.evaluation.backtester import _level_or_pct_stake


def test_flat_is_level_off_starting():
    # current $500, starting $1000 → flat = 2% of STARTING = $20 (5% cap of 500 = $25).
    assert _level_or_pct_stake("flat", bankroll=500.0, starting_bankroll=1000.0,
                               stake_percentage=0.02) == 20.0


def test_percentage_is_off_current():
    assert _level_or_pct_stake("percentage", bankroll=500.0, starting_bankroll=1000.0,
                               stake_percentage=0.02) == 10.0


def test_flat_and_percentage_differ_when_drawn_down():
    flat = _level_or_pct_stake("flat", 500.0, 1000.0, 0.02)
    pct = _level_or_pct_stake("percentage", 500.0, 1000.0, 0.02)
    assert flat != pct          # the whole point: no longer identical


def test_flat_equals_percentage_at_full_bankroll():
    # current == starting → the two coincide, as expected.
    assert _level_or_pct_stake("flat", 1000.0, 1000.0, 0.02) == \
           _level_or_pct_stake("percentage", 1000.0, 1000.0, 0.02)


def test_five_percent_cap_is_on_current_balance():
    # deep drawdown: current $200 → 5% cap = $10, below flat's level $20 → capped to $10.
    assert _level_or_pct_stake("flat", bankroll=200.0, starting_bankroll=1000.0,
                               stake_percentage=0.02) == 10.0
