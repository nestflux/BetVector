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
Team market values and injuries tables added in E15-03 (Transfermarkt datasets).

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
    # Referee name — extracted from Football-Data.co.uk CSV (E19-03).
    # Used to compute referee-specific features (avg fouls, avg yellows,
    # avg goals per game) for the prediction model (E21-02).
    referee = Column(String, nullable=True)
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
    # Non-penalty expected goals — strips out penalty xG which is essentially
    # random (conversion rate ~76% regardless of team).  NPxG is more
    # predictive of future performance than raw xG.  Source: Understat.
    npxg = Column(Float, nullable=True)
    npxga = Column(Float, nullable=True)
    # PPDA (Passes Per Defensive Action) coefficient — measures pressing
    # intensity.  Calculated as opponent_passes / team_defensive_actions.
    # Lower PPDA = team presses more aggressively (e.g. Liverpool ~8,
    # Burnley ~18).  Source: Understat.
    ppda_coeff = Column(Float, nullable=True)
    # PPDA allowed — same metric but from the opponent's defensive perspective.
    # How much pressing does THIS team face?
    ppda_allowed_coeff = Column(Float, nullable=True)
    # Deep completions — passes that reach the area near the opponent's box.
    # Measures attacking penetration quality.  Source: Understat.
    deep = Column(Integer, nullable=True)
    deep_allowed = Column(Integer, nullable=True)
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
            "'home_line', "  # AH line value (E19-03)
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
# 7b. CLUB ELO RATINGS (E21-01)
# ============================================================================
# Historical Elo ratings from ClubElo (http://api.clubelo.com).
#
# Elo ratings capture long-term team strength, adjusted for opponent quality.
# Unlike rolling form (which is noisy with 5-10 matches), Elo uses the entire
# historical record.  This makes it especially valuable:
#   - Early season: rolling stats are sparse, Elo provides a stable signal
#   - Promoted teams: start with low Elo — encodes "newly promoted" quality
#   - After transfers: market knows more than stats — Elo reflects this via results
#
# Ratings are fetched daily in the morning pipeline and stored per-team per-date.
# Feature computation looks up the most recent rating BEFORE the match date
# (temporal integrity).

class ClubElo(Base):
    __tablename__ = "club_elo"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    elo_rating = Column(Float, nullable=False)
    rank = Column(Integer, nullable=True)  # Global rank (may not always be available)
    rating_date = Column(String, nullable=False)  # ISO date (YYYY-MM-DD)
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    team = relationship("Team")

    __table_args__ = (
        UniqueConstraint("team_id", "rating_date", name="uq_club_elo_team_date"),
        Index("idx_club_elo_team", "team_id"),
        Index("idx_club_elo_date", "rating_date"),
    )

    def __repr__(self) -> str:
        return (
            f"ClubElo(team={self.team_id}, elo={self.elo_rating}, "
            f"rank={self.rank}, date={self.rating_date})"
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
    # --- Advanced rolling features: 5-match window (E16-01) ---
    # NPxG (non-penalty xG) — strips penalty xG (~76% conversion regardless
    # of team quality).  More predictive of future performance than raw xG
    # because penalties are essentially random events.  Source: Understat.
    npxg_5 = Column(Float, nullable=True)
    npxga_5 = Column(Float, nullable=True)
    npxg_diff_5 = Column(Float, nullable=True)              # NPxG - NPxGA
    # PPDA (Passes Per Defensive Action) — measures pressing intensity.
    # Lower PPDA = more aggressive pressing (Liverpool ~8, Burnley ~18).
    # High-pressing teams create more turnovers and chances.
    ppda_5 = Column(Float, nullable=True)
    ppda_allowed_5 = Column(Float, nullable=True)
    # Deep completions — passes reaching the area near the opponent's box.
    # Measures attacking penetration quality beyond just shots/xG.
    deep_5 = Column(Float, nullable=True)
    deep_allowed_5 = Column(Float, nullable=True)

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
    # --- Advanced rolling features: 10-match window (E16-01) ---
    npxg_10 = Column(Float, nullable=True)
    npxga_10 = Column(Float, nullable=True)
    npxg_diff_10 = Column(Float, nullable=True)
    ppda_10 = Column(Float, nullable=True)
    ppda_allowed_10 = Column(Float, nullable=True)
    deep_10 = Column(Float, nullable=True)
    deep_allowed_10 = Column(Float, nullable=True)

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

    # --- Market value features (E16-02) ---
    # Market value ratio = this team's squad value ÷ opponent's squad value.
    # A ratio > 1.0 means this team has a richer squad.  Market value is a
    # strong proxy for long-term squad quality — captures transfer spending,
    # talent retention, and depth in a single number.
    # Uses most recent Transfermarkt snapshot BEFORE the match date (temporal integrity).
    market_value_ratio = Column(Float, nullable=True)
    # Log of squad total value — normalises the massive range (€50M to €1.5B)
    # and provides a continuous quality signal even when opponent data is missing.
    squad_value_log = Column(Float, nullable=True)

    # --- Elo rating features (E21-01) ---
    # ClubElo Elo rating captures long-term team quality, adjusted for
    # strength of schedule.  More stable than rolling form (which is noisy
    # over 5-10 matches).  Especially valuable early season and for promoted teams.
    elo_rating = Column(Float, nullable=True)
    # Elo difference: this team's Elo minus opponent's Elo.
    # Positive = this team is stronger.  A 100-point Elo gap corresponds
    # to roughly a 64% expected win probability.
    elo_diff = Column(Float, nullable=True)

    # --- Market-implied features (E20-01, E20-02) ---
    # Pinnacle implied probabilities with overround removed.  Pinnacle is the
    # sharpest bookmaker — their closing line is widely considered the best
    # available probability estimate.  Adding these as features lets the model
    # incorporate market consensus (the "wisdom of the crowd" distilled through
    # sharp bettors).  Expected Brier improvement: 7-9% (Constantinou 2022).
    #
    # Overround removal formula (multiplicative/proportional):
    #   raw_prob = 1 / decimal_odds
    #   overround = sum(raw_probs) - 1.0
    #   true_prob = raw_prob / sum(raw_probs)
    #
    # TEMPORAL INTEGRITY: uses pre-match (opening) odds only — these are
    # available before kickoff and before the prediction is made.
    pinnacle_home_prob = Column(Float, nullable=True)
    pinnacle_draw_prob = Column(Float, nullable=True)
    pinnacle_away_prob = Column(Float, nullable=True)
    # Raw overround — informational.  Lower overround = sharper market.
    # Pinnacle typically runs 2-4% overround on 1X2 (vs 5-10% for soft books).
    pinnacle_overround = Column(Float, nullable=True)
    # Asian Handicap home line (E20-02) — the sharpest market in football.
    # The AH line is a direct market-implied measure of the expected goal
    # difference.  E.g., AH = -1.5 means the market expects the home team
    # to win by ~1.5 goals.  This is the single best feature for capturing
    # "how strong does the market think this team is?"
    ah_line = Column(Float, nullable=True)

    # --- Weather features (E16-02) ---
    # Match-day conditions from Open-Meteo.  Same value for both teams in a
    # match (weather doesn't change between home and away).
    temperature_c = Column(Float, nullable=True)
    wind_speed_kmh = Column(Float, nullable=True)
    precipitation_mm = Column(Float, nullable=True)
    # Binary flag: 1 if conditions significantly affect play.  Heavy rain
    # (>2mm) reduces passing accuracy; strong wind (>30km/h) makes long balls
    # unpredictable.  Both reduce goal-scoring rates on average.
    is_heavy_weather = Column(Integer, nullable=True)

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


# ============================================================================
# 20. TEAM_MARKET_VALUES  (E15-03)
# ============================================================================
# Weekly squad market value snapshots from Transfermarkt Datasets (CC0 license).
#
# Market value ratio between teams is a strong predictor of match outcomes —
# richer squads (higher total market value) generally outperform poorer ones.
# The value is aggregated from individual player market values per club.
#
# Data source: https://github.com/dcaribou/transfermarkt-datasets (CDN)
# Updated weekly.  One snapshot per team per evaluation date.
#
# Key features for prediction:
#   squad_total_value — total squad market value in EUR (sum of all players)
#   avg_player_value  — average player value in EUR (quality proxy)
#   squad_size        — number of registered players (depth proxy)
#   contract_expiring_count — players with contract ending ≤6 months (instability)

class TeamMarketValue(Base):
    __tablename__ = "team_market_values"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(
        Integer, ForeignKey("teams.id"), nullable=False,
    )
    # Total squad market value in EUR — sum of all player valuations
    # e.g. Manchester City ~€1.2 billion, promoted teams ~€100–200 million
    squad_total_value = Column(Float, nullable=False)
    # Average player value in EUR — quality-per-player metric
    avg_player_value = Column(Float, nullable=True)
    # Number of registered first-team players
    squad_size = Column(Integer, nullable=True)
    # Players with contracts expiring within 6 months — a proxy for
    # squad instability and potential loss of key assets
    contract_expiring_count = Column(Integer, nullable=True)
    # Date this snapshot was evaluated (YYYY-MM-DD)
    evaluated_at = Column(String, nullable=False)
    source = Column(String, nullable=False, server_default="transfermarkt_datasets")
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    team = relationship("Team")

    __table_args__ = (
        # One snapshot per team per evaluation date — idempotent loading
        UniqueConstraint(
            "team_id", "evaluated_at",
            name="uq_team_market_values_team_date",
        ),
        Index("idx_team_market_values_team", "team_id"),
        Index("idx_team_market_values_date", "evaluated_at"),
    )

    def __repr__(self) -> str:
        val_m = (self.squad_total_value or 0) / 1_000_000
        return (
            f"TeamMarketValue(team={self.team_id}, "
            f"value=€{val_m:.1f}M, size={self.squad_size}, "
            f"date='{self.evaluated_at}')"
        )


# ============================================================================
# 21. TEAM_INJURIES  (E15-03 — Placeholder)
# ============================================================================
# Placeholder model for future injury data integration.  The original build
# plan assumed injury data was available in the Transfermarkt datasets repo,
# but research revealed the 10 published tables do NOT include an injuries
# table.  This model is created for schema completeness so the feature
# engineering layer can reference it once an injury data source is added.
#
# Key predictive insight (for future use):
#   Teams missing >20% of squad value to injuries tend to underperform
#   their expected goals — a strong signal for in-season prediction.

class TeamInjury(Base):
    __tablename__ = "team_injuries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(
        Integer, ForeignKey("teams.id"), nullable=False,
    )
    player_name = Column(String, nullable=False)
    # Type of injury (e.g. "ACL tear", "muscle strain", "illness")
    injury_type = Column(String, nullable=True)
    # Estimated days out — NULL if unknown
    days_out = Column(Integer, nullable=True)
    # Market value of the injured player in EUR — used to calculate
    # "missing squad value" as a percentage of total squad value
    player_market_value = Column(Float, nullable=True)
    # Current status: "injured" (still out) or "returned" (back in training)
    status = Column(String, nullable=False, server_default="injured")
    # Date this injury was first reported (YYYY-MM-DD)
    reported_at = Column(String, nullable=False)
    # Expected return date (YYYY-MM-DD, nullable if unknown)
    expected_return = Column(String, nullable=True)
    source = Column(String, nullable=False, server_default="transfermarkt")
    created_at = Column(
        String, nullable=False, server_default=sa_text("(datetime('now'))"),
    )

    # Relationships
    team = relationship("Team")

    __table_args__ = (
        CheckConstraint(
            "status IN ('injured', 'returned')",
            name="ck_team_injuries_status",
        ),
        Index("idx_team_injuries_team", "team_id"),
        Index("idx_team_injuries_status", "status"),
        Index("idx_team_injuries_reported", "reported_at"),
    )

    def __repr__(self) -> str:
        return (
            f"TeamInjury(team={self.team_id}, "
            f"player='{self.player_name}', "
            f"status='{self.status}', "
            f"reported='{self.reported_at}')"
        )
