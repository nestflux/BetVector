"""WC-08-02 — Eastern-time conversion for kickoff display.
DF-02 — tournament-window helper that drives the WC login landing page."""

from datetime import date

from src.world_cup.timeutil import (
    to_eastern, format_kickoff_et, eastern_date, wc_window_active, tournament_window,
)


class TestToEastern:
    def test_june_kickoff_is_edt_utc_minus_4(self):
        # 2026-06-24 18:00 UTC -> 14:00 EDT (UTC-4 in summer)
        et = to_eastern("2026-06-24", "18:00")
        assert (et.hour, et.minute) == (14, 0)
        assert et.tzinfo is not None

    def test_accepts_hh_mm_ss(self):
        assert to_eastern("2026-06-24", "18:00:00").hour == 14

    def test_missing_inputs_return_none(self):
        assert to_eastern(None, "18:00") is None
        assert to_eastern("2026-06-24", None) is None
        assert to_eastern("2026-06-24", "") is None

    def test_garbage_returns_none(self):
        assert to_eastern("not-a-date", "18:00") is None
        assert to_eastern("2026-06-24", "nope") is None


class TestFormat:
    def test_basic_format(self):
        # 2026-06-24 is a Wednesday; 18:00 UTC -> 2:00 PM ET
        assert format_kickoff_et("2026-06-24", "18:00") == "Wed 2:00 PM ET"

    def test_no_leading_zero_on_hour(self):
        # 13:00 UTC -> 9:00 AM ET (not 09:00)
        assert format_kickoff_et("2026-06-24", "13:00", with_day=False) == "9:00 AM ET"

    def test_without_day(self):
        assert format_kickoff_et("2026-06-24", "18:00", with_day=False) == "2:00 PM ET"

    def test_missing_shows_placeholder(self):
        assert format_kickoff_et("2026-06-24", None) == "TBD"
        assert format_kickoff_et(None, None, placeholder="—") == "—"


class TestDateShift:
    def test_late_utc_kickoff_rolls_back_to_previous_eastern_day(self):
        # 2026-06-25 02:00 UTC -> 2026-06-24 22:00 ET
        assert eastern_date("2026-06-25", "02:00") == "2026-06-24"
        assert format_kickoff_et("2026-06-25", "02:00") == "Wed 10:00 PM ET"

    def test_same_day_when_no_rollover(self):
        assert eastern_date("2026-06-24", "18:00") == "2026-06-24"


class TestTournamentWindow:
    """DF-02 — wc_window_active gates the World Cup landing page."""

    def test_window_reads_config(self):
        # WC 2026 runs Jun 11 – Jul 19, 2026 (config/worldcup_2026.yaml)
        assert tournament_window() == (date(2026, 6, 11), date(2026, 7, 19))

    def test_active_inside_window(self):
        assert wc_window_active(date(2026, 6, 24)) is True

    def test_active_on_start_boundary(self):
        assert wc_window_active(date(2026, 6, 11)) is True       # inclusive

    def test_active_on_end_boundary(self):
        assert wc_window_active(date(2026, 7, 19)) is True        # inclusive

    def test_inactive_day_before(self):
        assert wc_window_active(date(2026, 6, 10)) is False

    def test_inactive_day_after_final(self):
        assert wc_window_active(date(2026, 7, 20)) is False       # reverts next day

    def test_no_arg_uses_today_without_crashing(self):
        # The default-today branch must run and return a bool (value is date-dependent).
        assert isinstance(wc_window_active(), bool)

    def test_inactive_when_window_unconfigured(self, monkeypatch):
        import src.world_cup.timeutil as tu
        monkeypatch.setattr(tu, "tournament_window", lambda: None)
        assert tu.wc_window_active(date(2026, 6, 24)) is False    # safe fallback
