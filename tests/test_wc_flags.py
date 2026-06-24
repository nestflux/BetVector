"""WC-08-01 — country flag assets + render helper."""

from src.world_cup.flags import FIFA_TO_ISO, _FLAG_BORDER, flag_path, render_flag


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


class TestUniformFlagBox:
    """DF-03 — every flag renders into one fixed box: same width, object-fit
    (no distortion), and a visible border so pale flags don't bleed into the bg."""

    def test_fixed_three_two_box(self):
        # Default height 18 → width round(18*1.5)=27. One uniform cell.
        html = render_flag("BRA")
        assert 'width="27"' in html and 'height="18"' in html

    def test_width_scales_with_height(self):
        # Box stays 3:2 at any height (24 → 36), so flags never go ragged.
        html = render_flag("ARG", height=24)
        assert 'width="36"' in html and 'height="24"' in html

    def test_object_fit_cover_prevents_distortion(self):
        # cover fills the cell by trimming the long edge, never stretching.
        assert "object-fit:cover" in render_flag("BRA")

    def test_pale_flags_have_visible_edge(self):
        # The 1px border is the "visible edge" from the acceptance criteria.
        assert f"border:1px solid {_FLAG_BORDER}" in render_flag("BRA")

    def test_missing_flag_keeps_same_cell_size(self):
        # Fallback occupies an identically sized bordered cell so a missing
        # flag doesn't break row alignment.
        html = render_flag("XXX")
        assert "<img" not in html and "XXX" in html
        assert "width:27px" in html and "height:18px" in html
        assert f"border:1px solid {_FLAG_BORDER}" in html
