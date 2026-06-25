"""Shared dashboard cache TTLs (config-driven) — Neon data-transfer control.

Streamlit's ``@st.cache_data`` is a CROSS-SESSION global cache keyed on
(function, args), so a single DB read serves every concurrent user until the
TTL expires.  That makes it the main lever for keeping the dashboard's Neon
data-transfer down (Neon free-tier egress is a recurring blocker — see
DATA_GAPS.md / PC-13).  Dashboard data changes only when the pipeline runs
(roughly daily), so a minutes-scale TTL is invisible to users.

IMPORTANT — only GLOBAL (non-user-scoped) loaders are cached with these TTLs.
Per-user or in-session-mutated data (a user's own bets / bankroll) is left
UNCACHED on purpose: a cross-session cache would risk one user seeing another's
data and would make freshly-placed bets fail to appear until the TTL expired.

Values come from ``config/settings.yaml`` (``dashboard:``) with safe fallbacks,
so the cache aggressiveness is tunable without code changes (Rule 6).
"""
from src.config import config


def _ttl(name: str, default: int) -> int:
    """Read a dashboard cache TTL (seconds) from config, falling back safely."""
    try:
        return int(getattr(config.settings.dashboard, name))
    except Exception:
        # Config section missing/malformed — use the documented default so the
        # dashboard still caches sensibly rather than crashing at import.
        return default


# Standard TTL for pipeline-updated global reads (fixtures, value bets, model
# performance). 10 minutes by default.
CACHE_TTL = _ttl("cache_ttl_seconds", 600)
# Fresher TTL for the most volatile global reads (live model metrics, top
# picks). 5 minutes.
CACHE_TTL_LIVE = _ttl("cache_ttl_live_seconds", 300)
# Long TTL for slow-moving global reads (group standings, recent results).
# 30 minutes.
CACHE_TTL_SLOW = _ttl("cache_ttl_slow_seconds", 1800)
