"""
BetVector — Market Feedback Loop (E12-04)
==========================================
Tracks the system's performance broken down by league × market type.
Over time, learns where BetVector has a genuine edge and where it doesn't.

Runs weekly (Sunday evening) as part of the evening pipeline.  For every
league × market combination with enough resolved bets, computes:
  - ROI (return on investment = total P&L / total staked)
  - 95% confidence interval for ROI (via bootstrap resampling)
  - A three-tier assessment: profitable / promising / insufficient / unprofitable

Assessment tiers (MP §11.4):
  profitable   — ROI > 0 AND CI lower bound > 0 AND n >= 250
  promising    — ROI > 0 but CI includes zero, OR 50 <= n < 250
  insufficient — n < 50 (not enough data to assess)
  unprofitable — ROI < 0 AND CI upper bound < 0 AND n >= 250

This module only reports and warns — it NEVER auto-filters or suppresses
value bets.  The decision to stop betting on a combination is always
made by the human operator.

Master Plan refs: MP §11.4 Odds Market Feedback Loop
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.config import config
from src.database.db import get_session
from src.database.models import BetLog, MarketPerformance

logger = logging.getLogger(__name__)


# ============================================================================
# Public API
# ============================================================================

def update_market_performance(
    period_end: Optional[str] = None,
) -> List[MarketPerformance]:
    """Compute and store ROI + assessment for every league × market combination.

    Called weekly (Sunday evening) from the pipeline.  Analyses ALL resolved
    system_pick bets to date and stores a snapshot in ``market_performance``.

    Parameters
    ----------
    period_end : str, optional
        ISO date string for the period end (default: today).

    Returns
    -------
    list of MarketPerformance
        All newly stored performance records.
    """
    if period_end is None:
        period_end = datetime.utcnow().strftime("%Y-%m-%d")

    mf_cfg = config.settings.self_improvement.market_feedback
    min_bets = mf_cfg.min_sample_size              # 50
    profitable_min = mf_cfg.profitable_min_bets     # 250 (PC-25-06: raised from 100)

    # Gather all resolved system_pick bets grouped by league × market
    combos = _gather_resolved_bets()

    if not combos:
        print("  → No resolved bets found for market performance analysis")
        return []

    records = []

    for (league, market_type), bets in combos.items():
        n = len(bets)
        stakes = [b["stake"] for b in bets]
        pnls = [b["pnl"] for b in bets]
        total_staked = sum(stakes)
        total_pnl = sum(pnls)

        # ROI = total P&L / total staked
        roi = total_pnl / total_staked if total_staked > 0 else 0.0

        # Wins and losses
        wins = sum(1 for b in bets if b["status"] == "won")
        losses = sum(1 for b in bets if b["status"] == "lost")

        # Compute 95% CI via bootstrap resampling
        ci_lower, ci_upper = _bootstrap_roi_ci(stakes, pnls)

        # Determine assessment tier
        assessment = _assess(roi, ci_lower, ci_upper, n, min_bets, profitable_min)

        records.append({
            "league": league,
            "market_type": market_type,
            "period_end": period_end,
            "total_bets": n,
            "wins": wins,
            "losses": losses,
            "total_staked": round(total_staked, 2),
            "total_pnl": round(total_pnl, 2),
            "roi": round(roi, 6),
            "roi_ci_lower": round(ci_lower, 6) if ci_lower is not None else None,
            "roi_ci_upper": round(ci_upper, 6) if ci_upper is not None else None,
            "assessment": assessment,
        })

    # Store in database
    stored = _store_market_performance(records)

    # Print summary
    for r in records:
        emoji = {
            "profitable": "🟢",
            "promising": "🟡",
            "insufficient": "⚪",
            "unprofitable": "🔴",
        }.get(r["assessment"], "")
        ci_str = ""
        if r["roi_ci_lower"] is not None:
            ci_str = f" (95% CI: {r['roi_ci_lower']:.1%} to {r['roi_ci_upper']:.1%})"
        print(f"  → {emoji} {r['league']} {r['market_type']}: "
              f"ROI {r['roi']:.1%}{ci_str} "
              f"[{r['assessment']}] ({r['total_bets']} bets)")

    return stored


def get_warnings() -> List[Dict[str, str]]:
    """Get warning messages for unprofitable league × market combinations.

    Returns human-readable warnings for combinations assessed as
    'unprofitable'.  These are displayed in the Today's Picks page
    as cautions — the system NEVER auto-suppresses bets.

    Returns
    -------
    list of dict
        Each dict has: league, market_type, roi, total_bets, message.
    """
    with get_session() as session:
        # Get the latest period_end
        latest = (
            session.query(MarketPerformance.period_end)
            .order_by(MarketPerformance.period_end.desc())
            .first()
        )
        if not latest:
            return []

        unprofitable = (
            session.query(MarketPerformance)
            .filter(
                MarketPerformance.period_end == latest[0],
                MarketPerformance.assessment == "unprofitable",
            )
            .all()
        )

    warnings = []
    for mp in unprofitable:
        warnings.append({
            "league": mp.league,
            "market_type": mp.market_type,
            "roi": mp.roi,
            "total_bets": mp.total_bets,
            "message": (
                f"⚠️ BetVector has historically underperformed in "
                f"{mp.league} {mp.market_type} "
                f"(ROI: {mp.roi:.1%} over {mp.total_bets} bets). "
                f"Proceed with caution."
            ),
        })

    return warnings


def detect_tier_transitions(
    current_period: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Detect league-level tier transitions from the two most recent assessments.

    Compares the current period's market performance assessments with the
    previous period's for each league.  A "transition" is any league whose
    overall assessment tier changed (e.g., 🟡 promising → 🟢 profitable).

    League-level tier is the BEST (most optimistic) tier across all market
    types for that league — because if ANY market is profitable, the league
    is worth tracking.

    Parameters
    ----------
    current_period : str, optional
        ISO date for the current period (default: latest in DB).

    Returns
    -------
    list of dict
        Each dict has: league, old_tier, new_tier, direction, detail.
        ``direction`` is "upgrade", "downgrade", or "lateral".
    """
    TIER_RANK = {
        "profitable": 4,
        "promising": 3,
        "insufficient": 2,
        "unprofitable": 1,
    }

    with get_session() as session:
        # Find the two most recent distinct period_end dates
        periods = (
            session.query(MarketPerformance.period_end)
            .distinct()
            .order_by(MarketPerformance.period_end.desc())
            .limit(2)
            .all()
        )
        if len(periods) < 2:
            # Need at least two periods to detect transitions
            return []

        current = periods[0][0] if current_period is None else current_period
        previous = periods[1][0] if current_period is None else periods[0][0]

        # If caller specified current_period, find the one before it
        if current_period is not None:
            prev_result = (
                session.query(MarketPerformance.period_end)
                .filter(MarketPerformance.period_end < current_period)
                .distinct()
                .order_by(MarketPerformance.period_end.desc())
                .first()
            )
            if not prev_result:
                return []
            previous = prev_result[0]

        # Get all records for current and previous periods
        current_records = (
            session.query(MarketPerformance)
            .filter(MarketPerformance.period_end == current)
            .all()
        )
        previous_records = (
            session.query(MarketPerformance)
            .filter(MarketPerformance.period_end == previous)
            .all()
        )

    # Aggregate to league-level tier (best tier across all markets)
    def _league_tier(records: list) -> Dict[str, str]:
        league_tiers: Dict[str, str] = {}
        for r in records:
            existing = league_tiers.get(r.league, "insufficient")
            if TIER_RANK.get(r.assessment, 0) > TIER_RANK.get(existing, 0):
                league_tiers[r.league] = r.assessment
        return league_tiers

    curr_tiers = _league_tier(current_records)
    prev_tiers = _league_tier(previous_records)

    # Detect transitions
    transitions: List[Dict[str, str]] = []
    all_leagues = set(curr_tiers.keys()) | set(prev_tiers.keys())

    tier_emoji = {
        "profitable": "🟢",
        "promising": "🟡",
        "insufficient": "⚪",
        "unprofitable": "🔴",
    }

    for league in sorted(all_leagues):
        old_tier = prev_tiers.get(league, "insufficient")
        new_tier = curr_tiers.get(league, "insufficient")

        if old_tier == new_tier:
            continue

        old_rank = TIER_RANK.get(old_tier, 0)
        new_rank = TIER_RANK.get(new_tier, 0)
        direction = "upgrade" if new_rank > old_rank else "downgrade"

        transitions.append({
            "league": league,
            "old_tier": old_tier,
            "new_tier": new_tier,
            "direction": direction,
            "detail": (
                f"{tier_emoji.get(old_tier, '')} {old_tier} → "
                f"{tier_emoji.get(new_tier, '')} {new_tier}"
            ),
        })

    if transitions:
        logger.info(
            "Detected %d tier transition(s): %s",
            len(transitions),
            ", ".join(f"{t['league']} {t['detail']}" for t in transitions),
        )

    return transitions


def generate_strategy_suggestions(
    transitions: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Generate strategy change suggestions based on tier transitions.

    These are SUGGESTIONS ONLY — they are never auto-applied.  The human
    operator reviews each suggestion in the weekly email and decides whether
    to update ``config/leagues.yaml`` manually.

    Parameters
    ----------
    transitions : list of dict
        Output from ``detect_tier_transitions()``.

    Returns
    -------
    list of dict
        Each dict has: league, suggestion, reason, action.
    """
    suggestions: List[Dict[str, str]] = []

    for t in transitions:
        league = t["league"]
        new_tier = t["new_tier"]
        old_tier = t["old_tier"]
        direction = t["direction"]

        if direction == "upgrade" and new_tier == "profitable":
            # Upgrade to profitable — suggest increasing exposure
            suggestions.append({
                "league": league,
                "suggestion": f"Consider increasing {league} stake_multiplier to 1.5",
                "reason": (
                    f"{league} upgraded from {old_tier} to profitable. "
                    f"CI lower bound is above zero with sufficient sample size. "
                    f"Edge appears statistically significant."
                ),
                "action": "increase_exposure",
            })
        elif direction == "upgrade" and new_tier == "promising":
            # Upgrade to promising — suggest standard exposure
            suggestions.append({
                "league": league,
                "suggestion": f"Consider setting {league} stake_multiplier to 1.0",
                "reason": (
                    f"{league} upgraded from {old_tier} to promising. "
                    f"ROI is positive but CI still crosses zero. "
                    f"Keep monitoring — may confirm edge with more data."
                ),
                "action": "maintain_exposure",
            })
        elif direction == "downgrade" and new_tier == "unprofitable":
            # Downgrade to unprofitable — suggest reducing exposure
            suggestions.append({
                "league": league,
                "suggestion": (
                    f"Consider reducing {league} stake_multiplier to 0.5 "
                    f"and setting auto_bet to false"
                ),
                "reason": (
                    f"{league} downgraded to unprofitable. "
                    f"CI upper bound is below zero with sufficient sample size. "
                    f"Reduce exposure but continue tracking for potential recovery."
                ),
                "action": "reduce_exposure",
            })
        elif direction == "downgrade":
            # Any other downgrade — suggest caution
            suggestions.append({
                "league": league,
                "suggestion": f"Review {league} — tier dropped from {old_tier} to {new_tier}",
                "reason": (
                    f"{league} downgraded from {old_tier} to {new_tier}. "
                    f"Performance may be declining. Review recent bet results "
                    f"and CLV trends before making changes."
                ),
                "action": "review",
            })

    return suggestions


def compute_shadow_pnl(league: Optional[str] = None) -> Dict[str, Any]:
    """Compute shadow P&L for leagues currently in shadow mode.

    Shadow bets are stored in ``shadow_value_bets`` (PC-25-12).  This function
    computes the hypothetical P&L for each active shadow strategy, comparing
    it against the corresponding live strategy.

    Parameters
    ----------
    league : str, optional
        If provided, compute only for this league.  Otherwise, compute for
        all leagues with resolved shadow bets.

    Returns
    -------
    dict
        Per-league shadow P&L summary:
        ``{league: {shadow_roi, live_roi, n_bets, pnl, strategy_change}}``.
    """
    from src.database.models import ShadowValueBet

    results: Dict[str, Any] = {}

    with get_session() as session:
        query = (
            session.query(ShadowValueBet)
            .filter(ShadowValueBet.result.in_(["won", "lost"]))
        )
        if league:
            query = query.filter(ShadowValueBet.league == league)

        shadow_bets = query.all()

    # Group by league
    by_league: Dict[str, list] = {}
    for sb in shadow_bets:
        by_league.setdefault(sb.league, []).append(sb)

    for lg, bets in by_league.items():
        total_stake = sum(b.shadow_stake for b in bets)
        total_pnl = sum(b.shadow_pnl or 0.0 for b in bets)
        shadow_roi = total_pnl / total_stake if total_stake > 0 else 0.0

        results[lg] = {
            "shadow_roi": round(shadow_roi, 6),
            "n_bets": len(bets),
            "pnl": round(total_pnl, 2),
            "total_staked": round(total_stake, 2),
            "strategy_change": bets[0].strategy_change if bets else "",
        }

    return results


def generate_shadow_comparison(min_weeks: int = 4) -> List[Dict[str, Any]]:
    """Generate comparison report: shadow vs live strategy performance.

    After ``min_weeks`` of shadow data, compares shadow P&L against live P&L
    for the same period.  Only promotes to live if shadow outperforms by >3pp ROI.

    Parameters
    ----------
    min_weeks : int
        Minimum weeks of shadow data required before generating a report.
        Default: 4 (one full month of Sunday-to-Sunday data).

    Returns
    -------
    list of dict
        Each dict has: league, shadow_roi, live_roi, roi_diff,
        recommendation ("promote" / "keep_shadow" / "abandon").
    """
    from datetime import timedelta
    from src.database.models import ShadowValueBet

    reports: List[Dict[str, Any]] = []

    with get_session() as session:
        # Find the earliest shadow bet per league
        from sqlalchemy import func as sqla_func
        earliest_by_league = (
            session.query(
                ShadowValueBet.league,
                sqla_func.min(ShadowValueBet.created_at).label("first_shadow"),
                sqla_func.count(ShadowValueBet.id).label("total_bets"),
            )
            .filter(ShadowValueBet.result.in_(["won", "lost"]))
            .group_by(ShadowValueBet.league)
            .all()
        )

    now_str = datetime.utcnow().strftime("%Y-%m-%d")

    for row in earliest_by_league:
        lg = row.league
        first_date = row.first_shadow
        n_bets = row.total_bets

        # Check if enough time has elapsed (min_weeks)
        try:
            first_dt = datetime.strptime(first_date[:10], "%Y-%m-%d")
            weeks_elapsed = (datetime.utcnow() - first_dt).days / 7
        except (ValueError, TypeError):
            continue

        if weeks_elapsed < min_weeks:
            continue

        # Get shadow P&L
        shadow = compute_shadow_pnl(league=lg)
        if lg not in shadow or shadow[lg]["n_bets"] < 10:
            continue

        shadow_roi = shadow[lg]["shadow_roi"]

        # Get live P&L for the same period from BetLog
        with get_session() as session:
            live_bets = (
                session.query(BetLog)
                .filter(
                    BetLog.league == lg,
                    BetLog.bet_type == "system_pick",
                    BetLog.status.in_(["won", "lost"]),
                    BetLog.date >= first_date[:10],
                )
                .all()
            )

        live_staked = sum(b.stake for b in live_bets) if live_bets else 0.0
        live_pnl = sum(b.pnl or 0.0 for b in live_bets) if live_bets else 0.0
        live_roi = live_pnl / live_staked if live_staked > 0 else 0.0

        roi_diff = shadow_roi - live_roi

        # Recommendation: promote only if shadow outperforms by >3pp (0.03)
        if roi_diff > 0.03:
            recommendation = "promote"
        elif roi_diff < -0.03:
            recommendation = "abandon"
        else:
            recommendation = "keep_shadow"

        reports.append({
            "league": lg,
            "shadow_roi": round(shadow_roi, 4),
            "live_roi": round(live_roi, 4),
            "roi_diff": round(roi_diff, 4),
            "n_shadow_bets": shadow[lg]["n_bets"],
            "n_live_bets": len(live_bets) if live_bets else 0,
            "weeks_elapsed": round(weeks_elapsed, 1),
            "recommendation": recommendation,
            "strategy_change": shadow[lg]["strategy_change"],
        })

    return reports


def get_market_summary() -> List[Dict]:
    """Get the latest market performance summary for all combinations.

    Used by the Model Health dashboard page for the "Market Edge Map"
    heatmap display.

    Returns
    -------
    list of dict
        Each dict contains: league, market_type, roi, roi_ci_lower,
        roi_ci_upper, assessment, total_bets.
    """
    with get_session() as session:
        latest = (
            session.query(MarketPerformance.period_end)
            .order_by(MarketPerformance.period_end.desc())
            .first()
        )
        if not latest:
            return []

        entries = (
            session.query(MarketPerformance)
            .filter(MarketPerformance.period_end == latest[0])
            .order_by(MarketPerformance.league, MarketPerformance.market_type)
            .all()
        )

    return [
        {
            "league": e.league,
            "market_type": e.market_type,
            "roi": e.roi,
            "roi_ci_lower": e.roi_ci_lower,
            "roi_ci_upper": e.roi_ci_upper,
            "assessment": e.assessment,
            "total_bets": e.total_bets,
            "wins": e.wins,
            "losses": e.losses,
            "total_pnl": e.total_pnl,
        }
        for e in entries
    ]


# ============================================================================
# Internal helpers
# ============================================================================

def _gather_resolved_bets() -> Dict[Tuple[str, str], List[dict]]:
    """Gather all resolved system_pick bets grouped by league × market_type.

    Only includes bets with status 'won' or 'lost' (not pending/void).
    """
    with get_session() as session:
        bets = (
            session.query(BetLog)
            .filter(
                BetLog.bet_type == "system_pick",
                BetLog.status.in_(["won", "lost"]),
            )
            .all()
        )

    combos: Dict[Tuple[str, str], List[dict]] = {}
    for bet in bets:
        key = (bet.league, bet.market_type)
        if key not in combos:
            combos[key] = []
        combos[key].append({
            "stake": bet.stake,
            "pnl": bet.pnl or 0.0,
            "status": bet.status,
        })

    return combos


def _bootstrap_roi_ci(
    stakes: List[float],
    pnls: List[float],
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
) -> Tuple[Optional[float], Optional[float]]:
    """Compute 95% confidence interval for ROI via bootstrap resampling.

    Resamples the bet-level data (stake, pnl) with replacement 1000 times,
    computes ROI for each sample, and returns the 2.5th and 97.5th
    percentiles as the confidence interval bounds.

    Parameters
    ----------
    stakes : list of float
        Stake amounts for each bet.
    pnls : list of float
        P&L for each bet.
    n_bootstrap : int
        Number of bootstrap samples (default: 1000).
    confidence : float
        Confidence level (default: 0.95 for 95% CI).

    Returns
    -------
    tuple of (float or None, float or None)
        (ci_lower, ci_upper).  None if insufficient data.
    """
    n = len(stakes)
    if n < 2:
        return None, None

    stakes_arr = np.array(stakes)
    pnls_arr = np.array(pnls)

    # Bootstrap: resample and compute ROI for each sample
    rng = np.random.default_rng(seed=42)
    roi_samples = []

    for _ in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        sample_stakes = stakes_arr[idx]
        sample_pnls = pnls_arr[idx]
        total_staked = sample_stakes.sum()
        if total_staked > 0:
            roi_samples.append(sample_pnls.sum() / total_staked)

    if not roi_samples:
        return None, None

    # Percentiles for the confidence interval
    alpha = (1 - confidence) / 2  # 0.025 for 95% CI
    ci_lower = float(np.percentile(roi_samples, alpha * 100))
    ci_upper = float(np.percentile(roi_samples, (1 - alpha) * 100))

    return ci_lower, ci_upper


def _assess(
    roi: float,
    ci_lower: Optional[float],
    ci_upper: Optional[float],
    n: int,
    min_bets: int,
    profitable_min: int,
) -> str:
    """Determine the assessment tier for a league × market combination.

    Tiers (MP §11.4):
      profitable   — ROI > 0 AND CI lower > 0 AND n >= 250
      promising    — ROI > 0 but CI includes 0, OR 50 <= n < 250
      insufficient — n < 50
      unprofitable — ROI < 0 AND CI upper < 0 AND n >= 250
    """
    # Insufficient data
    if n < min_bets:
        return "insufficient"

    # Need CI bounds for confident assessments
    if ci_lower is None or ci_upper is None:
        if roi > 0:
            return "promising"
        return "insufficient"

    # Profitable: ROI > 0, entire CI above zero, enough bets
    if roi > 0 and ci_lower > 0 and n >= profitable_min:
        return "profitable"

    # Unprofitable: ROI < 0, entire CI below zero, enough bets
    if roi < 0 and ci_upper < 0 and n >= profitable_min:
        return "unprofitable"

    # Promising: ROI > 0 but CI includes zero, or not enough for "profitable"
    if roi > 0:
        return "promising"

    # ROI < 0 but CI includes zero (or n < profitable_min) — still promising
    # because the data is inconclusive
    if n < profitable_min:
        return "promising"

    # ROI < 0 but CI includes zero — inconclusive, lean promising
    return "promising"


def _store_market_performance(
    records: List[dict],
) -> List[MarketPerformance]:
    """Store market performance records using INSERT OR REPLACE semantics.

    The market_performance table has a unique constraint on
    (league, market_type, period_end), so we use merge semantics.
    """
    stored = []

    with get_session() as session:
        for r in records:
            # Check for existing record
            existing = (
                session.query(MarketPerformance)
                .filter(
                    MarketPerformance.league == r["league"],
                    MarketPerformance.market_type == r["market_type"],
                    MarketPerformance.period_end == r["period_end"],
                )
                .first()
            )

            if existing:
                # Update existing
                existing.total_bets = r["total_bets"]
                existing.wins = r["wins"]
                existing.losses = r["losses"]
                existing.total_staked = r["total_staked"]
                existing.total_pnl = r["total_pnl"]
                existing.roi = r["roi"]
                existing.roi_ci_lower = r["roi_ci_lower"]
                existing.roi_ci_upper = r["roi_ci_upper"]
                existing.assessment = r["assessment"]
                existing.computed_at = datetime.utcnow().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                stored.append(existing)
            else:
                # Insert new
                mp = MarketPerformance(
                    league=r["league"],
                    market_type=r["market_type"],
                    period_end=r["period_end"],
                    total_bets=r["total_bets"],
                    wins=r["wins"],
                    losses=r["losses"],
                    total_staked=r["total_staked"],
                    total_pnl=r["total_pnl"],
                    roi=r["roi"],
                    roi_ci_lower=r["roi_ci_lower"],
                    roi_ci_upper=r["roi_ci_upper"],
                    assessment=r["assessment"],
                )
                session.add(mp)
                stored.append(mp)

    logger.info("Stored %d market performance records", len(stored))
    return stored
