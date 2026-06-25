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
    CONCEPTS,
    DAILY_LOOP,
    FAQ,
    GLOSSARY_GROUPS,
    GOOD_TO_KNOW,
    START_HERE_INTRO,
    TOUR,
    all_terms,
    edge_pp,
    filter_glossary,
    flat_stake,
    implied_pct_from_odds,
    kelly_fraction_of_bankroll,
    kelly_stake,
    term_count,
    tour_for_page,
    verdict_for_edge,
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


def test_edge_definition_matches_how_the_value_finder_flags():
    """The value finder flags on the RAW implied probability (1 ÷ odds, vig included);
    de-vig is only a deep-dive display refinement. The glossary must describe edge that
    way — not claim it's computed against a de-vigged price (the HC-03 correction)."""
    edge = next(d for (t, d) in all_terms() if t == "Edge").lower()
    assert "implied probability" in edge and "1 ÷" in edge   # raw 1/odds basis
    assert "de-vig" in edge                                   # noted as the deep-dive refinement


def test_start_here_orientation_is_present():
    assert len(START_HERE_INTRO) > 60
    assert len(DAILY_LOOP) >= 4 and all(len(s) == 2 for s in DAILY_LOOP)
    assert len(GOOD_TO_KNOW) >= 3 and all(len(n) == 2 for n in GOOD_TO_KNOW)


# ---------------------------------------------------------------------------
# 1b. screen tour (HC-02)
# ---------------------------------------------------------------------------

def test_tour_is_well_formed_and_covers_the_pages():
    pages = {e["page"] for e in TOUR}
    # every primary nav page + both deep dives has a card
    for must in ("Fixtures", "Today's Picks", "My Bets", "Performance Tracker",
                 "League Explorer", "World Cup", "Model Health", "Bankroll Manager",
                 "Settings", "Match Deep Dive", "WC Deep Dive"):
        assert must in pages, f"tour missing a card for {must}"
    for e in TOUR:
        assert e["icon"] and e["what"].strip()
        assert len(e["first"]) >= 2 and all(s.strip() for s in e["first"])
        for pair in e.get("decode", []):
            assert len(pair) == 2 and pair[0].strip() and pair[1].strip()


def test_tour_decode_explains_the_key_badges():
    """The decoder must cover the colour/badge vocabulary a newcomer trips on."""
    labels = " ".join(lbl for e in TOUR for (lbl, _) in e.get("decode", [])).lower()
    for token in ("ring", "verdict", "model badge", "pending", "trust"):
        assert token in labels, f"tour decoder never mentions “{token}”"


def test_tour_for_page_maps_real_pages_and_blanks_the_rest():
    assert tour_for_page("Fixtures")["page"] == "Fixtures"
    assert tour_for_page("WC Deep Dive")["icon"]
    # pages with no tour card (the Help page itself, owner-only Admin) → None
    for none_page in ("Help", "Admin", "", "Nonsense"):
        assert tour_for_page(none_page) is None


# ---------------------------------------------------------------------------
# 1c. FAQ (HC-03)
# ---------------------------------------------------------------------------

def test_faq_is_well_formed():
    assert len(FAQ) >= 5
    for q, a in FAQ:
        assert q.strip().endswith("?")
        assert len(a) >= 30
    blob = " ".join(q + " " + a for q, a in FAQ).lower()
    for topic in ("system pick", "edge", "no odds", "shadow"):
        assert topic in blob, f"FAQ never covers “{topic}”"


# ---------------------------------------------------------------------------
# 1d. Betting 101 concepts (HC-04)
# ---------------------------------------------------------------------------

def test_concepts_are_well_formed_with_worked_examples():
    assert len(CONCEPTS) >= 8
    for c in CONCEPTS:
        assert c["title"].strip()
        assert len(c["body"]) >= 40           # a real explanation
        assert len(c["example"]) >= 15        # and a worked example
    titles = " ".join(c["title"] for c in CONCEPTS).lower()
    for topic in ("edge", "clv", "variance", "bankroll", "calibration", "roi"):
        assert topic in titles, f"Betting 101 never teaches “{topic}”"


def test_edge_concept_uses_raw_implied_price_consistent_with_value_finder():
    """The value/edge lesson must match the code (edge = model − 1/odds), not de-vig —
    and its worked example must be arithmetically right (48% − 40% = +8%)."""
    edge_c = next(c for c in CONCEPTS if c["title"] == "Value and edge")
    assert "1 ÷ odds" in edge_c["body"] or "implied probability" in edge_c["body"]
    assert "48%" in edge_c["example"] and "40%" in edge_c["example"] and "+8%" in edge_c["example"]


# ---------------------------------------------------------------------------
# 1e. interactive-tool maths (HC-05) — exact arithmetic
# ---------------------------------------------------------------------------

def test_implied_pct_from_odds():
    assert implied_pct_from_odds(2.50) == 40.0
    assert implied_pct_from_odds(4.0) == 25.0
    assert implied_pct_from_odds(1.0) is None        # decimal odds must be > 1
    assert implied_pct_from_odds(0.5) is None
    assert implied_pct_from_odds("x") is None


def test_edge_pp_is_model_minus_raw_implied():
    assert round(edge_pp(48.0, 2.50), 6) == 8.0      # 48 − 40 (raw 1/odds, matches value_finder)
    assert round(edge_pp(40.0, 2.50), 6) == 0.0
    assert round(edge_pp(30.0, 2.50), 6) == -10.0
    assert edge_pp(50.0, 1.0) is None


def test_verdict_for_edge_uses_config_bounds():
    assert verdict_for_edge(8.0, 3.0, 15.0) == "value"
    assert verdict_for_edge(3.0, 3.0, 15.0) == "value"      # threshold inclusive
    assert verdict_for_edge(15.0, 3.0, 15.0) == "value"     # ceiling inclusive
    assert verdict_for_edge(2.9, 3.0, 15.0) == "none"
    assert verdict_for_edge(15.1, 3.0, 15.0) == "capped"
    assert verdict_for_edge(None, 3.0, 15.0) == "none"


def test_staking_helpers_exact():
    assert flat_stake(1000, 2) == 20.0
    assert flat_stake(1000, 0) == 0.0
    assert flat_stake(-5, 2) == 0.0
    assert flat_stake("x", 2) == 0.0
    # full-Kelly fraction f* = (p·odds − 1) / (odds − 1); 60% @ 2.0 → 0.2
    assert round(kelly_fraction_of_bankroll(60, 2.0), 6) == 0.2
    assert kelly_fraction_of_bankroll(40, 2.0) == 0.0       # no edge → floored at 0
    assert kelly_fraction_of_bankroll(50, 1.0) is None
    assert round(kelly_stake(1000, 60, 2.0, 0.25), 6) == 50.0   # 1000 × ¼ × 0.2
    assert kelly_stake(1000, 40, 2.0, 0.25) == 0.0


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

_PURE_FUNCS = {"_help_css", "_start_here_html", "_glossary_group_html", "_glossary_html",
               "_tour_card_html", "_tour_html", "_faq_html", "_concepts_html",
               "_value_result_html", "_stake_result_html", "_matrix_reader_html"}


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
    assert ".gloss-term" in css and ".help-step" in css and ".tour-card" in css


def test_view_renders_tour_cards_from_real_content():
    ns = _view_namespace()
    html = ns["_tour_html"](TOUR)
    assert "Fixtures" in html and "World Cup" in html
    assert "Look at first" in html and "Colours &amp; badges" in html
    # a real decoded badge + the page intro both land
    assert "value bet" in html.lower() and "verdict" in html.lower()


def test_view_tour_card_omits_decode_block_when_empty():
    ns = _view_namespace()
    card = ns["_tour_card_html"](
        {"icon": "⚙️", "page": "Settings", "what": "Your preferences.",
         "first": ["a", "b"], "decode": []}
    )
    assert "Look at first" in card and "Colours" not in card


def test_view_tour_escapes_hostile_fields():
    ns = _view_namespace()
    card = ns["_tour_card_html"](
        {"icon": "x", "page": "<b>P</b>", "what": "<i>w</i>",
         "first": ["<script>alert(1)</script>"],
         "decode": [("<img src=x onerror=1>", "<u>m</u>")]}
    )
    assert "<script>" not in card and "<img src=x" not in card and "<b>P" not in card
    assert "&lt;script&gt;" in card and "&lt;img" in card


def test_view_renders_faq_and_escapes():
    ns = _view_namespace()
    html = ns["_faq_html"](FAQ)
    assert "System Pick" in html and "?" in html        # a real Q/A rendered
    hostile = ns["_faq_html"]([("<script>q</script>", "<img src=x onerror=1>")])
    assert "<script>" not in hostile and "<img src=x" not in hostile
    assert "&lt;script&gt;" in hostile and "&lt;img" in hostile


def test_view_renders_concepts_and_escapes():
    ns = _view_namespace()
    html = ns["_concepts_html"](CONCEPTS)
    assert "Value and edge" in html and "Example." in html      # a card + the eg label
    assert "+8%" in html                                        # a worked number lands
    hostile = ns["_concepts_html"](
        [{"title": "<b>t</b>", "body": "<i>b</i>", "example": "<script>e</script>"}]
    )
    assert "<script>" not in hostile and "<b>t" not in hostile
    assert "&lt;script&gt;" in hostile and "&lt;b&gt;" in hostile


def test_view_renders_value_and_stake_tools():
    ns = _view_namespace()
    val = ns["_value_result_html"](2.50, 48.0, 40.0, 8.0, "value", 3.0, 15.0)
    assert "40.0%" in val and "+8.0 pp" in val and "VALUE" in val
    bad = ns["_value_result_html"](1.0, 50.0, None, None, "none", 3.0, 15.0)
    assert "Enter decimal odds" in bad
    stake = ns["_stake_result_html"](20.0, 50.0, 0.25)
    assert "$20.00" in stake and "$50.00" in stake and "25%" in stake


def test_view_matrix_reader_explains_the_markets():
    ns = _view_namespace()
    mx = ns["_matrix_reader_html"]()
    assert "home win" in mx.lower() and "draw" in mx.lower() and "away win" in mx.lower()
    assert "btts" in mx.lower()


# ---------------------------------------------------------------------------
# 3b. deep-link wiring (HC-03) — verified at source level (no Streamlit import)
# ---------------------------------------------------------------------------

def test_help_view_consumes_focus_and_has_faq_tab():
    src = HELP_VIEW.read_text()
    assert 'st.session_state.pop("help_focus_page"' in src   # focus consumed (and cleared)
    assert "tour_for_page(" in src                            # focus → that page's card
    assert "❓ FAQ" in src and "_faq_html(FAQ)" in src


def test_dashboard_wires_per_page_help_link():
    dash = (Path(__file__).resolve().parents[1] / "src" / "delivery" / "dashboard.py").read_text()
    assert "def render_help_link(" in dash
    assert 'st.session_state["help_focus_page"]' in dash      # link sets the focus
    assert 'st.switch_page("views/help.py")' in dash          # … and jumps to Help
    assert "render_help_link(" in dash                        # actually called in main()


def test_view_escapes_hostile_term_and_definition():
    ns = _view_namespace()
    html = ns["_glossary_group_html"](
        "Grp", "blurb",
        [("<img src=x onerror=alert(1)>", "<script>alert(2)</script>")],
    )
    assert "<img src=x" not in html and "<script>" not in html
    assert "&lt;img" in html and "&lt;script&gt;" in html
