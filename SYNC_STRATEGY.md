# BetVector — Local-to-Cloud Sync Strategy

## Overview

BetVector currently runs entirely on a local Mac with SQLite as the database.
This document outlines the phased migration path from local-only to a hybrid
local + cloud architecture, and eventually to a fully cloud-hosted system.

---

## Phase 1 — Local Only (Current)

**Status:** Active

- **Pipeline:** Runs locally via macOS launchd (3 daily runs: 07:00, 12:00, 21:00)
- **Database:** SQLite at `data/betvector.db` (WAL mode enabled)
- **Dashboard:** Streamlit runs locally (`streamlit run src/delivery/dashboard.py`)
- **Source of truth:** Local SQLite database

**Pros:**
- Zero hosting cost
- No latency — all queries are local
- Full control over data and pipeline
- No dependency on internet for dashboard access

**Cons:**
- Dashboard only accessible from the Mac
- If Mac is off/asleep, pipeline doesn't run (launchd catches up on wake)
- No mobile access to dashboard
- Data loss risk if disk fails (mitigated by git-tracked config + reproducible scraping)

---

## Phase 2 — Local Primary + Cloud Dashboard (Next)

**Goal:** Run the pipeline locally but make the dashboard accessible from anywhere.

**Architecture:**
```
Mac (pipeline) → SQLite → sync_to_cloud.py → Neon PostgreSQL
                                                    ↓
                                          Streamlit Community Cloud
                                          (reads from Neon PostgreSQL)
```

**How it works:**
1. Pipeline continues running locally on Mac, writing to SQLite
2. After each pipeline run, `sync_to_cloud.py` pushes new/changed records to Neon PostgreSQL
3. Streamlit Community Cloud app reads from Neon PostgreSQL
4. SQLite remains the source of truth — cloud is a read replica

**Key decisions:**
- **One-way sync only** (local → cloud). The cloud dashboard is read-only.
  Avoids conflict resolution, which is complex and error-prone.
- **Incremental sync** using `updated_at` timestamps. Only rows modified since
  the last sync are pushed. This keeps sync fast (seconds, not minutes).
- **Schema must match exactly.** Any migration applied to SQLite must also be
  applied to PostgreSQL. The `sync_to_cloud.py` script should verify schema
  compatibility before syncing.

**Implementation steps:**
1. Set `CLOUD_DATABASE_URL` in `.env` (Neon PostgreSQL connection string)
2. Implement `sync_to_cloud.py` with SQLAlchemy dual-engine approach
3. Add sync step to `run_pipeline_local.sh` (after pipeline completes)
4. Deploy dashboard to Streamlit Community Cloud with Neon connection

**Pitfalls to watch:**
- **Schema drift:** If a migration is applied locally but not to cloud, sync breaks.
  Solution: sync script checks table schemas before writing.
- **Neon free tier limits:** 0.5 GB storage, 100 compute hours/month.
  With 6 leagues and ~15K matches, we're well within limits (~50 MB).
- **Sync lag:** Dashboard shows data from the last sync, not real-time.
  Acceptable for a betting analytics tool (updates 3x daily).
- **Mac dependency:** Pipeline still requires the Mac to be on. If the owner
  travels for a week without the Mac, no new predictions are generated.

---

## Phase 3 — Cloud Pipeline (Future)

**Goal:** Move the pipeline to a cloud server so it runs independently of the Mac.

**Architecture:**
```
VPS (pipeline) → PostgreSQL (Neon)
                      ↓
            Streamlit Community Cloud
                      ↓
            Mobile / any browser
```

**Options:**
1. **Cheap VPS** (Hetzner, DigitalOcean — ~$5/month): Run pipeline on cron.
   Most reliable, most control. Python + SQLAlchemy + all dependencies installed.
2. **GitHub Actions** (free tier): Already has workflow files from the Neon era.
   Free but limited (2,000 minutes/month). Fragile — job timeouts, runner issues.
3. **Railway / Render** (free/hobby tier): Auto-deploy from git. Less control
   over scheduling but simpler setup.

**Migration steps:**
1. Set up VPS with Python 3.11 + BetVector dependencies
2. Clone repo, set environment variables (API keys, DATABASE_URL)
3. Configure cron jobs (same schedule as launchd: 07:00, 12:00, 21:00 UTC)
4. Verify pipeline writes directly to Neon PostgreSQL
5. Remove local sync step — pipeline writes to cloud DB directly
6. Keep local Mac as backup (can run pipeline manually if VPS goes down)

**Pitfalls to watch:**
- **API rate limits from VPS IP:** Some scraping targets may block datacenter IPs.
  Football-Data.co.uk and Understat are generally fine. API-Football and The Odds
  API use API keys, so IP doesn't matter.
- **Secret management:** API keys must be securely stored on VPS (not in git).
  Use `.env` file with restricted permissions (chmod 600).
- **Monitoring:** Need alerts if pipeline fails. Options: email on cron failure,
  healthcheck.io (free), or simple log monitoring.

---

## Data Backup Strategy

Regardless of phase, maintain these backups:

1. **Git-tracked config:** `config/*.yaml`, `CLAUDE.md`, build plan — always in git
2. **Local SQLite snapshots:** `scripts/backup_db.sh` creates timestamped copies
3. **Reproducible data:** All historical data can be re-scraped from Football-Data.co.uk,
   Understat, and ClubElo. Scraping scripts are idempotent (INSERT OR IGNORE).
4. **Predictions and bets:** These are the irreplaceable data. Back up `predictions`,
   `value_bets`, `bet_log`, and `bankroll_snapshots` tables regularly.

---

## Timeline

| Phase | Target | Blocker |
|-------|--------|---------|
| Phase 1 | Now | None — fully operational |
| Phase 2 | When mobile dashboard access is needed | Neon account setup (free) |
| Phase 3 | When Mac availability becomes unreliable | VPS setup (~$5/month) |

No phase requires architectural changes to the pipeline code. The SQLAlchemy ORM
abstracts the database — switching from SQLite to PostgreSQL requires only changing
the `DATABASE_URL` environment variable. This was proven during the E33 cloud
migration (Neon PostgreSQL) and PC-13 local rebuild (back to SQLite).
