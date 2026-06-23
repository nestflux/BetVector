"""Regression tests for WC value-finder selection normalization (PC-27 follow-up).

The Odds API returns h2h outcomes as team names ("Argentina") plus "Draw",
and totals as "Over"/"Under" with the line in a separate `point` field. The
WC model exposes probabilities keyed by home/draw/away and the 2.5 goals line.
A missing translation between the two meant `MARKET_TO_PROB` never matched any
real selection, so zero value bets were ever produced once odds and
predictions finally lived in the same database. These tests lock the
translation in place.
"""

from src.world_cup.value_finder import _canonical_selection

HOME = "Argentina"
AWAY = "Brazil"


class TestH2HSelections:
    def test_home_team_name_maps_to_home(self):
        assert _canonical_selection("h2h", "Argentina", HOME, AWAY, None) == "home"

    def test_away_team_name_maps_to_away(self):
        assert _canonical_selection("h2h", "Brazil", HOME, AWAY, None) == "away"

    def test_draw_maps_to_draw(self):
        assert _canonical_selection("h2h", "Draw", HOME, AWAY, None) == "draw"

    def test_draw_is_case_insensitive(self):
        assert _canonical_selection("h2h", "draw", HOME, AWAY, None) == "draw"

    def test_name_mapped_team_resolves(self):
        # The Odds API spells it "Bosnia & Herzegovina"; the DB stores
        # "Bosnia and Herzegovina" (config odds_api_name_map). The normalizer
        # must bridge that so the selection still maps to home/away.
        assert _canonical_selection(
            "h2h", "Bosnia & Herzegovina", "Bosnia and Herzegovina", AWAY, None
        ) == "home"

    def test_unknown_team_returns_none(self):
        assert _canonical_selection("h2h", "Narnia", HOME, AWAY, None) is None


class TestTotalsSelections:
    def test_over_at_2_5_maps_to_over(self):
        assert _canonical_selection("totals", "Over", HOME, AWAY, 2.5) == "over"

    def test_under_at_2_5_maps_to_under(self):
        assert _canonical_selection("totals", "Under", HOME, AWAY, 2.5) == "under"

    def test_other_line_is_rejected(self):
        # The model only prices the 2.5 line — never compare a 1.5 line price
        # against the 2.5 probability.
        assert _canonical_selection("totals", "Over", HOME, AWAY, 1.5) is None
        assert _canonical_selection("totals", "Under", HOME, AWAY, 3.5) is None

    def test_missing_point_is_accepted_as_2_5(self):
        assert _canonical_selection("totals", "Over", HOME, AWAY, None) == "over"


class TestUnsupportedMarkets:
    def test_spreads_returns_none(self):
        assert _canonical_selection("spreads", "Argentina", HOME, AWAY, -1.5) is None

    def test_h2h_lay_returns_none(self):
        # Betfair-style lay market — not a back price, must not be treated as h2h.
        assert _canonical_selection("h2h_lay", "Argentina", HOME, AWAY, None) is None

    def test_empty_selection_returns_none(self):
        assert _canonical_selection("h2h", "", HOME, AWAY, None) is None
