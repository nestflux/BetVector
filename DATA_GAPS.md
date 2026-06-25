# BetVector — Known Data Gaps

This document records data limitations that **cannot be fixed** due to
external source constraints.  Every gap listed here has been investigated
and confirmed unfixable as of 2026-03-12.

The prediction model handles these gracefully via `fillna(mean).fillna(0.0)`
during training and `fillna(0.0)` at prediction time.

---

## ⚠️ OPEN — Pre-season investigation (parked 2026-06-25; do before leagues resume ~Aug)

Unlike the confirmed-unfixable gaps below, these are **drifts to investigate** — surfaced by
the 2026-06-25 level-staking baseline regen (re-running each league's *tuned* backtest on
current data). No live impact now (leagues off-season); investigate/confirm before the season.

1. **Pinnacle / sharp-only odds coverage collapse (La Liga, Ligue 1).** Their backtests run
   `sharp_only: true` (Pinnacle-only). On current data the Pinnacle-covered value-bet count
   collapsed — **La Liga 110 → 16 bets, Ligue 1 → 55** — making their tier CIs meaningless
   (La Liga CI [−38%, +138%]). Investigate: did Pinnacle coverage for these leagues actually
   shrink in the DB, or is it a join/ingestion regression? Affects their value bets + tier
   reliability once live.
2. **EPL Poisson λ-clamping / Brier degradation.** EPL Poisson Brier drifted 0.578 → 0.603
   with heavy λ-clamping to the 0.2 floor (many matches' away-goals predictions pinned low).
   Investigate which feature(s) push away-λ to the floor on current data.

Stable (reproduce documented baselines — no action): Championship (731 bets, CI [3.4, 23.2]),
Serie A (CI [−32.4, −4.5]). The staking change is NOT a cause — tier CIs are a bootstrap on
per-bet returns = staking-invariant (Championship reproduced exactly). Full analysis:
`betvector_buildplan.md` §staking-reconcile.

---

## ⚙️ Neon data-transfer reduction (2026-06-25) — OPS NOTE

Neon (cloud Postgres) hit its free-tier **data-transfer** quota — same wall as
PC-13. Investigation found the chronic drains were (1) the **off-season league
pipelines** still firing 3×/day against Neon and (2) the **uncached dashboard**;
a burst from this session's full-history backtests + Neon-sourced previews tipped
it over. Owner-approved remediation applied (caching deferred):

1. **League crons PAUSED for the off-season.** `com.betvector.morning` (07:00),
   `com.betvector.midday` (12:00), `com.betvector.evening` (21:00) were
   `launchctl unload -w`'d (disabled across reboots). They did NO useful work
   off-season (no new matches until ~Aug) yet re-scraped + re-loaded all 6
   leagues against Neon every run. The WC jobs (`wc_morning` 09:30, `wc_evening`
   23:30, `wc_dispatcher` /15min) remain LOADED — WC is live.
   **RE-ENABLE when leagues resume (~Aug 22):**
   `for j in morning midday evening; do launchctl load -w ~/Library/LaunchAgents/com.betvector.$j.plist; done`
2. **Analytics/previews forced LOCAL.** New env override
   **`BETVECTOR_FORCE_LOCAL_DB=1`** (db.py `_build_connection_url`, Priority 0)
   returns the local SQLite mirror even when DATABASE_URL/secrets point at Neon.
   The `wc_preview` launch config now sets it. **Convention:** any backtest /
   preview / ad-hoc analysis run should set `BETVECTOR_FORCE_LOCAL_DB=1` (or
   simply not source `.env`) so it never burns Neon transfer. Production
   (pipelines, Streamlit Cloud) leaves the flag UNSET → Neon as before.
3. **DEFERRED (owner did not take):** dashboard read-caching (`@st.cache_data`)
   + a date filter on the WC landing page. The dashboard caches almost nothing,
   so every rerun re-pulls medium tables (WC page worst). This is the remaining
   chronic per-user drain — revisit once Neon is back online to redeploy.

---

## 1. Championship xG / Advanced Stats

**Affected league:** Championship (league_id=2)
**Affected columns:** All xG-derived features (`xg_5/10`, `xga_5/10`, `xg_diff_5/10`,
`npxg_5/10`, `npxga_5/10`, `npxg_diff_5/10`, `ppda_5/10`, `ppda_allowed_5/10`,
`deep_5/10`, `deep_allowed_5/10`, `set_piece_xg_5`, `open_play_xg_5`)

**Reason:** Understat does not cover the Championship (config: `understat_league: null`).
FBref was the original source but has been blocked by Cloudflare 403 since January 2026.
No free alternative xG source covers the English second tier.

**Impact:** Championship predictions rely on goals-only rolling features, Elo, odds, and
context features.  The league has a higher `edge_threshold_override: 0.03` to compensate.

---

## 2. Shots, Shots on Target, Possession

**Affected columns:** `shots_5`, `shots_10`, `shots_on_target_5`, `shots_on_target_10`,
`possession_5`, `possession_10` (6 columns, 100% NULL across all leagues)

**Reason:** These columns were sourced from FBref (via the `soccerdata` package).
FBref lost all Opta data and has been blocked by Cloudflare since January 2026.
Understat does not provide shots, shots on target, or possession data.

**Impact:** Minimal.  The model compensates via xG features (which correlate with
shot volume) and NPxG/deep completions (which capture attacking quality).  These
6 columns are defined in the Feature model but will remain NULL indefinitely.

---

## 3. Referee Statistics — Continental Leagues

**Affected leagues:** La Liga, Ligue 1, Bundesliga, Serie A (league_ids 3-6)
**Affected columns:** `ref_avg_fouls`, `ref_avg_yellows` (100% NULL for continental),
`ref_avg_goals`, `ref_home_win_pct` (65.9% NULL overall — only English leagues have data)

**Reason:** Football-Data.co.uk CSV files only include the referee name for English
leagues (E0 = EPL, E1 = Championship).  Continental league CSVs (SP1, F1, D1, I1)
do not have a referee column.

**Impact:** Referee features provide marginal signal (referee strictness → more fouls
→ more set pieces).  The model still predicts accurately for continental leagues
using all other features.

---

## 4. Venue xG Cold-Start

**Affected columns:** `venue_xg_5`, `venue_xga_5` (29% NULL overall)

**Reason:** These are 5-match rolling averages computed from **venue-specific**
matches only (home OR away).  A team needs at least 5 home matches (or 5 away
matches) before these columns become non-NULL.  This is expected behavior at
the start of each season.

**Impact:** None — this is by design.  The model uses overall `xg_5` when venue
xG is unavailable.

---

## 5. Transfermarkt — Current Snapshot Only

**Affected columns:** `market_value_ratio`, `squad_value_log`

**Limitation:** The Transfermarkt Datasets CDN (`dcaribou/transfermarkt-datasets`)
only serves the **current** snapshot of player market values.  There is no free
API for historical market values on specific dates.

**Workaround:** The current snapshot is used as a proxy for all seasons.  Market
value ratios between teams are relatively stable within a season — a team valued
at 5x their opponent today was likely at a similar ratio 6 months ago.  For
historical seasons (2020-2024), the current values are an acceptable approximation.

---

## 6. xG Features Cold-Start (All Leagues)

**Affected columns:** `xg_5`, `xga_5`, `xg_diff_5`, `xg_10`, etc. (28.3% NULL)

**Reason:** Rolling xG averages require a minimum number of prior completed
matches with MatchStat data.  At the start of each season, the first few matches
lack the 5 or 10 prior matches needed for the rolling window.  Additionally,
Championship matches contribute to this NULL rate since Understat does not cover
the league.

**Impact:** Expected — the model fills these with training-set means or 0.0.

---

## 7. Championship Transfermarkt Market Values

**Affected league:** Championship (league_id=2)
**Affected columns:** `market_value_ratio`, `squad_value_log`

**Reason:** The `dcaribou/transfermarkt-datasets` CDN only includes first-tier
league data.  The `current_club_domestic_competition_id` column has GB1 (EPL)
but not GB2 (Championship).  No free alternative provides squad-level market
value data for the English Championship.

**Impact:** Championship predictions rely on all other features (Elo, form,
goals, odds, context).  Market value features will be NULL for Championship.

---

## Summary Table

| Gap | Columns Affected | Leagues | Fixable? | Workaround |
|-----|-----------------|---------|----------|------------|
| Championship xG | 16 columns | Championship | No | Goals-only features + higher edge threshold |
| FBref shots/possession | 6 columns | All | No | xG/NPxG/deep features compensate |
| Continental referee | 4 columns | La Liga, L1, BuLi, Serie A | No | Model uses other features |
| Venue xG cold-start | 2 columns | All (season start) | No | By design — overall xG used |
| Transfermarkt history | 2 columns | All (historical) | No | Current values as proxy |
| xG cold-start | 8+ columns | All (season start) | No | Mean imputation |
| Championship market values | 2 columns | Championship | No | Model uses Elo + other features |
