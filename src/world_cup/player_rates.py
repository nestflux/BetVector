"""
BetVector World Cup 2026 — Player Rate Engine + Name Resolver (WC-11A-01)
========================================================================
The data foundation for the **display-only** player-insight features (WC-11A): a
per-player scoring/discipline profile, plus a resolver that maps a confirmed-XI
player NAME (as ESPN spells it) to the right club-stats record.

DECISION-SUPPORT / SHADOW ONLY. Nothing here touches the model or any value bet —
it only powers presentation (who carries the goals, what a changed XI implies).

Source: the already-downloaded Transfermarkt dataset (``data/raw/transfermarkt/
datasets/``) — no new scraping, no API cost. Because the raw files are local-only
(``data/raw/`` is gitignored, ~100 MB), the heavy aggregation is done ONCE by
``build_player_rates()`` into a compact, committed cache
(``data/world_cup/player_rates.csv.gz``, ~thousands of rows) that the dashboard —
including Streamlit Cloud, which has no raw files — loads at runtime.

Rates explained (the owner is learning):
- **goals-per-90 (gp90):** goals scored per 90 minutes played — a rate that
  controls for how much a player actually features. ~1.0 is an elite striker,
  ~0.1 a defender. Computed over a recent window so it reflects current form.
- **penalty taker:** a designated penalty taker carries a real "anytime scorer"
  bump, so we flag it from historic penalty goals.
- **international fallback:** players in untracked leagues (Saudi, MLS) have no
  recent club gp90 here, so we fall back to international goals/caps, clearly
  labelled — never silently mixing the two.

The resolver is the make-or-break for accuracy. ESPN gives names, Transfermarkt
keys on ids, so we map on **normalised name + nation**, tiebreak on the most
recent season + position, and — critically — return ``None`` (blank) rather than
guess when a name stays ambiguous. We never attach a wrong player's stats.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
TM_DIR = _ROOT / "data" / "raw" / "transfermarkt" / "datasets"
CACHE_PATH = _ROOT / "data" / "world_cup" / "player_rates.csv.gz"

# Build parameters (config-light: these are dataset-shaping constants, not user
# tunables — the WC structure, not a strategy).
ACTIVE_SINCE = 2022      # keep players whose last recorded season is >= this
RECENT_YEARS = 2         # gp90 / cards / penalties measured over this trailing window
MIN_MINUTES = 270        # ~3 full matches: below this, a club gp90 isn't reliable
PEN_THRESHOLD = 2        # >= this many penalty goals in the window => a taker

# Columns persisted in the cache (order matters for the CSV).
_CACHE_COLS = [
    "player_id", "name", "norm_name", "country", "norm_country",
    "position", "sub_position", "pos_bucket", "goals_per_90", "minutes_recent",
    "yellows_per_90", "pen_goals", "is_pen_taker", "intl_goals", "intl_caps",
    "market_value_eur", "last_season",
]


# ---------------------------------------------------------------------------
# Normalisation + position bucketing (pure)
# ---------------------------------------------------------------------------

def _normalize(s) -> str:
    """Accent-fold + lowercase + strip punctuation so "Vinícius Júnior" and
    "Vinicius Junior" compare equal. Empty string for missing input."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# WC team name (as we store it) -> Transfermarkt country_of_citizenship form,
# both normalised. Only the cases where the two genuinely diverge need an entry;
# everything else matches directly, and a miss falls back to a name-only lookup.
# Verified against the actual Transfermarkt country spellings (WC-11A-01). Only
# genuinely divergent names need an entry; "DR Congo", "Cape Verde", "Senegal",
# etc. match directly once normalised, and any miss falls through to a name-only
# lookup, so this map only has to cover the common-name disambiguation cases.
_NATION_ALIASES = {
    "usa": "united states",            # TM: "United States"
    "south korea": "korea south",      # TM: "Korea, South"
    "korea republic": "korea south",
    "ivory coast": "cote d ivoire",    # TM: "Cote d'Ivoire"
    "czechia": "czech republic",       # TM: "Czech Republic"
}


def _nation_key(nation: str) -> str:
    n = _normalize(nation)
    return _NATION_ALIASES.get(n, n)


# Curated last-resort override for the handful of genuinely ambiguous stars a
# tournament throws up (two same-name, same-nation, same-era players the recency +
# position tiebreak can't separate). Keyed by ``(normalised name, nation key)`` ->
# Transfermarkt player_id. Empty by default — the resolver blanks on ambiguity, so
# entries are added ONLY after eyeballing a real collision; mirrors the project's
# existing ``_ESPN_NAME_MAP`` pattern. A wrong override is worse than a blank, so
# keep it tiny and verified.
_OVERRIDE: dict[tuple[str, str], int] = {}


# ESPN position abbreviation -> coarse bucket (GK/DEF/MID/FWD). ESPN is granular
# (CD-L, DM, CF-R, ...), so we key on the leading letters.
def _espn_pos_bucket(abbr) -> str | None:
    """Coarse GK/DEF/MID/FWD bucket for an ESPN position abbreviation
    (G, CD-L, DM, CF-R, RB, …). Order matters: midfield (DM/CM/RM/LM/AM) is
    matched before the generic "D…"/"…" defender prefixes so a defensive
    MIDfielder ("DM") doesn't fall into DEF."""
    if not abbr:
        return None
    a = str(abbr).upper().strip()
    if a.startswith("G"):                                   # G / GK
        return "GK"
    if a.startswith(("DM", "CM", "RM", "LM", "AM", "CDM", "CAM")) or a in {"M", "MID", "MF"}:
        return "MID"
    if a.startswith(("CF", "ST", "SS", "RW", "LW", "RF", "LF")) or a == "F" or a.startswith("FW"):
        return "FWD"
    if a.startswith(("CD", "CB", "RB", "LB", "WB", "RWB", "LWB", "SW")) or a == "D" or a.startswith("DF"):
        return "DEF"
    return None


def _tm_pos_bucket(position) -> str | None:
    """Transfermarkt coarse ``position`` (Goalkeeper/Defender/Midfield/Attack)
    -> the same GK/DEF/MID/FWD bucket."""
    if not position:
        return None
    p = str(position).lower()
    if "goalkeeper" in p:
        return "GK"
    if "defend" in p:
        return "DEF"
    if "midfield" in p:
        return "MID"
    if "attack" in p or "forward" in p or "striker" in p:
        return "FWD"
    return None


# ---------------------------------------------------------------------------
# Cache build (heavy; run once, offline, where the raw files exist)
# ---------------------------------------------------------------------------

def build_player_rates(out_path: Path | None = None) -> int:
    """Aggregate the raw Transfermarkt files into the compact per-player cache.
    Returns the number of players written. Reads only local raw files; safe to
    re-run (overwrites the cache). Heavy — NOT called at request time."""
    import numpy as np
    import pandas as pd

    out_path = out_path or CACHE_PATH
    if not TM_DIR.exists():
        raise FileNotFoundError(f"Transfermarkt raw datasets not found at {TM_DIR}")

    # --- players: identity + metadata, kept to recently-active players ---
    players = pd.read_csv(
        TM_DIR / "players.csv.gz",
        usecols=["player_id", "name", "position", "sub_position",
                 "country_of_citizenship", "last_season", "international_goals",
                 "international_caps", "market_value_in_eur"],
    )
    players["last_season"] = pd.to_numeric(players["last_season"], errors="coerce")
    players = players[players["last_season"] >= ACTIVE_SINCE].copy()

    # --- appearances: recent window only (ISO dates sort lexicographically) ---
    apps = pd.read_csv(
        TM_DIR / "appearances.csv.gz",
        usecols=["player_id", "date", "goals", "yellow_cards", "red_cards",
                 "minutes_played"],
        dtype={"date": "string"},
    )
    max_date = apps["date"].max()
    cutoff = f"{int(max_date[:4]) - RECENT_YEARS}{max_date[4:]}"
    recent = apps[apps["date"] >= cutoff]
    agg = recent.groupby("player_id").agg(
        minutes_recent=("minutes_played", "sum"),
        goals_recent=("goals", "sum"),
        yellows_recent=("yellow_cards", "sum"),
    )
    mins90 = agg["minutes_recent"] / 90.0
    enough = agg["minutes_recent"] >= MIN_MINUTES
    agg["goals_per_90"] = np.where(enough, agg["goals_recent"] / mins90, np.nan)
    agg["yellows_per_90"] = np.where(enough, agg["yellows_recent"] / mins90, np.nan)

    # --- penalties: a designated-taker signal from goal events in the window ---
    events = pd.read_csv(
        TM_DIR / "game_events.csv.gz",
        usecols=["date", "type", "player_id", "description"],
        dtype={"date": "string", "description": "string"},
    )
    pens = events[(events["type"] == "Goals")
                  & events["description"].fillna("").str.contains("Penalty", case=False)
                  & (events["date"] >= cutoff)]
    pen_counts = pens.groupby("player_id").size().rename("pen_goals")

    # --- merge + derive ---
    df = (players
          .merge(agg[["minutes_recent", "goals_per_90", "yellows_per_90"]],
                 left_on="player_id", right_index=True, how="left")
          .merge(pen_counts, left_on="player_id", right_index=True, how="left"))
    df["pen_goals"] = df["pen_goals"].fillna(0).astype(int)
    df["is_pen_taker"] = df["pen_goals"] >= PEN_THRESHOLD
    df["minutes_recent"] = df["minutes_recent"].fillna(0).astype(int)
    df["norm_name"] = df["name"].map(_normalize)
    df["norm_country"] = df["country_of_citizenship"].map(_normalize)
    df["pos_bucket"] = df["position"].map(_tm_pos_bucket)
    df = df.rename(columns={"country_of_citizenship": "country",
                            "market_value_in_eur": "market_value_eur",
                            "international_goals": "intl_goals",
                            "international_caps": "intl_caps"})

    out = df[_CACHE_COLS]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, compression="gzip")
    logger.info("Built player-rate cache: %d players -> %s", len(out), out_path)
    return len(out)


# ---------------------------------------------------------------------------
# Runtime cache + indices (lazy, loaded once per process)
# ---------------------------------------------------------------------------

_CACHE = None          # list[dict] of player rows
_BY_NAME_NATION = None  # (norm_name, norm_country) -> list[dict]
_BY_NAME = None         # norm_name -> list[dict]


def _ensure_loaded() -> None:
    global _CACHE, _BY_NAME_NATION, _BY_NAME
    if _CACHE is not None:
        return
    import pandas as pd

    if not CACHE_PATH.exists():
        if TM_DIR.exists():
            build_player_rates()
        else:
            logger.warning("No player-rate cache and no raw files; rates unavailable.")
            _CACHE, _BY_NAME_NATION, _BY_NAME = [], {}, {}
            return

    df = pd.read_csv(CACHE_PATH, compression="infer")
    _CACHE = df.to_dict("records")
    _BY_NAME_NATION, _BY_NAME = {}, {}
    for row in _CACHE:
        nn = (row.get("norm_name") or "", row.get("norm_country") or "")
        _BY_NAME_NATION.setdefault(nn, []).append(row)
        _BY_NAME.setdefault(nn[0], []).append(row)


def reset_cache() -> None:
    """Drop the in-process cache (tests inject a fixture cache, then reset)."""
    global _CACHE, _BY_NAME_NATION, _BY_NAME
    _CACHE = _BY_NAME_NATION = _BY_NAME = None


def _pick(cands: list[dict], position: str | None) -> int | None:
    """Tiebreak a candidate list to a single player_id, or None if still
    ambiguous. Conservative: a wrong match is worse than a blank."""
    if not cands:
        return None
    if len(cands) == 1:
        return int(cands[0]["player_id"])
    # Prefer the most recently active player (resolves the "active vs retired
    # same-name" trap, e.g. the current Rodri over a 2013-retired namesake).
    top = max(c.get("last_season") or 0 for c in cands)
    live = [c for c in cands if (c.get("last_season") or 0) == top]
    if len(live) == 1:
        return int(live[0]["player_id"])
    # Still tied: try the position bucket from the confirmed lineup.
    if position:
        bucket = _espn_pos_bucket(position)
        by_pos = [c for c in live if c.get("pos_bucket") == bucket]
        if len(by_pos) == 1:
            return int(by_pos[0]["player_id"])
    return None  # genuinely ambiguous -> blank, never guess


def resolve_player(name: str, nation: str, position: str | None = None) -> int | None:
    """Map a confirmed-XI player to a Transfermarkt ``player_id``, or ``None``
    when it can't be done unambiguously. Strategy (validated in the WC-11A spike):
    a curated override first, then name+nation (the WC nation is a strong free
    disambiguator), tiebreak on recency + position, fall back to a unique name-only
    match, else blank — we never guess.

    Note: ``WCLineup.espn_athlete_id`` is captured as a stable key, but the resolve
    is name-based — Transfermarkt carries no ESPN ids, so there is no id bridge to
    match on (a future ESPN-id→player_id map could feed ``_OVERRIDE``)."""
    _ensure_loaded()
    nname = _normalize(name)
    if not nname:
        return None
    nnat = _nation_key(nation)
    if (nname, nnat) in _OVERRIDE:          # curated last-resort wins outright
        return _OVERRIDE[(nname, nnat)]
    pid = _pick(_BY_NAME_NATION.get((nname, nnat), []), position)
    if pid is not None:
        return pid
    # Nation mismatch (spelling / dual nationality): fall back to name-only, but
    # only accept it when it's unambiguous on its own.
    return _pick(_BY_NAME.get(nname, []), position)


def _row_for(player_id: int) -> dict | None:
    _ensure_loaded()
    for row in _CACHE:
        if int(row["player_id"]) == int(player_id):
            return row
    return None


def player_rate(name: str, nation: str, position: str | None = None) -> dict | None:
    """The display profile for a confirmed-XI player, or ``None`` when the name
    can't be resolved unambiguously (caller shows a blank, never a guess).

    ``goals_per_90`` prefers recent CLUB form; when a player has no tracked recent
    club minutes (Saudi/MLS), it falls back to an international goals-per-cap rate
    with ``source='international'`` so the UI can label it honestly. ``source`` is
    ``'club'`` / ``'international'`` / ``'none'``."""
    pid = resolve_player(name, nation, position=position)
    if pid is None:
        return None
    row = _row_for(pid)
    if row is None:
        return None

    gp90 = row.get("goals_per_90")
    has_club = gp90 is not None and not (isinstance(gp90, float) and math.isnan(gp90))
    source = "club" if has_club else "none"
    if not has_club:
        caps = row.get("intl_caps") or 0
        goals = row.get("intl_goals") or 0
        if caps and caps > 0:
            gp90 = float(goals) / float(caps)   # goals per international appearance
            source = "international"
        else:
            gp90 = None

    def _num(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return v

    def _str(v):
        # CSV blanks read back as NaN floats; never leak "nan" into a player card.
        return v if isinstance(v, str) and v.strip() else None

    return {
        "player_id": int(pid),
        "name": _str(row.get("name")),
        "goals_per_90": _num(gp90),
        "minutes_recent": int(row.get("minutes_recent") or 0),
        "yellows_per_90": _num(row.get("yellows_per_90")),
        "is_pen_taker": bool(row.get("is_pen_taker")),
        "pen_goals": int(row.get("pen_goals") or 0),
        "position": _str(row.get("position")),
        "sub_position": _str(row.get("sub_position")),
        "pos_bucket": _str(row.get("pos_bucket")),
        "market_value_eur": _num(row.get("market_value_eur")),
        "intl_goals": int(row.get("intl_goals") or 0) if _num(row.get("intl_goals")) is not None else 0,
        "intl_caps": int(row.get("intl_caps") or 0) if _num(row.get("intl_caps")) is not None else 0,
        "source": source,
    }


def cache_status() -> dict:
    """Lightweight health read for diagnostics / the dashboard footer."""
    _ensure_loaded()
    return {"players": len(_CACHE or []), "cache_path": str(CACHE_PATH),
            "exists": CACHE_PATH.exists()}
