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
from src.world_cup.predictor import MODEL_NAME, derive_markets_from_lambdas
from src.world_cup.value_finder import _canonical_selection, _load_betting_config

logger = logging.getLogger(__name__)

# Research-layer market groups: each group's canonical selections de-vig together
# (their de-vigged probabilities sum to 1). Keys are point-encoded so the three
# O/U lines stay distinct. This DISPLAY mapping is deliberately separate from
# value_finder._canonical_selection (which stays 2.5-only) — value bets are
# unchanged; this only widens what the research card / deep dive compare (DF-01).
_GROUPS = {
    "h2h":  ["home", "draw", "away"],
    "ou15": ["over_1.5", "under_1.5"],
    "ou25": ["over_2.5", "under_2.5"],
    "ou35": ["over_3.5", "under_3.5"],
    "btts": ["btts_yes", "btts_no"],
}

# Totals lines we surface; any other point is ignored (no model line for it).
_OU_POINTS = ("1.5", "2.5", "3.5")

_SHORT_LABELS = {
    "home": "Home", "draw": "Draw", "away": "Away",
    "over_1.5": "Over 1.5", "under_1.5": "Under 1.5",
    "over_2.5": "Over 2.5", "under_2.5": "Under 2.5",
    "over_3.5": "Over 3.5", "under_3.5": "Under 3.5",
    "btts_yes": "BTTS Yes", "btts_no": "BTTS No",
}


def _line_str(point) -> str | None:
    """Map a totals ``point`` to one of our display lines ("1.5"/"2.5"/"3.5"),
    or None for any line we don't surface."""
    if point is None:
        return None
    try:
        p = float(point)
    except (TypeError, ValueError):
        return None
    for s in _OU_POINTS:
        if abs(p - float(s)) < 1e-9:
            return s
    return None


def _canon(market_type, selection, home_name, away_name, point) -> str | None:
    """Research-layer canonical selection key (point-aware, multi-line). Reuses
    value_finder's logic for h2h/btts without altering it, and handles totals +
    alternate_totals here so every O/U line is kept distinct."""
    if market_type in ("totals", "alternate_totals"):
        line = _line_str(point)
        if line is None:
            return None
        low = (selection or "").strip().lower()
        if low.startswith("over"):
            return f"over_{line}"
        if low.startswith("under"):
            return f"under_{line}"
        return None
    base = _canonical_selection(market_type, selection, home_name, away_name, point)
    if base in ("home", "draw", "away"):
        return base
    if base in ("yes", "no"):
        return f"btts_{base}"
    return None


def _comp(p):
    """Complement 1 - p, or None when p is None."""
    return (1.0 - p) if p is not None else None


def _model_probs(pred) -> dict:
    """Model probability per canonical selection, or {} when no prediction.

    1X2, O/U 2.5 and BTTS come straight from the stored prediction (exact). The
    extra O/U lines (1.5, 3.5) the model computes but doesn't persist are rebuilt
    from the stored expected goals via the scoreline matrix (DF-01)."""
    if not pred:
        return {}
    o25 = pred.over_25_prob
    btts = pred.btts_prob
    derived = derive_markets_from_lambdas(
        pred.home_expected_goals, pred.away_expected_goals)
    o15 = derived.get("over_15")
    o35 = derived.get("over_35")
    if o25 is None:                       # stored missing → fall back to derived
        o25 = derived.get("over_25")
    if btts is None:
        btts = derived.get("btts")
    return {
        "home": pred.home_win_prob,
        "draw": pred.draw_prob,
        "away": pred.away_win_prob,
        "over_1.5": o15, "under_1.5": _comp(o15),
        "over_2.5": o25, "under_2.5": _comp(o25),
        "over_3.5": o35, "under_3.5": _comp(o35),
        "btts_yes": btts, "btts_no": _comp(btts),
    }


def _devig(implied: dict) -> dict:
    total = sum(implied.values())
    return {k: v / total for k, v in implied.items()} if total > 0 else dict(implied)


def _collect(odds, home_name: str, away_name: str) -> dict:
    """canonical_sel → {cur: [prices], open: [prices], best: (odds, book)}.

    Keyed by the point-encoded canonical selection, so the same line quoted under
    both ``totals`` and ``alternate_totals`` merges into one price pool."""
    data: dict = {}
    for o in odds:
        canon = _canon(o.market_type, o.selection, home_name, away_name, o.point)
        if not canon:
            continue
        d = data.setdefault(canon, {"cur": [], "open": [], "best": (0.0, "")})
        d["cur"].append(o.odds_decimal)
        if o.opening_odds:
            d["open"].append(o.opening_odds)
        if o.odds_decimal > d["best"][0]:
            d["best"] = (o.odds_decimal, o.bookmaker)
    return data


def _consensus(data: dict, sels: list[str]):
    """De-vigged current + opening consensus prob per selection, or (None, None)
    when the group is incomplete (a missing side means we can't de-vig)."""
    implied_cur, implied_open = {}, {}
    for sel in sels:
        d = data.get(sel)
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

    # h2h labels carry the team name; every other selection uses its short label.
    labels = dict(_SHORT_LABELS)
    labels["home"] = f"Home ({home})"
    labels["away"] = f"Away ({away})"

    selections = []
    for group, sels in _GROUPS.items():
        cur, opn = _consensus(data, sels)
        if cur is None:
            continue
        for sel in sels:
            d = data.get(sel) or {}
            best_odds, best_book = d.get("best", (0.0, ""))
            mkt_prob = cur.get(sel)
            mdl_prob = model.get(sel)
            move = (cur[sel] - opn[sel]) if (opn and sel in opn) else None
            selections.append({
                "market": group,
                "selection": sel,
                "label": labels.get(sel, sel),
                "model_prob": mdl_prob,
                "market_prob": mkt_prob,
                "edge": (mdl_prob - mkt_prob) if (mdl_prob is not None and mkt_prob is not None) else None,
                "best_odds": best_odds if best_odds > 1.0 else None,
                "best_book": best_book or None,
                "movement": move,  # +ve = market moved toward this selection since open
            })

    card = {
        "match_id": match_id,
        "home": home,
        "away": away,
        "home_fifa": home_fifa,
        "away_fifa": away_fifa,
        "date": match_date,
        "kickoff_time": kickoff,
        "selections": selections,
    }
    # DF-06: attach the digestible view structure — three plain-English blocks
    # (each with a model-vs-market read) and one headline lean for the card.
    summary = summarize_card(card)
    card["blocks"] = summary["blocks"]
    card["headline"] = summary["headline"]
    return card


# ============================================================================
# DF-06 — Research-card display structure (pure; the view only draws the bars)
# ============================================================================
# The research card groups its selections into three plain-English blocks
# (Match result / Goals / Both teams to score), each with a one-line read of
# where the edge sits, plus a single headline lean for the whole card. "Trust"
# uses the SAME edge bounds the WC value finder stakes on (config edge_threshold
# / max_actionable_edge): a lean is only highlighted inside [threshold, ceiling];
# a gap past the ceiling is flagged "likely model error", never celebrated. This
# is display-only — no model/value math changes (the card stays shadow).

# (display key, block title, the build_research_card market keys it gathers)
_BLOCKS = (
    ("h2h", "Match result", ("h2h",)),
    ("goals", "Goals", ("ou15", "ou25", "ou35")),
    ("btts", "Both teams to score", ("btts",)),
)


def _trust_bounds(cfg: dict | None = None) -> tuple[float, float]:
    """(edge_threshold, max_actionable_edge) — the same staking bounds the value
    finder uses, so the card's 'trust range' matches what we'd actually bet."""
    if cfg is None:
        try:
            cfg = _load_betting_config()
        except Exception:                     # config unreadable → safe defaults
            cfg = {}
    return cfg.get("edge_threshold", 0.03), cfg.get("max_actionable_edge", 0.15)


def _edge_trust(edge, threshold: float, ceiling: float) -> str:
    """Trust class for one model-vs-market edge: 'value' = a lean inside
    [threshold, ceiling]; 'capped' = past the ceiling (likely model error);
    'none' = sub-threshold or model at/below market; 'na' = no priced edge."""
    if edge is None:
        return "na"
    if edge >= threshold:
        return "capped" if edge > ceiling else "value"
    return "none"


def _read_name(row: dict, home: str, away: str) -> str:
    """Plain-English subject for a selection in an 'edge is on X' sentence."""
    sel = row.get("selection")
    if sel == "home":
        return home
    if sel == "away":
        return away
    if sel == "draw":
        return "the draw"
    if sel == "btts_yes":
        return "both teams scoring"
    if sel == "btts_no":
        return "one team kept off the scoresheet"
    return row.get("label") or (sel or "")      # "Over 2.5" etc.


def _block_read(rows: list[dict], home: str, away: str,
                threshold: float, ceiling: float) -> dict:
    """One plain-English read for a market block — names where the edge sits (if
    any), honouring the ceiling. Picks the selection the model most favours."""
    priced = [r for r in rows if r.get("edge") is not None]
    if not priced:
        return {"text": "No prices for this market yet.", "class": "na"}
    top = max(priced, key=lambda r: r["edge"])
    cls = _edge_trust(top["edge"], threshold, ceiling)
    name = _read_name(top, home, away)
    if cls == "value":
        return {"class": "value",
                "text": (f"Edge is on {name} — model {top['model_prob']:.0%} "
                         f"vs market {top['market_prob']:.0%} ({top['edge']:+.0%}).")}
    if cls == "capped":
        return {"class": "capped",
                "text": (f"Model leans hard to {name}, but the {top['edge']:+.0%} "
                         f"gap is past the trust ceiling — likely model error, "
                         f"not a bet.")}
    return {"class": "none", "text": "In line with the market — no edge worth backing."}


def _headline(selections: list[dict], home: str, away: str,
              threshold: float, ceiling: float) -> dict:
    """The card's single headline: the strongest TRUSTWORTHY lean (inside the
    ceiling) if one exists; otherwise the biggest over-ceiling gap flagged as
    likely model error; otherwise agreement with the market."""
    block_of = {mk: title for _, title, keys in _BLOCKS for mk in keys}
    priced = [r for r in selections if r.get("edge") is not None]
    if not priced:
        return {"class": "na", "text": "No odds for this match yet."}

    values = [r for r in priced if threshold <= r["edge"] <= ceiling]
    capped = [r for r in priced if r["edge"] > ceiling]

    if values:
        top = max(values, key=lambda r: r["edge"])
        name = _read_name(top, home, away)
        block = block_of.get(top["market"], "this match")
        price = (f" @ {top['best_odds']:.2f} ({top['best_book']})"
                 if top.get("best_odds") and top.get("best_book") else
                 (f" @ {top['best_odds']:.2f}" if top.get("best_odds") else ""))
        return {
            "class": "value", "selection": top["selection"], "label": name,
            "block": block, "edge": top["edge"], "model_prob": top["model_prob"],
            "market_prob": top["market_prob"], "best_odds": top.get("best_odds"),
            "best_book": top.get("best_book"), "movement": top.get("movement"),
            "text": (f"Strongest lean: {name} ({block}) — model "
                     f"{top['model_prob']:.0%} vs market {top['market_prob']:.0%}, "
                     f"{top['edge']:+.0%} edge{price}."),
        }
    if capped:
        top = max(capped, key=lambda r: r["edge"])
        name = _read_name(top, home, away)
        block = block_of.get(top["market"], "this match")
        return {
            "class": "capped", "selection": top["selection"], "label": name,
            "block": block, "edge": top["edge"], "movement": top.get("movement"),
            "text": (f"Biggest gap: {name} ({block}), {top['edge']:+.0%} — past the "
                     f"trust ceiling, so treat it as likely model error, not a signal."),
        }
    return {"class": "none", "text": "Model agrees with the market — no clear edge here."}


def summarize_card(card: dict, cfg: dict | None = None) -> dict:
    """DF-06: annotate each selection with a trust class and arrange the card into
    the three display blocks + a headline lean. Pure (no Streamlit) so the
    grouping, wording, and ceiling logic stay unit-testable; the view draws bars
    from ``blocks`` / ``headline``."""
    threshold, ceiling = _trust_bounds(cfg)
    home = card.get("home", "Home")
    away = card.get("away", "Away")
    sels = card.get("selections", [])

    for r in sels:
        r["trust"] = _edge_trust(r.get("edge"), threshold, ceiling)

    by_market: dict[str, list] = {}
    for r in sels:
        by_market.setdefault(r.get("market"), []).append(r)

    blocks = []
    for key, title, mkeys in _BLOCKS:
        rows = [r for mk in mkeys for r in by_market.get(mk, [])]
        if not rows:
            continue
        blocks.append({
            "key": key, "title": title, "selections": rows,
            "read": _block_read(rows, home, away, threshold, ceiling),
        })

    return {"blocks": blocks,
            "headline": _headline(sels, home, away, threshold, ceiling)}


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
            for group, sels in _GROUPS.items():
                cur, _ = _consensus(data, sels)
                if cur is None:
                    continue
                for sel in sels:
                    mp, kp = model.get(sel), cur.get(sel)
                    if mp is None or kp is None:
                        continue
                    d = data.get(sel) or {}
                    best, book = d.get("best", (0.0, ""))
                    out.append({
                        "match": f"{home} v {away}",
                        "selection": _SHORT_LABELS.get(sel, sel),
                        "edge": mp - kp,
                        "model": mp,
                        "market": kp,
                        "best_odds": best if best > 1.0 else None,
                        "best_book": book or None,
                    })

    out.sort(key=lambda x: -abs(x["edge"]))
    return out[:limit]
