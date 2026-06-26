"""Ensure SESSION_COOKIE_SECRET exists in .env (for persistent-login cookies).

The dashboard signs its "stay signed in" cookie with this secret (HMAC), so a
client can't forge a session. This script generates a strong random secret and
appends it to .env IF it isn't already set. Idempotent — re-running never
overwrites an existing secret.

The secret VALUE is never printed. To enable persistent login on Streamlit
Cloud too, open your local .env, copy the SESSION_COOKIE_SECRET line, and paste
it into the app's Cloud secrets.

Usage:  python scripts/gen_session_secret.py
"""
import re
import secrets
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"
KEY = "SESSION_COOKIE_SECRET"


def main() -> None:
    text = ENV.read_text() if ENV.exists() else ""

    # Already set with a non-empty value? Leave it untouched (idempotent).
    for line in text.splitlines():
        m = re.match(rf"^\s*{KEY}=(.*)$", line)
        if m and m.group(1).strip():
            print(f"{KEY} already set in .env — leaving it unchanged.")
            return

    token = secrets.token_hex(32)  # 256-bit secret
    sep = "" if (text == "" or text.endswith("\n")) else "\n"
    with ENV.open("a") as f:
        f.write(f"{sep}{KEY}={token}\n")
    print(
        f"Added {KEY} to .env (64 hex chars; value not printed). "
        "Persistent login now works locally. For the cloud app, copy that line "
        "from .env into Streamlit Cloud secrets."
    )


if __name__ == "__main__":
    main()
