"""
BetVector — Bankroll Manager (E6-02)
=====================================
Calculates bet stakes and enforces safety limits to protect the bankroll
from ruin.

Bankroll Management Basics
--------------------------
In sports betting, **bankroll management** is arguably more important
than the prediction model itself.  Even a winning system can go broke
with reckless staking.  The goal is to maximise long-term growth while
surviving inevitable losing streaks.

Staking Methods
---------------
This module supports three staking methods:

1. **Flat staking** (default):
   stake = current_bankroll × stake_percentage
   Example: $1000 × 0.02 = $20 per bet.  Simple and conservative.
   Recommended for beginners.

2. **Percentage staking**:
   Same formula as flat, but recalculates after each bet as the bankroll
   changes.  When winning, stakes grow; when losing, stakes shrink
   automatically.  In practice this is identical to flat in a single
   calculation — the difference emerges over a sequence of bets.

3. **Kelly Criterion** (fractional):
   The Kelly Criterion is a formula that calculates the theoretically
   optimal bet size to maximise the long-term growth rate of your
   bankroll.

   Full Kelly formula:
     f* = (p × b - 1) / (b - 1)
   Where:
     f* = fraction of bankroll to bet
     p  = true probability of winning (our model's estimate)
     b  = decimal odds offered by the bookmaker

   **Worked example:**
     Model says: 60% chance of Arsenal winning (p = 0.60)
     Bet365 offers: decimal odds of 2.10 (b = 2.10)

     f* = (0.60 × 2.10 - 1) / (2.10 - 1)
        = (1.26 - 1) / 1.10
        = 0.26 / 1.10
        = 0.2364  (23.64% of bankroll!)

   Full Kelly is extremely aggressive — betting 23.6% of your bankroll
   on a single match is a recipe for ruin if your probability estimates
   aren't perfect.  In practice, we use **fractional Kelly** (typically
   quarter-Kelly, i.e. kelly_fraction = 0.25):

     stake = f* × kelly_fraction × current_bankroll
           = 0.2364 × 0.25 × $1000
           = $59.09

   **When model_prob × odds < 1** (negative expected value), the Kelly
   formula yields a negative number, meaning "don't bet".  We return
   stake = 0 in this case.

Safety Limits
-------------
Four safety limits protect the bankroll from catastrophic loss:

- **Max bet cap** (5%): No single bet exceeds 5% of current bankroll,
  regardless of what the staking method calculates.
- **Daily loss limit** (10%): If total losses today exceed 10% of the
  starting bankroll, stop betting for the day.
- **Drawdown alert** (25%): If the bankroll drops 25% below its all-time
  peak, flag a warning (still allows betting, but alerts the user).
- **Minimum bankroll** (50%): If the bankroll drops below 50% of the
  starting amount, switch to paper trading only.

Master Plan refs: MP §4 Bankroll Management, MP §7 Bankroll Manager Interface,
                  MP §12 Glossary (bankroll, flat staking, Kelly)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional

from src.config import config
from src.database.db import get_session
from src.database.models import BetLog, User

logger = logging.getLogger(__name__)


# ============================================================================
# Stake Result Dataclass
# ============================================================================

@dataclass
class StakeResult:
    """Result of a stake calculation.

    Contains the recommended stake amount and any safety warnings
    that were triggered during calculation.
    """
    stake: float               # Recommended stake in currency units
    method: str                # Staking method used: flat/percentage/kelly
    safety_warnings: Dict[str, bool]  # Which safety limits were triggered
    message: str               # Human-readable summary


# ============================================================================
# Bankroll Manager
# ============================================================================

class BankrollManager:
    """Calculates bet stakes and enforces safety limits.

    Reads user-specific settings (staking method, percentages, bankroll)
    from the ``users`` table and safety limits from ``config/settings.yaml``.
    """

    def calculate_stake(
        self,
        user_id: int,
        model_prob: float,
        odds: float,
        league: Optional[str] = None,
    ) -> StakeResult:
        """Calculate the recommended stake for a value bet.

        Reads the user's staking method and bankroll from the database,
        applies the appropriate formula, then enforces all safety limits.

        The method also enforces two aggregate daily exposure caps that
        prevent over-committing capital on a single day:

        - **max_daily_exposure** (15%): the total amount staked across ALL
          leagues today must not exceed 15% of the current bankroll.  Without
          this cap, 10 value bets at 5% each would put 50% of the bankroll
          at risk simultaneously.

        - **max_league_daily_exposure** (8%): the total staked on a single
          league today must not exceed 8%.  This prevents concentration risk
          (e.g. loading up on 5 Championship bets while the league is in form).

        When a cap is hit the function returns stake=0 and logs a warning.
        The pipeline still logs the value bet as a system_pick (with stake=0)
        so that model performance tracking is unaffected.

        Parameters
        ----------
        user_id : int
            Database ID of the user.
        model_prob : float
            Model's estimated probability of the outcome (0.0–1.0).
        odds : float
            Decimal odds offered by the bookmaker (e.g. 2.10).
        league : str, optional
            Short name of the league (e.g. "EPL", "LaLiga").  Required for
            per-league exposure checks; if None the league cap is skipped.

        Returns
        -------
        StakeResult
            The recommended stake and any safety warnings.
        """
        # Load user settings from the database
        user = self._get_user(user_id)
        if user is None:
            return StakeResult(
                stake=0.0,
                method="unknown",
                safety_warnings={},
                message=f"User {user_id} not found",
            )

        # Check safety limits before calculating stake
        safety = self.check_safety_limits(user_id)

        # If daily loss limit or minimum bankroll hit, return 0 stake
        if safety["daily_limit_hit"] or safety["min_bankroll_hit"]:
            return StakeResult(
                stake=0.0,
                method=user["staking_method"],
                safety_warnings=safety,
                message=safety["message"],
            )

        # --- Aggregate daily exposure caps ---
        # Professional betting operations limit total daily deployment to
        # 15–20 % of bankroll.  Without this, many value bets on the same
        # day can put 50 %+ at risk simultaneously.
        #
        # We read both caps from config with graceful fallback to None
        # (None means "no cap") so that existing installs without these
        # config keys continue to work.
        safety_cfg = config.settings.safety
        max_daily_exp = getattr(safety_cfg, "max_daily_exposure", None)
        max_league_exp = getattr(safety_cfg, "max_league_daily_exposure", None)

        bankroll_for_cap = user["current_bankroll"]

        if max_daily_exp is not None:
            today_staked_all = self._get_daily_staked(user_id, league=None)
            daily_cap_amount = bankroll_for_cap * max_daily_exp
            if today_staked_all >= daily_cap_amount:
                logger.warning(
                    "Daily exposure cap hit for user %d: "
                    "$%.2f staked today >= $%.2f cap (%.0f%% of $%.2f bankroll). "
                    "Returning stake=0.",
                    user_id,
                    today_staked_all,
                    daily_cap_amount,
                    max_daily_exp * 100,
                    bankroll_for_cap,
                )
                return StakeResult(
                    stake=0.0,
                    method=user["staking_method"],
                    safety_warnings={**safety, "daily_exposure_cap_hit": True},
                    message=(
                        f"Daily exposure cap hit: ${today_staked_all:.2f} already "
                        f"staked today (limit: ${daily_cap_amount:.2f} = "
                        f"{max_daily_exp:.0%} of bankroll). No more bets today."
                    ),
                )

        if max_league_exp is not None and league is not None:
            today_staked_league = self._get_daily_staked(user_id, league=league)
            league_cap_amount = bankroll_for_cap * max_league_exp
            if today_staked_league >= league_cap_amount:
                logger.warning(
                    "League daily exposure cap hit for user %d, league %s: "
                    "$%.2f staked today >= $%.2f cap (%.0f%% of $%.2f bankroll). "
                    "Returning stake=0.",
                    user_id,
                    league,
                    today_staked_league,
                    league_cap_amount,
                    max_league_exp * 100,
                    bankroll_for_cap,
                )
                return StakeResult(
                    stake=0.0,
                    method=user["staking_method"],
                    safety_warnings={**safety, "league_exposure_cap_hit": True},
                    message=(
                        f"{league} exposure cap hit: ${today_staked_league:.2f} "
                        f"already staked on {league} today "
                        f"(limit: ${league_cap_amount:.2f} = "
                        f"{max_league_exp:.0%} of bankroll). "
                        f"No more {league} bets today."
                    ),
                )

        # Calculate raw stake based on the user's chosen method.
        # PC-25-15: Per-league staking method override.  If the league has
        # staking_method=kelly in its strategy config AND the user has Kelly
        # configured, use Kelly for that league.  Otherwise use the user's
        # default method.  This allows Championship (🟢 profitable) to use
        # Kelly while all other leagues stay on flat staking.
        method = user["staking_method"]
        bankroll = user["current_bankroll"]
        kelly_max_bet_override = None
        drawdown_rollback_pct = None

        if league is not None:
            for lg_cfg in config.leagues:
                if getattr(lg_cfg, "short_name", None) == league:
                    lg_strategy = getattr(lg_cfg, "strategy", None)
                    if lg_strategy is not None:
                        lg_staking = getattr(lg_strategy, "staking_method", None)
                        if lg_staking == "kelly":
                            method = "kelly"
                            kelly_max_bet_override = getattr(
                                lg_strategy, "kelly_max_bet_pct", None
                            )
                            drawdown_rollback_pct = getattr(
                                lg_strategy, "drawdown_rollback_pct", None
                            )
                        elif lg_staking == "flat":
                            method = "flat"
                    break

        if method == "kelly":
            raw_stake = self._kelly_stake(
                model_prob=model_prob,
                odds=odds,
                kelly_fraction=user["kelly_fraction"],
                bankroll=bankroll,
            )
        else:
            # Both "flat" and "percentage" use the same formula:
            # stake = current_bankroll × stake_percentage
            # The difference is that "percentage" recalculates after each bet
            # (which happens naturally since we always read current_bankroll)
            raw_stake = bankroll * user["stake_percentage"]

        # --- PC-25-09: Per-league stake multiplier ---
        # Each league has a stake_multiplier in its strategy config that scales
        # the base stake up or down based on the league's assessment tier:
        #   🟢 Profitable  → 1.5× (lean into verified edge)
        #   🟡 Promising   → 1.0× (standard stake)
        #   🔴 Unprofitable → 0.5× (reduce exposure, keep learning)
        #   ⚪ Insufficient → 0.5× (small stakes to gather data)
        #
        # Applied BEFORE the max bet cap so the safety ceiling still protects.
        # The multiplier is read from leagues.yaml strategy block — if the league
        # has no strategy block or no multiplier, we default to 1.0 (no change).
        stake_multiplier = 1.0
        if league is not None:
            for lg_cfg in config.leagues:
                if getattr(lg_cfg, "short_name", None) == league:
                    lg_strategy = getattr(lg_cfg, "strategy", None)
                    if lg_strategy is not None:
                        stake_multiplier = getattr(
                            lg_strategy, "stake_multiplier", 1.0
                        )
                    break

        multiplied_stake = raw_stake * stake_multiplier

        # Apply max bet cap: no single bet exceeds max_bet_percentage of bankroll.
        # PC-25-15: Kelly leagues use a stricter cap (3% vs global 5%).
        # This is a hard safety limit — even Kelly can't exceed it.
        max_bet_pct = config.settings.safety.max_bet_percentage
        if kelly_max_bet_override is not None:
            max_bet_pct = min(max_bet_pct, kelly_max_bet_override)
        max_stake = bankroll * max_bet_pct
        capped_stake = min(multiplied_stake, max_stake)

        # Round to 2 decimal places (currency)
        final_stake = round(max(0.0, capped_stake), 2)

        # Build message
        multiplier_note = ""
        if stake_multiplier != 1.0:
            multiplier_note = f" (×{stake_multiplier:.1f} {league} multiplier)"

        if final_stake == 0.0 and method == "kelly":
            msg = (
                f"Kelly stake is $0 — negative expected value "
                f"(model_prob × odds = {model_prob * odds:.3f} < 1.0)"
            )
        elif capped_stake < multiplied_stake:
            msg = (
                f"Stake capped at {max_bet_pct:.0%} of bankroll "
                f"(${max_stake:.2f}). "
                f"Raw {method} stake was ${raw_stake:.2f}{multiplier_note}."
            )
        else:
            msg = (
                f"{method.capitalize()} stake: "
                f"${final_stake:.2f} "
                f"({final_stake/bankroll:.1%} of bankroll){multiplier_note}"
            )

        # Include drawdown warning if applicable
        if safety["drawdown_warning"]:
            msg += " WARNING: Bankroll is 25%+ below peak."

        return StakeResult(
            stake=final_stake,
            method=method,
            safety_warnings=safety,
            message=msg,
        )

    def check_safety_limits(self, user_id: int) -> Dict:
        """Check all safety limits for a user.

        Returns a dict with boolean flags for each limit and a combined
        message explaining which limits are triggered.

        Parameters
        ----------
        user_id : int
            Database ID of the user.

        Returns
        -------
        dict
            Keys: daily_limit_hit, drawdown_warning, min_bankroll_hit, message.
        """
        user = self._get_user(user_id)
        if user is None:
            return {
                "daily_limit_hit": False,
                "drawdown_warning": False,
                "min_bankroll_hit": False,
                "message": f"User {user_id} not found",
            }

        starting = user["starting_bankroll"]
        current = user["current_bankroll"]

        # Load safety thresholds from config
        safety_cfg = config.settings.safety
        daily_loss_pct = safety_cfg.daily_loss_limit           # 0.10 = 10%
        drawdown_pct = safety_cfg.drawdown_alert_threshold     # 0.25 = 25%
        min_bankroll_pct = safety_cfg.minimum_bankroll_percentage  # 0.50 = 50%

        # --- Daily loss limit ---
        # Sum all losses from bets resolved today
        # If daily losses exceed daily_loss_limit × starting_bankroll, flag it
        daily_losses = self._get_daily_losses(user_id)
        daily_limit_amount = starting * daily_loss_pct
        daily_limit_hit = daily_losses >= daily_limit_amount

        # --- Drawdown alert ---
        # Check if current bankroll is 25%+ below peak
        # Peak = max historical bankroll (or starting, whichever is higher)
        peak_bankroll = self._get_peak_bankroll(user_id)
        drawdown_threshold = peak_bankroll * (1 - drawdown_pct)
        drawdown_warning = current < drawdown_threshold

        # --- Minimum bankroll ---
        # If bankroll drops below 50% of starting amount, paper trade only
        min_bankroll = starting * min_bankroll_pct
        min_bankroll_hit = current < min_bankroll

        # Build message
        messages = []
        if daily_limit_hit:
            messages.append(
                f"Daily loss limit hit: ${daily_losses:.2f} lost today "
                f"(limit: ${daily_limit_amount:.2f}). No more bets today."
            )
        if drawdown_warning:
            drawdown_actual = (peak_bankroll - current) / peak_bankroll
            messages.append(
                f"Drawdown warning: Bankroll ${current:.2f} is "
                f"{drawdown_actual:.1%} below peak ${peak_bankroll:.2f}."
            )
        if min_bankroll_hit:
            messages.append(
                f"Minimum bankroll breached: ${current:.2f} is below "
                f"${min_bankroll:.2f} (50% of starting). "
                f"Paper trading only."
            )
        if not messages:
            messages.append("All safety limits OK.")

        return {
            "daily_limit_hit": daily_limit_hit,
            "drawdown_warning": drawdown_warning,
            "min_bankroll_hit": min_bankroll_hit,
            "message": " ".join(messages),
        }

    # --- Staking formulas ---------------------------------------------------

    @staticmethod
    def _kelly_stake(
        model_prob: float,
        odds: float,
        kelly_fraction: float,
        bankroll: float,
    ) -> float:
        """Calculate fractional Kelly Criterion stake.

        The Kelly Criterion determines the optimal fraction of your
        bankroll to bet in order to maximise long-term growth.

        Formula: f* = (p × b - 1) / (b - 1)
        Where:
          p = model probability of winning
          b = decimal odds

        We then multiply by kelly_fraction (typically 0.25 for quarter-Kelly)
        and the current bankroll to get the actual stake amount.

        **Worked example:**
          p = 0.60 (model says 60% chance)
          b = 2.10 (bookmaker offers 2.10)
          kelly_fraction = 0.25 (quarter-Kelly)
          bankroll = $1000

          f* = (0.60 × 2.10 - 1) / (2.10 - 1)
             = (1.26 - 1) / 1.10
             = 0.2364

          stake = 0.2364 × 0.25 × $1000 = $59.09

        If model_prob × odds < 1, the expected value is negative and we
        should NOT bet.  The formula returns a negative fraction, which
        we clamp to 0.

        Parameters
        ----------
        model_prob : float
            Model's probability of the outcome.
        odds : float
            Decimal bookmaker odds.
        kelly_fraction : float
            Fractional Kelly multiplier (0.25 = quarter-Kelly).
        bankroll : float
            Current bankroll amount.

        Returns
        -------
        float
            Recommended stake (>= 0.0).
        """
        # Check for negative expected value
        # If model_prob × odds < 1, the bet has negative EV — don't bet
        if model_prob * odds < 1.0:
            return 0.0

        # Guard against division by zero (odds of exactly 1.0)
        if odds <= 1.0:
            return 0.0

        # Full Kelly fraction: f* = (p × b - 1) / (b - 1)
        full_kelly = (model_prob * odds - 1.0) / (odds - 1.0)

        # Apply fractional Kelly to reduce variance
        # Quarter-Kelly (0.25) is the standard conservative approach
        stake = full_kelly * kelly_fraction * bankroll

        # Clamp to non-negative (shouldn't be needed after the check above,
        # but belt-and-suspenders)
        return max(0.0, stake)

    # --- Database helpers ---------------------------------------------------

    @staticmethod
    def _get_user(user_id: int) -> Optional[Dict]:
        """Load user settings from the database."""
        with get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if user is None:
                return None
            return {
                "id": user.id,
                "starting_bankroll": user.starting_bankroll,
                "current_bankroll": user.current_bankroll,
                "staking_method": user.staking_method,
                "stake_percentage": user.stake_percentage,
                "kelly_fraction": user.kelly_fraction,
                "edge_threshold": user.edge_threshold,
            }

    @staticmethod
    def _get_daily_staked(user_id: int, league: Optional[str] = None) -> float:
        """Sum all stakes placed today for a user, optionally filtered by league.

        **Aggregate daily exposure** is the total amount of real capital
        committed today across all pending and resolved bets.  This is
        distinct from daily losses: a stake is committed the moment it is
        logged, regardless of whether the bet has settled yet.

        We include all bet statuses (pending, won, lost, etc.) so that
        even unsettled bets count towards the cap — they represent real
        exposure until the result is known.

        Parameters
        ----------
        user_id : int
            Database ID of the user.
        league : str or None
            If provided, sum only bets on this league.  If None, sum all
            leagues (used for the aggregate daily cap check).

        Returns
        -------
        float
            Total amount staked today, in currency units.
        """
        today = date.today().isoformat()

        with get_session() as session:
            query = session.query(BetLog).filter(
                BetLog.user_id == user_id,
                BetLog.date == today,
            )
            if league is not None:
                query = query.filter(BetLog.league == league)
            bets = query.all()

            total_staked = sum(b.stake or 0.0 for b in bets)

        return total_staked

    @staticmethod
    def _get_daily_losses(user_id: int) -> float:
        """Sum all losses from bets resolved today.

        Includes bets with status 'lost' or 'half_lost'.  The pnl column
        stores the profit/loss (negative for losses).

        Returns the absolute value of losses (positive number).
        """
        today = date.today().isoformat()

        with get_session() as session:
            # Query bets resolved today that are losses
            losses = (
                session.query(BetLog)
                .filter(
                    BetLog.user_id == user_id,
                    BetLog.date == today,
                    BetLog.status.in_(["lost", "half_lost"]),
                )
                .all()
            )

            # Sum the absolute losses (pnl is negative for losses)
            total_loss = sum(abs(bet.pnl or 0.0) for bet in losses)

        return total_loss

    @staticmethod
    def _get_peak_bankroll(user_id: int) -> float:
        """Get the peak (all-time high) bankroll for a user.

        Looks at the bankroll_after column in bet_log to find the maximum
        historical bankroll value.  Falls back to starting_bankroll if no
        bets have been placed yet.
        """
        with get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if user is None:
                return 0.0

            # Check bet history for peak bankroll
            bets = (
                session.query(BetLog.bankroll_after)
                .filter(
                    BetLog.user_id == user_id,
                    BetLog.bankroll_after.isnot(None),
                )
                .all()
            )

            if bets:
                historical_peak = max(b[0] for b in bets)
                # Peak is the max of starting bankroll and historical peak
                return max(user.starting_bankroll, historical_peak)

            # No bet history — peak is the starting bankroll
            return max(user.starting_bankroll, user.current_bankroll)
