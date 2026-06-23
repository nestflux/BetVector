"""WC-08-01 — country flag assets + render helper."""

from src.world_cup.flags import FIFA_TO_ISO, flag_path, render_flag


class TestFlagAssets:
    def test_all_48_teams_mapped(self):
        assert len(FIFA_TO_ISO) == 48

    def test_all_flag_files_present_and_nonempty(self):
        missing = [f for f in FIFA_TO_ISO if not flag_path(f).is_file()
                   or flag_path(f).stat().st_size == 0]
        assert not missing, f"missing flag assets: {missing}"

    def test_home_nations_use_subnational_codes(self):
        # England/Scotland must NOT be the Union Jack — they use gb-eng/gb-sct.
        assert FIFA_TO_ISO["ENG"] == "gb-eng"
        assert FIFA_TO_ISO["SCO"] == "gb-sct"

    def test_england_and_scotland_flags_differ(self):
        eng = flag_path("ENG").read_bytes()
        sco = flag_path("SCO").read_bytes()
        assert eng != sco, "England and Scotland resolved to the same flag image"


class TestRenderFlag:
    def test_present_flag_returns_inline_img(self):
        html = render_flag("BRA")
        assert html.startswith("<img") and "data:image/png;base64," in html

    def test_missing_flag_falls_back_to_text(self):
        html = render_flag("XXX")  # no such asset
        assert "<img" not in html
        assert "XXX" in html  # FIFA code shown as fallback

    def test_none_code_does_not_raise(self):
        # Defensive: a null/blank code must never crash a dashboard row.
        assert isinstance(render_flag(""), str)

    def test_height_is_applied(self):
        assert 'height="26"' in render_flag("ARG", height=26)
