"""
WC-10-02 — daily morning automation.

Covers the email-folding (yesterday's results folded into the morning digest, the
owner's option 1) and a guard that the morning pipeline keeps the CLV-capture +
accuracy steps it absorbed from the retired evening run.
"""

import ast
from datetime import date, timedelta
from pathlib import Path

from src.world_cup.alerts import (
    _previous_date, _render_results_section, _render_morning_html,
)


def _finished(home, away, hg, ag, ph, pd, pa):
    return {"home": home, "away": away, "home_goals": hg, "away_goals": ag,
            "pred_h": ph, "pred_d": pd, "pred_a": pa, "kickoff": "1:00 PM ET",
            "group": "A", "venue": "X", "pred_score": "2-0", "status": "finished"}


def test_previous_date():
    assert _previous_date("2026-06-24") == "2026-06-23"
    assert _previous_date(None) == (date.today() - timedelta(days=1)).isoformat()


def test_results_section_renders_scores_and_marks():
    finished = [
        _finished("Brazil", "Scotland", 2, 0, 0.7, 0.2, 0.1),   # home win, pred home → ✓
        _finished("Spain", "Uruguay", 0, 1, 0.6, 0.25, 0.15),   # away win, pred home → ✗
    ]
    html = _render_results_section(finished, "Yesterday's Results (1/2 correct)")
    assert "Results (1/2 correct)" in html   # apostrophe is HTML-escaped in the title
    assert "Brazil" in html and "2-0" in html
    assert "Spain" in html and "0-1" in html
    assert "&#10003;" in html   # ✓ for the correct pick
    assert "&#10007;" in html   # ✗ for the wrong pick


def test_results_section_empty_when_nothing_to_show():
    assert _render_results_section([], "Yesterday's Results") == ""
    nogoals = [{"home": "A", "away": "B", "home_goals": None, "away_goals": None, "pred_h": 0.5}]
    assert _render_results_section(nogoals, "T") == ""   # finished but unscored → skipped


def test_morning_html_includes_results_when_provided():
    recent = [_finished("Brazil", "Scotland", 2, 0, 0.7, 0.2, 0.1)]
    html = _render_morning_html([], [], {}, 5, recent, 1, 1)
    assert "Results (1/1 correct)" in html   # apostrophe is HTML-escaped in the title
    assert "Brazil" in html and "2-0" in html


def test_morning_html_omits_results_when_none():
    html = _render_morning_html([], [], {}, 5)   # no recent_results → no section
    # "correct)" is the results-section's escape-proof structural marker (the title
    # count suffix); a leaked section would contain it, so this catches a regression.
    assert "correct)" not in html


def test_morning_pipeline_keeps_clv_and_accuracy_steps():
    """Guard: the morning run must retain the steps it absorbed from the evening run."""
    src = Path("src/world_cup/pipeline.py").read_text()
    tree = ast.parse(src)
    morning = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_run_morning")
    body = ast.get_source_segment(src, morning)
    assert "capture_wc_closing_lines" in body   # CLV settlement on overnight finishes
    assert "compute_model_accuracy" in body     # daily metrics refresh
