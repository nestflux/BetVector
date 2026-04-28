#!/usr/bin/env python3
"""
BetVector — On-Demand Performance Report
==========================================
Generates a comprehensive terminal report covering system pick performance,
per-league and per-market breakdowns, shadow mode status, weekly trends,
and model health.

Usage:
    python scripts/performance_report.py              # Full report, all time
    python scripts/performance_report.py --league EPL  # Filter to one league
    python scripts/performance_report.py --days 30     # Last 30 days only
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import func, text

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so src.* imports resolve when running
# the script directly from the repo root.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.database.db import get_session  # noqa: E402
from src.database.models import (  # noqa: E402
    BetLog,
    EnsembleWeightHistory,
    League,
    ModelPerformance,
    ShadowValueBet,
)


# ===========================================================================
# ANSI colour helpers
# ===========================================================================

class C:
    """ANSI escape codes for coloured terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    WHITE = "\033[97m"
    BG_DARK = "\033[48;5;234m"
    UNDERLINE = "\033[4m"


def col_roi(value: float) -> str:
    """Colour a ROI/P&L value: green if positive, red if negative, yellow if near zero."""
    if value > 1.0:
        return f"{C.GREEN}{value:+.2f}{C.RESET}"
    elif value < -1.0:
        return f"{C.RED}{value:+.2f}{C.RESET}"
    else:
        return f"{C.YELLOW}{value:+.2f}{C.RESET}"


def col_pct(value: float) -> str:
    """Colour a percentage value."""
    if value > 1.0:
        return f"{C.GREEN}{value:+.1f}%{C.RESET}"
    elif value < -1.0:
        return f"{C.RED}{value:+.1f}%{C.RESET}"
    else:
        return f"{C.YELLOW}{value:+.1f}%{C.RESET}"


def col_clv(value: float | None) -> str:
    """Colour a CLV value."""
    if value is None:
        return f"{C.DIM}n/a{C.RESET}"
    pct = value * 100
    if pct > 0.5:
        return f"{C.GREEN}{pct:+.2f}%{C.RESET}"
    elif pct < -0.5:
        return f"{C.RED}{pct:+.2f}%{C.RESET}"
    else:
        return f"{C.YELLOW}{pct:+.2f}%{C.RESET}"


def header(title: str) -> str:
    """Create a section header bar."""
    line = "=" * 80
    return f"\n{C.CYAN}{C.BOLD}{line}\n  {title}\n{line}{C.RESET}"


def subheader(title: str) -> str:
    """Create a sub-section header."""
    line = "-" * 60
    return f"\n{C.WHITE}{C.BOLD}  {title}{C.RESET}\n  {C.DIM}{line}{C.RESET}"


# ===========================================================================
# Tier lookup from config/leagues.yaml
# ===========================================================================

def load_league_tiers() -> dict[str, str]:
    """Read tier classification from leagues.yaml strategy profiles.

    Returns a dict keyed by BOTH full name and short_name, e.g.:
        {"EPL": "Y", "English Premier League": "Y", "Championship": "G", ...}
    where G = green (profitable), Y = yellow (promising), R = red (unprofitable).
    """
    config_path = PROJECT_ROOT / "config" / "leagues.yaml"
    if not config_path.exists():
        return {}

    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    tiers: dict[str, str] = {}
    for league in cfg.get("leagues", []):
        full = league.get("name", "")
        short = league.get("short_name", "")
        strategy = league.get("strategy", {})
        multiplier = strategy.get("stake_multiplier", 1.0)
        auto_bet = strategy.get("auto_bet", False)

        # Tier logic mirrors PC-24/PC-25 classification:
        #   auto_bet=True + multiplier>=1.5 => green
        #   multiplier>=1.0 => yellow
        #   multiplier<1.0 => red
        if auto_bet and multiplier >= 1.5:
            tier = "G"
        elif multiplier >= 1.0:
            tier = "Y"
        else:
            tier = "R"

        tiers[short] = tier
        tiers[full] = tier

    return tiers


def tier_badge(tier: str) -> str:
    """Return a coloured tier badge for terminal display."""
    if tier == "G":
        return f"{C.GREEN}[GREEN]{C.RESET}"
    elif tier == "Y":
        return f"{C.YELLOW}[YELLOW]{C.RESET}"
    elif tier == "R":
        return f"{C.RED}[RED]{C.RESET}"
    return f"{C.DIM}[?]{C.RESET}"


# ===========================================================================
# Report sections
# ===========================================================================

def report_overall_summary(session, date_filter: str | None, league_filter: str | None) -> None:
    """Print the overall summary section: total picks, win rate, ROI, P&L, CLV."""
    print(header("OVERALL SUMMARY"))

    query = session.query(BetLog).filter(BetLog.bet_type == "system_pick")
    if date_filter:
        query = query.filter(BetLog.date >= date_filter)
    if league_filter:
        query = query.filter(BetLog.league == league_filter)

    bets = query.all()
    total = len(bets)
    if total == 0:
        print(f"\n  {C.DIM}No system picks found.{C.RESET}")
        return

    resolved = [b for b in bets if b.status in ("won", "lost")]
    pending = [b for b in bets if b.status == "pending"]
    won = [b for b in bets if b.status == "won"]
    lost = [b for b in bets if b.status == "lost"]

    total_staked = sum(b.stake for b in resolved) if resolved else 0
    total_pnl = sum(b.pnl or 0 for b in resolved)
    roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0
    win_rate = (len(won) / len(resolved) * 100) if resolved else 0

    clv_values = [b.clv for b in bets if b.clv is not None]
    avg_clv = sum(clv_values) / len(clv_values) if clv_values else None

    print(f"""
  Total System Picks:  {C.BOLD}{total}{C.RESET}
  Resolved:            {len(resolved)}  (Won: {C.GREEN}{len(won)}{C.RESET}  Lost: {C.RED}{len(lost)}{C.RESET})
  Pending:             {C.YELLOW}{len(pending)}{C.RESET}
  Win Rate:            {col_pct(win_rate).replace('%', '')}%  ({len(won)}/{len(resolved)})
  ROI:                 {col_pct(roi)}
  Total P&L:           {col_roi(total_pnl)}
  Avg CLV:             {col_clv(avg_clv)}""")


def report_per_league(session, date_filter: str | None, league_filter: str | None) -> None:
    """Print the per-league breakdown table."""
    print(header("PER-LEAGUE BREAKDOWN"))

    tiers = load_league_tiers()

    query = session.query(BetLog).filter(BetLog.bet_type == "system_pick")
    if date_filter:
        query = query.filter(BetLog.date >= date_filter)
    if league_filter:
        query = query.filter(BetLog.league == league_filter)

    bets = query.all()
    if not bets:
        print(f"\n  {C.DIM}No system picks found.{C.RESET}")
        return

    # Group by league
    leagues: dict[str, list] = {}
    for b in bets:
        leagues.setdefault(b.league, []).append(b)

    # Table header
    hdr = (
        f"  {'League':<22} {'Bets':>5} {'Won':>5} {'Lost':>5} {'Pend':>5} "
        f"{'Win%':>6} {'ROI%':>8} {'P&L':>9} {'AvgEdge':>8} {'AvgCLV':>8} {'Tier':>10}"
    )
    print(f"\n{C.BOLD}{C.UNDERLINE}{hdr}{C.RESET}")

    sorted_leagues = sorted(leagues.keys())
    for league_name in sorted_leagues:
        lb = leagues[league_name]
        total = len(lb)
        resolved = [b for b in lb if b.status in ("won", "lost")]
        pending_count = sum(1 for b in lb if b.status == "pending")
        won_count = sum(1 for b in lb if b.status == "won")
        lost_count = sum(1 for b in lb if b.status == "lost")

        total_staked = sum(b.stake for b in resolved) if resolved else 0
        total_pnl = sum(b.pnl or 0 for b in resolved)
        roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0
        win_rate = (won_count / len(resolved) * 100) if resolved else 0

        avg_edge = sum(b.edge for b in lb) / total * 100 if total else 0
        clv_vals = [b.clv for b in lb if b.clv is not None]
        avg_clv = sum(clv_vals) / len(clv_vals) if clv_vals else None

        tier = tiers.get(league_name, "?")

        # Truncate league name for display
        display_name = league_name[:21]

        # Build coloured values
        roi_str = col_pct(roi)
        pnl_str = col_roi(total_pnl)
        clv_str = col_clv(avg_clv) if avg_clv is not None else f"{C.DIM}n/a{C.RESET}"
        tier_str = tier_badge(tier)

        # Pad with raw widths (ANSI codes mess up alignment, so we pad manually)
        print(
            f"  {display_name:<22} {total:>5} {won_count:>5} {lost_count:>5} "
            f"{pending_count:>5} {win_rate:>5.1f}% {roi_str:>20} {pnl_str:>20} "
            f"{avg_edge:>7.1f}% {clv_str:>20} {tier_str}"
        )


def report_per_market(session, date_filter: str | None, league_filter: str | None) -> None:
    """Print the per-market-type breakdown."""
    print(header("PER-MARKET BREAKDOWN"))

    query = session.query(BetLog).filter(BetLog.bet_type == "system_pick")
    if date_filter:
        query = query.filter(BetLog.date >= date_filter)
    if league_filter:
        query = query.filter(BetLog.league == league_filter)

    bets = query.all()
    if not bets:
        print(f"\n  {C.DIM}No system picks found.{C.RESET}")
        return

    # Group by market_type
    markets: dict[str, list] = {}
    for b in bets:
        markets.setdefault(b.market_type, []).append(b)

    hdr = f"  {'Market':<20} {'Bets':>6} {'Win%':>7} {'ROI%':>9} {'AvgCLV':>9}"
    print(f"\n{C.BOLD}{C.UNDERLINE}{hdr}{C.RESET}")

    for market_name in sorted(markets.keys()):
        mb = markets[market_name]
        total = len(mb)
        resolved = [b for b in mb if b.status in ("won", "lost")]
        won_count = sum(1 for b in mb if b.status == "won")

        total_staked = sum(b.stake for b in resolved) if resolved else 0
        total_pnl = sum(b.pnl or 0 for b in resolved)
        roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0
        win_rate = (won_count / len(resolved) * 100) if resolved else 0

        clv_vals = [b.clv for b in mb if b.clv is not None]
        avg_clv = sum(clv_vals) / len(clv_vals) if clv_vals else None

        roi_str = col_pct(roi)
        clv_str = col_clv(avg_clv) if avg_clv is not None else f"{C.DIM}n/a{C.RESET}"

        print(f"  {market_name:<20} {total:>6} {win_rate:>6.1f}% {roi_str:>20} {clv_str:>20}")


def report_shadow_mode(session, date_filter: str | None, league_filter: str | None) -> None:
    """Print shadow mode test status and comparison."""
    print(header("SHADOW MODE STATUS"))

    query = session.query(ShadowValueBet)
    if date_filter:
        query = query.filter(ShadowValueBet.created_at >= date_filter)
    if league_filter:
        query = query.filter(ShadowValueBet.league == league_filter)

    shadows = query.all()
    if not shadows:
        print(f"\n  {C.DIM}No shadow bets found.{C.RESET}")
        return

    # Group by (league, strategy_change)
    groups: dict[tuple[str, str], list] = {}
    for s in shadows:
        key = (s.league, s.strategy_change)
        groups.setdefault(key, []).append(s)

    hdr = f"  {'League':<15} {'Strategy':<30} {'Bets':>5} {'Resolved':>9} {'Shadow ROI':>11}"
    print(f"\n{C.BOLD}{C.UNDERLINE}{hdr}{C.RESET}")

    for (league, strategy), slist in sorted(groups.items()):
        total = len(slist)
        resolved = [s for s in slist if s.result in ("won", "lost")]
        resolved_count = len(resolved)

        total_staked = sum(s.shadow_stake for s in resolved) if resolved else 0
        total_pnl = sum(s.shadow_pnl or 0 for s in resolved)
        roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0

        roi_str = col_pct(roi)

        # Truncate strategy for display
        strat_display = strategy[:29]
        print(f"  {league:<15} {strat_display:<30} {total:>5} {resolved_count:>9} {roi_str:>22}")


def report_weekly_trends(session, date_filter: str | None, league_filter: str | None) -> None:
    """Print the last 4 weeks of weekly performance trends."""
    print(header("TREND — LAST 4 WEEKS"))

    # Compute 4 weeks back from today (or from date_filter end)
    today = datetime.now().date()
    weeks: list[tuple[str, str]] = []
    for i in range(4):
        week_end = today - timedelta(days=i * 7)
        week_start = week_end - timedelta(days=6)
        weeks.append((week_start.isoformat(), week_end.isoformat()))
    weeks.reverse()  # Oldest first

    query_base = session.query(BetLog).filter(BetLog.bet_type == "system_pick")
    if league_filter:
        query_base = query_base.filter(BetLog.league == league_filter)

    hdr = f"  {'Week':<24} {'Placed':>7} {'Resolved':>9} {'Win%':>6} {'ROI%':>9} {'AvgCLV':>9}"
    print(f"\n{C.BOLD}{C.UNDERLINE}{hdr}{C.RESET}")

    for week_start, week_end in weeks:
        bets = (
            query_base
            .filter(BetLog.date >= week_start)
            .filter(BetLog.date <= week_end)
            .all()
        )

        total = len(bets)
        resolved = [b for b in bets if b.status in ("won", "lost")]
        won_count = sum(1 for b in bets if b.status == "won")

        total_staked = sum(b.stake for b in resolved) if resolved else 0
        total_pnl = sum(b.pnl or 0 for b in resolved)
        roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0
        win_rate = (won_count / len(resolved) * 100) if resolved else 0

        clv_vals = [b.clv for b in bets if b.clv is not None]
        avg_clv = sum(clv_vals) / len(clv_vals) if clv_vals else None

        roi_str = col_pct(roi) if resolved else f"{C.DIM}n/a{C.RESET}"
        clv_str = col_clv(avg_clv) if avg_clv is not None else f"{C.DIM}n/a{C.RESET}"
        win_str = f"{win_rate:.1f}%" if resolved else f"{C.DIM}n/a{C.RESET}"

        label = f"{week_start} to {week_end}"
        print(f"  {label:<24} {total:>7} {len(resolved):>9} {win_str:>6} {roi_str:>20} {clv_str:>20}")


def report_model_health(session, league_filter: str | None) -> None:
    """Print model health: latest Brier scores and ensemble weights."""
    print(header("MODEL HEALTH"))

    # --- Latest Brier scores per model ---
    print(subheader("Latest Brier Scores (from model_performance)"))

    # Get the most recent entry per model_name
    subq = (
        session.query(
            ModelPerformance.model_name,
            func.max(ModelPerformance.computed_at).label("latest"),
        )
        .group_by(ModelPerformance.model_name)
        .subquery()
    )
    latest_rows = (
        session.query(ModelPerformance)
        .join(
            subq,
            (ModelPerformance.model_name == subq.c.model_name)
            & (ModelPerformance.computed_at == subq.c.latest),
        )
        .all()
    )

    if latest_rows:
        hdr = f"  {'Model':<25} {'Period':<15} {'Brier':>7} {'ROI%':>8} {'Predictions':>12}"
        print(f"\n{C.BOLD}{hdr}{C.RESET}")
        for row in sorted(latest_rows, key=lambda r: r.model_name):
            brier_str = f"{row.brier_score:.4f}" if row.brier_score else "n/a"
            roi_str = col_pct(row.roi) if row.roi is not None else f"{C.DIM}n/a{C.RESET}"
            print(
                f"  {row.model_name:<25} {row.period_type:<15} "
                f"{brier_str:>7} {roi_str:>19} {row.total_predictions:>12}"
            )
    else:
        print(f"\n  {C.DIM}No model_performance records found.{C.RESET}")

    # --- Ensemble weights ---
    print(subheader("Ensemble Weights"))

    subq2 = (
        session.query(
            EnsembleWeightHistory.model_name,
            func.max(EnsembleWeightHistory.id).label("latest_id"),
        )
        .group_by(EnsembleWeightHistory.model_name)
        .subquery()
    )
    weight_rows = (
        session.query(EnsembleWeightHistory)
        .join(subq2, EnsembleWeightHistory.id == subq2.c.latest_id)
        .all()
    )

    if weight_rows:
        for row in sorted(weight_rows, key=lambda r: r.model_name):
            bar_len = int(row.weight * 40)
            bar = f"{C.GREEN}{'#' * bar_len}{C.DIM}{'.' * (40 - bar_len)}{C.RESET}"
            print(f"  {row.model_name:<20} {row.weight:.1%}  {bar}  (Brier: {row.brier_score:.4f})")
    else:
        print(f"\n  {C.DIM}No ensemble weight records found.{C.RESET}")


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="BetVector — On-Demand Performance Report",
    )
    parser.add_argument(
        "--league",
        type=str,
        default=None,
        help="Filter to a single league short_name (e.g. EPL, Championship, LaLiga)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Lookback window in days (default: all time)",
    )
    args = parser.parse_args()

    league_filter = args.league
    date_filter = None
    if args.days:
        cutoff = datetime.now().date() - timedelta(days=args.days)
        date_filter = cutoff.isoformat()

    # Title
    title_parts = ["BETVECTOR PERFORMANCE REPORT"]
    if league_filter:
        title_parts.append(f"League: {league_filter}")
    if date_filter:
        title_parts.append(f"Since: {date_filter}")
    else:
        title_parts.append("All Time")
    title_parts.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    print(f"\n{C.BOLD}{C.CYAN}")
    print("  " + "=" * 60)
    for part in title_parts:
        print(f"  {part}")
    print("  " + "=" * 60)
    print(C.RESET)

    with get_session() as session:
        report_overall_summary(session, date_filter, league_filter)
        report_per_league(session, date_filter, league_filter)
        report_per_market(session, date_filter, league_filter)
        report_shadow_mode(session, date_filter, league_filter)
        report_weekly_trends(session, date_filter, league_filter)
        report_model_health(session, league_filter)

    print(f"\n{C.DIM}  Report complete.{C.RESET}\n")


if __name__ == "__main__":
    main()
