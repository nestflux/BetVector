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

_PURE = {"_result_outcome", "_model_pick", "_pick_conf", "_short_date", "_result_row_html"}


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
