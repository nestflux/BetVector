"""
BetVector — Data Health page (DH-03)
====================================
The dashboard face of the read-only data-health engine (``src/monitoring/health_check.py``).
It answers, at a glance, "is the data actually landing where it should, and is it fresh?" —
green/amber/red cards across connectivity, source freshness, fixture coverage, standings
integrity (the stale-stub tripwire) and the last pipeline run.

This page only READS — it runs the same SELECT-only engine the CLI (`make health`) does,
caches the result for a minute, and offers a manual refresh. It never writes, and never
touches the model/value/bet path. The pure HTML helpers are escaped and AST-tested.
"""

from html import escape
from typing import Optional

import streamlit as st

from src.monitoring.health_check import run_health_checks
from src.monitoring.health_cli import report_to_dict


# ============================================================================
# Pure HTML helpers (Streamlit-free → AST-testable; all dynamic text escaped)
# ============================================================================

def _status_meta(status: str):
    """(_colour, glyph, short label) for a check status. Inlined so the helper is
    self-contained for the AST test harness (which execs functions, not module vars)."""
    table = {
        "ok": ("#3FB950", "✓", "OK"),
        "warn": ("#D29922", "⚠", "WARN"),
        "fail": ("#F85149", "✗", "FAIL"),
        "skip": ("#8B949E", "·", "N/A"),
    }
    return table.get(status, ("#8B949E", "·", status.upper()))


def _dh_css() -> str:
    return (
        "<style>"
        ".dh-banner{border-radius:10px;padding:14px 18px;margin:6px 0 18px;"
        "background:#161B22;}"
        ".dh-banner-status{font-family:Inter,sans-serif;font-size:20px;font-weight:700;}"
        ".dh-banner-sub{font-family:'JetBrains Mono',monospace;font-size:12px;"
        "color:#8B949E;margin-top:4px;}"
        ".dh-group{margin:0 0 16px;}"
        ".dh-group-title{font-family:Inter,sans-serif;font-size:13px;font-weight:700;"
        "color:#3FB950;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 8px;"
        "border-bottom:1px solid #21262D;padding-bottom:4px;}"
        ".dh-row{background:#161B22;border:1px solid #30363D;border-radius:8px;"
        "padding:9px 12px;margin-bottom:7px;}"
        ".dh-row-head{display:flex;align-items:center;gap:10px;}"
        ".dh-pill{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;"
        "border-radius:6px;padding:2px 8px;flex-shrink:0;}"
        ".dh-name{font-family:Inter,sans-serif;font-size:13px;font-weight:600;color:#E6EDF3;}"
        ".dh-detail{font-family:Inter,sans-serif;font-size:12px;color:#8B949E;"
        "margin-top:4px;line-height:1.45;}"
        "</style>"
    )


def _check_row_html(check: dict) -> str:
    """One check as a card: a coloured status pill, the check name, and the detail."""
    colour, glyph, label = _status_meta(check.get("status", "skip"))
    pill = (f'<span class="dh-pill" style="background:{colour}1f;color:{colour};'
            f'border:1px solid {colour}55;">{glyph} {escape(label)}</span>')
    return (
        '<div class="dh-row"><div class="dh-row-head">'
        f'{pill}<span class="dh-name">{escape(str(check.get("name", "")))}</span></div>'
        f'<div class="dh-detail">{escape(str(check.get("detail", "")))}</div></div>'
    )


def _group_section_html(group: str, checks: list) -> str:
    rows = "".join(_check_row_html(c) for c in checks)
    return (f'<div class="dh-group"><div class="dh-group-title">{escape(group)}</div>'
            f'{rows}</div>')


def _neon_usage_html(usage: Optional[dict], warn_pct: float = 0.80) -> str:
    """One card showing Neon cloud data-transfer usage vs the plan allowance.

    ``usage`` is the dict from ``neon_usage.fetch_neon_usage`` — or ``None`` when
    no API key is set / the API is unreachable, which renders a muted
    'unavailable' note rather than an error.  Colour: green below ``warn_pct``,
    amber from there up to the allowance, red at/over it.  All dynamic text
    escaped.  Streamlit-free so it is AST-testable."""
    if not usage:
        return (
            '<div class="dh-row"><div class="dh-row-head">'
            '<span class="dh-pill" style="background:#8B949E1f;color:#8B949E;'
            'border:1px solid #8B949E55;">· N/A</span>'
            '<span class="dh-name">Neon data transfer</span></div>'
            '<div class="dh-detail">Usage unavailable — set NEON_API_KEY (env or '
            'Streamlit secrets) to show cloud data-transfer headroom.</div></div>'
        )
    pct = usage.get("pct") or 0.0
    if pct >= 1.0:
        colour, glyph, label = "#F85149", "✗", "OVER"
    elif pct >= warn_pct:
        colour, glyph, label = "#D29922", "⚠", "HIGH"
    else:
        colour, glyph, label = "#3FB950", "✓", "OK"
    used_gb = usage.get("used_gb", 0.0) or 0.0
    limit_gb = usage.get("limit_gb", 5.0) or 5.0
    reset = usage.get("reset_date") or "—"
    days = usage.get("days_until_reset")
    days_txt = f" ({days} days)" if isinstance(days, int) else ""
    bar_w = max(0.0, min(pct, 1.0)) * 100
    pill = (f'<span class="dh-pill" style="background:{colour}1f;color:{colour};'
            f'border:1px solid {colour}55;">{glyph} {escape(label)}</span>')
    bar = (f'<div style="background:#21262D;border-radius:5px;height:7px;'
           f'margin:8px 0 2px;overflow:hidden;">'
           f'<div style="width:{bar_w:.0f}%;height:100%;background:{colour};"></div></div>')
    detail = (f"{used_gb:.2f} / {limit_gb:.0f} GB ({pct * 100:.0f}%) · "
              f"resets {reset}{days_txt}")
    return (
        '<div class="dh-row"><div class="dh-row-head">'
        f'{pill}<span class="dh-name">Neon data transfer</span></div>'
        f'{bar}<div class="dh-detail">{escape(detail)}</div></div>'
    )


def _overall_banner_html(overall: str, summary: dict, backend: str,
                         generated_at: str) -> str:
    colour, glyph, _ = _status_meta(overall)
    headline = {"ok": "All systems healthy", "warn": "Needs attention",
                "fail": "Problems detected"}.get(overall, overall.upper())
    sub = (f"{summary.get('ok', 0)} OK · {summary.get('warn', 0)} warn · "
           f"{summary.get('fail', 0)} fail · {summary.get('skip', 0)} n/a — "
           f"backend {escape(str(backend))} · checked {escape(str(generated_at))}")
    return (
        f'<div class="dh-banner" style="border-left:4px solid {colour};'
        f'background:{colour}14;">'
        f'<div class="dh-banner-status" style="color:{colour};">{glyph} '
        f'{escape(headline)}</div>'
        f'<div class="dh-banner-sub">{sub}</div></div>'
    )


def _render_report(data: dict) -> None:
    """Render a report dict (from report_to_dict) into the page. Streamlit-side; the
    HTML it emits comes entirely from the pure, escaped helpers above."""
    st.markdown(_dh_css(), unsafe_allow_html=True)
    st.markdown(
        _overall_banner_html(data["overall"], data["summary"], data["backend"],
                             data["generated_at"]),
        unsafe_allow_html=True)
    groups: "dict[str, list]" = {}
    for c in data["checks"]:
        groups.setdefault(c["group"], []).append(c)
    for group, checks in groups.items():
        st.markdown(_group_section_html(group, checks), unsafe_allow_html=True)


# ============================================================================
# Page layout (runs at import — Streamlit page convention)
# ============================================================================

@st.cache_data(ttl=60, show_spinner="Checking data health…")
def _load_report() -> dict:
    """Run the read-only engine and return the plain-dict report (cached 60s)."""
    return report_to_dict(run_health_checks())


@st.cache_data(ttl=600, show_spinner=False)
def _load_neon_usage() -> Optional[dict]:
    """Neon data-transfer usage via the control-plane API (cached 10 min).

    Returns None if no NEON_API_KEY is configured or the API is unreachable. The
    control-plane call does NOT count against the data-transfer quota it reports."""
    from src.config import config
    from src.monitoring.neon_usage import fetch_neon_usage
    try:
        limit = float(config.settings.health.neon.transfer_limit_gb)
    except Exception:
        limit = 5.0
    return fetch_neon_usage(limit_gb=limit)


def _neon_warn_pct() -> float:
    """Amber threshold (fraction of the allowance) from config, default 0.80."""
    try:
        from src.config import config
        return float(config.settings.health.neon.warn_pct)
    except Exception:
        return 0.80


# RBAC: owner-only page. It's hidden from the nav for viewers (dashboard.get_pages);
# this in-page gate is defence in depth in case the page is reached directly.
from src.auth import get_session_user_role  # noqa: E402

if get_session_user_role() != "owner":
    st.error("🔒 Data Health is restricted to the account owner.")
    st.stop()

st.markdown('<div class="bv-page-title">🩺 Data Health</div>', unsafe_allow_html=True)
st.caption(
    "A read-only check that the data is landing where it should — sources fresh, "
    "upcoming fixtures covered, standings tables fillable, and the pipeline running. "
    "Nothing here changes any data; it only looks."
)

_left, _right = st.columns([6, 1.4])
with _right:
    if st.button("↻ Refresh", use_container_width=True,
                 help="Re-run the checks now (otherwise cached for 60s)"):
        _load_report.clear()
        st.rerun()

try:
    _data = _load_report()
    _render_report(_data)
    # Cloud database (Neon) data-transfer headroom. The control-plane API call
    # does not count against the quota it reports, and degrades to an
    # 'unavailable' note if no NEON_API_KEY is configured.
    st.markdown(
        '<div class="dh-group"><div class="dh-group-title">Cloud Database</div>'
        + _neon_usage_html(_load_neon_usage(), _neon_warn_pct())
        + '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Amber = worth a look, red = needs action; “N/A” means a check doesn't apply "
        "right now (e.g. league sources are quiet in the off-season). The same check "
        "runs from a terminal any time with `make health`."
    )
except Exception as exc:  # pragma: no cover — defensive empty/error state
    st.error(f"Couldn't run the data-health check: {exc}")
