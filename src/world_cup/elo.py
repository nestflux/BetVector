"""
BetVector World Cup 2026 — International Elo Calculator (WC-02-03)
===================================================================
Computes Elo ratings for all 48 WC teams from historical international
results (2018-2026) using the World Football Elo methodology.

Reference: https://www.eloratings.net/about

K-factors by tournament type:
    Friendly = 20, Qualifier = 25, Confederation tournament = 35,
    WC group = 40, WC knockout = 50

Goal difference multiplier:
    1 goal = 1.0, 2 goals = 1.5, 3+ goals = (11 + goal_diff) / 8

Expected result: W_e = 1 / (10^(-elo_diff / 400) + 1)

Home advantage: +100 true home, +50 same-continent neutral, 0 neutral
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from sqlalchemy import select

from src.database.db import get_session
from src.world_cup.models import WCHistoricalMatch, WCTeam

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"

# Map WC team names that differ from historical dataset names
WC_TO_HIST_NAME = {
    "USA": "United States",
}
HIST_TO_WC_NAME = {v: k for k, v in WC_TO_HIST_NAME.items()}


def _load_elo_config() -> dict:
    """Load Elo parameters from config/worldcup_2026.yaml."""
    config_path = CONFIG_DIR / "worldcup_2026.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data.get("elo", {})


def _build_confederation_map() -> dict[str, str]:
    """Build {team_name: confederation} from wc_teams for all 48 WC teams,
    plus a broader lookup from historical match opponents."""
    confed_map: dict[str, str] = {}
    with get_session() as session:
        teams = session.execute(select(WCTeam)).scalars().all()
        for t in teams:
            confed_map[t.name] = t.confederation
            hist_name = WC_TO_HIST_NAME.get(t.name, t.name)
            if hist_name != t.name:
                confed_map[hist_name] = t.confederation
    return confed_map


def _k_factor(tournament: str, cfg: dict) -> int:
    """Determine K-factor from tournament name."""
    k = cfg.get("k_factors", {})
    t = tournament.lower()
    if "world cup" in t and "qualification" not in t and "qualif" not in t:
        if "knockout" in t or "round of" in t or "quarter" in t or "semi" in t or "final" in t:
            return k.get("wc_knockout", 50)
        return k.get("wc_group", 40)
    if any(comp in t for comp in [
        "uefa euro", "euro ", "euros", "copa am", "african cup",
        "cup of nations", "afcon", "asian cup", "gold cup",
        "confederations cup", "finalissima",
        "concacaf nations league final",
    ]):
        if "qualification" not in t and "qualif" not in t:
            return k.get("confederation_tournament", 35)
    if "qualification" in t or "qualif" in t or "nations league" in t:
        return k.get("qualifier", 25)
    return k.get("friendly", 20)


def _goal_diff_multiplier(goal_diff: int) -> float:
    """Scale Elo update by margin of victory."""
    g = abs(goal_diff)
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11 + g) / 8


def _expected_result(elo_diff: float) -> float:
    """Expected win probability given Elo difference (home - away)."""
    return 1.0 / (10 ** (-elo_diff / 400) + 1)


def _home_advantage(
    home_team: str,
    away_team: str,
    neutral_venue: bool,
    confed_map: dict[str, str],
    cfg: dict,
) -> float:
    """
    +100 for true home match, +50 for partial home (home team plays on
    same continent as its confederation in a non-neutral venue where it
    isn't truly at home — e.g. confederation tournament hosted in another
    country), 0 for fully neutral.

    For historical data: neutral_venue=True → 0, neutral_venue=False → +100
    (true home). The +50 partial case primarily matters during WC tournaments
    where host nations play at home venues but the match is flagged neutral.
    """
    ha_cfg = cfg.get("home_advantage", {})
    if neutral_venue:
        return ha_cfg.get("neutral", 0)
    return ha_cfg.get("true_home", 100)


def _actual_result(home_goals: int, away_goals: int) -> float:
    """1.0 for home win, 0.5 for draw, 0.0 for away win."""
    if home_goals > away_goals:
        return 1.0
    if home_goals == away_goals:
        return 0.5
    return 0.0


def _resolve_name(name: str) -> str:
    """Map WC team name to historical dataset name."""
    return WC_TO_HIST_NAME.get(name, name)


def _resolve_to_wc_name(name: str) -> str:
    """Map historical dataset name back to WC team name."""
    return HIST_TO_WC_NAME.get(name, name)


def compute_international_elo() -> dict[str, float]:
    """
    Process all historical international matches chronologically and
    compute Elo ratings. Returns a dict of {team_name: elo_rating}
    for all teams encountered, then stores the 48 WC teams' ratings
    in wc_teams.elo_rating.
    """
    cfg = _load_elo_config()
    starting_elo = cfg.get("default_rating", 1500.0)
    min_year = cfg.get("min_year", 2018)
    regression_factor = cfg.get("regression_factor", 0.20)
    regression_cutoff = cfg.get("regression_cutoff_date", "2022-12-19")

    confed_map = _build_confederation_map()

    with get_session() as session:
        matches = session.execute(
            select(WCHistoricalMatch)
            .where(WCHistoricalMatch.date >= f"{min_year}-01-01")
            .order_by(WCHistoricalMatch.date)
        ).scalars().all()

        if not matches:
            logger.warning(
                "No historical matches found from %d onward — "
                "all teams will get default Elo %.0f. "
                "Run scripts/import_wc_history.py first.",
                min_year, starting_elo,
            )

        logger.info("Processing %d historical matches for Elo", len(matches))

        elos: dict[str, float] = {}
        regression_applied = False

        for match in matches:
            home = match.home_team
            away = match.away_team

            if home not in elos:
                elos[home] = starting_elo
            if away not in elos:
                elos[away] = starting_elo

            # Apply regression to mean at the 2022 WC cycle boundary
            if not regression_applied and match.date > regression_cutoff:
                _apply_regression(elos, starting_elo, regression_factor)
                regression_applied = True
                logger.info(
                    "Applied %.0f%% Elo regression to mean at %s",
                    regression_factor * 100,
                    regression_cutoff,
                )

            k = _k_factor(match.tournament or "Friendly", cfg)
            gd_mult = _goal_diff_multiplier(match.home_goals - match.away_goals)
            neutral = bool(match.neutral_venue)
            ha = _home_advantage(home, away, neutral, confed_map, cfg)

            elo_diff = elos[home] + ha - elos[away]
            w_e = _expected_result(elo_diff)
            w_a = _actual_result(match.home_goals, match.away_goals)

            delta = k * gd_mult * (w_a - w_e)
            elos[home] += delta
            elos[away] -= delta

        logger.info("Elo computed for %d teams", len(elos))

        # Store Elo ratings for the 48 WC teams
        wc_teams = session.execute(select(WCTeam)).scalars().all()
        updated = 0
        for team in wc_teams:
            hist_name = _resolve_name(team.name)
            if hist_name in elos:
                team.elo_rating = round(elos[hist_name], 1)
                updated += 1
            else:
                logger.warning(
                    "No Elo data for WC team %s (looked up as '%s')",
                    team.name,
                    hist_name,
                )
                team.elo_rating = starting_elo

        session.commit()
        logger.info("Stored Elo ratings for %d / %d WC teams", updated, len(wc_teams))

    return elos


def _apply_regression(
    elos: dict[str, float], mean: float, factor: float,
) -> None:
    """Pull all ratings toward the mean between WC cycles."""
    for team in elos:
        elos[team] = elos[team] + factor * (mean - elos[team])


def update_elo_after_match(
    home_team_name: str,
    away_team_name: str,
    home_goals: int,
    away_goals: int,
    tournament: str = "FIFA World Cup",
    neutral_venue: bool = True,
) -> tuple[float, float]:
    """
    Update Elo ratings for both teams after a single match (e.g. during
    the tournament). Reads current Elo from DB, computes delta, writes
    back. Returns (new_home_elo, new_away_elo).

    WC 2026 matches are neutral venue by default (USA/Canada/Mexico
    host cities, but most teams are not at home).
    """
    if home_goals is None or away_goals is None:
        raise ValueError(
            "Cannot update Elo: match has no result yet "
            f"(home_goals={home_goals}, away_goals={away_goals})"
        )

    cfg = _load_elo_config()
    starting_elo = cfg.get("default_rating", 1500.0)
    ha_cfg = cfg.get("home_advantage", {})

    with get_session() as session:
        home_team = session.execute(
            select(WCTeam).where(WCTeam.name == home_team_name)
        ).scalar_one_or_none()
        away_team = session.execute(
            select(WCTeam).where(WCTeam.name == away_team_name)
        ).scalar_one_or_none()

        if not home_team or not away_team:
            raise ValueError(
                f"Team not found: home={home_team_name}, away={away_team_name}"
            )

        home_elo = home_team.elo_rating or starting_elo
        away_elo = away_team.elo_rating or starting_elo

        k = _k_factor(tournament, cfg)
        gd_mult = _goal_diff_multiplier(home_goals - away_goals)

        # WC host nations get partial home advantage at their own venues
        if neutral_venue:
            ha = ha_cfg.get("neutral", 0)
        elif home_team.is_host:
            ha = ha_cfg.get("partial_home", 50)
        else:
            ha = ha_cfg.get("neutral", 0)

        elo_diff = home_elo + ha - away_elo
        w_e = _expected_result(elo_diff)
        w_a = _actual_result(home_goals, away_goals)

        delta = k * gd_mult * (w_a - w_e)
        new_home = round(home_elo + delta, 1)
        new_away = round(away_elo - delta, 1)

        home_team.elo_rating = new_home
        away_team.elo_rating = new_away
        session.commit()

        logger.info(
            "Elo update: %s %.1f->%.1f, %s %.1f->%.1f (K=%d, delta=%.1f)",
            home_team_name, home_elo, new_home,
            away_team_name, away_elo, new_away,
            k, delta,
        )

    return new_home, new_away


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from src.database.db import init_db

    init_db()
    elos = compute_international_elo()

    sorted_elos = sorted(elos.items(), key=lambda x: x[1], reverse=True)
    print("\n=== Top 20 International Elo Ratings ===")
    for i, (team, elo) in enumerate(sorted_elos[:20], 1):
        wc_name = _resolve_to_wc_name(team)
        marker = " *" if wc_name != team or team in WC_TO_HIST_NAME.values() else ""
        print(f"  {i:2d}. {team:<25s} {elo:7.1f}{marker}")

    print("\n=== 48 WC Team Elo Ratings ===")
    from sqlalchemy import select as sel

    with get_session() as session:
        teams = session.execute(
            sel(WCTeam).order_by(WCTeam.elo_rating.desc())
        ).scalars().all()
        for i, t in enumerate(teams, 1):
            print(f"  {i:2d}. {t.name:<25s} {t.elo_rating:7.1f}  (Group {t.group_letter})")
