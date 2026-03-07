# BetVector — New User Guide

Welcome to BetVector. This guide is for people who have been given access
to the dashboard as a viewer. You don't need to touch any code, terminals,
or configuration files — your job is to use the dashboard and decide which
bets to place.

**Version:** 1.0
**Last updated:** March 2026

---

## What BetVector Does

BetVector runs three times every day, automatically:

1. **Morning (06:00 UTC)** — Scrapes today's fixtures and bookmaker odds,
   runs a Poisson football model against those odds, and surfaces every match
   where the model believes the bookmaker is mispricing the outcome. These
   are called **value bets**.

2. **Midday (13:00 UTC)** — Re-fetches odds (they move throughout the day),
   recalculates the edge on each value bet, and updates the picks list.

3. **Evening (22:00 UTC)** — Scrapes final scores, settles all pending bets
   as won or lost, updates your P&L, and records performance metrics.

You do not need to trigger any of these runs. They happen automatically.
Your role is to:

1. Open the dashboard after the morning run
2. Review today's picks
3. Decide which picks to place with your bookmaker
4. Log the bets you placed on the dashboard
5. Check results in the evening

---

## Logging In

Go to the BetVector dashboard URL (the owner will share this with you).

You will see a login screen asking for your **email address** and
**password**. Both are set by the owner — you receive them separately.

> **If you forget your password:** Contact the owner. They can reset it
> from the Admin page. You cannot reset it yourself.

After logging in you go straight to the **Fixtures** page. Your session
persists until you close the browser or click **Logout** in the sidebar.

---

## Your First Time: Onboarding Wizard

The first time you log in you will see a short setup wizard before the
main dashboard. It asks you to configure:

| Setting | What it means | Where to start |
|---------|---------------|----------------|
| **Starting Bankroll** | How much money you are committing to this strategy | The total you plan to bet with across the season |
| **Staking Method** | How to size each bet | Start with **Flat** — a fixed amount per bet, simple and safe |
| **Flat Stake / Percentage** | Only shown for flat or percentage staking | We suggest £20–£50 per bet depending on your bankroll |
| **Edge Threshold** | Minimum edge before a bet is flagged | Leave at the default 5% — you can tighten it later |
| **Paper Trading Mode** | Simulate bets without real money at risk | Turn **on** for your first few weeks |

You only see this wizard once. You can change all these settings later
from the **Settings** page.

---

## The Dashboard Pages

### 📅 Fixtures

The default landing page. Shows all upcoming fixtures in the leagues you
are tracking for the current week.

- **Green ring** around a team badge = home advantage flag
- **Blue ring** = team is on strong recent form
- Click any match to go to the **Match Deep Dive** for that fixture

### 🎯 Today's Picks

This is your primary daily page. After the morning pipeline runs, every
value bet the model found appears here as a card.

**Reading a pick card:**

| Field | What it means |
|-------|---------------|
| **Match** | Home team vs Away team, kickoff time |
| **Market** | 1X2 (match result), Over/Under 2.5 goals, or BTTS |
| **Selection** | What the model is recommending (e.g. Home win, Over 2.5) |
| **Model Probability** | The model's estimated chance of this outcome happening |
| **Implied Probability** | The bookmaker's estimate (calculated from the odds) |
| **Edge** | Model probability minus implied probability. Your expected advantage. |
| **Best Odds** | The highest odds found across tracked bookmakers |
| **Suggested Stake** | A stake calculated based on your bankroll and staking method |
| **Confidence** | High (edge ≥ 10%), Medium (5–10%), Low (< 5%) |

**To log a bet after you've placed it with your bookmaker:**

1. Find the pick card for the match
2. Click **"Log Bet"** (or "Confirm Bet Placed")
3. The system records this as a *user-placed bet* in your personal bet log
4. This is separate from the *system pick* that was already logged automatically — the dual tracking lets you compare what you actually bet vs what the model recommended

> **Important:** Log the bet after you've actually placed it. Do not log
> bets you're still thinking about — this creates inaccurate records.

### 📈 Performance Tracker

Shows how you are doing over time.

- **ROI** — your net return as a percentage of total staked
- **P&L Chart** — cumulative profit/loss plotted over time
- **Brier Score** — model prediction accuracy (lower is better; 0.25 is
  random chance, below that is skill)
- **Bet breakdown** — filter by market type, league, and date range
- Two views: *System Picks* (every model recommendation) and *Your Bets*
  (only what you actually placed)

Check this page every evening after the results pipeline runs.

### 🏟️ League Explorer

Performance broken down by league. Useful for seeing which leagues produce
the most value bets and where the model performs best. If one league is
consistently underperforming, you can consider raising the edge threshold
for it in Settings.

### 🔬 Model Health

Tracks whether the underlying Poisson model is well-calibrated.

- **Calibration curve** — a well-calibrated model hugs the diagonal line.
  If the curve bows upward, the model is underestimating probabilities.
  If it bows downward, it is overestimating.
- **Rolling Brier Score** — if this trends upward over several weeks, the
  model may need retraining. The system handles this automatically, but
  it is worth checking monthly.

You don't need to do anything on this page — it's informational.

### 💰 Bankroll Manager

Tracks your money.

- **Current Bankroll** — how much you have now vs how you started
- **Drawdown Monitor** — how far below your peak you are currently
- **Safety Alerts** — the system flags you if:
  - Your daily losses exceed 10% of bankroll
  - Drawdown from peak exceeds 25%
  - Bankroll drops below 50% of starting amount

If any safety alert fires, **stop placing new bets** until you review
the situation. These limits exist to protect you.

### ⚙️ Settings

Lets you change your personal preferences at any time.

- Switch staking method (flat / percentage / kelly)
- Adjust your edge threshold
- Change your stake size or bankroll percentage
- Toggle paper trading mode on/off
- **Danger Zone** — reset your bankroll back to starting, clear your bet
  history, or both. Use with caution. This action is permanent.

---

## Your Daily Routine

### Morning (check after 06:30 UTC — 06:30 GMT / 07:30 BST)

1. Open the dashboard → **Today's Picks**
2. Review pick cards. Focus on high-confidence picks (edge ≥ 8%)
3. Cross-reference with your own knowledge: any injury news? motivation
   concerns? weather? Do your own brief sense-check.
4. Place the bets you agree with at your bookmaker
5. Log each bet on the dashboard immediately after placing it

### Midday (check after 13:30 UTC)

1. Open **Today's Picks** again
2. Odds may have moved. Check if any edges have changed significantly
3. New value bets may have appeared on matches with later kickoffs
4. Place additional bets if new value has appeared

### Evening (check after 22:30 UTC)

1. Open **Performance Tracker** → check today's results
2. Open **Bankroll Manager** → check if any safety alerts fired
3. Nothing else needed — the system has already settled all bets and
   updated your P&L

### Weekly (Sundays)

1. Open **Model Health** — is the calibration curve still well-behaved?
2. Open **Performance Tracker** → filter by the past 4 weeks. Is ROI
   trending upward, flat, or downward?
3. Open **League Explorer** — which markets and leagues are performing?
4. Review your Settings if you want to adjust edge threshold or staking
   method based on what you are seeing.

---

## Understanding Odds and Edge

### Decimal Odds

BetVector uses decimal odds (the standard in UK/European betting).

- **Odds of 2.00** = 1 in 2 chance implied (50%) = you get your stake back
  plus 1× your stake if you win
- **Odds of 3.00** = 1 in 3 chance implied (33%) = you get your stake back
  plus 2× your stake if you win
- **Odds of 1.50** = 2 in 3 chance implied (67%) = you get your stake back
  plus 0.5× your stake if you win

### Implied Probability

A bookmaker's odds imply a probability: **1 ÷ odds**.

- Odds 2.00 → implied probability = 1/2.00 = 50%
- Odds 3.50 → implied probability = 1/3.50 = 28.6%

Bookmakers add an overround (their margin), so implied probabilities always
sum to more than 100% across a market.

### Edge

**Edge = Model Probability − Implied Probability**

If the model says a home win has 55% probability and the bookmaker's odds
imply 45%, the edge is **+10%**. This means the bookmaker is systematically
underpricing this outcome — you have an expected advantage on this bet.

Over a large number of bets with consistent positive edge, you should
generate a positive return. Edge alone does not guarantee winning any
individual bet.

### Why You Will Lose Individual Bets

A 60% probability outcome loses 40% of the time. That is normal and
expected. What matters is:

1. Placing bets only when edge is positive (≥ 5%)
2. Sizing bets appropriately (never risking more than 5% of bankroll on
   one bet)
3. Tracking results over a large sample (100+ bets minimum before drawing
   conclusions)
4. Not chasing losses

---

## Paper Trading Mode: What It Means

When paper trading is enabled:

- Every bet you log is marked as **simulated**
- Your bankroll tracking, P&L, and performance metrics all update as
  if real money was wagered
- No real money is at risk
- You can evaluate the model's performance before committing funds

**Recommended:** Run in paper trading mode for your first 4–6 weeks or
until you have at least 50 resolved bets. This builds confidence in the
model and helps you understand the variance before real money is involved.

Turn paper trading off in **Settings** when you are ready to go live.

---

## What the Model Does Not Know

The Poisson model is built on historical match data, xG, and bookmaker
odds. It does not know:

- **Breaking team news** — a key player ruled out 2 hours before kickoff
- **Motivation** — a team with nothing to play for in the final weeks
- **Travel/fixture congestion** — a team playing their 4th game in 10 days
- **Weather** — heavy rain significantly affects Over/Under markets
- **Referee tendencies** — certain referees affect match dynamics

These factors are captured partially (the congestion and referee features
exist in the model) but not perfectly. Your own knowledge of these
factors should augment the model's picks, not replace them.

If you know something significant that happened after the morning pipeline
ran — use your judgment. The model gave you a starting point; the final
decision is yours.

---

## Glossary

| Term | Plain English meaning |
|------|-----------------------|
| **Value Bet** | A bet where the model thinks the bookmaker's odds are too generous — our estimated probability is higher than the odds imply |
| **Edge** | Our expected advantage on a bet, in percentage points |
| **System Pick** | A value bet automatically logged by the model. Logged whether or not you place it. |
| **User-Placed Bet** | A bet you manually logged after placing it with your bookmaker |
| **Implied Probability** | What the bookmaker's odds say the chance of an outcome is (1 ÷ odds) |
| **1X2** | Match result market: 1 = home win, X = draw, 2 = away win |
| **Over/Under 2.5** | Whether the total goals in the match is 3 or more (Over) or 2 or fewer (Under) |
| **BTTS** | Both Teams To Score — both teams score at least one goal |
| **Brier Score** | Prediction accuracy measure. 0 = perfect. 0.25 = random. Lower is better. |
| **ROI** | Return on Investment — (total returns − total staked) ÷ total staked, as a percentage |
| **Drawdown** | How far your bankroll has fallen from its highest point |
| **Paper Trading** | Simulated betting — all the tracking, none of the real-money risk |
| **Kelly Criterion** | A staking formula that sizes bets based on edge size. Volatile alone; safer at quarter-Kelly. |
| **Scoreline Matrix** | The 7×7 grid of probabilities (0-0 through 6-6) that the model produces internally. All market probabilities are derived from this. |
| **xG** | Expected Goals — a measure of the quality of chances created, based on shot location and type |

---

## Getting Help

Contact the owner directly if:

- Your password is not working
- You think a result was settled incorrectly
- A bet you logged is not appearing in your bet log
- You want your edge threshold, bankroll, or staking method changed by
  the owner

The owner has an **Admin** page where they can see all user accounts,
reset individual bankrolls, and manage access.
