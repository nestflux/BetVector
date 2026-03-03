"""
BetVector — Backtest Reporter (E7-03)
=======================================
Generates formatted backtest reports for console output, JSON export,
and static PNG charts.

Three output modes:
  1. ``print_backtest_report()`` — formatted console table with key metrics
  2. ``save_backtest_report()`` — full JSON dump for programmatic analysis
  3. ``plot_backtest_results()`` — matplotlib PNG with PnL curve and calibration

Master Plan refs: MP §4 Evaluation
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from src.evaluation.backtester import BacktestResult

logger = logging.getLogger(__name__)


# ============================================================================
# Console Report
# ============================================================================

def print_backtest_report(result: BacktestResult) -> str:
    """Print a formatted backtest report to the console.

    Includes key metrics in a table format, plus a per-market breakdown
    if bets span multiple market types.

    Parameters
    ----------
    result : BacktestResult
        Completed backtest results.

    Returns
    -------
    str
        The formatted report string (also printed to console).
    """
    # Determine ROI label with clear positive/negative indicator
    roi_str = f"{result.roi:+.2f}%" if result.roi is not None else "N/A"
    roi_label = "PROFITABLE" if (result.roi or 0) > 0 else "LOSS"

    pnl_str = f"${result.total_pnl:+.2f}"
    brier_str = f"{result.brier_score:.4f}" if result.brier_score is not None else "N/A"
    clv_str = f"{result.clv_avg:.6f}" if result.clv_avg is not None else "N/A"

    lines = [
        "",
        "=" * 60,
        "  BETVECTOR WALK-FORWARD BACKTEST REPORT",
        "=" * 60,
        "",
        f"  {'Total matches:':<30} {result.total_matches}",
        f"  {'Matches predicted:':<30} {result.total_predicted}",
        f"  {'Value bets found:':<30} {result.total_value_bets}",
        f"  {'Total staked:':<30} ${result.total_staked:.2f}",
        f"  {'Total P&L:':<30} {pnl_str}",
        f"  {'ROI:':<30} {roi_str}  [{roi_label}]",
        f"  {'Brier score:':<30} {brier_str}",
        f"  {'Average CLV:':<30} {clv_str}",
        "",
    ]

    # Per-market breakdown from daily PnL series
    market_stats = _calculate_market_breakdown(result)
    if market_stats:
        lines.append("  Per-Market Breakdown:")
        lines.append(f"  {'Market':<15} {'Bets':>6} {'Won':>6} {'Lost':>6} {'Win%':>8}")
        lines.append("  " + "-" * 45)
        for market, stats in sorted(market_stats.items()):
            win_pct = (
                f"{stats['won'] / stats['total'] * 100:.1f}%"
                if stats["total"] > 0 else "N/A"
            )
            lines.append(
                f"  {market:<15} {stats['total']:>6} "
                f"{stats['won']:>6} {stats['lost']:>6} {win_pct:>8}"
            )
        lines.append("")

    # Daily PnL summary
    if result.daily_pnl_series:
        profitable_days = sum(
            1 for d in result.daily_pnl_series if d["pnl"] > 0
        )
        loss_days = sum(
            1 for d in result.daily_pnl_series if d["pnl"] < 0
        )
        flat_days = sum(
            1 for d in result.daily_pnl_series if d["pnl"] == 0
        )
        total_days = len(result.daily_pnl_series)

        lines.append(f"  {'Matchdays (total):':<30} {total_days}")
        lines.append(f"  {'Profitable days:':<30} {profitable_days}")
        lines.append(f"  {'Loss days:':<30} {loss_days}")
        lines.append(f"  {'Flat days:':<30} {flat_days}")
        lines.append("")

        # Peak and trough bankroll
        bankrolls = [d["bankroll"] for d in result.daily_pnl_series]
        if bankrolls:
            peak = max(bankrolls)
            trough = min(bankrolls)
            lines.append(f"  {'Peak bankroll:':<30} ${peak:.2f}")
            lines.append(f"  {'Trough bankroll:':<30} ${trough:.2f}")
            lines.append("")

    lines.append("=" * 60)
    lines.append("")

    report = "\n".join(lines)
    print(report)
    return report


# ============================================================================
# JSON Export
# ============================================================================

def save_backtest_report(
    result: BacktestResult,
    filepath: str = "data/predictions/backtest_report.json",
) -> Path:
    """Save the full backtest results as a JSON file.

    Includes all metrics, calibration data, and the complete daily PnL
    series for programmatic analysis or dashboard import.

    Parameters
    ----------
    result : BacktestResult
        Completed backtest results.
    filepath : str
        Path to save the JSON file.

    Returns
    -------
    Path
        The path to the saved file.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "summary": {
            "total_matches": result.total_matches,
            "total_predicted": result.total_predicted,
            "total_value_bets": result.total_value_bets,
            "total_staked": result.total_staked,
            "total_pnl": result.total_pnl,
            "roi": result.roi,
            "brier_score": result.brier_score,
            "clv_avg": result.clv_avg,
        },
        "calibration": result.calibration_data,
        "daily_pnl": result.daily_pnl_series,
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    logger.info("Saved backtest report to %s", path)
    return path


# ============================================================================
# Matplotlib Charts
# ============================================================================

def plot_backtest_results(
    result: BacktestResult,
    filepath: str = "data/predictions/backtest_results.png",
) -> Path:
    """Generate matplotlib charts from backtest results and save as PNG.

    Creates a figure with two subplots:
      1. **Cumulative PnL curve** — shows how the bankroll evolved over
         the season, with a horizontal line at $0 for reference.
      2. **Calibration plot** — predicted probability vs actual win rate
         per bin, with the ideal diagonal line for reference.

    Uses matplotlib (not Plotly) for static exports, as specified in
    CLAUDE.md Rule 2: "matplotlib only for static exports".

    Parameters
    ----------
    result : BacktestResult
        Completed backtest results.
    filepath : str
        Path to save the PNG file.

    Returns
    -------
    Path
        The path to the saved PNG file.
    """
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend for file output
    import matplotlib.pyplot as plt

    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # --- Plot 1: Cumulative PnL curve ---
    ax1 = axes[0]

    if result.daily_pnl_series:
        dates = [d["date"] for d in result.daily_pnl_series]
        cum_pnl = [d["cumulative_pnl"] for d in result.daily_pnl_series]

        # Use indices for x-axis (dates would overlap)
        x = range(len(dates))
        ax1.plot(x, cum_pnl, color="#3FB950", linewidth=1.5, label="Cumulative PnL")
        ax1.axhline(y=0, color="#F85149", linestyle="--", linewidth=0.8, alpha=0.7)
        ax1.fill_between(
            x, cum_pnl, 0,
            where=[p >= 0 for p in cum_pnl],
            color="#3FB950", alpha=0.15,
        )
        ax1.fill_between(
            x, cum_pnl, 0,
            where=[p < 0 for p in cum_pnl],
            color="#F85149", alpha=0.15,
        )

        # Show a few date labels
        n_labels = min(6, len(dates))
        step = max(1, len(dates) // n_labels)
        ax1.set_xticks(range(0, len(dates), step))
        ax1.set_xticklabels(
            [dates[i] for i in range(0, len(dates), step)],
            rotation=45, fontsize=7,
        )

    ax1.set_title("Cumulative PnL Over Season", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Matchday")
    ax1.set_ylabel("Cumulative PnL ($)")
    ax1.grid(True, alpha=0.3)

    # --- Plot 2: Calibration plot ---
    ax2 = axes[1]

    if result.calibration_data:
        predicted = []
        actual = []
        counts = []

        for label, data in sorted(result.calibration_data.items()):
            predicted.append(data["predicted_avg"])
            actual.append(data["actual_rate"])
            counts.append(data["count"])

        # Ideal diagonal
        ax2.plot([0, 1], [0, 1], color="#F85149", linestyle="--",
                 linewidth=0.8, alpha=0.7, label="Perfect calibration")

        # Actual calibration points (size proportional to count)
        sizes = [max(20, min(200, c * 0.5)) for c in counts]
        ax2.scatter(
            predicted, actual, s=sizes, color="#3FB950",
            alpha=0.8, edgecolors="white", linewidth=0.5,
            label="Actual",
        )

    ax2.set_title("Calibration Plot", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Predicted Probability")
    ax2.set_ylabel("Actual Win Rate")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    logger.info("Saved backtest charts to %s", path)
    return path


# ============================================================================
# Internal Helpers
# ============================================================================

def _calculate_market_breakdown(
    result: BacktestResult,
) -> dict:
    """Extract per-market win/loss stats from per-bet details.

    Groups bets by market type (1X2, OU25, BTTS, etc.) and calculates
    total bets, wins, and losses for each market.

    Returns an empty dict if no per-bet data is available (e.g. when
    using a BacktestResult without bet_details populated).
    """
    if not hasattr(result, "bet_details") or not result.bet_details:
        return {}

    # Group by market_type and tally wins/losses
    # Market groups: combine related markets for readability
    # e.g. OU15, OU25, OU35 → "Over/Under", or keep separate
    market_stats: dict = {}

    for bet in result.bet_details:
        market = bet.get("market_type", "unknown")
        if market not in market_stats:
            market_stats[market] = {"total": 0, "won": 0, "lost": 0}

        market_stats[market]["total"] += 1
        if bet.get("status") == "won":
            market_stats[market]["won"] += 1
        elif bet.get("status") == "lost":
            market_stats[market]["lost"] += 1

    return market_stats
