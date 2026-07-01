"""WC "to qualify / to advance" market (WC-QUAL-01) — settles on WHO ADVANCED from a
knockout tie (a.e.t. + penalties), the counterpart to "Match result (90 min)".

Covers the advancement logic, the market-aware bet_result router, knockout-only
validation, and the end-to-end case that motivates the feature: a KO won on penalties
settles "to qualify" as a WIN while "match result (90 min)" is a loss.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.database.db as db_mod  # noqa: E402
import src.database.models  # noqa: E402,F401
from src.database.db import Base  # noqa: E402
import src.world_cup.regulation as reg_mod  # noqa: E402
from src.world_cup.bets import (  # noqa: E402
    _did_qualify, bet_result, is_valid_selection, load_wc_accumulators, load_wc_bets,
    log_wc_accumulator, log_wc_bet, settle_wc_accumulators, settle_wc_bets,
)
from src.world_cup.regulation import reconcile_knockout_regulation  # noqa: E402
from src.world_cup.models import WCMatch, WCTeam  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    orig_e, orig_f = db_mod._engine, db_mod._SessionFactory
    db_mod._engine, db_mod._SessionFactory = engine, Session
    try:
        yield Session
    finally:
        db_mod._engine, db_mod._SessionFactory = orig_e, orig_f


_SEQ = [0]


def _match(db, *, stage="round_of_32", status="finished", home_goals=None,
           away_goals=None, went_to_extra_time=0, home_goals_reg=None,
           away_goals_reg=None, home_pens=None, away_pens=None,
           home=None, away=None, date="2026-07-05"):
    _SEQ[0] += 1
    mid = _SEQ[0]
    h, a = 100 + mid, 200 + mid
    hn, an = home or f"Home{mid}", away or f"Away{mid}"   # unique names per call
    with db() as s:
        s.add(WCTeam(id=h, name=hn, fifa_code=f"H{mid % 99}",
                     confederation="UEFA", group_letter="A"))
        s.add(WCTeam(id=a, name=an, fifa_code=f"A{mid % 99}",
                     confederation="UEFA", group_letter="B"))
        s.add(WCMatch(id=mid, date=date, stage=stage, home_team_id=h, away_team_id=a,
                      status=status, home_goals=home_goals, away_goals=away_goals,
                      went_to_extra_time=went_to_extra_time,
                      home_goals_reg=home_goals_reg, away_goals_reg=away_goals_reg,
                      home_pens=home_pens, away_pens=away_pens))
        s.commit()
    return mid


def _ke(period, team, ttype="Goal"):
    return {"period": {"number": period}, "team": {"displayName": team},
            "type": {"text": ttype}}


# ---- market registration ----------------------------------------------------

def test_qualify_is_a_valid_market():
    assert is_valid_selection("QUALIFY", "home")
    assert is_valid_selection("QUALIFY", "away")
    assert not is_valid_selection("QUALIFY", "draw")     # a tie always has an advancer


# ---- _did_qualify: who advanced --------------------------------------------

def test_qualify_decided_in_90(db):
    mid = _match(db, home_goals=2, away_goals=0, went_to_extra_time=0)
    with db() as s:
        m = s.get(WCMatch, mid)
        assert _did_qualify(m, "home") is True and _did_qualify(m, "away") is False


def test_qualify_decided_in_extra_time(db):
    # 1-1 at 90, 2-1 after ET (a.e.t.); home advanced without a shootout
    mid = _match(db, home_goals=2, away_goals=1, went_to_extra_time=1,
                 home_goals_reg=1, away_goals_reg=1)
    with db() as s:
        m = s.get(WCMatch, mid)
        assert _did_qualify(m, "home") is True and _did_qualify(m, "away") is False


def test_qualify_decided_on_penalties(db):
    # 1-1 a.e.t.; home wins the shootout 4-2 -> home advances
    mid = _match(db, home_goals=1, away_goals=1, went_to_extra_time=1,
                 home_goals_reg=1, away_goals_reg=1, home_pens=4, away_pens=2)
    with db() as s:
        m = s.get(WCMatch, mid)
        assert _did_qualify(m, "home") is True and _did_qualify(m, "away") is False


def test_qualify_defers_until_shootout_captured(db):
    # level a.e.t. but the shootout isn't captured yet -> defer (pending)
    mid = _match(db, home_goals=1, away_goals=1, went_to_extra_time=1,
                 home_goals_reg=1, away_goals_reg=1)  # pens NULL
    with db() as s:
        assert _did_qualify(s.get(WCMatch, mid), "home") is None


def test_qualify_none_for_group_or_unfinished(db):
    grp = _match(db, stage="group", home_goals=2, away_goals=1)
    sched = _match(db, status="scheduled")
    with db() as s:
        assert _did_qualify(s.get(WCMatch, grp), "home") is None      # no per-tie advancer
        assert _did_qualify(s.get(WCMatch, sched), "home") is None    # not played


# ---- bet_result router ------------------------------------------------------

def test_bet_result_routes_qualify_vs_90min(db):
    # 1-1 at 90 AND a.e.t.; home wins on pens. QUALIFY(home)=won; 1X2(home)=lost (draw)
    mid = _match(db, home_goals=1, away_goals=1, went_to_extra_time=1,
                 home_goals_reg=1, away_goals_reg=1, home_pens=5, away_pens=4)
    with db() as s:
        m = s.get(WCMatch, mid)
        assert bet_result(m, "QUALIFY", "home") == "won"
        assert bet_result(m, "QUALIFY", "away") == "lost"
        assert bet_result(m, "1X2", "home") == "lost"      # 90-min draw
        assert bet_result(m, "1X2", "draw") == "won"        # 90-min draw
    # QUALIFY never returns void; a deferred qualify is 'pending'
    pend = _match(db, home_goals=1, away_goals=1, went_to_extra_time=1)  # pens NULL
    with db() as s:
        assert bet_result(s.get(WCMatch, pend), "QUALIFY", "home") == "pending"


# ---- log validation: knockout-only -----------------------------------------

def test_log_qualify_rejected_on_group_match(db):
    grp = _match(db, stage="group", home_goals=2, away_goals=1)
    ko = _match(db, stage="round_of_32", home_goals=2, away_goals=1)
    assert log_wc_bet(1, grp, "QUALIFY", "home", 1.5, 10.0) is None   # group -> rejected
    assert isinstance(log_wc_bet(1, ko, "QUALIFY", "home", 1.5, 10.0), int)  # KO -> ok


def test_log_accumulator_rejects_qualify_group_leg(db):
    grp = _match(db, stage="group", home_goals=2, away_goals=1)
    ko = _match(db, stage="round_of_16", home_goals=1, away_goals=0)
    # one QUALIFY leg on a group match rejects the whole slip
    assert log_wc_accumulator(1, [
        {"match_id": ko, "market_type": "QUALIFY", "selection": "home", "odds": 1.6},
        {"match_id": grp, "market_type": "QUALIFY", "selection": "home", "odds": 1.8},
    ], 10.0) is None


# ---- end-to-end: the motivating case ---------------------------------------

def test_single_to_qualify_settles_on_advancement(db):
    # Spain 1-1 Morocco a.e.t., Spain (home) win 4-2 on pens.
    mid = _match(db, home_goals=1, away_goals=1, went_to_extra_time=1,
                 home_goals_reg=1, away_goals_reg=1, home_pens=4, away_pens=2)
    qwin = log_wc_bet(1, mid, "QUALIFY", "home", 1.7, 10.0)   # Spain to qualify
    qlose = log_wc_bet(1, mid, "QUALIFY", "away", 2.2, 10.0)  # Morocco to qualify
    win90 = log_wc_bet(1, mid, "1X2", "home", 2.5, 10.0)      # Spain to win in 90
    assert settle_wc_bets() == 3
    bets = {b["id"]: b for b in load_wc_bets(1)}
    assert bets[qwin]["status"] == "won" and bets[qwin]["pnl"] == 7.0
    assert bets[qlose]["status"] == "lost"
    assert bets[win90]["status"] == "lost"    # 90-min draw — the whole point


def test_qualify_acca_leg_settles(db):
    ko = _match(db, home_goals=1, away_goals=1, went_to_extra_time=1,
                home_goals_reg=1, away_goals_reg=1, home_pens=3, away_pens=1)  # home adv
    grp = _match(db, stage="group", home_goals=2, away_goals=0,
                 home="Brazil", away="Chile")
    aid = log_wc_accumulator(1, [
        {"match_id": ko, "market_type": "QUALIFY", "selection": "home", "odds": 1.6},
        {"match_id": grp, "market_type": "1X2", "selection": "home", "odds": 1.5},
    ], 10.0)
    assert settle_wc_accumulators() == 1
    acca = load_wc_accumulators(1)[0]
    assert acca["status"] == "won"            # qualify leg + group win both landed
    assert acca["pnl"] == round(10 * (1.6 * 1.5 - 1), 2)


# ---- reconciler captures the shootout score --------------------------------

def _patch_espn(monkeypatch, events, key_events):
    monkeypatch.setattr(reg_mod, "fetch_espn_results_for_date", lambda _d: events)
    monkeypatch.setattr(reg_mod, "_fetch_key_events", lambda _id: key_events)


def test_reconcile_captures_pens(monkeypatch, db):
    mid = _match(db, home="Spain", away="Morocco", home_goals=1, away_goals=1,
                 date="2026-07-05")
    espn = [{"home_name": "Spain", "away_name": "Morocco", "home_goals": 1,
             "away_goals": 1, "date": "2026-07-05", "espn_event_id": "E1",
             "detail": "FT-Pens", "home_pens": 4, "away_pens": 2}]
    _patch_espn(monkeypatch, espn, [_ke(1, "Spain"), _ke(2, "Morocco")])
    reconcile_knockout_regulation()
    with db() as s:
        m = s.get(WCMatch, mid)
        assert m.home_pens == 4 and m.away_pens == 2
        assert _did_qualify(m, "home") is True     # now resolvable


def test_reconcile_maps_flipped_pens_orientation(monkeypatch, db):
    # stored row has Morocco at home; ESPN reports Spain at home
    mid = _match(db, home="Morocco", away="Spain", home_goals=1, away_goals=1,
                 date="2026-07-05")
    espn = [{"home_name": "Spain", "away_name": "Morocco", "home_goals": 1,
             "away_goals": 1, "date": "2026-07-05", "espn_event_id": "E2",
             "detail": "FT-Pens", "home_pens": 4, "away_pens": 2}]  # Spain won pens
    _patch_espn(monkeypatch, espn, [_ke(1, "Spain"), _ke(2, "Morocco")])
    reconcile_knockout_regulation()
    with db() as s:
        m = s.get(WCMatch, mid)
        # stored home is Morocco -> home_pens should be Morocco's 2, not Spain's 4
        assert m.home_pens == 2 and m.away_pens == 4
        assert _did_qualify(m, "away") is True     # Spain (stored away) advanced
