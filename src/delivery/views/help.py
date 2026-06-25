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
    DAILY_LOOP,
    FAQ,
    GOOD_TO_KNOW,
    START_HERE_INTRO,
    TOUR,
    filter_glossary,
    term_count,
    tour_for_page,
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

_tab_start, _tab_tour, _tab_faq, _tab_gloss = st.tabs(
    ["📖 Start here", "🗺️ Screen tour", "❓ FAQ", "🔤 Glossary"]
)

with _tab_start:
    st.markdown(_start_here_html(), unsafe_allow_html=True)
    st.caption(
        "More is coming to this page — Betting 101 with worked examples, and "
        "interactive tools."
    )

with _tab_tour:
    st.caption(
        "A quick guide to each screen — what it's for, what to look at first, and what "
        "every colour and badge means."
    )
    st.markdown(_tour_html(TOUR), unsafe_allow_html=True)

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
