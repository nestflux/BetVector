"""Print Neon project consumption period (the quota-reset window) + usage.

Read-only. Uses the Neon MANAGEMENT API (console.neon.tech/api), which is the
control plane — it is NOT affected by the database data-transfer quota, so this
works even while SQL connections are quota-blocked.

Requires a Neon API key in .env as NEON_API_KEY (or NEON_API_TOKEN). Create one
at: Neon Console -> Account settings -> API Keys. The key is read from the env
and sent only in the Authorization header — it is never printed or logged.

Usage:
    source venv/bin/activate && python scripts/neon_usage.py
"""
import os
import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv("/Users/kyng/Projects/BetVector/.env")

key = os.environ.get("NEON_API_KEY") or os.environ.get("NEON_API_TOKEN")
if not key:
    print(
        "NO_NEON_API_KEY — add NEON_API_KEY=... to .env first "
        "(Neon Console -> Account settings -> API Keys), then re-run."
    )
    sys.exit(1)

headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
BASE = "https://console.neon.tech/api/v2"


def _get(url):
    try:
        return requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        sys.exit(1)


# Account-scoped keys can list every project; a PROJECT-scoped key cannot and
# must hit /projects/{id} instead. Resolve the project id from NEON_PROJECT_ID,
# else from the scoped-key error body (it names subject_project_id).
resp = _get(f"{BASE}/projects")
if resp.status_code == 200:
    projects = resp.json().get("projects", [])
else:
    pid = os.environ.get("NEON_PROJECT_ID")
    if not pid:
        # Neon's error body is JSON, so the id is wrapped in ESCAPED quotes
        # (subject_project_id:\"...\"); allow an optional backslash before it.
        m = re.search(r'subject_project_id:\s*\\?"?([a-z0-9-]+)', resp.text)
        pid = m.group(1) if m else None
    if not pid:
        # Never echo the key; show only the (key-free) error body.
        print(f"Neon API HTTP {resp.status_code}: {resp.text[:300]}")
        sys.exit(1)
    one = _get(f"{BASE}/projects/{pid}")
    if one.status_code != 200:
        print(f"Neon API HTTP {one.status_code}: {one.text[:300]}")
        sys.exit(1)
    projects = [one.json().get("project", {})]

if not projects:
    print("API key valid, but no projects are visible to it.")
    sys.exit(0)

for p in projects:
    print(f"Project: {p.get('name')}  (id={p.get('id')}, region={p.get('region_id')})")
    print(f"  consumption_period_start: {p.get('consumption_period_start')}")
    print(f"  consumption_period_end:   {p.get('consumption_period_end')}  <- quota resets here")
    print(f"  created_at:               {p.get('created_at')}")
    dt = p.get("data_transfer_bytes")
    if dt is not None:
        print(
            f"  data_transfer:            {int(dt):,} bytes "
            f"(~{int(dt) / 1e9:.2f} GB; Free plan allows 5 GB / period)"
        )
    # Show any other usage fields the project object carries (names vary by plan).
    for fld in (
        "written_data_bytes", "synthetic_storage_size", "compute_time_seconds",
    ):
        if p.get(fld) is not None:
            try:
                print(f"  {fld}: {int(p[fld]):,}")
            except (TypeError, ValueError):
                print(f"  {fld}: {p[fld]}")
    print()
