"""WC Results tab (world_cup.py Section 8).

The hub runs ``st.*`` at import, so the tab's pure helpers (outcome / model pick /
date / row HTML) are exercised via AST-exec; plus source-level checks that the
tab is wired, reads finished matches, scores the model's call, escapes output, and
routes into the deep dive.
"""
from __future__ import annotations

import ast
from datetime import datetime
from html import escape
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / "src" / "delivery" / "views" / "world_cup.py"
HUB_SRC = HUB.read_text()

_PURE = {"_result_outcome", "_model_pick", "_pick_conf", "_short_date", "_result_row_html",
         "_was_pred_prematch", "_parse_ts"}


def _ns():
    ns = {
        "escape": escape, "datetime": datetime,
        "TEXT": "#E6EDF3", "TEXT_DIM": "#8B949E", "GREEN": "#3FB950",
        "RED": "#F85149", "BORDER": "#30363D",
        "_OUTCOME_WORD": {"H": "home win", "D": "draw", "A": "away win"},
    }
    for node in ast.parse(HUB_SRC).body:
        if isinstance(node, ast.FunctionDef) and node.name in _PURE:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<wc>", "exec"), ns)
    return ns


def _pred(h, d, a, score="1-0"):
    return SimpleNamespace(home_win_prob=h, draw_prob=d, away_win_prob=a, most_likely_score=score)


# ---- outcome ----------------------------------------------------------------

def test_outcome_home_draw_away():
    ns = _ns()
    assert ns["_result_outcome"](3, 0) == "H"
    assert ns["_result_outcome"](1, 1) == "D"
    assert ns["_result_outcome"](0, 2) == "A"


def test_outcome_none_when_unscored():
    ns = _ns()
    assert ns["_result_outcome"](None, 1) is None
    assert ns["_result_outcome"](2, None) is None


# ---- model pick -------------------------------------------------------------

def test_model_pick_is_argmax():
    ns = _ns()
    assert ns["_model_pick"](_pred(0.6, 0.25, 0.15)) == "H"
    assert ns["_model_pick"](_pred(0.2, 0.5, 0.3)) == "D"
    assert ns["_model_pick"](_pred(0.2, 0.3, 0.5)) == "A"


def test_model_pick_none_without_prediction():
    ns = _ns()
    assert ns["_model_pick"](None) is None  # backfilled history has no model call


def test_pick_conf_is_probability_of_called_outcome():
    ns = _ns()
    assert ns["_pick_conf"](_pred(0.6, 0.25, 0.15), "H") == 0.6
    assert ns["_pick_conf"](_pred(0.2, 0.5, 0.3), "D") == 0.5
    assert ns["_pick_conf"](None, None) is None


# ---- short date -------------------------------------------------------------

def test_short_date_formats_and_degrades():
    ns = _ns()
    assert ns["_short_date"]("2026-06-19") == "19 Jun"
    assert ns["_short_date"]("2026-06-19T18:00Z") == "19 Jun"
    assert ns["_short_date"](None) == ""
    assert ns["_short_date"]("garbage") == "garbage"


# ---- row HTML ---------------------------------------------------------------

def test_row_marks_correct_call_green_and_checks_winner():
    ns = _ns()
    # Brazil 3-0 Haiti, model called home → correct ✓, home name emboldened.
    html = ns["_result_row_html"]("19 Jun", "Brazil", "Haiti", "", "", 3, 0, "H", 0.62)
    assert "Model ✓" in html and "#3FB950" in html       # green tick
    assert "called home win" in html and "62%" in html    # confidence in the called outcome
    assert 'font-weight:700;">Brazil' in html             # winner emphasised


def test_row_marks_wrong_call_red():
    ns = _ns()
    html = ns["_result_row_html"]("19 Jun", "England", "Ghana", "", "", 0, 0, "H", 0.50)
    assert "Model ✗" in html and "#F85149" in html        # red cross (called H, was D)


def test_row_no_model_call_when_pick_none():
    ns = _ns()
    html = ns["_result_row_html"]("19 Jun", "Mexico", "South Africa", "", "", 2, 0, None, None)
    assert "no model call" in html
    assert "Model ✓" not in html and "Model ✗" not in html


def test_row_escapes_team_names():
    ns = _ns()
    html = ns["_result_row_html"]("19 Jun", "<b>x</b>", "Haiti", "", "", 1, 0, "H", 0.70)
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


# ---- structural wiring ------------------------------------------------------

# ---- temporal-integrity guard: back-filled predictions must not count --------

def _pred_at(created_at, h=0.6, d=0.25, a=0.15):
    return SimpleNamespace(home_win_prob=h, draw_prob=d, away_win_prob=a,
                           most_likely_score="1-0", created_at=created_at)


def _match_at(date, kickoff_time="18:00"):
    return SimpleNamespace(date=date, kickoff_time=kickoff_time)


def test_prematch_prediction_counts():
    ns = _ns()
    # created the morning of the match, before an 18:00 kickoff -> genuine call
    assert ns["_was_pred_prematch"](
        _pred_at("2026-06-20 09:30:00"), _match_at("2026-06-20")) is True


def test_backfilled_prediction_excluded():
    ns = _ns()
    # created days AFTER the match (the real bug) -> must not count
    assert ns["_was_pred_prematch"](
        _pred_at("2026-06-26 13:30:00"), _match_at("2026-06-11")) is False
    # created later the SAME day, after the 18:00 kickoff -> still excluded
    assert ns["_was_pred_prematch"](
        _pred_at("2026-06-20 20:00:00"), _match_at("2026-06-20", "18:00")) is False


def test_unknown_kickoff_falls_back_to_end_of_day():
    ns = _ns()
    # kickoff unknown: a same-date prediction counts, a later-date one does not
    assert ns["_was_pred_prematch"](
        _pred_at("2026-06-20 09:30:00"), _match_at("2026-06-20", None)) is True
    assert ns["_was_pred_prematch"](
        _pred_at("2026-06-26 13:30:00"), _match_at("2026-06-20", None)) is False


def test_no_prediction_or_no_timestamp_is_not_prematch():
    ns = _ns()
    assert ns["_was_pred_prematch"](None, _match_at("2026-06-20")) is False
    assert ns["_was_pred_prematch"](_pred_at(None), _match_at("2026-06-20")) is False


def test_results_gate_and_predictor_filter_wired():
    # Results render drops back-filled predictions before scoring the model.
    assert "_was_pred_prematch(pred, m)" in HUB_SRC
    # Root cause: predict_all only predicts upcoming scheduled matches.
    pred_src = (ROOT / "src" / "world_cup" / "predictor.py").read_text()
    assert 'WCMatch.status == "scheduled"' in pred_src
    assert "WCMatch.date >= today" in pred_src


def test_results_tab_registered():
    assert '"✅ Results"' in HUB_SRC
    assert "tab_results" in HUB_SRC
    assert "def _render_results" in HUB_SRC


def test_results_reads_finished_and_scores_model():
    assert 'WCMatch.status == "finished"' in HUB_SRC
    assert "MODEL_NAME" in HUB_SRC  # the model's pre-match call is matched by name


def test_results_routes_into_deep_dive():
    assert "wc_deep_dive_match_id" in HUB_SRC
    assert 'st.switch_page("views/wc_deep_dive.py")' in HUB_SRC
