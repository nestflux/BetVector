"""Print Neon project data-transfer usage + consumption period (quota window).

Read-only. Delegates to ``src.monitoring.neon_usage.fetch_neon_usage``, which
calls the Neon MANAGEMENT API (control plane — NOT subject to the DB
data-transfer quota, so it works even while SQL connections are quota-blocked).

Requires a Neon API key in .env as NEON_API_KEY (create one at: Neon Console ->
Account settings -> API Keys). The key is read from the environment and sent
only in the Authorization header — it is never printed or logged.

Usage:
    source venv/bin/activate && python scripts/neon_usage.py
"""
import sys

from dotenv import load_dotenv

load_dotenv("/Users/kyng/Projects/BetVector/.env")

from src.monitoring.neon_usage import fetch_neon_usage  # noqa: E402

usage = fetch_neon_usage()
if usage is None:
    print(
        "Neon usage unavailable — set NEON_API_KEY in .env "
        "(Neon Console -> Account settings -> API Keys), then re-run."
    )
    sys.exit(1)

print(f"Project:                  {usage['project_name']}")
print(f"consumption_period_start: {usage['period_start']}")
print(f"consumption_period_end:   {usage['period_end']}  <- quota resets here")
print(
    f"data_transfer:            {usage['used_bytes']:,} bytes "
    f"(~{usage['used_gb']:.2f} GB of {usage['limit_gb']:.0f} GB "
    f"= {usage['pct'] * 100:.0f}%)"
)
_days = usage.get("days_until_reset")
if isinstance(_days, int):
    print(f"resets_in:                {_days} days ({usage['reset_date']})")
