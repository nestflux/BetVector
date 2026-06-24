# WC-09-08 — Player-Props Feasibility Spike (go/no-go)

**Type:** Spike / Research (time-boxed) · **Date:** 2026-06-23 · **No production code shipped.**

> **Recommendation in one line:** **Lean NO-GO for a staked product; CONDITIONAL
> SHADOW-GO** for a decision-support prototype only. The approach is technically
> feasible (the prototype produces market-accurate numbers from data we already
> have), but the value case is weak for the same reason team bets are shadow-only
> — the market is efficient and our player model would be cruder than our team
> model — and a live prop-odds feed would roughly consume the monthly Odds API
> quota. Defer a full WC-11 build; if pursued, scope it as shadow-only.

---

## 1. Per-player WC data availability & quality

All sourced from the **already-downloaded** Transfermarkt dataset
(`data/raw/transfermarkt/datasets/`) — no new scraping needed for the model side.

| Need | Source | Status |
|------|--------|--------|
| Per-player **goals + minutes** (→ goals-per-90) | `appearances.csv.gz` (millions of rows: IT1 155K, ES1 154K, GB1 150K, …) | ✅ Rich, current |
| Per-player **cards** (→ card-prop rates) | `appearances.csv.gz` (`yellow_cards`, `red_cards`) | ✅ Available |
| **Player → nation** mapping | `players.country_of_citizenship` → `national_teams.csv` (118 nations, FIFA rankings) | ⚠️ Works via **citizenship name**, not IDs (see gap 2) |
| Player metadata (position, market value, intl goals/caps, DOB) | `players.csv.gz` | ✅ Complete |
| **Shots / shots-on-target** | — | ❌ **Not in Transfermarkt** — would need FBref |
| **Official 26-man WC squads / expected lineups** | — | ❌ **Not in any dataset** (see gap 1) |

### Gaps / gotchas found
1. **Squad selection is the #1 blocker.** The data gives a nation's *eligible
   pool* (England: 1,682 citizens, 461 with recent club minutes), not the
   *selected 26* or the *starting XI*. Approximating the XI by "most recent club
   minutes" pulls in non-selected players (the prototype surfaced **James
   Tavernier**, not an England regular). A usable build needs the **official
   squad lists** (manual one-time entry, ~48 × 26 ≈ 1,250 names, or a squad
   scrape once squads are announced) and ideally **predicted lineups** on match day.
2. **`current_national_team_id` is unusable for the major nations.** It's
   populated for only ~5% of players and skews to minor nations (the IDs that do
   exist map cleanly, but England = 3299 has **zero** players pointing to it).
   Must link by `country_of_citizenship` name instead — which adds fuzziness
   (dual nationals; Transfermarkt splits England/Scotland/Wales, so "United
   Kingdom" needs care, mirroring our existing `USA → United States` alias work).
3. **Minutes/rotation uncertainty dominates the estimate.** Anytime-scorer prob
   scales directly with expected minutes; a 90' starter vs a 60' rotation risk is
   a large swing. Without predicted lineups we're guessing the most sensitive input.
4. **No shots data** → only **anytime-scorer** and **cards** are sourceable from
   Transfermarkt. Shots-on-target props (4-book coverage) would require adding FBref.
5. **Penalty-taker concentration is unmodeled.** A designated penalty taker carries
   a real anytime bump that raw club-gp90 transfers incorrectly when penalty duty
   differs between club and country. (`game_events.csv.gz` has ~247K goal events and
   could flag penalties — fixable, not impossible.)
6. **Club→international transfer is assumed 1:1.** The prototype uses *club* gp90
   directly as the *international* scoring basis, ignoring opposition strength and
   club-vs-country role differences. This assumption is baked into the core method.

---

## 2. Prototype — anytime scorer for one match (England, team λ ≈ 1.9)

Method: team expected goals (from our match model) distributed across the likely XI
by each player's **club goals-per-90**, then `P(anytime) = 1 − exp(−λ_player)`.
(The prototype held expected minutes *flat* across the XI — minutes is the dominant
unmodeled input, per gap 3 — so these figures are a strength-of-form sketch, not a
minutes-aware estimate.)

| Player | Pos | club gp90 | Model P(anytime) |
|--------|-----|-----------|------------------|
| Harry Kane | CF | 1.08 | **46.8%** |
| Ollie Watkins | CF | 0.48 | 24.2% |
| Jarrod Bowen | RW | 0.33 | 17.6% |
| Jude Bellingham | AM | 0.28 | 15.2% |
| Declan Rice | CM | 0.15 | 8.4% |

**Vs the market:** Kane's anytime is typically priced ≈ **2.00** (≈ 50% raw,
≈ **46%** de-vigged at a ~8% overround). The model's **46.8%** lands essentially
on the de-vigged market, and the ordering is role-correct (forwards high,
defensive mids low). **The approach produces credible numbers from data we already
hold.** (I did not spend Odds API credits to pull a live line for this go/no-go —
the alignment with the well-established Kane level is clear, and coverage is
already confirmed; a production build would wire the live pull.)

**What this proves:** the *modelling* is feasible and roughly calibrated for a
star striker. **What it doesn't prove:** an *edge* — matching the de-vigged market
is exactly what an efficient market expects, not a betting signal.

---

## 3. Prop-scrape budget plan (the hard constraint)

The Odds API cost = **markets × regions** per event, on the
`/events/{id}/odds` endpoint. Confirmed coverage (prior 15-credit check):
anytime/first scorer **10 books incl. Pinnacle**, shots-on-target 4, cards 4.

| Discipline | Plan |
|-----------|------|
| Regions | **1 only** (the region containing Pinnacle) — never multi-region |
| Markets | **1** (`player_goal_scorer_anytime`) for v1; add first-scorer only if justified |
| Cadence | **Day-of only** — pull just that day's WC fixtures, once, in the morning |
| Rough cost | ~4–8 fixtures/day × 1 market × 1 region ≈ **8–16 credits/day** → **~250–450 credits** over the group+knockout run |

**Budget reality:** that is **on the order of the entire ~323/month quota**, on top
of existing league + WC team-odds pulls. A props feed is **not affordable on the
current plan** without either (a) dropping some team-odds cadence, or (b) upgrading
the Odds API tier. This is a gating cost, not a footnote.

---

## 4. WC-11 scope sketch (only if the owner opts in)

Shadow-only, mirroring the team-model discipline (never staked until proven):

1. **`wc_players` + `wc_squads`** — ingest official 26-man squads (one-time manual
   or squad scrape); store position, club, market value.
2. **Player rate engine** — club goals-per-90 (+ card rates) from the existing
   Transfermarkt `appearances` data; recency-weighted, like the Bayesian team model.
3. **Anytime-scorer model** — team λ (from the Poisson/Bayesian) × player goal-share
   × expected minutes → `1 − exp(−λ)`. Expected minutes from predicted lineups;
   must also model **penalty-taker duty** and a **club→international level
   adjustment** (gaps 5–6) — both material for a staking-grade estimate.
4. **Shadow tracker** — surface model vs de-vigged market on the **research card**
   (reuse WC-09-03/04), track calibration/CLV; **no auto-bets**, ever.
5. **Tight odds budget** — §3 discipline, behind a config flag, day-of only.

Effort: ~3–5 days. Hard dependency: **official squad + lineup data** (gap 1).

---

## 5. Go / No-Go

**Lean NO-GO for staking; CONDITIONAL SHADOW-GO for decision-support.**

- ✅ **Feasible:** data exists (no new scraping for the model), prototype is
  market-accurate, coverage confirmed.
- ❌ **Weak value case:** anytime-scorer markets are efficient (Pinnacle prices
  them sharply); our player model would be *cruder* than our team model, which is
  itself **not sharp enough to stake** (WC bets are already shadow-only). A cruder
  model into an efficient market is unlikely to find real edge.
- ❌ **Real costs/blockers:** official squad + lineup data (not in any dataset);
  no shots data without FBref; a live prop feed ≈ the whole monthly Odds API quota.

**Recommendation:** **defer the full WC-11 build.** Revisit *only* if (a) the team
Bayesian shadow first demonstrates the modelling approach can beat the market at
all, and (b) the owner wants player estimates as **decision-support** (shown next
to the market on the research card), explicitly **not** a staked product, and is
willing to fund the odds budget. The spike has de-risked the *how* — the open
question is whether it's *worth it*, and today the honest answer is "not yet."
