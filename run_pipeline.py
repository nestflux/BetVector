#!/usr/bin/env python3
"""
BetVector — CLI Interface (E8-02)
==================================
Command-line interface for running the BetVector pipeline manually.

Usage examples::

    # Run the full morning pipeline (default if no command given)
    python run_pipeline.py morning

    # Re-fetch odds and recalculate edges
    python run_pipeline.py midday

    # Resolve bets and update P&L after matches finish
    python run_pipeline.py evening

    # Run a walk-forward backtest
    python run_pipeline.py backtest --league EPL --season 2024-25

    # Initialise the database and seed reference data
    python run_pipeline.py setup

    # Increase logging verbosity
    python run_pipeline.py morning --verbose

Commands
--------
- ``morning``  — Full pipeline: scrape → features → predict → value bets
- ``midday``   — Re-fetch odds, recalculate edges
- ``evening``  — Resolve bets, update P&L, compute metrics
- ``backtest`` — Walk-forward backtest on historical data
- ``setup``    — Initialise database and seed leagues/seasons/owner

Master Plan refs: MP §5 Architecture
"""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> int:
    """Parse arguments and dispatch to the appropriate pipeline command."""
    parser = argparse.ArgumentParser(
        prog="run_pipeline",
        description="BetVector — Football betting pipeline CLI",
        epilog=(
            "Examples:\n"
            "  python run_pipeline.py morning            Run full morning pipeline\n"
            "  python run_pipeline.py backtest --league EPL --season 2024-25\n"
            "  python run_pipeline.py setup              Initialise database\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Pipeline command to run")

    # --- morning ---
    sub_morning = subparsers.add_parser(
        "morning",
        help="Full pipeline: scrape → features → predict → value bets → log picks",
    )
    sub_morning.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG-level logging",
    )

    # --- midday ---
    sub_midday = subparsers.add_parser(
        "midday",
        help="Re-fetch odds and recalculate edges",
    )
    sub_midday.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG-level logging",
    )

    # --- evening ---
    sub_evening = subparsers.add_parser(
        "evening",
        help="Resolve bets, update P&L, compute performance metrics",
    )
    sub_evening.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG-level logging",
    )

    # --- backtest ---
    sub_backtest = subparsers.add_parser(
        "backtest",
        help="Run walk-forward backtest on historical data",
    )
    sub_backtest.add_argument(
        "--league", default="EPL",
        help="League short name (default: EPL)",
    )
    sub_backtest.add_argument(
        "--season", default="2024-25",
        help="Season to backtest (default: 2024-25)",
    )
    sub_backtest.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG-level logging",
    )

    # --- setup ---
    sub_setup = subparsers.add_parser(
        "setup",
        help="Initialise database and seed reference data (leagues, seasons, owner)",
    )
    sub_setup.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG-level logging",
    )

    args = parser.parse_args()

    # Default to morning if no command given
    if args.command is None:
        args.command = "morning"
        args.verbose = False

    # Configure logging level
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Dispatch to the appropriate command
    if args.command == "setup":
        return _run_setup()
    elif args.command == "morning":
        return _run_morning()
    elif args.command == "midday":
        return _run_midday()
    elif args.command == "evening":
        return _run_evening()
    elif args.command == "backtest":
        return _run_backtest(league=args.league, season=args.season)
    else:
        parser.print_help()
        return 1


# ============================================================================
# Command implementations
# ============================================================================

def _run_setup() -> int:
    """Initialise the database and seed reference data."""
    print("BetVector Setup")
    print("=" * 40)

    print("[1/2] Initialising database...")
    from src.database.db import init_db
    init_db()
    print("  → Database tables created")

    print("[2/2] Seeding reference data...")
    from src.database.seed import seed_all
    seed_all()
    print("  → Leagues, seasons, and owner seeded")

    print("\nSetup complete.")
    return 0


def _run_morning() -> int:
    """Run the full morning pipeline."""
    from src.pipeline import Pipeline
    pipeline = Pipeline()
    result = pipeline.run_morning()
    return 0 if result.status == "completed" else 1


def _run_midday() -> int:
    """Run the midday odds update."""
    from src.pipeline import Pipeline
    pipeline = Pipeline()
    result = pipeline.run_midday()
    return 0 if result.status == "completed" else 1


def _run_evening() -> int:
    """Run the evening results pipeline."""
    from src.pipeline import Pipeline
    pipeline = Pipeline()
    result = pipeline.run_evening()
    return 0 if result.status == "completed" else 1


def _run_backtest(league: str, season: str) -> int:
    """Run a walk-forward backtest."""
    from src.pipeline import Pipeline
    pipeline = Pipeline()
    result = pipeline.run_backtest(league=league, season=season)
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
