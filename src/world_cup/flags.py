"""
BetVector World Cup 2026 — Country Flags (WC-08-01)
====================================================
FIFA-code → ISO map, local asset paths, and an inline render helper for the
dashboard. Flags are stored as PNGs in ``data/flags/{FIFA}.png`` and tracked in
git so Streamlit Cloud serves them — the same pattern as ``data/badges/``.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from html import escape
from pathlib import Path

FLAG_DIR = Path(__file__).resolve().parents[2] / "data" / "flags"

# FIFA 3-letter code -> ISO 3166-1 alpha-2 (lowercase), as used by flagcdn.
# Home nations have no ISO country code, so they use flagcdn's sub-national
# codes (gb-eng / gb-sct / gb-wls) — that's why England and Scotland get their
# own flags rather than the Union Jack.
FIFA_TO_ISO: dict[str, str] = {
    "MEX": "mx", "CZE": "cz", "KOR": "kr", "RSA": "za",
    "CAN": "ca", "BIH": "ba", "SUI": "ch", "QAT": "qa",
    "BRA": "br", "SCO": "gb-sct", "HAI": "ht", "MAR": "ma",
    "PAR": "py", "TUR": "tr", "AUS": "au", "USA": "us",
    "ECU": "ec", "GER": "de", "CIV": "ci", "CUW": "cw",
    "NED": "nl", "SWE": "se", "JPN": "jp", "TUN": "tn",
    "BEL": "be", "IRN": "ir", "EGY": "eg", "NZL": "nz",
    "ESP": "es", "URU": "uy", "KSA": "sa", "CPV": "cv",
    "NOR": "no", "FRA": "fr", "SEN": "sn", "IRQ": "iq",
    "ARG": "ar", "AUT": "at", "ALG": "dz", "JOR": "jo",
    "COL": "co", "POR": "pt", "UZB": "uz", "COD": "cd",
    "ENG": "gb-eng", "CRO": "hr", "PAN": "pa", "GHA": "gh",
}


def flag_path(fifa_code: str) -> Path:
    """Local PNG path for a team's flag (named by FIFA code)."""
    return FLAG_DIR / f"{(fifa_code or '').upper()}.png"


@lru_cache(maxsize=64)
def _flag_b64(fifa_code: str) -> str | None:
    """Base64-encode a flag PNG once (cached). None if the asset is missing."""
    p = flag_path(fifa_code)
    if not p.is_file() or p.stat().st_size == 0:
        return None
    return base64.b64encode(p.read_bytes()).decode("ascii")


# Uniform flag box (DF-03). Every country's flag is drawn into the SAME fixed
# cell — width = height × 3:2 (the commonest national flag ratio) — regardless of
# its native aspect ratio, so a column of flags lines up cleanly beside the names
# instead of going ragged (Qatar wide, Switzerland near-square). ``object-fit:
# cover`` fills the cell without distortion (it trims a few px off the long edge
# rather than stretching), and a 1px border gives pale flags (Japan, England) a
# visible edge so they don't bleed into the #0D1117 surface.
_FLAG_RATIO = 1.5            # box width = round(height * ratio)
_FLAG_BORDER = "#30363D"     # design-system border token (matches world_cup.BORDER)


def render_flag(fifa_code: str, height: int = 18) -> str:
    """Inline base64 ``<img>`` of the team's flag inside a fixed uniform box,
    for use within ``st.markdown(unsafe_allow_html=True)``.

    Every flag renders at the same ``height × round(height * 1.5)`` cell (object-fit
    cover, rounded, subtle border) so differing national aspect ratios no longer
    produce ragged widths. Falls back to a same-size bordered cell showing the FIFA
    code when the asset is missing — never raises, and the row stays aligned.
    """
    width = round(height * _FLAG_RATIO)
    b64 = _flag_b64(fifa_code)
    if not b64:
        label = escape((fifa_code or "?").upper())
        # Same-size bordered cell so a missing flag keeps the row aligned.
        return (
            f'<span style="display:inline-block;box-sizing:border-box;'
            f'width:{width}px;height:{height}px;line-height:{height}px;'
            f'text-align:center;font-size:0.5rem;color:#8B949E;'
            f'border:1px solid {_FLAG_BORDER};border-radius:3px;'
            f'vertical-align:middle;overflow:hidden;">{label}</span>'
        )
    return (
        f'<img src="data:image/png;base64,{b64}" width="{width}" height="{height}" '
        f'style="box-sizing:border-box;object-fit:cover;'
        f'border:1px solid {_FLAG_BORDER};border-radius:3px;vertical-align:middle;" '
        f'alt="{escape((fifa_code or "").upper())}">'
    )
