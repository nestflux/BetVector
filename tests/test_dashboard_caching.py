"""Dashboard read-caching — Neon data-transfer control.

Verifies:
- the shared cache TTLs resolve to positive ints (with a config fallback),
- the GLOBAL loaders are decorated with @st.cache_data (the egress cut),
- the USER-SCOPED loaders are NOT cached — a cross-session @st.cache_data cache
  without user_id in the key would leak one user's bets/bankroll to another, so
  they stay uncached on purpose (this is the multi-user safety guard),
- the World Cup upcoming-matches query is date-windowed, not a full-table scan.

View modules run st.* at import, so these checks are AST-on-source, not imports.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "src" / "delivery" / "views"


def _decorated_functions(path: Path) -> dict[str, list[str]]:
    """Map function name -> list of its decorator source snippets."""
    tree = ast.parse(path.read_text())
    return {
        node.name: [ast.unparse(d) for d in node.decorator_list]
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def _is_cache_data(decorators: list[str]) -> bool:
    return any("st.cache_data" in d for d in decorators)


# --- TTL config -------------------------------------------------------------

def test_cache_ttls_are_positive_ints():
    from src.delivery._cache import CACHE_TTL, CACHE_TTL_LIVE, CACHE_TTL_SLOW
    for v in (CACHE_TTL, CACHE_TTL_LIVE, CACHE_TTL_SLOW):
        assert isinstance(v, int) and v > 0


def test_cache_ttl_falls_back_when_config_key_missing():
    import src.delivery._cache as c
    assert c._ttl("does_not_exist_xyz", 777) == 777


# --- GLOBAL loaders MUST be cached (the egress cut) -------------------------

GLOBAL_CACHED = {
    "model_health.py": [
        "compute_live_brier_and_calibration", "load_calibration_data",
        "load_model_comparison", "load_ensemble_weights", "load_feature_importance",
        "load_market_edge_map", "load_calibration_history", "load_retrain_history",
    ],
    "fixtures.py": ["get_all_upcoming_fixtures", "get_recent_results", "get_top_picks"],
    "picks.py": ["get_value_bets_in_range"],
    "my_bets.py": ["load_fixtures_with_odds"],
    "world_cup.py": ["_compute_group_standings"],
}


@pytest.mark.parametrize("filename,funcs", list(GLOBAL_CACHED.items()))
def test_global_loaders_are_cached(filename, funcs):
    decs = _decorated_functions(VIEWS / filename)
    for fn in funcs:
        assert fn in decs, f"{fn} not found in {filename}"
        assert _is_cache_data(decs[fn]), f"{fn} in {filename} must be @st.cache_data"


# --- USER-SCOPED loaders MUST NOT be cached (multi-user leak guard) ---------

USER_SCOPED_UNCACHED = {
    "performance.py": ["load_bet_data"],
    "bankroll.py": [
        "load_bet_history", "load_bankroll_history", "load_monthly_breakdown",
    ],
    "my_bets.py": ["load_user_bets"],
}


@pytest.mark.parametrize("filename,funcs", list(USER_SCOPED_UNCACHED.items()))
def test_user_scoped_loaders_not_cached(filename, funcs):
    """@st.cache_data is a cross-session global cache; caching per-user data
    without user_id in the key would let one user see another's bets/bankroll.
    These loaders stay uncached unless/until user_id is part of the cache key."""
    decs = _decorated_functions(VIEWS / filename)
    for fn in funcs:
        assert fn in decs, f"{fn} not found in {filename}"
        assert not _is_cache_data(decs[fn]), (
            f"{fn} in {filename} reads USER-SCOPED data and must NOT be "
            f"@st.cache_data without user_id in the cache key (multi-user leak)"
        )


# --- WC egress optimization -------------------------------------------------

def test_wc_upcoming_query_is_date_windowed():
    src = (VIEWS / "world_cup.py").read_text()
    assert "WCMatch.date >= sql_from" in src and "WCMatch.date <= sql_to" in src, (
        "the WC upcoming-matches query must filter by a date window in SQL, "
        "not load every match and filter in Python"
    )
