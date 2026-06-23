"""
BetVector World Cup 2026 — Research Data Layer (WC-09-03)
=========================================================
Per-match decision-support data for the research card (WC-09-04): best price
across books, de-vigged market consensus, model-vs-market edge, and line
movement (opening vs current consensus). All read-only over stored odds +
predictions — no new API cost.

Line movement uses ``WCOdds.opening_odds`` (the frozen first-seen price); when
only a single snapshot exists, movement is None and the UI shows "—".
"""

from __future__ import annotations

import logging
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.database.db import get_session
from src.world_cup.models import WCMatch
from src.world_cup.predictor import MODEL_NAME
from src.world_cup.value_finder import _canonical_selection

logger = logging.getLogger(__name__)

# Market groups whose selections must de-vig together (sum to 1).
_GROUPS = {
    "h2h": ["home", "draw", "away"],
    "totals": ["over", "under"],
}


_SHORT_LABELS = {
    ("h2h", "home"): "Home", ("h2h", "draw"): "Draw", ("h2h", "away"): "Away",
    ("totals", "over"): "Over 2.5", ("totals", "under"): "Under 2.5",
}


def _model_probs(pred) -> dict:
    """Model probability per canonical selection, or {} when no prediction."""
    if not pred:
        return {}
    over = pred.over_25_prob
    return {
        ("h2h", "home"): pred.home_win_prob,
        ("h2h", "draw"): pred.draw_prob,
        ("h2h", "away"): pred.away_win_prob,
        ("totals", "over"): over,
        ("totals", "under"): (1.0 - over) if over is not None else None,
    }


def _devig(implied: dict) -> dict:
    total = sum(implied.values())
    return {k: v / total for k, v in implied.items()} if total > 0 else dict(implied)


def _collect(odds, home_name: str, away_name: str) -> dict:
    """(market, canonical_sel) → {cur: [prices], open: [prices], best: (odds, book)}."""
    data: dict = {}
    for o in odds:
        canon = _canonical_selection(o.market_type, o.selection, home_name, away_name, o.point)
        if not canon:
            continue
        d = data.setdefault((o.market_type, canon), {"cur": [], "open": [], "best": (0.0, "")})
        d["cur"].append(o.odds_decimal)
        if o.opening_odds:
            d["open"].append(o.opening_odds)
        if o.odds_decimal > d["best"][0]:
            d["best"] = (o.odds_decimal, o.bookmaker)
    return data


def _consensus(data: dict, market: str, sels: list[str]):
    """De-vigged current + opening consensus prob per selection, or (None, None)
    when the market group is incomplete (can't de-vig)."""
    implied_cur, implied_open = {}, {}
    for sel in sels:
        d = data.get((market, sel))
        if not d or not d["cur"]:
            return None, None
        implied_cur[sel] = 1.0 / median(d["cur"])
        if d["open"]:
            implied_open[sel] = 1.0 / median(d["open"])
    cur = _devig(implied_cur)
    opn = _devig(implied_open) if len(implied_open) == len(sels) else None
    return cur, opn


def build_research_card(match_id: int) -> dict | None:
    """Assemble the research-card data for one match: per-selection model prob,
    de-vigged market prob, edge, best price + book, and line movement."""
    with get_session() as session:
        m = session.execute(
            select(WCMatch)
            .where(WCMatch.id == match_id)
            .options(
                joinedload(WCMatch.home_team),
                joinedload(WCMatch.away_team),
                joinedload(WCMatch.odds),
                joinedload(WCMatch.predictions),
            )
        ).unique().scalar_one_or_none()
        if not m:
            return None

        home = m.home_team.name if m.home_team else "?"
        away = m.away_team.name if m.away_team else "?"
        home_fifa = m.home_team.fifa_code if m.home_team else None
        away_fifa = m.away_team.fifa_code if m.away_team else None
        pred = next((p for p in m.predictions if p.model_name == MODEL_NAME), None)
        data = _collect(m.odds, home, away)
        match_date = m.date
        kickoff = m.kickoff_time

    model = _model_probs(pred)

    labels = {
        ("h2h", "home"): f"Home ({home})",
        ("h2h", "draw"): "Draw",
        ("h2h", "away"): f"Away ({away})",
        ("totals", "over"): "Over 2.5",
        ("totals", "under"): "Under 2.5",
    }

    selections = []
    for market, sels in _GROUPS.items():
        cur, opn = _consensus(data, market, sels)
        if cur is None:
            continue
        for sel in sels:
            d = data.get((market, sel)) or {}
            best_odds, best_book = d.get("best", (0.0, ""))
            mkt_prob = cur.get(sel)
            mdl_prob = model.get((market, sel))
            move = (cur[sel] - opn[sel]) if (opn and sel in opn) else None
            selections.append({
                "market": market,
                "selection": sel,
                "label": labels.get((market, sel), sel),
                "model_prob": mdl_prob,
                "market_prob": mkt_prob,
                "edge": (mdl_prob - mkt_prob) if (mdl_prob is not None and mkt_prob is not None) else None,
                "best_odds": best_odds if best_odds > 1.0 else None,
                "best_book": best_book or None,
                "movement": move,  # +ve = market moved toward this selection since open
            })

    return {
        "match_id": match_id,
        "home": home,
        "away": away,
        "home_fifa": home_fifa,
        "away_fifa": away_fifa,
        "date": match_date,
        "kickoff_time": kickoff,
        "selections": selections,
    }


def top_disagreements(limit: int = 10) -> list[dict]:
    """Across all upcoming matches, the selections where the model most disagrees
    with the de-vigged market consensus — a review queue of hypotheses to
    investigate, sorted by |edge| descending. One bulk query (no N+1).
    """
    out: list[dict] = []
    with get_session() as session:
        matches = session.execute(
            select(WCMatch)
            .where(WCMatch.status != "finished")
            .options(
                joinedload(WCMatch.home_team),
                joinedload(WCMatch.away_team),
                joinedload(WCMatch.odds),
                joinedload(WCMatch.predictions),
            )
        ).unique().scalars().all()

        for m in matches:
            home = m.home_team.name if m.home_team else "?"
            away = m.away_team.name if m.away_team else "?"
            pred = next((p for p in m.predictions if p.model_name == MODEL_NAME), None)
            if not pred:
                continue
            model = _model_probs(pred)
            data = _collect(m.odds, home, away)
            for market, sels in _GROUPS.items():
                cur, _ = _consensus(data, market, sels)
                if cur is None:
                    continue
                for sel in sels:
                    mp, kp = model.get((market, sel)), cur.get(sel)
                    if mp is None or kp is None:
                        continue
                    d = data.get((market, sel)) or {}
                    best, book = d.get("best", (0.0, ""))
                    out.append({
                        "match": f"{home} v {away}",
                        "selection": _SHORT_LABELS.get((market, sel), sel),
                        "edge": mp - kp,
                        "model": mp,
                        "market": kp,
                        "best_odds": best if best > 1.0 else None,
                        "best_book": book or None,
                    })

    out.sort(key=lambda x: -abs(x["edge"]))
    return out[:limit]
