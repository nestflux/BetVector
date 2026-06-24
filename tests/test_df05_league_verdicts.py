"""DF-05 — league fixture verdicts (trust-weighted).

Pins the trust-tier mapping, the verdict classification over the ValueFinder's
stored value bets, the label mapping, and the colour-tiered chip (proven reads
stronger than unproven). Pure — imports the streamlit-free ``_verdict`` module
directly (fixtures.py runs Streamlit at import, so the logic lives apart).
"""

from types import SimpleNamespace

from src.delivery.views._verdict import (
    LeagueVerdict,
    TRUST_PROVEN, TRUST_PROMISING, TRUST_UNPROVEN,
    build_league_trust_map,
    classify_league_verdict,
    league_verdict_chip_html,
    trust_tier_for_multiplier,
)

COLOURS = {"green": "#3FB950", "yellow": "#D29922", "text_secondary": "#8B949E"}
HOME, AWAY = "Arsenal", "Chelsea"


def vb(edge, model_prob=0.55, odds=2.10, book="Pinnacle"):
    return {"edge": edge, "model_prob": model_prob, "confidence": "medium",
            "odds": odds, "bookmaker": book}


# ----------------------------------------------------------- trust tier

def test_trust_tier_thresholds():
    assert trust_tier_for_multiplier(1.5) == TRUST_PROVEN
    assert trust_tier_for_multiplier(2.0) == TRUST_PROVEN
    assert trust_tier_for_multiplier(1.0) == TRUST_PROMISING
    assert trust_tier_for_multiplier(1.49) == TRUST_PROMISING
    assert trust_tier_for_multiplier(0.5) == TRUST_UNPROVEN
    assert trust_tier_for_multiplier(0.99) == TRUST_UNPROVEN


def test_trust_tier_bad_value_defaults_promising():
    assert trust_tier_for_multiplier(None) == TRUST_PROMISING
    assert trust_tier_for_multiplier("nope") == TRUST_PROMISING


def test_build_league_trust_map():
    leagues = [
        SimpleNamespace(short_name="ELC", strategy=SimpleNamespace(stake_multiplier=1.5)),
        SimpleNamespace(short_name="EPL", strategy=SimpleNamespace(stake_multiplier=1.0)),
        SimpleNamespace(short_name="FL1", strategy=SimpleNamespace(stake_multiplier=0.5)),
        SimpleNamespace(short_name="NOSTRAT", strategy=None),       # → promising default
        SimpleNamespace(short_name=None, strategy=None),             # skipped (no name)
    ]
    m = build_league_trust_map(leagues)
    assert m == {"ELC": TRUST_PROVEN, "EPL": TRUST_PROMISING,
                 "FL1": TRUST_UNPROVEN, "NOSTRAT": TRUST_PROMISING}


def test_build_trust_map_empty():
    assert build_league_trust_map(None) == {}
    assert build_league_trust_map([]) == {}


# ----------------------------------------------------------- classify

def test_no_value_bets_is_none():
    v = classify_league_verdict({}, HOME, AWAY, TRUST_PROVEN)
    assert v.tier == "none" and v.trust == TRUST_PROVEN
    assert classify_league_verdict(None, HOME, AWAY, TRUST_PROMISING).tier == "none"


def test_single_value_bet():
    info = {("1X2", "home"): vb(0.074, odds=2.10, book="FanDuel")}
    v = classify_league_verdict(info, HOME, AWAY, TRUST_PROMISING)
    assert v.tier == "value" and v.selection == "home" and v.label == HOME
    assert v.edge == 0.074 and v.odds == 2.10 and v.bookmaker == "FanDuel"
    assert v.model_prob == 0.55


def test_picks_highest_edge():
    info = {
        ("1X2", "home"): vb(0.04),
        ("OU25", "over"): vb(0.11),
        ("BTTS", "yes"): vb(0.07),
    }
    v = classify_league_verdict(info, HOME, AWAY, TRUST_PROMISING)
    assert v.selection == "over" and v.market_type == "OU25" and v.edge == 0.11


def test_label_mapping():
    cases = {
        ("1X2", "home"): HOME, ("1X2", "away"): AWAY, ("1X2", "draw"): "Draw",
        ("OU25", "over"): "Over 2.5", ("OU25", "under"): "Under 2.5",
        ("OU15", "over"): "Over 1.5", ("OU35", "under"): "Under 3.5",
        ("BTTS", "yes"): "BTTS Yes", ("BTTS", "no"): "BTTS No",
    }
    for (mt, sel), expected in cases.items():
        v = classify_league_verdict({(mt, sel): vb(0.08)}, HOME, AWAY, TRUST_PROMISING)
        assert v.label == expected, f"{mt}/{sel} → {v.label}, expected {expected}"


# ----------------------------------------------------------- chip html

def test_chip_none_is_muted():
    html = league_verdict_chip_html(LeagueVerdict(tier="none"), COLOURS)
    assert "no model edge" in html
    assert COLOURS["text_secondary"] in html
    assert "✓" not in html and "⚠" not in html


def test_chip_proven_is_green_pill():
    v = classify_league_verdict({("1X2", "home"): vb(0.074)}, HOME, AWAY, TRUST_PROVEN)
    html = league_verdict_chip_html(v, COLOURS)
    assert "✓" in html and "Arsenal" in html and "+7.4%" in html
    assert f"background:{COLOURS['green']}" in html      # filled pill = strongest
    assert "\U0001F7E2" in html                          # 🟢
    assert "@ 2.10" in html


def test_chip_promising_is_green_text():
    v = classify_league_verdict({("OU25", "over"): vb(0.09)}, HOME, AWAY, TRUST_PROMISING)
    html = league_verdict_chip_html(v, COLOURS)
    assert "✓" in html and "Over 2.5" in html
    assert f"color:{COLOURS['green']}" in html
    assert f"background:{COLOURS['green']}" not in html   # not a pill
    assert "\U0001F7E1" in html                           # 🟡


def test_chip_unproven_is_amber_caution():
    v = classify_league_verdict({("1X2", "away"): vb(0.10)}, HOME, AWAY, TRUST_UNPROVEN)
    html = league_verdict_chip_html(v, COLOURS)
    assert "⚠" in html and "Chelsea" in html
    assert f"color:{COLOURS['yellow']}" in html
    assert "unproven league" in html
    assert "\U0001F534" in html                           # 🔴


def test_chip_escapes_label():
    # A malicious/odd team name must be HTML-escaped, not injected.
    info = {("1X2", "home"): vb(0.08)}
    v = classify_league_verdict(info, "<script>x</script>", AWAY, TRUST_PROMISING)
    html = league_verdict_chip_html(v, COLOURS)
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_chip_without_odds_omits_price():
    v = classify_league_verdict({("1X2", "home"): vb(0.08, odds=None)}, HOME, AWAY, TRUST_PROMISING)
    html = league_verdict_chip_html(v, COLOURS)
    assert "@ " not in html
