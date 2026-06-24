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
from src.world_cup.lineups import _prior_starter_rows, _starter_rows, lineup_signal
from src.world_cup.models import WCMatch, WCTeam
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


# ============================================================================
# DF-07 — Curated disagreements queue (verdict-tagged review sentences)
# ============================================================================
# top_disagreements (above) is the primitive: every priceable selection, sorted
# by |edge|, both sides of each market. The review queue the dashboard shows is
# curated on top of it: each market is collapsed to the ONE side the model
# favours (so a row is a clear directional call, not a mirror pair), tagged with
# a verdict against the SAME edge ceiling the value finder stakes on, and ranked
# so trustworthy convictions lead. Shadow / decision-support only — nothing here
# is staked; it's a queue of hypotheses to investigate.

_RANK = {"value": 0, "capped": 1}      # convictions before likely-model-error


def _queue_label(sel: str, home: str, away: str) -> str:
    """Crisp subject for a 'Back X' / 'model rates X' disagreement sentence —
    the team name for home/away, else the short market label."""
    if sel == "home":
        return home
    if sel == "away":
        return away
    if sel == "draw":
        return "the draw"
    return _SHORT_LABELS.get(sel, sel)      # "Over 2.5", "BTTS Yes", …


def _disagreement_sentence(d: dict) -> str:
    """One plain-English review sentence for a disagreement. Conviction reads as
    a backable lean (with the best price); a capped gap reads as a flagged
    over-the-ceiling discrepancy — likely model error, never a call to back."""
    m, k = d["model_prob"], d["market_prob"]
    if d["trust"] == "capped":
        return (f'{d["match"]}: model rates {d["label"]} {m:.0%} vs market '
                f'{k:.0%} — past the trust ceiling, likely model error.')
    if d.get("best_odds") and d.get("best_book"):
        price = f', best price {d["best_odds"]:.2f} ({d["best_book"]})'
    elif d.get("best_odds"):
        price = f', best price {d["best_odds"]:.2f}'
    else:
        price = ''
    return (f'Back {d["label"]} in {d["match"]} — model {m:.0%} vs '
            f'market {k:.0%}{price}.')


def build_disagreements(limit: int = 10, cfg: dict | None = None) -> list[dict]:
    """DF-07 — the dashboard review queue: across upcoming matches, each market
    collapsed to the side the MODEL most favours over the de-vigged market, kept
    only when that edge clears the threshold (a real disagreement), tagged with a
    verdict against the value finder's bounds:
      ``value``  — edge in [threshold, ceiling]: ✓ conviction (a backable shadow
                   lean to investigate).
      ``capped`` — edge past the ceiling: ⚠ likely model error (too big to trust).
    Convictions rank first (by edge), then likely-model-error rows (by edge), so
    the trustworthy calls lead. One bulk query (no N+1). Read-only / shadow."""
    threshold, ceiling = _trust_bounds(cfg)
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
                # The single side the model most favours over the market here.
                best = None
                for sel in sels:
                    mp, kp = model.get(sel), cur.get(sel)
                    if mp is None or kp is None:
                        continue
                    edge = mp - kp
                    if best is None or edge > best[0]:
                        best = (edge, sel, mp, kp)
                if best is None:
                    continue
                edge, sel, mp, kp = best
                if edge < threshold:        # model broadly in line — not a disagreement
                    continue
                d = data.get(sel) or {}
                price, book = d.get("best", (0.0, ""))
                row = {
                    "match": f"{home} v {away}",
                    "group": group,
                    "selection": sel,
                    "label": _queue_label(sel, home, away),
                    "trust": _edge_trust(edge, threshold, ceiling),  # value | capped
                    "edge": edge,
                    "model_prob": mp,
                    "market_prob": kp,
                    "best_odds": price if price > 1.0 else None,
                    "best_book": book or None,
                }
                out.append(row)

    # Convictions first (largest edge first), then likely-model-error rows.
    out.sort(key=lambda r: (_RANK.get(r["trust"], 2), -r["edge"]))
    out = out[:limit]
    for r in out:
        r["text"] = _disagreement_sentence(r)
    return out


# ============================================================================
# DF-08 — Model-vs-every-book comparison (deep dive)
# ============================================================================
# The research card collapses every book into one de-vigged consensus. The deep
# dive opens that up: for each market it lays the model probability beside EVERY
# pulled book's own de-vigged line, so you can see who's softest on the side the
# model favours (line shopping) and how wide the book-to-book spread is. Same
# read-only data + same de-vig as the card — no model/value change (shadow).

# (display key, friendly title, the canonical selections that de-vig together)
_BOOK_MARKETS = (
    ("h2h", "Match result", ["home", "draw", "away"]),
    ("ou15", "Over / Under 1.5 goals", ["over_1.5", "under_1.5"]),
    ("ou25", "Over / Under 2.5 goals", ["over_2.5", "under_2.5"]),
    ("ou35", "Over / Under 3.5 goals", ["over_3.5", "under_3.5"]),
    ("btts", "Both teams to score", ["btts_yes", "btts_no"]),
)


def _collect_by_book(odds, home_name: str, away_name: str) -> dict:
    """bookmaker → {canonical_sel: odds_decimal}. Per-book prices for the
    model-vs-every-book deep-dive comparison. When a book quotes the same line
    twice (e.g. once under ``totals`` and once under ``alternate_totals``) we keep
    the better price for the bettor, mirroring the card's best-price handling."""
    books: dict = {}
    for o in odds:
        canon = _canon(o.market_type, o.selection, home_name, away_name, o.point)
        if not canon:
            continue
        b = books.setdefault(o.bookmaker, {})
        if canon not in b or o.odds_decimal > b[canon]:
            b[canon] = o.odds_decimal
    return books


def build_book_comparison(match_id: int, cfg: dict | None = None) -> dict | None:
    """DF-08 — per-market model-vs-EVERY-book comparison for the WC deep dive.

    For each market (Match result / O/U 1.5·2.5·3.5 / BTTS) returns the model
    probability per selection, the de-vigged median market consensus, and — for
    every bookmaker that quotes a complete set of that market's selections — that
    book's own de-vigged probability, raw price, and the model edge
    (model − de-vigged book). Books are ordered by where the model sees the most
    value. Each selection also carries the single best price across all books for
    a line-shopping cue. Read-only over stored odds + the stored prediction
    (shadow); no new API cost. Returns ``None`` if the match doesn't exist."""
    threshold, ceiling = _trust_bounds(cfg)
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
        info = {
            "match_id": match_id,
            "home": home,
            "away": away,
            "home_fifa": m.home_team.fifa_code if m.home_team else None,
            "away_fifa": m.away_team.fifa_code if m.away_team else None,
            "date": m.date,
            "kickoff_time": m.kickoff_time,
            "stage": m.stage,
            "status": m.status,
            "home_goals": m.home_goals,
            "away_goals": m.away_goals,
        }
        pred = next((p for p in m.predictions if p.model_name == MODEL_NAME), None)
        data = _collect(m.odds, home, away)
        by_book = _collect_by_book(m.odds, home, away)

    model = _model_probs(pred)
    info["has_prediction"] = pred is not None
    info["lambda_home"] = pred.home_expected_goals if pred else None
    info["lambda_away"] = pred.away_expected_goals if pred else None
    info["most_likely_score"] = pred.most_likely_score if pred else None

    # h2h carries the team name; everything else its short label.
    labels = dict(_SHORT_LABELS)
    labels["home"] = f"Home ({home})"
    labels["away"] = f"Away ({away})"

    markets = []
    for key, title, sels in _BOOK_MARKETS:
        consensus, _ = _consensus(data, sels)        # de-vigged median across books

        books = []
        for book, prices in by_book.items():
            implied, complete = {}, True
            for sel in sels:
                dec = prices.get(sel)
                if not dec or dec <= 1.0:
                    complete = False
                    break
                implied[sel] = 1.0 / dec
            if not complete:                          # book must quote every side
                continue
            fair = _devig(implied)
            edges, trust = {}, {}
            for sel in sels:
                mp = model.get(sel)
                e = (mp - fair[sel]) if mp is not None else None
                edges[sel] = e
                trust[sel] = _edge_trust(e, threshold, ceiling)
            valid_edges = [e for e in edges.values() if e is not None]
            books.append({
                "book": book,
                "probs": fair,
                "raw": {sel: prices[sel] for sel in sels},
                "edges": edges,
                "trust": trust,
                "best_edge": max(valid_edges) if valid_edges else None,
            })

        if consensus is None and not books:
            continue                                  # market not priced → skip

        # Best price + book per selection (line-shopping cue).
        best = {}
        for sel in sels:
            d = data.get(sel) or {}
            bo, bk = d.get("best", (0.0, ""))
            best[sel] = {"odds": bo, "book": bk} if bo > 1.0 else None

        # Softest book first: where the model sees the most value.
        books.sort(key=lambda b: (b["best_edge"] is None, -(b["best_edge"] or 0.0)))

        markets.append({
            "key": key,
            "title": title,
            "selections": sels,
            "labels": {sel: labels.get(sel, sel) for sel in sels},
            "model": {sel: model.get(sel) for sel in sels},
            "consensus": consensus or {},
            "best": best,
            "books": books,
            "n_books": len(books),
        })

    info["markets"] = markets
    return info


# ============================================================================
# DF-09 — Line movement for backable selections (the CLV story)
# ============================================================================
# WCOdds keeps only the opening price (frozen on first insert) and the latest
# price — there is no per-snapshot tick history — so a backable selection's
# movement is the handful of real prices we actually hold, all on one consistent
# best-available-across-books basis: the opening line, the entry we logged (the
# best price when the value bet was found), the current best line, and the
# closing line frozen at kickoff. CLV (entry vs close) is the headline. Read-only
# over stored odds + stored value bets — no model/value change (shadow).

# A stored value bet's (market_type, canonical selection) → (research canon key so
# we can pull its prices out of _collect, friendly market label). The WC value
# finder only ever bets the O/U 2.5 line (value_finder.MARKET_TO_PROB), so totals
# map straight to the 2.5 selections.
_VB_TO_CANON = {
    ("h2h", "home"): ("home", "Match result"),
    ("h2h", "draw"): ("draw", "Match result"),
    ("h2h", "away"): ("away", "Match result"),
    ("totals", "over"): ("over_2.5", "Goals (O/U 2.5)"),
    ("totals", "under"): ("under_2.5", "Goals (O/U 2.5)"),
    ("btts", "yes"): ("btts_yes", "Both teams to score"),
    ("btts", "no"): ("btts_no", "Both teams to score"),
}


def _best_price(prices: list) -> float | None:
    """Best (longest) price in a list, or None when empty — the bettor-friendly
    pick, matching how entry/close are defined (best available at that time)."""
    return max(prices) if prices else None


def build_movement(match_id: int) -> dict | None:
    """DF-09 — line movement for each backable selection on a WC match (the CLV
    story). For every value bet logged on the match, trace its price on one
    consistent best-available-across-books basis — the opening line, the entry we
    logged, the current best line, and the closing line frozen at kickoff — plus
    the stored CLV (entry vs close; positive = we beat the close). WCOdds keeps
    only the opening + latest price (no tick history), so ``points`` is the real
    snapshots we hold, in time order, not a dense series.

    Read-only over stored odds + value bets; the WC system stays shadow /
    decision-support. Returns ``None`` if the match doesn't exist; ``selections``
    is ``[]`` when nothing has been flagged backable. Selections are ordered by
    CLV (strongest 'beat the close' first; unknown CLV last)."""
    with get_session() as session:
        m = session.execute(
            select(WCMatch)
            .where(WCMatch.id == match_id)
            .options(
                joinedload(WCMatch.home_team),
                joinedload(WCMatch.away_team),
                joinedload(WCMatch.odds),
                joinedload(WCMatch.value_bets),
            )
        ).unique().scalar_one_or_none()
        if not m:
            return None

        home = m.home_team.name if m.home_team else "?"
        away = m.away_team.name if m.away_team else "?"
        data = _collect(m.odds, home, away)
        # Snapshot the value bets to plain dicts while the session is open, so the
        # rest runs detached (mirrors build_book_comparison's session handling).
        vbs = [{
            "market_type": vb.market_type,
            "selection": vb.selection,
            "best_odds": vb.best_odds,
            "bookmaker": vb.bookmaker,
            "closing_odds": vb.closing_odds,
            "clv": vb.clv,
            "edge": vb.edge,
            "model_prob": vb.model_prob,
        } for vb in m.value_bets]
        info = {
            "match_id": match_id,
            "home": home,
            "away": away,
            "home_fifa": m.home_team.fifa_code if m.home_team else None,
            "away_fifa": m.away_team.fifa_code if m.away_team else None,
            "date": m.date,
            "kickoff_time": m.kickoff_time,
            "status": m.status,
        }

    # h2h carries the team name; every other selection uses its short label.
    labels = dict(_SHORT_LABELS)
    labels["home"], labels["away"], labels["draw"] = home, away, "Draw"

    selections = []
    for vb in vbs:
        mapped = _VB_TO_CANON.get((vb["market_type"], vb["selection"]))
        if not mapped:
            continue                          # a market we don't trace (defensive)
        canon, market_label = mapped
        d = data.get(canon) or {}
        open_price = _best_price(d.get("open") or [])
        cur_odds, cur_book = d.get("best", (0.0, ""))
        current = cur_odds if cur_odds > 1.0 else None
        entry = vb["best_odds"]
        close = vb["closing_odds"]

        # Real price snapshots in time order; skip any stage we don't hold.
        points = [(stage, price) for stage, price in (
            ("Open", open_price), ("Entry", entry),
            ("Current", current), ("Close", close),
        ) if price]

        selections.append({
            "market": market_label,
            "selection": labels.get(canon, canon),
            "canon": canon,
            "open": open_price,
            "entry": entry,
            "entry_book": vb["bookmaker"],
            "current": current,
            "current_book": cur_book or None,
            "close": close,
            "clv": vb["clv"],
            "edge": vb["edge"],
            "model_prob": vb["model_prob"],
            "points": points,
        })

    # Best CLV first (strongest beat-the-close story); unknown CLV sinks last.
    selections.sort(key=lambda s: (s["clv"] is None, -(s["clv"] or 0.0)))
    info["selections"] = selections
    info["has_movement"] = any(len(s["points"]) >= 2 for s in selections)
    return info


# ============================================================================
# DF-10 — group/qualification context + per-match model comparison
# ============================================================================
# Two read-only layers for the deep dive's final sections. Both stay shadow /
# decision-support: the qualification read is points-only context, and the model
# comparison reads the STORED Bayesian shadow prediction (never recomputed, never
# staked).

# FIFA 2026: 4 teams per group, 3 group games each; top 2 advance plus the 8 best
# third-placed teams across all 12 groups.
_GROUP_SLOTS = 3


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 4 -> '4th' (group tables only need 1–4)."""
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(n, f"{n}th")


def _team_rank(table: list[dict], team_id: int) -> int:
    """Current table position (1-based) of a team, or 0 if absent (defensive)."""
    for row in table:
        if row["id"] == team_id:
            return row["rank"]
    return 0


def _qual_status(pts: int, rem: int, others: list[tuple[int, int]]) -> str:
    """Conservative top-2 qualification read for one team, points-only. ``others``
    is ``[(current_points, remaining_matches), ...]`` for the rest of the group.

    Returns ``'clinched'`` (mathematically guaranteed a top-2 finish, whatever
    happens), ``'eliminated'`` (cannot reach top 2 even winning out), or
    ``'contention'``. Ties and head-to-head are assumed to break AGAINST the team
    so we never over-claim — a 'clinched'/'eliminated' label is always safe, and
    the genuinely uncertain best-third-place race (which depends on other groups)
    is left under 'contention' rather than guessed at."""
    team_max = pts + 3 * max(rem, 0)
    # Guaranteed top 2: at most one other team can even reach our current floor
    # (the points we already hold and can't lose), so at most one finishes above us.
    can_reach_floor = sum(1 for opts, orem in others
                          if opts + 3 * max(orem, 0) >= pts)
    if can_reach_floor <= 1:
        return "clinched"
    # Eliminated from top 2: two or more others already sit above our ceiling
    # (more points now than we could reach even by winning every remaining game).
    already_above = sum(1 for opts, _ in others if opts > team_max)
    if already_above >= 2:
        return "eliminated"
    return "contention"


def build_group_context(match_id: int) -> dict | None:
    """DF-10 — what this match means for the group. Read-only over stored teams +
    finished group results. For a group match: the current group table (both teams
    in the tie flagged) plus the qualification impact of each result — or the
    realised impact once it's played. For a knockout tie there is no table to move
    (single elimination), so we say exactly that. Returns ``None`` if the match
    doesn't exist. Pure context — nothing here is a bet or a model input."""
    with get_session() as session:
        m = session.execute(
            select(WCMatch)
            .where(WCMatch.id == match_id)
            .options(joinedload(WCMatch.home_team), joinedload(WCMatch.away_team))
        ).unique().scalar_one_or_none()
        if not m:
            return None

        home = m.home_team.name if m.home_team else "?"
        away = m.away_team.name if m.away_team else "?"
        info = {
            "match_id": match_id,
            "home": home, "away": away,
            "home_fifa": m.home_team.fifa_code if m.home_team else None,
            "away_fifa": m.away_team.fifa_code if m.away_team else None,
            "home_id": m.home_team_id, "away_id": m.away_team_id,
            "stage": m.stage, "group_letter": m.group_letter, "status": m.status,
            "home_goals": m.home_goals, "away_goals": m.away_goals,
            "is_group": False, "table": [], "scenarios": [], "realized": None,
        }
        group = m.group_letter
        if m.stage != "group" or not group:
            info["headline"] = (
                "Knockout tie — win or out. There's no group table to move here; "
                "the stake is a place in the next round.")
            return info

        group_teams = session.execute(
            select(WCTeam).where(WCTeam.group_letter == group)
        ).scalars().all()
        finished = session.execute(
            select(WCMatch).where(
                WCMatch.stage == "group",
                WCMatch.group_letter == group,
                WCMatch.status == "finished",
            )
        ).scalars().all()
        team_rows = [(t.id, t.name, t.fifa_code) for t in group_teams]
        results = [(mm.home_team_id, mm.away_team_id, mm.home_goals, mm.away_goals)
                   for mm in finished if mm.home_goals is not None]

    info["is_group"] = True
    home_id, away_id = info["home_id"], info["away_id"]

    # Standings from finished group results — same point logic as the WC hub.
    stats = {tid: {"id": tid, "name": nm, "fifa_code": fc, "played": 0, "won": 0,
                   "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "gd": 0, "points": 0}
             for tid, nm, fc in team_rows}
    for hid, aid, hg, ag in results:
        for tid, gf, ga in ((hid, hg, ag), (aid, ag, hg)):
            s = stats.get(tid)
            if not s:
                continue
            s["played"] += 1
            s["gf"] += gf
            s["ga"] += ga
            s["gd"] = s["gf"] - s["ga"]
            if gf > ga:
                s["won"] += 1
                s["points"] += 3
            elif gf == ga:
                s["drawn"] += 1
                s["points"] += 1
            else:
                s["lost"] += 1

    ordered = sorted(stats.values(),
                     key=lambda x: (-x["points"], -x["gd"], -x["gf"]))
    table = []
    for rank, s in enumerate(ordered, start=1):
        row = dict(s)
        row["rank"] = rank
        row["is_match_team"] = s["id"] in (home_id, away_id)
        table.append(row)
    info["table"] = table

    def _status_after(home_delta: int, away_delta: int) -> dict:
        """Points + qualification status for both match teams after a hypothetical
        result (the two play this game, everyone else's remaining games stand)."""
        snap = {}
        for tid, s in stats.items():
            rem = max(_GROUP_SLOTS - s["played"], 0)
            pts = s["points"]
            if tid == home_id:
                pts += home_delta
                rem = max(rem - 1, 0)
            elif tid == away_id:
                pts += away_delta
                rem = max(rem - 1, 0)
            snap[tid] = (pts, rem)
        out = {}
        for tid in (home_id, away_id):
            pts, rem = snap[tid]
            others = [snap[o] for o in snap if o != tid]
            out[tid] = (pts, _qual_status(pts, rem, others))
        return out

    if info["status"] == "finished":
        # The result is in: read each team's standing straight from the table.
        for tid in (home_id, away_id):
            s = stats.get(tid)
            if not s:
                continue
            rem = max(_GROUP_SLOTS - s["played"], 0)
            others = [(stats[o]["points"], max(_GROUP_SLOTS - stats[o]["played"], 0))
                      for o in stats if o != tid]
            stats[tid]["_status"] = _qual_status(s["points"], rem, others)
        info["realized"] = {
            "home_pts": stats.get(home_id, {}).get("points"),
            "home_status": stats.get(home_id, {}).get("_status", "contention"),
            "away_pts": stats.get(away_id, {}).get("points"),
            "away_status": stats.get(away_id, {}).get("_status", "contention"),
        }
        info["headline"] = (
            f"Group {group}: result in. {home} are {_ordinal(_team_rank(table, home_id))} "
            f"on {stats.get(home_id, {}).get('points', 0)}, {away} "
            f"{_ordinal(_team_rank(table, away_id))} on "
            f"{stats.get(away_id, {}).get('points', 0)}. Top 2 advance, plus the 8 "
            f"best third-placed teams.")
    else:
        for label, hd, ad in (
            (f"If {home} win", 3, 0),
            ("If they draw", 1, 1),
            (f"If {away} win", 0, 3),
        ):
            after = _status_after(hd, ad)
            hp, hs = after[home_id]
            ap, as_ = after[away_id]
            info["scenarios"].append({
                "label": label,
                "home_pts": hp, "home_status": hs,
                "away_pts": ap, "away_status": as_,
            })
        info["headline"] = (
            f"Group {group}: {home} are {_ordinal(_team_rank(table, home_id))} on "
            f"{stats.get(home_id, {}).get('points', 0)}, {away} "
            f"{_ordinal(_team_rank(table, away_id))} on "
            f"{stats.get(away_id, {}).get('points', 0)}. Top 2 advance, plus the 8 "
            f"best third-placed teams — here's what each result does.")
    return info


# Metrics we line the two models up on (both stored on every WCPrediction row).
_MODEL_METRICS = [
    ("home_win_prob", "Home win", "pct"),
    ("draw_prob", "Draw", "pct"),
    ("away_win_prob", "Away win", "pct"),
    ("over_25_prob", "Over 2.5 goals", "pct"),
    ("btts_prob", "Both teams to score", "pct"),
    ("home_expected_goals", "Home xG", "num"),
    ("away_expected_goals", "Away xG", "num"),
]


def build_model_comparison(match_id: int) -> dict | None:
    """DF-10 — per-match Bayesian-vs-Poisson read (shadow). Lines up the two
    STORED predictions for this match: the staked Poisson (model_name=MODEL_NAME)
    and the shadow Bayesian (model_name=MODEL_NAME_BAYES). Reads stored rows only —
    nothing is recomputed and nothing here places a bet; the Bayesian stays shadow
    / display-only, promotion is manual. Returns ``None`` if the match doesn't
    exist; per-metric rows are present only when the Poisson prediction exists, and
    the ``bayesian`` column is ``None`` until the shadow model has run."""
    from src.world_cup.bayesian_model import MODEL_NAME_BAYES  # lazy: pulls scipy
    with get_session() as session:
        m = session.execute(
            select(WCMatch)
            .where(WCMatch.id == match_id)
            .options(joinedload(WCMatch.home_team),
                     joinedload(WCMatch.away_team),
                     joinedload(WCMatch.predictions))
        ).unique().scalar_one_or_none()
        if not m:
            return None
        home = m.home_team.name if m.home_team else "?"
        away = m.away_team.name if m.away_team else "?"
        preds = {p.model_name: {k: getattr(p, k) for k, _, _ in _MODEL_METRICS}
                 for p in m.predictions}

    poisson = preds.get(MODEL_NAME)
    bayes = preds.get(MODEL_NAME_BAYES)
    info = {
        "match_id": match_id, "home": home, "away": away,
        "has_poisson": poisson is not None,
        "has_bayesian": bayes is not None,
        "rows": [], "agreement": None,
    }
    if not poisson:
        return info

    for key, label, kind in _MODEL_METRICS:
        pv = poisson.get(key)
        bv = bayes.get(key) if bayes else None
        delta = (bv - pv) if (pv is not None and bv is not None) else None
        info["rows"].append({"metric": label, "kind": kind,
                             "poisson": pv, "bayesian": bv, "delta": delta})

    # Do the two models agree on the most likely 1X2 outcome?
    if bayes:
        def _fav(p: dict) -> str:
            trio = {"home": p.get("home_win_prob"), "draw": p.get("draw_prob"),
                    "away": p.get("away_win_prob")}
            return max(trio, key=lambda k: trio[k] if trio[k] is not None else -1.0)

        label = {"home": f"a {home} win", "draw": "a draw", "away": f"an {away} win"}
        pf, bf = _fav(poisson), _fav(bayes)
        info["agreement"] = (
            f"Both models lean to {label[pf]}." if pf == bf
            else f"The models disagree on the lean — Poisson favours {label[pf]}, "
                 f"the Bayesian shadow favours {label[bf]}.")
    return info


# ============================================================================
# WC-11A-02 — Lineup impact: display-only adjusted-λ (the core "A1")
# ============================================================================
# Once the XI is confirmed, scale the model's STORED expected goals (λ) by how the
# announced XI's attacking firepower compares to the team's PREVIOUS XI:
#     lambda_adjusted = lambda_model × (Σ in-XI goal-share ÷ Σ baseline-XI goal-share)
# where a player's goal-share is his recent goals-per-90 (from the injected
# rate_lookup, WC-11A-01) and the baseline is the team's last captured XI. So a
# rotated-out striker (high goal-share) pulls the adjusted λ down; an upgrade lifts
# it. This is a what-if for the eye only — READ-ONLY, never written back to
# WCPrediction, never an edge or a bet. The model and value bets are untouched
# (shadow): the value finder keeps staking off the stored λ, not this number.

# Display-only guard: the what-if can move the model's λ by at most ±50%, so a thin
# player-rate resolve (only a striker or two matched) can't throw out a nonsensical
# number. A real rotation moves the ratio well inside this band.
_ADJ_RATIO_LO, _ADJ_RATIO_HI = 0.5, 1.5


def _resolve_share(rows: list[dict], nation: str, rate_lookup) -> tuple[dict, float, list]:
    """Resolve each XI row to its goal-share (recent goals-per-90 via ``rate_lookup``).
    Returns ``(share_by_name, total_share, missing_names)``. A player we can't rate
    (resolver returns None, or no goals-per-90) is excluded from the total and
    listed in ``missing`` — never guessed at, mirroring the WC-11A-01 resolver."""
    shares: dict = {}
    missing: list = []
    total = 0.0
    for r in rows:
        name = r.get("name")
        looked = rate_lookup(r.get("full_name") or name, nation, r.get("position"))
        gp90 = looked.get("goals_per_90") if looked else None
        if gp90 is None or gp90 < 0:
            shares[name] = None
            missing.append(name)
            continue
        shares[name] = float(gp90)
        total += float(gp90)
    return shares, total, missing


def _team_impact(leg: dict, sig_entry: dict, rate_lookup) -> dict:
    """Per-team adjusted-λ from the confirmed XI vs the baseline XI (pure; no DB).
    ``leg`` carries the team's nation, stored model λ, and the rich current +
    baseline starter rows; ``sig_entry`` is the team's ``lineup_signal`` entry
    (status / formation / rotation). Read-only — computes a display number, writes
    nothing."""
    nation = leg["nation"]
    if sig_entry.get("status") != "announced":
        return {"team": nation, "status": "not_announced"}

    formation = sig_entry.get("formation")
    heavy = bool(sig_entry.get("heavy_rotation"))
    changes = sig_entry.get("changes")
    lambda_model = leg.get("lambda_model")
    if lambda_model is None:                      # XI in, but the model hasn't run
        return {"team": nation, "status": "no_model", "formation": formation,
                "heavy_rotation": heavy, "changes": changes}

    cur_share, cur_total, missing = _resolve_share(leg["current"], nation, rate_lookup)
    _, base_total, _ = _resolve_share(leg["baseline"], nation, rate_lookup)

    # No usable baseline (first match, or too few players resolved either side) →
    # we have nothing honest to scale against, so the adjusted λ is just the model λ.
    baseline_available = bool(leg["baseline"]) and base_total > 0 and cur_total > 0
    if baseline_available:
        ratio = max(_ADJ_RATIO_LO, min(_ADJ_RATIO_HI, cur_total / base_total))
    else:
        ratio = 1.0
    lambda_adjusted = lambda_model * ratio
    delta = lambda_adjusted - lambda_model

    # Scorer board: the confirmed XI (in_xi) plus any baseline player rotated OUT
    # (in_xi False — surfaced so a dropped high-share striker explains the delta).
    # Each in-XI player's exp_goals is his slice of the adjusted λ; the rated slices
    # sum to lambda_adjusted. Highest goal-share first; unrated players sink last.
    cur_names = {r["name"] for r in leg["current"]}
    scorers: list = []
    for r in leg["current"]:
        share = cur_share.get(r["name"])
        exp = (share / cur_total * lambda_adjusted) if (share and cur_total > 0) else None
        scorers.append({"player": r["name"], "in_xi": True,
                        "share": share, "exp_goals": exp})
    for r in leg["baseline"]:
        if r["name"] in cur_names:
            continue
        looked = rate_lookup(r.get("full_name") or r["name"], nation, r.get("position"))
        gp90 = looked.get("goals_per_90") if looked else None
        scorers.append({"player": r["name"], "in_xi": False,
                        "share": gp90, "exp_goals": 0.0})       # benched → 0 this match
    scorers.sort(key=lambda s: (s["share"] is None, -(s["share"] or 0.0)))

    return {
        "team": nation, "status": "announced",
        "formation": formation, "heavy_rotation": heavy, "changes": changes,
        "lambda_model": lambda_model, "lambda_adjusted": lambda_adjusted,
        "delta": delta, "baseline_available": baseline_available,
        "scorers": scorers, "missing": missing,
        "n_xi": len(leg["current"]),
        "n_rated": sum(1 for v in cur_share.values() if v is not None),
    }


def build_lineup_impact(match_id: int, rate_lookup) -> dict | None:
    """WC-11A-02 — per-team display-only adjusted-λ for the deep dive (shadow).

    Reuses ``lineup_signal`` for the confirmed XI / formation / rotation truth, reads
    the STORED λ off the Poisson ``WCPrediction``, and scales it by the confirmed
    XI's goal-share vs the team's previous XI (see the section note). ``rate_lookup``
    ``(name, nation, position) -> dict|None`` is injected (the view passes
    ``player_rates.player_rate``) so the math stays unit-testable and this module
    stays free of the player-rate cache.

    READ-ONLY: no ``session.add`` / ``commit`` here, and nothing is written back to
    WCPrediction — the value finder still stakes off the stored λ, not this what-if.
    Returns ``None`` if the match doesn't exist; each team's ``status`` covers the
    not-announced / no-model cases."""
    sig = lineup_signal(match_id)
    if sig is None:
        return None
    sig_by_name = {t.get("team"): t for t in sig.get("teams", [])}

    with get_session() as session:
        m = session.execute(
            select(WCMatch)
            .where(WCMatch.id == match_id)
            .options(joinedload(WCMatch.home_team),
                     joinedload(WCMatch.away_team),
                     joinedload(WCMatch.predictions))
        ).unique().scalar_one_or_none()
        if not m:
            return None

        home = m.home_team.name if m.home_team else "?"
        away = m.away_team.name if m.away_team else "?"
        pred = next((p for p in m.predictions if p.model_name == MODEL_NAME), None)
        lam = ({m.home_team_id: pred.home_expected_goals,
                m.away_team_id: pred.away_expected_goals} if pred else {})

        legs = []
        for nation, tid in ((home, m.home_team_id), (away, m.away_team_id)):
            legs.append({
                "nation": nation,
                "lambda_model": lam.get(tid),
                "current": _starter_rows(session, match_id, tid),
                "baseline": _prior_starter_rows(session, tid, m.date, match_id),
            })
        info = {
            "match_id": match_id, "home": home, "away": away,
            "home_fifa": m.home_team.fifa_code if m.home_team else None,
            "away_fifa": m.away_team.fifa_code if m.away_team else None,
        }

    info["teams"] = [_team_impact(leg, sig_by_name.get(leg["nation"], {}), rate_lookup)
                     for leg in legs]
    return info
