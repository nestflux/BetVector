"""
BetVector Database Connection Manager
======================================
Central database module providing engine creation, session management, and
schema initialisation.  Every other module that touches the database imports
from here — never constructs its own engine or session.

Architecture notes (MP §5):
- Dual-database support: SQLite for local dev, PostgreSQL for cloud.
- Connection resolved via: DATABASE_URL env var → Streamlit secrets → config file.
- WAL mode enabled for SQLite only (PostgreSQL handles concurrency natively).
- Every function that touches the database handles connection errors and
  retries once (CLAUDE.md Rule 6).

Usage::

    from src.database.db import get_session, init_db, Base

    # First-time setup — creates the DB file and all tables
    init_db()

    # Normal usage — get a session, do work, session auto-closes
    with get_session() as session:
        result = session.execute(text("SELECT 1")).scalar()
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import config, PROJECT_ROOT

logger = logging.getLogger(__name__)

# ============================================================================
# Declarative Base
# ============================================================================
# All ORM models (defined in E2-02, E2-03, E2-04) inherit from this Base.
# init_db() calls Base.metadata.create_all() to build the schema.


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base for all BetVector ORM models."""
    pass


# ============================================================================
# Module-level singletons (lazily initialised)
# ============================================================================

_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


# ============================================================================
# Engine creation
# ============================================================================

def _build_connection_url() -> str:
    """Construct a SQLAlchemy connection URL.

    Resolution order (highest priority first):
      1. ``DATABASE_URL`` environment variable — primary mechanism for cloud
         deployment (GitHub Actions pipelines + Neon PostgreSQL).
      2. Streamlit Cloud secrets (``st.secrets["database"]["connection_string"]``)
         — used when deployed to Streamlit Community Cloud.
      3. Config file (``config/settings.yaml`` → ``database.path``)
         — default for local development with SQLite.

    For SQLite this produces ``sqlite:///absolute/path/to/betvector.db``.
    For PostgreSQL it returns the connection string as-is (e.g.
    ``postgresql://user:pass@host/dbname?sslmode=require``).
    """
    # Priority 1: DATABASE_URL env var (GitHub Actions, Docker, any cloud)
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        logger.info("Using database connection from DATABASE_URL env var")
        return database_url

    # Priority 2: Streamlit Cloud secrets (only available when running in
    # Streamlit, not during pipeline CLI runs).
    # We only attempt to read st.secrets when a secrets.toml file actually
    # exists — accessing st.secrets without one triggers a visible
    # "No secrets found" Streamlit error.
    try:
        import streamlit as st
        from pathlib import Path as _P
        _proj_secrets = _P(__file__).resolve().parents[1].parent / ".streamlit" / "secrets.toml"
        _home_secrets = _P.home() / ".streamlit" / "secrets.toml"
        if (_proj_secrets.exists() or _home_secrets.exists()) and "database" in st.secrets:
            conn_str = st.secrets["database"]["connection_string"]
            if conn_str:
                logger.info("Using database connection from Streamlit secrets")
                return conn_str
    except Exception:
        # Not running in Streamlit context (CLI pipeline, tests, etc.)
        pass

    # Priority 3: Fall back to config file (local SQLite)
    db_path = config.settings.database.path
    full_path = (PROJECT_ROOT / db_path).resolve()
    return f"sqlite:///{full_path}"


def _enable_sqlite_wal(dbapi_conn, connection_record) -> None:
    """Enable WAL journal mode on every new SQLite connection.

    WAL (Write-Ahead Logging) allows concurrent readers while a write is
    in progress — critical for the Streamlit dashboard reading while the
    pipeline writes.  Also enables foreign key enforcement, which SQLite
    disables by default.
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(force_new: bool = False) -> Engine:
    """Return the SQLAlchemy engine, creating it on first call.

    The engine is cached at module level — subsequent calls return the same
    instance unless ``force_new=True`` (useful in tests).

    Parameters
    ----------
    force_new : bool
        If True, discard the cached engine and create a fresh one.

    Returns
    -------
    sqlalchemy.engine.Engine

    Raises
    ------
    RuntimeError
        If the engine cannot be created after one retry.
    """
    global _engine, _SessionFactory

    if _engine is not None and not force_new:
        return _engine

    url = _build_connection_url()
    # Mask password in log output for PostgreSQL connection strings
    _log_url = url
    if "postgresql" in url and "@" in url:
        # postgresql://user:PASSWORD@host/db → postgresql://user:***@host/db
        _log_url = url.split("@")[0].rsplit(":", 1)[0] + ":***@" + url.split("@", 1)[1]
    logger.info("Creating database engine: %s", _log_url)

    # Ensure the parent directory exists so SQLite can create the file.
    # PostgreSQL doesn't use file paths — skip this for non-SQLite URLs.
    if url.startswith("sqlite"):
        db_file = Path(url.replace("sqlite:///", ""))
        db_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        engine = _create_engine_with_retry(url)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to create database engine after retry: {exc}"
        ) from exc

    _engine = engine
    # Reset session factory so it binds to the new engine
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)

    return _engine


def _create_engine_with_retry(url: str, max_retries: int = 1) -> Engine:
    """Create an engine, retrying once on OperationalError.

    The one-retry policy satisfies Rule 6: "every function that touches the
    database must handle connection errors and retry once."
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            # Pool settings differ by backend:
            # - SQLite: single-connection pool to avoid "database is locked"
            # - PostgreSQL: QueuePool sized for Neon serverless free tier
            #   (pool_size=3 keeps within Neon's connection limits, pool_recycle
            #   handles serverless scale-to-zero reconnects)
            engine_kwargs: dict = {"echo": False, "pool_pre_ping": True}
            if url.startswith("postgresql"):
                engine_kwargs.update({
                    "pool_size": 3,
                    "max_overflow": 2,
                    "pool_recycle": 300,
                })

            engine = create_engine(url, **engine_kwargs)
            # Register the WAL/FK pragma listener BEFORE the first connection
            # so every connection (including the verification below) gets WAL.
            # Only applies to SQLite — PostgreSQL handles concurrency natively.
            if url.startswith("sqlite"):
                event.listen(engine, "connect", _enable_sqlite_wal)
            # Verify the connection actually works
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return engine
        except OperationalError as exc:
            last_error = exc
            if attempt < max_retries:
                wait = 1.0 * (attempt + 1)
                logger.warning(
                    "Database connection attempt %d failed (%s), "
                    "retrying in %.1fs...",
                    attempt + 1, exc, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "Database connection failed after %d attempts: %s",
                    max_retries + 1, exc,
                )
    raise last_error  # type: ignore[misc]


# ============================================================================
# Session management
# ============================================================================

@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional session scope.

    Usage::

        with get_session() as session:
            session.execute(text("SELECT 1"))

    On success the session is committed; on exception it is rolled back.
    The session is always closed on exit.  This satisfies the context-manager
    pattern recommended by SQLAlchemy 2.0.
    """
    global _SessionFactory

    engine = get_engine()
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)

    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


# ============================================================================
# Schema management
# ============================================================================

def init_db() -> None:
    """Create all tables that don't already exist.

    Safe to call multiple times — SQLAlchemy's ``create_all`` uses
    ``CREATE TABLE IF NOT EXISTS`` under the hood.

    This function:
    1. Ensures the engine is initialised.
    2. Calls ``Base.metadata.create_all()`` to build every table registered
       on the Base (ORM models defined in E2-02, E2-03, E2-04).
    3. Verifies WAL mode is active (SQLite only).
    """
    engine = get_engine()
    Base.metadata.create_all(engine)

    # Verify WAL mode is actually enabled (belt and suspenders)
    if str(engine.url).startswith("sqlite"):
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).scalar()
            if result != "wal":
                logger.warning(
                    "Expected WAL journal mode but got '%s'. "
                    "Attempting to enable WAL...", result,
                )
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.commit()
            else:
                logger.info("SQLite WAL mode confirmed.")

    logger.info(
        "Database initialised at %s (%d tables)",
        engine.url,
        len(Base.metadata.tables),
    )


def reset_db() -> None:
    """Drop ALL tables and recreate the schema from scratch.

    **Development only** — this destroys all data.  The pipeline and
    dashboard should never call this function.  It exists for test setup
    and local development resets.
    """
    engine = get_engine()
    logger.warning("Dropping all tables — this destroys all data!")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    logger.info("Database reset complete. All tables recreated.")


def verify_connection() -> bool:
    """Quick health-check: can we execute a query?

    Returns True if the database is reachable, False otherwise.
    Useful for dashboard status indicators and pipeline pre-flight checks.
    """
    try:
        with get_session() as session:
            result = session.execute(text("SELECT 1")).scalar()
            return result == 1
    except Exception as exc:
        logger.error("Database health-check failed: %s", exc)
        return False
