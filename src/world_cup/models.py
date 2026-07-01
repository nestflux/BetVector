"""
BetVector World Cup 2026 — ORM Models (WC-01-01)
==================================================
SQLAlchemy 2.0 ORM models for World Cup data. All tables prefixed with
``wc_`` to avoid collision with league tables. Inherits ``Base`` from
``src.database.db`` so ``init_db()`` creates these alongside league tables.

Tables:
    1. wc_teams               — 48 participating nations
    2. wc_matches             — Group + knockout fixtures and results
    3. wc_historical_matches  — Historical international results for Elo/training
    4. wc_odds                — Bookmaker odds per match
    5. wc_predictions         — Model outputs per match
    6. wc_value_bets          — Identified value bets
    7. wc_features            — Computed feature vectors per match
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from src.database.db import Base


class WCTeam(Base):
    __tablename__ = "wc_teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    fifa_code = Column(String(3), nullable=False, unique=True)
    confederation = Column(String, nullable=False)
    group_letter = Column(String(1), nullable=False)

    # Elo & rankings
    elo_rating = Column(Float, nullable=True)
    fifa_ranking = Column(Integer, nullable=True)
    fifa_points = Column(Float, nullable=True)

    # Economic indicators (World Bank API — WC-02-04)
    gdp_per_capita = Column(Float, nullable=True)
    population = Column(Float, nullable=True)
    gini_coefficient = Column(Float, nullable=True)
    political_stability = Column(Float, nullable=True)

    # Squad data (Transfermarkt / YAML seed — WC-02-05)
    squad_market_value = Column(Float, nullable=True)
    avg_squad_age = Column(Float, nullable=True)
    players_in_top5_leagues = Column(Integer, nullable=True)
    cl_players = Column(Integer, nullable=True)
    avg_caps = Column(Float, nullable=True)
    squad_mv_gini = Column(Float, nullable=True)

    # Manager
    manager_name = Column(String, nullable=True)
    manager_tenure_months = Column(Integer, nullable=True)

    # Historical WC record
    wc_appearances = Column(Integer, nullable=False, server_default="0")
    best_wc_finish = Column(String, nullable=True)
    is_host = Column(Integer, nullable=False, server_default="0")

    # Meta
    dark_horse_score = Column(Float, nullable=True)
    home_capital_lat = Column(Float, nullable=True)
    home_capital_lon = Column(Float, nullable=True)
    home_avg_june_temp_c = Column(Float, nullable=True)

    created_at = Column(String, nullable=False, server_default=func.now())

    # Relationships
    home_matches = relationship(
        "WCMatch", foreign_keys="WCMatch.home_team_id", back_populates="home_team",
    )
    away_matches = relationship(
        "WCMatch", foreign_keys="WCMatch.away_team_id", back_populates="away_team",
    )

    def __repr__(self) -> str:
        return f"WCTeam(id={self.id}, name='{self.name}', group='{self.group_letter}')"


class WCMatch(Base):
    __tablename__ = "wc_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_number = Column(Integer, nullable=True, unique=True)
    group_letter = Column(String(1), nullable=True)
    stage = Column(String, nullable=False, server_default="group")
    matchday = Column(Integer, nullable=True)
    date = Column(String, nullable=False)
    kickoff_time = Column(String, nullable=True)
    venue = Column(String, nullable=True)
    city = Column(String, nullable=True)
    altitude_m = Column(Float, nullable=True, server_default="0")

    home_team_id = Column(Integer, ForeignKey("wc_teams.id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("wc_teams.id"), nullable=False)
    home_goals = Column(Integer, nullable=True)
    away_goals = Column(Integer, nullable=True)
    home_goals_ht = Column(Integer, nullable=True)
    away_goals_ht = Column(Integer, nullable=True)
    home_xg = Column(Float, nullable=True)
    away_xg = Column(Float, nullable=True)
    attendance = Column(Integer, nullable=True)
    temperature_c = Column(Float, nullable=True)

    status = Column(String, nullable=False, server_default="scheduled")

    created_at = Column(String, nullable=False, server_default=func.now())
    updated_at = Column(String, nullable=False, server_default=func.now())

    # Relationships
    home_team = relationship("WCTeam", foreign_keys=[home_team_id], back_populates="home_matches")
    away_team = relationship("WCTeam", foreign_keys=[away_team_id], back_populates="away_matches")
    odds = relationship("WCOdds", back_populates="match", cascade="all, delete-orphan")
    predictions = relationship("WCPrediction", back_populates="match", cascade="all, delete-orphan")
    value_bets = relationship("WCValueBet", back_populates="match", cascade="all, delete-orphan")
    features = relationship("WCFeature", back_populates="match", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_wc_matches_date", "date"),
        Index("ix_wc_matches_status", "status"),
        Index("ix_wc_matches_stage", "stage"),
    )

    def __repr__(self) -> str:
        return (
            f"WCMatch(id={self.id}, #{self.match_number}, "
            f"stage='{self.stage}', status='{self.status}')"
        )


class WCHistoricalMatch(Base):
    __tablename__ = "wc_historical_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, nullable=False)
    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)
    home_goals = Column(Integer, nullable=False)
    away_goals = Column(Integer, nullable=False)
    tournament = Column(String, nullable=True)
    match_weight = Column(Float, nullable=False, server_default="0.5")
    neutral_venue = Column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        UniqueConstraint("date", "home_team", "away_team", name="uq_wc_hist_match"),
        Index("ix_wc_hist_date", "date"),
    )

    def __repr__(self) -> str:
        return (
            f"WCHistoricalMatch({self.date}: {self.home_team} "
            f"{self.home_goals}-{self.away_goals} {self.away_team})"
        )


class WCOdds(Base):
    __tablename__ = "wc_odds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("wc_matches.id"), nullable=False)
    bookmaker = Column(String, nullable=False)
    market_type = Column(String, nullable=False)
    selection = Column(String, nullable=False)
    odds_decimal = Column(Float, nullable=False)        # current / latest price
    opening_odds = Column(Float, nullable=True)         # first price seen — set on
    # insert, never updated → enables line movement (WC-09-03)
    implied_prob = Column(Float, nullable=True)
    point = Column(Float, nullable=True)
    captured_at = Column(String, nullable=False, server_default=func.now())
    source = Column(String, nullable=True, server_default="odds_api")

    # Relationships
    match = relationship("WCMatch", back_populates="odds")

    __table_args__ = (
        UniqueConstraint(
            "match_id", "bookmaker", "market_type", "selection",
            name="uq_wc_odds_entry",
        ),
        Index("ix_wc_odds_match", "match_id"),
    )

    def __repr__(self) -> str:
        return (
            f"WCOdds(match={self.match_id}, {self.bookmaker}, "
            f"{self.market_type}: {self.selection} @ {self.odds_decimal})"
        )


class WCPrediction(Base):
    __tablename__ = "wc_predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("wc_matches.id"), nullable=False)
    model_name = Column(String, nullable=False, server_default="wc_poisson_v1")
    home_win_prob = Column(Float, nullable=False)
    draw_prob = Column(Float, nullable=False)
    away_win_prob = Column(Float, nullable=False)
    home_expected_goals = Column(Float, nullable=False)
    away_expected_goals = Column(Float, nullable=False)
    over_25_prob = Column(Float, nullable=True)
    btts_prob = Column(Float, nullable=True)
    most_likely_score = Column(String, nullable=True)
    created_at = Column(String, nullable=False, server_default=func.now())

    # Relationships
    match = relationship("WCMatch", back_populates="predictions")
    value_bets = relationship("WCValueBet", back_populates="prediction", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("match_id", "model_name", name="uq_wc_pred_match_model"),
        Index("ix_wc_preds_match", "match_id"),
    )

    def __repr__(self) -> str:
        return (
            f"WCPrediction(match={self.match_id}, "
            f"H={self.home_win_prob:.2f}/D={self.draw_prob:.2f}/A={self.away_win_prob:.2f})"
        )


class WCValueBet(Base):
    __tablename__ = "wc_value_bets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("wc_matches.id"), nullable=False)
    prediction_id = Column(Integer, ForeignKey("wc_predictions.id"), nullable=False)
    market_type = Column(String, nullable=False)
    selection = Column(String, nullable=False)
    model_prob = Column(Float, nullable=False)
    best_odds = Column(Float, nullable=False)
    implied_prob = Column(Float, nullable=False)
    edge = Column(Float, nullable=False)
    bookmaker = Column(String, nullable=False)
    kelly_stake = Column(Float, nullable=True)
    outcome = Column(String, nullable=True)
    # Closing-line value (WC-09-01). closing_odds = best price for this selection
    # frozen once the match starts (the last stored pre-kickoff snapshot — no new
    # API cost). clv = (1/closing_odds) - (1/best_odds); +ve = we beat the close.
    closing_odds = Column(Float, nullable=True)
    clv = Column(Float, nullable=True)
    created_at = Column(String, nullable=False, server_default=func.now())

    # Relationships
    match = relationship("WCMatch", back_populates="value_bets")
    prediction = relationship("WCPrediction", back_populates="value_bets")

    __table_args__ = (
        Index("ix_wc_vb_match", "match_id"),
    )

    def __repr__(self) -> str:
        return (
            f"WCValueBet(match={self.match_id}, {self.selection} "
            f"@ {self.best_odds}, edge={self.edge:.3f})"
        )


class WCFeature(Base):
    __tablename__ = "wc_features"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("wc_matches.id"), nullable=False, unique=True)

    # Tier 1 — Strength
    elo_diff = Column(Float, nullable=True)
    elo_home = Column(Float, nullable=True)
    elo_away = Column(Float, nullable=True)
    market_value_ratio = Column(Float, nullable=True)

    # Tier 1 — Squad
    avg_age_home = Column(Float, nullable=True)
    avg_age_away = Column(Float, nullable=True)
    top5_league_players_home = Column(Integer, nullable=True)
    top5_league_players_away = Column(Integer, nullable=True)
    cl_players_home = Column(Integer, nullable=True)
    cl_players_away = Column(Integer, nullable=True)

    # Tier 1 — Historical
    wc_appearances_home = Column(Integer, nullable=True)
    wc_appearances_away = Column(Integer, nullable=True)
    best_finish_home = Column(Integer, nullable=True)
    best_finish_away = Column(Integer, nullable=True)

    # Tier 1 — Context
    is_host_home = Column(Integer, nullable=True)
    is_host_away = Column(Integer, nullable=True)

    # Tier 2 — Confederation & rest
    confederation_adj_home = Column(Float, nullable=True)
    confederation_adj_away = Column(Float, nullable=True)
    rest_days_home = Column(Integer, nullable=True)
    rest_days_away = Column(Integer, nullable=True)

    # Tier 2 — Economic
    gdp_ratio = Column(Float, nullable=True)
    population_ratio = Column(Float, nullable=True)

    # Tier 2 — Tactical
    manager_tenure_home = Column(Integer, nullable=True)
    manager_tenure_away = Column(Integer, nullable=True)

    # Tier 2 — Form & meta
    home_form_last5 = Column(Float, nullable=True)
    away_form_last5 = Column(Float, nullable=True)
    dark_horse_score_home = Column(Float, nullable=True)
    dark_horse_score_away = Column(Float, nullable=True)

    # Tier 3 — Venue
    altitude_m = Column(Float, nullable=True)
    climate_gap_home = Column(Float, nullable=True)
    climate_gap_away = Column(Float, nullable=True)
    travel_distance_home_km = Column(Float, nullable=True)
    travel_distance_away_km = Column(Float, nullable=True)

    # Tier 3 — Tournament dynamics
    motivation_home = Column(String, nullable=True)
    motivation_away = Column(String, nullable=True)
    matchday = Column(Integer, nullable=True)
    group_strength = Column(Float, nullable=True)
    stage_code = Column(Integer, nullable=True)
    # Knockout matches produce ~15% fewer goals (research) — model multiplies xG by this
    knockout_deflation = Column(Float, nullable=True, server_default="1.0")

    created_at = Column(String, nullable=False, server_default=func.now())

    # Relationships
    match = relationship("WCMatch", back_populates="features")

    __table_args__ = (
        Index("ix_wc_features_match", "match_id"),
    )

    def __repr__(self) -> str:
        return f"WCFeature(match={self.match_id}, elo_diff={self.elo_diff})"


class WCCalibrationMetric(Base):
    __tablename__ = "wc_calibration_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(String, nullable=False, server_default=func.now())
    calibration_type = Column(String, nullable=False)
    n_matches = Column(Integer, nullable=False)
    brier = Column(Float, nullable=True)
    brier_per_class = Column(Float, nullable=True)
    log_loss = Column(Float, nullable=True)
    accuracy = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_wc_cal_type", "calibration_type"),
    )

    def __repr__(self) -> str:
        return (
            f"WCCalibrationMetric(type='{self.calibration_type}', "
            f"brier={self.brier}, n={self.n_matches})"
        )


class WCLineup(Base):
    """Starting XI / squad for a WC match, scraped from ESPN's free JSON API in the
    pre-kickoff window (WC-10-06). Decision-support only — feeds the rotation/absence
    flag on the research card (WC-10-07); it never changes the model or value bets.
    """

    __tablename__ = "wc_lineups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("wc_matches.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("wc_teams.id"), nullable=False)
    player_name = Column(String, nullable=False)   # ESPN displayName (short, e.g. "Vinicius Jr")
    # WC-11A-01: fuller identity for the player-rate join. ESPN returns both a short
    # displayName and a full name + a stable athlete id; the short form zero-matches
    # external player datasets (Transfermarkt), so we keep the full name for the
    # name resolver and the id as a future stable key. Both nullable (back-compat).
    full_name = Column(String, nullable=True)       # ESPN fullName (e.g. "Vinicius Junior")
    espn_athlete_id = Column(String, nullable=True)  # ESPN athlete.id (stable join key)
    is_starter = Column(Integer, nullable=False, server_default="0")  # 1 = in the XI
    position = Column(String, nullable=True)    # ESPN abbrev (G, CD-L, AM-C, F, ...)
    jersey = Column(Integer, nullable=True)
    formation = Column(String, nullable=True)   # team formation, e.g. "4-2-3-1"
    captured_at = Column(String, nullable=False, server_default=func.now())

    team = relationship("WCTeam")

    __table_args__ = (
        UniqueConstraint("match_id", "team_id", "player_name", name="uq_wc_lineup"),
        Index("ix_wc_lineup_match", "match_id"),
    )

    def __repr__(self) -> str:
        return (
            f"WCLineup(match={self.match_id}, team={self.team_id}, "
            f"{self.player_name!r}, starter={self.is_starter})"
        )


class WCBetLog(Base):
    """A user's PERSONAL World Cup bet — placed and tracked by a user, kept entirely
    separate from the model's shadow value picks (``wc_value_bets``) and from league
    bets (``bet_log``). Scoped per ``user_id``; settles off the ``wc_matches`` final
    score.

    ``market_type`` / ``selection`` use the canonical convention of
    ``betting.tracker._did_bet_win`` — market in {1X2, OU15, OU25, OU35, BTTS},
    selection in {home, draw, away, over, under, yes, no} — so settlement reuses the
    exact same proven league outcome logic.

    ``model_prob`` / ``edge`` are captured (frozen) at log time when the bet is
    placed off a model tip, never recomputed — consistent with temporal integrity.
    """

    __tablename__ = "wc_bet_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    match_id = Column(Integer, ForeignKey("wc_matches.id"), nullable=False)
    market_type = Column(String, nullable=False)   # 1X2 / OU15 / OU25 / OU35 / BTTS
    selection = Column(String, nullable=False)      # home/draw/away/over/under/yes/no
    odds = Column(Float, nullable=False)            # decimal odds the user actually got
    stake = Column(Float, nullable=False)
    bookmaker = Column(String, nullable=True)
    # Captured at log time when placed off a model tip (frozen, never recomputed):
    model_prob = Column(Float, nullable=True)
    edge = Column(Float, nullable=True)
    source = Column(String, nullable=True)          # research_card / deep_dive / manual
    status = Column(String, nullable=False, server_default="pending")  # pending/won/lost/void
    pnl = Column(Float, nullable=True)              # profit/loss once settled
    notes = Column(String, nullable=True)
    placed_at = Column(String, nullable=False, server_default=func.now())
    settled_at = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_wc_bet_user", "user_id"),
        Index("ix_wc_bet_match", "match_id"),
        Index("ix_wc_bet_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"WCBetLog(user={self.user_id}, match={self.match_id}, "
            f"{self.market_type}/{self.selection} @ {self.odds}, status={self.status})"
        )


class WCAccumulator(Base):
    """A user's PERSONAL World Cup ACCUMULATOR (parlay) — two or more legs combined
    into ONE bet where EVERY leg must win for the bet to pay out, and the payout
    MULTIPLIES (combined odds = product of the leg odds). Sits alongside the single
    bets in ``wc_bet_log``; both are per-user and settle off ``wc_matches`` scores.

    This is a calculator + tracker, NEVER a recommender: the user builds the slip,
    the system freezes the combined odds at log time, settles all-legs-must-win, and
    tracks P&L. It never writes to the model / value / prediction path.

    ``combined_odds`` is frozen when the slip is logged (the product of the leg odds
    the user actually got). At settlement the *effective* odds are recomputed from the
    legs that actually won, so a VOID leg (e.g. an abandoned match) simply drops out
    of the multiplier — matching standard bookmaker accumulator rules.
    """

    __tablename__ = "wc_accumulator"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    stake = Column(Float, nullable=False)
    combined_odds = Column(Float, nullable=False)   # product of leg odds, frozen at log
    source = Column(String, nullable=True)          # research_card / deep_dive / manual
    status = Column(String, nullable=False, server_default="pending")  # pending/won/lost/void
    pnl = Column(Float, nullable=True)              # profit/loss once settled
    notes = Column(String, nullable=True)
    placed_at = Column(String, nullable=False, server_default=func.now())
    settled_at = Column(String, nullable=True)

    # Deleting an accumulator removes its legs (parent owns the legs).
    legs = relationship(
        "WCAccaLeg", back_populates="accumulator",
        cascade="all, delete-orphan", order_by="WCAccaLeg.id",
    )

    __table_args__ = (
        Index("ix_wc_acca_user", "user_id"),
        Index("ix_wc_acca_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"WCAccumulator(id={self.id}, user={self.user_id}, "
            f"odds={self.combined_odds}, status={self.status})"
        )


class WCAccaLeg(Base):
    """One leg of a WC accumulator (``WCAccumulator``). Each leg is a single
    market/selection on one match, using the canonical convention of
    ``betting.tracker._did_bet_win`` so it settles by the exact same proven logic as a
    single bet. A leg resolves to ``won`` / ``lost`` / ``void`` (dropped from the
    payout) / ``pending``; the parent's status and P&L are derived from the legs.

    ``model_prob`` / ``edge`` are captured (frozen) at log time when a leg comes from a
    model tip — used only for the INFORMATIVE combined-edge readout, never recomputed
    and never fed back into the model.
    """

    __tablename__ = "wc_acca_leg"

    id = Column(Integer, primary_key=True, autoincrement=True)
    accumulator_id = Column(Integer, ForeignKey("wc_accumulator.id"), nullable=False)
    match_id = Column(Integer, ForeignKey("wc_matches.id"), nullable=False)
    market_type = Column(String, nullable=False)   # 1X2 / OU15 / OU25 / OU35 / BTTS
    selection = Column(String, nullable=False)      # home/draw/away/over/under/yes/no
    odds = Column(Float, nullable=False)            # decimal odds for this leg
    # Captured at log time when the leg comes from a model tip (frozen, never recomputed):
    model_prob = Column(Float, nullable=True)
    edge = Column(Float, nullable=True)
    status = Column(String, nullable=False, server_default="pending")  # pending/won/lost/void
    settled_at = Column(String, nullable=True)

    accumulator = relationship("WCAccumulator", back_populates="legs")

    __table_args__ = (
        Index("ix_wc_acca_leg_parent", "accumulator_id"),
        Index("ix_wc_acca_leg_match", "match_id"),
    )

    def __repr__(self) -> str:
        return (
            f"WCAccaLeg(acca={self.accumulator_id}, match={self.match_id}, "
            f"{self.market_type}/{self.selection} @ {self.odds}, status={self.status})"
        )
