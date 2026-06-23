"""
BetVector World Cup 2026 — World Bank & Alternative Data (WC-02-04)
====================================================================
Fetch economic, demographic, and governance indicators from the World
Bank API for all 48 WC teams. Stores results in wc_teams and caches
to avoid redundant API calls.

World Bank API (free, no auth):
    https://api.worldbank.org/v2/country/{iso3}/indicators/{code}?format=json

Indicators (from World Bank API):
    NY.GDP.PCAP.CD  — GDP per capita (current US$)
    SP.POP.TOTL     — Population
    SI.POV.GINI     — Gini coefficient (inequality, 0-100)

Political stability (-2.5 to +2.5) sourced from hardcoded WGI 2023
estimates — the PV.EST API endpoint was retired by the World Bank.
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path

import requests
from sqlalchemy import select

from src.database.db import get_session
from src.world_cup.models import WCTeam

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "raw"
CACHE_FILE = DATA_DIR / "wc_world_bank_cache.json"

WB_BASE = "https://api.worldbank.org/v2/country"

INDICATORS = {
    "gdp_per_capita": "NY.GDP.PCAP.CD",
    "population": "SP.POP.TOTL",
    "gini_coefficient": "SI.POV.GINI",
}

# FIFA code → ISO 3166-1 alpha-3 (World Bank uses ISO3)
FIFA_TO_ISO3 = {
    "ALG": "DZA",
    "ARG": "ARG",
    "AUS": "AUS",
    "AUT": "AUT",
    "BEL": "BEL",
    "BIH": "BIH",
    "BRA": "BRA",
    "CAN": "CAN",
    "CPV": "CPV",
    "COL": "COL",
    "CRO": "HRV",
    "CUW": "CUW",
    "CZE": "CZE",
    "COD": "COD",
    "ECU": "ECU",
    "EGY": "EGY",
    "ENG": "GBR",  # England and Scotland share UK data (no sub-national WB stats)
    "FRA": "FRA",
    "GER": "DEU",
    "GHA": "GHA",
    "HAI": "HTI",
    "IRN": "IRN",
    "IRQ": "IRQ",
    "CIV": "CIV",
    "JPN": "JPN",
    "JOR": "JOR",
    "MEX": "MEX",
    "MAR": "MAR",
    "NED": "NLD",
    "NZL": "NZL",
    "NOR": "NOR",
    "PAN": "PAN",
    "PAR": "PRY",
    "POR": "PRT",
    "QAT": "QAT",
    "KSA": "SAU",
    "SCO": "GBR",
    "SEN": "SEN",
    "RSA": "ZAF",
    "KOR": "KOR",
    "ESP": "ESP",
    "SWE": "SWE",
    "SUI": "CHE",
    "TUN": "TUN",
    "TUR": "TUR",
    "USA": "USA",
    "URU": "URY",
    "UZB": "UZB",
}

# Regional Gini averages — fallback when World Bank has no country-level data.
# Source: World Bank regional aggregates (2020-2023 range).
REGIONAL_GINI = {
    "UEFA": 32.0,
    "CONMEBOL": 45.0,
    "CAF": 40.0,
    "AFC": 35.0,
    "CONCACAF": 42.0,
    "OFC": 36.0,
}

# WGI Political Stability Index (2023 estimates, scale -2.5 to +2.5)
# Source: World Bank Worldwide Governance Indicators (info.worldbank.org/governance/wgi/)
# The WGI API endpoints (PV.EST etc.) were retired from the World Bank v2 API.
# These are static reference data, not tuneable parameters — kept as module constants.
POLITICAL_STABILITY = {
    "DZA": -0.88, "ARG": -0.07, "AUS": 0.86, "AUT": 0.98, "BEL": 0.53,
    "BIH": -0.45, "BRA": -0.38, "CAN": 0.96, "CPV": 0.70, "COL": -0.73,
    "HRV": 0.65, "CUW": 0.60, "CZE": 0.85, "COD": -2.17, "ECU": -0.96,
    "EGY": -0.83, "GBR": 0.41, "FRA": 0.21, "DEU": 0.57, "GHA": -0.01,
    "HTI": -1.97, "IRN": -1.22, "IRQ": -1.86, "CIV": -0.69, "JPN": 1.07,
    "JOR": -0.34, "MEX": -0.81, "MAR": -0.30, "NLD": 0.72, "NZL": 1.30,
    "NOR": 1.15, "PAN": 0.09, "PRY": -0.47, "PRT": 0.88, "QAT": 0.80,
    "SAU": -0.27, "SEN": -0.10, "ZAF": -0.19, "KOR": 0.42, "ESP": 0.39,
    "SWE": 0.92, "CHE": 1.25, "TUN": -0.65, "TUR": -1.15, "USA": 0.14,
    "URY": 0.88, "UZB": -0.58,
}


def _fetch_indicator_batch(
    iso3_codes: list[str], indicator_code: str, retries: int = 2,
) -> dict[str, float | None]:
    """Fetch the latest value for an indicator across multiple countries in one call."""
    countries = ";".join(iso3_codes)
    url = f"{WB_BASE}/{countries}/indicators/{indicator_code}"
    # Broad date range to capture latest available data point for each country
    params = {"format": "json", "per_page": 1000, "date": "2018:2025"}

    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=90)
            resp.raise_for_status()
            data = resp.json()
            if len(data) < 2 or not data[1]:
                return {code: None for code in iso3_codes}

            # Group entries by country, pick most recent non-null
            country_values: dict[str, float | None] = {code: None for code in iso3_codes}
            # Entries come sorted by date descending
            for entry in data[1]:
                iso3 = entry.get("countryiso3code", entry.get("country", {}).get("id", ""))
                if iso3 in country_values and country_values[iso3] is None:
                    if entry.get("value") is not None:
                        country_values[iso3] = float(entry["value"])
            return country_values

        except requests.Timeout:
            if attempt < retries:
                logger.warning("Timeout fetching %s batch, retry %d", indicator_code, attempt + 1)
                time.sleep(3)
                continue
            logger.warning("Timeout fetching %s batch after %d retries", indicator_code, retries)
            return {code: None for code in iso3_codes}
        except (requests.RequestException, ValueError, IndexError, KeyError) as e:
            logger.warning("Failed to fetch %s batch: %s", indicator_code, e)
            return {code: None for code in iso3_codes}


def _load_cache() -> dict | None:
    """Load cached World Bank data if it exists."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Cache file corrupt or unreadable, will re-fetch: %s", e)
        return None


def _save_cache(data: dict) -> None:
    """Save fetched data to cache file."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Cached World Bank data to %s", CACHE_FILE)
    except OSError as e:
        logger.warning("Failed to write cache (non-fatal): %s", e)


def fetch_country_indicators(force_refresh: bool = False) -> dict[str, dict]:
    """
    Fetch World Bank indicators for all 48 WC teams. Returns a dict of
    {fifa_code: {gdp_per_capita, population, gini_coefficient, political_stability}}.

    Results are cached to disk — subsequent calls return cached data
    unless force_refresh=True.
    """
    if not force_refresh:
        cached = _load_cache()
        if cached:
            logger.info("Using cached World Bank data (%d teams)", len(cached))
            _store_indicators(cached)
            return cached

    with get_session() as session:
        teams = session.execute(select(WCTeam)).scalars().all()

    # Build mappings
    fifa_to_iso3 = {}
    iso3_to_fifa = {}
    team_confeds = {}
    for team in teams:
        iso3 = FIFA_TO_ISO3.get(team.fifa_code)
        if not iso3:
            logger.warning("No ISO3 mapping for %s (%s)", team.name, team.fifa_code)
            continue
        fifa_to_iso3[team.fifa_code] = iso3
        iso3_to_fifa[iso3] = team.fifa_code
        team_confeds[team.fifa_code] = team.confederation

    # England and Scotland both map to GBR — deduplicate for API call
    unique_iso3 = list(set(fifa_to_iso3.values()))

    # Batch fetch: 4 API calls instead of 192
    results: dict[str, dict] = {fc: {} for fc in fifa_to_iso3}
    for field, indicator_code in INDICATORS.items():
        logger.info("Fetching %s (%s) for %d countries...", field, indicator_code, len(unique_iso3))
        batch = _fetch_indicator_batch(unique_iso3, indicator_code)
        time.sleep(2)

        for fifa_code, iso3 in fifa_to_iso3.items():
            results[fifa_code][field] = batch.get(iso3)

    # Gini fallback: use regional average if missing
    for fifa_code, team_data in results.items():
        if team_data.get("gini_coefficient") is None:
            confed = team_confeds.get(fifa_code, "UEFA")
            fallback = REGIONAL_GINI.get(confed, 35.0)
            team_data["gini_coefficient"] = fallback
            logger.info(
                "Gini missing for %s — using %s regional average: %.1f",
                fifa_code, confed, fallback,
            )

    # Political stability from hardcoded WGI 2023 (API retired)
    ps_populated = 0
    for fifa_code, iso3 in fifa_to_iso3.items():
        ps_val = POLITICAL_STABILITY.get(iso3)
        results[fifa_code]["political_stability"] = ps_val
        if ps_val is not None:
            ps_populated += 1
    logger.info("Political stability: %d/%d teams populated", ps_populated, len(fifa_to_iso3))

    _save_cache(results)
    _store_indicators(results)

    return results


def _store_indicators(data: dict[str, dict]) -> None:
    """Write fetched indicators into the wc_teams table."""
    try:
        with get_session() as session:
            teams = session.execute(select(WCTeam)).scalars().all()
            team_map = {t.fifa_code: t for t in teams}

            updated = 0
            for fifa_code, indicators in data.items():
                team = team_map.get(fifa_code)
                if not team:
                    continue

                if indicators.get("gdp_per_capita") is not None:
                    team.gdp_per_capita = indicators["gdp_per_capita"]
                if indicators.get("population") is not None:
                    team.population = indicators["population"]
                if indicators.get("gini_coefficient") is not None:
                    team.gini_coefficient = indicators["gini_coefficient"]
                if indicators.get("political_stability") is not None:
                    team.political_stability = indicators["political_stability"]
                updated += 1

            session.commit()
            logger.info("Stored World Bank indicators for %d teams", updated)
    except Exception as e:
        logger.error("Failed to store indicators in DB: %s", e)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# WC 2026 venue coordinates (USA, Canada, Mexico)
WC_VENUES = {
    "MetLife Stadium": (40.8128, -74.0742, "East Rutherford", 24.0),
    "AT&T Stadium": (32.7480, -97.0929, "Arlington", 33.0),
    "Hard Rock Stadium": (25.9580, -80.2389, "Miami", 28.0),
    "SoFi Stadium": (33.9535, -118.3390, "Inglewood", 21.0),
    "Lumen Field": (47.5952, -122.3316, "Seattle", 17.0),
    "Lincoln Financial Field": (39.9012, -75.1676, "Philadelphia", 25.0),
    "Arrowhead Stadium": (39.0489, -94.4839, "Kansas City", 27.0),
    "NRG Stadium": (29.6847, -95.4107, "Houston", 31.0),
    "Mercedes-Benz Stadium": (33.7554, -84.4010, "Atlanta", 26.0),
    "Gillette Stadium": (42.0909, -71.2643, "Foxborough", 21.0),
    "BMO Field": (43.6332, -79.4186, "Toronto", 20.0),
    "BC Place": (49.2768, -123.1118, "Vancouver", 16.0),
    "Estadio Azteca": (19.3029, -99.1505, "Mexico City", 16.0),
    "Estadio Akron": (20.6829, -103.4624, "Guadalajara", 22.0),
    "Estadio BBVA": (25.6055, -100.2867, "Monterrey", 29.0),
}


def compute_derived_features() -> dict[str, dict]:
    """
    Compute climate_gap and travel_distance for each team based on
    capital coordinates and WC venue locations. Returns a dict for
    use in feature engineering (WC-03). These are per-team baselines
    that get written to WCFeature per-match later.

    climate_gap = |home_june_temp - avg_venue_june_temp|
    travel_distance_km = avg haversine(capital, venue) across all venues
    """
    venue_list = list(WC_VENUES.values())
    avg_venue_temp = sum(v[3] for v in venue_list) / len(venue_list)

    results: dict[str, dict] = {}

    with get_session() as session:
        teams = session.execute(select(WCTeam)).scalars().all()
        for team in teams:
            team_data: dict[str, float | None] = {}

            if team.home_avg_june_temp_c is not None:
                team_data["climate_gap"] = round(
                    abs(team.home_avg_june_temp_c - avg_venue_temp), 1
                )
            else:
                team_data["climate_gap"] = None

            if team.home_capital_lat is not None and team.home_capital_lon is not None:
                distances = [
                    haversine_km(team.home_capital_lat, team.home_capital_lon, v[0], v[1])
                    for v in venue_list
                ]
                team_data["travel_distance_km"] = round(sum(distances) / len(distances), 1)
            else:
                team_data["travel_distance_km"] = None

            results[team.fifa_code] = team_data

    logger.info("Computed derived features for %d teams", len(results))
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from src.database.db import init_db

    init_db()

    print("=== Fetching World Bank Indicators ===")
    data = fetch_country_indicators()

    print(f"\nFetched data for {len(data)} teams")
    all_fields = list(INDICATORS.keys()) + ["political_stability"]
    nulls = {field: 0 for field in all_fields}
    for fifa_code, indicators in data.items():
        for field in all_fields:
            if indicators.get(field) is None:
                nulls[field] += 1

    for field, count in nulls.items():
        total = len(data)
        print(f"  {field}: {total - count}/{total} populated ({count} NULL)")

    print("\n=== Computing Derived Features ===")
    derived = compute_derived_features()
    for code, feats in sorted(derived.items()):
        print(f"  {code}: climate_gap={feats['climate_gap']}, travel={feats['travel_distance_km']} km")

    print("\n=== Final Team Data ===")
    with get_session() as session:
        teams = session.execute(
            select(WCTeam).order_by(WCTeam.name)
        ).scalars().all()
        for t in teams:
            gdp_str = f"{t.gdp_per_capita:>10.0f}" if t.gdp_per_capita else "      NULL"
            pop_str = f"{t.population:>12.0f}" if t.population else "        NULL"
            gini_str = f"{t.gini_coefficient:>5.1f}" if t.gini_coefficient else " NULL"
            stab_str = f"{t.political_stability:>6.2f}" if t.political_stability else "  NULL"
            print(f"  {t.name:<25s} GDP={gdp_str} Pop={pop_str} Gini={gini_str} Stab={stab_str}")
