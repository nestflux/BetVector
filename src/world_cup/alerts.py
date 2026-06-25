"""
BetVector World Cup 2026 — Email Alerts (WC-05-02)
====================================================
Morning and evening WC email alerts reusing the existing Gmail SMTP
infrastructure from src/delivery/email_alerts.py.

Morning email (match days): predictions, value bets, group standings.
Evening email (match days): results vs predictions, updated Elo, accuracy.
No email sent on days without WC matches.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select

from src.database.db import get_session
from html import escape

from src.delivery.email_alerts import _get_user_email, _send_email
from src.world_cup.calibration import compute_model_accuracy, update_tournament_elo
from src.world_cup.models import WCMatch, WCPrediction, WCTeam, WCValueBet
from src.world_cup.predictor import MODEL_NAME
from src.world_cup.value_finder import find_wc_value_bets

logger = logging.getLogger(__name__)

# BetVector dark theme (CLAUDE.md Rule 5)
BG = "#0D1117"
SURFACE = "#161B22"
TEXT = "#E6EDF3"
TEXT_DIM = "#8B949E"
GREEN = "#3FB950"
RED = "#F85149"
YELLOW = "#D29922"
BORDER = "#30363D"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', 'Fira Code', Consolas, monospace"


def _get_today_str() -> str:
    return date.today().isoformat()


def _previous_date(target_date: str | None) -> str:
    """ISO date for the day before target_date (or before today). Used to fold
    yesterday's results into the morning digest (WC-10-02)."""
    base = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date.today()
    return (base - timedelta(days=1)).isoformat()


def _get_todays_matches(target_date: str | None = None) -> list[dict]:
    """Load today's WC matches with predictions and teams."""
    d = target_date or _get_today_str()
    matches = []

    with get_session() as session:
        rows = session.execute(
            select(WCMatch)
            .where(WCMatch.date == d)
            .order_by(WCMatch.kickoff_time)
        ).scalars().all()

        for m in rows:
            home = session.get(WCTeam, m.home_team_id)
            away = session.get(WCTeam, m.away_team_id)
            pred = session.execute(
                select(WCPrediction)
                .where(
                    WCPrediction.match_id == m.id,
                    WCPrediction.model_name == MODEL_NAME,
                )
            ).scalar_one_or_none()

            matches.append({
                "id": m.id,
                "home": home.name if home else "?",
                "away": away.name if away else "?",
                "kickoff": m.kickoff_time or "TBD",
                "venue": m.venue or "",
                "stage": m.stage,
                "group": m.group_letter or "",
                "status": m.status,
                "home_goals": m.home_goals,
                "away_goals": m.away_goals,
                "pred_h": pred.home_win_prob if pred else None,
                "pred_d": pred.draw_prob if pred else None,
                "pred_a": pred.away_win_prob if pred else None,
                "pred_score": pred.most_likely_score if pred else None,
            })

    return matches


def _get_group_standings() -> dict[str, list[dict]]:
    """Compute current group standings from finished matches."""
    standings: dict[str, dict[int, dict]] = {}

    with get_session() as session:
        teams = session.execute(select(WCTeam)).scalars().all()
        for t in teams:
            if t.group_letter not in standings:
                standings[t.group_letter] = {}
            standings[t.group_letter][t.id] = {
                "name": t.name, "pts": 0, "gd": 0, "gf": 0, "mp": 0,
            }

        finished = session.execute(
            select(WCMatch)
            .where(WCMatch.status == "finished", WCMatch.stage == "group")
        ).scalars().all()

        for m in finished:
            if m.home_goals is None:
                continue
            g = m.group_letter
            if not g or g not in standings:
                continue
            h = standings[g].get(m.home_team_id)
            a = standings[g].get(m.away_team_id)
            if not h or not a:
                continue

            h["mp"] += 1
            a["mp"] += 1
            h["gf"] += m.home_goals
            h["gd"] += m.home_goals - m.away_goals
            a["gf"] += m.away_goals
            a["gd"] += m.away_goals - m.home_goals

            if m.home_goals > m.away_goals:
                h["pts"] += 3
            elif m.home_goals == m.away_goals:
                h["pts"] += 1
                a["pts"] += 1
            else:
                a["pts"] += 3

    result = {}
    for g, teams_dict in sorted(standings.items()):
        sorted_teams = sorted(
            teams_dict.values(),
            key=lambda x: (-x["pts"], -x["gd"], -x["gf"]),
        )
        result[g] = sorted_teams
    return result


def _render_results_section(finished: list[dict], title: str) -> str:
    """Render a finished-matches results table (home score-score away + ✓/✗ vs the
    model's pick). Returns "" when there are no scored matches. Used to fold
    yesterday's results into the morning email (WC-10-02)."""
    rows = ""
    for m in finished:
        if m.get("home_goals") is None:
            continue
        score = f'{m["home_goals"]}-{m["away_goals"]}'
        if m["pred_h"] is not None:
            icon = (f'<span style="color:{GREEN};">&#10003;</span>' if _is_prediction_correct(m)
                    else f'<span style="color:{RED};">&#10007;</span>')
        else:
            icon = ""
        rows += f'''
        <tr>
            <td style="padding:8px 12px;color:{TEXT};font-size:14px;border-bottom:1px solid {BORDER};">
                <strong>{escape(m["home"])}</strong> {score} <strong>{escape(m["away"])}</strong>
            </td>
            <td style="padding:8px 12px;text-align:center;border-bottom:1px solid {BORDER};">{icon}</td>
        </tr>'''
    if not rows:
        return ""
    return f'''
        <tr><td style="padding:16px 24px;background-color:{SURFACE};">
            <h2 style="color:{TEXT};font-size:16px;margin:0 0 8px;">{escape(title)}</h2>
            <table style="width:100%;border-collapse:collapse;">{rows}</table>
        </td></tr>'''


def _render_morning_html(
    matches: list[dict],
    value_bets: list,
    standings: dict,
    day_number: int,
    recent_results: list[dict] | None = None,
    recent_correct: int = 0,
    recent_total: int = 0,
) -> str:
    """Build morning email HTML."""
    vb_count = len(value_bets)
    match_count = len(matches)

    # Match rows
    match_rows = ""
    for m in matches:
        pred_str = ""
        if m["pred_h"] is not None:
            pred_str = (
                f'<span style="color:{GREEN};font-family:{MONO};font-size:12px;">'
                f'H {m["pred_h"]:.0%} | D {m["pred_d"]:.0%} | A {m["pred_a"]:.0%}'
                f'</span>'
            )
            if m["pred_score"]:
                pred_str += f' <span style="color:{TEXT_DIM};font-size:11px;">({m["pred_score"]})</span>'

        match_rows += f'''
        <tr>
            <td style="padding:8px 12px;color:{TEXT};font-size:14px;border-bottom:1px solid {BORDER};">
                {escape(m["kickoff"])}
            </td>
            <td style="padding:8px 12px;color:{TEXT};font-size:14px;border-bottom:1px solid {BORDER};">
                <strong>{escape(m["home"])}</strong> vs <strong>{escape(m["away"])}</strong>
                <br>{pred_str}
            </td>
            <td style="padding:8px 12px;color:{TEXT_DIM};font-size:12px;border-bottom:1px solid {BORDER};">
                Group {escape(m["group"])} — {escape(m["venue"])}
            </td>
        </tr>'''

    # Value bet rows
    vb_rows = ""
    for vb in value_bets[:10]:
        vb_rows += f'''
        <tr>
            <td style="padding:6px 12px;color:{TEXT};font-size:13px;border-bottom:1px solid {BORDER};">
                {escape(vb.home_team)} vs {escape(vb.away_team)}
            </td>
            <td style="padding:6px 12px;color:{GREEN};font-family:{MONO};font-size:13px;border-bottom:1px solid {BORDER};">
                {escape(vb.market_type)}/{escape(vb.selection)}
            </td>
            <td style="padding:6px 12px;color:{GREEN};font-family:{MONO};font-size:13px;border-bottom:1px solid {BORDER};">
                +{vb.edge:.1%}
            </td>
            <td style="padding:6px 12px;color:{TEXT};font-family:{MONO};font-size:13px;border-bottom:1px solid {BORDER};">
                {vb.best_odds:.2f} ({escape(vb.bookmaker)})
            </td>
            <td style="padding:6px 12px;color:{YELLOW};font-family:{MONO};font-size:13px;border-bottom:1px solid {BORDER};">
                {vb.kelly_stake:.2%}
            </td>
        </tr>'''

    # Group standings
    standings_html = ""
    for g, teams_list in sorted(standings.items()):
        if not any(t["mp"] > 0 for t in teams_list):
            continue
        standings_html += f'''
        <div style="display:inline-block;width:48%;min-width:280px;vertical-align:top;margin-bottom:12px;">
            <h4 style="color:{TEXT};margin:8px 0 4px;font-size:13px;">Group {g}</h4>
            <table style="width:100%;border-collapse:collapse;">
                <tr style="color:{TEXT_DIM};font-size:11px;">
                    <td style="padding:2px 8px;">Team</td>
                    <td style="padding:2px 4px;text-align:center;">MP</td>
                    <td style="padding:2px 4px;text-align:center;">Pts</td>
                    <td style="padding:2px 4px;text-align:center;">GD</td>
                </tr>'''
        for i, t in enumerate(teams_list):
            color = GREEN if i < 2 else (YELLOW if i == 2 else TEXT_DIM)
            standings_html += f'''
                <tr>
                    <td style="padding:2px 8px;color:{color};font-size:12px;">{escape(t["name"])}</td>
                    <td style="padding:2px 4px;color:{TEXT_DIM};font-size:12px;text-align:center;">{t["mp"]}</td>
                    <td style="padding:2px 4px;color:{color};font-family:{MONO};font-size:12px;text-align:center;"><strong>{t["pts"]}</strong></td>
                    <td style="padding:2px 4px;color:{TEXT_DIM};font-family:{MONO};font-size:12px;text-align:center;">{t["gd"]:+d}</td>
                </tr>'''
        standings_html += '</table></div>'

    vb_section = ""
    if vb_rows:
        vb_section = f'''
        <tr><td style="padding:16px 24px;background-color:{SURFACE};">
            <h2 style="color:{GREEN};font-size:16px;margin:0 0 8px;">Value Bets ({vb_count})</h2>
            <table style="width:100%;border-collapse:collapse;">
                <tr style="color:{TEXT_DIM};font-size:11px;">
                    <td style="padding:4px 12px;">Match</td>
                    <td style="padding:4px 12px;">Market</td>
                    <td style="padding:4px 12px;">Edge</td>
                    <td style="padding:4px 12px;">Odds</td>
                    <td style="padding:4px 12px;">Kelly</td>
                </tr>
                {vb_rows}
            </table>
        </td></tr>'''

    standings_section = ""
    if standings_html:
        standings_section = f'''
        <tr><td style="padding:16px 24px;background-color:{SURFACE};">
            <h2 style="color:{TEXT};font-size:16px;margin:0 0 8px;">Group Standings</h2>
            {standings_html}
        </td></tr>'''

    # Yesterday's results folded into the morning digest (WC-10-02, owner option 1):
    # one daily email covers today's picks + how the prior day's matches went.
    results_section = (
        _render_results_section(
            recent_results, f"Yesterday's Results ({recent_correct}/{recent_total} correct)")
        if recent_results else ""
    )

    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>BetVector WC Morning</title></head>
<body style="margin:0;padding:0;background-color:{BG};font-family:{FONT};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{BG};">
    <tr><td align="center" style="padding:24px 16px;">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
            <tr><td style="padding:24px;background-color:{SURFACE};border-radius:8px 8px 0 0;border-bottom:1px solid {BORDER};">
                <h1 style="margin:0;color:{TEXT};font-size:22px;">
                    &#127942; WC Day {day_number}: {match_count} Match{"es" if match_count != 1 else ""} Today
                </h1>
            </td></tr>
            <tr><td style="padding:16px 24px;background-color:{SURFACE};">
                <h2 style="color:{TEXT};font-size:16px;margin:0 0 8px;">Today's Matches</h2>
                <table style="width:100%;border-collapse:collapse;">
                    {match_rows}
                </table>
            </td></tr>
            {vb_section}
            {results_section}
            {standings_section}
            <tr><td style="padding:16px 24px;background-color:{SURFACE};border-radius:0 0 8px 8px;border-top:1px solid {BORDER};">
                <p style="margin:0;color:{TEXT_DIM};font-size:11px;">
                    BetVector World Cup 2026 — Automated prediction email
                </p>
            </td></tr>
        </table>
    </td></tr>
</table>
</body></html>'''


def _render_elo_section(elo_snapshot: list[dict] | None) -> str:
    """Render updated Elo ratings table for evening email."""
    if not elo_snapshot:
        return ""
    rows = ""
    for i, t in enumerate(elo_snapshot, 1):
        rows += f'''
                    <tr>
                        <td style="padding:4px 12px;color:{TEXT_DIM};font-size:12px;">{i}.</td>
                        <td style="padding:4px 12px;color:{TEXT};font-size:13px;">{escape(t["name"])}</td>
                        <td style="padding:4px 12px;color:{GREEN};font-family:{MONO};font-size:13px;text-align:right;">{t["elo"]:.0f}</td>
                    </tr>'''
    return f'''
            <tr><td style="padding:16px 24px;background-color:{SURFACE};">
                <h2 style="color:{TEXT};font-size:16px;margin:0 0 8px;">Updated Elo Ratings (Top 10)</h2>
                <table style="width:100%;border-collapse:collapse;">
                    {rows}
                </table>
            </td></tr>'''


def _render_evening_html(
    finished: list[dict],
    accuracy: dict,
    day_number: int,
    correct: int,
    total: int,
    elo_snapshot: list[dict] | None = None,
) -> str:
    """Build evening results email HTML. Receives only finished matches."""
    result_rows = ""
    for m in finished:
        if m["home_goals"] is None:
            continue
        score = f'{m["home_goals"]}-{m["away_goals"]}'

        if m["pred_h"] is not None:
            is_correct = _is_prediction_correct(m)
            icon = f'<span style="color:{GREEN};">&#10003;</span>' if is_correct else f'<span style="color:{RED};">&#10007;</span>'
        else:
            icon = ""

        result_rows += f'''
        <tr>
            <td style="padding:8px 12px;color:{TEXT};font-size:14px;border-bottom:1px solid {BORDER};">
                <strong>{escape(m["home"])}</strong> {score} <strong>{escape(m["away"])}</strong>
            </td>
            <td style="padding:8px 12px;color:{TEXT};font-size:14px;border-bottom:1px solid {BORDER};text-align:center;">
                {icon}
            </td>
        </tr>'''

    # Model accuracy metrics
    brier_str = f'{accuracy.get("brier", 0):.4f}' if accuracy.get("n_matches", 0) > 0 else "N/A"
    acc_str = f'{accuracy.get("accuracy", 0):.0%}' if accuracy.get("n_matches", 0) > 0 else "N/A"
    n_str = str(accuracy.get("n_matches", 0))

    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>BetVector WC Evening</title></head>
<body style="margin:0;padding:0;background-color:{BG};font-family:{FONT};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{BG};">
    <tr><td align="center" style="padding:24px 16px;">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
            <tr><td style="padding:24px;background-color:{SURFACE};border-radius:8px 8px 0 0;border-bottom:1px solid {BORDER};">
                <h1 style="margin:0;color:{TEXT};font-size:22px;">
                    &#127942; WC Day {day_number} Results: {correct}/{total} Correct
                </h1>
            </td></tr>
            <tr><td style="padding:16px 24px;background-color:{SURFACE};">
                <h2 style="color:{TEXT};font-size:16px;margin:0 0 8px;">Results</h2>
                <table style="width:100%;border-collapse:collapse;">
                    {result_rows}
                </table>
            </td></tr>
            <tr><td style="padding:16px 24px;background-color:{SURFACE};">
                <h2 style="color:{TEXT};font-size:16px;margin:0 0 8px;">Model Performance</h2>
                <table style="width:100%;border-collapse:collapse;">
                    <tr>
                        <td style="padding:6px 12px;color:{TEXT_DIM};font-size:13px;">Brier Score (3-way)</td>
                        <td style="padding:6px 12px;color:{GREEN};font-family:{MONO};font-size:14px;">{brier_str}</td>
                    </tr>
                    <tr>
                        <td style="padding:6px 12px;color:{TEXT_DIM};font-size:13px;">Accuracy</td>
                        <td style="padding:6px 12px;color:{GREEN};font-family:{MONO};font-size:14px;">{acc_str}</td>
                    </tr>
                    <tr>
                        <td style="padding:6px 12px;color:{TEXT_DIM};font-size:13px;">Matches Evaluated</td>
                        <td style="padding:6px 12px;color:{TEXT};font-family:{MONO};font-size:14px;">{n_str}</td>
                    </tr>
                </table>
            </td></tr>
            {_render_elo_section(elo_snapshot)}
            <tr><td style="padding:16px 24px;background-color:{SURFACE};border-radius:0 0 8px 8px;border-top:1px solid {BORDER};">
                <p style="margin:0;color:{TEXT_DIM};font-size:11px;">
                    BetVector World Cup 2026 — Automated results email
                </p>
            </td></tr>
        </table>
    </td></tr>
</table>
</body></html>'''


def _compute_day_number(target_date: str | None = None) -> int:
    """Compute tournament day number (Day 1 = first match date)."""
    d = target_date or _get_today_str()
    with get_session() as session:
        first = session.execute(
            select(WCMatch.date).order_by(WCMatch.date).limit(1)
        ).scalar_one_or_none()
    if not first:
        return 1
    try:
        first_dt = datetime.strptime(first, "%Y-%m-%d").date()
        today_dt = datetime.strptime(d, "%Y-%m-%d").date()
        return max(1, (today_dt - first_dt).days + 1)
    except (ValueError, TypeError):
        return 1


def _wc_notifiable_user_ids(session=None) -> list[int]:
    """User ids opted in to the World Cup digest: active, with an email, and
    ``notify_wc == 1``. The WC digest is opt-IN (``notify_wc`` defaults to 0),
    unlike the league emails. ``session`` is injectable for testing."""
    from src.database.db import get_session
    from src.database.models import User

    def _query(s) -> list[int]:
        rows = (s.query(User.id)
                .filter(User.is_active == 1, User.email.isnot(None),
                        User.email != "", User.notify_wc == 1)
                .all())
        return [r[0] for r in rows]

    if session is not None:
        return _query(session)
    with get_session() as s:
        return _query(s)


def send_wc_morning_email_to_all(target_date: str | None = None) -> int:
    """Send the morning WC digest to every opted-in user (``notify_wc == 1``).
    Per-user try/except so one failure never blocks the rest. Returns the number
    sent. This is the entry point the WC pipeline calls."""
    sent = 0
    for uid in _wc_notifiable_user_ids():
        try:
            if send_wc_morning_email(uid, target_date):
                sent += 1
        except Exception:
            logger.exception("WC morning email failed for user %d", uid)
    logger.info("WC morning digest: sent to %d opted-in user(s)", sent)
    return sent


def send_wc_evening_email_to_all(target_date: str | None = None) -> int:
    """Send the evening WC review to every opted-in user (``notify_wc == 1``)."""
    sent = 0
    for uid in _wc_notifiable_user_ids():
        try:
            if send_wc_evening_email(uid, target_date):
                sent += 1
        except Exception:
            logger.exception("WC evening email failed for user %d", uid)
    logger.info("WC evening digest: sent to %d opted-in user(s)", sent)
    return sent


def send_wc_morning_email(user_id: int = 1, target_date: str | None = None) -> bool:
    """Send morning WC email with predictions and value bets.

    Returns False (no email sent) on days without WC matches.
    Callable from the WC pipeline.
    """
    matches = _get_todays_matches(target_date)
    if not matches:
        logger.info("No WC matches today — skipping morning email")
        return False

    email, name, _ = _get_user_email(user_id)
    if not email:
        logger.warning("No email for user %d — skipping WC morning email", user_id)
        return False

    value_bets = find_wc_value_bets()
    standings = _get_group_standings()
    day_number = _compute_day_number(target_date)

    # Fold yesterday's results into the morning digest (WC-10-02, owner option 1):
    # the morning run now settles overnight results, so one daily email covers
    # today's picks + how the prior day's matches went (the evening run is retired).
    prev_matches = _get_todays_matches(_previous_date(target_date))
    # Only scored finished matches: keeps the X/Y count coherent with what's
    # rendered and guards _is_prediction_correct against a NULL-goals dereference.
    recent_finished = [m for m in prev_matches
                       if m["status"] == "finished" and m["home_goals"] is not None]
    recent_correct = sum(1 for m in recent_finished
                         if m["pred_h"] is not None and _is_prediction_correct(m))
    recent_total = len(recent_finished)

    html = _render_morning_html(matches, value_bets, standings, day_number,
                                recent_finished, recent_correct, recent_total)
    vb_count = len(value_bets)
    subject = f"\U0001F3C6 WC Day {day_number}: {vb_count} value bet{'s' if vb_count != 1 else ''} for today"

    try:
        return _send_email(email, subject, html)
    except Exception:
        logger.exception("Failed to send WC morning email to %s", email)
        return False


def send_wc_evening_email(user_id: int = 1, target_date: str | None = None) -> bool:
    """Send evening WC email with results and model accuracy.

    Returns False on days without finished WC matches.
    Callable from the WC pipeline.
    """
    matches = _get_todays_matches(target_date)
    finished = [m for m in matches if m["status"] == "finished"]
    if not finished:
        logger.info("No finished WC matches today — skipping evening email")
        return False

    email, name, _ = _get_user_email(user_id)
    if not email:
        logger.warning("No email for user %d — skipping WC evening email", user_id)
        return False

    # Update Elo with today's results before reporting
    update_tournament_elo()
    accuracy = compute_model_accuracy()
    elo_snapshot = _get_top_elo_teams()
    day_number = _compute_day_number(target_date)

    # Compute correctness once — used in both subject and body
    correct = sum(
        1 for m in finished
        if m["pred_h"] is not None and _is_prediction_correct(m)
    )
    total = len(finished)

    html = _render_evening_html(finished, accuracy, day_number, correct, total, elo_snapshot)
    subject = f"\U0001F3C6 WC Day {day_number} Results: {correct}/{total} correct"

    try:
        return _send_email(email, subject, html)
    except Exception:
        logger.exception("Failed to send WC evening email to %s", email)
        return False


def _get_top_elo_teams(n: int = 10) -> list[dict]:
    """Get top N teams by current Elo rating for the evening email."""
    with get_session() as session:
        teams = session.execute(
            select(WCTeam)
            .where(WCTeam.elo_rating.isnot(None))
            .order_by(WCTeam.elo_rating.desc())
            .limit(n)
        ).scalars().all()
        return [{"name": t.name, "elo": round(t.elo_rating, 1)} for t in teams]


def _is_prediction_correct(m: dict) -> bool:
    """Check if model's most probable outcome matched actual result."""
    if m["home_goals"] > m["away_goals"]:
        return m["pred_h"] > max(m["pred_d"], m["pred_a"])
    elif m["home_goals"] == m["away_goals"]:
        return m["pred_d"] > max(m["pred_h"], m["pred_a"])
    else:
        return m["pred_a"] > max(m["pred_h"], m["pred_d"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from src.database.db import init_db

    init_db()

    print("=== WC Morning Email (dry run) ===")
    matches = _get_todays_matches()
    print(f"Today's matches: {len(matches)}")
    for m in matches:
        print(f"  {m['kickoff']} {m['home']} vs {m['away']}")

    if matches:
        value_bets = find_wc_value_bets()
        standings = _get_group_standings()
        day_number = _compute_day_number()
        html = _render_morning_html(matches, value_bets, standings, day_number)
        print(f"Morning HTML rendered: {len(html)} chars, {len(value_bets)} value bets, Day {day_number}")
    else:
        print("  No WC matches today — no email would be sent")

    print("\n=== WC Evening Email (dry run) ===")
    finished = [m for m in matches if m["status"] == "finished"]
    print(f"Finished today: {len(finished)}")
    if finished:
        update_tournament_elo()
        accuracy = compute_model_accuracy()
        elo_snap = _get_top_elo_teams()
        day_number = _compute_day_number()
        correct = sum(1 for m in finished if m["pred_h"] is not None and _is_prediction_correct(m))
        total = len(finished)
        html = _render_evening_html(finished, accuracy, day_number, correct, total, elo_snap)
        print(f"Evening HTML rendered: {len(html)} chars, {correct}/{total} correct, Brier={accuracy.get('brier', 0):.4f}")
    else:
        print("  No finished matches today — no email would be sent")
