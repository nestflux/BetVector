"""
BetVector World Cup 2026 — Tournament Simulator (WC-04-02)
===========================================================
Monte Carlo simulation of the entire WC 2026 tournament.

Produces advancement probabilities for all 48 teams:
  - P(advance from group), P(reach R32), P(reach R16), P(reach QF),
    P(reach SF), P(reach final), P(win tournament)

Uses Poisson model (WC-04-01) to generate match-level goal samples.
Already-decided matches use actual results — only unplayed matches
are simulated.

2026 format:
  - 12 groups of 4 teams (A-L)
  - Top 2 per group advance (24 teams)
  - 8 best third-placed teams advance (32 total)
  - Knockout: R32 → R16 → QF → SF → Final
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

import numpy as np
from scipy.stats import poisson
from sqlalchemy import select

from src.database.db import get_session
from src.world_cup.models import WCMatch, WCTeam
from src.world_cup.predictor import WCPoissonPredictor

logger = logging.getLogger(__name__)

# Knockout bracket progression — pairs of match indices from the previous round
R16_BRACKET = {1: (1, 2), 2: (3, 4), 3: (5, 6), 4: (7, 8),
               5: (9, 10), 6: (11, 12), 7: (13, 14), 8: (15, 16)}
QF_BRACKET = {1: (1, 2), 2: (3, 4), 3: (5, 6), 4: (7, 8)}
SF_BRACKET = {1: (1, 2), 2: (3, 4)}


def simulate_tournament(
    predictor: WCPoissonPredictor,
    n_sims: int = 10000,
    seed: int = 42,
) -> dict:
    """
    Run Monte Carlo simulation of the entire WC 2026 tournament.

    Returns dict with:
      - team_probs: {team_name: {stage: probability}}
      - n_sims: number of simulations run
      - elapsed_seconds: wall-clock time
    """
    rng = np.random.default_rng(seed)
    start = time.time()

    with get_session() as session:
        teams = session.execute(select(WCTeam)).scalars().all()
        matches = session.execute(
            select(WCMatch).order_by(WCMatch.date)
        ).scalars().all()

    team_map = {t.id: t for t in teams}
    team_name_map = {t.id: t.name for t in teams}

    # Build group membership
    groups = defaultdict(list)
    for t in teams:
        groups[t.group_letter].append(t.id)

    # Separate finished and scheduled group matches
    finished_group = [m for m in matches if m.stage == "group" and m.status == "finished"]
    scheduled_group = [m for m in matches if m.stage == "group" and m.status != "finished"]

    # Build lambda cache for scheduled matches
    lambda_cache = {}
    for m in scheduled_group:
        pred = predictor.predict(m.id)
        if pred:
            lambda_cache[m.id] = (pred["lambda_home"], pred["lambda_away"])
        else:
            lambda_cache[m.id] = (1.3, 1.1)

    # Count trackers
    stages = ["group", "r32", "r16", "qf", "sf", "final", "winner"]
    counts = {team_name_map[t.id]: {s: 0 for s in stages} for t in teams}

    for _ in range(n_sims):
        # 1. Simulate group stage
        standings = _simulate_groups(
            groups, finished_group, scheduled_group, lambda_cache, rng,
        )

        # Track group advancement
        advancing_32 = set()
        for group_letter, table in standings.items():
            for pos, (tid, pts, gd, gf) in enumerate(table):
                if pos < 2:
                    advancing_32.add(tid)
                    counts[team_name_map[tid]]["group"] += 1

        # 2. Select 8 best third-placed teams
        thirds = []
        for group_letter, table in standings.items():
            if len(table) >= 3:
                tid, pts, gd, gf = table[2]
                thirds.append((tid, pts, gd, gf, group_letter))

        thirds.sort(key=lambda x: (-x[1], -x[2], -x[3]))
        best_thirds = thirds[:8]
        for tid, pts, gd, gf, gl in best_thirds:
            advancing_32.add(tid)
            counts[team_name_map[tid]]["group"] += 1

        # 3. Build R32 bracket
        group_winners = {}
        group_runners = {}
        for gl, table in standings.items():
            if len(table) >= 2:
                group_winners[gl] = table[0][0]
                group_runners[gl] = table[1][0]

        # Map third-place slots to actual teams
        third_teams = [t[0] for t in best_thirds]

        r32_matchups = _build_r32(group_winners, group_runners, third_teams)

        # 4. Simulate knockout rounds
        r32_winners = _simulate_knockout_round(
            r32_matchups, team_map, predictor, rng, counts, team_name_map, "r32",
        )

        r16_matchups = [(r32_winners[a - 1], r32_winners[b - 1])
                        for a, b in R16_BRACKET.values()
                        if a - 1 < len(r32_winners) and b - 1 < len(r32_winners)]
        r16_winners = _simulate_knockout_round(
            r16_matchups, team_map, predictor, rng, counts, team_name_map, "r16",
        )

        qf_matchups = [(r16_winners[a - 1], r16_winners[b - 1])
                       for a, b in QF_BRACKET.values()
                       if a - 1 < len(r16_winners) and b - 1 < len(r16_winners)]
        qf_winners = _simulate_knockout_round(
            qf_matchups, team_map, predictor, rng, counts, team_name_map, "qf",
        )

        sf_matchups = [(qf_winners[a - 1], qf_winners[b - 1])
                       for a, b in SF_BRACKET.values()
                       if a - 1 < len(qf_winners) and b - 1 < len(qf_winners)]
        sf_winners = _simulate_knockout_round(
            sf_matchups, team_map, predictor, rng, counts, team_name_map, "sf",
        )

        # Final
        if len(sf_winners) >= 2:
            final_matchup = [(sf_winners[0], sf_winners[1])]
            final_winner = _simulate_knockout_round(
                final_matchup, team_map, predictor, rng, counts, team_name_map, "final",
            )
            if final_winner:
                counts[team_name_map[final_winner[0]]]["winner"] += 1

    elapsed = time.time() - start

    # Convert counts to probabilities
    team_probs = {}
    for name, stage_counts in counts.items():
        team_probs[name] = {s: c / n_sims for s, c in stage_counts.items()}

    # Verify winner probabilities sum to ~1.0
    winner_sum = sum(p.get("winner", 0) for p in team_probs.values())
    logger.info("Winner probability sum: %.4f (should be ~1.0)", winner_sum)

    return {
        "team_probs": team_probs,
        "n_sims": n_sims,
        "elapsed_seconds": elapsed,
        "winner_sum": winner_sum,
    }


def _simulate_groups(
    groups: dict, finished: list, scheduled: list,
    lambda_cache: dict, rng,
) -> dict:
    """Simulate all group matches and return final standings per group."""
    points = defaultdict(int)
    gd = defaultdict(int)
    gf = defaultdict(int)
    # Head-to-head record: h2h[(A,B)] = points A earned against B
    h2h_pts = defaultdict(int)

    def _record(hid, aid, hg, ag):
        gf[hid] += hg
        gf[aid] += ag
        gd[hid] += hg - ag
        gd[aid] += ag - hg
        if hg > ag:
            points[hid] += 3
            h2h_pts[(hid, aid)] += 3
        elif hg == ag:
            points[hid] += 1
            points[aid] += 1
            h2h_pts[(hid, aid)] += 1
            h2h_pts[(aid, hid)] += 1
        else:
            points[aid] += 3
            h2h_pts[(aid, hid)] += 3

    for m in finished:
        _record(m.home_team_id, m.away_team_id, m.home_goals, m.away_goals)

    for m in scheduled:
        lh, la = lambda_cache.get(m.id, (1.3, 1.1))
        _record(m.home_team_id, m.away_team_id, rng.poisson(lh), rng.poisson(la))

    # FIFA tiebreaker: points → head-to-head → GD → GF
    def _sort_key(tid, group_tids):
        h2h = sum(h2h_pts[(tid, other)] for other in group_tids if other != tid)
        return (-points[tid], -h2h, -gd[tid], -gf[tid])

    standings = {}
    for gl, team_ids in groups.items():
        table = [(tid, points[tid], gd[tid], gf[tid]) for tid in team_ids]
        table.sort(key=lambda x: _sort_key(x[0], team_ids))
        standings[gl] = table

    return standings


def _build_r32(
    winners: dict, runners: dict, third_teams: list,
) -> list[tuple[int, int]]:
    """
    Build R32 matchups from group results.

    Structure (16 matches, 32 teams):
      - 8 matches: group winners vs runners-up (cross-group paired)
      - 4 matches: group winners vs third-place teams
      - 4 matches: runners-up vs third-place teams

    This ensures third-place teams face seeded opponents (winners/runners)
    rather than each other, consistent with FIFA's approach to bracket
    balance and competitive fairness.
    """
    matchups = []

    # 8 winner-vs-runner cross-group matchups
    wr_pairs = [
        ("C", "D"), ("D", "C"), ("G", "H"), ("H", "G"),
        ("I", "K"), ("K", "I"), ("J", "L"), ("L", "J"),
    ]
    for w_group, r_group in wr_pairs:
        w = winners.get(w_group)
        r = runners.get(r_group)
        if w and r:
            matchups.append((w, r))

    # 4 winner-vs-third matchups (groups A, B, E, F winners face thirds)
    winner_vs_third_groups = ["A", "B", "E", "F"]
    for i, gl in enumerate(winner_vs_third_groups):
        w = winners.get(gl)
        if w and i < len(third_teams):
            matchups.append((w, third_teams[i]))

    # 4 runner-vs-third matchups (groups A, B, E, F runners face remaining thirds)
    runner_vs_third_groups = ["A", "B", "E", "F"]
    for i, gl in enumerate(runner_vs_third_groups):
        r = runners.get(gl)
        idx = i + 4
        if r and idx < len(third_teams):
            matchups.append((r, third_teams[idx]))

    return matchups


def _simulate_knockout_round(
    matchups: list[tuple[int, int]],
    team_map: dict,
    predictor: WCPoissonPredictor,
    rng,
    counts: dict,
    name_map: dict,
    stage: str,
) -> list[int]:
    """
    Simulate a knockout round. Returns list of winning team IDs.

    Knockout matches can't end in draws — if 90-min result is level,
    the match goes to extra time + penalties. We model this as a
    coin flip with slight Elo skew (research shows penalties are
    roughly 50/50 with modest home/quality advantage).
    """
    winners = []
    for home_id, away_id in matchups:
        home = team_map.get(home_id)
        away = team_map.get(away_id)
        if not home or not away:
            continue

        # Use Elo-based lambdas — knockout stages don't have pre-computed
        # WCFeature rows (those are only for scheduled group matches),
        # so we derive lambdas from Elo difference directly.
        elo_h = home.elo_rating or 1500
        elo_a = away.elo_rating or 1500
        elo_diff = elo_h - elo_a

        # Neutral venue in knockouts — no home advantage boost
        base_lambda = 1.15
        elo_factor = elo_diff / 667.0
        lh = max(0.3, base_lambda + elo_factor * 0.4)
        la = max(0.3, base_lambda - elo_factor * 0.4)

        # Knockout deflation — teams prioritize defense when elimination is at stake
        lh *= 0.85
        la *= 0.85

        hg = rng.poisson(lh)
        ag = rng.poisson(la)

        if hg > ag:
            winner = home_id
        elif ag > hg:
            winner = away_id
        else:
            # Penalties are roughly 50/50 with a slight Elo edge
            pen_prob = np.clip(0.5 + elo_diff / 2000.0, 0.35, 0.65)
            winner = home_id if rng.random() < pen_prob else away_id

        winners.append(winner)
        counts[name_map[winner]][stage] += 1

    return winners


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from src.database.db import init_db

    init_db()

    print("=== Training Predictor ===")
    predictor = WCPoissonPredictor(alpha=1.0)
    diag = predictor.fit()
    print(f"Training: {diag.get('n_matches', 0)} matches, rho={diag.get('rho', 0):.4f}")

    print("\n=== Running Tournament Simulation (10,000 sims) ===")
    result = simulate_tournament(predictor, n_sims=10000, seed=42)
    print(f"Elapsed: {result['elapsed_seconds']:.1f}s")
    print(f"Winner prob sum: {result['winner_sum']:.4f}")

    print("\n=== Tournament Winner Probabilities ===")
    probs = result["team_probs"]
    by_winner = sorted(probs.items(), key=lambda x: -x[1].get("winner", 0))

    print(f"{'Team':<25s} {'Group':>6s} {'R32':>6s} {'R16':>6s} {'QF':>6s} {'SF':>6s} {'Final':>6s} {'Win':>6s}")
    print("-" * 85)
    for name, p in by_winner[:20]:
        print(
            f"{name:<25s} "
            f"{p.get('group', 0):>5.1%} "
            f"{p.get('r32', 0):>5.1%} "
            f"{p.get('r16', 0):>5.1%} "
            f"{p.get('qf', 0):>5.1%} "
            f"{p.get('sf', 0):>5.1%} "
            f"{p.get('final', 0):>5.1%} "
            f"{p.get('winner', 0):>5.1%}"
        )

    # Sanity check: bookmaker favorites should be in top 5
    top5 = [name for name, _ in by_winner[:5]]
    expected = {"France", "Spain", "Argentina", "England", "Brazil", "Germany"}
    overlap = set(top5) & expected
    print(f"\nTop 5: {top5}")
    print(f"Expected favorites in top 5: {overlap} ({len(overlap)}/5)")
