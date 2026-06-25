"""
BetVector — Data Health alert (DH-04)
=====================================
Runs the read-only health engine at the end of the morning pipeline and emails the owner
when something needs attention (overall verdict at or above the configured severity —
default WARN, so genuine issues like stale standings stubs reach the owner).

Designed for pipeline resilience (CLAUDE.md Rule 6): `run_and_alert` NEVER raises — a
health-check or email failure must not break the pipeline. The send function and owner id
are injectable so the alert logic is unit-testable without sending real email.
"""

from __future__ import annotations

from html import escape
from typing import Callable, Optional

from src.monitoring.health_check import (
    FAIL, WARN, _RANK, HealthReport, resolve_config, run_health_checks,
)


def _alert_worthy(overall: str, min_status: str) -> bool:
    """True when the overall verdict is at least as severe as ``min_status``."""
    return _RANK.get(overall, 0) >= _RANK.get(min_status, _RANK[WARN])


def build_alert_subject(report: HealthReport) -> str:
    s = report.summary()
    return (f"BetVector Data Health: {report.overall.upper()} "
            f"— {s.get(FAIL, 0)} fail, {s.get(WARN, 0)} warn")


def build_alert_body_html(report: HealthReport) -> str:
    """A compact, escaped HTML body listing the failing/warning checks (worst first).
    Plugs into email_alerts.send_alert, which wraps it in the BetVector shell."""
    fails = [c for c in report.checks if c.status == FAIL]
    warns = [c for c in report.checks if c.status == WARN]

    def _items(checks) -> str:
        return "".join(
            f'<li style="margin-bottom:6px;"><strong>{escape(c.name)}</strong> '
            f'<span style="color:#8B949E;">({escape(c.group)})</span><br>'
            f'<span style="color:#8B949E;font-size:13px;">{escape(c.detail)}</span></li>'
            for c in checks)

    parts = [
        f'<p>The morning data-health check came back <strong>{escape(report.overall.upper())}'
        f'</strong> (backend {escape(report.backend)}, {escape(report.generated_at)}).</p>'
    ]
    if fails:
        parts.append('<p style="color:#F85149;"><strong>Problems</strong></p>'
                     f'<ul>{_items(fails)}</ul>')
    if warns:
        parts.append('<p style="color:#D29922;"><strong>Worth a look</strong></p>'
                     f'<ul>{_items(warns)}</ul>')
    parts.append('<p style="font-size:12px;color:#8B949E;">Full report any time: the '
                 '🩺 Data Health page in the dashboard, or <code>make health</code>.</p>')
    return "".join(parts)


def _resolve_owner_id() -> int:
    """The owner's user id (role='owner'), falling back to 1 (the default owner)."""
    try:
        from src.database.db import get_session
        from src.database.models import User
        with get_session() as session:
            owner = session.query(User).filter(
                User.role == "owner").order_by(User.id).first()
            if owner is not None:
                return owner.id
    except Exception:
        pass
    return 1


def run_and_alert(
    send_alert_fn: Optional[Callable[[int, str, str], bool]] = None,
    user_id: Optional[int] = None,
    report: Optional[HealthReport] = None,
    config_override: Optional[dict] = None,
) -> dict:
    """Run the health check (or use an injected ``report``) and email the owner if the
    verdict is alert-worthy. Returns a small summary; never raises.

    Parameters are injectable for testing: ``send_alert_fn(user_id, subject, body)`` (the
    real one is ``email_alerts.send_alert``), ``user_id`` (defaults to the resolved
    owner), and a prebuilt ``report``."""
    summary = {"overall": "unknown", "alerted": False, "sent": False,
               "n_fail": 0, "n_warn": 0}
    try:
        if report is None:
            report = run_health_checks(config_override=config_override)
        counts = report.summary()
        summary.update(overall=report.overall, n_fail=counts.get(FAIL, 0),
                       n_warn=counts.get(WARN, 0))

        cfg = resolve_config(config_override)
        if not _alert_worthy(report.overall, cfg["alert"]["min_status"]):
            return summary
        summary["alerted"] = True

        if send_alert_fn is None:
            from src.delivery.email_alerts import send_alert as send_alert_fn
        if user_id is None:
            user_id = _resolve_owner_id()

        summary["sent"] = bool(send_alert_fn(
            user_id, build_alert_subject(report), build_alert_body_html(report)))
    except Exception as exc:  # pipeline resilience: never break the run
        import logging
        logging.getLogger(__name__).warning(
            "Data-health alert failed (non-fatal): %s", exc)
    return summary
