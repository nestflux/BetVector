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


# ---------------------------------------------------------------------------
# 4. HC-06 — per-page glossaries (single source) + downloadable manual
# ---------------------------------------------------------------------------

_ALLOWED_GLOSS_COLOURS = {"#3FB950", "#D29922", "#F85149", "#8B949E"}

# (view file, the PAGE_GLOSSARIES key it now renders from)
_MIGRATED_VIEWS = [
    ("picks.py", "Today's Picks"),
    ("performance.py", "Performance Tracker"),
    ("bankroll.py", "Bankroll Manager"),
    ("match_detail.py", "Match Deep Dive"),
    ("wc_deep_dive.py", "WC Deep Dive"),
]


def _page_rows(page_key):
    """Flat list of every row across a page's glossary sections."""
    return [row for _title, rows in help_content.PAGE_GLOSSARIES[page_key] for row in rows]


def _page_def(page_key, label):
    """The definition rendered for a given term label on a page (or None)."""
    for term, defn, *_rest in _page_rows(page_key):
        if term == label:
            return defn
    return None


def test_glossary_by_term_covers_every_master_term():
    # The lookup is exactly the master glossary, keyed by term — nothing added, nothing lost.
    assert len(help_content.GLOSSARY_BY_TERM) == term_count()
    for term, defn in all_terms():
        assert help_content.GLOSSARY_BY_TERM[term] == defn
    # glossary_def() is the same lookup and raises on an unknown term (so page typos fail).
    assert help_content.glossary_def("Edge") == help_content.GLOSSARY_BY_TERM["Edge"]
    try:
        help_content.glossary_def("not-a-real-term")
        assert False, "glossary_def should KeyError on an unknown term"
    except KeyError:
        pass


def test_page_glossaries_are_well_formed():
    assert set(help_content.PAGE_GLOSSARY_KEYS) == {k for _f, k in _MIGRATED_VIEWS}
    for key in help_content.PAGE_GLOSSARY_KEYS:
        sections = help_content.PAGE_GLOSSARIES[key]
        assert sections, f"{key}: no sections"
        for title, rows in sections:
            assert title is None or (isinstance(title, str) and title.strip())
            assert rows, f"{key}: empty section {title!r}"
            for row in rows:
                assert len(row) in (2, 3), f"{key}: bad row {row!r}"
                label, defn = row[0], row[1]
                assert label.strip() and len(defn) > 15, f"{key}: thin row {label!r}"
                if len(row) == 3:
                    assert row[2] in _ALLOWED_GLOSS_COLOURS, f"{key}: bad colour {row[2]}"


def test_page_glossaries_pull_shared_definitions_from_the_master():
    # Shared betting concepts are written once: the page row reuses the master definition
    # verbatim (this is what stops the page glossaries drifting from the Help page).
    cases = [
        ("Today's Picks", "Edge", "Edge"),
        ("Today's Picks", "Odds", "Odds (decimal)"),
        ("Performance Tracker", "Total P&L", "P&L (Profit and Loss)"),
        ("Bankroll Manager", "Drawdown", "Drawdown"),
        ("Bankroll Manager", "Flat Staking", "Flat staking"),
        ("Match Deep Dive", "xG", "xG (Expected Goals)"),
        ("Match Deep Dive", "Confidence", "Confidence"),
        ("WC Deep Dive", "CLV", "CLV (Closing-Line Value)"),
    ]
    for page_key, label, master_term in cases:
        assert _page_def(page_key, label) == help_content.GLOSSARY_BY_TERM[master_term], (
            f"{page_key}:{label} should reuse the master '{master_term}' definition")


def test_migration_propagates_the_hc04_fixes_to_the_page_glossaries():
    # HC-04 corrected the master source; migrating must carry those fixes onto the pages.
    bank = help_content.glossary_sections_html("Bankroll Manager")
    assert "25%" in bank and "30%" not in bank          # drawdown alert is 25%, not 30%
    flat = _page_def("Bankroll Manager", "Flat Staking")
    assert "current-bankroll" in flat                   # flat reads CURRENT bankroll …
    assert "starting bankroll" not in flat.lower()      # … not the starting bankroll


def test_glossary_sections_html_renders_escaped_for_every_page():
    for _file, key in _MIGRATED_VIEWS:
        html = help_content.glossary_sections_html(key)
        assert html and html.count('class="gloss-row"') == len(_page_rows(key))
    # Unknown page → empty (graceful), never an error.
    assert help_content.glossary_sections_html("Nope") == ""
    # Ampersands in labels/titles are HTML-escaped (no raw, unescaped markup).
    picks = help_content.glossary_sections_html("Today's Picks")
    assert "Filters &amp; Controls" in picks and "Filters & Controls" not in picks
    perf = help_content.glossary_sections_html("Performance Tracker")
    assert "Total P&amp;L" in perf
    # Tinted tier labels carry an inline colour from the allowed design tokens.
    assert 'style="color: #3FB950;"' in picks            # HIGH confidence is green


def test_build_manual_markdown_has_every_section_and_no_html():
    md = help_content.build_manual_markdown()
    for heading in ("# BetVector — User Manual", "## Start here", "## Screen tour",
                    "## Betting 101", "## FAQ", "## Glossary"):
        assert heading in md, f"missing heading: {heading}"
    assert "### 🎯 Today's Picks" in md                  # a tour card
    assert "**Value bet**" in md                          # a glossary term
    assert "> **Example.**" in md                         # a Betting 101 worked example
    assert FAQ[0][0] in md                                # a verbatim FAQ question
    assert DAILY_LOOP[0][0] in md                         # a daily-loop step label
    # It is Markdown, not HTML — no view markup leaks into the document.
    for leak in ("<span", "</div>", "unsafe_allow_html", "<script", "&amp;"):
        assert leak not in md, f"HTML leaked into the manual: {leak}"


def test_build_manual_markdown_is_complete():
    # Every master glossary term appears in the downloadable manual.
    md = help_content.build_manual_markdown()
    for term, _defn in all_terms():
        assert f"**{term}**" in md, f"manual missing glossary term: {term}"


def test_build_manual_html_is_an_escaped_document():
    html = help_content.build_manual_html()
    assert html.startswith("<!DOCTYPE html>") and html.rstrip().endswith("</body></html>")
    assert "<h1>BetVector — User Manual</h1>" in html and "<h2>Glossary</h2>" in html
    assert "Performance &amp; bankroll" in html          # group name escaped in the HTML
    assert "<dt>Value bet</dt>" in html                  # a glossary term as a definition
    for leak in ("unsafe_allow_html", "<script"):
        assert leak not in html


def test_every_migrated_view_renders_from_the_shared_source():
    views_dir = Path(__file__).resolve().parents[1] / "src" / "delivery" / "views"
    for file_name, key in _MIGRATED_VIEWS:
        src = (views_dir / file_name).read_text()
        assert "from src.delivery.help_content import glossary_sections_html" in src, file_name
        assert f'glossary_sections_html("{key}")' in src, file_name
        # the old inline definitions are gone (no duplicate term source on the page)
        assert 'gloss-title">The Pick Card' not in src
        assert 'gloss-title">Bankroll Basics' not in src
        assert 'gloss-title">Form &amp; Performance' not in src
    # the specific HC-04 wrong wording no longer lives in the bankroll view source
    bank_src = (views_dir / "bankroll.py").read_text()
    assert "above 30% triggers" not in bank_src
    assert "starting bankroll, regardless" not in bank_src
