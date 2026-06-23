"""
BetVector World Cup 2026 — Value Bet Finder (WC-05-01)
=======================================================
Identifies value bets by comparing WC Poisson model probabilities
against bookmaker odds from The Odds API.

A value bet exists when the model's probability for an outcome exceeds
the bookmaker's implied probability (1/odds) by at least the edge
threshold. Quarter-Kelly staking is applied for bankroll safety —
full Kelly is mathematically optimal but practically dangerous because
any error in probability estimation leads to aggressive overbetting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.database.db import get_session
from src.world_cup.models import (
    WCMatch, WCOdds, WCPrediction, WCTeam, WCValueBet,
)
from src.world_cup.predictor import MODEL_NAME
from src.world_cup.scraper import _normalize_team_name

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

# Maps (market_type, selection) to WCPrediction attribute names.
# Spreads deferred — Poisson model doesn't produce spread-adjusted probs.
MARKET_TO_PROB = {
    ("h2h", "home"): "home_win_prob",
    ("h2h", "draw"): "draw_prob",
    ("h2h", "away"): "away_win_prob",
    ("totals", "over"): "over_25_prob",
    ("totals", "under"): "_under_25_prob",  # computed as 1 - over_25_prob
    ("btts", "yes"): "btts_prob",
    ("btts", "no"): "_btts_no_prob",  # computed as 1 - btts_prob
}


def _canonical_selection(
    market_type: str,
    selection: str,
    home_name: str,
    away_name: str,
    point: float | None,
) -> str | None:
    """Translate a raw Odds API selection into the canonical key used by
    MARKET_TO_PROB.

    The Odds API stores h2h outcomes as team names ("Argentina") plus
    "Draw", and totals as "Over"/"Under" with the line in a separate
    ``point`` field. The WC model exposes probabilities keyed by
    home/draw/away and the 2.5-goals line only, so we map team names to
    home/away (applying the same name normalization the scraper uses) and
    ignore totals lines other than 2.5. Returns None for anything we can't
    line up with a model probability (e.g. spreads, h2h_lay, other lines).
    """
    sel = (selection or "").strip()
    if market_type == "h2h":
        if sel.lower() == "draw":
            return "draw"
        norm = _normalize_team_name(sel)
        if norm == home_name:
            return "home"
        if norm == away_name:
            return "away"
        return None
    if market_type == "totals":
        # The model only prices the 2.5 line; skip every other line so we
        # never compare, say, Over 1.5 odds against the 2.5 probability.
        if point is not None and abs(point - 2.5) > 1e-9:
            return None
        low = sel.lower()
        if low.startswith("over"):
            return "over"
        if low.startswith("under"):
            return "under"
        return None
    if market_type == "btts":
        low = sel.lower()
        if low in ("yes", "no"):
            return low
    return None


@dataclass
class WCValueBetResult:
    match_id: int
    prediction_id: int
    market_type: str
    selection: str
    model_prob: float
    best_odds: float
    implied_prob: float
    edge: float
    kelly_stake: float
    bookmaker: str
    home_team: str
    away_team: str


def _load_betting_config() -> dict:
    """Load WC betting parameters from config/worldcup_2026.yaml."""
    config_path = CONFIG_DIR / "worldcup_2026.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data.get("betting", {})


def _compute_kelly(model_prob: float, odds: float, fraction: float = 0.25) -> float:
    """Quarter-Kelly stake sizing.

    Kelly criterion: f* = (p * b - q) / b
    where p = model probability, b = odds - 1, q = 1 - p.

    Full Kelly maximizes log-growth but is volatile — a 10% overestimate
    in model probability can lead to 2x the intended stake. Quarter-Kelly
    sacrifices ~25% of theoretical growth for dramatically smoother
    bankroll trajectories.
    """
    if odds <= 1.0 or model_prob <= 0.0 or model_prob >= 1.0:
        return 0.0

    b = odds - 1.0
    q = 1.0 - model_prob
    full_kelly = (model_prob * b - q) / b

    if full_kelly <= 0.0:
        return 0.0

    return round(full_kelly * fraction, 6)


def find_wc_value_bets(
    edge_threshold: float | None = None,
    kelly_fraction: float | None = None,
) -> list[WCValueBetResult]:
    """
    Scan all upcoming WC matches for value bets.

    For each match with a prediction and odds, compares the model's
    probability against the best available bookmaker odds. When the
    model sees a higher probability than the market implies, that's
    an edge — and when the edge exceeds the threshold, it's a value bet.

    Parameters
    ----------
    edge_threshold : float, optional
        Minimum edge to flag (default from config, typically 3%).
    kelly_fraction : float, optional
        Kelly fraction for stake sizing (default from config, typically 0.25).

    Returns
    -------
    list[WCValueBetResult]
        Value bets sorted by edge descending. Empty list when no value exists.
    """
    cfg = _load_betting_config()
    threshold = edge_threshold if edge_threshold is not None else cfg.get("edge_threshold", 0.03)
    fraction = kelly_fraction if kelly_fraction is not None else cfg.get("kelly_fraction", 0.25)
    supported_markets = set(cfg.get("markets", ["h2h", "totals", "spreads"]))
    # Edge ceiling guardrail. Against a sharp 59-bookmaker WC market, an edge
    # this large almost always reflects model error (the measured under/home
    # biases on sparse international data) rather than genuine value. Capping it
    # stops miscalibration from manufacturing phantom "value" bets. Config-driven.
    max_edge = cfg.get("max_actionable_edge", 0.15)

    results: list[WCValueBetResult] = []
    capped = 0

    with get_session() as session:
        # Get all upcoming matches with predictions
        upcoming = session.execute(
            select(WCMatch)
            .where(WCMatch.status != "finished")
            .order_by(WCMatch.date)
        ).scalars().all()

        if not upcoming:
            logger.info("find_wc_value_bets: No upcoming matches")
            return []

        for match in upcoming:
            pred = session.execute(
                select(WCPrediction)
                .where(
                    WCPrediction.match_id == match.id,
                    WCPrediction.model_name == MODEL_NAME,
                )
            ).scalar_one_or_none()

            if not pred:
                continue

            home = session.get(WCTeam, match.home_team_id)
            away = session.get(WCTeam, match.away_team_id)
            home_name = home.name if home else "?"
            away_name = away.name if away else "?"

            # Get all odds for this match, grouped by market+selection
            odds_rows = session.execute(
                select(WCOdds)
                .where(WCOdds.match_id == match.id)
            ).scalars().all()

            if not odds_rows:
                continue

            # Find best odds per (market_type, canonical_selection). The Odds
            # API returns h2h selections as team names + "Draw" and totals as
            # "Over"/"Under"; normalize to the home/draw/away/over/under keys
            # MARKET_TO_PROB uses so model probabilities line up with odds.
            best_per_market: dict[tuple[str, str], WCOdds] = {}
            for o in odds_rows:
                canon = _canonical_selection(
                    o.market_type, o.selection, home_name, away_name, o.point
                )
                if canon is None:
                    continue
                key = (o.market_type, canon)
                if key not in best_per_market or o.odds_decimal > best_per_market[key].odds_decimal:
                    best_per_market[key] = o

            for (mkt, sel), best in best_per_market.items():
                if mkt not in supported_markets:
                    continue

                prob_attr = MARKET_TO_PROB.get((mkt, sel))
                if prob_attr is None:
                    continue

                # Handle computed probabilities (complement of stored value)
                if prob_attr == "_under_25_prob":
                    over_prob = pred.over_25_prob
                    if over_prob is None:
                        continue
                    model_prob = 1.0 - over_prob
                elif prob_attr == "_btts_no_prob":
                    btts_yes = pred.btts_prob
                    if btts_yes is None:
                        continue
                    model_prob = 1.0 - btts_yes
                else:
                    model_prob = getattr(pred, prob_attr, None)
                    if model_prob is None:
                        continue

                if best.odds_decimal <= 1.0:
                    continue

                # Edge = model probability minus market-implied probability
                implied_prob = 1.0 / best.odds_decimal
                edge = model_prob - implied_prob

                if edge < threshold:
                    continue

                if edge > max_edge:
                    # Too large to be real against a sharp market — model error.
                    capped += 1
                    logger.info(
                        "Skip %s/%s match %d: edge %.1f%% > actionable ceiling %.1f%%",
                        mkt, sel, match.id, edge * 100, max_edge * 100,
                    )
                    continue

                kelly = _compute_kelly(model_prob, best.odds_decimal, fraction)

                results.append(WCValueBetResult(
                    match_id=match.id,
                    prediction_id=pred.id,
                    market_type=mkt,
                    selection=sel,
                    model_prob=round(model_prob, 6),
                    best_odds=best.odds_decimal,
                    implied_prob=round(implied_prob, 6),
                    edge=round(edge, 6),
                    kelly_stake=kelly,
                    bookmaker=best.bookmaker,
                    home_team=home_name,
                    away_team=away_name,
                ))

    # Rank by edge × confidence. When calibration data is available,
    # confidence scales with model accuracy; otherwise default to 1.0.
    from src.world_cup.calibration import compute_model_accuracy
    cal = compute_model_accuracy()
    # Confidence: (1 - brier_per_class / 0.333) gives 0→1 as brier improves
    # from random (0.333/class) to perfect (0). Clamp to [0.5, 1.0] to
    # avoid over-penalizing early-tournament uncertainty.
    bpc = cal.get("brier_per_class", 0.22)
    confidence = max(0.5, min(1.0, 1.0 - bpc / 0.333)) if cal.get("n_matches", 0) > 0 else 1.0
    results.sort(key=lambda x: -(x.edge * confidence))
    logger.info(
        "find_wc_value_bets: %d value bets across %d matches "
        "(threshold=%.1f%%, ceiling=%.1f%%, %d capped as model-error)",
        len(results), len(upcoming), threshold * 100, max_edge * 100, capped,
    )
    return results


def save_wc_value_bets(value_bets: list[WCValueBetResult]) -> dict:
    """Persist value bets to wc_value_bets table. Idempotent — skips duplicates."""
    new_count = 0
    updated_count = 0
    skipped = 0

    with get_session() as session:
        for vb in value_bets:
            # Check for existing entry (same match + market + selection + bookmaker)
            existing = session.execute(
                select(WCValueBet)
                .where(
                    WCValueBet.match_id == vb.match_id,
                    WCValueBet.market_type == vb.market_type,
                    WCValueBet.selection == vb.selection,
                    WCValueBet.bookmaker == vb.bookmaker,
                )
            ).scalar_one_or_none()

            if existing:
                # Update edge/odds if they've moved since last scan
                if abs(existing.edge - vb.edge) > 0.001:
                    existing.edge = vb.edge
                    existing.model_prob = vb.model_prob
                    existing.best_odds = vb.best_odds
                    existing.implied_prob = vb.implied_prob
                    existing.kelly_stake = vb.kelly_stake
                    updated_count += 1
                else:
                    skipped += 1
                continue

            row = WCValueBet(
                match_id=vb.match_id,
                prediction_id=vb.prediction_id,
                market_type=vb.market_type,
                selection=vb.selection,
                model_prob=vb.model_prob,
                best_odds=vb.best_odds,
                implied_prob=vb.implied_prob,
                edge=vb.edge,
                bookmaker=vb.bookmaker,
                kelly_stake=vb.kelly_stake,
            )
            session.add(row)
            new_count += 1

        session.commit()

    logger.info("save_wc_value_bets: %d new, %d updated, %d skipped",
                new_count, updated_count, skipped)
    return {"new": new_count, "updated": updated_count, "skipped": skipped,
            "total": len(value_bets)}


def capture_wc_closing_lines() -> dict:
    """Freeze the closing line and compute CLV for WC shadow picks whose match
    has finished (WC-09-01).

    The closing line is the best stored price for the pick's selection — i.e. the
    last pre-kickoff odds snapshot, which is already in ``wc_odds`` (the scraper
    upserts, so once a match leaves the API its odds are frozen). So this adds
    **no new API cost**. Idempotent: only fills ``closing_odds`` where it is NULL.

    CLV = (1/closing_odds) - (1/best_odds) — the league convention. A positive CLV
    means we took a better price than the close, the leading indicator of edge.
    """
    captured = 0
    skipped_no_odds = 0

    with get_session() as session:
        # Picks that don't yet have a closing line, with match + teams + odds eager-loaded
        vbs = session.execute(
            select(WCValueBet)
            .where(WCValueBet.closing_odds.is_(None))
            .options(
                joinedload(WCValueBet.match).joinedload(WCMatch.home_team),
                joinedload(WCValueBet.match).joinedload(WCMatch.away_team),
                joinedload(WCValueBet.match).joinedload(WCMatch.odds),
            )
        ).unique().scalars().all()

        for vb in vbs:
            m = vb.match
            # The line is only "closed" once the match has been played.
            if not m or m.status != "finished":
                continue

            home_name = m.home_team.name if m.home_team else ""
            away_name = m.away_team.name if m.away_team else ""

            # Best frozen price for this pick's canonical selection = the close.
            best = 0.0
            for o in m.odds:
                if o.market_type != vb.market_type:
                    continue
                canon = _canonical_selection(
                    o.market_type, o.selection, home_name, away_name, o.point
                )
                if canon == vb.selection and o.odds_decimal > best:
                    best = o.odds_decimal

            if best <= 1.0:
                skipped_no_odds += 1
                continue

            vb.closing_odds = best
            vb.clv = round((1.0 / best) - (1.0 / vb.best_odds), 6)
            captured += 1

        session.commit()

    logger.info(
        "capture_wc_closing_lines: %d closing lines captured, %d skipped (no odds)",
        captured, skipped_no_odds,
    )
    return {"captured": captured, "skipped_no_odds": skipped_no_odds}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from src.database.db import init_db

    init_db()

    print("=== WC Value Bet Scan ===")
    bets = find_wc_value_bets()
    print(f"Found: {len(bets)} value bets")
    if bets:
        for vb in bets[:15]:
            print(
                f"  {vb.home_team} vs {vb.away_team} | "
                f"{vb.market_type}/{vb.selection} | "
                f"edge={vb.edge:+.1%} model={vb.model_prob:.1%} "
                f"@ {vb.best_odds:.2f} ({vb.bookmaker}) "
                f"kelly={vb.kelly_stake:.4f}"
            )

        print("\n=== Saving to DB ===")
        result = save_wc_value_bets(bets)
        print(f"New: {result['new']}, Skipped: {result['skipped']}")
    else:
        print("  No value bets (no upcoming matches with predictions + odds)")
