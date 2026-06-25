"""BETVECTOR_FORCE_LOCAL_DB override — keep analytics/previews off Neon.

When the flag is truthy, _build_connection_url must return the local SQLite URL
even if DATABASE_URL (Neon) is set, so backtests / preview servers / ad-hoc
scripts never consume Neon data-transfer quota. When unset/falsy, DATABASE_URL
must still win (production behaviour unchanged).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.db import _build_connection_url

_FAKE_NEON = "postgresql://u:p@ep-fake.neon.tech/db?sslmode=require"


def test_force_local_overrides_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _FAKE_NEON)
    monkeypatch.setenv("BETVECTOR_FORCE_LOCAL_DB", "1")
    url = _build_connection_url()
    assert url.startswith("sqlite:///"), f"expected local sqlite, got {url}"
    assert "neon.tech" not in url


def test_without_flag_database_url_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _FAKE_NEON)
    monkeypatch.delenv("BETVECTOR_FORCE_LOCAL_DB", raising=False)
    assert _build_connection_url() == _FAKE_NEON


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", "On"])
def test_truthy_variants_force_local(monkeypatch, val):
    monkeypatch.setenv("DATABASE_URL", _FAKE_NEON)
    monkeypatch.setenv("BETVECTOR_FORCE_LOCAL_DB", val)
    assert _build_connection_url().startswith("sqlite:///")


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off"])
def test_falsy_variants_do_not_force_local(monkeypatch, val):
    monkeypatch.setenv("DATABASE_URL", _FAKE_NEON)
    monkeypatch.setenv("BETVECTOR_FORCE_LOCAL_DB", val)
    assert _build_connection_url() == _FAKE_NEON
