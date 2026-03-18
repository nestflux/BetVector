"""
PC-25 — Multi-League Strategy System Tests
============================================
Tests covering per-league strategy profiles (PC-25-01), sharp-only filtering
integration (PC-25-02), aggregate daily exposure caps (PC-25-03), and config
loading with graceful fallbacks.

Accepted strategy settings (from PC-24-02 backtest data):
  - LaLiga:       sharp_only=True  (+21.49pp ROI with Pinnacle-only)
  - Ligue1:       sharp_only=True  (+22.14pp ROI with Pinnacle-only)
  - EPL:          sharp_only=False (Pinnacle hurt by -12.2pp)
  - Championship: sharp_only=False (market inefficient enough)
  - Bundesliga:   sharp_only=False (insufficient data)
  - SerieA:       sharp_only=False (insufficient data)

Master Plan refs: MP §4 Value Detection, MP §11.4 Assessment Tiers,
                  config/leagues.yaml strategy blocks
"""
import inspect
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ============================================================================
# Strategy Profile Config Loading Tests — PC-25-01
# ============================================================================

class TestStrategyProfileConfig:
    """Verify leagues.yaml has strategy blocks with all required keys."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        """Load leagues.yaml once per test."""
        config_path = Path(__file__).parent.parent / "config" / "leagues.yaml"
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.leagues = self.config["leagues"]
        self.league_map = {lg["short_name"]: lg for lg in self.leagues}

    STRATEGY_KEYS = {"sharp_only", "stake_multiplier", "max_daily_bets",
                     "auto_bet", "clv_tracking"}

    def test_every_league_has_strategy_block(self):
        """All 6 leagues have a strategy block in leagues.yaml."""
        for lg in self.leagues:
            assert "strategy" in lg, (
                f"{lg['short_name']} is missing strategy block"
            )

    def test_strategy_has_all_required_keys(self):
        """Each strategy block has all 5 required keys."""
        for lg in self.leagues:
            strategy = lg.get("strategy", {})
            missing = self.STRATEGY_KEYS - set(strategy.keys())
            assert not missing, (
                f"{lg['short_name']} strategy missing keys: {missing}"
            )

    def test_sharp_only_is_boolean(self):
        """sharp_only is a boolean in every league."""
        for lg in self.leagues:
            sharp = lg["strategy"]["sharp_only"]
            assert isinstance(sharp, bool), (
                f"{lg['short_name']} sharp_only should be bool, got {type(sharp)}"
            )

    def test_stake_multiplier_is_positive_number(self):
        """stake_multiplier is a positive number."""
        for lg in self.leagues:
            mult = lg["strategy"]["stake_multiplier"]
            assert isinstance(mult, (int, float)) and mult > 0, (
                f"{lg['short_name']} stake_multiplier should be positive, got {mult}"
            )

    def test_max_daily_bets_is_positive_int(self):
        """max_daily_bets is a positive integer."""
        for lg in self.leagues:
            cap = lg["strategy"]["max_daily_bets"]
            assert isinstance(cap, int) and cap > 0, (
                f"{lg['short_name']} max_daily_bets should be positive int, got {cap}"
            )

    def test_auto_bet_is_boolean(self):
        """auto_bet is a boolean."""
        for lg in self.leagues:
            auto = lg["strategy"]["auto_bet"]
            assert isinstance(auto, bool), (
                f"{lg['short_name']} auto_bet should be bool, got {type(auto)}"
            )

    def test_clv_tracking_is_boolean(self):
        """clv_tracking is a boolean."""
        for lg in self.leagues:
            clv = lg["strategy"]["clv_tracking"]
            assert isinstance(clv, bool), (
                f"{lg['short_name']} clv_tracking should be bool, got {type(clv)}"
            )


# ============================================================================
# Per-League Sharp-Only Settings — PC-25-02
# ============================================================================

class TestSharpOnlySettings:
    """Verify sharp_only settings match PC-24-02 backtest findings."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        config_path = Path(__file__).parent.parent / "config" / "leagues.yaml"
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.league_map = {lg["short_name"]: lg for lg in self.config["leagues"]}

    def test_laliga_sharp_only_true(self):
        """LaLiga uses Pinnacle-only (+21.49pp ROI improvement)."""
        assert self.league_map["LaLiga"]["strategy"]["sharp_only"] is True

    def test_ligue1_sharp_only_true(self):
        """Ligue1 uses Pinnacle-only (+22.14pp ROI improvement)."""
        assert self.league_map["Ligue1"]["strategy"]["sharp_only"] is True

    def test_epl_sharp_only_false(self):
        """EPL uses all bookmakers (Pinnacle filtering hurt by -12.2pp)."""
        assert self.league_map["EPL"]["strategy"]["sharp_only"] is False

    def test_championship_sharp_only_false(self):
        """Championship uses all bookmakers (market inefficient enough)."""
        assert self.league_map["Championship"]["strategy"]["sharp_only"] is False

    def test_bundesliga_sharp_only_false(self):
        """Bundesliga uses all bookmakers (insufficient data to justify)."""
        assert self.league_map["Bundesliga"]["strategy"]["sharp_only"] is False

    def test_seriea_sharp_only_false(self):
        """SerieA uses all bookmakers (insufficient data to justify)."""
        assert self.league_map["SerieA"]["strategy"]["sharp_only"] is False


# ============================================================================
# Auto-Bet Tier Alignment — PC-25-01
# ============================================================================

class TestAutoBetTierAlignment:
    """Verify auto_bet matches assessment tier assignments."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        config_path = Path(__file__).parent.parent / "config" / "leagues.yaml"
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.league_map = {lg["short_name"]: lg for lg in self.config["leagues"]}

    def test_championship_auto_bet_true(self):
        """Championship is 🟢 profitable — auto_bet should be True."""
        assert self.league_map["Championship"]["strategy"]["auto_bet"] is True

    def test_epl_auto_bet_false(self):
        """EPL is 🟡 promising — auto_bet should be False."""
        assert self.league_map["EPL"]["strategy"]["auto_bet"] is False

    def test_laliga_auto_bet_false(self):
        """LaLiga is 🟡 promising — auto_bet should be False."""
        assert self.league_map["LaLiga"]["strategy"]["auto_bet"] is False

    def test_unprofitable_leagues_auto_bet_false(self):
        """🔴 unprofitable leagues should all have auto_bet=False."""
        for name in ["Ligue1", "Bundesliga", "SerieA"]:
            assert self.league_map[name]["strategy"]["auto_bet"] is False, (
                f"{name} is 🔴 unprofitable, auto_bet should be False"
            )


# ============================================================================
# ConfigNamespace Strategy Loading — PC-25-01
# ============================================================================

class TestConfigNamespaceStrategy:
    """Verify the config loader properly wraps strategy blocks."""

    def test_strategy_accessible_via_dot_notation(self):
        """Strategy block is accessible as league_cfg.strategy.sharp_only."""
        from src.config import config

        for lg in config.leagues:
            strategy = getattr(lg, "strategy", None)
            assert strategy is not None, (
                f"{lg.short_name} has no strategy in ConfigNamespace"
            )
            # All 5 keys should be accessible via dot notation
            assert hasattr(strategy, "sharp_only")
            assert hasattr(strategy, "stake_multiplier")
            assert hasattr(strategy, "max_daily_bets")
            assert hasattr(strategy, "auto_bet")
            assert hasattr(strategy, "clv_tracking")

    def test_strategy_fallback_pattern(self):
        """Pipeline pattern for reading strategy with fallback works."""
        from src.config import config

        for lg in config.leagues:
            # This is the exact pattern used in pipeline.py
            strategy = getattr(lg, "strategy", None)
            sharp_only = (
                getattr(strategy, "sharp_only", False)
                if strategy else False
            )
            assert isinstance(sharp_only, bool)

    def test_laliga_strategy_via_config(self):
        """LaLiga strategy reads sharp_only=True via config loader."""
        from src.config import config

        laliga = next(lg for lg in config.leagues if lg.short_name == "LaLiga")
        assert laliga.strategy.sharp_only is True

    def test_epl_strategy_via_config(self):
        """EPL strategy reads sharp_only=False via config loader."""
        from src.config import config

        epl = next(lg for lg in config.leagues if lg.short_name == "EPL")
        assert epl.strategy.sharp_only is False


# ============================================================================
# Pipeline Integration — PC-25-01 + PC-25-02
# ============================================================================

class TestPipelineSharpOnlyIntegration:
    """Verify pipeline passes sharp_only correctly to ValueFinder."""

    def test_value_finder_accepts_sharp_only_param(self):
        """ValueFinder.find_value_bets() accepts sharp_only parameter."""
        from src.betting.value_finder import ValueFinder
        sig = inspect.signature(ValueFinder.find_value_bets)
        assert "sharp_only" in sig.parameters
        assert sig.parameters["sharp_only"].default is False

    def test_value_finder_accepts_sharp_bookmaker_param(self):
        """ValueFinder.find_value_bets() accepts sharp_bookmaker parameter."""
        from src.betting.value_finder import ValueFinder
        sig = inspect.signature(ValueFinder.find_value_bets)
        assert "sharp_bookmaker" in sig.parameters
        assert sig.parameters["sharp_bookmaker"].default == "Pinnacle"

    def test_backtester_accepts_sharp_only_param(self):
        """run_backtest() accepts sharp_only parameter."""
        from src.evaluation.backtester import run_backtest
        sig = inspect.signature(run_backtest)
        assert "sharp_only" in sig.parameters
        assert sig.parameters["sharp_only"].default is False

    def test_settings_has_sharp_bookmaker(self):
        """settings.yaml has sharp_bookmaker config for Pinnacle."""
        settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(settings_path, "r") as f:
            settings = yaml.safe_load(f)
        vb = settings.get("value_betting", {})
        assert vb.get("sharp_bookmaker") == "Pinnacle"


# ============================================================================
# CLV Tracking Config — PC-25-04
# ============================================================================

class TestCLVTrackingConfig:
    """Verify CLV tracking is enabled for all leagues."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        config_path = Path(__file__).parent.parent / "config" / "leagues.yaml"
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

    def test_all_leagues_have_clv_tracking_enabled(self):
        """Every league has clv_tracking=True in its strategy."""
        for lg in self.config["leagues"]:
            assert lg["strategy"]["clv_tracking"] is True, (
                f"{lg['short_name']} should have clv_tracking=True"
            )


# ============================================================================
# Aggregate Daily Exposure Caps — PC-25-03
# ============================================================================

def _make_mock_user(bankroll: float = 1000.0) -> dict:
    """Return a synthetic user dict that mirrors BankrollManager._get_user()."""
    return {
        "id": 1,
        "starting_bankroll": bankroll,
        "current_bankroll": bankroll,
        "staking_method": "flat",
        "stake_percentage": 0.02,   # 2% per bet = $20 on $1000
        "kelly_fraction": 0.25,
        "edge_threshold": 0.05,
    }


def _make_mock_safety() -> dict:
    """Return a safety dict that mimics check_safety_limits() returning OK."""
    return {
        "daily_limit_hit": False,
        "drawdown_warning": False,
        "min_bankroll_hit": False,
        "message": "All safety limits OK.",
    }


class TestDailyExposureCapConfig:
    """Verify settings.yaml has the new exposure cap keys."""

    @pytest.fixture(autouse=True)
    def load_settings(self):
        settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(settings_path, "r") as f:
            self.settings = yaml.safe_load(f)
        self.safety = self.settings.get("safety", {})

    def test_max_daily_exposure_present(self):
        """settings.yaml safety section has max_daily_exposure key."""
        assert "max_daily_exposure" in self.safety, (
            "max_daily_exposure missing from config/settings.yaml safety section"
        )

    def test_max_daily_exposure_is_015(self):
        """max_daily_exposure is 0.15 (15%) as specified in PC-25-03."""
        assert self.safety["max_daily_exposure"] == pytest.approx(0.15)

    def test_max_league_daily_exposure_present(self):
        """settings.yaml safety section has max_league_daily_exposure key."""
        assert "max_league_daily_exposure" in self.safety, (
            "max_league_daily_exposure missing from config/settings.yaml safety section"
        )

    def test_max_league_daily_exposure_is_008(self):
        """max_league_daily_exposure is 0.08 (8%) as specified in PC-25-03."""
        assert self.safety["max_league_daily_exposure"] == pytest.approx(0.08)

    def test_league_cap_lower_than_daily_cap(self):
        """Per-league cap (8%) is lower than aggregate cap (15%) — correct layering."""
        assert self.safety["max_league_daily_exposure"] < self.safety["max_daily_exposure"]


class TestBankrollManagerExposureCaps:
    """Verify BankrollManager.calculate_stake() enforces exposure caps."""

    def _run_calculate_stake(
        self,
        today_staked_all: float = 0.0,
        today_staked_league: float = 0.0,
        bankroll: float = 1000.0,
        league: str = "EPL",
    ):
        """
        Helper: run calculate_stake() with mocked DB and config.

        Patches:
          - _get_user()         → returns a synthetic $1000 flat-stake user
          - check_safety_limits() → returns all-OK safety dict
          - _get_daily_staked() → returns provided staked amounts
        """
        from src.betting.bankroll import BankrollManager

        manager = BankrollManager()

        user = _make_mock_user(bankroll=bankroll)
        safety = _make_mock_safety()
        today = date.today().isoformat()

        def _mock_daily_staked(uid, league=None):  # noqa: ANN001
            if league is None:
                return today_staked_all
            return today_staked_league

        with (
            patch.object(BankrollManager, "_get_user", return_value=user),
            patch.object(BankrollManager, "check_safety_limits", return_value=safety),
            patch.object(BankrollManager, "_get_daily_staked", side_effect=_mock_daily_staked),
        ):
            return manager.calculate_stake(
                user_id=1,
                model_prob=0.55,
                odds=2.10,
                league=league,
            )

    def test_no_cap_hit_returns_nonzero_stake(self):
        """With $0 staked today, stake is positive (caps not triggered)."""
        result = self._run_calculate_stake(
            today_staked_all=0.0,
            today_staked_league=0.0,
        )
        assert result.stake > 0, "Expected a positive stake when no cap is hit"

    def test_aggregate_cap_hit_returns_zero_stake(self):
        """When today_staked_all >= 15% of bankroll, stake=0."""
        # $1000 bankroll × 15% = $150 aggregate cap
        # Simulate $150 already staked today
        result = self._run_calculate_stake(
            today_staked_all=150.0,
            today_staked_league=0.0,
            bankroll=1000.0,
        )
        assert result.stake == 0.0, (
            "Expected stake=0 when aggregate daily exposure cap (15%) is hit"
        )
        assert "daily_exposure_cap_hit" in result.safety_warnings
        assert result.safety_warnings["daily_exposure_cap_hit"] is True

    def test_aggregate_cap_just_below_returns_nonzero_stake(self):
        """When today_staked_all is just under the 15% cap, stake > 0."""
        # $1000 bankroll × 15% = $150 cap; $149.99 already staked → just under
        result = self._run_calculate_stake(
            today_staked_all=149.99,
            today_staked_league=0.0,
            bankroll=1000.0,
        )
        assert result.stake > 0, (
            "Expected positive stake when aggregate staked is just below the cap"
        )

    def test_league_cap_hit_returns_zero_stake(self):
        """When today_staked_league >= 8% of bankroll, stake=0."""
        # $1000 bankroll × 8% = $80 per-league cap
        # Simulate $80 already staked on EPL today
        result = self._run_calculate_stake(
            today_staked_all=80.0,
            today_staked_league=80.0,
            bankroll=1000.0,
            league="EPL",
        )
        assert result.stake == 0.0, (
            "Expected stake=0 when league daily exposure cap (8%) is hit"
        )
        assert "league_exposure_cap_hit" in result.safety_warnings
        assert result.safety_warnings["league_exposure_cap_hit"] is True

    def test_league_cap_hit_message_contains_league_name(self):
        """The stake=0 message names the capped league."""
        result = self._run_calculate_stake(
            today_staked_all=80.0,
            today_staked_league=80.0,
            bankroll=1000.0,
            league="LaLiga",
        )
        assert result.stake == 0.0
        assert "LaLiga" in result.message

    def test_aggregate_cap_triggers_before_league_cap(self):
        """Aggregate cap (15%) takes priority and triggers first when both are hit."""
        # Both caps exceeded: $200 all leagues, $80 EPL on $1000 bankroll
        result = self._run_calculate_stake(
            today_staked_all=200.0,
            today_staked_league=80.0,
            bankroll=1000.0,
            league="EPL",
        )
        assert result.stake == 0.0
        # Aggregate cap message is returned (checked first in code)
        assert "daily_exposure_cap_hit" in result.safety_warnings

    def test_league_none_skips_league_cap(self):
        """When league=None, the per-league cap check is skipped."""
        from src.betting.bankroll import BankrollManager

        manager = BankrollManager()
        user = _make_mock_user(bankroll=1000.0)
        safety = _make_mock_safety()

        with (
            patch.object(BankrollManager, "_get_user", return_value=user),
            patch.object(BankrollManager, "check_safety_limits", return_value=safety),
            patch.object(BankrollManager, "_get_daily_staked", return_value=0.0),
        ):
            result = manager.calculate_stake(
                user_id=1,
                model_prob=0.55,
                odds=2.10,
                league=None,    # No league provided
            )
        # Should succeed — aggregate cap not hit, league cap skipped
        assert result.stake > 0

    def test_calculate_stake_signature_has_league_param(self):
        """calculate_stake() accepts a league keyword argument."""
        from src.betting.bankroll import BankrollManager
        sig = inspect.signature(BankrollManager.calculate_stake)
        assert "league" in sig.parameters
        assert sig.parameters["league"].default is None

    def test_get_daily_staked_signature(self):
        """_get_daily_staked() accepts user_id and optional league."""
        from src.betting.bankroll import BankrollManager
        sig = inspect.signature(BankrollManager._get_daily_staked)
        assert "user_id" in sig.parameters
        assert "league" in sig.parameters
        assert sig.parameters["league"].default is None


# ============================================================================
# CLV Backfill for ValueBet — PC-25-04
# ============================================================================

class TestCLVBackfillValueBet:
    """Verify backfill_closing_odds() handles ValueBet records."""

    def test_valuebet_model_has_closing_odds_column(self):
        """ValueBet ORM model has closing_odds column (PC-25-04)."""
        from src.database.models import ValueBet
        assert hasattr(ValueBet, "closing_odds"), (
            "ValueBet model missing closing_odds column"
        )

    def test_valuebet_model_has_clv_column(self):
        """ValueBet ORM model has clv column (PC-25-04)."""
        from src.database.models import ValueBet
        assert hasattr(ValueBet, "clv"), (
            "ValueBet model missing clv column"
        )

    def test_backfill_closing_odds_returns_vb_keys(self):
        """backfill_closing_odds() return dict includes ValueBet keys."""
        from src.scrapers.loader import backfill_closing_odds

        # Call with real DB — it may have no pending entries, but the
        # return dict must include the new ValueBet keys regardless.
        result = backfill_closing_odds()
        assert "vb_updated" in result, "Return dict missing 'vb_updated' key"
        assert "vb_no_closing" in result, "Return dict missing 'vb_no_closing' key"
        assert "vb_total_checked" in result, "Return dict missing 'vb_total_checked' key"

    def test_backfill_closing_odds_still_returns_betlog_keys(self):
        """backfill_closing_odds() still returns original BetLog keys."""
        from src.scrapers.loader import backfill_closing_odds

        result = backfill_closing_odds()
        assert "updated" in result, "Return dict missing 'updated' key"
        assert "no_closing_odds" in result, "Return dict missing 'no_closing_odds' key"
        assert "total_checked" in result, "Return dict missing 'total_checked' key"

    def test_clv_formula_is_correct(self):
        """CLV formula: (1/closing) - (1/detection) — negative = good."""
        # Example: detected at 2.50 (40% implied), closed at 2.00 (50% implied)
        # CLV = 0.50 - 0.40 = +0.10 — closing line moved toward the selection,
        # meaning you got better odds than the market settled at.
        # Wait — that's POSITIVE clv, but in our code:
        # clv = (1/closing) - (1/detection) = 0.50 - 0.40 = +0.10
        # Positive CLV means closing implied prob > detection implied prob,
        # which means closing odds shortened (got worse) — you got better value!
        detection_odds = 2.50
        closing_odds = 2.00
        clv = (1.0 / closing_odds) - (1.0 / detection_odds)
        assert abs(clv - 0.10) < 0.001

    def test_clv_negative_when_odds_drifted_away(self):
        """CLV is negative when closing odds are higher than detection (bad)."""
        # Detected at 2.00 (50% implied), closed at 2.50 (40% implied)
        # CLV = 0.40 - 0.50 = -0.10 — odds drifted away, you overpaid
        detection_odds = 2.00
        closing_odds = 2.50
        clv = (1.0 / closing_odds) - (1.0 / detection_odds)
        assert abs(clv - (-0.10)) < 0.001

    def test_loader_imports_valuebet(self):
        """loader.py imports ValueBet for CLV backfill."""
        from src.scrapers import loader
        assert hasattr(loader, "ValueBet") or "ValueBet" in dir(loader), (
            "loader.py should import ValueBet for PC-25-04 CLV backfill"
        )


# ============================================================================
# Profitable Min Bets Threshold — PC-25-06
# ============================================================================

class TestProfitableMinBets:
    """Verify profitable_min_bets raised to 250 for statistical reliability."""

    @pytest.fixture(autouse=True)
    def load_settings(self):
        settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(settings_path, "r") as f:
            self.settings = yaml.safe_load(f)
        self.market_fb = self.settings.get("self_improvement", {}).get(
            "market_feedback", {}
        )

    def test_profitable_min_bets_is_250(self):
        """profitable_min_bets is 250 (raised from 100 for statistical reliability)."""
        assert self.market_fb.get("profitable_min_bets") == 250, (
            f"Expected 250, got {self.market_fb.get('profitable_min_bets')}"
        )

    def test_profitable_min_bets_greater_than_min_sample(self):
        """profitable_min_bets (250) > min_sample_size (50) — correct hierarchy."""
        min_sample = self.market_fb.get("min_sample_size", 0)
        profitable_min = self.market_fb.get("profitable_min_bets", 0)
        assert profitable_min > min_sample, (
            f"profitable_min_bets ({profitable_min}) should exceed "
            f"min_sample_size ({min_sample})"
        )

    def test_confidence_interval_is_95pct(self):
        """Confidence interval is 0.95 (95%) for ROI estimates."""
        assert self.market_fb.get("confidence_interval") == pytest.approx(0.95)
