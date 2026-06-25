"""Neon data-transfer usage (Data Health page line).

Covers the read-only control-plane fetch (src/monitoring/neon_usage.py) and the
pure page helper _neon_usage_html (data_health.py, AST-exec'd since the page runs
st.* at import). The fetch must never raise, must return None without a key, and
must parse both account-key and project-scoped-key responses.
"""
from __future__ import annotations

import ast
from html import escape as _escape
from pathlib import Path
from typing import Optional as _Optional

ROOT = Path(__file__).resolve().parents[1]
DH_SRC = (ROOT / "src" / "delivery" / "views" / "data_health.py").read_text()


class FakeResp:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


def _load_neon_html():
    """Exec just the _neon_usage_html FunctionDef from the page (no st.* import)."""
    ns = {"escape": _escape, "Optional": _Optional}
    for node in ast.parse(DH_SRC).body:
        if isinstance(node, ast.FunctionDef) and node.name == "_neon_usage_html":
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<dh>", "exec"), ns)
    return ns["_neon_usage_html"]


# ---- module: fetch_neon_usage ---------------------------------------------

def test_fetch_returns_none_without_key(monkeypatch):
    import src.monitoring.neon_usage as nu
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    assert nu.fetch_neon_usage() is None


def test_fetch_account_key_parses_usage(monkeypatch):
    import src.monitoring.neon_usage as nu
    monkeypatch.setenv("NEON_API_KEY", "fake-key")
    proj = {
        "name": "Betvector", "data_transfer_bytes": 5_730_538_482,
        "consumption_period_start": "2026-06-01T00:00:00Z",
        "consumption_period_end": "2026-07-01T00:00:00Z",
    }
    monkeypatch.setattr(
        nu.requests, "get",
        lambda url, headers=None, timeout=None: FakeResp(200, {"projects": [proj]}),
    )
    u = nu.fetch_neon_usage(limit_gb=5)
    assert u is not None
    assert u["project_name"] == "Betvector"
    assert u["used_gb"] == 5.73
    assert round(u["pct"], 3) == 1.146
    assert u["limit_gb"] == 5.0
    assert u["reset_date"] == "2026-07-01"


def test_fetch_scoped_key_discovers_project(monkeypatch):
    import src.monitoring.neon_usage as nu
    monkeypatch.setenv("NEON_API_KEY", "fake-key")
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    proj = {"name": "Betvector", "data_transfer_bytes": 1_000_000_000,
            "consumption_period_end": "2026-07-01T00:00:00Z"}
    # Neon's scoped-key 404 body names the project id in ESCAPED quotes.
    err = '{"message":"not allowed ... subject_project_id:\\"fragrant-meadow-00076470\\""}'
    seen = []

    def fake_get(url, headers=None, timeout=None):
        seen.append(url)
        if url.endswith("/projects"):
            return FakeResp(404, text=err)
        return FakeResp(200, {"project": proj})

    monkeypatch.setattr(nu.requests, "get", fake_get)
    u = nu.fetch_neon_usage(limit_gb=5)
    assert u is not None and u["used_gb"] == 1.0
    assert any("fragrant-meadow-00076470" in url for url in seen), seen


def test_fetch_never_raises_on_network_error(monkeypatch):
    import src.monitoring.neon_usage as nu
    monkeypatch.setenv("NEON_API_KEY", "fake-key")

    def boom(*a, **k):
        raise nu.requests.RequestException("network down")

    monkeypatch.setattr(nu.requests, "get", boom)
    assert nu.fetch_neon_usage() is None


# ---- page helper: _neon_usage_html ----------------------------------------

def test_neon_html_unavailable_when_none():
    html = _load_neon_html()(None, 0.8)
    assert "unavailable" in html.lower()
    assert "NEON_API_KEY" in html


def test_neon_html_over_limit_is_red():
    u = {"used_gb": 5.73, "limit_gb": 5.0, "pct": 1.146,
         "reset_date": "2026-07-01", "days_until_reset": 5}
    html = _load_neon_html()(u, 0.8)
    assert "OVER" in html and "#F85149" in html
    assert "5.73 / 5 GB (115%)" in html
    assert "2026-07-01" in html


def test_neon_html_high_is_amber():
    u = {"used_gb": 4.5, "limit_gb": 5.0, "pct": 0.9,
         "reset_date": "2026-07-01", "days_until_reset": 5}
    html = _load_neon_html()(u, 0.8)
    assert "HIGH" in html and "#D29922" in html


def test_neon_html_under_warn_is_green():
    u = {"used_gb": 1.0, "limit_gb": 5.0, "pct": 0.2,
         "reset_date": "2026-07-01", "days_until_reset": 5}
    html = _load_neon_html()(u, 0.8)
    assert "OK" in html and "#3FB950" in html


def test_neon_html_escapes_dynamic_text():
    u = {"used_gb": 1.0, "limit_gb": 5.0, "pct": 0.2,
         "reset_date": "<script>", "days_until_reset": 1}
    html = _load_neon_html()(u, 0.8)
    assert "<script>" not in html and "&lt;script&gt;" in html
