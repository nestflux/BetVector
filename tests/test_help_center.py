"""HC-01 — Help Center spine + consolidated searchable master glossary.

Three layers:
  1. Content integrity (help_content.py — pure, importable): the glossary is a
     well-formed single source of truth (5 groups, every term unique, every
     definition substantive) and the Start-here orientation is present.
  2. The pure search filter (help_content.filter_glossary): blank → everything;
     a query filters by term OR definition, case-insensitively; empty groups drop;
     no match → [].
  3. data → render: AST-exec the view's pure HTML helpers over the real content and
     prove the glossary + orientation render, the empty state is graceful, and a
     hostile term/definition is escaped.

The Help page is read-only and content-driven — no DB, no model, no bet logic.
"""

import ast
from html import escape
from pathlib import Path

from src.delivery import help_content
from src.delivery.help_content import (
    DAILY_LOOP,
    GLOSSARY_GROUPS,
    GOOD_TO_KNOW,
    START_HERE_INTRO,
    all_terms,
    filter_glossary,
    term_count,
)

HELP_VIEW = (
    Path(__file__).resolve().parents[1] / "src" / "delivery" / "views" / "help.py"
)

_EXPECTED_GROUPS = [
    "Betting basics", "Markets", "The model", "Performance & bankroll", "World Cup",
]


# ---------------------------------------------------------------------------
# 1. content integrity
# ---------------------------------------------------------------------------

def test_glossary_groups_are_well_formed():
    assert [g["group"] for g in GLOSSARY_GROUPS] == _EXPECTED_GROUPS
    for g in GLOSSARY_GROUPS:
        assert g["blurb"].strip()                       # every group explains itself
        assert g["terms"], f"{g['group']} has no terms"
        for term, defn in g["terms"]:
            assert term.strip()
            assert len(defn) >= 20                       # a real definition, not a stub


def test_every_term_is_unique_single_source_of_truth():
    """The whole point of the consolidation: each term is defined exactly once, so the
    page (and later the doc + page glossaries) can't drift."""
    terms = [t for (t, _) in all_terms()]
    dupes = sorted({t for t in terms if terms.count(t) > 1})
    assert not dupes, f"duplicate glossary terms: {dupes}"
    assert term_count() == len(terms) == len(set(terms))


def test_core_consolidated_terms_are_present():
    """Spot-check the terms that mattered in the drift report + the ones authored
    fresh (no page had ever defined them)."""
    terms = {t for (t, _) in all_terms()}
    for must in ("Value bet", "Edge", "CLV (Closing-Line Value)", "Overround (vig / margin)",
                 "De-vig", "Scoreline matrix", "Brier score", "Calibration",
                 "Kelly Criterion", "Drawdown", "Squad value", "Trust tiers (🟢 🟡 🔴)"):
        assert must in terms, f"missing canonical term: {must}"


def test_squad_value_reconciles_the_threshold_drift():
    """Drift resolution: picks fired the badge at ~2×, match_detail's prose said
    '>1.5× is significant'. The canonical line keeps both honestly."""
    sv = next(d for (t, d) in all_terms() if t == "Squad value")
    assert "1.5" in sv and "2" in sv


def test_edge_definition_kept_the_devig_precision():
    """Drift resolution: Edge adopts the de-vigged-probability wording (the most
    correct of the three page versions), not the looser 'implied probability' one."""
    edge = next(d for (t, d) in all_terms() if t == "Edge")
    assert "de-vig" in edge.lower()


def test_start_here_orientation_is_present():
    assert len(START_HERE_INTRO) > 60
    assert len(DAILY_LOOP) >= 4 and all(len(s) == 2 for s in DAILY_LOOP)
    assert len(GOOD_TO_KNOW) >= 3 and all(len(n) == 2 for n in GOOD_TO_KNOW)


# ---------------------------------------------------------------------------
# 2. the pure search filter
# ---------------------------------------------------------------------------

def test_blank_query_returns_everything():
    assert filter_glossary("") is GLOSSARY_GROUPS
    assert filter_glossary("   ") is GLOSSARY_GROUPS
    assert filter_glossary(None) is GLOSSARY_GROUPS


def test_query_filters_by_term_case_insensitive():
    groups = filter_glossary("EDGE")
    hits = {t for g in groups for (t, _) in g["terms"]}
    assert "Edge" in hits and "Edge threshold" in hits and "Capped edge" in hits
    # unrelated terms are gone
    assert "Drawdown" not in hits


def test_query_matches_definition_text_not_just_terms():
    """'diagonal' appears only inside the Calibration definition, never as a term —
    so a definition-only hit proves we search the body too."""
    groups = filter_glossary("diagonal")
    found = {t for g in groups for (t, _) in g["terms"]}
    assert "Calibration" in found
    assert all(t == "Calibration" for g in groups for (t, _) in g["terms"])


def test_no_match_returns_empty_and_drops_empty_groups():
    assert filter_glossary("zzzqqq-not-a-term") == []
    # a real but narrow query keeps only the groups that actually matched
    groups = filter_glossary("bankroll")
    assert groups and all(g["terms"] for g in groups)
    assert {g["group"] for g in groups} <= set(_EXPECTED_GROUPS)


def test_filter_preserves_group_shape():
    g = filter_glossary("kelly")[0]
    assert set(g.keys()) == {"group", "blurb", "terms"}


# ---------------------------------------------------------------------------
# 3. data -> render: AST-exec the view's pure HTML helpers
# ---------------------------------------------------------------------------

_PURE_FUNCS = {"_help_css", "_start_here_html", "_glossary_group_html", "_glossary_html"}


def _view_namespace():
    """Exec the Help view's pure helpers without importing the module (it runs st.*
    at import). Inject the help_content constants the helpers close over."""
    tree = ast.parse(HELP_VIEW.read_text())
    ns = {
        "escape": escape,
        "START_HERE_INTRO": START_HERE_INTRO,
        "DAILY_LOOP": DAILY_LOOP,
        "GOOD_TO_KNOW": GOOD_TO_KNOW,
    }
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _PURE_FUNCS:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<help>", "exec"), ns)
    return ns


def test_view_renders_full_glossary_from_real_content():
    ns = _view_namespace()
    html = ns["_glossary_html"](GLOSSARY_GROUPS)
    for group in _EXPECTED_GROUPS:
        assert escape(group) in html                   # titles are escaped (e.g. & → &amp;)
    assert "Value bet" in html and "Closing-Line Value" in html   # a term
    assert "too generous" in html                                  # a definition body


def test_view_glossary_empty_state_is_graceful():
    ns = _view_namespace()
    html = ns["_glossary_html"]([])
    assert "No terms match" in html


def test_view_renders_start_here_orientation():
    ns = _view_namespace()
    html = ns["_start_here_html"]()
    assert "Your daily loop" in html and "Good to know" in html
    assert escape(DAILY_LOOP[0][0]) in html                        # first step label
    assert escape(GOOD_TO_KNOW[0][0]) in html                      # first note title


def test_help_page_is_registered_in_nav():
    """The ❓ Help page is wired into the sidebar (dashboard.get_pages); checked at the
    source level so we don't import Streamlit/auth just to assert a registration."""
    dash = (Path(__file__).resolve().parents[1] / "src" / "delivery" / "dashboard.py").read_text()
    assert '"views/help.py"' in dash and 'title="Help"' in dash


def test_view_help_css_is_a_style_block():
    ns = _view_namespace()
    css = ns["_help_css"]()
    assert css.startswith("<style>") and css.endswith("</style>")
    assert ".gloss-term" in css and ".help-step" in css


def test_view_escapes_hostile_term_and_definition():
    ns = _view_namespace()
    html = ns["_glossary_group_html"](
        "Grp", "blurb",
        [("<img src=x onerror=alert(1)>", "<script>alert(2)</script>")],
    )
    assert "<img src=x" not in html and "<script>" not in html
    assert "&lt;img" in html and "&lt;script&gt;" in html
