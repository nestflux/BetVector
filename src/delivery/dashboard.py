"""
BetVector — Dashboard Shell (E9-01, E30-03, E33-05)
====================================================
Main Streamlit entry point.  Provides the dark-themed app shell with
navigation, password gate, and custom CSS injection.

Deployment:
- **Local:** ``streamlit run src/delivery/dashboard.py`` (SQLite via config)
- **Streamlit Cloud:** Deploy from GitHub repo; database connection via
  ``st.secrets["database"]["connection_string"]`` (Neon PostgreSQL)

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

E30-03: Logo integration:
- Favicon: Bvlogo1.5 (V icon) replaces 📊 emoji
- Sidebar: st.logo() with Bvlogo3 (expanded) / Bvlogo1.5 (collapsed)
- Login gate: Bvlogo3 image replaces text heading

Master Plan refs: MP §8 Design System, MP §3 Flow 4
"""

import sys
import base64
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Streamlit Cloud sys.path fix
# On Streamlit Cloud the repo root (/mount/src/betvector/) is NOT added to
# sys.path automatically, so `from src.config import ...` fails with
# ModuleNotFoundError.  Insert it explicitly before any src.* imports.
# This is a no-op when running locally (the editable install handles it).
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from dotenv import load_dotenv
import streamlit as st

from src.config import PROJECT_ROOT

# Load .env file so DASHBOARD_PASSWORD and other secrets are available
# even when running via `streamlit run` directly (without the Desktop launcher).
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path)

# ============================================================================
# Logo assets (E30-03)
# Bvlogo3.png  = full wordmark "BetVector" with lightning-slash V (sidebar expanded, login)
# Bvlogo1.5.png = standalone V icon with green arrow (favicon, sidebar collapsed)
# ============================================================================
_LOGO_DIR = PROJECT_ROOT / "docs" / "logo"
_LOGO_WORDMARK = str(_LOGO_DIR / "Bvlogo3.png")
_LOGO_ICON = str(_LOGO_DIR / "Bvlogo1.5.png")

# Pre-encode the wordmark as base64 once at startup so the centered header
# can use an inline <img> src without needing a file path accessible to the
# browser (Streamlit doesn't serve arbitrary files via unsafe_allow_html).
try:
    _LOGO_B64 = base64.b64encode(Path(_LOGO_WORDMARK).read_bytes()).decode("ascii")
except OSError:
    _LOGO_B64 = ""


def render_page_logo(width: int = 200) -> None:
    """Render the BetVector wordmark centered at the top of the content area.

    Called from main() before nav.run() so it appears on every page.
    Uses an inline base64 <img> so it works even without a static file server.

    Parameters
    ----------
    width : int
        Display width of the logo in pixels (default 200).
    """
    if not _LOGO_B64:
        return
    st.markdown(
        f'<div style="text-align: center; padding: 28px 0 6px;">'
        f'<img src="data:image/png;base64,{_LOGO_B64}" '
        f'style="width: {width}px; max-width: 55%;" alt="BetVector">'
        f'</div>',
        unsafe_allow_html=True,
    )


# ============================================================================
# Page Config — must be first Streamlit call
# ============================================================================

st.set_page_config(
    page_title="BetVector",
    page_icon=_LOGO_ICON,
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
    # Check env var first, then Streamlit secrets (for Streamlit Cloud).
    # We only check st.secrets when a secrets file actually exists —
    # accessing st.secrets without one triggers a visible Streamlit warning.
    dashboard_password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not dashboard_password:
        try:
            secrets_path = Path(__file__).resolve().parents[2] / ".streamlit" / "secrets.toml"
            home_secrets = Path.home() / ".streamlit" / "secrets.toml"
            if secrets_path.exists() or home_secrets.exists():
                dashboard_password = st.secrets.get("DASHBOARD_PASSWORD", "")
        except Exception:
            dashboard_password = ""
    if not dashboard_password:
        return True

    # Check if already authenticated this session
    if st.session_state.get("authenticated", False):
        return True

    # Inject login-specific CSS — styles the ENTER button to feel like a
    # proper gateway rather than a default Streamlit button.  The selector
    # targets only buttons inside the login form so other pages aren't affected.
    st.markdown("""
    <style>
    /* ENTER button — full-width, green-bordered, JetBrains Mono */
    [data-testid="stForm"] .stFormSubmitButton > button {
        width: 100%;
        background: transparent;
        border: 1px solid #3FB950;
        color: #3FB950;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 12px !important;
        font-weight: 700 !important;
        letter-spacing: 4px;
        text-transform: uppercase;
        padding: 14px 24px !important;
        border-radius: 6px;
        margin-top: 4px;
        cursor: pointer;
        transition: background 0.2s ease, box-shadow 0.2s ease;
    }
    [data-testid="stForm"] .stFormSubmitButton > button:hover {
        background: rgba(63, 185, 80, 0.08);
        box-shadow: 0 0 18px rgba(63, 185, 80, 0.18);
    }
    [data-testid="stForm"] .stFormSubmitButton > button:active {
        background: rgba(63, 185, 80, 0.15);
    }
    /* Remove the default red error colour from the password input border */
    [data-testid="stForm"] [data-baseweb="input"] {
        border-color: #30363D !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Show login form — centered logo + form for a polished login screen.
    # Using st.form so pressing Enter key on the keyboard also submits.
    _, col, _ = st.columns([1, 2, 1])
    with col:
        render_page_logo(width=220)
        st.markdown(
            '<p style="text-align:center; font-family: Inter, sans-serif; '
            'font-size: 13px; color: #8B949E; margin-bottom: 24px;">'
            "Quantitative edge in football betting</p>",
            unsafe_allow_html=True,
        )
        st.divider()
        with st.form("login_form", border=False):
            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter password",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button("ENTER")
            if submitted:
                if password == dashboard_password:
                    st.session_state["authenticated"] = True
                    st.rerun()
                elif password:
                    st.error("Incorrect password. Try again.")

    return False


# ============================================================================
# Page Definitions
# ============================================================================

def get_pages() -> list:
    """Define the six dashboard pages.

    Uses Streamlit's st.Page to define each page with its file path,
    title, and icon.  The pages are loaded from src/delivery/views/.

    Returns
    -------
    list
        List of st.Page objects for st.navigation().
    """
    # Paths are relative to this file's directory (src/delivery/)
    # E26-03: Fixtures is the landing page — the most interesting first
    # view, showing all matches with predicted scores and top picks.
    # Today's Picks is still prominent in the sidebar.
    return [
        st.Page(
            "views/fixtures.py",
            title="Fixtures",
            icon="📅",
            default=True,
        ),
        st.Page(
            "views/picks.py",
            title="Today's Picks",
            icon="🎯",
        ),
        st.Page(
            "views/performance.py",
            title="Performance Tracker",
            icon="📈",
        ),
        st.Page(
            "views/leagues.py",
            title="League Explorer",
            icon="🏟️",
        ),
        st.Page(
            "views/model_health.py",
            title="Model Health",
            icon="🔬",
        ),
        st.Page(
            "views/bankroll.py",
            title="Bankroll Manager",
            icon="💰",
        ),
        st.Page(
            "views/settings.py",
            title="Settings",
            icon="⚙️",
        ),
        st.Page(
            "views/match_detail.py",
            title="Match Deep Dive",
            icon="🔍",
        ),
    ]


# ============================================================================
# Sidebar
# ============================================================================

def render_sidebar() -> None:
    """Render the sidebar with branding and info.

    E30-03: Uses ``st.logo()`` to show the full wordmark (Bvlogo3) when
    the sidebar is expanded, and the V icon (Bvlogo1.5) when collapsed.
    This replaces the plain-text "BetVector" heading.
    """
    # st.logo() is a Streamlit 1.31+ feature that places a persistent
    # logo at the top of the sidebar.  It accepts two images:
    #   image      = shown when sidebar is expanded (full wordmark)
    #   icon_image = shown when sidebar is collapsed (compact V icon)
    st.logo(
        image=_LOGO_WORDMARK,
        icon_image=_LOGO_ICON,
        size="large",
    )
    with st.sidebar:
        st.markdown(
            '<p class="text-muted">Quantitative edge in football betting</p>',
            unsafe_allow_html=True,
        )
        st.divider()


# ============================================================================
# Main
# ============================================================================

def check_onboarding() -> bool:
    """Check if the current user has completed onboarding.

    Returns True if onboarding is complete (normal dashboard should load).
    Returns False if onboarding is needed (wizard should display instead).
    New users (has_onboarded=0) see the onboarding wizard.
    Returning users skip straight to the dashboard.
    """
    from src.database.db import get_session
    from src.database.models import User

    with get_session() as session:
        # Default to user_id=1 for MVP (single-user system)
        user = session.get(User, 1)
        if not user:
            return True  # No user yet — let setup handle it
        return bool(user.has_onboarded)


def main() -> None:
    """Main entry point for the BetVector dashboard."""
    # Inject custom CSS (must come after set_page_config)
    inject_custom_css()

    # Password gate
    if not check_password():
        return

    # Verify database is accessible before loading pages.
    # On Streamlit Cloud we connect to Neon PostgreSQL via secrets.
    # Show a friendly message instead of crashing with a traceback.
    try:
        from src.database.db import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as db_err:
        st.error("Database connection failed")
        st.markdown(
            "BetVector could not connect to the database. "
            "This usually means:\n\n"
            "- **Local:** Run `python run_pipeline.py setup` first to "
            "create the SQLite database.\n"
            "- **Streamlit Cloud:** Configure your Neon PostgreSQL "
            "connection string in Settings → Secrets under `[database]` "
            "→ `connection_string`.\n\n"
            f"Error: `{db_err}`"
        )
        return

    # Onboarding gate — new users see the wizard instead of the dashboard.
    # We use st.navigation with a single page to prevent Streamlit from
    # showing the default page discovery sidebar.
    if not check_onboarding():
        from src.delivery.pages.onboarding import render_onboarding
        onboarding_page = st.Page(render_onboarding, title="Welcome", icon="👋")
        nav = st.navigation([onboarding_page], position="hidden")
        nav.run()
        return

    # Render sidebar branding
    render_sidebar()

    # Centered wordmark at top of every page
    render_page_logo()

    # Set up navigation
    pages = get_pages()
    nav = st.navigation(pages)
    nav.run()


if __name__ == "__main__":
    main()
