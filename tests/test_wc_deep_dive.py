"""DF-08 — WC deep-dive view structural integration test.

The deep-dive page module resolves the match id and renders at import time
(same pattern as match_detail.py / world_cup.py), so we verify its structure via
AST rather than executing it. The pure data layer it draws — model-vs-every-book
(``build_book_comparison``) and the 7x7 matrix (``scoreline_matrix_from_lambdas``)
— is unit-tested with real data in test_wc_research.py. Here we confirm the view
is wired: the section renderers exist, the match id is resolved from session_state
+ query param, the heatmap and model-vs-books sections are present, dynamic HTML
is escaped, empty states are handled, and the WC hub + nav route into this page.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "src" / "delivery" / "views"

DD = VIEWS / "wc_deep_dive.py"
DD_SRC = DD.read_text()
DD_TREE = ast.parse(DD_SRC)
DD_FUNCS = {n.name for n in ast.walk(DD_TREE) if isinstance(n, ast.FunctionDef)}
DD_IMPORTS = {
    alias.name
    for n in ast.walk(DD_TREE) if isinstance(n, ast.ImportFrom)
    for alias in n.names
}

HUB_SRC = (VIEWS / "world_cup.py").read_text()
DASH_SRC = (ROOT / "src" / "delivery" / "dashboard.py").read_text()


class TestDeepDiveStructure:
    def test_page_parses(self):
        assert DD_TREE is not None

    def test_section_renderers_present(self):
        expected = {
            "_render_header", "_render_heatmap", "_scoreline_heatmap",
            "_render_model_vs_books", "_market_table_html", "_book_cell_html",
            "_render_picker", "_render_deep_dive",
        }
        assert expected <= DD_FUNCS, f"missing: {expected - DD_FUNCS}"

    def test_data_layer_imported(self):
        # The view draws the unit-tested pure layer, not its own model math.
        assert "build_book_comparison" in DD_IMPORTS
        assert "scoreline_matrix_from_lambdas" in DD_IMPORTS

    def test_wc_helpers_imported(self):
        assert "render_flag" in DD_IMPORTS          # flags in the header
        assert "format_kickoff_et" in DD_IMPORTS    # ET kickoff


class TestMatchResolution:
    def test_resolves_from_session_state(self):
        # Set by the WC hub on switch_page; popped (one-shot) here.
        assert "wc_deep_dive_match_id" in DD_SRC
        assert ".pop(" in DD_SRC

    def test_resolves_from_query_param(self):
        # URL share / refresh fallback, synced for shareability.
        assert "wc_match_id" in DD_SRC
        assert "st.query_params" in DD_SRC


class TestHeatmap:
    def test_renders_7x7_matrix(self):
        src = _func_src(DD_TREE, DD_SRC, "_render_heatmap")
        assert "scoreline_matrix_from_lambdas(" in src
        assert "st.plotly_chart(" in src

    def test_empty_state_when_no_prediction(self):
        # Missing-data state handled, not a crash.
        assert "st.info(" in _func_src(DD_TREE, DD_SRC, "_render_heatmap")


class TestModelVsEveryBook:
    def test_iterates_every_book(self):
        # The market table loops over all pulled books, not a single preferred one.
        src = _func_src(DD_TREE, DD_SRC, "_market_table_html")
        assert 'market["books"]' in src
        assert "n_books" in src

    def test_model_and_consensus_rows(self):
        src = _func_src(DD_TREE, DD_SRC, "_market_table_html")
        assert "Model" in src and "consensus" in src

    def test_empty_state_when_no_odds(self):
        assert "st.info(" in _func_src(DD_TREE, DD_SRC, "_render_model_vs_books")

    def test_dynamic_html_escaped(self):
        # Team + book names flow into HTML — they must be escaped.
        assert 'escape(b["book"])' in _func_src(DD_TREE, DD_SRC, "_market_table_html")
        assert "escape(" in _func_src(DD_TREE, DD_SRC, "_render_header")


class TestEntryWiring:
    def test_hub_switches_into_deep_dive(self):
        # Both the fixtures strip and the research card route here.
        assert 'st.switch_page("views/wc_deep_dive.py")' in HUB_SRC
        assert HUB_SRC.count('st.session_state["wc_deep_dive_match_id"]') >= 2

    def test_back_returns_to_hub(self):
        assert 'st.switch_page("views/world_cup.py")' in DD_SRC

    def test_page_registered_in_nav(self):
        assert '"views/wc_deep_dive.py"' in DASH_SRC


def _func_src(tree: ast.AST, source: str, name: str) -> str:
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(source, node) or ""
