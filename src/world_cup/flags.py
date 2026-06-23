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


def render_flag(fifa_code: str, height: int = 18) -> str:
    """Inline base64 ``<img>`` for the team's flag for use inside
    ``st.markdown(unsafe_allow_html=True)``.

    Falls back to the FIFA code as small grey text when the asset is missing —
    never raises, so a missing flag can't break a dashboard row.
    """
    b64 = _flag_b64(fifa_code)
    if not b64:
        label = escape((fifa_code or "?").upper())
        return f'<span style="font-size:0.7rem;color:#8B949E">{label}</span>'
    return (
        f'<img src="data:image/png;base64,{b64}" height="{height}" '
        f'style="vertical-align:middle;border-radius:2px;" '
        f'alt="{escape((fifa_code or "").upper())}">'
    )
