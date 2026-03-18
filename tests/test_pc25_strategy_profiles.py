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


# ============================================================================
# Stake Multiplier Calibration — PC-25-09
# ============================================================================

class TestStakeMultiplierConfig:
    """Verify stake_multiplier values match assessment tiers."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        config_path = Path(__file__).parent.parent / "config" / "leagues.yaml"
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.league_map = {lg["short_name"]: lg for lg in self.config["leagues"]}

    def test_championship_multiplier_is_1_5(self):
        """Championship (🟢 profitable) gets 1.5× stake multiplier."""
        assert self.league_map["Championship"]["strategy"]["stake_multiplier"] == 1.5

    def test_epl_multiplier_is_1_0(self):
        """EPL (🟡 promising) gets 1.0× stake multiplier."""
        assert self.league_map["EPL"]["strategy"]["stake_multiplier"] == 1.0

    def test_laliga_multiplier_is_1_0(self):
        """LaLiga (🟡 promising) gets 1.0× stake multiplier."""
        assert self.league_map["LaLiga"]["strategy"]["stake_multiplier"] == 1.0

    def test_ligue1_multiplier_is_0_5(self):
        """Ligue1 (🔴 unprofitable) gets 0.5× stake multiplier."""
        assert self.league_map["Ligue1"]["strategy"]["stake_multiplier"] == 0.5

    def test_bundesliga_multiplier_is_0_5(self):
        """Bundesliga (🔴 unprofitable) gets 0.5× stake multiplier."""
        assert self.league_map["Bundesliga"]["strategy"]["stake_multiplier"] == 0.5

    def test_seriea_multiplier_is_0_5(self):
        """SerieA (🔴 unprofitable) gets 0.5× stake multiplier."""
        assert self.league_map["SerieA"]["strategy"]["stake_multiplier"] == 0.5


class TestStakeMultiplierEnforcement:
    """Verify BankrollManager.calculate_stake() applies the multiplier."""

    def _run_with_multiplier(self, league: str, bankroll: float = 1000.0):
        """
        Run calculate_stake() with a mocked league and return the result.
        Uses the real config to look up the league's stake_multiplier.
        """
        from src.betting.bankroll import BankrollManager

        manager = BankrollManager()
        user = _make_mock_user(bankroll=bankroll)
        safety = _make_mock_safety()

        with (
            patch.object(BankrollManager, "_get_user", return_value=user),
            patch.object(BankrollManager, "check_safety_limits", return_value=safety),
            patch.object(BankrollManager, "_get_daily_staked", return_value=0.0),
        ):
            return manager.calculate_stake(
                user_id=1,
                model_prob=0.55,
                odds=2.10,
                league=league,
            )

    def test_championship_stake_is_1_5x_base(self):
        """Championship (1.5×) should produce 1.5× the EPL (1.0×) stake."""
        epl_result = self._run_with_multiplier("EPL")
        champ_result = self._run_with_multiplier("Championship")
        # Championship stake should be 1.5× EPL stake
        assert champ_result.stake == pytest.approx(epl_result.stake * 1.5, rel=0.01), (
            f"Championship ${champ_result.stake} should be 1.5× EPL ${epl_result.stake}"
        )

    def test_ligue1_stake_is_0_5x_base(self):
        """Ligue1 (0.5×) should produce half the EPL (1.0×) stake."""
        epl_result = self._run_with_multiplier("EPL")
        ligue1_result = self._run_with_multiplier("Ligue1")
        assert ligue1_result.stake == pytest.approx(epl_result.stake * 0.5, rel=0.01), (
            f"Ligue1 ${ligue1_result.stake} should be 0.5× EPL ${epl_result.stake}"
        )

    def test_unknown_league_defaults_to_1x(self):
        """Unknown league name defaults to 1.0× (no multiplier)."""
        epl_result = self._run_with_multiplier("EPL")
        unknown_result = self._run_with_multiplier("FakeLeague")
        assert unknown_result.stake == pytest.approx(epl_result.stake, rel=0.01), (
            "Unknown league should use 1.0× multiplier (same as EPL)"
        )

    def test_none_league_defaults_to_1x(self):
        """league=None skips multiplier (same as 1.0×)."""
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
                user_id=1, model_prob=0.55, odds=2.10, league=None,
            )
        # Default flat stake: $1000 × 2% = $20
        assert result.stake == pytest.approx(20.0, rel=0.01)

    def test_multiplier_applied_before_cap(self):
        """Multiplier is applied before the max bet cap, so cap still protects."""
        # Championship at 1.5× on a $200 bankroll:
        # Base stake = $200 × 2% = $4, multiplied = $4 × 1.5 = $6
        # Max cap = $200 × 5% = $10 → $6 < $10, so not capped
        result = self._run_with_multiplier("Championship", bankroll=200.0)
        assert result.stake == pytest.approx(6.0, rel=0.01)

    def test_multiplier_message_includes_league(self):
        """Stake message includes the multiplier info when != 1.0."""
        result = self._run_with_multiplier("Championship")
        assert "1.5" in result.message, (
            f"Message should mention 1.5× multiplier: {result.message}"
        )

    def test_tracker_match_info_has_league_short_name(self):
        """_get_match_info() returns league_short_name for multiplier lookup."""
        from src.betting.tracker import _get_match_info
        sig_source = inspect.getsource(_get_match_info)
        assert "league_short_name" in sig_source, (
            "_get_match_info() must return league_short_name for PC-25-09"
        )


# ============================================================================
# Weekly Strategy Review — PC-25-11
# ============================================================================

class TestWeeklyStrategyReview:
    """Verify automated weekly strategy review components (PC-25-11).

    PC-25-11 extends the Sunday pipeline to detect tier transitions,
    generate strategy suggestions (never auto-applied), and include
    them in the weekly summary email.
    """

    def test_detect_tier_transitions_exists(self):
        """detect_tier_transitions() is importable from market_feedback."""
        from src.self_improvement.market_feedback import detect_tier_transitions
        assert callable(detect_tier_transitions)

    def test_detect_tier_transitions_returns_list(self):
        """detect_tier_transitions() returns a list."""
        from src.self_improvement.market_feedback import detect_tier_transitions
        result = detect_tier_transitions()
        assert isinstance(result, list)

    def test_generate_strategy_suggestions_exists(self):
        """generate_strategy_suggestions() is importable from market_feedback."""
        from src.self_improvement.market_feedback import generate_strategy_suggestions
        assert callable(generate_strategy_suggestions)

    def test_generate_strategy_suggestions_returns_list(self):
        """generate_strategy_suggestions() returns a list for empty input."""
        from src.self_improvement.market_feedback import generate_strategy_suggestions
        result = generate_strategy_suggestions([])
        assert isinstance(result, list)
        assert len(result) == 0

    def test_suggestions_never_auto_applied(self):
        """Strategy suggestions have action keys but are never auto-applied.

        The code SUGGESTS changes — the human operator decides whether
        to update leagues.yaml manually.
        """
        from src.self_improvement.market_feedback import generate_strategy_suggestions
        # Simulate an upgrade transition
        transitions = [{
            "league": "TestLeague",
            "old_tier": "promising",
            "new_tier": "profitable",
            "direction": "upgrade",
            "detail": "🟡 promising → 🟢 profitable",
        }]
        suggestions = generate_strategy_suggestions(transitions)
        assert len(suggestions) == 1
        s = suggestions[0]
        assert "suggestion" in s
        assert "reason" in s
        assert "action" in s
        assert s["action"] == "increase_exposure"

    def test_downgrade_suggestion(self):
        """Downgrade to unprofitable generates reduce_exposure suggestion."""
        from src.self_improvement.market_feedback import generate_strategy_suggestions
        transitions = [{
            "league": "TestLeague",
            "old_tier": "promising",
            "new_tier": "unprofitable",
            "direction": "downgrade",
            "detail": "🟡 promising → 🔴 unprofitable",
        }]
        suggestions = generate_strategy_suggestions(transitions)
        assert len(suggestions) == 1
        assert suggestions[0]["action"] == "reduce_exposure"

    def test_pipeline_calls_weekly_review(self):
        """Pipeline has weekly market performance & strategy review section."""
        source_path = Path(__file__).parent.parent / "src" / "pipeline.py"
        source = source_path.read_text()
        assert "detect_tier_transitions" in source
        assert "generate_strategy_suggestions" in source
        assert "update_market_performance" in source

    def test_weekly_email_template_has_tier_section(self):
        """Weekly summary email template includes tier transitions section."""
        template_path = Path(__file__).parent.parent / "templates" / "weekly_summary.html"
        template = template_path.read_text()
        assert "tier_transitions" in template
        assert "strategy_suggestions" in template
        assert "League Tier Changes" in template

    def test_weekly_email_loader_passes_transitions(self):
        """_load_weekly_data() passes tier_transitions to template."""
        source_path = Path(__file__).parent.parent / "src" / "delivery" / "email_alerts.py"
        source = source_path.read_text()
        assert "tier_transitions" in source
        assert "strategy_suggestions" in source

    def test_tier_rank_ordering(self):
        """Tier ranking: profitable > promising > insufficient > unprofitable."""
        from src.self_improvement.market_feedback import detect_tier_transitions
        # Verify the function exists and can be inspected
        source = inspect.getsource(detect_tier_transitions)
        assert "TIER_RANK" in source
        # The rank dict should have 4 tiers
        assert '"profitable": 4' in source or "'profitable': 4" in source


# ============================================================================
# Shadow Mode — PC-25-12
# ============================================================================

class TestShadowModeConfig:
    """Verify shadow mode configuration exists in leagues.yaml."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        config_path = Path(__file__).parent.parent / "config" / "leagues.yaml"
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.league_map = {lg["short_name"]: lg for lg in self.config["leagues"]}

    def test_every_league_has_shadow_mode(self):
        """All leagues have shadow_mode key in strategy block."""
        for lg in self.config["leagues"]:
            strategy = lg.get("strategy", {})
            assert "shadow_mode" in strategy, (
                f"{lg['short_name']} missing shadow_mode in strategy"
            )

    def test_shadow_mode_is_boolean(self):
        """shadow_mode is boolean in every league."""
        for lg in self.config["leagues"]:
            sm = lg["strategy"]["shadow_mode"]
            assert isinstance(sm, bool), (
                f"{lg['short_name']} shadow_mode should be bool, got {type(sm)}"
            )

    def test_all_leagues_start_with_shadow_off(self):
        """All leagues start with shadow_mode=False (manual opt-in only)."""
        for lg in self.config["leagues"]:
            assert lg["strategy"]["shadow_mode"] is False, (
                f"{lg['short_name']} should start with shadow_mode=False"
            )


class TestShadowBetStorage:
    """Verify shadow bets are stored separately from real value bets."""

    def test_shadow_value_bet_model_exists(self):
        """ShadowValueBet ORM model is importable."""
        from src.database.models import ShadowValueBet
        assert ShadowValueBet is not None

    def test_shadow_value_bet_has_required_columns(self):
        """ShadowValueBet has all required columns."""
        from src.database.models import ShadowValueBet
        required = [
            "id", "match_id", "league", "market_type", "selection",
            "model_prob", "bookmaker_odds", "edge", "shadow_stake",
            "strategy_change", "created_at",
        ]
        for col in required:
            assert hasattr(ShadowValueBet, col), (
                f"ShadowValueBet missing column: {col}"
            )

    def test_shadow_bet_not_in_main_value_bets(self):
        """Shadow bets use a separate table, not the main value_bets table."""
        from src.database.models import ShadowValueBet, ValueBet
        assert ShadowValueBet.__tablename__ != ValueBet.__tablename__


class TestShadowPnLTracking:
    """Verify shadow P&L tracking per league."""

    def test_shadow_pnl_function_exists(self):
        """compute_shadow_pnl() exists in market_feedback."""
        from src.self_improvement.market_feedback import compute_shadow_pnl
        assert callable(compute_shadow_pnl)

    def test_shadow_comparison_report_function_exists(self):
        """generate_shadow_comparison() exists in market_feedback."""
        from src.self_improvement.market_feedback import generate_shadow_comparison
        assert callable(generate_shadow_comparison)


# ============================================================================
# Per-League Model Variants — PC-25-13
# ============================================================================

class TestPerLeagueModelConfig:
    """Verify per-league model variant configuration."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        config_path = Path(__file__).parent.parent / "config" / "leagues.yaml"
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.league_map = {lg["short_name"]: lg for lg in self.config["leagues"]}

    def test_every_league_has_model_params(self):
        """All leagues have model_params block in config."""
        for lg in self.config["leagues"]:
            assert "model_params" in lg, (
                f"{lg['short_name']} missing model_params block"
            )

    def test_lambda_clamps_per_league(self):
        """Each league has lambda_min and lambda_max."""
        for lg in self.config["leagues"]:
            mp = lg.get("model_params", {})
            assert "lambda_min" in mp, f"{lg['short_name']} missing lambda_min"
            assert "lambda_max" in mp, f"{lg['short_name']} missing lambda_max"
            assert mp["lambda_min"] > 0
            assert mp["lambda_max"] > mp["lambda_min"]

    def test_bundesliga_scores_more(self):
        """Bundesliga has higher lambda_max than Serie A (scores more goals)."""
        bund = self.league_map["Bundesliga"]["model_params"]
        seriea = self.league_map["SerieA"]["model_params"]
        assert bund["lambda_max"] >= seriea["lambda_max"]

    def test_training_weight_exists(self):
        """Each league has training_weight in model_params."""
        for lg in self.config["leagues"]:
            mp = lg.get("model_params", {})
            assert "training_weight" in mp, (
                f"{lg['short_name']} missing training_weight"
            )
            assert mp["training_weight"] > 0


class TestPoissonUsesPerLeagueLambda:
    """Verify Poisson model can read per-league lambda clamps."""

    def test_poisson_predict_accepts_league_param(self):
        """PoissonModel.predict() accepts a league parameter."""
        from src.models.poisson import PoissonModel
        sig = inspect.signature(PoissonModel.predict)
        assert "league" in sig.parameters

    def test_poisson_model_has_lambda_clamp_config(self):
        """PoissonModel reads lambda clamps from league config."""
        from src.models.poisson import PoissonModel
        source = inspect.getsource(PoissonModel.predict)
        assert "lambda_min" in source or "model_params" in source


# ============================================================================
# Probabilistic Kelly — PC-25-15
# ============================================================================

class TestProbabilisticKellyConfig:
    """Verify per-league Kelly staking configuration."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        config_path = Path(__file__).parent.parent / "config" / "leagues.yaml"
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.league_map = {lg["short_name"]: lg for lg in self.config["leagues"]}

    def test_every_league_has_staking_method(self):
        """All leagues have staking_method in strategy."""
        for lg in self.config["leagues"]:
            strategy = lg.get("strategy", {})
            assert "staking_method" in strategy, (
                f"{lg['short_name']} missing staking_method in strategy"
            )

    def test_staking_method_values(self):
        """staking_method is 'flat' or 'kelly'."""
        for lg in self.config["leagues"]:
            method = lg["strategy"]["staking_method"]
            assert method in ("flat", "kelly"), (
                f"{lg['short_name']} has invalid staking_method: {method}"
            )

    def test_championship_uses_kelly(self):
        """Championship (only 🟢 profitable) uses Kelly staking."""
        assert self.league_map["Championship"]["strategy"]["staking_method"] == "kelly"

    def test_unprofitable_leagues_use_flat(self):
        """🔴 unprofitable leagues use flat staking (conservative)."""
        for name in ["Ligue1", "Bundesliga", "SerieA"]:
            assert self.league_map[name]["strategy"]["staking_method"] == "flat", (
                f"{name} should use flat staking (🔴 tier)"
            )

    def test_kelly_max_bet_3_pct(self):
        """Kelly leagues have max_bet_percentage of 3% (not 5%)."""
        for lg in self.config["leagues"]:
            if lg["strategy"]["staking_method"] == "kelly":
                mp = lg.get("strategy", {})
                assert "kelly_max_bet_pct" in mp, (
                    f"{lg['short_name']} Kelly league missing kelly_max_bet_pct"
                )
                assert mp["kelly_max_bet_pct"] == 0.03

    def test_kelly_drawdown_rollback(self):
        """Kelly leagues have drawdown_rollback_pct for auto-rollback."""
        for lg in self.config["leagues"]:
            if lg["strategy"]["staking_method"] == "kelly":
                strategy = lg.get("strategy", {})
                assert "drawdown_rollback_pct" in strategy, (
                    f"{lg['short_name']} Kelly league missing drawdown_rollback_pct"
                )
                assert strategy["drawdown_rollback_pct"] == 0.15


class TestBankrollManagerKellyPerLeague:
    """Verify BankrollManager uses per-league Kelly when configured."""

    def test_calculate_stake_reads_league_staking_method(self):
        """calculate_stake() checks league's staking_method config."""
        from src.betting.bankroll import BankrollManager
        source = inspect.getsource(BankrollManager.calculate_stake)
        assert "staking_method" in source
