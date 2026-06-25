"""Read-only Neon data-transfer usage via the management API (control plane).

The Neon *management* API (console.neon.tech/api) is the control plane — it is
NOT subject to the database data-transfer quota it reports, so this keeps working
even when SQL connections are quota-blocked.  The Data Health page uses it to
show "data transfer X / 5 GB, resets <date>".

Auth: a Neon API key from the environment (``NEON_API_KEY`` / ``NEON_API_TOKEN``
— set in ``.env`` locally, loaded by the dashboard) or Streamlit secrets
(``NEON_API_KEY`` or ``[neon].api_key`` — for the cloud app).  The key is sent
only in the Authorization header and is never logged.

This module NEVER raises and NEVER calls ``load_dotenv`` (that would pull in
``DATABASE_URL`` and could flip a force-local dashboard onto Neon) — it only
reads what is already in the environment / secrets.  Any problem → ``None`` so
callers degrade gracefully.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE = "https://console.neon.tech/api/v2"
_TIMEOUT = 15


def _api_key() -> Optional[str]:
    """Neon API key from env first (local/pipeline), then Streamlit secrets (cloud)."""
    key = os.environ.get("NEON_API_KEY") or os.environ.get("NEON_API_TOKEN")
    if key:
        return key.strip()
    try:
        import streamlit as st
        if "NEON_API_KEY" in st.secrets:
            return str(st.secrets["NEON_API_KEY"]).strip()
        neon = st.secrets.get("neon") if hasattr(st.secrets, "get") else None
        if neon and "api_key" in neon:
            return str(neon["api_key"]).strip()
    except Exception:
        pass
    return None


def _resolve_project(headers: dict) -> Optional[dict]:
    """Return the Neon project object.

    Account-scoped keys can list every project; a project/org-scoped key cannot
    and must hit ``/projects/{id}``.  For the scoped case the project id is taken
    from ``NEON_PROJECT_ID`` if set, else parsed out of the scoped-key error body
    (Neon names ``subject_project_id`` there, JSON-escaped).
    """
    resp = requests.get(f"{_BASE}/projects", headers=headers, timeout=_TIMEOUT)
    if resp.status_code == 200:
        projects = resp.json().get("projects", [])
        return projects[0] if projects else None

    pid = os.environ.get("NEON_PROJECT_ID")
    if not pid:
        # The id sits inside an escaped-quote JSON string: subject_project_id:\"...\"
        match = re.search(r'subject_project_id:\s*\\?"?([a-z0-9-]+)', resp.text)
        pid = match.group(1) if match else None
    if not pid:
        return None

    one = requests.get(f"{_BASE}/projects/{pid}", headers=headers, timeout=_TIMEOUT)
    if one.status_code != 200:
        return None
    return one.json().get("project")


def fetch_neon_usage(limit_gb: float = 5.0) -> Optional[dict]:
    """Return Neon data-transfer usage for the current consumption period.

    Returns a dict with ``project_name, used_bytes, used_gb, limit_gb, pct
    (0..1+), period_start, period_end, reset_date (YYYY-MM-DD), days_until_reset``
    — or ``None`` if no API key is configured or the API is unreachable.  Never
    raises.
    """
    key = _api_key()
    if not key:
        return None
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        project = _resolve_project(headers)
        if not project:
            return None
        used = int(project.get("data_transfer_bytes") or 0)
        used_gb = used / 1e9
        end = project.get("consumption_period_end")
        reset_date, days_until = None, None
        if end:
            try:
                end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                reset_date = end_dt.date().isoformat()
                days_until = (end_dt - datetime.now(timezone.utc)).days
            except Exception:
                pass
        limit = float(limit_gb) if limit_gb else 0.0
        return {
            "project_name": project.get("name"),
            "used_bytes": used,
            "used_gb": round(used_gb, 2),
            "limit_gb": limit,
            "pct": (used_gb / limit) if limit else 0.0,
            "period_start": project.get("consumption_period_start"),
            "period_end": end,
            "reset_date": reset_date,
            "days_until_reset": days_until,
        }
    except Exception:
        logger.debug("fetch_neon_usage failed", exc_info=True)
        return None
