"""
BetVector — Weather Scraper (Real-Time Data Sources)
=====================================================
Fetches match-day weather conditions from the Open-Meteo API.  Weather can
significantly affect match outcomes:

  - **Heavy rain:** Reduces passing accuracy and goal-scoring rates
  - **Strong wind (>30 km/h):** Makes long balls unpredictable, favours
    direct-play teams over possession-based ones
  - **Extreme temperatures:** Affects player stamina and intensity
  - **Snow/frost:** Rare in EPL but can change match dynamics entirely

Data source: Open-Meteo (https://open-meteo.com)
  - **Free tier:** No API key needed, no rate limits (be respectful)
  - **Forecast:** Up to 16 days ahead (for upcoming matches)
  - **Historical:** Back to 1940 (for past matches / backfilling)
  - **Resolution:** Hourly data at 1km grid

Stadium coordinates are stored in ``config/stadiums.yaml`` and used to
look up the weather at each ground for the match kickoff window.

WMO Weather Codes (international standard):
  0     = Clear sky
  1-3   = Partly cloudy / overcast
  45-48 = Fog
  51-55 = Drizzle
  56-57 = Freezing drizzle
  61-65 = Rain
  66-67 = Freezing rain
  71-77 = Snow / ice pellets
  80-82 = Rain showers
  85-86 = Snow showers
  95-99 = Thunderstorm

Master Plan refs: MP §5 Data Sources
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

from src.config import PROJECT_ROOT, config
from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DOMAIN = "api.open-meteo.com"
ARCHIVE_DOMAIN = "archive-api.open-meteo.com"

# WMO weather code → simplified category for feature engineering
# These categories are what the model actually uses as features
WMO_CATEGORY_MAP: Dict[int, str] = {
    0: "clear",
    1: "clear",        # Mainly clear
    2: "cloudy",       # Partly cloudy
    3: "cloudy",       # Overcast
    45: "fog",
    48: "fog",
    51: "drizzle",
    53: "drizzle",
    55: "drizzle",
    56: "drizzle",     # Freezing drizzle
    57: "drizzle",
    61: "rain",
    63: "rain",
    65: "heavy_rain",
    66: "rain",        # Freezing rain
    67: "heavy_rain",
    71: "snow",
    73: "snow",
    75: "snow",
    77: "snow",        # Ice pellets
    80: "rain",        # Slight rain showers
    81: "rain",        # Moderate rain showers
    82: "heavy_rain",  # Violent rain showers
    85: "snow",
    86: "snow",
    95: "storm",       # Thunderstorm
    96: "storm",       # Thunderstorm with hail
    99: "storm",       # Thunderstorm with heavy hail
}

# Default kickoff hour (UTC) — EPL matches typically start at 15:00 UTC
# on Saturdays, with earlier/later slots on other days.  We use 15:00 as
# default if the exact kickoff time is unknown.
DEFAULT_KICKOFF_HOUR = 15


# ============================================================================
# Weather Scraper
# ============================================================================

class WeatherScraper(BaseScraper):
    """Weather data scraper using the Open-Meteo API.

    Fetches hourly weather data for each match location (using stadium
    coordinates from ``config/stadiums.yaml``) at the match kickoff time.

    No API key needed — Open-Meteo is free for non-commercial use.
    """

    def __init__(self) -> None:
        super().__init__()
        self._stadium_coords: Dict[str, Dict[str, float]] = {}
        self._load_stadium_coords()
        # URLs from config
        try:
            self._forecast_url = str(getattr(
                config.settings.scraping.weather, "forecast_url",
                "https://api.open-meteo.com/v1/forecast",
            ))
            self._archive_url = str(getattr(
                config.settings.scraping.weather, "archive_url",
                "https://archive-api.open-meteo.com/v1/archive",
            ))
        except (AttributeError, TypeError):
            self._forecast_url = "https://api.open-meteo.com/v1/forecast"
            self._archive_url = "https://archive-api.open-meteo.com/v1/archive"

    @property
    def source_name(self) -> str:
        return "weather"

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Not used directly — use ``scrape_for_matches()`` instead.

        The weather scraper differs from other scrapers because it needs
        specific match dates and teams (to look up stadium coordinates).
        The pipeline calls ``scrape_for_matches()`` with a list of matches.
        """
        logger.info(
            "[weather] scrape() called — use scrape_for_matches() for "
            "targeted weather fetching"
        )
        return pd.DataFrame()

    def scrape_for_matches(
        self,
        match_list: List[Dict[str, Any]],
        league_short_name: str = "EPL",
    ) -> pd.DataFrame:
        """Fetch weather for a list of matches.

        Parameters
        ----------
        match_list : list of dict
            Each dict must have: ``match_id``, ``date`` (YYYY-MM-DD),
            ``home_team`` (canonical name), and optionally ``kickoff_hour`` (int, UTC).
        league_short_name : str
            League identifier for looking up stadium coords.

        Returns
        -------
        pd.DataFrame
            Weather data with columns: ``match_id``, ``temperature_c``,
            ``wind_speed_kmh``, ``humidity_pct``, ``precipitation_mm``,
            ``weather_code``, ``weather_category``.
        """
        if not match_list:
            return pd.DataFrame()

        if not self._stadium_coords:
            logger.warning(
                "[weather] No stadium coordinates loaded — check config/stadiums.yaml"
            )
            return pd.DataFrame()

        league_stadiums = self._stadium_coords.get(league_short_name, {})
        if not league_stadiums:
            logger.warning(
                "[weather] No stadium data for league %s", league_short_name,
            )
            return pd.DataFrame()

        rows: List[Dict[str, Any]] = []
        today = date.today()

        for match in match_list:
            match_id = match.get("match_id")
            match_date_str = match.get("date", "")
            home_team = match.get("home_team", "")
            kickoff_hour = match.get("kickoff_hour", DEFAULT_KICKOFF_HOUR)

            if not match_id or not match_date_str or not home_team:
                continue

            # Look up stadium coordinates for the home team
            coords = league_stadiums.get(home_team)
            if coords is None:
                logger.debug(
                    "[weather] No stadium coords for %s — skipping match %s",
                    home_team, match_id,
                )
                continue

            lat = coords.get("lat")
            lon = coords.get("lon")
            if lat is None or lon is None:
                continue

            # Determine if we need forecast or historical API
            try:
                match_date = datetime.strptime(match_date_str, "%Y-%m-%d").date()
            except ValueError:
                logger.warning(
                    "[weather] Could not parse date '%s' for match %s",
                    match_date_str, match_id,
                )
                continue

            # Fetch weather
            weather = self._fetch_weather_for_location(
                lat=lat,
                lon=lon,
                match_date=match_date,
                kickoff_hour=kickoff_hour,
                is_historical=(match_date < today),
            )

            if weather:
                weather["match_id"] = match_id
                rows.append(weather)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        logger.info(
            "[weather] Fetched weather for %d/%d matches",
            len(df), len(match_list),
        )

        return df

    # -----------------------------------------------------------------------
    # Weather fetching
    # -----------------------------------------------------------------------

    def _fetch_weather_for_location(
        self,
        lat: float,
        lon: float,
        match_date: date,
        kickoff_hour: int = DEFAULT_KICKOFF_HOUR,
        is_historical: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Fetch weather for a specific location and date.

        Uses the forecast API for future matches and the historical API
        for past matches.  Extracts the hourly reading closest to kickoff.

        Returns
        -------
        dict or None
            Weather data dict, or None on failure.
        """
        date_str = match_date.isoformat()

        # Choose the right API based on whether the match is past or future
        if is_historical:
            base_url = self._archive_url
            domain = ARCHIVE_DOMAIN
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": date_str,
                "end_date": date_str,
                "hourly": "temperature_2m,wind_speed_10m,relative_humidity_2m,precipitation,weather_code",
            }
        else:
            base_url = self._forecast_url
            domain = DOMAIN
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": date_str,
                "end_date": date_str,
                "hourly": "temperature_2m,wind_speed_10m,relative_humidity_2m,precipitation,weather_code",
            }

        try:
            self.rate_limiter.wait(domain)
            response = self._request_with_retry(base_url, domain, params=params)
            data = response.json()

            # Parse hourly data at kickoff time
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            winds = hourly.get("wind_speed_10m", [])
            humidities = hourly.get("relative_humidity_2m", [])
            precips = hourly.get("precipitation", [])
            weather_codes = hourly.get("weather_code", [])

            if not times:
                return None

            # Find the index closest to kickoff hour
            target_hour = f"{date_str}T{kickoff_hour:02d}:00"
            idx = self._find_closest_hour(times, target_hour)

            if idx is None or idx >= len(temps):
                return None

            # Extract weather at kickoff
            weather_code = int(weather_codes[idx]) if idx < len(weather_codes) else None
            weather_category = WMO_CATEGORY_MAP.get(weather_code, "unknown")

            return {
                "temperature_c": self._safe_val(temps, idx),
                "wind_speed_kmh": self._safe_val(winds, idx),
                "humidity_pct": self._safe_val(humidities, idx),
                "precipitation_mm": self._safe_val(precips, idx),
                "weather_code": weather_code,
                "weather_category": weather_category,
            }

        except ScraperError as e:
            logger.warning("[weather] Failed to fetch weather: %s", e)
            return None
        except Exception as e:
            logger.warning("[weather] Error fetching weather for %s: %s", date_str, e)
            return None

    # -----------------------------------------------------------------------
    # Stadium coordinates
    # -----------------------------------------------------------------------

    def _load_stadium_coords(self) -> None:
        """Load stadium coordinates from ``config/stadiums.yaml``."""
        stadiums_path = PROJECT_ROOT / "config" / "stadiums.yaml"

        if not stadiums_path.exists():
            logger.warning(
                "[weather] config/stadiums.yaml not found — weather scraper disabled"
            )
            return

        try:
            with open(stadiums_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            stadiums = data.get("stadiums", {})
            self._stadium_coords = stadiums

            total = sum(len(v) for v in stadiums.values())
            logger.info(
                "[weather] Loaded %d stadium coordinates from %d leagues",
                total, len(stadiums),
            )

        except Exception as e:
            logger.error("[weather] Failed to load stadiums.yaml: %s", e)

    # -----------------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------------

    @staticmethod
    def _find_closest_hour(
        times: List[str], target: str,
    ) -> Optional[int]:
        """Find the index of the hour closest to the target time.

        Times are in ISO format like ``"2025-08-16T15:00"``.
        """
        if not times:
            return None

        # Try exact match first
        for i, t in enumerate(times):
            if target in t:
                return i

        # Fallback: find the closest hour
        try:
            target_dt = datetime.fromisoformat(target)
            best_idx = 0
            best_diff = float("inf")
            for i, t in enumerate(times):
                dt = datetime.fromisoformat(t)
                diff = abs((dt - target_dt).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i
            return best_idx
        except (ValueError, TypeError):
            # If all else fails, use midday (index 15 for hourly data starting at midnight)
            return min(15, len(times) - 1)

    @staticmethod
    def _safe_val(arr: List, idx: int):
        """Safely get a value from an array by index."""
        if idx < len(arr) and arr[idx] is not None:
            return float(arr[idx])
        return None
