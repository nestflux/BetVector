"""
WC-10-07 — rotation/absence flag (decision-support).

Verifies lineup_signal computes XI changes vs the team's previous captured XI,
flags heavy rotation at the config threshold, handles no-prior / not-announced /
unknown-match, and that the research card wires the flag in. In-memory.
"""

import ast
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.db import Base
import src.world_cup.lineups as lineups
from src.world_cup.lineups import lineup_signal, _rotation_threshold
from src.world_cup.models import WCTeam, WCMatch, WCLineup


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        WCTeam(id=1, name="Brazil", fifa_code="BRA", confederation="C", group_letter="A"),
        WCTeam(id=2, name="Scotland", fifa_code="SCO", confederation="U", group_letter="A"),
    ])
    yield s
    s.close()


def _patch(s, monkeypatch):
    @contextmanager
    def fake():
        yield s
    monkeypatch.setattr(lineups, "get_session", fake)


def _seed_xi(s, match_id, team_id, names, formation="4-3-3"):
    for nm in names:
        s.add(WCLineup(match_id=match_id, team_id=team_id, player_name=nm,
                       is_starter=1, formation=formation))


def _match(s, mid, date, status="scheduled"):
    s.add(WCMatch(id=mid, stage="group", group_letter="A", date=date,
                  kickoff_time="18:00", home_team_id=1, away_team_id=2, status=status))


def test_heavy_rotation_flagged(session, monkeypatch):
    s = session
    _match(s, 10, "2026-06-20", status="finished")   # prior
    _match(s, 13, "2026-06-25")                       # current
    prior = [f"P{i}" for i in range(11)]
    _seed_xi(s, 10, 1, prior)
    # keep 6, swap in 5 new → 5 changes (== threshold)
    _seed_xi(s, 13, 1, [f"P{i}" for i in range(6)] + [f"Q{i}" for i in range(5)])
    s.commit()
    _patch(s, monkeypatch)

    sig = lineup_signal(13)
    brazil = next(t for t in sig["teams"] if t["team"] == "Brazil")
    assert brazil["status"] == "announced"
    assert brazil["changes"] == 5 and brazil["heavy_rotation"] is True
    assert brazil["formation"] == "4-3-3" and len(brazil["xi"]) == 11
    # Scotland has no captured XI for this match
    scotland = next(t for t in sig["teams"] if t["team"] == "Scotland")
    assert scotland["status"] == "not_announced"


def test_light_rotation_not_flagged(session, monkeypatch):
    s = session
    _match(s, 10, "2026-06-20", status="finished")
    _match(s, 13, "2026-06-25")
    _seed_xi(s, 10, 1, [f"P{i}" for i in range(11)])
    _seed_xi(s, 13, 1, [f"P{i}" for i in range(9)] + ["Q0", "Q1"])   # 2 changes
    s.commit()
    _patch(s, monkeypatch)
    brazil = next(t for t in lineup_signal(13)["teams"] if t["team"] == "Brazil")
    assert brazil["changes"] == 2 and brazil["heavy_rotation"] is False


def test_no_prior_xi_means_changes_none(session, monkeypatch):
    s = session
    _match(s, 13, "2026-06-25")
    _seed_xi(s, 13, 1, [f"P{i}" for i in range(11)])
    s.commit()
    _patch(s, monkeypatch)
    brazil = next(t for t in lineup_signal(13)["teams"] if t["team"] == "Brazil")
    assert brazil["status"] == "announced"
    assert brazil["changes"] is None and brazil["heavy_rotation"] is False


def test_not_announced_when_no_xi(session, monkeypatch):
    s = session
    _match(s, 13, "2026-06-25")
    s.commit()
    _patch(s, monkeypatch)
    sig = lineup_signal(13)
    assert all(t["status"] == "not_announced" for t in sig["teams"])


def test_unknown_match_returns_none(session, monkeypatch):
    _patch(session, monkeypatch)
    assert lineup_signal(99999) is None


def test_rotation_threshold_from_config():
    assert _rotation_threshold() == 5    # config/worldcup_2026.yaml lineups.rotation_threshold


def test_dashboard_wires_lineup_flag():
    src = Path("src/delivery/views/world_cup.py").read_text()
    tree = ast.parse(src)
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_render_lineup_flag" in funcs
    assert "_render_lineup_flag(sel_id)" in src   # called from the research card
