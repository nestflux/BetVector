# BetVector — Known Data Gaps

This document records data limitations that **cannot be fixed** due to
external source constraints.  Every gap listed here has been investigated
and confirmed unfixable as of 2026-03-12.

The prediction model handles these gracefully via `fillna(mean).fillna(0.0)`
during training and `fillna(0.0)` at prediction time.

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
