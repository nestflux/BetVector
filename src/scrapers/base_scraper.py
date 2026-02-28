"""
BetVector Base Scraper — Abstract Interface & Shared Utilities (E3-01)
======================================================================
Abstract base class that all BetVector scrapers inherit from.  Provides:

  - **Rate limiting:** Enforces a configurable minimum delay between HTTP
    requests to the same domain (default 2 seconds from config).  This is
    critical — Football-Data.co.uk and FBref are free public resources and
    must not be hammered.

  - **Retry logic:** Automatic retries with exponential backoff for
    transient HTTP errors (429 Too Many Requests, 500 Internal Server Error,
    503 Service Unavailable).  Configured via ``config/settings.yaml``.

  - **Raw file saving:** Every scraper saves the raw downloaded data to
    ``data/raw/`` before any processing.  This guarantees reproducibility —
    if a parsing bug is found later, the original data is still on disk.

  - **Logging:** Structured logging at INFO (progress), WARNING (retries),
    and ERROR (failures) levels.

Subclasses must implement:
  - ``scrape(league_config, season)`` → ``pd.DataFrame``
  - ``source_name`` property → ``str``  (e.g. "football_data", "fbref")

Usage::

    from src.scrapers.football_data import FootballDataScraper

    scraper = FootballDataScraper()
    df = scraper.scrape(league_config, "2024-25")

Master Plan refs: MP §5 Architecture → Data Sources, MP §7 Scraper Interface
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import requests
from requests.exceptions import ConnectionError, HTTPError, Timeout

from src.config import PROJECT_ROOT, config

logger = logging.getLogger(__name__)


# ============================================================================
# Rate Limiter
# ============================================================================
# Tracks the timestamp of the last request to each domain and enforces a
# minimum gap between consecutive requests.  This prevents us from abusing
# free data sources and getting IP-banned.

class RateLimiter:
    """Per-domain rate limiter using time.sleep().

    The minimum interval between requests is read from
    ``config/settings.yaml → scraping.min_request_interval_seconds``
    (default 2 seconds).

    Usage::

        limiter = RateLimiter()
        limiter.wait("www.football-data.co.uk")  # blocks if needed
        # ... make request ...
        limiter.wait("www.football-data.co.uk")  # waits ≥2s since last call
    """

    def __init__(self, min_interval: Optional[float] = None) -> None:
        # Read from config if not explicitly overridden (tests can override)
        if min_interval is not None:
            self._min_interval = min_interval
        else:
            self._min_interval = float(
                config.settings.scraping.min_request_interval_seconds
            )
        # Map of domain → timestamp of last request
        self._last_request: Dict[str, float] = {}

    @property
    def min_interval(self) -> float:
        """Minimum seconds between requests to the same domain."""
        return self._min_interval

    def wait(self, domain: str) -> None:
        """Block until enough time has passed since the last request to *domain*.

        If this is the first request to a domain, returns immediately.
        Otherwise, sleeps for the remaining portion of the minimum interval.
        """
        now = time.monotonic()
        last = self._last_request.get(domain)

        if last is not None:
            elapsed = now - last
            remaining = self._min_interval - elapsed
            if remaining > 0:
                logger.info(
                    "Rate limiter: waiting %.2fs before next request to %s",
                    remaining, domain,
                )
                time.sleep(remaining)

        # Record the actual request time (after any sleep)
        self._last_request[domain] = time.monotonic()


# ============================================================================
# Base Scraper
# ============================================================================

class BaseScraper(ABC):
    """Abstract base class for all BetVector data scrapers.

    Provides shared infrastructure:
      - ``self.rate_limiter`` — per-domain rate limiting
      - ``self._request_with_retry()`` — HTTP GET with exponential backoff
      - ``self.save_raw()`` — persist raw data to ``data/raw/``

    Subclasses must implement:
      - ``scrape(league_config, season)`` → cleaned ``pd.DataFrame``
      - ``source_name`` → short identifier for this data source
    """

    # Retryable HTTP status codes — transient errors that may resolve
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self) -> None:
        self.rate_limiter = RateLimiter()
        self._max_retries: int = int(config.settings.scraping.max_retries)
        self._timeout: int = int(
            config.settings.scraping.request_timeout_seconds
        )

    # --- abstract interface ---------------------------------------------------

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Short identifier for this data source.

        Used in raw file names and log messages.
        Examples: ``"football_data"``, ``"fbref"``, ``"api_football"``
        """

    @abstractmethod
    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Download and parse data for one league-season.

        Parameters
        ----------
        league_config : ConfigNamespace
            League configuration object from ``config.get_active_leagues()``.
            Contains ``short_name``, ``football_data_code``, ``seasons``, etc.
        season : str
            Season identifier, e.g. ``"2024-25"``.

        Returns
        -------
        pd.DataFrame
            Clean, normalised DataFrame ready for loading into the database.

        Raises
        ------
        ScraperError
            If the data cannot be retrieved after all retries.
        """

    # --- HTTP with retry ------------------------------------------------------

    def _request_with_retry(
        self,
        url: str,
        domain: str,
        **kwargs,
    ) -> requests.Response:
        """Perform an HTTP GET with rate limiting and exponential backoff.

        Parameters
        ----------
        url : str
            The URL to fetch.
        domain : str
            Domain name for rate limiting (e.g. ``"www.football-data.co.uk"``).
        **kwargs
            Additional keyword arguments passed to ``requests.get()``.

        Returns
        -------
        requests.Response
            The successful HTTP response.

        Raises
        ------
        ScraperError
            If all retries are exhausted.
        """
        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            # Respect rate limit before every attempt
            self.rate_limiter.wait(domain)

            try:
                logger.info(
                    "[%s] GET %s (attempt %d/%d)",
                    self.source_name, url, attempt + 1, self._max_retries + 1,
                )
                response = requests.get(url, timeout=self._timeout, **kwargs)

                # Check for retryable HTTP status codes
                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    wait_time = self._backoff_delay(attempt)
                    logger.warning(
                        "[%s] HTTP %d from %s — retrying in %.1fs "
                        "(attempt %d/%d)",
                        self.source_name, response.status_code, url,
                        wait_time, attempt + 1, self._max_retries + 1,
                    )
                    if attempt < self._max_retries:
                        time.sleep(wait_time)
                        continue
                    # Last attempt — raise
                    response.raise_for_status()

                # Non-retryable error — fail immediately
                response.raise_for_status()
                return response

            except (ConnectionError, Timeout) as exc:
                last_error = exc
                if attempt < self._max_retries:
                    wait_time = self._backoff_delay(attempt)
                    logger.warning(
                        "[%s] %s fetching %s — retrying in %.1fs "
                        "(attempt %d/%d)",
                        self.source_name, type(exc).__name__, url,
                        wait_time, attempt + 1, self._max_retries + 1,
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        "[%s] Failed to fetch %s after %d attempts: %s",
                        self.source_name, url, self._max_retries + 1, exc,
                    )

            except HTTPError as exc:
                # Non-retryable HTTP error (4xx other than 429)
                logger.error(
                    "[%s] HTTP error fetching %s: %s",
                    self.source_name, url, exc,
                )
                raise ScraperError(
                    f"HTTP error fetching {url}: {exc}"
                ) from exc

        raise ScraperError(
            f"Failed to fetch {url} after {self._max_retries + 1} attempts: "
            f"{last_error}"
        )

    @staticmethod
    def _backoff_delay(attempt: int) -> float:
        """Calculate exponential backoff delay for a retry attempt.

        Attempt 0 → 2s, attempt 1 → 4s, attempt 2 → 8s, etc.
        """
        return 2.0 ** (attempt + 1)

    # --- raw file saving ------------------------------------------------------

    def save_raw(
        self,
        data: pd.DataFrame,
        league_short_name: str,
        season: str,
    ) -> Path:
        """Save raw scraped data to ``data/raw/`` for reproducibility.

        File naming convention:
            ``{source_name}_{league}_{season}_{YYYY-MM-DD}.csv``

        Parameters
        ----------
        data : pd.DataFrame
            The raw data to save.
        league_short_name : str
            League short name, e.g. ``"EPL"``.
        season : str
            Season identifier, e.g. ``"2024-25"``.

        Returns
        -------
        Path
            Absolute path to the saved CSV file.
        """
        raw_dir = PROJECT_ROOT / "data" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        today = date.today().isoformat()  # YYYY-MM-DD
        filename = f"{self.source_name}_{league_short_name}_{season}_{today}.csv"
        filepath = raw_dir / filename

        data.to_csv(filepath, index=False)
        logger.info(
            "[%s] Saved raw data → %s (%d rows)",
            self.source_name, filepath, len(data),
        )
        return filepath


# ============================================================================
# Custom exception
# ============================================================================

class ScraperError(Exception):
    """Raised when a scraper cannot complete its work.

    This is a non-fatal error at the pipeline level — the pipeline
    orchestrator catches it, logs it, and continues to the next step.
    A single scraper failure should never prevent the rest of the
    pipeline from running.
    """
