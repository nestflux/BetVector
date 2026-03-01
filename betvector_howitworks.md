# BetVector -- How It Works

A guide to the concepts and mechanics behind BetVector's quantitative football betting system.

---

## The Big Picture

Saturday morning. You scroll through the day's fixtures, feel good about Arsenal at home, and put money on them to win. By Monday, you can't remember whether you're up or down this month. You have no framework for deciding which bets are smart and which are just noise. You're betting on feel.

BetVector replaces feel with math.

It is a quantitative betting system that collects football data from public sources, predicts match outcomes using statistical models, compares those predictions to bookmaker odds, and flags situations where the bookmaker's price is wrong in your favour. These are called **value bets** -- situations where the expected return is positive.

The philosophy is simple: you don't need to predict who will win. You need to find prices that are wrong. If you bet on enough mispriced outcomes, the math works in your favour over hundreds of bets. Individual bets lose all the time. That's fine. The system is designed to profit in aggregate.

BetVector handles the entire chain: data collection, feature engineering, prediction, value detection, stake calculation, bet tracking, result resolution, performance measurement, and self-improvement. You review the picks, place the ones you choose on your sportsbook, and track everything on a dashboard.

---

## Understanding Betting Odds

Before anything else, you need to understand how odds work -- not as a bettor, but as a mathematician.

### Decimal Odds

BetVector uses **decimal odds**, the standard in European betting. Decimal odds tell you the total return per unit staked, including your stake back.

| Decimal Odds | You Bet | You Get Back (if you win) | Profit |
|:---:|:---:|:---:|:---:|
| 1.50 | 10.00 | 15.00 | 5.00 |
| 2.00 | 10.00 | 20.00 | 10.00 |
| 3.50 | 10.00 | 35.00 | 25.00 |

Higher odds mean a bigger payout but a less likely outcome (according to the bookmaker).

### Implied Probability

Every set of odds can be converted into a probability -- the bookmaker's estimate of how likely that outcome is.

```
implied_probability = 1 / decimal_odds
```

Examples:

| Decimal Odds | Implied Probability |
|:---:|:---:|
| 1.50 | 1 / 1.50 = 66.7% |
| 2.00 | 1 / 2.00 = 50.0% |
| 3.50 | 1 / 3.50 = 28.6% |

If a bookmaker offers Arsenal at 2.00, they're saying Arsenal has roughly a 50% chance of winning.

### The Bookmaker's Margin (Overround)

Here is the catch. Bookmakers don't offer fair odds. For a match result market (home / draw / away), add up the implied probabilities:

```
Arsenal to win:    odds 1.90  ->  implied = 52.6%
Draw:              odds 3.40  ->  implied = 29.4%
Chelsea to win:    odds 4.00  ->  implied = 25.0%
                                  Total   = 107.0%
```

The total is 107%, not 100%. That extra 7% is the **overround** (also called the **vig** or **vigorish**). It's the bookmaker's built-in profit margin. No matter what happens, the bookmaker collects slightly more from losing bets than they pay out on winning ones.

This means the implied probabilities from odds are always inflated. The "true" fair probabilities for the match above would sum to 100%, so each outcome's real probability is slightly lower than the odds suggest. The bookmaker is systematically offering you worse prices than fair value.

This is why most bettors lose. Even if your predictions are as good as the bookmaker's, the overround ensures you lose money over time. To profit, you need to be *better* than the bookmaker -- at least some of the time.

---

## How BetVector Predicts Match Outcomes

### The Poisson Distribution

Goals in football are rare, roughly random events. A typical team scores 1 to 2 goals per match, and the exact number in any given game is unpredictable. This makes football goals a textbook application of the **Poisson distribution** -- a statistical model designed for exactly this type of event: counting occurrences of something that happens at a known average rate.

The Poisson distribution takes a single parameter called **lambda** -- the average expected number of events. If lambda = 1.5 for Arsenal's attack, the Poisson distribution tells us:

```
P(0 goals) = 22.3%
P(1 goal)  = 33.5%
P(2 goals) = 25.1%
P(3 goals) = 12.6%
P(4 goals) =  4.7%
P(5 goals) =  1.4%
P(6 goals) =  0.4%
```

Most of the probability mass sits at 1-2 goals, with a long tail of less likely scorelines. This matches what we actually observe in football.

### Attack Strength, Defence Strength, and Home Advantage

BetVector estimates two lambda values for every match:

- **lambda_home** -- how many goals the home team is expected to score
- **lambda_away** -- how many goals the away team is expected to score

These are calculated from **rolling features** -- statistics computed over each team's recent matches:

| Feature | What It Measures |
|---|---|
| `goals_scored_5` | Average goals scored per game over last 5 matches |
| `goals_conceded_5` | Average goals conceded per game over last 5 matches |
| `xg_5` | Average expected goals (xG) over last 5 matches |
| `xga_5` | Average expected goals against over last 5 matches |
| `shots_on_target_5` | Average shots on target over last 5 matches |
| `form_5` | Points per game over last 5 matches |

The model uses Poisson regression (a type of generalised linear model, or GLM) to learn the relationship between these features and actual goals scored. In essence, it learns patterns like: "a team averaging 2.1 xG over their last 5 home matches, facing a team conceding 1.6 xGA away, tends to score around 1.8 goals."

**Home advantage** is real and significant. Across European football, home teams score roughly 0.3 more goals per match on average than away teams. The model learns this from the data -- home and away features are calculated separately, and the regression captures the home boost naturally.

### From Lambda Values to the Scoreline Matrix

Once we have lambda_home and lambda_away, we build a **scoreline probability matrix**: a 7x7 grid showing the probability of every possible scoreline from 0-0 to 6-6.

Each cell is calculated as:

```
P(home = h, away = a) = poisson.pmf(h, lambda_home) * poisson.pmf(a, lambda_away)
```

Here is a concrete example. Suppose for Arsenal vs Chelsea:

```
lambda_home (Arsenal) = 1.72
lambda_away (Chelsea) = 1.14
```

The scoreline matrix looks like this (probabilities as percentages):

```
         Chelsea goals
           0      1      2      3      4      5      6
    0    5.73   6.53   3.72   1.42   0.40   0.09   0.02
    1    9.85  11.23   6.40   2.44   0.70   0.16   0.03
A   2    8.47   9.66   5.50   2.10   0.60   0.14   0.03
r   3    4.86   5.54   3.16   1.20   0.34   0.08   0.01
s   4    2.09   2.38   1.36   0.52   0.15   0.03   0.01
e   5    0.72   0.82   0.47   0.18   0.05   0.01   0.00
n   6    0.21   0.24   0.13   0.05   0.01   0.00   0.00
```

The most likely scoreline is 1-1 (11.23%), followed by 1-0 (9.85%) and 2-1 (9.66%). This feels right -- a moderately high-scoring match with Arsenal slightly favoured.

**The independence assumption.** You'll notice we multiply the home and away Poisson probabilities together. This assumes Arsenal scoring 2 goals and Chelsea scoring 1 goal are independent events. In reality, there is a weak correlation (a team chasing a deficit may score more but also concede more), but the independence assumption works well in practice for match-level predictions and keeps the model simple and interpretable.

The matrix is truncated at 6 goals per side (because 7+ goal hauls are vanishingly rare) and renormalised so all 49 cells sum to exactly 1.0.

### Deriving Market Probabilities from the Matrix

This is where the architecture becomes elegant. From a single scoreline matrix, BetVector derives probabilities for *every* betting market by summing the appropriate cells:

**1X2 (Match Result)**

```
P(home win) = sum of all cells where home > away     = 48.2%
P(draw)     = sum of all cells where home == away     = 24.8%
P(away win) = sum of all cells where away > home      = 27.0%
```

**Over/Under 2.5 Goals**

```
P(over 2.5)  = sum of all cells where home + away > 2  = 53.1%
P(under 2.5) = sum of all cells where home + away <= 2 = 46.9%
```

**Both Teams to Score (BTTS)**

```
P(BTTS yes) = sum of all cells where home > 0 AND away > 0 = 64.8%
P(BTTS no)  = sum of all cells where home == 0 OR away == 0 = 35.2%
```

**Over/Under 1.5, 3.5, Asian Handicap** -- all derived from the same matrix using the same logic with different cell-summing rules.

One model, one matrix, all markets. This is the core architectural insight of BetVector. When a more advanced model (Elo, XGBoost, neural net) is added later, it just produces its own scoreline matrix. Everything downstream stays the same.

---

## Finding Value Bets

### What Makes a Bet "Value"

A value bet is not about who you think will win. It's about finding prices that are wrong.

Suppose BetVector's model estimates Arsenal has a 55% chance of beating Chelsea, but the bookmaker is offering odds of 2.10 (which implies only a 47.6% chance). The bookmaker thinks Arsenal is less likely to win than our model does. If our model is right, the bookmaker's price is too generous -- and we should bet on it.

```
Model probability:    55.0%
Implied probability:  1 / 2.10 = 47.6%
Edge:                 55.0% - 47.6% = 7.4%
```

The **edge** is the gap between what we think is true and what the bookmaker's price implies. A positive edge means the bet has **positive expected value** (+EV).

### Expected Value

Expected value (EV) tells you how much you expect to profit per unit staked over the long run:

```
EV = (probability * decimal_odds) - 1
   = (0.55 * 2.10) - 1
   = 1.155 - 1
   = +0.155  (or +15.5%)
```

This means that for every 1.00 you bet in this situation, you expect to profit 0.155 in the long run. Not on every individual bet -- on *average*, across many similar bets.

### Why You Should Bet on Value, Not on Winners

This is the hardest mental shift for new bettors. Consider two scenarios:

**Scenario A:** You bet on Manchester City at 1.20 odds (83.3% implied). Your model says they have an 82% chance of winning. City wins. You made money. But the bet was -EV: you needed 83.3% to break even and only had 82%. Over hundreds of these bets, you lose money despite most of them winning.

**Scenario B:** You bet on Nottingham Forest at 4.50 odds (22.2% implied). Your model says they have a 28% chance of winning. Forest loses. You lost money on this bet. But it was +EV: you needed only 22.2% to break even and had 28%. Over hundreds of these bets, you profit despite most of them losing.

The second bettor is the profitable one. Value betting means accepting that most of your bets on underdogs will lose, while trusting that the math works over a large enough sample. This is the **law of large numbers** at work -- the more bets you place, the closer your actual returns converge to the expected value.

### Confidence Tiers

BetVector categorises each value bet by the size of the edge:

| Tier | Edge | Interpretation |
|---|:---:|---|
| **High** | >= 10% | Substantial mispricing by the bookmaker |
| **Medium** | 5% to 10% | Clear value, standard betting range |
| **Low** | < 5% | Marginal value, may not survive the overround |

The default minimum edge threshold is 5%. You can adjust this in the dashboard settings. A higher threshold means fewer but stronger picks; a lower threshold means more picks but smaller edges.

---

## Managing Your Bankroll

### Why Bankroll Management Matters More Than Predictions

This is counterintuitive but critical: **bankroll management is more important than the quality of your model.** A good model with reckless staking goes broke. A mediocre model with disciplined staking survives losing streaks and compounds gains.

The reason is variance. Even with a genuine 5% edge, you will have losing weeks, losing fortnights, sometimes losing months. If your stake sizes are too large relative to your bankroll, a normal run of bad luck can wipe you out before the edge has time to materialise.

BetVector supports three staking methods, from simplest to most advanced.

### Flat Staking (Recommended for Beginners)

Bet a fixed percentage of your starting bankroll on every qualifying bet.

```
stake = starting_bankroll * stake_percentage
```

Example with a 1,000 bankroll and 2% stakes:

```
stake = 1,000 * 0.02 = 20 per bet
```

Every bet is 20, regardless of how the bankroll changes. Simple, predictable, and conservative. This is the default and recommended method because it requires no additional calculations and limits your exposure naturally.

### Percentage Staking

Same formula as flat staking, but recalculated against your *current* bankroll after each bet.

```
stake = current_bankroll * stake_percentage
```

If your bankroll grows to 1,200:

```
stake = 1,200 * 0.02 = 24 per bet
```

If it drops to 800:

```
stake = 800 * 0.02 = 16 per bet
```

This has a natural self-correcting property: when you're winning, stakes grow and you compound faster. When you're losing, stakes shrink and you bleed more slowly. It makes it mathematically impossible to reach zero (since you're always betting a percentage of what remains).

### The Kelly Criterion

The Kelly Criterion is a formula from information theory that calculates the mathematically optimal bet size to maximise the long-term growth rate of your bankroll. It is elegant, powerful, and dangerous if misused.

The formula:

```
f* = (p * b - 1) / (b - 1)
```

Where:
- `f*` = fraction of bankroll to bet
- `p` = true probability of winning (our model's estimate)
- `b` = decimal odds offered by the bookmaker

**Worked example:**

```
Model says: 60% chance of Arsenal winning (p = 0.60)
Bookmaker offers: decimal odds of 2.10 (b = 2.10)

f* = (0.60 * 2.10 - 1) / (2.10 - 1)
   = (1.26 - 1) / 1.10
   = 0.26 / 1.10
   = 0.2364  (23.64% of bankroll)
```

Full Kelly says bet 23.64% of your bankroll on this single match. That is extremely aggressive. If your probability estimate is even slightly wrong -- say the true probability is 52% instead of 60% -- you're massively over-staking and headed for ruin.

BetVector uses **fractional Kelly**, specifically **quarter-Kelly** (kelly_fraction = 0.25):

```
stake = f* * kelly_fraction * current_bankroll
      = 0.2364 * 0.25 * 1,000
      = 59.10
```

Quarter-Kelly sacrifices some theoretical growth rate for dramatically reduced risk of ruin. It is only recommended after 500+ bets with confirmed good calibration, because Kelly's optimality depends entirely on the accuracy of your probability estimates.

When the expected value is negative (model_prob * odds < 1), the Kelly formula returns a negative number, meaning "don't bet." BetVector returns a stake of zero in this case.

### Safety Limits

Regardless of staking method, BetVector enforces four hard safety limits:

| Limit | Threshold | What Happens |
|---|:---:|---|
| **Max bet cap** | 5% of current bankroll | No single bet can exceed this, even if Kelly says otherwise |
| **Daily loss limit** | 10% of starting bankroll | If total daily losses exceed this, stop betting for the day |
| **Drawdown alert** | 25% below peak bankroll | Warning flag on the dashboard (betting still allowed) |
| **Minimum bankroll** | 50% of starting bankroll | Auto-switch to paper trading until bankroll recovers |

These limits exist because models are not perfect, bad luck is real, and the worst time to bet big is when you're already losing. The minimum bankroll limit is especially important -- it forces you to stop risking real money when something may be fundamentally wrong.

---

## The Three Daily Pipelines

BetVector runs three automated pipelines per day, each at a specific time and with a specific purpose.

### Morning (06:00 UTC) -- Preparing Today's Picks

This is the main pipeline. It runs the full chain:

```
1. Scrape latest match data and odds from all sources
2. Load scraped data into the database
3. Compute rolling features for all teams
4. Run the prediction model on today's fixtures
5. Compare model probabilities to bookmaker odds
6. Flag value bets that exceed the edge threshold
7. Log all value bets as system picks in the database
```

By 07:00, the morning picks email lands in your inbox with today's value bets, each annotated with the model's probability, the bookmaker's implied probability, the edge, and the recommended stake.

### Midday (13:00 UTC) -- Catching Odds Movements

Odds are not static. As bettors place money throughout the day, bookmakers adjust their prices. A value bet at 06:00 might no longer be value by 13:00 -- or a new one might have appeared.

```
1. Re-fetch current odds from API-Football
2. Recalculate edges against existing predictions
3. Update the value_bets table with current odds and edges
```

The dashboard shows both the original odds (at prediction time) and the current odds, with a warning if the edge has eroded below your threshold.

### Evening (22:00 UTC) -- Settling the Books

After the day's matches are played:

```
1. Scrape match results
2. Resolve pending bets (pending -> won / lost / void)
3. Calculate daily profit and loss
4. Update bankroll balances
5. Generate updated performance metrics
6. Run recalibration checks
7. Check retrain triggers
```

### Pipeline Resilience

Each step in each pipeline is wrapped in its own error handling. If FBref is blocked by Cloudflare (which happens), the pipeline logs the error and continues with the data it has. If odds scraping times out, predictions still run using the last available odds. If the email server is down, results are still recorded in the database.

A single failure never blocks the entire pipeline. This is critical for a system that runs unattended on a schedule.

---

## Walk-Forward Backtesting

### What It Is and Why It Matters

Before risking real money, you want to know: does this model actually work? Backtesting answers that question by running the model on historical data and measuring its performance.

But backtesting in sports prediction is treacherous. The most common mistake is **data leakage** -- accidentally using future information to make past predictions. If your model trains on the full season's data and then "predicts" individual matches from that same season, it will look amazing. But it is cheating. Those results are meaningless.

### How BetVector Prevents Data Leakage

BetVector uses **walk-forward validation**, the only honest backtesting approach for time-series data. It works like this:

```
Matchday 1:
  Train on: pre-season data only
  Predict:  matchday 1 fixtures
  Record:   predictions, value bets, simulated P&L

Matchday 2:
  Train on: pre-season + matchday 1 results
  Predict:  matchday 2 fixtures
  Record:   predictions, value bets, simulated P&L

Matchday 3:
  Train on: pre-season + matchdays 1-2 results
  Predict:  matchday 3 fixtures
  Record:   predictions, value bets, simulated P&L

... continue through the entire season
```

At every step, the model sees only data from before the prediction date. This is exactly how it would operate in real life. The model learns and improves as the season progresses and more data becomes available.

Early-season predictions (matchdays 1-5) will be noisy because the model has very little training data. This is realistic -- you would face the same uncertainty at the start of a real season.

### Reading Backtest Results

A backtest produces several outputs:

- **ROI over time**: A line chart showing cumulative return. You want this trending upward, though expect drawdowns along the way.
- **Brier score by matchday**: How calibrated the model's probabilities were at each point in the season.
- **Total bets, win rate, P&L**: The headline numbers.
- **Per-market breakdown**: Which markets (1X2, Over/Under, BTTS) the model finds value in most consistently.

A backtest ROI of +3% to +8% over a full season is a strong result. The Poisson model alone, without advanced features like xG (when FBref data is unavailable), typically produces a baseline ROI in the range of -5% to +5%, which is competitive given that most bettors lose 5-10% to the overround.

---

## The Self-Improvement Engine

A static model degrades over time. Teams change, leagues evolve, and the bookmaker market adapts. BetVector includes a self-improvement engine that keeps the system calibrated and honest.

### Automatic Recalibration

**Platt scaling** and **isotonic regression** are techniques that adjust a model's raw probabilities to better match observed outcomes. If the model consistently says "60% chance" but those bets only win 52% of the time, recalibration learns this bias and adjusts future probabilities downward.

Recalibration runs automatically during the evening pipeline, but only when there is a sufficient sample size (minimum number of predictions to avoid overfitting to noise).

### Retrain Triggers

The model monitors its own performance using a rolling Brier score. If the rolling Brier score degrades by 15% or more compared to the all-time average, the system triggers a retrain -- rebuilding the model from scratch using the most recent data.

This catches situations where something fundamental has changed (e.g., a major transfer window reshuffles multiple squads) and the old model's parameters no longer reflect reality.

### Market Feedback Loop

Not all leagues and markets are equal. BetVector tracks ROI per league and per market type. If the model consistently finds value in EPL Over/Under 2.5 but loses money on Serie A BTTS, the system can down-weight or disable underperforming market-league combinations.

### Why Guardrails Matter

Every automatic adjustment has three safety mechanisms:

1. **Minimum sample size** -- no adjustment is made until enough data has been collected to draw meaningful conclusions.
2. **Maximum change rate** -- no single recalibration step can shift probabilities by more than a capped amount, preventing wild overcorrections.
3. **Rollback mechanism** -- if an adjustment makes performance worse over the next evaluation window, it is automatically reversed.

An overconfident self-improvement system that "learns" from noise is worse than no self-improvement at all. The guardrails ensure changes are gradual, evidence-based, and reversible.

---

## Understanding the Dashboard

BetVector's dashboard is a Streamlit web application with a dark-theme trading terminal aesthetic. It runs on your phone's browser or laptop and is organised into seven pages.

### Today's Picks -- Your Daily Action Items

The landing page on match days. Shows all value bets for today, sorted by edge size. Each pick displays:

- The match and league
- The market (1X2, Over/Under, BTTS)
- BetVector's probability vs. the bookmaker's implied probability
- The edge and confidence tier (high / medium / low)
- The recommended stake based on your chosen staking method

You can mark bets as placed (with the actual odds and stake you got), and the system tracks your real bets alongside the model's system picks.

When there are no value bets, the page shows a reassuring empty state: the absence of value is itself useful information.

### Performance -- Tracking Long-Term Profitability

Your P&L over time, displayed as an interactive line chart. Includes:

- Cumulative ROI
- Daily, weekly, and monthly P&L breakdowns
- Win rate across all markets
- Brier score trend (is the model getting more or less accurate?)
- Performance comparison: system picks vs. your actually placed bets

The critical insight here: short-term results are dominated by variance. A losing week means nothing. Look at the 100-bet and 500-bet rolling averages.

### Leagues -- Per-League Breakdown

Shows performance metrics broken down by league. Useful for identifying which leagues the model handles well and which it struggles with. Each league shows standings, upcoming fixtures, and the model's historical accuracy.

### Match Deep Dive -- Under the Hood of a Prediction

Click any match to see the full prediction breakdown:

- The 7x7 scoreline probability matrix as a colour-coded heatmap
- Derived market probabilities for all supported markets
- Both teams' rolling form over the last 5 and 10 matches
- Head-to-head record from recent meetings
- Feature values that went into the prediction

This page is where you learn to think like a quantitative bettor. Instead of "Arsenal should win because they're playing at home," you see the specific numbers: Arsenal's rolling xG, Chelsea's away defence, the home advantage boost, and how all of that translates into a 48.2% win probability.

### Model Health -- Keeping the System Honest

The model health page answers: "Can I trust this model?"

- **Calibration curve**: A plot of predicted probability vs. actual win rate, bucketed. If the model says "60% chance" and those events happen 60% of the time, the points sit on the diagonal. Deviations reveal systematic biases.
- **Rolling Brier score**: Tracks prediction accuracy over time. A rising Brier score means the model is getting worse.
- **Prediction volume**: How many predictions and value bets the model is generating. A sudden drop might indicate a data source outage.

### Bankroll Manager -- Protecting Your Capital

Your current bankroll, historical balance chart, and safety limit status:

- Current balance and change from starting bankroll
- Drawdown from peak (with alert if above 25%)
- Daily loss limit status (how much runway remains today)
- Staking method indicator and recent bet sizes

### Settings -- Configuration

- Staking method selector (flat / percentage / Kelly)
- Edge threshold slider (1% to 15%)
- Active leagues
- Paper trading toggle (simulate bets without risking real money)
- Notification preferences

---

## Key Metrics Explained

### ROI (Return on Investment)

The simplest question: am I making money?

```
ROI = (total_profit / total_staked) * 100
```

Example: You've staked a total of 2,000 across 100 bets and your profit is 80.

```
ROI = (80 / 2,000) * 100 = 4.0%
```

For context, professional sports bettors target 2-5% long-term ROI. Anything above 0% means you're beating the bookmaker. ROI is volatile in small samples -- you need 500+ bets before it stabilises into something meaningful.

### Brier Score

How accurate are the probability estimates themselves, regardless of whether you bet on them?

```
Brier score = mean of (predicted_probability - actual_outcome)^2
```

For a single prediction: if you said "70% chance of Arsenal winning" and Arsenal won (outcome = 1):

```
(0.70 - 1)^2 = 0.09
```

If Arsenal lost (outcome = 0):

```
(0.70 - 0)^2 = 0.49
```

Averaged across all predictions:
- **0.0** = perfect (never achievable in football)
- **0.25** = useless (equivalent to predicting 50/50 on everything)
- **Below 0.20** for match results is good -- football is inherently random, and even perfect models can't eliminate that randomness

Lower is better. The Brier score rewards both accuracy and calibration -- you get a good score by being both right and appropriately confident.

### Calibration

When BetVector says "60% chance," does that outcome happen 60% of the time?

Calibration is checked by grouping all predictions into probability buckets (e.g., 50-55%, 55-60%, 60-65%) and comparing the average predicted probability to the actual win rate within each bucket.

```
Bucket 50-55%: average prediction = 52.3%, actual win rate = 51.8%  (well calibrated)
Bucket 60-65%: average prediction = 62.1%, actual win rate = 55.0%  (overconfident)
Bucket 70-75%: average prediction = 72.0%, actual win rate = 73.5%  (slightly underconfident)
```

Perfect calibration means all points sit on the diagonal of a calibration plot (predicted = actual). **Overconfident** models predict higher probabilities than reality delivers. **Underconfident** models predict lower. The recalibration engine fixes systematic biases over time.

### CLV (Closing Line Value)

The single best predictor of long-term betting profitability.

The **closing line** is the final set of odds offered just before a match kicks off. It represents the market's most informed estimate, incorporating all available information and betting volume. If you consistently get better odds than the closing line, you are extracting value from the market.

```
CLV = (closing_implied_probability - your_implied_probability) / your_implied_probability
```

Example: You bet Arsenal at 2.10 (47.6% implied). The closing odds move to 1.90 (52.6% implied).

```
CLV = (52.6% - 47.6%) / 47.6% = +10.5%
```

Positive average CLV across many bets is strong evidence that you have a genuine edge -- regardless of short-term P&L fluctuations.

---

## Data Sources and Limitations

### Where the Data Comes From

BetVector uses three free public data sources:

| Source | Data | Update Frequency |
|---|---|---|
| **Football-Data.co.uk** | Historical match results, bookmaker odds (20+ seasons, 50+ bookmakers) | Weekly |
| **FBref** (via soccerdata) | Expected goals (xG), shots, possession, pass completion | After each matchday |
| **API-Football** (RapidAPI free tier) | Live fixtures, upcoming match odds, results | 2-3 times daily |

### What Happens When FBref Is Blocked

FBref uses Cloudflare protection that occasionally blocks automated scrapers with a 403 error. When this happens:

- The scraper logs the error and continues
- Features that depend on FBref data (xG, shots, possession) are set to null
- The prediction model still runs using goals-based and form-based features
- Predictions will be somewhat less accurate without xG, but still functional

This is by design. The pipeline never crashes because of a single data source outage.

### API Rate Limits

API-Football's free tier allows 100 requests per day. BetVector tracks API usage and respects this limit. All HTTP requests to any source include a minimum 2-second delay between consecutive calls to avoid overwhelming free public services.

### EPL-Only (For Now) and How to Expand

The MVP covers the English Premier League. Adding a new league requires only a configuration entry in `config/leagues.yaml` -- no code changes. The scraping, feature engineering, prediction, and value detection pipelines are all league-agnostic by design. Future expansions to La Liga, Serie A, Bundesliga, and smaller value leagues (where bookmaker inefficiencies tend to be larger) require only config updates and data availability.

---

## Glossary

| Term | Definition |
|---|---|
| **Brier score** | A measure of prediction accuracy. The mean squared difference between predicted probabilities and actual outcomes. Range 0 (perfect) to 1 (worst). Lower is better. |
| **Calibration** | How well predicted probabilities match observed frequencies. A calibrated model's 60% predictions happen 60% of the time. |
| **CLV (Closing Line Value)** | The difference between the odds you bet at and the final closing odds. Positive CLV indicates you're beating the market. |
| **Drawdown** | The percentage decline from your bankroll's all-time peak to its current value. A measure of how deep your current losing streak runs. |
| **Edge** | The difference between your model's probability and the bookmaker's implied probability. Positive edge = potential value bet. |
| **EV (Expected Value)** | The average profit or loss per unit staked over the long run. Positive EV (+EV) means the bet is profitable on average. |
| **Implied probability** | The probability embedded in a set of odds: `1 / decimal_odds`. What the bookmaker believes (or prices) the likelihood to be. |
| **Kelly Criterion** | A formula that calculates the optimal bet size to maximise long-term bankroll growth: `f* = (p*b - 1) / (b - 1)`. |
| **Lambda** | The expected number of goals for a team in a match. The key parameter of the Poisson distribution used in BetVector's model. |
| **Overround (vig)** | The bookmaker's built-in profit margin. The amount by which implied probabilities across all outcomes exceed 100%. |
| **Paper trading** | Simulating bets without risking real money. Used to evaluate model performance before committing capital. |
| **Poisson distribution** | A probability distribution that models the number of times a rare event occurs in a fixed interval. Used to model goals scored in football. |
| **Scoreline matrix** | A 7x7 grid of probabilities for every possible match scoreline (0-0 through 6-6). BetVector's universal model output from which all market probabilities are derived. |
| **Walk-forward validation** | A backtesting method that trains only on past data and predicts the next time step, then advances. Prevents data leakage by never using future information. |
| **xG (Expected Goals)** | A statistical measure of the quality of scoring chances created, based on factors like shot location, angle, and assist type. More predictive of future performance than actual goals scored. |
