#!/usr/bin/env python3
"""
BetVector — Understat Data Gap Diagnostic
==========================================
Quick diagnostic to figure out why EPL 2022-23 and 2023-24 Understat data
failed to load during the backfill (GitHub Actions run #22942486235).

Tests:
  1. Can the understatapi package reach Understat for these seasons?
  2. Does get_match_data() return match fixtures?
  3. Does get_team_data() return rich stats (xG, NPxG, PPDA, deep)?
  4. What does our DB currently have for these seasons (MatchStats)?
  5. Can our own UnderstatScraper.scrape() succeed end-to-end?

Usage:
    python scripts/diagnose_understat_gap.py
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Ensure project root on PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("diagnose_understat")

PROBLEM_SEASONS = ["2022-23", "2023-24"]
WORKING_SEASON = "2024-25"  # Known good — control test


def divider(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


# ============================================================================
# Test 1: Raw understatapi package — can it reach Understat at all?
# ============================================================================

def test_raw_api() -> dict:
    """Hit the understatapi package directly for each season."""
    divider("TEST 1 — Raw understatapi Package")

    results = {}

    try:
        from understatapi import UnderstatClient
        client = UnderstatClient()
        print(f"  understatapi imported OK, client created")
    except ImportError:
        print("  FAIL: understatapi not installed (pip install understatapi)")
        return {"error": "not installed"}

    all_seasons = PROBLEM_SEASONS + [WORKING_SEASON]

    for season_str in all_seasons:
        api_year = int(season_str.split("-")[0])
        label = f"EPL {season_str} (year={api_year})"
        print(f"\n  --- {label} ---")

        season_result = {
            "match_data_count": 0,
            "team_data_count": 0,
            "team_data_teams": [],
            "sample_history_len": 0,
            "sample_stats_keys": [],
            "error": None,
        }

        # --- get_match_data ---
        try:
            time.sleep(3)  # Rate limit
            league_obj = client.league(league="EPL")
            match_data = league_obj.get_match_data(season=str(api_year))

            if match_data:
                season_result["match_data_count"] = len(match_data)
                # Show a sample match
                sample = match_data[0]
                home_title = sample.get("h", {}).get("title", "?")
                away_title = sample.get("a", {}).get("title", "?")
                is_result = sample.get("isResult", False)
                xg = sample.get("xG", {})
                print(f"  get_match_data(): {len(match_data)} matches")
                print(f"    Sample: {home_title} vs {away_title}, "
                      f"isResult={is_result}, xG={xg}")
            else:
                print(f"  get_match_data(): EMPTY/None — {type(match_data)}")
                season_result["error"] = "match_data empty"

        except Exception as exc:
            print(f"  get_match_data() EXCEPTION: {type(exc).__name__}: {exc}")
            season_result["error"] = f"match_data: {exc}"

        # --- get_team_data ---
        try:
            time.sleep(3)  # Rate limit
            league_obj = client.league(league="EPL")
            team_data = league_obj.get_team_data(season=str(api_year))

            if team_data:
                season_result["team_data_count"] = len(team_data)
                team_names = [
                    info.get("title", "?") for info in team_data.values()
                ]
                season_result["team_data_teams"] = sorted(team_names)

                print(f"  get_team_data(): {len(team_data)} teams")
                print(f"    Teams: {', '.join(sorted(team_names)[:5])}...")

                # Check history length and stats keys for first team
                first_team_id = list(team_data.keys())[0]
                first_team = team_data[first_team_id]
                history = first_team.get("history", [])
                season_result["sample_history_len"] = len(history)

                print(f"    First team '{first_team.get('title')}': "
                      f"{len(history)} history entries")

                if history:
                    entry = history[0]
                    season_result["sample_stats_keys"] = sorted(entry.keys())
                    has_npxg = "npxG" in entry
                    has_ppda = "ppda" in entry
                    has_deep = "deep" in entry
                    print(f"    Stats keys: {sorted(entry.keys())}")
                    print(f"    Has npxG: {has_npxg}, ppda: {has_ppda}, "
                          f"deep: {has_deep}")
                    if has_npxg:
                        print(f"    Sample npxG={entry.get('npxG')}, "
                              f"npxGA={entry.get('npxGA')}")
                    if has_ppda:
                        ppda = entry.get("ppda", {})
                        print(f"    Sample ppda={ppda}")
                else:
                    print(f"    WARNING: history array is EMPTY")
                    season_result["error"] = "team_data history empty"
            else:
                print(f"  get_team_data(): EMPTY/None — {type(team_data)}")
                if season_result["error"] is None:
                    season_result["error"] = "team_data empty"

        except Exception as exc:
            print(f"  get_team_data() EXCEPTION: {type(exc).__name__}: {exc}")
            if season_result["error"] is None:
                season_result["error"] = f"team_data: {exc}"

        results[season_str] = season_result

    return results


# ============================================================================
# Test 2: Our scraper — does UnderstatScraper.scrape() work end-to-end?
# ============================================================================

def test_our_scraper() -> dict:
    """Run our own UnderstatScraper.scrape() for each problem season."""
    divider("TEST 2 — Our UnderstatScraper.scrape()")

    from src.scrapers.understat_scraper import UnderstatScraper
    from src.config import BetVectorConfig

    config = BetVectorConfig()
    active_leagues = config.get_active_leagues()
    epl_cfg = next(
        (lc for lc in active_leagues if lc.short_name == "EPL"), None
    )
    if epl_cfg is None:
        print("  FAIL: EPL not found in active leagues")
        return {"error": "no EPL config"}

    print(f"  EPL config:")
    print(f"    understat_league = {getattr(epl_cfg, 'understat_league', 'MISSING')}")
    print(f"    short_name = {epl_cfg.short_name}")

    scraper = UnderstatScraper()
    results = {}

    all_seasons = PROBLEM_SEASONS + [WORKING_SEASON]

    for season_str in all_seasons:
        print(f"\n  --- scrape(EPL, {season_str}) ---")
        try:
            df = scraper.scrape(league_config=epl_cfg, season=season_str)

            if df.empty:
                print(f"  RESULT: Empty DataFrame (0 rows)")
                results[season_str] = {"rows": 0, "error": "empty"}
            else:
                finished = df[df["home_xg"].notna()]
                has_npxg = df["home_npxg"].notna().sum()
                has_ppda = df["home_ppda"].notna().sum()
                has_deep = df["home_deep"].notna().sum()

                print(f"  RESULT: {len(df)} matches, {len(finished)} with xG")
                print(f"    NPxG coverage: {has_npxg}/{len(finished)} matches")
                print(f"    PPDA coverage: {has_ppda}/{len(finished)} matches")
                print(f"    Deep coverage: {has_deep}/{len(finished)} matches")

                # Show team names
                teams = sorted(set(df["home_team"]) | set(df["away_team"]))
                print(f"    Teams ({len(teams)}): {', '.join(teams[:5])}...")

                results[season_str] = {
                    "rows": len(df),
                    "finished": len(finished),
                    "npxg": int(has_npxg),
                    "ppda": int(has_ppda),
                    "deep": int(has_deep),
                    "teams": len(teams),
                }
        except Exception as exc:
            print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results[season_str] = {"rows": 0, "error": str(exc)}

    return results


# ============================================================================
# Test 3: Database state — what MatchStats do we have for EPL?
# ============================================================================

def test_db_state() -> dict:
    """Check current DB MatchStats for EPL by season."""
    divider("TEST 3 — Database MatchStat State (Cloud DB)")

    from src.database.db import get_session
    from src.database.models import Match, MatchStat, League
    from sqlalchemy import func

    results = {}

    try:
        with get_session() as session:
            # Find EPL league ID
            epl = session.query(League).filter_by(short_name="EPL").first()
            if not epl:
                print("  EPL league not found in DB")
                return {"error": "no EPL in DB"}

            print(f"  EPL league_id = {epl.id}")
            print()

            # Get match and stat counts per season
            season_data = (
                session.query(
                    Match.season,
                    func.count(Match.id).label("match_count"),
                )
                .filter(Match.league_id == epl.id)
                .group_by(Match.season)
                .order_by(Match.season)
                .all()
            )

            for season_str, match_count in season_data:
                # Count MatchStats for this season
                stat_count = (
                    session.query(func.count(MatchStat.id))
                    .join(Match, MatchStat.match_id == Match.id)
                    .filter(
                        Match.league_id == epl.id,
                        Match.season == season_str,
                    )
                    .scalar()
                )

                # Count MatchStats with NPxG (rich stats)
                npxg_count = (
                    session.query(func.count(MatchStat.id))
                    .join(Match, MatchStat.match_id == Match.id)
                    .filter(
                        Match.league_id == epl.id,
                        Match.season == season_str,
                        MatchStat.npxg.isnot(None),
                    )
                    .scalar()
                )

                # Count MatchStats with set_piece_xg (shot-level breakdown)
                shot_xg_count = (
                    session.query(func.count(MatchStat.id))
                    .join(Match, MatchStat.match_id == Match.id)
                    .filter(
                        Match.league_id == epl.id,
                        Match.season == season_str,
                        MatchStat.set_piece_xg.isnot(None),
                    )
                    .scalar()
                )

                expected_stats = match_count * 2  # home + away per match
                gap = expected_stats - stat_count

                marker = "✅" if gap == 0 else "⚠️" if stat_count > 0 else "❌"

                print(
                    f"  {marker} {season_str}: "
                    f"{match_count} matches, "
                    f"{stat_count}/{expected_stats} stats "
                    f"(gap={gap}), "
                    f"{npxg_count} with NPxG, "
                    f"{shot_xg_count} with shot_xg"
                )

                results[season_str] = {
                    "matches": match_count,
                    "stats": stat_count,
                    "expected": expected_stats,
                    "gap": gap,
                    "npxg": npxg_count,
                    "shot_xg": shot_xg_count,
                }

    except Exception as exc:
        print(f"  DB EXCEPTION: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return {"error": str(exc)}

    return results


# ============================================================================
# Summary & Recommendations
# ============================================================================

def print_summary(raw_results: dict, scraper_results: dict, db_results: dict) -> None:
    """Print final diagnosis and recommended fix."""
    divider("DIAGNOSIS SUMMARY")

    # Check if raw API works
    api_ok = all(
        raw_results.get(s, {}).get("match_data_count", 0) > 0
        for s in PROBLEM_SEASONS
    )
    team_ok = all(
        raw_results.get(s, {}).get("team_data_count", 0) > 0
        for s in PROBLEM_SEASONS
    )

    # Check if our scraper works
    scraper_ok = all(
        scraper_results.get(s, {}).get("rows", 0) > 0
        for s in PROBLEM_SEASONS
    )

    # Check DB gaps
    has_db_gaps = any(
        db_results.get(s, {}).get("gap", 1) > 0
        for s in PROBLEM_SEASONS
    )

    print(f"  Raw API match data accessible:  {'✅ YES' if api_ok else '❌ NO'}")
    print(f"  Raw API team data accessible:   {'✅ YES' if team_ok else '❌ NO'}")
    print(f"  Our scraper produces data:      {'✅ YES' if scraper_ok else '❌ NO'}")
    print(f"  DB has data gaps:               {'⚠️ YES' if has_db_gaps else '✅ NO'}")

    print()

    if api_ok and team_ok and scraper_ok and has_db_gaps:
        print("  DIAGNOSIS: Understat data is available and our scraper works.")
        print("  The backfill failure was likely a TRANSIENT issue (rate limit,")
        print("  network timeout, or session expiry during the GitHub Actions run).")
        print()
        print("  RECOMMENDED FIX:")
        print("    Re-run the Understat backfill for just these two seasons:")
        print()
        print("    python scripts/backfill_historical.py understat "
              "--league EPL --seasons 2022-23 2023-24")
        print("    python scripts/backfill_historical.py shot-xg "
              "--league EPL --seasons 2022-23 2023-24")
        print()
        print("  Then verify features are recomputed:")
        print("    python scripts/backfill_historical.py features "
              "--league EPL --seasons 2022-23 2023-24")

    elif not api_ok or not team_ok:
        print("  DIAGNOSIS: Understat API is NOT returning data for these seasons.")
        print("  This may be a permanent change in Understat's data availability,")
        print("  or the understatapi package needs updating.")
        print()
        print("  RECOMMENDED FIX:")
        print("    1. Check if understatapi has a newer version: pip install -U understatapi")
        print("    2. Try accessing https://understat.com/league/EPL/2022 in a browser")
        print("    3. If data exists on the page but not via API, consider direct scraping")

    elif not scraper_ok:
        print("  DIAGNOSIS: Raw API works but our scraper fails.")
        print("  There may be a bug in our team name mapping or date parsing")
        print("  for these seasons. Check the scraper logs above for details.")

    elif not has_db_gaps:
        print("  DIAGNOSIS: All data is present! No gaps to fill.")
        print("  The backfill errors were transient and data was loaded on a")
        print("  previous successful run.")

    print()


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    print("=" * 70)
    print("  BetVector — Understat Data Gap Diagnostic")
    print(f"  Testing seasons: {', '.join(PROBLEM_SEASONS)}")
    print(f"  Control season:  {WORKING_SEASON}")
    print("=" * 70)

    start = time.time()

    # Test 1: Raw understatapi
    raw_results = test_raw_api()

    # Test 2: Our scraper
    scraper_results = test_our_scraper()

    # Test 3: DB state
    db_results = test_db_state()

    # Summary
    print_summary(raw_results, scraper_results, db_results)

    elapsed = time.time() - start
    print(f"  Total elapsed: {elapsed:.1f}s")
    print()


if __name__ == "__main__":
    main()
