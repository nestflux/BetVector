"""
BetVector World Cup 2026 — Daily Pipeline (WC-07-01)
=====================================================
Orchestrates the WC pipeline: scrape → elo → features → predict →
simulate → value bets → email alerts.

Morning pipeline runs before matches (picks + value bets).
Evening pipeline runs after matches (results + accuracy review).

Each step is wrapped in try/except — a single step failure must never
prevent subsequent steps from running. The pipeline logs to
data/logs/wc_{mode}_{date}.log.

Usage:
    python -m src.world_cup.pipeline --mode morning
    python -m src.world_cup.pipeline --mode evening
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parents[2] / "data" / "logs"

# Load .env for local/direct runs so DATABASE_URL (Neon) is honored, exactly
# like run_pipeline.py does for the league pipeline. The launchd wrapper
# (run_wc_pipeline.sh) also sources .env, but auto-loading here ensures a
# direct `python -m src.world_cup.pipeline` run targets the SAME database —
# preventing the SQLite/Neon split-brain where odds and predictions landed
# in different DBs and value bets could never be produced.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass  # python-dotenv not installed — env vars must be set externally


def _setup_logging(mode: str) -> None:
    """Configure file + console logging for this pipeline run."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"wc_{mode}_{date.today().isoformat()}.log"

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def _step(name: str, fn, *args, **kwargs):
    """Run a pipeline step with timing and error isolation."""
    logger.info("━━━ Step: %s ━━━", name)
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        elapsed = time.time() - t0
        logger.info("✓ %s completed in %.1fs — %s", name, elapsed, result)
        return result
    except Exception as e:
        elapsed = time.time() - t0
        logger.error("✗ %s FAILED after %.1fs: %s", name, elapsed, e, exc_info=True)
        return None


def run_wc_pipeline(mode: str = "morning") -> dict:
    """
    Run the World Cup pipeline.

    Parameters
    ----------
    mode : str
        'morning' — scrape, elo, odds, features, predict, simulate, value bets, email
        'evening' — scrape results, elo update, evaluate accuracy, email review

    Returns
    -------
    dict with step results and overall status.
    """
    _setup_logging(mode)
    logger.info("=" * 60)
    logger.info("WC 2026 Pipeline — %s — %s", mode.upper(), date.today().isoformat())
    logger.info("=" * 60)

    t_start = time.time()
    results = {}

    from src.database.db import init_db
    init_db()

    if mode == "morning":
        results = _run_morning()
    elif mode == "evening":
        results = _run_evening()
    else:
        logger.error("Unknown mode: %s (expected 'morning' or 'evening')", mode)
        return {"status": "error", "reason": f"unknown mode: {mode}"}

    elapsed = time.time() - t_start
    results["total_seconds"] = round(elapsed, 1)
    results["status"] = "completed"

    logger.info("=" * 60)
    logger.info("Pipeline %s completed in %.1fs", mode.upper(), elapsed)
    logger.info("=" * 60)

    return results


def _run_morning() -> dict:
    """
    Morning pipeline steps:
    1. Scrape latest WC results (update completed matches)
    2. Update Elo ratings for newly completed matches
    3. Fetch fresh odds for upcoming matches
    4. Compute/recompute features for upcoming matches
    5. Generate predictions for upcoming matches
    6. Run tournament simulator (10K simulations)
    7. Find value bets
    8. Send morning email alert
    """
    results = {}

    # 1. Scrape results (picks up overnight completions)
    from src.world_cup.scraper import scrape_wc_results
    results["scrape_results"] = _step("Scrape WC Results", scrape_wc_results)

    # 1a. Self-heal: sweep recent ESPN results for any GROUP match the Odds API's
    # 3-day /scores window missed, so standings can't silently fall behind. ESPN is
    # free with no lookback limit; results-only (never invents fixtures); idempotent.
    from src.world_cup.results_espn import self_heal_wc_results
    results["espn_self_heal"] = _step("ESPN Results Self-Heal", self_heal_wc_results)

    # 1b. Capture closing lines (CLV) for matches that just finished — WC-10-02.
    # The morning run is now the daily spine (the 22:00 evening run is retired), so
    # it must settle CLV on overnight completions, not just refresh today's board.
    from src.world_cup.value_finder import capture_wc_closing_lines
    results["closing_lines"] = _step("Capture Closing Lines (CLV)", capture_wc_closing_lines)

    # 2. Update Elo from any newly finished matches
    from src.world_cup.calibration import update_tournament_elo
    results["elo_update"] = _step("Update Tournament Elo", update_tournament_elo)

    # 2b. Recompute model accuracy on settled matches (WC-10-02 — absorbed from the
    # retired evening run) so Model Health and the morning email stay current.
    from src.world_cup.calibration import compute_model_accuracy
    results["accuracy"] = _step("Compute Model Accuracy", compute_model_accuracy)

    # 3. Fetch fresh odds
    from src.world_cup.scraper import scrape_wc_odds
    results["scrape_odds"] = _step("Scrape WC Odds", scrape_wc_odds)

    # 4. Compute features for all matches
    from src.world_cup.features import compute_wc_features
    results["features"] = _step("Compute WC Features", compute_wc_features)

    # 5. Fit model and generate predictions
    from src.world_cup.predictor import WCPoissonPredictor
    predictor = WCPoissonPredictor(alpha=1.0)
    results["model_fit"] = _step("Fit WC Poisson Model", predictor.fit)
    if predictor._is_fitted:
        results["predictions"] = _step("Generate Predictions", predictor.predict_all)
    else:
        logger.warning("Model not fitted — skipping predictions")
        results["predictions"] = None

    # 5b. Bayesian shadow model (WC-09-06) — runs alongside the Poisson, stored
    # under model_name="wc_bayesian_v1". SHADOW ONLY: never staked, never
    # overrides the Poisson, and generates no value bets (the value finder reads
    # only the Poisson model_name). Tracked on the scorecard (WC-09-07) so we can
    # see whether it earns promotion. Isolated by _step — a failure here never
    # blocks the Poisson predictions, simulation, or value bets below.
    from src.world_cup.bayesian_model import BayesianPoissonModel
    bayes = BayesianPoissonModel()
    results["bayes_fit"] = _step("Fit WC Bayesian (shadow)", bayes.fit)
    if bayes._fitted:
        results["bayes_predictions"] = _step(
            "Generate Bayesian Shadow Predictions", bayes.predict_all_shadow)
    else:
        results["bayes_predictions"] = None

    # 6. Run tournament simulator
    from src.world_cup.simulator import simulate_tournament
    if predictor._is_fitted:
        results["simulation"] = _step(
            "Tournament Simulation (10K)",
            simulate_tournament, predictor, n_sims=10_000, seed=42,
        )
    else:
        results["simulation"] = None

    # 7. Find and save value bets
    from src.world_cup.value_finder import find_wc_value_bets, save_wc_value_bets
    vbs = _step("Find Value Bets", find_wc_value_bets)
    if vbs:
        results["value_bets"] = _step("Save Value Bets", save_wc_value_bets, vbs)
    else:
        results["value_bets"] = {"new": 0, "total": 0}

    # 7b. Write today's fixtures to the local cache for the pre-kickoff dispatcher
    # (WC-10-03) — lets the 15-min heartbeat find imminent matches without Neon.
    from src.world_cup.dispatcher import write_fixture_cache
    results["fixture_cache"] = _step("Write Fixture Cache", write_fixture_cache)

    # 8. Send morning email to every opted-in user (notify_wc=1; opt-in default off)
    from src.world_cup.alerts import send_wc_morning_email_to_all
    results["email"] = _step("Send Morning Email", send_wc_morning_email_to_all)

    return results


def run_prematch(match_id: int) -> dict:
    """Focused pre-kickoff run for ONE match (fired by the dispatcher ~40 min
    pre-KO, WC-10-04): one 1-event Odds-API pull (1 region) to capture the
    near-closing line for this match, then re-derive value/edge against the
    current predictions. Hits Neon + the Odds API — only ever on a real fire,
    never on an idle heartbeat."""
    from src.world_cup.scraper import scrape_wc_match_odds
    odds = scrape_wc_match_odds(match_id)
    result = {"match_id": match_id, "odds_status": odds.get("status"),
              "remaining": odds.get("remaining")}
    if odds.get("status") == "ok":
        from src.world_cup.value_finder import find_wc_value_bets, save_wc_value_bets
        vbs = find_wc_value_bets()
        result["value_bets"] = save_wc_value_bets(vbs) if vbs else {"new": 0, "total": 0}
    logger.info("Pre-match run for match %d → %s", match_id, result)
    return result


def _run_evening() -> dict:
    """
    Evening pipeline steps:
    1. Scrape today's results
    2. Update Elo ratings
    3. Evaluate predictions vs actual results
    4. Update model accuracy metrics
    5. Send evening review email
    """
    results = {}

    # 1. Scrape today's results
    from src.world_cup.scraper import scrape_wc_results
    results["scrape_results"] = _step("Scrape WC Results", scrape_wc_results)

    # 1a. Self-heal: same ESPN gap-fill as the morning run, so an evening match the
    # Odds API hasn't settled yet still lands tonight (free, results-only, idempotent).
    from src.world_cup.results_espn import self_heal_wc_results
    results["espn_self_heal"] = _step("ESPN Results Self-Heal", self_heal_wc_results)

    # 1b. Freeze closing lines + CLV for picks whose match just finished (WC-09-01)
    from src.world_cup.value_finder import capture_wc_closing_lines
    results["closing_lines"] = _step("Capture Closing Lines (CLV)", capture_wc_closing_lines)

    # 2. Update Elo
    from src.world_cup.calibration import update_tournament_elo
    results["elo_update"] = _step("Update Tournament Elo", update_tournament_elo)

    # 3-4. Compute accuracy metrics (Brier, log-loss, accuracy)
    from src.world_cup.calibration import compute_model_accuracy
    results["accuracy"] = _step("Compute Model Accuracy", compute_model_accuracy)

    # 5. Send evening email to every opted-in user (notify_wc=1; opt-in default off)
    from src.world_cup.alerts import send_wc_evening_email_to_all
    results["email"] = _step("Send Evening Email", send_wc_evening_email_to_all)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="BetVector World Cup 2026 Daily Pipeline",
    )
    parser.add_argument(
        "--mode",
        choices=["morning", "evening"],
        default="morning",
        help="Pipeline mode: morning (full) or evening (results review)",
    )
    args = parser.parse_args()

    result = run_wc_pipeline(mode=args.mode)

    if result.get("status") == "completed":
        print(f"\nPipeline {args.mode} completed in {result['total_seconds']}s")
        sys.exit(0)
    else:
        print(f"\nPipeline {args.mode} failed: {result.get('reason', 'unknown')}")
        sys.exit(1)
