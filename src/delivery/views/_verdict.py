"""
BetVector — League Fixture Verdicts (DF-05)
============================================
A decision-first verdict per league fixture, mirroring the World Cup verdict
(DF-04) but folding in each league's strategy/trust tier so a pick in a *proven*
league reads stronger than the same edge in an *unproven* one.

Pure helpers — no Streamlit, no DB, no model/value math. This deliberately lives
apart from ``fixtures.py`` (which runs Streamlit at import) so it stays unit-
testable. It does NOT recompute edges: it classifies the value bets the
ValueFinder already stored, passed in via the fixture's ``market_vb_info`` dict.

Trust tier comes from a league's ``stake_multiplier`` (leagues.yaml strategy
block, the same PC-25 source BankrollManager uses):
  🟢 proven     stake_multiplier >= 1.5  (verified edge — lean in / auto-bet)
  🟡 promising  stake_multiplier >= 1.0  (standard — analysis only)
  🔴 unproven   stake_multiplier <  1.0  (reduce exposure, keep learning)

Unlike the WC verdict there is deliberately NO "capped" tier here: the league
ValueFinder has no actionable-edge ceiling (leagues are calibrated and a proven
league genuinely auto-bets its edges), so surfacing a stored value bet as value
mirrors the league value path. Caution is expressed through the trust tier
instead — an unproven league's pick renders amber ("treat with caution").
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

TRUST_PROVEN = "proven"
TRUST_PROMISING = "promising"
TRUST_UNPROVEN = "unproven"

# Tier → the marker the rest of the app already uses (model_health, leagues.yaml).
_TRUST_MARK = {
    TRUST_PROVEN: "\U0001F7E2",      # 🟢
    TRUST_PROMISING: "\U0001F7E1",   # 🟡
    TRUST_UNPROVEN: "\U0001F534",    # 🔴
}

# (market_type, selection) → concise chip label. 1X2 home/away resolve to the
# actual team names at classification time; everything else is static.
_STATIC_LABELS = {
    ("1X2", "draw"): "Draw",
    ("OU25", "over"): "Over 2.5", ("OU25", "under"): "Under 2.5",
    ("OU15", "over"): "Over 1.5", ("OU15", "under"): "Under 1.5",
    ("OU35", "over"): "Over 3.5", ("OU35", "under"): "Under 3.5",
    ("BTTS", "yes"): "BTTS Yes", ("BTTS", "no"): "BTTS No",
}


def trust_tier_for_multiplier(stake_multiplier) -> str:
    """Map a league's ``stake_multiplier`` to its trust tier. Defaults to
    promising on a missing/garbage value (same neutral default BankrollManager
    uses)."""
    try:
        m = float(stake_multiplier)
    except (TypeError, ValueError):
        return TRUST_PROMISING
    if m >= 1.5:
        return TRUST_PROVEN
    if m >= 1.0:
        return TRUST_PROMISING
    return TRUST_UNPROVEN


def build_league_trust_map(leagues_cfg) -> dict:
    """``short_name`` → trust tier, from each league's
    ``strategy.stake_multiplier``. Built once per render (config is in-memory) so
    the per-fixture lookup adds no DB queries."""
    out: dict = {}
    for lg in (leagues_cfg or []):
        name = getattr(lg, "short_name", None)
        if not name:
            continue
        strat = getattr(lg, "strategy", None)
        mult = getattr(strat, "stake_multiplier", 1.0) if strat is not None else 1.0
        out[name] = trust_tier_for_multiplier(mult)
    return out


@dataclass
class LeagueVerdict:
    """One headline verdict for a league fixture (DF-05)."""
    tier: str                          # "value" | "none"
    trust: str = TRUST_PROMISING       # proven | promising | unproven
    market_type: str | None = None
    selection: str | None = None
    label: str | None = None
    edge: float | None = None
    model_prob: float | None = None
    odds: float | None = None
    bookmaker: str | None = None


def _verdict_label(market_type, selection, home_team, away_team) -> str:
    if (market_type, selection) == ("1X2", "home"):
        return home_team
    if (market_type, selection) == ("1X2", "away"):
        return away_team
    return _STATIC_LABELS.get((market_type, selection), f"{market_type} {selection}")


def classify_league_verdict(market_vb_info, home_team, away_team, trust) -> LeagueVerdict:
    """Best stored value bet for a fixture + the league trust tier.

    ``market_vb_info`` is ``{(market_type, selection): {edge, model_prob, odds,
    bookmaker, ...}}`` — exactly the ValueBets the ValueFinder already stored (no
    recompute). Empty → no actionable edge → tier "none". Otherwise the
    highest-edge pick becomes the verdict; the trust tier sets the emphasis at
    render time.
    """
    if not market_vb_info:
        return LeagueVerdict(tier="none", trust=trust)
    (mt, sel), info = max(
        market_vb_info.items(), key=lambda kv: kv[1].get("edge", 0.0)
    )
    return LeagueVerdict(
        tier="value", trust=trust, market_type=mt, selection=sel,
        label=_verdict_label(mt, sel, home_team, away_team),
        edge=info.get("edge"), model_prob=info.get("model_prob"),
        odds=info.get("odds"), bookmaker=info.get("bookmaker"),
    )


def league_verdict_chip_html(v, colours) -> str:
    """Colour-tiered verdict chip; the trust tier modulates the emphasis (DF-05):
    proven value = a filled green pill (the strongest, auto-bet tier); promising
    value = green text; unproven value = amber "treat with caution"; no edge =
    muted. ``colours`` is the page's COLOURS dict (green / yellow / text_secondary).
    """
    green = colours["green"]
    amber = colours["yellow"]
    dim = colours["text_secondary"]

    if v.tier == "none" or not v.label:
        return (
            f'<span style="font-family:Inter,sans-serif;font-size:12px;'
            f'color:{dim};">— no model edge</span>'
        )

    label = escape(v.label)
    edge = f"{v.edge:+.1%}" if v.edge is not None else ""
    mark = _TRUST_MARK.get(v.trust, "")
    price = (
        f' <span style="color:{dim};font-size:11px;">@ {v.odds:.2f}</span>'
        if v.odds else ""
    )

    if v.trust == TRUST_PROVEN:
        # Strongest: a filled green pill — these are the verified, auto-bet leagues.
        body = (
            f'<span style="font-family:Inter,sans-serif;font-size:12px;font-weight:600;'
            f'background:{green};color:#0D1117;padding:2px 9px;border-radius:10px;">'
            f'✓ {label} {edge}</span>'
        )
        note = f' <span style="font-size:11px;" title="proven league">{mark}</span>'
    elif v.trust == TRUST_UNPROVEN:
        body = (
            f'<span style="font-family:Inter,sans-serif;font-size:13px;font-weight:600;'
            f'color:{amber};">⚠ {label} {edge}</span>'
        )
        note = (
            f' <span style="font-size:11px;" title="unproven league">{mark}</span>'
            f' <span style="color:{dim};font-size:11px;">unproven league</span>'
        )
    else:  # promising
        body = (
            f'<span style="font-family:Inter,sans-serif;font-size:13px;font-weight:600;'
            f'color:{green};">✓ {label} {edge}</span>'
        )
        note = f' <span style="font-size:11px;" title="promising league">{mark}</span>'

    return f'{body}{price}{note}'
