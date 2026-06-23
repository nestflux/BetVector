"""
BetVector World Cup 2026 — Shadow Scorecard (WC-09-02)
======================================================
Self-assessment over WC shadow/tracked picks on finished matches: CLV (the
leading edge indicator), hit rate, flat-stake paper P&L, and calibration
(predicted vs actual). This is the rig that judges both the model and the
owner's decisions BEFORE any real money is risked — and the same rig that will
judge the Bayesian model (WC-09-07).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.database.db import get_session
from src.world_cup.models import WCMatch, WCValueBet

logger = logging.getLogger(__name__)

# Calibration bands on the model's probability for the pick.
_BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def settle_wc_pick(vb: WCValueBet, m: WCMatch) -> bool | None:
    """Did the pick win, given the finished match result? None if undecidable.

    Note: h2h on knockout matches settles on the stored (final) result; a
    90-minute draw that went to penalties is an edge case we accept for v1,
    since shadow picks are overwhelmingly group-stage.
    """
    hg, ag = m.home_goals, m.away_goals
    if hg is None or ag is None:
        return None
    total = hg + ag
    key = (vb.market_type, vb.selection)
    return {
        ("h2h", "home"): hg > ag,
        ("h2h", "draw"): hg == ag,
        ("h2h", "away"): ag > hg,
        ("totals", "over"): total > 2,    # over 2.5
        ("totals", "under"): total < 3,   # under 2.5
        ("btts", "yes"): hg > 0 and ag > 0,
        ("btts", "no"): hg == 0 or ag == 0,
    }.get(key)


def _calibration(picks: list[dict]) -> list[dict]:
    """Bin picks by model probability → predicted vs actual hit rate per band."""
    out = []
    for lo, hi in _BANDS:
        band = [p for p in picks if lo <= p["model_prob"] < hi]
        if not band:
            continue
        predicted = sum(p["model_prob"] for p in band) / len(band)
        actual = sum(1 for p in band if p["won"]) / len(band)
        out.append({
            "Prob band": f"{int(lo*100)}–{int(hi*100) if hi <= 1 else 100}%",
            "Predicted": f"{predicted:.0%}",
            "Actual": f"{actual:.0%}",
            "n": len(band),
        })
    return out


def compute_wc_scorecard() -> dict:
    """Aggregate the shadow scorecard over settled WC picks.

    Returns ``{"n": 0}`` when there are no settled picks yet (the common early
    state). CLV is computed only over picks that already have a closing line.
    """
    picks: list[dict] = []
    with get_session() as session:
        vbs = session.execute(
            select(WCValueBet).options(
                joinedload(WCValueBet.match).joinedload(WCMatch.home_team),
                joinedload(WCValueBet.match).joinedload(WCMatch.away_team),
            )
        ).unique().scalars().all()

        for vb in vbs:
            m = vb.match
            if not m or m.status != "finished" or m.home_goals is None:
                continue
            won = settle_wc_pick(vb, m)
            if won is None:
                continue
            picks.append({
                "clv": vb.clv,
                "won": bool(won),
                "odds": vb.best_odds,
                "model_prob": vb.model_prob,
            })

    n = len(picks)
    if n == 0:
        return {"n": 0}

    clvs = [p["clv"] for p in picks if p["clv"] is not None]
    wins = sum(1 for p in picks if p["won"])
    # Flat 1u stake: win → (odds-1) profit, loss → -1.
    pnl = sum((p["odds"] - 1) if p["won"] else -1.0 for p in picks)

    return {
        "n": n,
        "n_clv": len(clvs),
        "mean_clv": (sum(clvs) / len(clvs)) if clvs else None,
        "pct_positive_clv": (sum(1 for c in clvs if c > 0) / len(clvs)) if clvs else None,
        "hit_rate": wins / n,
        "wins": wins,
        "pnl_units": round(pnl, 2),
        "roi": round(pnl / n, 4),
        "calibration": _calibration(picks),
    }
