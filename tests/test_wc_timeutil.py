"""WC-08-02 — Eastern-time conversion for kickoff display."""

from src.world_cup.timeutil import to_eastern, format_kickoff_et, eastern_date


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
