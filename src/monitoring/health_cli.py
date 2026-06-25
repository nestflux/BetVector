"""
BetVector — Data Health CLI (DH-02)
===================================
Turns a :class:`~src.monitoring.health_check.HealthReport` into a terminal report
(`make health` / `python scripts/health_check.py`) and a machine-readable JSON dump.

The formatter is pure (report → string), so it's unit-testable without a database.
``main()`` wraps it: load .env, run the read-only engine, print, and exit non-zero on
any FAIL (``--strict`` also fails on WARN) so the check can gate a pipeline or CI step.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from src.monitoring.health_check import (
    FAIL, OK, SKIP, WARN, HealthReport, run_health_checks,
)

_GLYPH = {OK: "✓", WARN: "⚠", FAIL: "✗", SKIP: "·"}
_LABEL = {OK: "OK", WARN: "WARN", FAIL: "FAIL", SKIP: "SKIP"}
_ANSI = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", SKIP: "\033[90m"}
_RESET = "\033[0m"
_BOLD = "\033[1m"


def report_to_dict(report: HealthReport) -> dict:
    """The report as a plain JSON-serialisable dict (for ``--json`` / automation)."""
    return {
        "generated_at": report.generated_at,
        "backend": report.backend,
        "overall": report.overall,
        "summary": report.summary(),
        "checks": [
            {"group": c.group, "name": c.name, "status": c.status,
             "detail": c.detail, "value": c.value, "threshold": c.threshold}
            for c in report.checks
        ],
    }


def exit_code(report: HealthReport, strict: bool = False) -> int:
    """0 when healthy; 1 on any FAIL (or, with ``strict``, on any WARN too)."""
    if report.overall == FAIL:
        return 1
    if strict and report.overall == WARN:
        return 1
    return 0


def _c(text: str, status: str, color: bool) -> str:
    return f"{_ANSI[status]}{text}{_RESET}" if color else text


def format_report(report: HealthReport, color: bool = False) -> str:
    """Render the report as a grouped, aligned PASS/WARN/FAIL text block. Pure."""
    s = report.summary()
    head = _BOLD if color else ""
    reset = _RESET if color else ""
    lines = [
        f"{head}BetVector — Data Health{reset}",
        f"  generated {report.generated_at}   backend={report.backend}",
        f"  Overall: {_c(_LABEL[report.overall], report.overall, color)}"
        f"   (ok {s[OK]} · warn {s[WARN]} · fail {s[FAIL]} · skip {s[SKIP]})",
        "─" * 72,
    ]
    for group, checks in report.by_group().items():
        lines.append(f"{head}{group}{reset}")
        for c in checks:
            glyph = _c(f"{_GLYPH[c.status]} {_LABEL[c.status]:4}", c.status, color)
            lines.append(f"  {glyph}  {c.name}")
            lines.append(f"          {c.detail}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="health_check",
        description="BetVector read-only data-health check.")
    parser.add_argument("--json", action="store_true",
                        help="emit the report as JSON instead of text")
    parser.add_argument("--no-color", action="store_true",
                        help="disable ANSI colour in the text report")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero on WARN as well as FAIL")
    args = parser.parse_args(argv)

    # Load .env so an ad-hoc run reaches the cloud (Neon) DB rather than local SQLite.
    try:
        from dotenv import load_dotenv
        from src.config import PROJECT_ROOT
        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:
        pass

    report = run_health_checks()

    if args.json:
        print(json.dumps(report_to_dict(report), indent=2))
    else:
        color = (not args.no_color) and sys.stdout.isatty()
        print(format_report(report, color=color))
    return exit_code(report, strict=args.strict)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
