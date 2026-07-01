"""
BetVector World Cup — bet-tracker odds helpers (WC-ODDS).

Read-only lookups over ``wc_odds`` so the bet-tracker log form + accumulator slip can
pre-fill the price for a (match, market, selection) from a chosen bookmaker — or the
best price across books. Covers the markets the pipeline already stores: 1X2 (``h2h``)
and Over/Under (``totals``). BTTS is NOT stored in wc_odds — it's fetched LIVE on
demand (``fetch_btts_odds``, WC-ODDS-02), budget-guarded and never written back;
"to qualify" stays manual.

SHADOW-SAFE: the stored-odds lookups only READ ``wc_odds`` and the on-demand BTTS
fetch NEVER writes it, so the model / value / prediction path is untouched. (Writing
BTTS prices into wc_odds would feed the value finder and start generating BTTS value
picks — exactly what the tracker must not do.)
"""
from __future__ import annotations

from typing import Optional

import requests
import yaml
from sqlalchemy import select
from sqlalchemy.orm import aliased

from src.config import PROJECT_ROOT
from src.database.db import get_session
from src.world_cup.models import WCMatch, WCOdds, WCTeam
# Same normalization + odds-feed constants the scraper stored the odds with, so an
# on-demand BTTS event resolves against the exact team names already in wc_odds.
from src.world_cup.scraper import (
    API_BASE, SPORT_KEY, _get_api_key, _normalize_team_name,
)

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


# ============================================================================
# WC-ODDS-02 — on-demand BTTS ("both teams to score") odds
#
# BTTS isn't part of the once-daily bulk board pull (that pull carries only
# h2h/totals to stay cheap), so it's fetched LIVE the moment the tracker asks for it.
# One FREE /events lookup + ONE paid single-event single-region call (~1 credit),
# budget-guarded, and the result is returned for DISPLAY ONLY — never written to
# wc_odds (that would feed the value finder). Cache it at the call site.
# ============================================================================

def _hard_stop_threshold() -> int:
    """The Odds API monthly-budget floor (`scraping.the_odds_api.hard_stop_threshold`,
    default 30) below which on-demand fetches stand down. Config-driven."""
    try:
        with open(PROJECT_ROOT / "config" / "settings.yaml") as f:
            data = yaml.safe_load(f) or {}
        return int(data.get("scraping", {}).get("the_odds_api", {})
                   .get("hard_stop_threshold", 30))
    except Exception:
        return 30


def _below_budget_floor(remaining) -> bool:
    """True when the remaining Odds API credits are at/below the config hard-stop — so
    an on-demand fetch should skip the paid call and fall back to manual entry. An
    unknown / unparseable ``remaining`` -> False (don't block; the paid call itself
    surfaces a real error if we are genuinely out)."""
    try:
        # float() (not int()) so a float-formatted header can't spuriously fail to
        # parse and skip the guard — The Odds API sends integers, but this is safe.
        return float(remaining) <= _hard_stop_threshold()
    except (TypeError, ValueError):
        return False


def _parse_btts(event: dict) -> dict:
    """Pull the BTTS market out of an Odds-API event-odds payload into
    ``{bookmaker_title: {"yes": float, "no": float}}``. Books without a usable BTTS
    market are skipped; a price must be > 1.0 (a real decimal quote) to count."""
    out: dict = {}
    for bm in (event or {}).get("bookmakers", []):
        title = bm.get("title") or bm.get("key")
        if not title:
            continue
        for mk in bm.get("markets", []):
            if mk.get("key") != "btts":
                continue
            prices: dict = {}
            for oc in mk.get("outcomes", []):
                name = (oc.get("name") or "").strip().lower()
                price = oc.get("price")
                if name in ("yes", "no") and isinstance(price, (int, float)) \
                        and price > 1.0:
                    prices[name] = float(price)
            if prices:
                out[title] = prices
    return out


def pick_btts(fetched: dict, selection: str,
              bookmaker: Optional[str] = None) -> Optional[dict]:
    """Pick a BTTS price from a fetched ``{book: {"yes","no"}}`` dict for the tracker's
    selection ("yes"/"no"), as ``{"odds","bookmaker"}``. A specific ``bookmaker`` maps
    to that book — falling back to the best price (with its book) when that book didn't
    quote BTTS; None / "Best price" -> the highest price across books. None when nobody
    quoted the side."""
    sel = "yes" if (selection or "").strip().lower() == "yes" else "no"
    priced = [(b, p[sel]) for b, p in (fetched or {}).items() if p.get(sel)]
    if not priced:
        return None
    want = (bookmaker or "").strip().lower()
    if want and want != _BEST.lower():
        hit = next(((b, pr) for b, pr in priced if b.lower() == want), None)
        if hit is not None:
            return {"odds": round(hit[1], 2), "bookmaker": hit[0]}
        # chosen book didn't quote BTTS -> fall back to the best price across books
    book, price = max(priced, key=lambda x: x[1])
    return {"odds": round(price, 2), "bookmaker": book}


def fetch_btts_odds(match_id: int, region: str = "us") -> dict:
    """Fetch BTTS ("both teams to score") odds for one match LIVE from The Odds API for
    a single region (US by default), as ``{bookmaker: {"yes": float, "no": float}}``.

    Cost: one FREE ``/events`` lookup to resolve the match's Odds-API event, then ONE
    paid ``/events/{id}/odds?markets=btts&regions=us`` (markets x regions = 1 x 1 =
    ~1 credit). Budget-guarded — the free ``/events`` response's remaining-credit header
    is checked first and the paid call is skipped (-> ``{}``) once the budget is at/below
    the config hard-stop, so on-demand fetching can never blow the monthly quota.

    READ-ONLY / SHADOW-SAFE: the result is for display only and is NEVER written to
    wc_odds. Returns ``{}`` on any miss / API failure / budget-low / no BTTS quoted;
    never raises. Cache at the call site (the view wraps this in ``st.cache_data``) so a
    match is fetched at most once per cache window."""
    api_key = _get_api_key()
    if not api_key:
        return {}
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
            return {}
        _mid, home_name, away_name = m

        # 1. FREE /events lookup — resolve this match's Odds-API event id AND read the
        #    remaining-credit header for the budget guard (this call costs nothing).
        er = requests.get(f"{API_BASE}/sports/{SPORT_KEY}/events",
                          params={"apiKey": api_key}, timeout=20)
        if er.status_code != 200:
            return {}
        if _below_budget_floor(er.headers.get("x-requests-remaining")):
            return {}   # budget guard: stand down rather than spend the paid credit
        event_id = None
        for ev in er.json():
            if (_normalize_team_name(ev.get("home_team", "")) == home_name
                    and _normalize_team_name(ev.get("away_team", "")) == away_name):
                event_id = ev.get("id")
                break
        if not event_id:
            return {}

        # 2. Paid 1-event BTTS pull for ONE region (~1 credit) — targets only this
        #    match, so it never disturbs other matches' stored closing lines / CLV.
        r = requests.get(
            f"{API_BASE}/sports/{SPORT_KEY}/events/{event_id}/odds",
            params={"apiKey": api_key, "regions": region, "markets": "btts",
                    "oddsFormat": "decimal"}, timeout=20)
        if r.status_code != 200:
            return {}
        return _parse_btts(r.json())
    except Exception:
        return {}
