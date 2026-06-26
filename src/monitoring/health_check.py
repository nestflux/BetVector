"""
BetVector — Data Health Check engine (DH-01)
============================================
A read-only diagnostics engine that answers one question the Model Health page
never does: **is the data actually where it should be, and is it fresh?**

Model Health watches model *accuracy* (Brier, calibration, CLV) on already-settled
bets. This engine watches the *plumbing* — whether each source is still streaming
in, whether upcoming fixtures have odds and predictions, and (the reason this exists)
whether the league/World-Cup standings can actually be filled. The classic failure is
a rescheduled fixture leaving an orphan ``scheduled`` stub that never flips to
``finished``; the standings query only counts finished matches, so those results
silently vanish from the table. ``cleanup_stale_stubs`` sweeps them, but nothing
*alarmed* when they appeared — that tripwire is the standings check below.

Five groups of checks:
  1. Connectivity   — DB reachable; which backend (the Neon-vs-SQLite split-brain
                      tripwire); required ingestion API keys present.
  2. Source freshness — per source, how long since the last row landed vs its cadence,
                      plus the remaining Odds API monthly budget.
  3. Coverage       — of the upcoming fixtures, what % have odds and predictions
                      (the "all-grey badges / no odds" symptom), and any finished
                      match with NULL goals (corrupts standings).
  4. Standings integrity — stale scheduled stubs (league + World Cup) that would
                      leave a table short.
  5. Last pipeline run — did the most recent morning run finish, recently, with output?

Design: every check is a SELECT — **read-only**, never writes, never touches the
model/value/bet path, $0. ``session``, ``now``, the config thresholds, the env, and
the odds-budget file path are all injectable, so the whole engine is unit-testable
against a seeded in-memory database. Thresholds live in ``config/settings.yaml``
(``health:`` block) with documented defaults here, so nothing is hardcoded-only.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from src.config import config, PROJECT_ROOT
from src.database.db import get_session
from src.database.models import (
    ClubElo,
    Match,
    MatchStat,
    Odds,
    PipelineRun,
    Prediction,
    TeamMarketValue,
    Weather,
)

# Status levels. SKIP = "not applicable right now" (e.g. no upcoming fixtures, or
# the World Cup tables are empty out of season) — it never worsens the overall verdict.
OK = "ok"
WARN = "warn"
FAIL = "fail"
SKIP = "skip"
_RANK = {SKIP: -1, OK: 0, WARN: 1, FAIL: 2}


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """One health check's outcome. ``value``/``threshold`` are optional context for
    the renderers (the CLI and dashboard) to show the actual number behind the verdict."""
    group: str
    name: str
    status: str
    detail: str
    value: Optional[object] = None
    threshold: Optional[object] = None


@dataclass
class HealthReport:
    generated_at: str
    backend: str
    overall: str
    checks: list = field(default_factory=list)

    def by_group(self) -> "dict[str, list]":
        """Checks grouped by their ``group``, preserving insertion order."""
        out: "dict[str, list]" = {}
        for c in self.checks:
            out.setdefault(c.group, []).append(c)
        return out

    def summary(self) -> "dict[str, int]":
        """Count of checks at each status level."""
        counts = {OK: 0, WARN: 0, FAIL: 0, SKIP: 0}
        for c in self.checks:
            counts[c.status] = counts.get(c.status, 0) + 1
        return counts


def _overall(checks: "list[CheckResult]") -> str:
    """The worst status across all checks (SKIP/OK → ok, any WARN → warn, any FAIL → fail)."""
    worst = OK
    for c in checks:
        if _RANK.get(c.status, 0) > _RANK.get(worst, 0):
            worst = c.status
    return worst


# ---------------------------------------------------------------------------
# Config — defaults here, overridable from settings.yaml (health:) and per-call
# ---------------------------------------------------------------------------

HEALTH_DEFAULTS = {
    # Max age (hours) before a source is WARN / FAIL, by cadence class.
    "freshness_hours": {
        "live": {"warn": 6, "fail": 24},      # bookmaker odds — pulled every run
        "daily": {"warn": 36, "fail": 72},     # results, predictions, stats, Elo, weather
        "weekly": {"warn": 192, "fail": 384},  # Transfermarkt squad values (8d / 16d)
    },
    "coverage": {
        "upcoming_days": 7,        # window of fixtures to check coverage for
        "min_odds_pct": 0.70,      # WARN if fewer than this share of upcoming have odds
        "min_pred_pct": 0.90,      # WARN if fewer than this share of upcoming have a prediction
    },
    "standings": {
        "stale_stub_fail_count": 10,  # >= this many stale stubs escalates WARN → FAIL
    },
    "pipeline": {
        "morning_overdue_hours": 26,  # WARN if the last morning run is older than this
        "stuck_running_hours": 3,     # a run still "running" past this is treated as stuck/FAIL
    },
    # Reused from scraping.the_odds_api in settings.yaml; defaults mirror that block.
    "odds_api": {"warn_remaining": 100, "fail_remaining": 30},
    # Morning-pipeline alert: email the owner when the overall verdict is at least this
    # bad. Default "warn" so genuine issues (e.g. stale standings stubs, which register
    # as WARN) reach the owner; set to "fail" for failures only.
    "alert": {"min_status": "warn"},
}

# Ingestion API keys → the source they unlock. Missing key ⇒ that source can't run.
_INGESTION_KEYS = {
    "THE_ODDS_API_KEY": "The Odds API (live odds)",
    "API_FOOTBALL_KEY": "API-Football (results / odds / injuries)",
    "FOOTBALL_DATA_ORG_KEY": "Football-Data.org (results)",
    "SOCCERDATA_API_KEY": "Soccerdata (injuries / lineups)",
}

# Per-source freshness map: (label, ORM model, timestamp attr, cadence class,
# season_gated). ``season_gated`` sources only stream when the domestic leagues are
# actually playing — between seasons they are legitimately stale, so we SKIP rather
# than cry wolf. Odds, Elo and Transfermarkt update independently of the league
# calendar, so they are judged on age regardless.
_FRESHNESS_SOURCES = [
    ("Bookmaker odds", Odds, "captured_at", "live", True),
    ("Match results & fixtures", Match, "updated_at", "daily", True),
    ("Model predictions", Prediction, "created_at", "daily", True),
    ("Advanced stats (xG)", MatchStat, "created_at", "daily", True),
    ("Club Elo ratings", ClubElo, "created_at", "daily", False),
    ("Match-day weather", Weather, "created_at", "daily", True),
    ("Squad values (Transfermarkt)", TeamMarketValue, "created_at", "weekly", False),
]


def _get(root, path, default):
    """Walk an attribute path on the config namespace, returning ``default`` if any
    hop is missing/None. Lets the engine run with sane defaults before the ``health:``
    block is added to settings.yaml, and keeps every threshold config-driven (Rule 6)."""
    cur = root
    for key in path:
        try:
            cur = getattr(cur, key)
        except (AttributeError, KeyError, TypeError):
            return default
    return default if cur is None else cur


def resolve_config(override: Optional[dict] = None) -> dict:
    """Build the effective threshold dict: defaults ← settings.yaml(``health:``) ←
    per-call override. The odds-budget thresholds are read from the existing
    ``scraping.the_odds_api`` block so they are not duplicated."""
    cfg = copy.deepcopy(HEALTH_DEFAULTS)
    s = getattr(config, "settings", None)
    if s is not None:
        for cls in ("live", "daily", "weekly"):
            for bound in ("warn", "fail"):
                cfg["freshness_hours"][cls][bound] = _get(
                    s, ("health", "freshness_hours", cls, bound),
                    cfg["freshness_hours"][cls][bound])
        cfg["coverage"]["upcoming_days"] = _get(
            s, ("health", "coverage", "upcoming_days"), cfg["coverage"]["upcoming_days"])
        cfg["coverage"]["min_odds_pct"] = _get(
            s, ("health", "coverage", "min_odds_pct"), cfg["coverage"]["min_odds_pct"])
        cfg["coverage"]["min_pred_pct"] = _get(
            s, ("health", "coverage", "min_pred_pct"), cfg["coverage"]["min_pred_pct"])
        cfg["standings"]["stale_stub_fail_count"] = _get(
            s, ("health", "standings", "stale_stub_fail_count"),
            cfg["standings"]["stale_stub_fail_count"])
        cfg["pipeline"]["morning_overdue_hours"] = _get(
            s, ("health", "pipeline", "morning_overdue_hours"),
            cfg["pipeline"]["morning_overdue_hours"])
        cfg["pipeline"]["stuck_running_hours"] = _get(
            s, ("health", "pipeline", "stuck_running_hours"),
            cfg["pipeline"]["stuck_running_hours"])
        # Reuse the Odds API budget thresholds already defined for scraping.
        cfg["odds_api"]["warn_remaining"] = _get(
            s, ("scraping", "the_odds_api", "warning_threshold"),
            cfg["odds_api"]["warn_remaining"])
        cfg["odds_api"]["fail_remaining"] = _get(
            s, ("scraping", "the_odds_api", "hard_stop_threshold"),
            cfg["odds_api"]["fail_remaining"])
        cfg["alert"]["min_status"] = _get(
            s, ("health", "alert", "min_status"), cfg["alert"]["min_status"])
    if override:
        _deep_merge(cfg, override)
    return cfg


def _deep_merge(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------------------
# Timestamp helpers — every stored timestamp is an ISO *string* (func.now()),
# and the separator differs between SQLite ("YYYY-MM-DD HH:MM:SS") and Postgres,
# so parse tolerantly rather than relying on lexical comparison.
# ---------------------------------------------------------------------------

def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    s = str(value).strip()
    # Drop a timezone suffix (Z or ±HH:MM) — comparisons are UTC-vs-UTC. Only look
    # past the date (s[10:]) so the date's own hyphens aren't mistaken for an offset.
    if s.endswith("Z"):
        s = s[:-1]
    tail = s[10:]
    if "+" in tail:
        s = s[:10] + tail.split("+", 1)[0]
    elif "-" in tail:
        s = s[:10] + tail.split("-", 1)[0]
    s = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _age_hours(ts_value, now: datetime) -> Optional[float]:
    """Hours between a stored ISO timestamp and ``now`` (UTC). None if unparseable.
    A future timestamp (clock skew) clamps to 0 so it reads as fresh, not stale."""
    parsed = _parse_iso(ts_value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds() / 3600.0)


def _humanize_hours(hours: Optional[float]) -> str:
    if hours is None:
        return "unknown"
    if hours < 1:
        return f"{int(round(hours * 60))} min ago"
    if hours < 48:
        return f"{hours:.1f} h ago"
    return f"{hours / 24:.1f} days ago"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_backend(session: Session) -> CheckResult:
    """Which database are we actually talking to? The pipeline and dashboard must
    both be on Neon; falling back to local SQLite mid-pipeline is the split-brain
    footgun where the cloud DB silently stops updating."""
    try:
        name = session.get_bind().dialect.name
    except Exception:
        name = "unknown"
    if name == "postgresql":
        return CheckResult("Connectivity", "Database backend", OK,
                           "Neon PostgreSQL (the shared cloud database).", value=name)
    if name == "sqlite":
        return CheckResult("Connectivity", "Database backend", WARN,
                           "Local SQLite. Expected for local dev, but if this is a "
                           "pipeline/cloud run the cloud DB is NOT being updated "
                           "(split-brain risk).", value=name)
    return CheckResult("Connectivity", "Database backend", WARN,
                       f"Unrecognised backend '{name}'.", value=name)


def _check_api_keys(env: dict) -> CheckResult:
    """Are the ingestion API keys present? A vanished key is a silent way for a
    source to stop streaming. Values are never read or printed — only presence."""
    missing = [f"{key} → {src}" for key, src in _INGESTION_KEYS.items() if not env.get(key)]
    if not missing:
        return CheckResult("Connectivity", "Ingestion API keys", OK,
                           f"All {len(_INGESTION_KEYS)} ingestion keys present.")
    return CheckResult("Connectivity", "Ingestion API keys", WARN,
                       "Missing from the environment (may instead be in Streamlit "
                       "secrets): " + "; ".join(missing), value=len(missing))


def _freshness_status(age_h: Optional[float], cls: str, cfg: dict) -> str:
    if age_h is None:
        return SKIP
    bounds = cfg["freshness_hours"][cls]
    if age_h >= bounds["fail"]:
        return FAIL
    if age_h >= bounds["warn"]:
        return WARN
    return OK


def _leagues_active(session: Session, now: datetime, cfg: dict) -> bool:
    """Are the domestic leagues currently playing? True if any fixture is scheduled in
    the coverage window ahead, or any match finished in the last few days. Between
    seasons both are empty, and league-tied sources are stale by design — used to
    suppress off-season false alarms on the season-gated freshness checks."""
    days = cfg["coverage"]["upcoming_days"]
    today = now.date().isoformat()
    soon = (now.date() + timedelta(days=days)).isoformat()
    recent = (now.date() - timedelta(days=3)).isoformat()
    upcoming = session.query(Match.id).filter(
        Match.status == "scheduled", Match.date >= today, Match.date <= soon).first()
    if upcoming:
        return True
    just_played = session.query(Match.id).filter(
        Match.status == "finished", Match.date >= recent, Match.date <= today).first()
    return just_played is not None


def _check_source_freshness(session: Session, now: datetime, cfg: dict) -> "list[CheckResult]":
    """Per source: how long since the most recent row landed, vs its cadence. Season-
    gated sources are skipped (not failed) when the leagues are between seasons."""
    active = _leagues_active(session, now, cfg)
    results = []
    for label, model, ts_attr, cls, gated in _FRESHNESS_SOURCES:
        latest = session.query(func.max(getattr(model, ts_attr))).scalar()
        if latest is None:
            results.append(CheckResult("Source freshness", label, SKIP,
                                       "No rows yet — nothing ingested for this source.",
                                       value=None))
            continue
        age = _age_hours(latest, now)
        if gated and not active:
            results.append(CheckResult(
                "Source freshness", label, SKIP,
                f"Last update {_humanize_hours(age)}, but no recent or upcoming league "
                f"fixtures — off-season, so staleness is expected.",
                value=round(age, 1) if age is not None else None))
            continue
        status = _freshness_status(age, cls, cfg)
        bounds = cfg["freshness_hours"][cls]
        results.append(CheckResult(
            "Source freshness", label, status,
            f"Last update {_humanize_hours(age)} ({cls} cadence; "
            f"warn ≥{bounds['warn']}h, fail ≥{bounds['fail']}h).",
            value=round(age, 1) if age is not None else None,
            threshold=bounds))
    return results


def _check_odds_budget(cfg: dict, budget_path: Path) -> CheckResult:
    """Remaining Odds API monthly budget — run out and live odds stop flowing."""
    if not budget_path.exists():
        return CheckResult("Source freshness", "Odds API budget", SKIP,
                           "No budget file yet (data/logs/odds_api_budget.json).")
    try:
        data = json.loads(budget_path.read_text())
        remaining = int(data.get("remaining"))
    except Exception as exc:
        return CheckResult("Source freshness", "Odds API budget", WARN,
                           f"Budget file unreadable: {exc}")
    warn_at = cfg["odds_api"]["warn_remaining"]
    fail_at = cfg["odds_api"]["fail_remaining"]
    if remaining < fail_at:
        status = FAIL
    elif remaining < warn_at:
        status = WARN
    else:
        status = OK
    return CheckResult("Source freshness", "Odds API budget", status,
                       f"{remaining} requests left this month "
                       f"(warn <{warn_at}, fail <{fail_at}).",
                       value=remaining, threshold={"warn": warn_at, "fail": fail_at})


def _check_upcoming_coverage(session: Session, now: datetime, cfg: dict) -> "list[CheckResult]":
    """Of the fixtures kicking off in the next N days, how many have odds and a
    prediction? Low coverage is exactly the 'all-grey badges / no odds' symptom."""
    days = cfg["coverage"]["upcoming_days"]
    today = now.date().isoformat()
    end = (now.date() + timedelta(days=days)).isoformat()
    ids = [r[0] for r in session.query(Match.id).filter(
        Match.status == "scheduled", Match.date >= today, Match.date <= end).all()]
    if not ids:
        return [CheckResult("Coverage", f"Upcoming fixtures (next {days}d)", SKIP,
                            "No scheduled fixtures in the window — nothing to cover.")]
    n = len(ids)
    with_odds = session.query(func.count(distinct(Odds.match_id))).filter(
        Odds.match_id.in_(ids)).scalar() or 0
    with_pred = session.query(func.count(distinct(Prediction.match_id))).filter(
        Prediction.match_id.in_(ids)).scalar() or 0
    odds_pct, pred_pct = with_odds / n, with_pred / n
    out = [
        CheckResult("Coverage", f"Odds coverage (next {days}d)",
                    OK if odds_pct >= cfg["coverage"]["min_odds_pct"] else WARN,
                    f"{with_odds}/{n} upcoming fixtures have odds ({odds_pct:.0%}; "
                    f"target ≥{cfg['coverage']['min_odds_pct']:.0%}).",
                    value=round(odds_pct, 3), threshold=cfg["coverage"]["min_odds_pct"]),
        CheckResult("Coverage", f"Prediction coverage (next {days}d)",
                    OK if pred_pct >= cfg["coverage"]["min_pred_pct"] else WARN,
                    f"{with_pred}/{n} upcoming fixtures have a model prediction "
                    f"({pred_pct:.0%}; target ≥{cfg['coverage']['min_pred_pct']:.0%}).",
                    value=round(pred_pct, 3), threshold=cfg["coverage"]["min_pred_pct"]),
    ]
    return out


def _check_corrupt_results(session: Session) -> CheckResult:
    """Matches marked 'finished' but with NULL goals silently count as 0-0 in the
    standings aggregation — a real corruption, so any is a FAIL."""
    bad = session.query(func.count()).select_from(Match).filter(
        Match.status == "finished", Match.home_goals.is_(None)).scalar() or 0
    if bad == 0:
        return CheckResult("Standings integrity", "Finished matches have scores", OK,
                           "Every finished match has goals recorded.")
    return CheckResult("Standings integrity", "Finished matches have scores", FAIL,
                       f"{bad} match(es) are 'finished' but have NULL goals — these "
                       f"corrupt the standings (counted as 0-0).", value=bad)


def _check_stale_stubs(session: Session, now: datetime, cfg: dict) -> CheckResult:
    """THE standings tripwire: a match still 'scheduled' whose date is already in the
    past never flips to 'finished', so its result is missing and the table comes up
    short. ``cleanup_stale_stubs`` should sweep these every run."""
    today = now.date().isoformat()
    rows = session.query(Match.league_id, func.count()).filter(
        Match.status == "scheduled", Match.date < today).group_by(Match.league_id).all()
    total = sum(c for _lid, c in rows)
    if total == 0:
        return CheckResult("Standings integrity", "Stale scheduled stubs (leagues)", OK,
                           "No past-dated fixtures stuck as 'scheduled'.")
    fail_at = cfg["standings"]["stale_stub_fail_count"]
    status = FAIL if total >= fail_at else WARN
    return CheckResult("Standings integrity", "Stale scheduled stubs (leagues)", status,
                       f"{total} past-dated fixture(s) across {len(rows)} league(s) "
                       f"still 'scheduled' — results missing, standings will be short. "
                       f"cleanup_stale_stubs should postpone these (fail ≥{fail_at}).",
                       value=total, threshold=fail_at)


def _check_last_pipeline_run(session: Session, now: datetime, cfg: dict) -> CheckResult:
    """Did the most recent morning pipeline finish, recently, and actually produce
    predictions? Reads the pipeline_runs ledger.

    Season-gated: the morning run tracked here is the DOMESTIC LEAGUE pipeline, which
    is intentionally paused between seasons (its launchd crons are unloaded off-season).
    When the leagues aren't playing we SKIP rather than WARN — otherwise it would cry
    "the scheduled job may not be firing" for the whole off-season even though the pause
    is deliberate. (The World Cup pipeline is covered by its own freshness checks.)"""
    if not _leagues_active(session, now, cfg):
        return CheckResult("Pipeline", "Last morning run", SKIP,
                           "Domestic leagues are between seasons — the league morning "
                           "pipeline is intentionally paused, so no recent run is expected.")
    run = session.query(PipelineRun).filter(
        PipelineRun.run_type == "morning").order_by(
        PipelineRun.started_at.desc()).first()
    if run is None:
        return CheckResult("Pipeline", "Last morning run", SKIP,
                           "No morning runs recorded in pipeline_runs yet.")
    age = _age_hours(run.started_at, now)
    overdue = cfg["pipeline"]["morning_overdue_hours"]
    stuck = cfg["pipeline"]["stuck_running_hours"]
    when = _humanize_hours(age)
    if run.status == "failed":
        return CheckResult("Pipeline", "Last morning run", FAIL,
                           f"Last morning run FAILED ({when}). "
                           f"{(run.error_message or '').strip()[:160]}", value=run.status)
    if run.status == "running" and age is not None and age >= stuck:
        return CheckResult("Pipeline", "Last morning run", FAIL,
                           f"A morning run has been 'running' for {when} — likely stuck "
                           f"(zombie process).", value=run.status)
    preds = run.predictions_made or 0
    if age is not None and age >= overdue:
        return CheckResult("Pipeline", "Last morning run", WARN,
                           f"Last successful morning run was {when} (overdue ≥{overdue}h) "
                           f"— the scheduled job may not be firing.", value=round(age, 1))
    if run.status == "completed" and preds == 0:
        return CheckResult("Pipeline", "Last morning run", WARN,
                           f"Last morning run completed ({when}) but produced 0 "
                           f"predictions.", value=preds)
    return CheckResult("Pipeline", "Last morning run", OK,
                       f"Completed {when}: {preds} predictions, "
                       f"{run.value_bets_found or 0} value bets.", value=preds)


def _check_world_cup(session: Session, now: datetime, cfg: dict) -> "list[CheckResult]":
    """World-Cup-specific checks, only when the WC tables hold data (i.e. during the
    tournament window). Imported lazily so the engine never hard-depends on the WC
    module. Mirrors the league stale-stub + odds-freshness tripwires for the WC hub."""
    try:
        from src.world_cup.models import WCMatch, WCOdds
    except Exception:
        return []
    try:
        total_matches = session.query(func.count()).select_from(WCMatch).scalar() or 0
    except Exception:
        return []
    if total_matches == 0:
        return [CheckResult("World Cup", "Tournament data", SKIP,
                            "No World Cup matches loaded (out of tournament window).")]
    out = []
    today = now.date().isoformat()
    stale = session.query(func.count()).select_from(WCMatch).filter(
        WCMatch.status == "scheduled", WCMatch.date < today).scalar() or 0
    out.append(CheckResult("World Cup", "Stale WC stubs (group tables)",
                           OK if stale == 0 else WARN,
                           "No past-dated WC fixtures stuck as 'scheduled'." if stale == 0
                           else f"{stale} past-dated WC fixture(s) still 'scheduled' — "
                                f"group standings will be short.", value=stale))
    latest_odds = session.query(func.max(WCOdds.captured_at)).scalar()
    age = _age_hours(latest_odds, now)
    out.append(CheckResult("World Cup", "WC odds freshness",
                           _freshness_status(age, "live", cfg) if latest_odds else SKIP,
                           f"Last WC odds {_humanize_hours(age)}." if latest_odds
                           else "No WC odds captured yet.",
                           value=round(age, 1) if age is not None else None))
    return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _odds_budget_path(override: Optional[Path]) -> Path:
    if override is not None:
        return Path(override)
    return PROJECT_ROOT / "data" / "logs" / "odds_api_budget.json"


def _run_all(session: Session, now: datetime, cfg: dict, env: dict,
             budget_path: Path) -> "list[CheckResult]":
    checks: "list[CheckResult]" = [
        CheckResult("Connectivity", "Database reachable", OK, "SELECT 1 succeeded."),
        _check_backend(session),
        _check_api_keys(env),
    ]
    checks += _check_source_freshness(session, now, cfg)
    checks.append(_check_odds_budget(cfg, budget_path))
    checks += _check_upcoming_coverage(session, now, cfg)
    checks.append(_check_stale_stubs(session, now, cfg))
    checks.append(_check_corrupt_results(session))
    checks.append(_check_last_pipeline_run(session, now, cfg))
    checks += _check_world_cup(session, now, cfg)
    return checks


def run_health_checks(
    session: Optional[Session] = None,
    now: Optional[datetime] = None,
    config_override: Optional[dict] = None,
    env: Optional[dict] = None,
    odds_budget_path: Optional[Path] = None,
) -> HealthReport:
    """Run every health check and return a :class:`HealthReport`.

    All inputs are injectable for testing: pass a ``session`` bound to a seeded DB, a
    fixed ``now`` (UTC) for deterministic freshness, a ``config_override`` dict, an
    ``env`` dict for the API-key check, and an ``odds_budget_path``. With nothing
    passed it opens a real read-only session, uses the live config, ``os.environ``,
    and the real budget file."""
    now = now or datetime.utcnow()
    cfg = resolve_config(config_override)
    env = env if env is not None else dict(os.environ)
    budget_path = _odds_budget_path(odds_budget_path)
    generated_at = now.isoformat(timespec="seconds")

    def _build(sess: Session) -> HealthReport:
        backend = "unknown"
        try:
            backend = sess.get_bind().dialect.name
        except Exception:
            pass
        checks = _run_all(sess, now, cfg, env, budget_path)
        return HealthReport(generated_at, backend, _overall(checks), checks)

    if session is not None:
        return _build(session)

    try:
        with get_session() as sess:
            return _build(sess)
    except Exception as exc:
        # The database itself is unreachable — return a minimal FAIL report rather
        # than raising, so the CLI/dashboard can still render the bad news.
        return HealthReport(
            generated_at, "unknown", FAIL,
            [CheckResult("Connectivity", "Database reachable", FAIL,
                         f"Cannot connect to the database: {exc}")])
