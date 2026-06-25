"""DH-02 — Data Health CLI (pure formatter + dict + exit codes + entrypoint)."""

from __future__ import annotations

import json

from src.monitoring.health_check import CheckResult, HealthReport, FAIL, OK, SKIP, WARN
from src.monitoring import health_cli
from src.monitoring.health_cli import (
    exit_code, format_report, main, report_to_dict,
)


def _report(overall=WARN):
    return HealthReport("2026-06-24T12:00:00", "postgresql", overall, [
        CheckResult("Connectivity", "Database reachable", OK, "SELECT 1 succeeded."),
        CheckResult("Standings integrity", "Stale scheduled stubs (leagues)", WARN,
                    "2 past-dated fixtures still scheduled.", value=2),
        CheckResult("Source freshness", "Bookmaker odds", SKIP,
                    "off-season, staleness expected."),
    ])


def test_format_report_is_grouped_and_plain_without_colour():
    out = format_report(_report())
    assert "BetVector — Data Health" in out
    assert "backend=postgresql" in out and "Overall: WARN" in out
    # group headers
    for g in ("Connectivity", "Standings integrity", "Source freshness"):
        assert g in out
    # check name + detail surface
    assert "Stale scheduled stubs (leagues)" in out
    assert "2 past-dated fixtures still scheduled." in out
    # summary counts
    assert "ok 1" in out and "warn 1" in out and "skip 1" in out
    # no ANSI escapes when color is off
    assert "\033[" not in out


def test_format_report_adds_ansi_when_colour_on():
    assert "\033[" in format_report(_report(), color=True)


def test_report_to_dict_is_json_serialisable():
    d = report_to_dict(_report())
    assert d["backend"] == "postgresql" and d["overall"] == "warn"
    assert d["summary"]["warn"] == 1 and len(d["checks"]) == 3
    stub = next(c for c in d["checks"] if c["name"].startswith("Stale"))
    assert stub["value"] == 2 and stub["status"] == "warn"
    json.dumps(d)  # must not raise


def test_exit_code_semantics():
    assert exit_code(_report(OK)) == 0
    assert exit_code(_report(WARN)) == 0            # warnings don't fail by default
    assert exit_code(_report(WARN), strict=True) == 1
    assert exit_code(_report(FAIL)) == 1
    assert exit_code(_report(FAIL), strict=True) == 1


def test_main_text_output_and_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(health_cli, "run_health_checks", lambda: _report(FAIL))
    rc = main(["--no-color"])
    out = capsys.readouterr().out
    assert "BetVector — Data Health" in out
    assert rc == 1                                  # FAIL → non-zero


def test_main_json_output(monkeypatch, capsys):
    monkeypatch.setattr(health_cli, "run_health_checks", lambda: _report(OK))
    rc = main(["--json"])
    payload = json.loads(capsys.readouterr().out)   # valid JSON
    assert payload["overall"] == "ok" and rc == 0
    assert {"group", "name", "status", "detail"} <= set(payload["checks"][0])


def test_main_strict_fails_on_warn(monkeypatch, capsys):
    monkeypatch.setattr(health_cli, "run_health_checks", lambda: _report(WARN))
    assert main(["--no-color"]) == 0
    monkeypatch.setattr(health_cli, "run_health_checks", lambda: _report(WARN))
    assert main(["--no-color", "--strict"]) == 1
