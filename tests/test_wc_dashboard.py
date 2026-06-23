"""WC-08-07 — World Cup dashboard structural integration test.

The page module runs main() at import time (heavy DB + cached 10K simulation),
so we verify its structure via AST rather than executing it. This confirms the
4-tab redesign stays wired correctly: the tabs exist, every section render
function is present, the third-place split landed, and the flag / Eastern-time
/ canonical-selection helpers are imported. Visual + responsive rendering is
verified via the preview harness; the flag and ET helpers have their own unit
tests (test_wc_flags / test_wc_timeutil).
"""

import ast
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "src" / "delivery" / "views" / "world_cup.py"
SOURCE = PAGE.read_text()
TREE = ast.parse(SOURCE)

FUNCS = {n.name for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)}
IMPORTED = {
    alias.name
    for n in ast.walk(TREE) if isinstance(n, ast.ImportFrom)
    for alias in n.names
}


def _func_source(name: str) -> str:
    node = next(n for n in ast.walk(TREE)
                if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SOURCE, node) or ""


class TestPageStructure:
    def test_page_parses(self):
        assert TREE is not None  # ast.parse already succeeded at import

    def test_all_section_renderers_present(self):
        expected = {
            "_render_todays_matches", "_render_value_bets",
            "_render_group_standings", "_render_group_advancement",
            "_render_third_place", "_render_knockout_bracket",
            "_render_winner_chart", "_render_model_performance", "main",
        }
        assert expected <= FUNCS, f"missing renderers: {expected - FUNCS}"

    def test_tab1_helpers_present(self):
        assert {"_model_lean_html", "_best_price_html",
                "_flag_for_name", "_team_fifa_map"} <= FUNCS


class TestFourTabs:
    def test_st_tabs_called(self):
        assert "st.tabs(" in SOURCE

    def test_four_tab_labels(self):
        for label in ("Today & Bets", "Groups", "Knockouts", "Model"):
            assert label in SOURCE, f"tab label missing: {label}"


class TestIntegrationWiring:
    def test_flag_helper_imported(self):
        assert "render_flag" in IMPORTED

    def test_eastern_time_imported(self):
        assert "format_kickoff_et" in IMPORTED
        assert "eastern_date" in IMPORTED

    def test_canonical_selection_imported(self):
        assert "_canonical_selection" in IMPORTED


class TestNoN1Queries:
    def test_fixtures_strip_bulk_loads(self):
        # Tab 1 upcoming-fixtures query must eager-load relations (no N+1).
        assert "joinedload" in _func_source("_render_todays_matches")

    def test_value_bets_bulk_loads(self):
        assert "joinedload" in _func_source("_render_value_bets")


class TestCollapsibleGroups:
    def test_groups_use_expanders(self):
        # Tab 2 wraps standings / advancement / third-place in expanders.
        main_src = _func_source("main")
        assert main_src.count("st.expander(") >= 3
