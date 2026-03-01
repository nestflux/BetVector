"""
BetVector ORM Models — Core Tables (E2-02)
============================================
SQLAlchemy 2.0 ORM models for the 9 core tables defined in MP §6.
All models inherit from ``Base`` (defined in ``src.database.db``).

Tables defined here:
    1. users          — System users with bankroll & staking preferences
    2. leagues        — Tracked football leagues (EPL, etc.)
    3. seasons        — Season records per league
    4. teams          — Teams with cross-source name mappings
    5. matches        — Match fixtures and results
    6. match_stats    — Per-team match statistics (xG, shots, possession, etc.)
    7. odds           — Bookmaker odds for various markets
    8. features       — Computed features for model input
    9. predictions    — Model outputs (scoreline matrix + derived probabilities)

Additional tables (value_bets, bet_log, model_performance, pipeline_runs)
are defined in E2-03.  Self-improvement tables are defined in E2-04.
Weather table added for Open-Meteo match-day conditions (real-time data sources).

Usage::

    from src.database.db import get_session, init_db
    from src.database.models import User, League, Match

    init_db()  # Creates all tables

    with get_session() as session:
        user = User(name="Owner", email="owner@example.com", role="owner")
        session.add(user)
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text as sa_text,
)
from sqlalchemy.orm import relationship

from src.database.db import Base


# ============================================================================
# 1. USERS
# ============================================================================
# System users.  The owner is the primary user who sets bankroll preferences,
# staking method, and edge threshold.  Viewers are friends who receive the
# same emails but don't place bets through the system.
# Every personal table (bet_log, bankroll data) is scoped to user_id.

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=True)
    role = Column(
        String, nullable=False, server_default="viewer",
    )
    # Bankroll settings — these defaults match config/settings.yaml and
    # can be overridden per-user via the dashboard settings page.
    starting_bankroll = Column(Float, nullable=False, server_default="500.0")
    current_bankroll = Column(Float, nullable=False, server_default="500.0")
    staking_method = Column(
        String, nullable=False, server_default="flat",
    )
    # stake_percentage: fraction of bankroll per bet (0.02 = 2%)
    stake_percentage = Column(Float, nullable=False, server_default="0.02")
    # kelly_fraction: multiplier for Kelly criterion (0.25 = quarter-Kelly)
    kelly_fraction = Column(Float, nullable=False, server_default="0.25")
    # edge_threshold: minimum edge to flag a value bet (0.05 = 5%)
    edge_threshold = Column(Float, nullable=False, server_default="0.05")
    # has_onboarded: set to 1 after the user completes the onboarding wizard
    has_onboarded = Column(Integer, nullable=False, server_default="0")
    # Notification preferences: 1 = enabled, 0 = disabled
    # Controls which email types this user receives.
    notify_morning = Column(Integer, nullable=False, server_default="1")
    notify_evening = Column(Integer, nullable=False, server_default="1")
    notify_weekly = Column(Integer, nullable=False, server_default="1")
    is_active = Column(Integer, nullable=False, server_default="1")
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )
    updated_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'viewer')",
            name="ck_users_role",
        ),
        CheckConstraint(
            "staking_method IN ('flat', 'percentage', 'kelly')",
            name="ck_users_staking_method",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"User(id={self.id}, name='{self.name}', role='{self.role}', "
            f"bankroll={self.current_bankroll})"
        )


# ============================================================================
# 2. LEAGUES
# ============================================================================
# Football leagues the system tracks.  Each league has identifiers for all
# three data sources: Football-Data.co.uk, FBref (via soccerdata), and
# API-Football (via RapidAPI).

class League(Base):
    __tablename__ = "leagues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    short_name = Column(String, nullable=False, unique=True)
    country = Column(String, nullable=False)
    # Data-source identifiers — each source uses a different naming scheme
    football_data_code = Column(String, nullable=True)   # e.g. "E0"
    fbref_league_id = Column(String, nullable=True)      # e.g. "ENG-Premier League"
    api_football_id = Column(Integer, nullable=True)      # e.g. 39
    is_active = Column(Integer, nullable=False, server_default="1")
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    seasons = relationship("Season", back_populates="league")
    teams = relationship("Team", back_populates="league")

    def __repr__(self) -> str:
        return (
            f"League(id={self.id}, short_name='{self.short_name}', "
            f"active={self.is_active})"
        )


# ============================================================================
# 3. SEASONS
# ============================================================================
# Tracks which seasons have been loaded for each league.  The is_loaded flag
# prevents re-scraping data that's already in the database.

class Season(Base):
    __tablename__ = "seasons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(
        Integer, ForeignKey("leagues.id"), nullable=False,
    )
    season = Column(String, nullable=False)               # e.g. "2024-25"
    start_date = Column(String, nullable=True)
    end_date = Column(String, nullable=True)
    is_loaded = Column(Integer, nullable=False, server_default="0")

    # Relationships
    league = relationship("League", back_populates="seasons")

    __table_args__ = (
        UniqueConstraint("league_id", "season", name="uq_seasons_league_season"),
    )

    def __repr__(self) -> str:
        return (
            f"Season(id={self.id}, league_id={self.league_id}, "
            f"season='{self.season}', loaded={self.is_loaded})"
        )


# ============================================================================
# 4. TEAMS
# ============================================================================
# Canonical team records with cross-source name mappings.  Different data
# sources spell team names differently (e.g. "Man United" vs "Manchester Utd"
# vs "Manchester United"), so each source gets its own name column.

class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)                 # Canonical name
    league_id = Column(
        Integer, ForeignKey("leagues.id"), nullable=False,
    )
    # Source-specific names for fuzzy matching during data ingestion
    football_data_name = Column(String, nullable=True)
    fbref_name = Column(String, nullable=True)
    api_football_id = Column(Integer, nullable=True)
    # API-Football uses different team names than our canonical names
    # (e.g. "Tottenham" vs "Tottenham Hotspur"), so we store their version
    api_football_name = Column(String, nullable=True)

    # Relationships
    league = relationship("League", back_populates="teams")

    __table_args__ = (
        UniqueConstraint("name", "league_id", name="uq_teams_name_league"),
    )

    def __repr__(self) -> str:
        return f"Team(id={self.id}, name='{self.name}', league_id={self.league_id})"


# ============================================================================
# 5. MATCHES
# ============================================================================
# Every fixture and result.  Goals columns are NULL until the match finishes.
# The status column tracks the match lifecycle.

class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(
        Integer, ForeignKey("leagues.id"), nullable=False,
    )
    season = Column(String, nullable=False)               # e.g. "2024-25"
    matchday = Column(Integer, nullable=True)              # 1–38 for EPL
    date = Column(String, nullable=False)                  # ISO YYYY-MM-DD
    kickoff_time = Column(String, nullable=True)           # HH:MM (24hr)
    home_team_id = Column(
        Integer, ForeignKey("teams.id"), nullable=False,
    )
    away_team_id = Column(
        Integer, ForeignKey("teams.id"), nullable=False,
    )
    # Goals — NULL if match not yet played
    home_goals = Column(Integer, nullable=True)
    away_goals = Column(Integer, nullable=True)
    home_ht_goals = Column(Integer, nullable=True)         # Half-time
    away_ht_goals = Column(Integer, nullable=True)         # Half-time
    status = Column(
        String, nullable=False, server_default="scheduled",
    )
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )
    updated_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    home_team = relationship("Team", foreign_keys=[home_team_id])
    away_team = relationship("Team", foreign_keys=[away_team_id])
    stats = relationship("MatchStat", back_populates="match")
    odds = relationship("Odds", back_populates="match")
    features = relationship("Feature", back_populates="match")
    predictions = relationship("Prediction", back_populates="match")

    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'in_play', 'finished', 'postponed')",
            name="ck_matches_status",
        ),
        UniqueConstraint(
            "league_id", "date", "home_team_id", "away_team_id",
            name="uq_matches_league_date_teams",
        ),
        Index("idx_matches_date", "date"),
        Index("idx_matches_league_season", "league_id", "season"),
        Index("idx_matches_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"Match(id={self.id}, date='{self.date}', "
            f"home={self.home_team_id} vs away={self.away_team_id}, "
            f"score={self.home_goals}-{self.away_goals}, "
            f"status='{self.status}')"
        )


# ============================================================================
# 6. MATCH_STATS
# ============================================================================
# Per-team statistics for a played match.  Sourced primarily from FBref.
# xG (expected goals) is the most important stat — it measures shot quality
# and is the foundation for Poisson-based prediction models.

class MatchStat(Base):
    __tablename__ = "match_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(
        Integer, ForeignKey("matches.id"), nullable=False,
    )
    team_id = Column(
        Integer, ForeignKey("teams.id"), nullable=False,
    )
    is_home = Column(Integer, nullable=False)              # 1 = home, 0 = away
    # Expected goals — the single most predictive stat in football analytics.
    # xG measures the quality of chances created; xGA measures chances conceded.
    xg = Column(Float, nullable=True)
    xga = Column(Float, nullable=True)
    shots = Column(Integer, nullable=True)
    shots_on_target = Column(Integer, nullable=True)
    # Possession as a proportion (0.0–1.0), not percentage
    possession = Column(Float, nullable=True)
    passes_completed = Column(Integer, nullable=True)
    passes_attempted = Column(Integer, nullable=True)
    # Pass completion rate as a proportion (0.0–1.0)
    pass_pct = Column(Float, nullable=True)
    corners = Column(Integer, nullable=True)
    fouls = Column(Integer, nullable=True)
    yellow_cards = Column(Integer, nullable=True)
    red_cards = Column(Integer, nullable=True)
    source = Column(String, nullable=False, server_default="fbref")
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    match = relationship("Match", back_populates="stats")
    team = relationship("Team")

    __table_args__ = (
        UniqueConstraint("match_id", "team_id", name="uq_match_stats_match_team"),
        Index("idx_match_stats_match", "match_id"),
    )

    def __repr__(self) -> str:
        venue = "H" if self.is_home else "A"
        return (
            f"MatchStat(match={self.match_id}, team={self.team_id}, "
            f"{venue}, xG={self.xg})"
        )


# ============================================================================
# 7. ODDS
# ============================================================================
# Bookmaker odds for every supported market.  Each row is one selection
# (e.g. "home win at 2.10") from one bookmaker for one match.
#
# Market types explained (for the owner who is learning — see MP §12):
#   1X2  — Match result: home win (1), draw (X), away win (2)
#   OU25 — Over/Under 2.5 goals: will there be 3+ goals or fewer?
#   OU15 — Over/Under 1.5 goals
#   OU35 — Over/Under 3.5 goals
#   BTTS — Both Teams To Score: will both teams find the net?
#   AH   — Asian Handicap: a spread bet with half-goal lines

class Odds(Base):
    __tablename__ = "odds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(
        Integer, ForeignKey("matches.id"), nullable=False,
    )
    bookmaker = Column(String, nullable=False)             # e.g. "Bet365", "market_avg"
    market_type = Column(String, nullable=False)
    selection = Column(String, nullable=False)
    # odds_decimal: European decimal format (e.g. 2.10 means £2.10 return per £1)
    odds_decimal = Column(Float, nullable=False)
    # implied_prob: 1.0 / odds_decimal — the bookmaker's raw probability
    # estimate (includes overround / vig)
    implied_prob = Column(Float, nullable=False)
    is_opening = Column(Integer, nullable=False, server_default="0")
    captured_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )
    source = Column(String, nullable=False, server_default="football_data")

    # Relationships
    match = relationship("Match", back_populates="odds")

    __table_args__ = (
        CheckConstraint(
            "market_type IN ('1X2', 'OU25', 'OU15', 'OU35', 'BTTS', 'AH')",
            name="ck_odds_market_type",
        ),
        CheckConstraint(
            "selection IN ("
            "'home', 'draw', 'away', 'over', 'under', 'yes', 'no', "
            "'home_-0.5', 'home_-1.0', 'home_-1.5', "
            "'home_+0.5', 'home_+1.0', 'home_+1.5', "
            "'away_-0.5', 'away_-1.0', 'away_-1.5', "
            "'away_+0.5', 'away_+1.0', 'away_+1.5'"
            ")",
            name="ck_odds_selection",
        ),
        UniqueConstraint(
            "match_id", "bookmaker", "market_type", "selection", "captured_at",
            name="uq_odds_match_bookie_market_sel_time",
        ),
        Index("idx_odds_match", "match_id"),
        Index("idx_odds_bookmaker", "bookmaker"),
        Index("idx_odds_market", "market_type"),
    )

    def __repr__(self) -> str:
        return (
            f"Odds(match={self.match_id}, {self.bookmaker} "
            f"{self.market_type}/{self.selection} @ {self.odds_decimal})"
        )


# ============================================================================
# 8. FEATURES
# ============================================================================
# Computed features for each team in a match, used as model input.
# All rolling averages use ONLY data from BEFORE the match date — temporal
# integrity is the #1 constraint (CLAUDE.md Rule 6).
#
# Rolling windows are configurable in config/settings.yaml (default: 5, 10).
# "form" = points per game (3 for win, 1 for draw, 0 for loss).

class Feature(Base):
    __tablename__ = "features"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(
        Integer, ForeignKey("matches.id"), nullable=False,
    )
    team_id = Column(
        Integer, ForeignKey("teams.id"), nullable=False,
    )
    is_home = Column(Integer, nullable=False)              # 1 = home, 0 = away

    # --- Rolling features: 5-match window ---
    form_5 = Column(Float, nullable=True)
    goals_scored_5 = Column(Float, nullable=True)
    goals_conceded_5 = Column(Float, nullable=True)
    xg_5 = Column(Float, nullable=True)
    xga_5 = Column(Float, nullable=True)
    xg_diff_5 = Column(Float, nullable=True)               # xG - xGA
    shots_5 = Column(Float, nullable=True)
    shots_on_target_5 = Column(Float, nullable=True)
    possession_5 = Column(Float, nullable=True)

    # --- Rolling features: 10-match window ---
    form_10 = Column(Float, nullable=True)
    goals_scored_10 = Column(Float, nullable=True)
    goals_conceded_10 = Column(Float, nullable=True)
    xg_10 = Column(Float, nullable=True)
    xga_10 = Column(Float, nullable=True)
    xg_diff_10 = Column(Float, nullable=True)
    shots_10 = Column(Float, nullable=True)
    shots_on_target_10 = Column(Float, nullable=True)
    possession_10 = Column(Float, nullable=True)

    # --- Venue-specific rolling features (5-match, home or away only) ---
    venue_form_5 = Column(Float, nullable=True)
    venue_goals_scored_5 = Column(Float, nullable=True)
    venue_goals_conceded_5 = Column(Float, nullable=True)
    venue_xg_5 = Column(Float, nullable=True)
    venue_xga_5 = Column(Float, nullable=True)

    # --- Head-to-head (last 5 meetings between these two teams) ---
    h2h_wins = Column(Integer, nullable=True)
    h2h_draws = Column(Integer, nullable=True)
    h2h_losses = Column(Integer, nullable=True)
    h2h_goals_scored = Column(Float, nullable=True)        # Average per H2H match
    h2h_goals_conceded = Column(Float, nullable=True)

    # --- Context ---
    rest_days = Column(Integer, nullable=True)             # Days since last match
    matchday = Column(Integer, nullable=True)              # Matchday number in season
    # season_progress: 0.0 (season start) to 1.0 (season end)
    season_progress = Column(Float, nullable=True)

    computed_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    match = relationship("Match", back_populates="features")
    team = relationship("Team")

    __table_args__ = (
        UniqueConstraint("match_id", "team_id", name="uq_features_match_team"),
        Index("idx_features_match", "match_id"),
    )

    def __repr__(self) -> str:
        venue = "H" if self.is_home else "A"
        return (
            f"Feature(match={self.match_id}, team={self.team_id}, "
            f"{venue}, form_5={self.form_5})"
        )


# ============================================================================
# 9. PREDICTIONS
# ============================================================================
# Model output for a match.  Every prediction model produces a 7×7 scoreline
# probability matrix (home goals 0–6 × away goals 0–6).  All market
# probabilities (1X2, O/U, BTTS) are derived from this matrix via
# derive_market_probabilities() — never calculated any other way.
#
# The scoreline_matrix column stores the matrix as a JSON string:
#   [[p_00, p_01, ..., p_06], [p_10, ...], ..., [p_60, ..., p_66]]
# where p_ij = P(home scores i, away scores j).  All 49 values sum to ~1.0.

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(
        Integer, ForeignKey("matches.id"), nullable=False,
    )
    model_name = Column(String, nullable=False)            # e.g. "poisson_v1"
    model_version = Column(String, nullable=False)         # e.g. "1.0.0"

    # Lambda parameters for the Poisson distribution
    predicted_home_goals = Column(Float, nullable=False)
    predicted_away_goals = Column(Float, nullable=False)

    # The 7×7 scoreline matrix as JSON — the universal model interface
    scoreline_matrix = Column(Text, nullable=False)

    # Derived market probabilities (all derived from the scoreline matrix)
    prob_home_win = Column(Float, nullable=False)
    prob_draw = Column(Float, nullable=False)
    prob_away_win = Column(Float, nullable=False)
    prob_over_25 = Column(Float, nullable=False)
    prob_under_25 = Column(Float, nullable=False)
    prob_over_15 = Column(Float, nullable=False)
    prob_under_15 = Column(Float, nullable=False)
    prob_over_35 = Column(Float, nullable=False)
    prob_under_35 = Column(Float, nullable=False)
    # BTTS = Both Teams To Score
    prob_btts_yes = Column(Float, nullable=False)
    prob_btts_no = Column(Float, nullable=False)

    is_ensemble = Column(Integer, nullable=False, server_default="0")
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    match = relationship("Match", back_populates="predictions")

    __table_args__ = (
        UniqueConstraint(
            "match_id", "model_name", "model_version",
            name="uq_predictions_match_model",
        ),
        Index("idx_predictions_match", "match_id"),
        Index("idx_predictions_model", "model_name"),
    )

    def __repr__(self) -> str:
        return (
            f"Prediction(match={self.match_id}, model='{self.model_name}', "
            f"H={self.prob_home_win:.2f}/D={self.prob_draw:.2f}/"
            f"A={self.prob_away_win:.2f})"
        )


# ============================================================================
# 10. VALUE_BETS  (E2-03)
# ============================================================================
# Identified value bets where the model's probability exceeds the bookmaker's
# implied probability by at least the configured edge threshold.
#
# Key betting concepts (MP §12 Glossary):
#   Edge = model_prob - implied_prob (how much we think the bookie is wrong)
#   EV   = (model_prob × odds) - 1.0 (expected profit per unit staked)
#   Confidence tiers: high (≥10% edge), medium (5–10%), low (<5%)

class ValueBet(Base):
    __tablename__ = "value_bets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(
        Integer, ForeignKey("matches.id"), nullable=False,
    )
    prediction_id = Column(
        Integer, ForeignKey("predictions.id"), nullable=False,
    )
    bookmaker = Column(String, nullable=False)
    market_type = Column(String, nullable=False)
    selection = Column(String, nullable=False)
    # model_prob: the model's estimated true probability for this outcome
    model_prob = Column(Float, nullable=False)
    # bookmaker_odds: best available decimal odds (e.g. 2.10)
    bookmaker_odds = Column(Float, nullable=False)
    # implied_prob: 1.0 / bookmaker_odds (includes the bookie's margin / vig)
    implied_prob = Column(Float, nullable=False)
    # edge: model_prob - implied_prob (positive = we think it's underpriced)
    edge = Column(Float, nullable=False)
    # expected_value: (model_prob × bookmaker_odds) - 1.0
    expected_value = Column(Float, nullable=False)
    confidence = Column(String, nullable=False)
    # Human-readable explanation of why this is a value bet
    explanation = Column(Text, nullable=True)
    detected_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    match = relationship("Match")
    prediction = relationship("Prediction")

    __table_args__ = (
        CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_value_bets_confidence",
        ),
        UniqueConstraint(
            "match_id", "market_type", "selection", "bookmaker", "detected_at",
            name="uq_value_bets_match_market_sel_bookie_time",
        ),
        Index("idx_value_bets_match", "match_id"),
        Index("idx_value_bets_edge", "edge"),
    )

    def __repr__(self) -> str:
        return (
            f"ValueBet(match={self.match_id}, {self.market_type}/"
            f"{self.selection}, edge={self.edge:.3f}, "
            f"confidence='{self.confidence}')"
        )


# ============================================================================
# 11. BET_LOG  (E2-03)
# ============================================================================
# The most important tracking table.  Records every bet — both system picks
# (auto-logged when a value bet is detected) and user-placed bets (logged
# when the user confirms they placed the bet with a bookmaker).
#
# Dual bet tracking (MP §6, CLAUDE.md Rule 6):
#   system_pick  — auto-logged for every value bet, tracks model performance
#   user_placed  — logged when the user actually bets, tracks real P&L
#
# Odds are captured at three points in time:
#   odds_at_detection  — when the system first spotted the value
#   odds_at_placement  — when the user placed the bet (NULL for system_pick)
#   closing_odds       — just before kickoff (for CLV calculation)
#
# CLV (Closing Line Value) measures whether you beat the closing line —
# the strongest indicator of long-term betting skill (MP §12).

class BetLog(Base):
    __tablename__ = "bet_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Always scoped to a user — even with one user (prevents refactor later)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False,
    )
    # NULL if this is a manual bet not from a system pick
    value_bet_id = Column(
        Integer, ForeignKey("value_bets.id"), nullable=True,
    )
    match_id = Column(
        Integer, ForeignKey("matches.id"), nullable=False,
    )
    date = Column(String, nullable=False)                  # Match date ISO
    league = Column(String, nullable=False)
    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)
    market_type = Column(String, nullable=False)
    selection = Column(String, nullable=False)
    model_prob = Column(Float, nullable=False)
    bookmaker = Column(String, nullable=False)
    odds_at_detection = Column(Float, nullable=False)
    # NULL for system_pick — only populated when user actually places bet
    odds_at_placement = Column(Float, nullable=True)
    implied_prob = Column(Float, nullable=False)
    edge = Column(Float, nullable=False)
    stake = Column(Float, nullable=False)                  # Amount in currency
    stake_method = Column(String, nullable=False)          # flat/percentage/kelly
    bet_type = Column(
        String, nullable=False, server_default="system_pick",
    )
    status = Column(
        String, nullable=False, server_default="pending",
    )
    # P&L: positive = profit, negative = loss
    pnl = Column(Float, server_default="0.0")
    bankroll_before = Column(Float, nullable=True)
    bankroll_after = Column(Float, nullable=True)
    # Closing odds captured just before kickoff
    closing_odds = Column(Float, nullable=True)
    # CLV = implied_prob(closing) - implied_prob(placement)
    # Positive CLV means you beat the market
    clv = Column(Float, nullable=True)
    resolved_at = Column(String, nullable=True)
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )
    updated_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    user = relationship("User")
    value_bet = relationship("ValueBet")
    match = relationship("Match")

    __table_args__ = (
        CheckConstraint(
            "bet_type IN ('system_pick', 'user_placed')",
            name="ck_bet_log_bet_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'won', 'lost', 'void', "
            "'half_won', 'half_lost')",
            name="ck_bet_log_status",
        ),
        Index("idx_bet_log_user", "user_id"),
        Index("idx_bet_log_match", "match_id"),
        Index("idx_bet_log_status", "status"),
        Index("idx_bet_log_date", "date"),
        Index("idx_bet_log_type", "bet_type"),
    )

    def __repr__(self) -> str:
        return (
            f"BetLog(id={self.id}, user={self.user_id}, "
            f"{self.bet_type}, {self.market_type}/{self.selection}, "
            f"edge={self.edge:.3f}, status='{self.status}', "
            f"pnl={self.pnl})"
        )


# ============================================================================
# 12. MODEL_PERFORMANCE  (E2-03)
# ============================================================================
# Aggregated performance metrics per model per time period.  Used by the
# dashboard and self-improvement engine to track how well each model is doing.
#
# Brier score (MP §12): mean squared error of probability predictions.
#   Lower = better.  0.25 = coin flip, <0.20 = decent, <0.15 = good.
# ROI: return on investment = total_profit / total_staked.
# CLV: closing line value, the gold-standard metric for betting edge.

class ModelPerformance(Base):
    __tablename__ = "model_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String, nullable=False)
    period_type = Column(String, nullable=False)
    period_start = Column(String, nullable=False)
    period_end = Column(String, nullable=False)
    total_predictions = Column(Integer, nullable=False)
    # Brier score: lower is better (0 = perfect, 0.25 = useless)
    brier_score = Column(Float, nullable=True)
    roi = Column(Float, nullable=True)
    avg_clv = Column(Float, nullable=True)
    # JSON: {"0.5-0.55": {"predicted": 0.525, "actual": 0.51, "count": 40}}
    calibration_json = Column(Text, nullable=True)
    win_rate_1x2 = Column(Float, nullable=True)
    win_rate_ou = Column(Float, nullable=True)
    win_rate_btts = Column(Float, nullable=True)
    computed_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    __table_args__ = (
        CheckConstraint(
            "period_type IN ('daily', 'weekly', 'monthly', "
            "'season', 'all_time')",
            name="ck_model_perf_period_type",
        ),
        UniqueConstraint(
            "model_name", "period_type", "period_start",
            name="uq_model_perf_model_period",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"ModelPerformance(model='{self.model_name}', "
            f"{self.period_type} {self.period_start}→{self.period_end}, "
            f"brier={self.brier_score}, roi={self.roi})"
        )


# ============================================================================
# 13. PIPELINE_RUNS  (E2-03)
# ============================================================================
# Operational log for every pipeline execution.  Records what was run, when,
# how long it took, and whether it succeeded or failed.  Essential for
# debugging and monitoring system health.

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_type = Column(String, nullable=False)
    started_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )
    completed_at = Column(String, nullable=True)
    status = Column(
        String, nullable=False, server_default="running",
    )
    matches_scraped = Column(Integer, server_default="0")
    predictions_made = Column(Integer, server_default="0")
    value_bets_found = Column(Integer, server_default="0")
    emails_sent = Column(Integer, server_default="0")
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "run_type IN ('morning', 'midday', 'evening', "
            "'manual', 'backtest')",
            name="ck_pipeline_runs_run_type",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_pipeline_runs_status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"PipelineRun(id={self.id}, type='{self.run_type}', "
            f"status='{self.status}', "
            f"scraped={self.matches_scraped}, "
            f"predicted={self.predictions_made})"
        )


# ============================================================================
# 14. CALIBRATION_HISTORY  (E2-04)
# ============================================================================
# Tracks every automatic recalibration event (MP §11.1).
#
# Recalibration applies Platt scaling or isotonic regression to model outputs
# to correct systematic over/under-confidence.  Only runs after 200+ resolved
# predictions AND mean absolute calibration error exceeds 3 percentage points.
# If the next 100 predictions show worse performance, the recalibration is
# rolled back automatically.

class CalibrationHistory(Base):
    __tablename__ = "calibration_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String, nullable=False)
    calibration_method = Column(String, nullable=False)
    sample_size = Column(Integer, nullable=False)
    # Calibration error before and after — lower is better
    mean_abs_error_before = Column(Float, nullable=False)
    mean_abs_error_after = Column(Float, nullable=False)
    # Serialised calibration model parameters (JSON)
    parameters_json = Column(Text, nullable=False)
    is_active = Column(Integer, nullable=False, server_default="1")
    rolled_back = Column(Integer, nullable=False, server_default="0")
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    __table_args__ = (
        CheckConstraint(
            "calibration_method IN ('platt', 'isotonic')",
            name="ck_calibration_method",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"CalibrationHistory(model='{self.model_name}', "
            f"method='{self.calibration_method}', "
            f"err {self.mean_abs_error_before:.3f}→{self.mean_abs_error_after:.3f}, "
            f"active={self.is_active})"
        )


# ============================================================================
# 15. FEATURE_IMPORTANCE_LOG  (E2-04)
# ============================================================================
# Tracks feature importance over time for tree-based models (MP §11.2).
#
# Only XGBoost and LightGBM produce native feature importance scores.
# Features below 1% importance for 3 consecutive training cycles are flagged
# for human review on the dashboard — they are NEVER auto-removed.

class FeatureImportanceLog(Base):
    __tablename__ = "feature_importance_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String, nullable=False)
    training_date = Column(String, nullable=False)         # ISO date
    feature_name = Column(String, nullable=False)          # e.g. "form_5", "xg_10"
    # importance_gain: feature importance by "gain" method (native to XGBoost/LightGBM)
    importance_gain = Column(Float, nullable=False)
    importance_rank = Column(Integer, nullable=False)      # 1 = most important
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    __table_args__ = (
        Index(
            "idx_feature_importance_model",
            "model_name", "training_date",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"FeatureImportanceLog(model='{self.model_name}', "
            f"date='{self.training_date}', "
            f"feature='{self.feature_name}', "
            f"gain={self.importance_gain:.4f}, rank={self.importance_rank})"
        )


# ============================================================================
# 16. ENSEMBLE_WEIGHT_HISTORY  (E2-04)
# ============================================================================
# Tracks ensemble model weight changes over time (MP §11.3).
#
# Weights are recalculated every 100 resolved ensemble predictions using
# inverse Brier score weighting.  Guardrails:
#   - Max ±10 pp change per recalculation
#   - Weight floor: 10% (no model drops below)
#   - Weight ceiling: 60% (preserve ensemble diversity)

class EnsembleWeightHistory(Base):
    __tablename__ = "ensemble_weight_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String, nullable=False)
    weight = Column(Float, nullable=False)                 # 0.0–1.0
    brier_score = Column(Float, nullable=False)
    evaluation_window = Column(Integer, nullable=False)    # e.g. 300
    previous_weight = Column(Float, nullable=True)
    reason = Column(String, nullable=False)
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    def __repr__(self) -> str:
        prev = f"{self.previous_weight:.2f}" if self.previous_weight else "N/A"
        return (
            f"EnsembleWeight(model='{self.model_name}', "
            f"weight={self.weight:.2f} (was {prev}), "
            f"brier={self.brier_score:.3f})"
        )


# ============================================================================
# 17. MARKET_PERFORMANCE  (E2-04)
# ============================================================================
# Tracks edge and ROI by league × market type (MP §11.4).
#
# Assessment tiers (evaluated weekly on Sundays):
#   profitable   — ROI positive AND 95% CI lower bound positive AND n >= 100
#   promising    — ROI positive but CI includes zero, OR 50 <= n < 100
#   insufficient — fewer than 50 bets
#   unprofitable — ROI negative AND 95% CI upper bound negative AND n >= 100

class MarketPerformance(Base):
    __tablename__ = "market_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    league = Column(String, nullable=False)                # e.g. "EPL"
    market_type = Column(String, nullable=False)           # e.g. "1X2", "OU25"
    period_end = Column(String, nullable=False)            # ISO date (Sunday)
    total_bets = Column(Integer, nullable=False)
    wins = Column(Integer, nullable=False)
    losses = Column(Integer, nullable=False)
    total_staked = Column(Float, nullable=False)
    total_pnl = Column(Float, nullable=False)
    roi = Column(Float, nullable=False)
    roi_ci_lower = Column(Float, nullable=True)            # 95% CI lower bound
    roi_ci_upper = Column(Float, nullable=True)            # 95% CI upper bound
    assessment = Column(String, nullable=False)
    computed_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    __table_args__ = (
        CheckConstraint(
            "assessment IN ('profitable', 'promising', "
            "'insufficient', 'unprofitable')",
            name="ck_market_perf_assessment",
        ),
        UniqueConstraint(
            "league", "market_type", "period_end",
            name="uq_market_perf_league_market_period",
        ),
        Index("idx_market_perf_league", "league", "market_type"),
    )

    def __repr__(self) -> str:
        return (
            f"MarketPerformance({self.league} {self.market_type}, "
            f"roi={self.roi:.3f}, n={self.total_bets}, "
            f"assessment='{self.assessment}')"
        )


# ============================================================================
# 18. RETRAIN_HISTORY  (E2-04)
# ============================================================================
# Tracks automatic and manual model retrains (MP §11.5).
#
# Automatic retrain fires when the rolling Brier score (last 100 predictions)
# degrades by >= 15% vs the all-time average.  Cooldown: 30 days between
# auto-retrains.  If the new model performs worse over 50 test predictions,
# it is automatically rolled back.

class RetrainHistory(Base):
    __tablename__ = "retrain_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String, nullable=False)
    trigger_type = Column(String, nullable=False)
    trigger_reason = Column(String, nullable=False)
    brier_before = Column(Float, nullable=False)
    brier_after = Column(Float, nullable=True)             # NULL if rolled back immediately
    training_samples = Column(Integer, nullable=False)
    was_rolled_back = Column(Integer, nullable=False, server_default="0")
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('automatic', 'manual', 'scheduled')",
            name="ck_retrain_trigger_type",
        ),
    )

    def __repr__(self) -> str:
        after = f"{self.brier_after:.3f}" if self.brier_after else "N/A"
        return (
            f"RetrainHistory(model='{self.model_name}', "
            f"trigger='{self.trigger_type}', "
            f"brier {self.brier_before:.3f}→{after}, "
            f"rolled_back={self.was_rolled_back})"
        )


# ============================================================================
# 19. WEATHER  (Real-Time Data Sources)
# ============================================================================
# Match-day weather conditions fetched from Open-Meteo API.  Weather can
# affect match outcomes — heavy rain reduces passing accuracy and goal-scoring,
# strong wind makes long balls unpredictable, and extreme cold/heat affects
# player stamina.  Each row is linked 1:1 to a match via match_id.
#
# Data source: Open-Meteo (free, no API key required).
# WMO weather codes: 0–3 = clear/cloud, 51–67 = rain, 71–77 = snow,
#   80–82 = rain showers, 95–99 = thunderstorm.

class Weather(Base):
    __tablename__ = "weather"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(
        Integer, ForeignKey("matches.id"), nullable=False,
    )
    # Temperature at kickoff in degrees Celsius
    temperature_c = Column(Float, nullable=True)
    # Wind speed at kickoff in km/h — high wind (>30 km/h) affects long balls
    wind_speed_kmh = Column(Float, nullable=True)
    # Relative humidity as percentage (0–100)
    humidity_pct = Column(Float, nullable=True)
    # Precipitation in mm during the match window
    precipitation_mm = Column(Float, nullable=True)
    # WMO weather code — numeric standard for weather conditions
    weather_code = Column(Integer, nullable=True)
    # Simplified category for feature engineering: "clear", "cloudy",
    # "rain", "heavy_rain", "snow", "storm"
    weather_category = Column(String, nullable=True)
    source = Column(String, nullable=False, server_default="open_meteo")
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    match = relationship("Match")

    __table_args__ = (
        # One weather record per match — idempotent loading
        UniqueConstraint("match_id", name="uq_weather_match"),
        Index("idx_weather_match", "match_id"),
    )

    def __repr__(self) -> str:
        return (
            f"Weather(match={self.match_id}, "
            f"temp={self.temperature_c}°C, wind={self.wind_speed_kmh}km/h, "
            f"category='{self.weather_category}')"
        )
