"""WC-11A-04 — Player watch extras (booking risk · star absence · milestones).

Three layers, mirroring every WC-11A UI issue:
  1. The pure logic (research._next_milestone / _team_watch) — exact, no DB, with an
     injected fake rate_lookup so the booking-risk / star-absence / milestone rules are
     pinned down independently of the 29k-row player cache.
  2. The DB-backed builder (research.build_player_watch) over a seeded in-memory match
     WITH a prior XI (so the star-absence path is real), proven READ-ONLY (no odds
     pulled, nothing written back).
  3. data → render: AST-exec the view's pure HTML helpers over the built data and prove
     the booking / absence / milestone notes render, the empty state is graceful, and a
     hostile name is escaped.

Player watch spends ZERO Odds API credits — these are squad facts (card rate, who's
missing, caps/goals), built entirely from the confirmed XI + the player-rate cache.
"""

import ast
from contextlib import contextmanager
from html import escape
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.research as research
import src.world_cup.lineups as lineups
from src.world_cup.research import build_player_watch, _next_milestone, _team_watch
from src.world_cup.predictor import MODEL_NAME
from src.world_cup.models import WCTeam, WCMatch, WCPrediction, WCLineup

DD = Path(__file__).resolve().parents[1] / "src" / "delivery" / "views" / "wc_deep_dive.py"


# ---------------------------------------------------------------------------
# helpers + a fake squad
# ---------------------------------------------------------------------------

def _rows(names):
    """XI rows in the shape lineups._starter_rows returns (full_name/position None so
    the fake lookup resolves by the short name, as the real resolver would)."""
    return [{"name": n, "full_name": None, "position": None} for n in names]


def _leg(nation, current, baseline):
    return {"nation": nation, "current": _rows(current), "baseline": _rows(baseline)}


def _lookup(rates):
    """A fake rate_lookup(name, nation, position) -> profile | None, keyed by name.
    ``rates`` maps name -> a dict of the fields _team_watch reads; unknown -> None."""
    def f(name, nation, position):
        v = rates.get(name)
        return dict(v) if v is not None else None
    return f


# A clean role player: no booking risk, no milestone, not a star.
CLEAN = {"goals_per_90": 0.12, "yellows_per_90": 0.05, "market_value_eur": 5_000_000,
         "intl_caps": 12, "intl_goals": 1, "is_pen_taker": False, "source": "club"}

RATES = {
    **{f"P{i}": CLEAN for i in range(7)},           # clean Brazil role players
    **{f"Q{i}": CLEAN for i in range(11)},          # clean Scotland XI (nothing flagged)
    # In Brazil's CURRENT XI:
    "Clogger": {**CLEAN, "yellows_per_90": 0.55, "market_value_eur": 30_000_000},  # booking risk
    "Anchor":  {**CLEAN, "yellows_per_90": 0.20, "intl_caps": 30},                 # below the line
    "Capsman": {**CLEAN, "intl_caps": 98, "market_value_eur": 35_000_000},         # → 100 caps
    "Goalman": {**CLEAN, "intl_goals": 48, "intl_caps": 70, "market_value_eur": 35_000_000},  # → 50 goals
    # In Brazil's PRIOR XI but benched now → absent stars:
    "Star":    {**CLEAN, "market_value_eur": 180_000_000, "goals_per_90": 0.50},   # star by value
    "Veteran": {**CLEAN, "market_value_eur": 10_000_000, "goals_per_90": 0.66,     # star by g/90
                "intl_caps": 119, "intl_goals": 60},
}
RL = _lookup(RATES)

SIG_ON = {"status": "announced", "formation": "4-2-3-1",
          "heavy_rotation": False, "changes": 2}

BRA_NOW = [f"P{i}" for i in range(7)] + ["Clogger", "Anchor", "Capsman", "Goalman"]
BRA_PRIOR = [f"P{i}" for i in range(7)] + ["Star", "Veteran", "Capsman", "Goalman"]


# ---------------------------------------------------------------------------
# 1. pure logic
# ---------------------------------------------------------------------------

def test_next_milestone_only_fires_when_close():
    assert _next_milestone(48, 50, 5) == 50          # 2 away
    assert _next_milestone(49, 50, 5) == 50          # 1 away — must not be excluded
    assert _next_milestone(44, 50, 5) is None        # 6 away → too far
    assert _next_milestone(99, 50, 5) == 100         # next band
    assert _next_milestone(50, 50, 5) is None        # just hit it; next (100) is 50 away
    assert _next_milestone(0, 50, 5) is None         # a fresh count never flags
    assert _next_milestone(None, 50, 5) is None
    assert _next_milestone(9, 10, 3) == 10
    assert _next_milestone(6, 10, 3) is None          # 4 away
    # floor: a low international-goal tally isn't a landmark, even if it's "close".
    assert _next_milestone(9, 10, 3, floor=20) is None    # would-be 10 is below the floor
    assert _next_milestone(19, 10, 3, floor=20) == 20     # 20 clears the floor


def test_not_announced_is_a_clean_minimal_state():
    out = _team_watch(_leg("Brazil", [], []), {"status": "not_announced"}, RL)
    assert out == {"team": "Brazil", "status": "not_announced"}


def test_booking_risk_flags_card_prone_starters_sorted():
    """High recent yellow-card rate → flagged; a clean / below-threshold starter is not;
    most card-prone first."""
    rates = {**RATES, "Clogger2": {**CLEAN, "yellows_per_90": 0.42}}
    out = _team_watch(_leg("Brazil", ["P0", "Anchor", "Clogger", "Clogger2"], []),
                      SIG_ON, _lookup(rates))
    names = [b["player"] for b in out["booking_risk"]]
    assert names == ["Clogger", "Clogger2"]          # 0.55 before 0.42; P0/Anchor out
    assert out["booking_risk"][0]["yellows_per_90"] == pytest.approx(0.55)


def test_star_absence_from_baseline_by_value_or_form_sorted():
    """A high-value OR high-scoring player in the previous XI but not this one is an
    absent star; a baseline player still in the XI is not; ranked by value."""
    out = _team_watch(_leg("Brazil", BRA_NOW, BRA_PRIOR), SIG_ON, RL)
    absent = [a["player"] for a in out["absent_stars"]]
    assert absent == ["Star", "Veteran"]             # 180m before the g/90 veteran
    # Capsman/Goalman are in BOTH XIs → never "absent"; clean P-players aren't stars.
    assert "Capsman" not in absent and "P0" not in absent


def test_milestones_from_current_xi_sorted_by_closeness():
    out = _team_watch(_leg("Brazil", BRA_NOW, BRA_PRIOR), SIG_ON, RL)
    miles = {(m["player"], m["kind"]): m for m in out["milestones"]}
    assert miles[("Capsman", "caps")]["target"] == 100
    assert miles[("Capsman", "caps")]["away"] == 2
    assert miles[("Goalman", "goals")]["target"] == 50
    assert miles[("Goalman", "goals")]["away"] == 2
    # Sorted nearest-first (both 2 away here) and only genuine near-misses appear.
    assert all(m["away"] <= 5 for m in out["milestones"])


def test_quiet_xi_is_a_graceful_empty_state():
    """A clean XI with no rotation, no card-prone starter and no milestone yields empty
    lists — the card will show 'Nothing flagged', not a crash."""
    out = _team_watch(_leg("Scotland", [f"Q{i}" for i in range(11)],
                           [f"Q{i}" for i in range(11)]), SIG_ON, RL)
    assert out["status"] == "announced"
    assert out["booking_risk"] == [] and out["absent_stars"] == []
    assert out["milestones"] == [] and out["n_flags"] == 0


def test_star_absence_needs_a_baseline():
    """First captured XI (no prior) → no absence callout, even with stars on the pitch."""
    out = _team_watch(_leg("Brazil", BRA_NOW, []), SIG_ON, RL)
    assert out["absent_stars"] == []


def test_watch_needs_no_model_lambda():
    """Player watch is squad facts, not a model output — it must build from a leg that
    carries no stored λ at all (so it shows the moment the XI lands, before predict)."""
    leg = {"nation": "Brazil", "current": _rows(["Clogger", "P0"]), "baseline": []}
    out = _team_watch(leg, SIG_ON, RL)               # note: no "lambda_model" key
    assert out["status"] == "announced"
    assert [b["player"] for b in out["booking_risk"]] == ["Clogger"]


# ---------------------------------------------------------------------------
# 2. DB-backed builder (shares the WC-11A read; real baseline; read-only; no odds)
# ---------------------------------------------------------------------------

MATCH_ID = 60
PRIOR_ID = 59
SCO_XI = [f"Q{i}" for i in range(11)]


@pytest.fixture
def seeded(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="CONMEBOL", group_letter="C"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="UEFA", group_letter="C"),
    ])
    # A PRIOR match (earlier date) gives each team a baseline XI: Brazil started Star +
    # Veteran there and benches them now → a real star-absence path.
    s.add(WCMatch(id=PRIOR_ID, stage="group", group_letter="C", date="2026-06-20",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="finished"))
    s.add(WCMatch(id=MATCH_ID, stage="group", group_letter="C", date="2026-06-25",
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status="scheduled"))
    s.add(WCPrediction(id=600, match_id=MATCH_ID, model_name=MODEL_NAME,
                       home_win_prob=0.62, draw_prob=0.22, away_win_prob=0.16,
                       home_expected_goals=2.0, away_expected_goals=1.2,
                       over_25_prob=0.55, btts_prob=0.40))
    for nm in BRA_PRIOR:
        s.add(WCLineup(match_id=PRIOR_ID, team_id=1, player_name=nm, is_starter=1,
                       formation="4-2-3-1", captured_at="2026-06-20T17:00"))
    for nm in SCO_XI:
        s.add(WCLineup(match_id=PRIOR_ID, team_id=2, player_name=nm, is_starter=1,
                       formation="4-4-2", captured_at="2026-06-20T17:00"))
    for nm in BRA_NOW:
        s.add(WCLineup(match_id=MATCH_ID, team_id=1, player_name=nm, is_starter=1,
                       formation="4-2-3-1", captured_at="2026-06-25T17:00"))
    for nm in SCO_XI:
        s.add(WCLineup(match_id=MATCH_ID, team_id=2, player_name=nm, is_starter=1,
                       formation="4-4-2", captured_at="2026-06-25T17:00"))
    s.commit()

    @contextmanager
    def fake():
        yield s

    monkeypatch.setattr(research, "get_session", fake)
    monkeypatch.setattr(lineups, "get_session", fake)
    yield s
    s.close()


def test_build_player_watch_end_to_end(seeded):
    data = build_player_watch(MATCH_ID, RL)
    assert data["match_id"] == MATCH_ID
    bra = next(t for t in data["teams"] if t["team"] == "Brazil")
    assert bra["status"] == "announced"
    assert [b["player"] for b in bra["booking_risk"]] == ["Clogger"]
    assert [a["player"] for a in bra["absent_stars"]] == ["Star", "Veteran"]
    assert {(m["player"], m["target"]) for m in bra["milestones"]} == \
        {("Capsman", 100), ("Goalman", 50)}
    # Scotland's XI is clean and unchanged → a graceful empty card.
    sco = next(t for t in data["teams"] if t["team"] == "Scotland")
    assert sco["status"] == "announced" and sco["n_flags"] == 0


def test_build_player_watch_unknown_match_is_none(seeded):
    assert build_player_watch(999, RL) is None


def test_build_player_watch_is_read_only(seeded):
    """Shadow + no-cost guarantee: building the notes must not add a row or touch the
    stored λ (no session.add / commit), and no odds are pulled anywhere in the path."""
    before_pred = seeded.query(WCPrediction).count()
    before_lineup = seeded.query(WCLineup).count()
    build_player_watch(MATCH_ID, RL)
    pred = seeded.query(WCPrediction).filter_by(match_id=MATCH_ID).one()
    assert pred.home_expected_goals == 2.0 and pred.away_expected_goals == 1.2
    assert seeded.query(WCPrediction).count() == before_pred
    assert seeded.query(WCLineup).count() == before_lineup


# ---------------------------------------------------------------------------
# 3. data -> render: AST-exec the view's pure HTML helpers
# ---------------------------------------------------------------------------

_PURE_FUNCS = {"_eur_short", "_player_watch_card_html"}


def _view_namespace():
    tree = ast.parse(DD.read_text())
    ns = {"escape": escape}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<dd>", "exec"), ns)
        elif isinstance(node, ast.FunctionDef) and node.name in _PURE_FUNCS:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<dd>", "exec"), ns)
    return ns


def test_eur_short_formats_compactly():
    ns = _view_namespace()
    f = ns["_eur_short"]
    assert f(180_000_000) == "€180M" and f(900_000) == "€900k"
    assert f(None) == "—" and f(0) == "—"


def test_view_renders_player_watch_card_from_real_built_data(seeded):
    ns = _view_namespace()
    data = build_player_watch(MATCH_ID, RL)
    bra = next(t for t in data["teams"] if t["team"] == "Brazil")
    card = ns["_player_watch_card_html"](bra)
    assert "Booking risk" in card and "Clogger" in card and "YEL" in card
    assert "Star absence" in card and "Brazil without Star" in card and "€180M" in card
    assert "Milestones" in card and "100 caps" in card and "50 intl goals" in card


def test_view_card_has_a_graceful_empty_state(seeded):
    ns = _view_namespace()
    data = build_player_watch(MATCH_ID, RL)
    sco = next(t for t in data["teams"] if t["team"] == "Scotland")
    card = ns["_player_watch_card_html"](sco)
    assert "Nothing flagged" in card
    assert "Booking risk" not in card and "Star absence" not in card


def test_view_card_handles_not_announced():
    ns = _view_namespace()
    card = ns["_player_watch_card_html"]({"team": "Spain", "status": "not_announced"})
    assert "not announced" in card.lower()


def test_view_escapes_hostile_player_name():
    ns = _view_namespace()
    card = ns["_player_watch_card_html"]({
        "team": "Spain", "status": "announced", "formation": "4-3-3",
        "booking_risk": [{"player": "<img src=x onerror=alert(1)>", "yellows_per_90": 0.6}],
        "absent_stars": [], "milestones": [],
    })
    assert "<img src=x" not in card and "&lt;img" in card
