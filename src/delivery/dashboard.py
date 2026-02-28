"""
BetVector — Dashboard Shell (E9-01)
====================================
Main Streamlit entry point.  Provides the dark-themed app shell with
navigation, password gate, and custom CSS injection.

Run with::

    streamlit run src/delivery/dashboard.py

Design System
-------------
The dashboard uses a dark trading-terminal aesthetic inspired by
Bloomberg Terminal and TradingView (MP §8).  Key design tokens:

- Background:  #0D1117  (near-black with blue undertone)
- Surface:     #161B22  (cards, panels, elevated surfaces)
- Text:        #E6EDF3  (high contrast white)
- Green:       #3FB950  (profits, wins, positive edges)
- Red:         #F85149  (losses, drawdowns, warnings)
- Yellow:      #D29922  (medium confidence, caution)
- Blue:        #58A6FF  (links, interactive elements)
- Border:      #30363D  (card and section borders)

Typography:
- JetBrains Mono — monospace font for data values, numbers, odds
- Inter — sans-serif for body text, labels, headings

Six pages (MP §3 Flow 4):
1. Today's Picks
2. Performance Tracker
3. League Explorer
4. Model Health
5. Bankroll Manager
6. Settings

Master Plan refs: MP §8 Design System, MP §3 Flow 4
"""

import os

import streamlit as st

# ============================================================================
# Page Config — must be first Streamlit call
# ============================================================================

st.set_page_config(
    page_title="BetVector",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================================
# Custom CSS — MP §8 Design System
# ============================================================================

def inject_custom_css() -> None:
    """Inject custom CSS for fonts, cards, tables, and badges.

    Loads JetBrains Mono and Inter from Google Fonts, then applies the
    BetVector design system tokens from MP §8.
    """
    st.markdown("""
    <style>
    /* --- Google Fonts --- */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');

    /* --- Global Typography --- */
    /* Inter for body text, labels, and headings */
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* JetBrains Mono for data values and numbers */
    .data-value, .stMetricValue, [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
    }

    /* --- Background Overrides --- */
    /* Ensure Streamlit uses our exact colours */
    .stApp {
        background-color: #0D1117;
    }
    [data-testid="stSidebar"] {
        background-color: #161B22;
        border-right: 1px solid #30363D;
    }

    /* --- Card Styling --- */
    /* BV cards: surface bg, subtle border, rounded corners */
    .bv-card {
        background-color: #161B22;
        border: 1px solid #30363D;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
    }
    .bv-card:hover {
        border-color: #3FB950;
        background-color: #1C2333;
    }

    /* --- Metric Cards --- */
    /* Large numbers in metric cards use JetBrains Mono */
    [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 28px !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricLabel"] {
        font-family: 'Inter', sans-serif !important;
        color: #8B949E !important;
        font-size: 12px !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    [data-testid="stMetricDelta"] {
        font-family: 'JetBrains Mono', monospace !important;
    }

    /* --- Table Styling --- */
    /* Alternating row colours, no outer border */
    [data-testid="stTable"] table {
        border-collapse: collapse;
        width: 100%;
    }
    [data-testid="stTable"] th {
        color: #8B949E !important;
        text-transform: uppercase;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
        border-bottom: 1px solid #30363D;
    }
    [data-testid="stTable"] td {
        font-family: 'JetBrains Mono', monospace;
        font-size: 14px;
        border-bottom: 1px solid #30363D;
    }
    [data-testid="stTable"] tr:nth-child(even) {
        background-color: #161B22;
    }
    [data-testid="stTable"] tr:nth-child(odd) {
        background-color: #0D1117;
    }

    /* --- DataFrame styling --- */
    [data-testid="stDataFrame"] {
        font-family: 'JetBrains Mono', monospace;
    }

    /* --- Badge Styling --- */
    .bv-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-family: 'Inter', sans-serif;
        font-size: 11px;
        font-weight: 600;
        color: #0D1117;
    }
    .bv-badge-green { background-color: #3FB950; }
    .bv-badge-red { background-color: #F85149; }
    .bv-badge-yellow { background-color: #D29922; }
    .bv-badge-blue { background-color: #58A6FF; }
    .bv-badge-muted {
        background-color: #484F58;
        color: #E6EDF3;
    }

    /* --- Colour Utility Classes --- */
    .text-green { color: #3FB950 !important; }
    .text-red { color: #F85149 !important; }
    .text-yellow { color: #D29922 !important; }
    .text-blue { color: #58A6FF !important; }
    .text-muted { color: #8B949E !important; }
    .text-primary { color: #E6EDF3 !important; }

    /* --- Positive/Negative number colours --- */
    .positive { color: #3FB950 !important; font-family: 'JetBrains Mono', monospace; }
    .negative { color: #F85149 !important; font-family: 'JetBrains Mono', monospace; }

    /* --- Sidebar Navigation Styling --- */
    [data-testid="stSidebarNav"] {
        padding-top: 1rem;
    }
    [data-testid="stSidebar"] .stRadio label {
        font-family: 'Inter', sans-serif !important;
        font-size: 14px;
        padding: 8px 12px;
        border-radius: 6px;
        transition: background-color 0.2s;
    }
    [data-testid="stSidebar"] .stRadio label:hover {
        background-color: #1C2333;
    }

    /* --- Section Headers --- */
    .bv-section-header {
        font-family: 'Inter', sans-serif;
        font-size: 18px;
        font-weight: 600;
        color: #E6EDF3;
        margin-bottom: 16px;
    }

    /* --- Page Title --- */
    .bv-page-title {
        font-family: 'Inter', sans-serif;
        font-size: 24px;
        font-weight: 700;
        color: #E6EDF3;
        margin-bottom: 8px;
    }

    /* --- Empty State --- */
    .bv-empty-state {
        text-align: center;
        padding: 48px 24px;
        color: #8B949E;
        font-family: 'Inter', sans-serif;
        font-size: 14px;
    }

    /* --- Error State --- */
    .bv-error {
        border: 1px solid #F85149;
        border-radius: 8px;
        padding: 16px;
        color: #F85149;
        background-color: rgba(248, 81, 73, 0.1);
    }

    /* --- Loading Skeleton --- */
    @keyframes bv-pulse {
        0%, 100% { opacity: 0.3; }
        50% { opacity: 0.7; }
    }
    .bv-skeleton {
        background-color: #161B22;
        border-radius: 4px;
        animation: bv-pulse 1.5s ease-in-out infinite;
    }

    /* --- Mobile Responsive --- */
    @media (max-width: 768px) {
        [data-testid="stMetricValue"] {
            font-size: 22px !important;
        }
        .bv-card {
            padding: 12px;
        }
    }

    /* --- Hide Streamlit branding --- */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)


# ============================================================================
# Password Gate
# ============================================================================

def check_password() -> bool:
    """Simple password gate using an environment variable.

    Checks the entered password against DASHBOARD_PASSWORD from .env.
    If the environment variable is not set, the dashboard is open
    (useful for local development).

    Returns True if authenticated, False otherwise.
    """
    # If no password is set in env, allow access (dev mode)
    dashboard_password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not dashboard_password:
        return True

    # Check if already authenticated this session
    if st.session_state.get("authenticated", False):
        return True

    # Show login form
    st.markdown(
        '<div class="bv-page-title">BetVector</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="text-muted">Quantitative edge in football betting</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    password = st.text_input("Enter dashboard password", type="password")

    if password:
        if password == dashboard_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")

    return False


# ============================================================================
# Page Definitions
# ============================================================================

def get_pages() -> list:
    """Define the six dashboard pages.

    Uses Streamlit's st.Page to define each page with its file path,
    title, and icon.  The pages are loaded from src/delivery/pages/.

    Returns
    -------
    list
        List of st.Page objects for st.navigation().
    """
    # Paths are relative to this file's directory (src/delivery/)
    return [
        st.Page(
            "pages/picks.py",
            title="Today's Picks",
            icon="🎯",
            default=True,
        ),
        st.Page(
            "pages/performance.py",
            title="Performance Tracker",
            icon="📈",
        ),
        st.Page(
            "pages/leagues.py",
            title="League Explorer",
            icon="🏟️",
        ),
        st.Page(
            "pages/model_health.py",
            title="Model Health",
            icon="🔬",
        ),
        st.Page(
            "pages/bankroll.py",
            title="Bankroll Manager",
            icon="💰",
        ),
        st.Page(
            "pages/settings.py",
            title="Settings",
            icon="⚙️",
        ),
        st.Page(
            "pages/match_detail.py",
            title="Match Deep Dive",
            icon="🔍",
        ),
    ]


# ============================================================================
# Sidebar
# ============================================================================

def render_sidebar() -> None:
    """Render the sidebar with branding and info."""
    with st.sidebar:
        st.markdown(
            '<div class="bv-page-title">BetVector</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p class="text-muted">Quantitative edge in football betting</p>',
            unsafe_allow_html=True,
        )
        st.divider()


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    """Main entry point for the BetVector dashboard."""
    # Inject custom CSS (must come after set_page_config)
    inject_custom_css()

    # Password gate
    if not check_password():
        return

    # Render sidebar branding
    render_sidebar()

    # Set up navigation
    pages = get_pages()
    nav = st.navigation(pages)
    nav.run()


if __name__ == "__main__":
    main()
