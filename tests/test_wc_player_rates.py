"""WC-11A-01 — player rate engine + name resolver (display-only foundation).

The resolver is the make-or-break for accuracy: it must map a confirmed-XI player
name to the right club-stats record, and — critically — return None (blank) rather
than guess when a name is ambiguous. These tests exercise the pure helpers plus the
resolve/rate path over a tiny fixture cache (no raw Transfermarkt files needed)."""

import gzip

import pytest

import src.world_cup.player_rates as pr


class TestNormalize:
    def test_accent_fold_and_lower(self):
        assert pr._normalize("Vinícius Júnior") == "vinicius junior"

    def test_strips_punctuation(self):
        assert pr._normalize("N'Golo Kanté") == "n golo kante"

    def test_missing_inputs(self):
        assert pr._normalize(None) == ""
        assert pr._normalize(float("nan")) == ""


class TestPosBuckets:
    def test_espn_buckets(self):
        assert pr._espn_pos_bucket("G") == "GK"
        assert pr._espn_pos_bucket("DM") == "MID"      # defensive MIDfielder, not DEF
        assert pr._espn_pos_bucket("CD-L") == "DEF"
        assert pr._espn_pos_bucket("CF-R") == "FWD"
        assert pr._espn_pos_bucket("F") == "FWD"
        assert pr._espn_pos_bucket("RB") == "DEF"
        assert pr._espn_pos_bucket("CM") == "MID"
        assert pr._espn_pos_bucket(None) is None

    def test_tm_buckets(self):
        assert pr._tm_pos_bucket("Goalkeeper") == "GK"
        assert pr._tm_pos_bucket("Defender") == "DEF"
        assert pr._tm_pos_bucket("Midfield") == "MID"
        assert pr._tm_pos_bucket("Attack") == "FWD"

    def test_nation_alias(self):
        assert pr._nation_key("USA") == "united states"
        assert pr._nation_key("South Korea") == "korea south"
        assert pr._nation_key("England") == "england"      # no alias -> normalised name


def _row(pid, name, country, gp90, bucket="FWD", pos="Attack", last=2025,
         pen=0, intl_g=0, intl_c=0, mins=8000, yc=0.10):
    vals = {
        "player_id": pid, "name": name, "norm_name": pr._normalize(name),
        "country": country, "norm_country": pr._normalize(country),
        "position": pos, "sub_position": "", "pos_bucket": bucket,
        "goals_per_90": "" if gp90 is None else gp90, "minutes_recent": mins,
        "yellows_per_90": yc, "pen_goals": pen, "is_pen_taker": pen >= pr.PEN_THRESHOLD,
        "intl_goals": intl_g, "intl_caps": intl_c, "market_value_eur": "",
        "last_season": last,
    }
    return ",".join(str(vals[c]) for c in pr._CACHE_COLS)


@pytest.fixture
def fixture_cache(tmp_path, monkeypatch):
    """A tiny committed-cache stand-in covering the tricky resolver cases."""
    rows = [
        _row(1, "Harry Kane", "England", 1.15, pen=8, intl_g=68, intl_c=100),
        _row(2, "Rodri", "Spain", 0.07, bucket="MID", pos="Midfield", last=2025),   # active
        _row(3, "Rodri", "Spain", None, bucket="DEF", pos="Defender", last=2013, mins=0),  # retired
        _row(4, "Cristiano Ronaldo", "Portugal", None, mins=0, intl_g=130, intl_c=200),    # Saudi -> intl
        _row(5, "Bruno", "Spain", 0.20, bucket="MID", pos="Midfield", last=2025),
        _row(6, "Bruno", "Spain", 0.30, bucket="FWD", pos="Attack", last=2025),
        _row(7, "Christian Pulisic", "United States", 0.35),
        _row(8, "Kylian Mbappé", "France", 0.92, pen=5),
    ]
    p = tmp_path / "rates.csv.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write(",".join(pr._CACHE_COLS) + "\n" + "\n".join(rows) + "\n")
    monkeypatch.setattr(pr, "CACHE_PATH", p)
    pr.reset_cache()
    yield
    pr.reset_cache()


class TestResolver:
    def test_exact_name_nation(self, fixture_cache):
        assert pr.resolve_player("Harry Kane", "England") == 1

    def test_accent_insensitive(self, fixture_cache):
        assert pr.resolve_player("Kylian Mbappe", "France") == 8     # query has no accent

    def test_nation_alias_usa(self, fixture_cache):
        assert pr.resolve_player("Christian Pulisic", "USA") == 7    # USA -> United States

    def test_recency_tiebreak_picks_active(self, fixture_cache):
        assert pr.resolve_player("Rodri", "Spain") == 2              # active over retired

    def test_ambiguous_without_position_blanks(self, fixture_cache):
        assert pr.resolve_player("Bruno", "Spain") is None          # two active same-season

    def test_position_breaks_tie(self, fixture_cache):
        assert pr.resolve_player("Bruno", "Spain", position="DM") == 5   # MID
        assert pr.resolve_player("Bruno", "Spain", position="CF") == 6   # FWD

    def test_unknown_blanks(self, fixture_cache):
        assert pr.resolve_player("Nobody Here", "Brazil") is None

    def test_override_map_wins(self, fixture_cache, monkeypatch):
        # A curated override resolves outright, past a normal ambiguity (Bruno
        # alone is ambiguous -> None; the override pins it to a specific id).
        monkeypatch.setattr(pr, "_OVERRIDE", {(pr._normalize("Bruno"), "spain"): 6})
        assert pr.resolve_player("Bruno", "Spain") == 6


class TestPlayerRate:
    def test_club_form(self, fixture_cache):
        r = pr.player_rate("Harry Kane", "England")
        assert r["source"] == "club"
        assert abs(r["goals_per_90"] - 1.15) < 1e-9
        assert r["is_pen_taker"] is True
        assert r["pos_bucket"] == "FWD"

    def test_international_fallback(self, fixture_cache):
        r = pr.player_rate("Cristiano Ronaldo", "Portugal")
        assert r["source"] == "international"
        assert abs(r["goals_per_90"] - 130 / 200) < 1e-9            # goals per cap

    def test_blank_on_ambiguous(self, fixture_cache):
        assert pr.player_rate("Bruno", "Spain") is None

    def test_unknown_returns_none(self, fixture_cache):
        assert pr.player_rate("Nobody Here", "Brazil") is None
