"""
BetVector World Cup 2026 Add-On Module
=======================================
Time-boxed module for FIFA World Cup 2026 prediction and value betting.
Active June 11 – July 19, 2026. All tables prefixed with ``wc_``.

Submodules:
    models      — WC-specific ORM models (wc_teams, wc_matches, etc.)
    seed        — Seed 48 teams + venues from YAML config
    scraper     — Odds API + results collection
    elo         — International Elo rating computation
    world_bank  — Economic/demographic indicators from World Bank API
    squad       — Squad-level data (market value, age, club distribution)
    features    — Feature engineering (37 features across 4 tiers)
    predictor   — Regularized Poisson model for international football
    simulator   — Monte Carlo tournament advancement simulator
    value_finder — Value bet identification + Kelly staking
    alerts      — WC-specific email alerts
    pipeline    — Daily WC pipeline orchestrator
"""
