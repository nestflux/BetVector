"""
BetVector World Cup — bet-tracker odds helpers (WC-ODDS).

Read-only lookups over ``wc_odds`` so the bet-tracker log form + accumulator slip can
pre-fill the price for a (match, market, selection) from a chosen bookmaker — or the
best price across books. Covers the markets the pipeline already stores: 1X2 (``h2h``)
and Over/Under (``totals``). BTTS / "to qualify" aren't stored here (BTTS is fetched
on demand in WC-ODDS-02; to-qualify stays manual).

SHADOW-SAFE: these functions only READ ``wc_odds`` — nothing is written, so the
model / value / prediction path is untouched.
"""
from __future__ import annotations

from typing import Optional

import yaml
from sqlalchemy import select
from sqlalchemy.orm import aliased

from src.config import PROJECT_ROOT
from src.database.db import get_session
from src.world_cup.models import WCMatch, WCOdds, WCTeam
from src.world_cup.scraper import _normalize_team_name  # same normalization the scraper stored with

# Tracker O/U markets -> the goals line carried in wc_odds.point.
_OU_POINT = {"OU15": 1.5, "OU25": 2.5, "OU35": 3.5}
_BEST = "Best price"


def default_bookmaker() -> str:
    """The pre-selected bookmaker for the tracker's odds auto-fill — config-driven
    (`scraping.the_odds_api.default_bookmaker`); FanDuel unless overridden."""
    try:
        with open(PROJECT_ROOT / "config" / "settings.yaml") as f:
            data = yaml.safe_load(f) or {}
        return (data.get("scraping", {}).get("the_odds_api", {})
                .get("default_bookmaker", "FanDuel"))
    except Exception:
        return "FanDuel"


def _odds_market_for(tracker_market: str) -> Optional[str]:
    """The wc_odds market_type carrying a tracker market's price: 1X2 -> ``h2h``,
    O/U -> ``totals``. BTTS / QUALIFY aren't stored in wc_odds -> None."""
    if tracker_market == "1X2":
        return "h2h"
    if tracker_market in _OU_POINT:
        return "totals"
    return None


def _row_matches(row, tracker_market: str, selection: str,
                 home_name: str, away_name: str) -> bool:
    """Does a wc_odds row carry the price for this tracker (market, selection)? Maps
    home/away/draw + over/under onto the odds feed's naming (team names / "Draw" /
    "Over"/"Under" + point), normalizing team names exactly as the scraper did on
    write (so an Odds-API name that differs from our DB name still lines up)."""
    sel = (row.selection or "").strip()
    if tracker_market == "1X2":
        if selection == "draw":
            return sel.lower() == "draw"
        norm = _normalize_team_name(sel)
        return norm == (home_name if selection == "home" else away_name)
    if tracker_market in _OU_POINT:
        if row.point is None \
                or abs(float(row.point) - _OU_POINT[tracker_market]) > 1e-9:
            return False
        return sel.lower().startswith(selection)   # "over" / "under"
    return False


def wc_odds_lookup(match_id: int, market_type: str, selection: str,
                   bookmaker: Optional[str] = None) -> Optional[dict]:
    """Stored odds for a tracker (market, selection), as
    ``{"odds": float, "bookmaker": str}`` — or None when not stored (BTTS / QUALIFY /
    an O/U line no book quoted, or the chosen book has no price). ``bookmaker`` None
    or "Best price" -> the highest price across books; a specific book -> that book's
    price. READ-ONLY; never raises."""
    odds_market = _odds_market_for(market_type)
    if odds_market is None:
        return None
    try:
        with get_session() as session:
            HomeT = aliased(WCTeam)
            AwayT = aliased(WCTeam)
            m = session.execute(
                select(WCMatch.id, HomeT.name, AwayT.name)
                .join(HomeT, WCMatch.home_team_id == HomeT.id)
                .join(AwayT, WCMatch.away_team_id == AwayT.id)
                .where(WCMatch.id == match_id)
            ).first()
            if m is None:
                return None
            _mid, home_name, away_name = m
            rows = session.execute(
                select(WCOdds).where(
                    WCOdds.match_id == match_id,
                    WCOdds.market_type == odds_market,
                )
            ).scalars().all()
        hits = [r for r in rows
                if _row_matches(r, market_type, selection, home_name, away_name)]
        if not hits:
            return None
        want = (bookmaker or "").strip().lower()
        if want and want != _BEST.lower():
            row = next((r for r in hits if (r.bookmaker or "").lower() == want), None)
            if row is None:
                return None   # chosen book has no price for this line
            return {"odds": round(row.odds_decimal, 2), "bookmaker": row.bookmaker}
        best = max(hits, key=lambda r: r.odds_decimal)   # "Best price"
        return {"odds": round(best.odds_decimal, 2), "bookmaker": best.bookmaker}
    except Exception:
        return None


def wc_odds_books(match_id: int) -> list:
    """Distinct bookmakers with 1X2 / O-U odds stored for the match — the selector's
    options, default book (FanDuel) first if present, then alphabetical. [] on error."""
    try:
        with get_session() as session:
            books = session.execute(
                select(WCOdds.bookmaker).distinct().where(
                    WCOdds.match_id == match_id,
                    WCOdds.market_type.in_(("h2h", "totals")),
                )
            ).scalars().all()
        ordered = sorted({b for b in books if b})
        default = default_bookmaker()
        if default in ordered:
            ordered = [default] + [b for b in ordered if b != default]
        return ordered
    except Exception:
        return []
