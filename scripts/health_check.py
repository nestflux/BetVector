#!/usr/bin/env python
"""BetVector data-health check CLI (DH-02).

Thin entrypoint — the logic lives in src.monitoring.health_cli so it stays testable.
Run it with `make health`, or directly:

    python scripts/health_check.py            # coloured text report
    python scripts/health_check.py --json     # machine-readable JSON
    python scripts/health_check.py --strict   # exit non-zero on WARN as well as FAIL

Read-only: every check is a SELECT. Exits 1 on any FAIL (or any WARN under --strict),
so it can gate a pipeline or CI step.
"""

import sys
from pathlib import Path

# Allow running as a bare script (python scripts/health_check.py) without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.monitoring.health_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
