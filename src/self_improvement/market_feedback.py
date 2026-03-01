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
  profitable   — ROI > 0 AND CI lower bound > 0 AND n >= 100
  promising    — ROI > 0 but CI includes zero, OR 50 <= n < 100
  insufficient — n < 50 (not enough data to assess)
  unprofitable — ROI < 0 AND CI upper bound < 0 AND n >= 100

This module only reports and warns — it NEVER auto-filters or suppresses
value bets.  The decision to stop betting on a combination is always
made by the human operator.

Master Plan refs: MP §11.4 Odds Market Feedback Loop
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

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
    profitable_min = mf_cfg.profitable_min_bets     # 100

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
      profitable   — ROI > 0 AND CI lower > 0 AND n >= 100
      promising    — ROI > 0 but CI includes 0, OR 50 <= n < 100
      insufficient — n < 50
      unprofitable — ROI < 0 AND CI upper < 0 AND n >= 100
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
