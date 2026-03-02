"""
BetVector — Email Alerts Module (E11-02)
=========================================
Sends HTML emails using Gmail SMTP with Jinja2 templates.

Three scheduled email types:
1. **Morning Picks** (06:00 UTC) — Today's value bets with edge, odds, stakes.
2. **Evening Review** (22:00 UTC) — Today's results, P&L, tomorrow preview.
3. **Weekly Summary** (Sunday 20:00 UTC) — Week recap, model health, highlights.

Plus a generic ``send_alert()`` for retrain notifications and safety warnings.

Credentials are NEVER stored in code or YAML — they come from environment
variables (GMAIL_APP_PASSWORD, FROM_EMAIL) loaded at runtime.

Master Plan refs: MP §5 Architecture → Email, MP §3 Flows 1–3
"""

from __future__ import annotations

import logging
import os
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader

from src.config import config
from src.database.db import get_session
from src.database.models import (
    BetLog,
    League,
    Match,
    ModelPerformance,
    PipelineRun,
    Team,
    User,
    ValueBet,
)

logger = logging.getLogger(__name__)

# ============================================================================
# Template Engine
# ============================================================================
# Resolve the templates directory relative to the project root.
# config/email_config.yaml specifies paths like "templates/morning_picks.html"
# but Jinja2 just needs the directory.

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATE_DIR = _PROJECT_ROOT / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,  # HTML templates already have correct escaping
)


# ============================================================================
# SMTP Helpers
# ============================================================================

# Retry configuration for transient SMTP errors
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def _get_smtp_config() -> dict:
    """Load SMTP config from email_config.yaml and environment variables.

    Returns a dict with keys: host, port, use_tls, timeout, from_address,
    password, display_name.

    Raises ValueError if required environment variables are missing.
    """
    email_cfg = config.email

    # Connection settings from YAML
    smtp = email_cfg.smtp
    sender = email_cfg.sender

    # Credentials from environment variables — NEVER from config files
    from_address = os.environ.get(sender.from_address_env, "")
    password = os.environ.get(sender.app_password_env, "")

    if not from_address:
        raise ValueError(
            f"Environment variable '{sender.from_address_env}' is not set. "
            "Set it to the Gmail address used for sending BetVector emails."
        )
    if not password:
        raise ValueError(
            f"Environment variable '{sender.app_password_env}' is not set. "
            "Create a Gmail App Password and set it in your .env file."
        )

    return {
        "host": smtp.host,
        "port": smtp.port,
        "use_tls": smtp.use_tls,
        "timeout": smtp.timeout_seconds,
        "from_address": from_address,
        "password": password,
        "display_name": sender.display_name,
    }


def _send_email(
    to_address: str,
    subject: str,
    html_body: str,
    smtp_cfg: Optional[dict] = None,
) -> bool:
    """Send an HTML email via Gmail SMTP with TLS.

    Retries up to MAX_RETRIES times on transient SMTP errors.

    Args:
        to_address: Recipient email address.
        subject: Email subject line.
        html_body: Rendered HTML content.
        smtp_cfg: Optional pre-loaded SMTP config (avoids re-reading for bulk).

    Returns:
        True if email was sent successfully, False otherwise.
    """
    if smtp_cfg is None:
        smtp_cfg = _get_smtp_config()

    # Build the MIME message
    msg = MIMEMultipart("alternative")
    msg["From"] = f'{smtp_cfg["display_name"]} <{smtp_cfg["from_address"]}>'
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Connect with TLS (port 587 + STARTTLS)
            server = smtplib.SMTP(
                smtp_cfg["host"],
                smtp_cfg["port"],
                timeout=smtp_cfg["timeout"],
            )
            server.ehlo()
            if smtp_cfg["use_tls"]:
                server.starttls()
                server.ehlo()
            server.login(smtp_cfg["from_address"], smtp_cfg["password"])
            server.sendmail(
                smtp_cfg["from_address"],
                [to_address],
                msg.as_string(),
            )
            server.quit()
            logger.info(
                "Email sent successfully to %s (subject: %s) on attempt %d",
                to_address, subject, attempt,
            )
            return True

        except smtplib.SMTPException as exc:
            last_error = exc
            logger.warning(
                "SMTP error on attempt %d/%d for %s: %s",
                attempt, MAX_RETRIES, to_address, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)

        except OSError as exc:
            # Network errors (timeout, connection refused, etc.)
            last_error = exc
            logger.warning(
                "Network error on attempt %d/%d for %s: %s",
                attempt, MAX_RETRIES, to_address, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)

    logger.error(
        "Failed to send email to %s after %d attempts. Last error: %s",
        to_address, MAX_RETRIES, last_error,
    )
    return False


# ============================================================================
# Data Loaders — query DB for template variables
# ============================================================================

def _load_todays_picks(user_id: int) -> tuple[list[dict], int]:
    """Load today's value bets for the morning picks email.

    Returns (picks_list, pick_count) where picks_list contains dicts
    matching the morning_picks.html template variables.
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")

    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            return [], 0

        # Use aliased Team for home/away joins to avoid ambiguous column error
        from sqlalchemy.orm import aliased

        HomeTeam = aliased(Team)
        AwayTeam = aliased(Team)

        value_bets = (
            session.query(ValueBet, Match, HomeTeam, AwayTeam, League)
            .join(Match, ValueBet.match_id == Match.id)
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .join(League, Match.league_id == League.id)
            .filter(Match.date == today)
            .order_by(ValueBet.edge.desc())
            .all()
        )

        picks = []
        for vb, match, home, away, league in value_bets:
            # Calculate stake based on user settings
            if user.staking_method == "kelly":
                # Quarter-Kelly: (edge / (odds - 1)) * kelly_fraction * bankroll
                if vb.bookmaker_odds > 1:
                    kelly_stake = (
                        (vb.edge / (vb.bookmaker_odds - 1))
                        * user.kelly_fraction
                        * user.current_bankroll
                    )
                    stake = max(0, round(kelly_stake, 2))
                else:
                    stake = 0.0
            else:
                # Flat or percentage staking
                stake = round(
                    user.current_bankroll * user.stake_percentage, 2
                )

            picks.append({
                "home_team": home.name,
                "away_team": away.name,
                "league": league.name,
                "market": vb.market_type,
                "selection": vb.selection,
                "probability": vb.model_prob,
                "odds": vb.bookmaker_odds,
                "implied_prob": vb.implied_prob,
                "edge": vb.edge,
                "confidence": vb.confidence,
                "stake": stake,
                "explanation": vb.explanation or "",
            })

        return picks, len(picks)


def _load_todays_results(user_id: int) -> dict:
    """Load today's settled bets for the evening review email.

    Returns a dict with all template variables for evening_review.html.
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")
    week_start = (
        datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())
    ).strftime("%Y-%m-%d")
    month_start = datetime.utcnow().replace(day=1).strftime("%Y-%m-%d")

    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            return {}

        # Today's resolved bets
        bets = (
            session.query(BetLog)
            .filter(
                BetLog.user_id == user_id,
                BetLog.date == today,
                BetLog.bet_type == "system_pick",
            )
            .all()
        )

        results = []
        daily_pnl = 0.0
        daily_wins = 0
        daily_losses = 0
        daily_pending = 0

        for bet in bets:
            results.append({
                "home_team": bet.home_team,
                "away_team": bet.away_team,
                "league": bet.league,
                "market": bet.market_type,
                "selection": bet.selection,
                "result": bet.status,
                "odds": bet.odds_at_detection,
                "stake": bet.stake,
                "pnl": bet.pnl or 0.0,
            })

            if bet.status == "won":
                daily_wins += 1
                daily_pnl += bet.pnl or 0.0
            elif bet.status == "lost":
                daily_losses += 1
                daily_pnl += bet.pnl or 0.0
            elif bet.status == "pending":
                daily_pending += 1

        # Weekly P&L — sum of all settled bets this week
        from sqlalchemy import func

        weekly_pnl = (
            session.query(func.coalesce(func.sum(BetLog.pnl), 0.0))
            .filter(
                BetLog.user_id == user_id,
                BetLog.bet_type == "system_pick",
                BetLog.status.in_(["won", "lost"]),
                BetLog.date >= week_start,
            )
            .scalar()
        ) or 0.0

        # Monthly ROI — total P&L / total stakes this month
        monthly_pnl = (
            session.query(func.coalesce(func.sum(BetLog.pnl), 0.0))
            .filter(
                BetLog.user_id == user_id,
                BetLog.bet_type == "system_pick",
                BetLog.status.in_(["won", "lost"]),
                BetLog.date >= month_start,
            )
            .scalar()
        ) or 0.0

        monthly_stakes = (
            session.query(func.coalesce(func.sum(BetLog.stake), 0.0))
            .filter(
                BetLog.user_id == user_id,
                BetLog.bet_type == "system_pick",
                BetLog.status.in_(["won", "lost"]),
                BetLog.date >= month_start,
            )
            .scalar()
        ) or 0.0

        monthly_roi = monthly_pnl / monthly_stakes if monthly_stakes > 0 else 0.0

        # Tomorrow's fixtures
        tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow_matches = (
            session.query(Match, League)
            .join(League, Match.league_id == League.id)
            .filter(Match.date == tomorrow)
            .all()
        )
        tomorrow_fixtures = len(tomorrow_matches)
        tomorrow_leagues = ", ".join(
            sorted({lg.short_name for _, lg in tomorrow_matches})
        )

        # Check if all bets lost — show variance message
        all_lost_msg = None
        settled = [b for b in bets if b.status in ("won", "lost")]
        if settled and all(b.status == "lost" for b in settled):
            all_lost_msg = (
                "Variance happens. The model's edge is measured over "
                "hundreds of bets, not individual days. Stay disciplined."
            )

        return {
            "results": results,
            "daily_pnl": daily_pnl,
            "daily_wins": daily_wins,
            "daily_losses": daily_losses,
            "daily_pending": daily_pending,
            "weekly_pnl": weekly_pnl,
            "monthly_roi": monthly_roi,
            "current_bankroll": user.current_bankroll,
            "tomorrow_fixtures": tomorrow_fixtures,
            "tomorrow_leagues": tomorrow_leagues,
            "all_lost_msg": all_lost_msg,
        }


def _load_weekly_data(user_id: int) -> dict:
    """Load the week's data for the weekly summary email.

    Returns a dict with all template variables for weekly_summary.html.
    """
    from sqlalchemy import func

    now = datetime.utcnow()
    # Week = Mon–Sun. Get the Monday of this week.
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    week_end = now.strftime("%Y-%m-%d")
    month_start = now.replace(day=1).strftime("%Y-%m-%d")

    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            return {}

        # --- Core stats ---
        bets = (
            session.query(BetLog)
            .filter(
                BetLog.user_id == user_id,
                BetLog.bet_type == "system_pick",
                BetLog.date >= week_start,
                BetLog.date <= week_end,
            )
            .all()
        )

        settled = [b for b in bets if b.status in ("won", "lost")]
        wins = sum(1 for b in settled if b.status == "won")
        losses = sum(1 for b in settled if b.status == "lost")
        pending = sum(1 for b in bets if b.status == "pending")
        total_bets = wins + losses
        win_rate = wins / total_bets if total_bets > 0 else 0.0

        weekly_pnl = sum(b.pnl or 0.0 for b in settled)
        weekly_stakes = sum(b.stake for b in settled)
        weekly_roi = weekly_pnl / weekly_stakes if weekly_stakes > 0 else 0.0

        # Bankroll at start of week (use the earliest bankroll_before this week)
        first_bet = (
            session.query(BetLog)
            .filter(
                BetLog.user_id == user_id,
                BetLog.date >= week_start,
                BetLog.bankroll_before.isnot(None),
            )
            .order_by(BetLog.date, BetLog.id)
            .first()
        )
        bankroll_start = (
            first_bet.bankroll_before if first_bet else user.current_bankroll
        )
        bankroll_end = user.current_bankroll
        bankroll_change = bankroll_end - bankroll_start

        # Cumulative ROI (all-time)
        all_pnl = (
            session.query(func.coalesce(func.sum(BetLog.pnl), 0.0))
            .filter(
                BetLog.user_id == user_id,
                BetLog.bet_type == "system_pick",
                BetLog.status.in_(["won", "lost"]),
            )
            .scalar()
        ) or 0.0
        all_stakes = (
            session.query(func.coalesce(func.sum(BetLog.stake), 0.0))
            .filter(
                BetLog.user_id == user_id,
                BetLog.bet_type == "system_pick",
                BetLog.status.in_(["won", "lost"]),
            )
            .scalar()
        ) or 0.0
        cumulative_roi = all_pnl / all_stakes if all_stakes > 0 else 0.0

        # --- Daily breakdown (Mon–Sun) ---
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        daily_breakdown = []
        for i, day_name in enumerate(day_names):
            day_date = (
                datetime.strptime(week_start, "%Y-%m-%d") + timedelta(days=i)
            ).strftime("%Y-%m-%d")

            day_bets = [
                b for b in settled if b.date == day_date
            ]
            day_pnl = sum(b.pnl or 0.0 for b in day_bets)
            daily_breakdown.append({
                "day": day_name,
                "pnl": day_pnl,
                "bets": len(day_bets),
            })

        # --- Best and worst picks ---
        best_pick = None
        worst_pick = None

        won_bets = [b for b in settled if b.status == "won"]
        lost_bets = [b for b in settled if b.status == "lost"]

        if won_bets:
            best = max(won_bets, key=lambda b: b.edge)
            best_pick = {
                "home_team": best.home_team,
                "away_team": best.away_team,
                "league": best.league,
                "market": best.market_type,
                "selection": best.selection,
                "edge": best.edge,
                "odds": best.odds_at_detection,
                "pnl": best.pnl or 0.0,
            }

        if lost_bets:
            # Worst pick = highest confidence that lost
            worst = max(lost_bets, key=lambda b: b.edge)
            worst_pick = {
                "home_team": worst.home_team,
                "away_team": worst.away_team,
                "league": worst.league,
                "market": worst.market_type,
                "selection": worst.selection,
                "edge": worst.edge,
                "odds": worst.odds_at_detection,
                "pnl": worst.pnl or 0.0,
            }

        # --- Model health snapshot ---
        # Get the most recent model performance record
        latest_perf = (
            session.query(ModelPerformance)
            .order_by(ModelPerformance.computed_at.desc())
            .first()
        )

        brier_score = (
            latest_perf.brier_score
            if latest_perf and latest_perf.brier_score is not None
            else 0.25
        )
        # Determine Brier trend by comparing to prior evaluation
        prior_perf = (
            session.query(ModelPerformance)
            .order_by(ModelPerformance.computed_at.desc())
            .offset(1)
            .first()
        )
        if (
            prior_perf
            and latest_perf
            and latest_perf.brier_score is not None
            and prior_perf.brier_score is not None
        ):
            if latest_perf.brier_score < prior_perf.brier_score - 0.005:
                brier_trend = "improving"
            elif latest_perf.brier_score > prior_perf.brier_score + 0.005:
                brier_trend = "declining"
            else:
                brier_trend = "stable"
        else:
            brier_trend = "stable"

        # Calibration status — derive from calibration_json if available.
        # calibration_json stores per-bin accuracy data; we compute the mean
        # absolute calibration error across bins.
        import json as _json

        calibration_status = "well_calibrated"
        if latest_perf and latest_perf.calibration_json:
            try:
                cal_data = _json.loads(latest_perf.calibration_json)
                # Each bin: {"predicted": 0.525, "actual": 0.51, "count": 40}
                errors = [
                    v["predicted"] - v["actual"]
                    for v in cal_data.values()
                    if isinstance(v, dict) and "predicted" in v and "actual" in v
                ]
                if errors:
                    mean_error = sum(errors) / len(errors)
                    if mean_error > 0.03:
                        calibration_status = "overconfident"
                    elif mean_error < -0.03:
                        calibration_status = "underconfident"
            except (ValueError, KeyError, TypeError):
                pass  # Keep default "well_calibrated" on parse errors

        # CLV (closing line value) — average edge at close vs detection
        clv_bets = [
            b for b in settled
            if b.odds_at_placement and b.odds_at_detection
        ]
        if clv_bets:
            # CLV = how much our detection odds beat closing odds, on average
            clv_values = [
                ((1 / b.odds_at_detection) - (1 / b.odds_at_placement)) * 100
                for b in clv_bets
                if b.odds_at_placement > 0 and b.odds_at_detection > 0
            ]
            clv_mean = sum(clv_values) / len(clv_values) if clv_values else 0.0
        else:
            clv_mean = 0.0

        # CLV trend — compare this week's avg to last week's
        clv_trend = "flat"
        if clv_mean > 1.0:
            clv_trend = "positive"
        elif clv_mean < -1.0:
            clv_trend = "negative"

        # --- Next week preview ---
        next_monday = (
            datetime.strptime(week_start, "%Y-%m-%d") + timedelta(days=7)
        ).strftime("%Y-%m-%d")
        next_sunday = (
            datetime.strptime(week_start, "%Y-%m-%d") + timedelta(days=13)
        ).strftime("%Y-%m-%d")

        next_week_matches = (
            session.query(Match, League)
            .join(League, Match.league_id == League.id)
            .filter(Match.date >= next_monday, Match.date <= next_sunday)
            .all()
        )
        next_week_fixtures = len(next_week_matches)
        next_week_leagues = ", ".join(
            sorted({lg.short_name for _, lg in next_week_matches})
        )

        return {
            "total_bets": total_bets,
            "wins": wins,
            "losses": losses,
            "pending": pending,
            "win_rate": win_rate,
            "weekly_pnl": weekly_pnl,
            "weekly_roi": weekly_roi,
            "cumulative_roi": cumulative_roi,
            "bankroll_start": bankroll_start,
            "bankroll_end": bankroll_end,
            "bankroll_change": bankroll_change,
            "daily_breakdown": daily_breakdown,
            "best_pick": best_pick,
            "worst_pick": worst_pick,
            "brier_score": brier_score,
            "brier_trend": brier_trend,
            "calibration_status": calibration_status,
            "clv_mean": clv_mean,
            "clv_trend": clv_trend,
            "next_week_fixtures": next_week_fixtures,
            "next_week_leagues": next_week_leagues,
        }


# ============================================================================
# Public API — Send Functions
# ============================================================================

def _get_user_email(user_id: int) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Get user's email, name, and edge threshold.

    Returns (email, name, edge_threshold) or (None, None, None) if user not found.
    """
    with get_session() as session:
        user = session.get(User, user_id)
        if not user or not user.email or not user.is_active:
            return None, None, None
        return user.email, user.name, str(user.edge_threshold)


def _get_dashboard_url() -> str:
    """Get the dashboard URL from settings or fall back to localhost."""
    try:
        return getattr(config.settings, "dashboard_url", "http://localhost:8501")
    except AttributeError:
        return "http://localhost:8501"


def send_morning_picks(user_id: int = 1) -> bool:
    """Send the morning picks email with today's value bets.

    Renders the morning_picks.html template with today's value bets
    from the database and sends it to the user's configured email address.

    Args:
        user_id: The user to send to (default: owner, id=1).

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    email, name, edge_threshold = _get_user_email(user_id)
    if not email:
        logger.warning("No email configured for user %d — skipping morning picks.", user_id)
        return False

    picks, pick_count = _load_todays_picks(user_id)
    today_str = datetime.utcnow().strftime("%A %d %b %Y")
    dashboard_url = _get_dashboard_url()

    # Determine leagues for subject line
    leagues = ", ".join(sorted({p["league"] for p in picks})) if picks else "No picks"

    # Render template
    template = _jinja_env.get_template("morning_picks.html")
    html_body = template.render(
        date=today_str,
        user_name=name,
        picks=picks,
        pick_count=pick_count,
        no_picks_msg=None,
        edge_threshold=float(edge_threshold) if edge_threshold else 0.05,
        dashboard_url=dashboard_url,
    )

    # Format subject line from config template
    subject_tpl = config.email.schedule.morning_picks.subject_template
    subject = subject_tpl.format(
        pick_count=pick_count,
        leagues=leagues,
    )

    success = _send_email(email, subject, html_body)

    if success:
        logger.info("Morning picks email sent to %s (%d picks).", email, pick_count)
    else:
        logger.error("Failed to send morning picks email to %s.", email)

    return success


def send_evening_review(user_id: int = 1) -> bool:
    """Send the evening review email with today's results and P&L.

    Renders the evening_review.html template with today's bet results,
    daily/weekly/monthly stats, and a tomorrow preview.

    Args:
        user_id: The user to send to (default: owner, id=1).

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    email, name, _ = _get_user_email(user_id)
    if not email:
        logger.warning("No email configured for user %d — skipping evening review.", user_id)
        return False

    data = _load_todays_results(user_id)
    if not data:
        logger.warning("No data loaded for user %d — skipping evening review.", user_id)
        return False

    today_str = datetime.utcnow().strftime("%A %d %b %Y")
    dashboard_url = _get_dashboard_url()

    # Render template
    template = _jinja_env.get_template("evening_review.html")
    html_body = template.render(
        date=today_str,
        user_name=name,
        dashboard_url=dashboard_url,
        **data,
    )

    # Format subject line
    pnl = data["daily_pnl"]
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    wins = data["daily_wins"]
    total = data["daily_wins"] + data["daily_losses"]

    subject_tpl = config.email.schedule.evening_review.subject_template
    subject = subject_tpl.format(
        pnl=pnl_str,
        wins=wins,
        total=total,
    )

    success = _send_email(email, subject, html_body)

    if success:
        logger.info("Evening review email sent to %s (P&L: %s).", email, pnl_str)
    else:
        logger.error("Failed to send evening review email to %s.", email)

    return success


def send_weekly_summary(user_id: int = 1) -> bool:
    """Send the weekly summary email with the week's performance recap.

    Renders the weekly_summary.html template with weekly stats, best/worst
    picks, model health snapshot, and next week preview.

    Args:
        user_id: The user to send to (default: owner, id=1).

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    email, name, _ = _get_user_email(user_id)
    if not email:
        logger.warning("No email configured for user %d — skipping weekly summary.", user_id)
        return False

    data = _load_weekly_data(user_id)
    if not data:
        logger.warning("No data loaded for user %d — skipping weekly summary.", user_id)
        return False

    # Week label: "Week of 23 Feb – 1 Mar 2026"
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6)
    week_label = (
        f"Week of {week_start.strftime('%-d %b')} – "
        f"{week_end.strftime('%-d %b %Y')}"
    )

    dashboard_url = _get_dashboard_url()

    # Render template
    template = _jinja_env.get_template("weekly_summary.html")
    html_body = template.render(
        week_label=week_label,
        user_name=name,
        dashboard_url=dashboard_url,
        **data,
    )

    # Format subject line
    weekly_pnl = data["weekly_pnl"]
    pnl_str = f"+${weekly_pnl:.2f}" if weekly_pnl >= 0 else f"-${abs(weekly_pnl):.2f}"
    roi = data["weekly_roi"] * 100

    subject_tpl = config.email.schedule.weekly_summary.subject_template
    subject = subject_tpl.format(
        weekly_pnl=pnl_str,
        roi=f"{roi:+.1f}",
    )

    success = _send_email(email, subject, html_body)

    if success:
        logger.info("Weekly summary email sent to %s (P&L: %s).", email, pnl_str)
    else:
        logger.error("Failed to send weekly summary email to %s.", email)

    return success


def send_alert(
    user_id: int,
    subject: str,
    body: str,
) -> bool:
    """Send a generic alert email (retrain notifications, safety warnings, etc.).

    This is a simple wrapper around _send_email for non-templated alerts.
    The body should be plain HTML.

    Args:
        user_id: The user to send to.
        subject: Email subject line.
        body: HTML body content.

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    email, name, _ = _get_user_email(user_id)
    if not email:
        logger.warning("No email configured for user %d — skipping alert.", user_id)
        return False

    # Wrap the body in a minimal BetVector-styled HTML wrapper
    html_body = f"""<!DOCTYPE html>
<html><body style="margin:0; padding:0; background-color:#0D1117;
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
style="background-color:#0D1117;">
<tr><td align="center" style="padding:24px 16px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
style="max-width:600px; width:100%; background-color:#161B22;
border-radius:8px; padding:24px;">
<tr><td>
<h2 style="margin:0 0 16px; color:#E6EDF3; font-size:18px;">
BetVector Alert
</h2>
<div style="color:#E6EDF3; font-size:14px; line-height:1.6;">
{body}
</div>
<p style="margin:24px 0 0; font-size:11px; color:#484F58;">
BetVector &middot; This is an automated alert.
</p>
</td></tr>
</table>
</td></tr>
</table>
</body></html>"""

    success = _send_email(email, f"BetVector Alert — {subject}", html_body)

    if success:
        logger.info("Alert email sent to %s (subject: %s).", email, subject)
    else:
        logger.error("Failed to send alert to %s (subject: %s).", email, subject)

    return success


# ============================================================================
# Pipeline Integration Helper
# ============================================================================

def increment_emails_sent(pipeline_run_id: int, count: int = 1) -> None:
    """Increment the emails_sent counter on a pipeline_runs record.

    Called by the pipeline orchestrator after each successful email send
    so the run summary shows how many emails went out.

    Args:
        pipeline_run_id: The pipeline_runs.id to update.
        count: Number of emails to add (default: 1).
    """
    try:
        with get_session() as session:
            run = session.get(PipelineRun, pipeline_run_id)
            if run:
                run.emails_sent = (run.emails_sent or 0) + count
                session.commit()
    except Exception as exc:
        logger.warning(
            "Failed to update emails_sent for pipeline run %d: %s",
            pipeline_run_id, exc,
        )
