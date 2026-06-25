"""DH-03 — Data Health dashboard page.

The page runs ``st.*`` at import (Streamlit convention), so its pure HTML helpers are
exercised via AST-exec over a sample report dict (the same dict shape ``report_to_dict``
produces). Plus source-level checks that the page is wired to the read-only engine and
registered in the nav.
"""

from __future__ import annotations

import ast
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "src" / "delivery" / "views" / "data_health.py"
DASH = ROOT / "src" / "delivery" / "dashboard.py"

_PURE = {"_status_meta", "_dh_css", "_check_row_html", "_group_section_html",
         "_overall_banner_html"}

SAMPLE = {
    "generated_at": "2026-06-24T12:00:00", "backend": "postgresql", "overall": "warn",
    "summary": {"ok": 9, "warn": 2, "fail": 0, "skip": 6},
    "checks": [
        {"group": "Connectivity", "name": "Database reachable", "status": "ok",
         "detail": "SELECT 1 succeeded."},
        {"group": "Standings integrity", "name": "Stale scheduled stubs (leagues)",
         "status": "warn", "detail": "2 past-dated fixtures still scheduled.", "value": 2},
    ],
}


def _ns():
    ns = {"escape": escape}
    for node in ast.parse(VIEW.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in _PURE:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<dh>", "exec"), ns)
    return ns


def test_status_meta_maps_each_status_to_design_colours():
    ns = _ns()
    assert ns["_status_meta"]("ok")[0] == "#3FB950"
    assert ns["_status_meta"]("warn")[0] == "#D29922"
    assert ns["_status_meta"]("fail")[0] == "#F85149"
    assert ns["_status_meta"]("skip")[0] == "#8B949E"


def test_check_row_shows_pill_name_and_detail():
    ns = _ns()
    html = ns["_check_row_html"](SAMPLE["checks"][1])
    assert "WARN" in html and "#D29922" in html
    assert "Stale scheduled stubs (leagues)" in html
    assert "2 past-dated fixtures still scheduled." in html


def test_group_section_has_title_and_rows():
    ns = _ns()
    html = ns["_group_section_html"]("Standings integrity", [SAMPLE["checks"][1]])
    assert "Standings integrity" in html and "dh-group-title" in html
    assert "Stale scheduled stubs" in html


def test_overall_banner_headline_and_counts():
    ns = _ns()
    html = ns["_overall_banner_html"]("warn", SAMPLE["summary"], "postgresql",
                                      "2026-06-24T12:00:00")
    assert "Needs attention" in html and "#D29922" in html
    assert "9 OK" in html and "2 warn" in html and "backend postgresql" in html
    # the healthy + failing headlines too
    assert "All systems healthy" in ns["_overall_banner_html"](
        "ok", SAMPLE["summary"], "postgresql", "x")
    assert "Problems detected" in ns["_overall_banner_html"](
        "fail", SAMPLE["summary"], "postgresql", "x")


def test_helpers_escape_hostile_text():
    ns = _ns()
    hostile = {"name": "<img src=x onerror=alert(1)>", "status": "warn",
               "detail": "<script>alert(2)</script>"}
    html = ns["_check_row_html"](hostile)
    assert "<img src=x" not in html and "<script>" not in html
    assert "&lt;img" in html and "&lt;script&gt;" in html


def test_css_defines_the_page_classes():
    ns = _ns()
    css = ns["_dh_css"]()
    for cls in (".dh-banner", ".dh-group-title", ".dh-row", ".dh-pill", ".dh-detail"):
        assert cls in css


# --- source-level wiring -----------------------------------------------------

def test_page_is_registered_in_nav():
    dash = DASH.read_text()
    assert '"views/data_health.py"' in dash
    assert 'title="Data Health"' in dash


def test_view_runs_the_readonly_engine_with_cache_and_refresh():
    src = VIEW.read_text()
    assert "from src.monitoring.health_check import run_health_checks" in src
    assert "report_to_dict(run_health_checks())" in src   # read-only engine → dict
    assert "st.cache_data" in src                          # cached
    assert "_load_report.clear()" in src and "st.rerun()" in src  # manual refresh
    assert "_render_report(" in src
    # read-only: the page must not write to the DB
    for forbidden in ("session.add", "session.commit", "session.delete", "INSERT",
                      "UPDATE ", "init_db("):
        assert forbidden not in src, f"data health page must be read-only ({forbidden})"
