"""
Download WC national-team flags from flagcdn into data/flags/{FIFA}.png.

Idempotent (skips existing non-empty files) and rate-limited (>=0.5s between
requests). Run once:  python scripts/download_wc_flags.py
"""

import sys
import time

import requests

from src.world_cup.flags import FIFA_TO_ISO, FLAG_DIR, flag_path

FLAGCDN = "https://flagcdn.com/w80/{iso}.png"  # w80 = retina-friendly width


def main() -> int:
    FLAG_DIR.mkdir(parents=True, exist_ok=True)
    ok = skip = fail = 0
    failures = []

    for fifa, iso in FIFA_TO_ISO.items():
        dest = flag_path(fifa)
        if dest.is_file() and dest.stat().st_size > 0:
            skip += 1
            continue

        url = FLAGCDN.format(iso=iso)
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code == 200 and resp.content:
                dest.write_bytes(resp.content)
                ok += 1
                print(f"OK   {fifa} <- {iso} ({len(resp.content)} bytes)")
            else:
                fail += 1
                failures.append(f"{fifa}/{iso} HTTP {resp.status_code}")
                print(f"FAIL {fifa} <- {iso}: HTTP {resp.status_code}")
        except Exception as e:  # network error — never crash the whole run
            fail += 1
            failures.append(f"{fifa}/{iso} {e}")
            print(f"FAIL {fifa} <- {iso}: {e}")

        time.sleep(0.5)  # be polite to the free CDN

    print(f"\nDownloaded {ok}, skipped {skip}, failed {fail}, "
          f"total {len(FIFA_TO_ISO)}")
    if failures:
        print("Failures:", failures)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
