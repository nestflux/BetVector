"""
BetVector — Help & Manual (HC-01)
==================================
The in-app guide: one place to answer “what am I looking at?” and “what does this
word mean?”. Read-only and content-driven — every word comes from the single
source of truth in ``src/delivery/help_content.py`` (so the page, the existing
page-level glossaries, and the future downloadable manual never drift apart).

Sections (this page grows over the HC epic):
- **Start here** — a two-minute orientation: what BetVector does, the daily loop,
  and what “shadow / decision-support” means.
- **Glossary** — one searchable master list of every term, badge and colour,
  grouped (Betting basics / Markets / The model / Performance & bankroll / World
  Cup), consolidating the five glossaries that used to live on separate pages.

Coming in later HC issues: a screen-by-screen tour (HC-02), an FAQ + on-page
“How to read this page” links (HC-03), Betting 101 with worked examples (HC-04),
and interactive tools (HC-05). The page is laid out in tabs so those slot in.

Pure HTML helpers are kept module-level and Streamlit-free so they can be
AST-tested; the ``st.*`` calls run at import (Streamlit page convention).
"""

from html import escape

import streamlit as st

from src.delivery.help_content import (
    CONCEPTS,
    DAILY_LOOP,
    FAQ,
    GOOD_TO_KNOW,
    START_HERE_INTRO,
    TOUR,
    build_manual_html,
    build_manual_markdown,
    edge_pp,
    filter_glossary,
    flat_stake,
    implied_pct_from_odds,
    kelly_stake,
    term_count,
    tour_for_page,
    verdict_for_edge,
)


# ============================================================================
# Pure HTML helpers (Streamlit-free → AST-testable; all dynamic text escaped)
# ============================================================================

def _help_css() -> str:
    """Scoped styles for the Help page. Mirrors the ``.gloss-*`` classes the
    existing page glossaries use (so the look is identical), plus a few ``.help-*``
    classes for the Start-here orientation."""
    return (
        "<style>"
        ".gloss-section{margin-bottom:20px;}"
        ".gloss-title{font-family:Inter,sans-serif;font-size:14px;font-weight:700;"
        "color:#3FB950;text-transform:uppercase;letter-spacing:0.5px;"
        "margin-bottom:4px;border-bottom:1px solid #21262D;padding-bottom:4px;}"
        ".gloss-blurb{font-family:Inter,sans-serif;font-size:12px;color:#8B949E;"
        "margin:0 0 10px;}"
        ".gloss-row{display:flex;gap:12px;margin-bottom:8px;line-height:1.5;}"
        ".gloss-term{font-family:'JetBrains Mono',monospace;font-size:12px;"
        "font-weight:600;color:#E6EDF3;min-width:175px;flex-shrink:0;}"
        ".gloss-def{font-family:Inter,sans-serif;font-size:13px;color:#8B949E;}"
        ".help-intro{font-family:Inter,sans-serif;font-size:15px;color:#E6EDF3;"
        "line-height:1.6;margin-bottom:6px;}"
        ".help-h{font-family:Inter,sans-serif;font-size:14px;font-weight:700;"
        "color:#3FB950;text-transform:uppercase;letter-spacing:0.5px;"
        "margin:20px 0 12px;}"
        ".help-step{display:flex;gap:12px;margin-bottom:12px;align-items:flex-start;}"
        ".help-num{flex-shrink:0;width:24px;height:24px;border-radius:50%;"
        "background:#161B22;border:1px solid #30363D;color:#3FB950;"
        "font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;"
        "display:flex;align-items:center;justify-content:center;}"
        ".help-step-body{font-family:Inter,sans-serif;font-size:14px;color:#8B949E;"
        "line-height:1.5;}"
        ".help-step-label{color:#E6EDF3;font-weight:600;}"
        ".help-note{background:#161B22;border:1px solid #30363D;border-radius:8px;"
        "padding:10px 14px;margin-bottom:10px;}"
        ".help-note-title{font-family:Inter,sans-serif;font-size:13px;font-weight:600;"
        "color:#E6EDF3;margin-bottom:2px;}"
        ".help-note-body{font-family:Inter,sans-serif;font-size:13px;color:#8B949E;"
        "line-height:1.5;}"
        ".tour-card{background:#161B22;border:1px solid #30363D;border-radius:8px;"
        "padding:14px 16px;margin-bottom:14px;}"
        ".tour-head{font-family:Inter,sans-serif;font-size:15px;font-weight:700;"
        "color:#E6EDF3;margin-bottom:4px;}"
        ".tour-icon{margin-right:8px;}"
        ".tour-what{font-family:Inter,sans-serif;font-size:13px;color:#8B949E;"
        "line-height:1.5;margin-bottom:6px;}"
        ".tour-sub{font-family:Inter,sans-serif;font-size:11px;font-weight:700;"
        "color:#3FB950;text-transform:uppercase;letter-spacing:0.5px;margin:12px 0 6px;}"
        ".tour-first{margin:0;padding-left:18px;}"
        ".tour-first li{font-family:Inter,sans-serif;font-size:13px;color:#E6EDF3;"
        "line-height:1.5;margin-bottom:4px;}"
        ".faq-item{border-bottom:1px solid #21262D;padding:12px 0;}"
        ".faq-q{font-family:Inter,sans-serif;font-size:14px;font-weight:600;"
        "color:#E6EDF3;margin-bottom:4px;}"
        ".faq-a{font-family:Inter,sans-serif;font-size:13px;color:#8B949E;"
        "line-height:1.55;}"
        ".help-focus-head{font-family:Inter,sans-serif;font-size:12px;font-weight:700;"
        "color:#3FB950;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;}"
        ".concept{background:#161B22;border:1px solid #30363D;border-radius:8px;"
        "padding:12px 16px;margin-bottom:12px;}"
        ".concept-title{font-family:Inter,sans-serif;font-size:15px;font-weight:700;"
        "color:#E6EDF3;margin-bottom:6px;}"
        ".concept-body{font-family:Inter,sans-serif;font-size:13px;color:#8B949E;"
        "line-height:1.55;margin-bottom:8px;}"
        ".concept-eg{background:#0D1117;border-left:2px solid #3FB950;border-radius:4px;"
        "padding:8px 12px;font-family:Inter,sans-serif;font-size:12.5px;color:#E6EDF3;"
        "line-height:1.5;}"
        ".concept-eg b{color:#3FB950;font-weight:600;}"
        ".tool-h{font-family:Inter,sans-serif;font-size:13px;font-weight:700;color:#3FB950;"
        "text-transform:uppercase;letter-spacing:0.5px;margin:16px 0 8px;}"
        ".help-dl-head{font-family:Inter,sans-serif;font-size:15px;font-weight:700;"
        "color:#E6EDF3;margin:6px 0 4px;}"
        ".tool-out{background:#161B22;border:1px solid #30363D;border-radius:8px;"
        "padding:10px 14px;font-family:Inter,sans-serif;}"
        ".tool-row{display:flex;justify-content:space-between;gap:12px;font-size:13px;"
        "color:#8B949E;padding:3px 0;}"
        ".tool-val{font-family:'JetBrains Mono',monospace;color:#E6EDF3;}"
        ".tool-pill{display:inline-block;font-family:'JetBrains Mono',monospace;"
        "font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;}"
        ".mx{border-collapse:collapse;font-family:'JetBrains Mono',monospace;font-size:11px;}"
        ".mx td,.mx th{width:26px;height:22px;text-align:center;color:#E6EDF3;"
        "border:1px solid #0D1117;}"
        ".mx th{color:#8B949E;font-weight:600;}"
        ".mx-legend{font-family:Inter,sans-serif;font-size:12px;color:#8B949E;"
        "margin-top:8px;line-height:1.6;}"
        "</style>"
    )


def _start_here_html() -> str:
    """The Start-here orientation: intro + the numbered daily loop + the
    “good to know” notes, all from ``help_content`` and escaped."""
    intro = f'<p class="help-intro">{escape(START_HERE_INTRO)}</p>'
    steps = "".join(
        f'<div class="help-step"><div class="help-num">{i}</div>'
        f'<div class="help-step-body"><span class="help-step-label">{escape(label)}</span>'
        f' — {escape(text)}</div></div>'
        for i, (label, text) in enumerate(DAILY_LOOP, start=1)
    )
    notes = "".join(
        f'<div class="help-note"><div class="help-note-title">{escape(title)}</div>'
        f'<div class="help-note-body">{escape(text)}</div></div>'
        for title, text in GOOD_TO_KNOW
    )
    return (
        f'{intro}'
        f'<div class="help-h">Your daily loop</div>{steps}'
        f'<div class="help-h">Good to know</div>{notes}'
    )


def _glossary_group_html(group: str, blurb: str, terms: list) -> str:
    """One glossary group: an uppercase title, a short blurb, and the term/definition
    rows. Every term and definition is escaped."""
    rows = "".join(
        f'<div class="gloss-row"><span class="gloss-term">{escape(str(term))}</span>'
        f'<span class="gloss-def">{escape(str(defn))}</span></div>'
        for term, defn in terms
    )
    return (
        f'<div class="gloss-section"><div class="gloss-title">{escape(str(group))}</div>'
        f'<div class="gloss-blurb">{escape(str(blurb))}</div>{rows}</div>'
    )


def _tour_card_html(entry: dict) -> str:
    """One page's tour card: icon + name, what it's for, the three things to look at
    first, and — when the page has any — its colours/badges decoded. All escaped."""
    icon = escape(str(entry.get("icon", "")))
    page = escape(str(entry.get("page", "")))
    what = escape(str(entry.get("what", "")))
    firsts = "".join(f"<li>{escape(str(x))}</li>" for x in entry.get("first", []))
    decode = entry.get("decode") or []
    decode_html = ""
    if decode:
        rows = "".join(
            f'<div class="gloss-row"><span class="gloss-term">{escape(str(label))}</span>'
            f'<span class="gloss-def">{escape(str(meaning))}</span></div>'
            for label, meaning in decode
        )
        decode_html = f'<div class="tour-sub">Colours &amp; badges</div>{rows}'
    return (
        f'<div class="tour-card">'
        f'<div class="tour-head"><span class="tour-icon">{icon}</span>{page}</div>'
        f'<div class="tour-what">{what}</div>'
        f'<div class="tour-sub">Look at first</div>'
        f'<ol class="tour-first">{firsts}</ol>'
        f'{decode_html}</div>'
    )


def _tour_html(tour: list) -> str:
    """All page tour cards, in sidebar order."""
    return "".join(_tour_card_html(e) for e in tour)


def _faq_html(faq: list) -> str:
    """The FAQ as escaped question/answer rows."""
    return "".join(
        f'<div class="faq-item"><div class="faq-q">{escape(str(q))}</div>'
        f'<div class="faq-a">{escape(str(a))}</div></div>'
        for q, a in faq
    )


def _concepts_html(concepts: list) -> str:
    """Betting 101 cards: a title, a plain-English explanation, and a worked example in
    a tinted box. All dynamic text escaped (the “Example.” label is a static literal)."""
    return "".join(
        f'<div class="concept">'
        f'<div class="concept-title">{escape(str(c.get("title", "")))}</div>'
        f'<div class="concept-body">{escape(str(c.get("body", "")))}</div>'
        f'<div class="concept-eg"><b>Example.</b> {escape(str(c.get("example", "")))}'
        f'</div></div>'
        for c in concepts
    )


def _value_result_html(odds, model_pct, implied, edge, verdict, threshold_pp, ceiling_pp) -> str:
    """The 'Is it value?' read-out (all values numeric — no user strings reach the
    markup). Shows implied %, the raw edge (model − 1/odds) coloured by verdict, and the
    verdict pill against the config bounds."""
    if implied is None or edge is None:
        return ('<div class="tool-out"><div class="tool-row">'
                '<span>Enter decimal odds above 1.00 to compare.</span></div></div>')
    label, col = {
        "value": ("VALUE", "#3FB950"),
        "capped": ("CAPPED — likely model error", "#D29922"),
        "none": ("NO EDGE", "#8B949E"),
    }[verdict]
    return (
        '<div class="tool-out">'
        f'<div class="tool-row"><span>Bookmaker implied probability (1 ÷ {odds:.2f})</span>'
        f'<span class="tool-val">{implied:.1f}%</span></div>'
        f'<div class="tool-row"><span>Your chance</span>'
        f'<span class="tool-val">{model_pct:.1f}%</span></div>'
        f'<div class="tool-row"><span>Edge (your % − implied)</span>'
        f'<span class="tool-val" style="color:{col};">{edge:+.1f} pp</span></div>'
        f'<div class="tool-row"><span>Verdict (backable {threshold_pp:.0f}–{ceiling_pp:.0f} pp)</span>'
        f'<span class="tool-pill" style="background:{col};color:#0D1117;">{label}</span></div>'
        '</div>'
    )


def _stake_result_html(flat, kelly, kelly_fraction) -> str:
    """The 'How much to stake?' read-out — flat/percentage and (fractional) Kelly, in
    dollars. Numeric only."""
    note = "" if kelly > 0 else " — no edge at these numbers"
    return (
        '<div class="tool-out">'
        f'<div class="tool-row"><span>Flat / percentage stake</span>'
        f'<span class="tool-val">${flat:,.2f}</span></div>'
        f'<div class="tool-row"><span>Kelly stake ({kelly_fraction * 100:.0f}% of full Kelly)</span>'
        f'<span class="tool-val">${kelly:,.2f}{note}</span></div>'
        '</div>'
    )


def _matrix_reader_html() -> str:
    """A small labelled 7×7 scoreline grid: home-win / draw / away-win regions tinted,
    with a legend explaining how each market is summed from the cells. Static."""
    green, grey, red = "rgba(63,185,80,0.22)", "rgba(139,148,158,0.25)", "rgba(248,81,73,0.20)"
    head = "".join(f"<th>{a}</th>" for a in range(7))
    rows = ""
    for h in range(7):
        cells = "".join(
            f'<td style="background:{green if h > a else (grey if h == a else red)};">·</td>'
            for a in range(7)
        )
        rows += f"<tr><th>{h}</th>{cells}</tr>"
    return (
        '<div style="overflow-x:auto;">'
        f'<table class="mx"><tr><th>H\\A</th>{head}</tr>{rows}</table></div>'
        '<div class="mx-legend">Rows = home goals, columns = away goals. '
        '<b style="color:#3FB950;">Green</b> cells (home &gt; away) sum to the home win; '
        'the <b style="color:#8B949E;">grey</b> diagonal (level scores) sums to the draw; '
        '<b style="color:#F85149;">red</b> cells (away &gt; home) sum to the away win. '
        'Over 2.5 = every cell where the two numbers add to 3 or more; BTTS Yes = every '
        'cell where both are at least 1.</div>'
    )


def _tool_bounds():
    """(threshold_pp, ceiling_pp, kelly_fraction) from the SAME config the value finder
    uses — documented defaults if it can't be loaded. Not pure (reads config), so it
    stays out of the AST-tested helper set."""
    try:
        from src.world_cup.value_finder import _load_betting_config
        cfg = _load_betting_config() or {}
    except Exception:
        cfg = {}
    return (
        float(cfg.get("edge_threshold", 0.03)) * 100.0,
        float(cfg.get("max_actionable_edge", 0.15)) * 100.0,
        float(cfg.get("kelly_fraction", 0.25)),
    )


def _glossary_html(groups: list) -> str:
    """The full (possibly filtered) glossary, or a friendly empty state when a search
    matches nothing."""
    if not groups:
        return (
            '<div class="bv-empty-state">No terms match your search. Try a shorter '
            'word, or clear the box to see everything.</div>'
        )
    return "".join(
        _glossary_group_html(g["group"], g["blurb"], g["terms"]) for g in groups
    )


# ============================================================================
# Page layout (runs at import — Streamlit page convention)
# ============================================================================

st.markdown('<div class="bv-page-title">Help &amp; Manual</div>', unsafe_allow_html=True)
st.markdown(
    '<p class="text-muted">What everything means and where to find it — your guide '
    'to BetVector.</p>',
    unsafe_allow_html=True,
)
st.markdown(_help_css(), unsafe_allow_html=True)

# Deep-link focus (HC-03): a page's "How to read this page" link drops you here with
# that page's tour card surfaced at the top. Pop it so it clears on the next action.
_focus = st.session_state.pop("help_focus_page", None)
_focus_card = tour_for_page(_focus) if _focus else None
if _focus_card:
    st.markdown('<div class="help-focus-head">How to read this page</div>',
                unsafe_allow_html=True)
    st.markdown(_tour_card_html(_focus_card), unsafe_allow_html=True)
    st.caption(
        "That's the quick guide for the page you came from. The full tour, FAQ and "
        "glossary are in the tabs below."
    )

st.divider()

_tab_start, _tab_tour, _tab_101, _tab_tools, _tab_faq, _tab_gloss = st.tabs(
    ["📖 Start here", "🗺️ Screen tour", "🎓 Betting 101", "🧮 Tools", "❓ FAQ", "🔤 Glossary"]
)

with _tab_start:
    st.markdown(_start_here_html(), unsafe_allow_html=True)
    st.caption(
        "Tip: the tabs above cover the screen tour, Betting 101 with worked examples, "
        "interactive tools, an FAQ, and a searchable glossary."
    )
    # Downloadable manual — the whole Help Center as one document, built from the same
    # content shown here (so it never drifts). Markdown opens anywhere; the print-friendly
    # HTML can be saved as a PDF from the browser's Print dialog. No new dependency.
    st.divider()
    st.markdown(
        '<div class="help-dl-head">📘 Take the manual with you</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "The full guide — Start here, the screen tour, Betting 101, the FAQ and the "
        "glossary — as one document. Markdown opens anywhere; open the HTML and use your "
        "browser's Print → Save as PDF for a PDF copy."
    )
    _dl_md, _dl_html = st.columns(2)
    with _dl_md:
        st.download_button(
            "⬇ Download the manual (Markdown)",
            data=build_manual_markdown(),
            file_name="betvector_manual.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with _dl_html:
        st.download_button(
            "⬇ Download the manual (HTML / print to PDF)",
            data=build_manual_html(),
            file_name="betvector_manual.html",
            mime="text/html",
            use_container_width=True,
        )

with _tab_tour:
    st.caption(
        "A quick guide to each screen — what it's for, what to look at first, and what "
        "every colour and badge means."
    )
    st.markdown(_tour_html(TOUR), unsafe_allow_html=True)

with _tab_101:
    st.caption("The ideas behind the numbers — each with a quick worked example.")
    st.markdown(_concepts_html(CONCEPTS), unsafe_allow_html=True)

with _tab_tools:
    st.caption("Try the numbers yourself — read-only, nothing is logged.")
    _thr_pp, _ceil_pp, _kf = _tool_bounds()

    st.markdown('<div class="tool-h">Is it value?</div>', unsafe_allow_html=True)
    _tc1, _tc2 = st.columns(2)
    _t_odds = _tc1.number_input("Decimal odds", min_value=1.01, value=2.50, step=0.05,
                                key="help_tool_odds")
    _t_model = _tc2.number_input("Your (or the model's) chance, %", min_value=0.0,
                                 max_value=100.0, value=48.0, step=0.5, key="help_tool_model")
    _t_imp = implied_pct_from_odds(_t_odds)
    _t_edge = edge_pp(_t_model, _t_odds)
    _t_verd = verdict_for_edge(_t_edge, _thr_pp, _ceil_pp)
    st.markdown(
        _value_result_html(_t_odds, _t_model, _t_imp, _t_edge, _t_verd, _thr_pp, _ceil_pp),
        unsafe_allow_html=True,
    )

    st.markdown('<div class="tool-h">How much to stake?</div>', unsafe_allow_html=True)
    _tc3, _tc4 = st.columns(2)
    _t_bank = _tc3.number_input("Bankroll, $", min_value=0.0, value=1000.0, step=50.0,
                                key="help_tool_bank")
    _t_pct = _tc4.number_input("Stake, % of bankroll", min_value=0.0, max_value=100.0,
                               value=2.0, step=0.5, key="help_tool_pct")
    st.markdown(
        _stake_result_html(flat_stake(_t_bank, _t_pct),
                           kelly_stake(_t_bank, _t_model, _t_odds, _kf), _kf),
        unsafe_allow_html=True,
    )
    st.caption(
        f"Kelly uses the odds and chance from the calculator above, sized to {_kf * 100:.0f}% "
        "of full Kelly for safety. Educational only — not a recommendation to bet."
    )

    st.markdown('<div class="tool-h">Reading the scoreline matrix</div>', unsafe_allow_html=True)
    st.markdown(_matrix_reader_html(), unsafe_allow_html=True)

with _tab_faq:
    st.caption("Quick answers to the questions that come up most.")
    st.markdown(_faq_html(FAQ), unsafe_allow_html=True)

with _tab_gloss:
    _query = st.text_input(
        "Search terms",
        placeholder="Search a word, badge or colour — e.g. edge, CLV, drawdown, BTTS…",
        label_visibility="collapsed",
        key="help_glossary_search",
    )
    _groups = filter_glossary(_query)
    _shown = sum(len(g["terms"]) for g in _groups)
    _suffix = f' matching “{_query.strip()}”' if _query and _query.strip() else ""
    st.caption(f"Showing {_shown} of {term_count()} terms{_suffix}.")
    st.markdown(_glossary_html(_groups), unsafe_allow_html=True)
