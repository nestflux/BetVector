# BetVector -- How It Works

A plain-English guide to understanding how a quantitative football betting system
thinks, learns, and protects your money.

If you know football but not statistics, this document is for you.

---

## 1. The Big Picture

### What BetVector Does in Plain English

Saturday morning. You open your phone, scroll through the day's football fixtures,
and place a bet on Arsenal because they have been playing well and it "feels right."
By Monday you cannot remember if you are up or down this month. You have a vague
sense it is negative, but no real data. You place another bet next weekend using the
same process: gut feeling, tribal knowledge, hope.

This is how the vast majority of football bettors operate. No systematic edge.
No data. No staking discipline. No performance tracking. They are, in effect,
donating money to bookmakers who employ teams of quantitative analysts, proprietary
data pipelines, and decades of model refinement.

BetVector exists to put the data on your side.

It is a Python-based system that:
1. **Scrapes football data** from free public sources (match results, team statistics, bookmaker odds).
2. **Engineers features** -- numerical representations of team form, attack strength, defensive quality, home advantage, and other factors.
3. **Builds a Poisson regression model** that predicts how many goals each team will score.
4. **Constructs a 7x7 scoreline probability matrix** covering every possible result from 0-0 to 6-6.
5. **Derives betting market probabilities** (match result, over/under, both teams to score) from that single matrix.
6. **Detects value bets** by comparing model probabilities to bookmaker odds.
7. **Manages bankroll** with disciplined staking strategies and hard safety limits.
8. **Tracks every bet** (both system recommendations and user-placed bets) with full performance metrics.
9. **Self-improves over time** through automatic recalibration, market feedback, and retrain triggers.

The entire system runs automatically on a daily schedule. You check your email
each morning, review the value bets on the dashboard, place the ones you choose
on your sportsbook, and the system handles everything else.

### The Core Idea: Finding Mispriced Bets

Here is the single most important concept behind everything BetVector does:

**A bet has "value" when the bookmaker's odds imply a lower probability than
what the model calculates.**

This does not mean the bet will win. It means that if you make this type of bet
over and over -- hundreds of times -- you will come out ahead, because you are
consistently getting better prices than the true probability warrants.

Think of it like a shop that accidentally prices an item at half its market value.
Buying it is a good deal regardless of whether you end up liking the product. In
betting terms, the "discount" is the gap between what the model thinks is the true
probability and what the bookmaker's price implies.

### Edge -- The System's Estimate of Your Advantage

That gap has a name: **edge**.

```
Edge = Model Probability - Bookmaker's Implied Probability
```

**Example:** BetVector's model says Manchester City has a 75% chance of beating a
struggling Wolves side at the Etihad. The bookmaker offers decimal odds of 1.54
on a Man City win. Those odds imply a probability of 1 / 1.54 = 64.9%. The edge
is 75.0% - 64.9% = **10.1%**.

The model is saying: "This bet is priced as if Man City have a 65% chance, but I
think they have a 75% chance. That 10% gap is your advantage."

Over a single bet, anything can happen. Wolves might score a screamer and win 1-0.
But over 200 bets with a consistent 10% edge, the mathematics of probability are
firmly on your side. This is exactly how casinos make money -- they do not win
every hand of blackjack, but the house edge guarantees they profit over thousands
of hands.

### What BetVector Is Not

BetVector is not a "tip sheet." It does not tell you who will win. It tells you
where the bookmaker's price is wrong. A bet can be a losing bet and still be a
good bet -- if the odds offered were generous enough relative to the true
probability. This distinction between outcome and process is the foundation of
disciplined betting.

It is not a gambling app. It is not a guaranteed money-maker. It is a quantitative
tool for making informed, disciplined betting decisions backed by data -- with full
transparency about when the edge is real and when it is not.

---

## 2. Where the Data Comes From

Every prediction starts with data. BetVector pulls from three sources, each
providing different pieces of the puzzle.

### Football-Data.co.uk

This is the bedrock data source -- a free, public repository of football match
results and bookmaker odds, maintained as downloadable CSV files. It has been
running for over two decades and covers all the major European leagues.

**What it provides:**

- **Final scores:** Home goals, away goals, half-time scores.
- **Match statistics:** Shots, shots on target, corners, fouls, yellow and red cards.
- **Bookmaker odds:** Odds from dozens of bookmakers including Bet365, Pinnacle, William Hill, and many more.
- **Market average odds:** The average across all bookmakers, which serves as a useful benchmark for fair prices.

This is the data that tells BetVector what happened in every match and what price
the bookmakers offered. Without it, there is no training data for the model and no
odds to compare against.

**Why it matters:** Historical odds data is gold. It lets BetVector backtest
strategies on past seasons -- asking "if the system had been running last year,
would it have made money?" -- which is essential for validating the model before
risking real money.

### FBref (via soccerdata)

FBref is the gold standard for advanced football statistics. While Football-Data
gives you goals and shots, FBref gives you the numbers behind the numbers.

**What it provides:**

- **Expected Goals (xG):** A measure of shot quality. When a player shoots from
  6 yards out after a cutback, that shot might have an xG of 0.35 (meaning it
  scores roughly 35% of the time across all football). A speculative 30-yard
  effort might have an xG of 0.03. A team's total xG for a match is the sum of
  all their shot probabilities.
- **Expected Goals Against (xGA):** The same concept from the defensive
  perspective -- how many goals the opposition deserved to score based on their
  chances.
- **Possession, pass completion, shots on target** and other granular
  match-level statistics.

**Why xG matters so much:** Goals in football are partly random. A team can
create five excellent chances and score none of them. Another team can have one
shot all match and score from 40 yards. Over a single match, actual goals are
noisy. xG cuts through that noise and measures the *quality* of chances created,
regardless of whether the ball went in.

xG is the single most predictive publicly available metric for future football
performance. A team that is "over-performing their xG" (scoring more goals than
their chances deserve) is likely to regress. A team that is "under-performing"
(creating great chances but not finishing them) is likely to improve. The model
captures these patterns.

**Current status:** FBref uses Cloudflare protection that periodically blocks
automated data collection with a 403 error. BetVector handles this gracefully --
when FBref is unavailable, the system continues without xG features. Goals, form,
and other features still provide a solid foundation. When FBref is accessible, xG
features are layered on top for better predictions.

### API-Football

API-Football is a REST API (accessed through RapidAPI) that provides real-time
fixture data and live odds for upcoming matches.

**What it provides:**

- **Upcoming fixtures:** Who plays whom, when, and where.
- **Current bookmaker odds** for those fixtures, updated throughout the day.
- **Lineup and injury information** when available before kickoff.

**Free tier limitations:** The free plan allows 100 API requests per day.
BetVector tracks this usage carefully and spreads requests across 2-3 daily
pipeline runs to capture odds movements without exceeding the quota. Every request
includes a minimum 2-second delay to avoid overloading the service.

### How Data Gets Into the System

The data flow follows a strict, modular pattern:

```
Scraper downloads raw data from the internet
              |
              v
Loader cleans, normalises, and deduplicates the data
              |
              v
Loader writes to the SQLite database
              |
              v
All downstream modules (features, model, value finder)
read from the database -- never directly from each other
```

This architecture is deliberate. The scraper does not hand data to the feature
engineer through a function argument. Instead, the scraper writes to the database,
and the feature engineer reads from it. This means every module is independent --
you can re-run the feature engineer without re-running the scraper, or replace
the scraper entirely without touching anything downstream.

The database is the single source of truth. If it is not in the database, it does
not exist for the system.

### Temporal Integrity -- The Sacred Rule

Every piece of data in the system is timestamped. The system never, under any
circumstances, uses data from a match that has not yet been played.

When calculating features for a Saturday fixture, BetVector uses only matches
completed before Saturday. When training the model and predicting a March 1st
match, it trains only on matches before March 1st. When backtesting a full
season, each prediction step sees only data from before that matchday.

This sounds obvious, but "future data leakage" is the most common and devastating
mistake in sports prediction systems. A model that accidentally peeks at future
results will look spectacular in testing and fail miserably in live operation.
BetVector enforces temporal integrity at every level with explicit date filters
on every database query.

---

## 3. Feature Engineering -- Teaching the Model What Matters

### What Are Features?

In everyday language, a "feature" is a piece of information you think matters for
making a prediction. In BetVector, features are numbers that describe each team's
recent performance going into a match.

Think of features like a scouting report condensed into numbers. A football scout
might say: "Arsenal have been in great form at home, scoring freely, and their
opponents have been leaky at the back." BetVector says the same thing, but with
precision:

```
home_goals_scored_5:    1.8  (Arsenal averaged 1.8 goals per game over their last 5)
home_venue_form_5:      2.4  (2.4 points per game in their last 5 home matches)
away_goals_conceded_5:  1.6  (the opponent concedes 1.6 goals per game in their last 5)
```

The prediction model takes these numbers as input and produces a goal expectation
as output. Better features lead to better predictions.

### Rolling Averages

The most important features in BetVector are **rolling averages** -- statistics
calculated over a team's most recent N completed matches.

BetVector uses two default windows:
- **5-match window:** Captures very recent form. If a team has won their last 5
  in a row, that signal comes through strongly.
- **10-match window:** Captures a slightly longer trend, smoothing out individual
  fluky results.

**Why rolling windows instead of season averages?**

Because recent form matters more than what happened four months ago. A team that
started the season poorly but has won 8 of their last 10 is a very different
proposition from a team on a 6-match losing streak whose overall season average
looks decent only because of a strong opening run.

Here is a concrete example that shows the difference:

| Metric | Season Average | Last 5 Matches | What This Tells You |
|--------|:---:|:---:|---|
| Goals scored per game | 1.4 | 2.2 | Team is hitting form, attack has clicked |
| Goals conceded per game | 1.3 | 0.6 | Defence has tightened significantly |
| xG per game | 1.5 | 2.0 | Creating higher-quality chances |

The season average says "average team." The rolling averages say "team in excellent
form." The model needs the rolling averages to capture this shift.

**The full set of rolling features computed for each window:**

- **Form:** Points per game (Win = 3 points, Draw = 1, Loss = 0). A team averaging
  2.4 points per game over 5 matches has won 4 and drawn 1 -- strong form.
- **Goals scored per game:** Raw attacking output.
- **Goals conceded per game:** Raw defensive record.
- **xG per game:** Quality-adjusted attacking output (when FBref data is available).
- **xGA per game:** Quality-adjusted defensive record.
- **xG difference:** xG minus xGA per game. Positive means creating better chances
  than they are conceding. This is one of the most predictive single features in
  football analytics.
- **Shots and shots on target per game:** Volume of attacking activity.
- **Possession:** Average share of the ball.

### Context Features

Beyond rolling performance numbers, BetVector tracks contextual factors that
influence match outcomes:

**Home/away advantage:** Football has a well-documented home advantage effect.
Across the Premier League, home teams win roughly 46% of the time, draw about
27%, and lose about 27%. That is a significant tilt compared to what you would
expect by chance.

BetVector captures this through **venue-specific rolling features** -- the same
statistics described above, but calculated using only a team's home matches (when
they are at home) or only their away matches (when they are away).

A team might score 1.8 goals per game overall, but 2.3 at home and only 1.2 away.
That venue split matters enormously for predicting a specific match. The model
receives both the overall rolling average and the venue-specific one, and learns
to weight them appropriately.

**Rest days:** How many days since each team's last match. A team playing on 2
days' rest after a midweek Champions League fixture is at a measurable
disadvantage compared to a team with a full week of recovery. Research consistently
shows that fatigue affects both goalscoring output and defensive concentration.

**Head-to-head record:** The historical record between the two specific teams
over their last 5 meetings. Some matchups have consistent patterns -- a mid-table
team might regularly raise their game against a top-6 side, or a particular
tactical approach might consistently cause problems for a specific opponent.

**Season progress:** Where we are in the season, expressed as a number from 0.0
to 1.0. Early-season matches (matchdays 1-5) are harder to predict because teams
are still settling formations and integrating new signings. Late-season matches can
be distorted by teams that have already secured their league position and may not
be fully motivated.

**Matchday number:** The specific gameweek in the season (e.g., matchday 28 of 38
in the Premier League). Related to season progress but provides a more granular
signal that the model can use to identify patterns at specific points in the
campaign.

### How Features Are Stored

All features are pre-computed before each prediction and stored in the `features`
table in the database. Each row represents one team going into one specific match,
with columns for every rolling feature, venue feature, head-to-head metric, and
context variable.

The critical constraint bears repeating: features are computed using **only data
from before the match date**. If the match is on February 15th, the 5-match rolling
average uses the 5 most recent matches completed before February 15th. The match
itself is never included. A match that has not been played yet is never touched.
This temporal integrity rule is the foundation the entire system rests on.

---

## 4. The Prediction Model -- Poisson Regression

### What Is Poisson Regression?

The Poisson distribution is a mathematical tool for modelling how many times a
rare event occurs in a fixed interval. It was originally developed in the 1830s by
the French mathematician Simeon Denis Poisson. One of its earliest famous
applications was modelling the number of Prussian soldiers killed by horse kicks
per year -- a rare event occurring at a roughly constant rate in a fixed time
period.

Goals in football have the same statistical structure:

1. **They are relatively rare** -- a typical team scores 1 to 3 per match.
2. **They occur roughly independently of each other** -- one goal does not strongly
   prevent or cause the next (with some exceptions like tactical shifts after a
   goal, which are second-order effects).
3. **The rate of scoring depends on measurable factors** -- team quality, opponent
   quality, home advantage, recent form.

This makes the Poisson distribution an excellent starting point for football
prediction. It is not perfect (no model is), but it captures the essential
structure of goalscoring remarkably well.

### Understanding Lambda

The key number in a Poisson model is **lambda** (the Greek letter). Lambda is
the *expected average rate* of the event. In BetVector, lambda represents the
expected number of goals a team will score in a particular match.

Lambda is not a prediction of the exact score. A lambda of 1.5 does not mean the
team will score 1.5 goals (which is obviously impossible). It means the team is
expected to score 1.5 goals **on average**, and the actual number of goals will be
drawn from a probability distribution centred around that average.

Here is what the Poisson distribution looks like for different lambda values:

**Lambda = 1.0** (a modest attack, or a strong opposing defence):

| Goals | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Probability | 36.8% | 36.8% | 18.4% | 6.1% | 1.5% | 0.3% | 0.1% |

The most likely outcome is 0 or 1 goal. Scoring 3 or more is quite unlikely (under 8%).

**Lambda = 1.5** (a typical Premier League team in an average match):

| Goals | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Probability | 22.3% | 33.5% | 25.1% | 12.6% | 4.7% | 1.4% | 0.4% |

Most likely 1 goal, but 2 is quite possible. A clean sheet is still a 22% chance.

**Lambda = 2.5** (a strong attack against a weak defence -- e.g., Man City vs a
struggling relegation candidate at home):

| Goals | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Probability | 8.2% | 20.5% | 25.7% | 21.4% | 13.4% | 6.7% | 2.8% |

2 and 3 goals are most likely. The chance of keeping a clean sheet is under 10%.
Even 5 or 6 goals has a combined 9.5% chance.

Notice how as lambda increases, the distribution shifts right -- higher goal tallies
become more likely, and the chance of scoring zero drops sharply. This matches what
we observe in real football.

### How It Works Step by Step

BetVector trains **two separate Poisson regression models**:

**Home goals model:** Predicts how many goals the home team will score.

- **Input features:** The home team's attacking features (goals scored, xG, shots
  on target, form) and the away team's defensive features (goals conceded, xGA).
- **Logic:** "Given how well this home team has been attacking and how poorly the
  away team has been defending, how many goals should we expect?"
- **Output:** lambda_home (expected home goals).

**Away goals model:** Predicts how many goals the away team will score.

- **Input features:** The away team's attacking features and the home team's
  defensive features.
- **Logic:** The mirror image -- "Given how well the away team attacks and how
  well the home team defends, how many away goals should we expect?"
- **Output:** lambda_away (expected away goals).

The model learns by fitting to hundreds of historical matches. It sees each match's
features and actual goals, and learns the relationship: "When the home attack
features look like *this* and the away defence features look like *that*, the home
team tends to score about *this many* goals."

Under the hood, the model uses a **Generalised Linear Model (GLM)** with a **log
link function**. In simplified terms:

```
log(expected_goals) = baseline + weight1 x feature1 + weight2 x feature2 + ...
```

Which means:

```
expected_goals = exp(baseline + weight1 x feature1 + weight2 x feature2 + ...)
```

The exponential ensures the predicted goal count is always positive (you cannot
score negative goals). It also captures the multiplicative nature of attacking and
defensive quality -- a very strong attack against a very weak defence produces
more goals than you would expect from simply adding their individual effects.

### The 7x7 Scoreline Matrix -- The Heart of the System

Once we have lambda_home and lambda_away, we build the most important data
structure in the entire system: the **scoreline probability matrix**.

The matrix is a 7x7 grid covering every possible scoreline from 0-0 to 6-6. That
is 49 possible scorelines. Each cell contains the probability of that exact result
occurring.

**How each cell is calculated:**

```
P(home scores h, away scores a) = P(home scores h) x P(away scores a)
```

Using the standard Poisson probability formula:

```
P(X = k) = (lambda^k x e^(-lambda)) / k!
```

**Concrete example:** Suppose for Arsenal vs Chelsea, the model estimates:

```
lambda_home = 1.8  (Arsenal expected to score 1.8 goals)
lambda_away = 1.1  (Chelsea expected to score 1.1 goals)
```

The probability of a 2-1 Arsenal win:

```
P(home=2, away=1) = P(Arsenal scores 2) x P(Chelsea scores 1)

P(Arsenal scores 2) = (1.8^2 x e^(-1.8)) / 2! = 0.2678  (26.78%)
P(Chelsea scores 1) = (1.1^1 x e^(-1.1)) / 1! = 0.3322  (33.22%)

P(2-1) = 0.2678 x 0.3322 = 0.0890  (8.9%)
```

There is roughly an 8.9% chance of a 2-1 Arsenal win.

Here is what the complete matrix looks like with those lambda values:

```
                       Chelsea Goals
                   0      1      2      3      4      5      6
Arsenal  0      5.5%   6.0%   3.3%   1.2%   0.3%   0.1%   0.0%
Goals    1      9.8%  10.8%   6.0%   2.2%   0.6%   0.1%   0.0%
         2      8.9%   9.7%   5.4%   2.0%   0.5%   0.1%   0.0%
         3      5.3%   5.8%   3.2%   1.2%   0.3%   0.1%   0.0%
         4      2.4%   2.6%   1.5%   0.5%   0.1%   0.0%   0.0%
         5      0.9%   0.9%   0.5%   0.2%   0.1%   0.0%   0.0%
         6      0.3%   0.3%   0.2%   0.1%   0.0%   0.0%   0.0%
```

All 49 cells sum to 100%. The most likely single scoreline is 1-1 at 10.8%,
followed by 1-0 at 9.8% and 2-1 at 9.7%. This feels intuitively right for a match
where Arsenal are moderately favoured at home.

**Why the matrix is so important:** This single matrix is the universal interface
for the entire system. Every prediction model -- whether it is Poisson regression,
an Elo rating system, an XGBoost ensemble, or a neural network -- must produce a
7x7 scoreline matrix. All downstream calculations (market probabilities, value
detection, staking) derive from this one structure.

This design means you can swap out the prediction model entirely without changing
a single line of code in the value finder, bankroll manager, dashboard, or any
other component. The matrix is the contract between the model and the rest of the
system.

**The independence assumption:** You will notice that we multiply the home and away
Poisson probabilities independently:

```
P(home=h, away=a) = P(home=h) x P(away=a)
```

This assumes that the number of goals Arsenal scores is statistically independent
of the number Chelsea scores. In reality, there is a weak correlation -- a team
chasing a deficit might push forward more aggressively and both score and concede
more. A match between two cautious, defensive sides might produce fewer goals for
both.

However, this correlation is small enough in practice that the independent Poisson
model remains competitive with more complex correlation-aware models. The
independence assumption is a simplification that works well and keeps the model
interpretable. Future ensemble models can combine Poisson with models that account
for correlation, getting the best of both approaches.

The matrix is truncated at 6 goals per side because scoring 7 or more goals in a
match is vanishingly rare, and renormalised so all 49 cells sum to exactly 1.0.

### From Scoreline Matrix to Betting Markets

This is where the architecture becomes elegant. Every betting market can be derived
from the scoreline matrix by simply summing the appropriate cells. This derivation
happens in a single function: `derive_market_probabilities()`. Every market
probability in BetVector flows through this one function. It is never bypassed. It
is never duplicated. If you want to know the probability of any betting outcome,
it comes from the matrix.

**1X2 (Match Result):**

The three outcomes are home win, draw, and away win:

- **Home win:** Sum all cells where home goals > away goals (the bottom-left
  triangle of the matrix: 1-0, 2-0, 2-1, 3-0, 3-1, 3-2, ...).
- **Draw:** Sum all cells along the diagonal where home goals = away goals
  (0-0, 1-1, 2-2, 3-3, ...).
- **Away win:** Sum all cells where home goals < away goals (the upper-right
  triangle: 0-1, 0-2, 1-2, 0-3, ...).

Using our Arsenal vs Chelsea example:
```
P(Arsenal win) = sum of lower-left triangle = approximately 53.5%
P(Draw)        = sum of diagonal            = approximately 22.0%
P(Chelsea win) = sum of upper-right triangle = approximately 24.5%
```

These sum to 100%, as they must.

**Over/Under 2.5 Goals:**

- **Over 2.5:** Sum all cells where home + away >= 3 (three or more total goals).
  This includes every cell where the sum of row and column indices is 3 or more:
  2-1, 1-2, 3-0, 0-3, 2-2, and everything higher.
- **Under 2.5:** Sum all cells where home + away <= 2 (zero, one, or two total
  goals). This includes 0-0, 1-0, 0-1, 2-0, 0-2, and 1-1.

**Both Teams to Score (BTTS):**

- **BTTS Yes:** Sum all cells where *both* teams scored at least 1 goal
  (home >= 1 AND away >= 1). This is the portion of the matrix excluding the
  entire top row (where home = 0) and the entire left column (where away = 0).
- **BTTS No:** Sum all cells where at least one team scored 0 (the top row plus
  the left column, being careful not to double-count 0-0).

**Over/Under 1.5 and 3.5 Goals:**

Exactly the same logic as Over/Under 2.5, but with different thresholds:
- Over 1.5: total goals >= 2.
- Under 1.5: total goals <= 1.
- Over 3.5: total goals >= 4.
- Under 3.5: total goals <= 3.

The beauty of this approach cannot be overstated: **one model, one matrix, all
markets**. There is no separate "Over/Under model" or "BTTS model." They all come
from the same underlying prediction, ensuring consistency across markets. If the
model thinks a match will be high-scoring, that view is reflected simultaneously
in the Over/Under probabilities, the BTTS probabilities, and the match result
probabilities.

---

## 5. Value Bet Detection -- Finding the Edge

### What Makes a Bet "Value"?

A value bet exists when the bookmaker's odds imply a lower probability than what
your model estimates. You are not trying to predict who will win. You are trying to
find prices that are wrong.

Here is the analogy that makes this concept click:

**The biased coin.** Imagine a coin that lands on heads 60% of the time. Someone
offers you even-money odds (decimal 2.00, implying 50%) on heads. You should take
that bet every single time. You will not win every flip -- 40% of the time you
will lose. But over 1,000 flips, you will win roughly 600 and lose roughly 400.
At even money, that nets you about 200 units of profit from 1,000 bets.

Now imagine the same coin, but someone offers odds of 1.40 on heads (implying
71.4% probability). Even though heads is the more likely outcome, the odds are
not generous enough. You need a 71.4% win rate to break even at those odds, but
the coin only delivers 60%. This is a *bad* bet despite the outcome being more
likely to win.

The first situation has positive edge. The second has negative edge. BetVector's
entire purpose is distinguishing between these two situations across thousands of
football markets.

### How Odds Work

Bookmaker odds in BetVector are expressed in **decimal format**, the standard in
European betting.

**Converting decimal odds to implied probability:**

```
Implied probability = 1 / decimal odds
```

| Decimal Odds | Implied Probability | Interpretation |
|:---:|:---:|---|
| 1.50 | 66.7% | Heavy favourite |
| 2.00 | 50.0% | Coin flip |
| 3.00 | 33.3% | Underdog |
| 5.00 | 20.0% | Long shot |
| 10.00 | 10.0% | Very unlikely |

**Converting decimal odds to payout:**

```
Total payout = stake x decimal odds
Profit = stake x (decimal odds - 1)
```

A 20-pound bet at odds of 2.50: total payout is 50 pounds (30 profit + 20 stake
returned).

### The Overround -- The Bookmaker's Built-in Advantage

In a perfectly fair market, the implied probabilities for all outcomes should sum
to exactly 100%. But bookmakers are running a business. They shade the odds so the
probabilities sum to more than 100%.

**Example for an Arsenal vs Chelsea 1X2 market:**

| Outcome | Fair Probability | Fair Odds | Bookmaker Odds | Implied Prob |
|---|:---:|:---:|:---:|:---:|
| Arsenal win | 50.0% | 2.00 | 1.91 | 52.4% |
| Draw | 25.0% | 4.00 | 3.60 | 27.8% |
| Chelsea win | 25.0% | 4.00 | 3.60 | 27.8% |
| **Total** | **100.0%** | | | **108.0%** |

The implied probabilities sum to 108% instead of 100%. That extra 8% is the
**overround** (also called the **vig** or **vigorish** or **juice**). It is the
bookmaker's guaranteed profit margin. No matter what happens on the pitch, the
bookmaker collects more from losing bets than they pay out on winners.

This is why most bettors lose in the long run. They are not just trying to predict
football; they are trying to overcome a structural disadvantage built into every
price they see. BetVector's job is to find the specific situations where the
bookmaker has left enough room in their pricing -- despite the overround -- for a
positive expected return.

### The Edge Calculation

The edge calculation is straightforward:

```
Edge = Model Probability - Bookmaker's Implied Probability
```

**Complete worked example:**

Match: Arsenal vs Chelsea, Saturday 3pm.
BetVector prediction: Arsenal home win probability = 55.0%.
Bet365 offers Arsenal to win at 2.10.
Implied probability = 1 / 2.10 = 47.6%.
Edge = 55.0% - 47.6% = **7.4%**.

Is this a value bet? At the default 5% threshold, yes. The model estimates a 7.4%
edge, meaning the bookmaker is underpricing Arsenal by a meaningful amount.

**Expected Value (EV)** tells you the average profit per pound staked:

```
EV = (model_probability x decimal_odds) - 1.0
   = (0.55 x 2.10) - 1.0
   = 1.155 - 1.0
   = +0.155 (15.5% profit per pound staked on average)
```

For every pound you stake on bets with this profile (assuming the model is well
calibrated), you expect to make 15.5p in profit over the long run. Not on each
individual bet -- on average, across many similar bets.

**Configuring the threshold:** BetVector only flags a bet when the edge exceeds
your configured minimum threshold. The default is 5%. You can adjust this on
the Settings page:

- **Lower threshold (3%):** More bets flagged, but lower average edge quality.
  Good for accumulating sample size quickly.
- **Higher threshold (10%):** Fewer bets, but each one has a larger estimated
  edge. Higher quality, but you might go days without a pick.

### Confidence Tiers

Not all value bets are created equal. BetVector classifies each one by the size
of its edge:

**HIGH confidence (edge >= 10%):** The bookmaker has substantially mispriced this
outcome. These bets are rare but represent the system's strongest opportunities.
A 12% edge means the bookmaker thinks the outcome is roughly 12 percentage points
less likely than the model does -- a significant disagreement.

**MEDIUM confidence (5% <= edge < 10%):** Clear value, the standard betting range.
The majority of your bets will come from this tier. Edges of 5-10% are meaningful
but not dramatic. Over hundreds of bets, this is where steady profit accumulates.

Think of confidence tiers as a signal-to-noise ratio. A 3% edge might be real,
or it might be noise in the model. A 12% edge is much more likely to represent
a genuine mispricing by the bookmaker.

---

## 6. Bankroll Management -- Protecting Your Money

### Why Bankroll Management Matters

Here is a truth that most bettors learn the hard way: **you can have a genuine
edge and still go broke.**

Imagine you have a real edge on every bet. Your model is perfectly calibrated.
But you bet 50% of your bankroll on each bet. After just two consecutive losses
(which will happen -- even a 70% winner loses two in a row regularly), your
bankroll has dropped to 25% of its starting value. After four losses in a row
(rare but inevitable over hundreds of bets), you are at 6.25%. Your edge is real,
but your bankroll is destroyed before the mathematics had time to work.

This is the fundamental tension in betting: you need to bet big enough to grow
your bankroll meaningfully, but small enough to survive the inevitable losing
streaks that variance guarantees.

**The goal of bankroll management is not to maximise the profit on any single
bet. It is to survive long enough for the edge to compound over hundreds of bets.**

### Staking Methods

BetVector supports three staking strategies, listed from simplest to most
sophisticated:

#### Flat Staking (Recommended for Beginners)

The simplest approach: bet the same percentage of your bankroll every time,
regardless of the odds or how confident the model is.

```
Stake = Current Bankroll x Stake Percentage
```

With a 1,000-pound bankroll and a 2% stake percentage:

```
Stake = 1,000 x 0.02 = 20 pounds per bet
```

Every bet is 20 pounds. Simple, predictable, and conservative. There is no
thinking required about bet sizing, which removes one more emotional decision
from the process.

**Advantages:** Dead simple. Minimal variance. Easy to track. You always know
exactly how much each bet costs.

**Disadvantages:** Does not adjust for the strength of the edge. A bet with a 12%
edge gets the same 20-pound stake as one with a 5.5% edge, even though the first
is objectively a better opportunity.

Flat staking is the default and recommended starting point. It is boring, and in
betting, boring is good.

#### Percentage Staking

Conceptually identical to flat staking, but the stake recalculates after every
bet based on your *current* bankroll rather than a fixed amount.

```
Stake = Current Bankroll x Stake Percentage
```

If your bankroll grows to 1,200 pounds after a winning streak:

```
Stake = 1,200 x 0.02 = 24 pounds per bet
```

If it drops to 800 pounds during a losing run:

```
Stake = 800 x 0.02 = 16 pounds per bet
```

This has a beautiful natural property: when you are winning and your bankroll
grows, your stakes grow with it -- compounding your gains. When you are losing
and your bankroll shrinks, your stakes shrink automatically -- protecting your
remaining capital. It makes it mathematically impossible to reach zero, since you
are always betting a percentage of what remains.

#### Kelly Criterion (Advanced)

The Kelly Criterion is a mathematical formula developed by John Kelly at Bell Labs
in 1956. It was originally used in information theory but translates perfectly to
betting. It calculates the theoretically optimal fraction of your bankroll to bet
in order to maximise the long-term growth rate.

**The formula:**

```
f* = (p x b - 1) / (b - 1)
```

Where:
- **f*** = the fraction of your bankroll to bet
- **p** = your model's probability of the outcome winning
- **b** = the decimal odds offered by the bookmaker

**Worked example:**

```
Model says: 60% chance of Arsenal winning   (p = 0.60)
Bookmaker offers: decimal odds of 2.10      (b = 2.10)

f* = (0.60 x 2.10 - 1) / (2.10 - 1)
   = (1.26 - 1) / 1.10
   = 0.26 / 1.10
   = 0.2364   (23.64% of your bankroll!)
```

Full Kelly says to bet nearly a quarter of your bankroll on this single match.
That is **extremely aggressive**. If your probability estimate is even slightly
wrong -- say the true probability is 52% instead of 60% -- you are massively
over-staking and headed for ruin.

This is why BetVector uses **fractional Kelly**, specifically **quarter-Kelly**
(kelly_fraction = 0.25):

```
Actual stake = f* x kelly_fraction x bankroll
             = 0.2364 x 0.25 x 1,000
             = 59.09 pounds
```

Quarter-Kelly gives you approximately 75% of the growth rate of full Kelly but
with a fraction of the variance. It is a much safer approach that acknowledges
the reality that probability estimates are imperfect.

**When Kelly says "don't bet":** If model_probability x odds < 1.0 (meaning the
expected value is negative), the Kelly formula returns a negative number. This is
the mathematics telling you not to bet. BetVector returns a stake of zero in this
case. It is a natural safety mechanism built into the formula.

**When to use Kelly:** Only after 500+ bets with confirmed good calibration. Kelly
is optimal *only if* your probability estimates are accurate. If the model is
poorly calibrated, Kelly will oversize bets and accelerate your losses. Start with
flat staking. Move to percentage staking when comfortable. Consider Kelly only
when you have strong evidence that the model's probabilities match reality.

### Safety Limits

Regardless of which staking method you choose, BetVector enforces four
non-negotiable safety limits:

**1. Maximum Bet Cap: 5% of bankroll**

No single bet ever exceeds 5% of your current bankroll. Even if the Kelly formula
calculates a 15% stake, the cap kicks in. This prevents any single losing bet from
doing catastrophic damage.

With a 1,000-pound bankroll: maximum single bet = 50 pounds.

**2. Daily Loss Limit: 10% of starting bankroll**

If your total losses in a single day exceed 10% of your starting bankroll, the
system stops recommending bets for the rest of the day. Bad days happen -- this
limit ensures a bad day does not spiral into a catastrophic day.

With a 1,000-pound starting bankroll: if you lose 100 pounds in one day, no more
bets until tomorrow.

**3. Drawdown Alert: 25% below peak**

If your bankroll drops 25% below its highest-ever value (the "peak"), the system
flags a visible warning on every bet. You can still bet, but the warning ensures
you are consciously aware of the situation.

If your bankroll peaked at 1,200 pounds and drops to 900 pounds, that is a 25%
drawdown. The alert fires. Drawdowns are normal even with a genuine edge --
variance causes temporary losing streaks. But awareness matters.

**4. Minimum Bankroll: 50% of starting amount**

If your bankroll drops below 50% of your starting amount, the system switches to
paper trading only. No real-money bets are recommended until the bankroll
recovers.

Started with 1,000 pounds and dropped to 499 pounds? Paper trading only. This is
the emergency brake. If your bankroll has halved, something may be wrong -- bad
model, bad luck, or a combination -- and the system forces a pause for reflection.

### Paper Trading Mode

BetVector starts in **paper trading mode** by default. This is not a limitation;
it is a feature.

In paper mode, every bet is logged exactly as if you placed it. Full tracking of
P&L, ROI, Brier score, CLV, and all other metrics. The dashboard looks identical.
The emails contain the same information. The only difference is that no real money
is at risk.

Paper trading serves three purposes:

1. **Model validation:** Does the system actually have an edge? Two to four weeks
   of paper trading with 200+ tracked bets gives you real data to evaluate before
   committing capital.
2. **Discipline training:** You learn to trust the system, understand the
   dashboard, and develop the daily routine -- all without financial stress.
3. **Emotional calibration:** You experience losing streaks in paper mode and
   learn that they are normal. This makes it much easier to stay disciplined
   during real losing streaks later.

The recommended paper trading period is 2-4 weeks with at least 200 system picks
before considering a transition to real money.

---

## 7. Performance Measurement -- How Do We Know It's Working?

A system that cannot measure its own performance is not a system -- it is hope
wearing a lab coat. BetVector tracks several metrics, each answering a different
question about the system's health.

### Brier Score

**The question:** "How accurate are the probability estimates?"

The Brier score measures the quality of probabilistic predictions. Unlike win
rate (which only cares about right or wrong), the Brier score rewards you for
being confident when right and penalises you for being confident when wrong.

**Formula:**
```
Brier Score = average of (predicted_probability - actual_outcome)^2
```

Where actual_outcome is 1 if the event happened and 0 if it did not.

**Example across three predictions:**

| Match | Model Prediction | What Happened | Squared Error |
|---|:---:|:---:|:---:|
| Arsenal home win | 70% | Won (1) | (0.70 - 1)^2 = 0.09 |
| Chelsea home win | 55% | Lost (0) | (0.55 - 0)^2 = 0.3025 |
| Liverpool home win | 80% | Won (1) | (0.80 - 1)^2 = 0.04 |

Average Brier = (0.09 + 0.3025 + 0.04) / 3 = 0.144

**How to interpret it:**

- **0.0** = perfect predictions (impossible in football due to inherent randomness).
- **0.25** = no better than predicting 50/50 on everything. This is the "coin flip"
  baseline.
- **< 0.20** = genuinely good for football 1X2 predictions. Football is inherently
  random, and breaking below 0.20 means the model is capturing real signal.
- **Professional range:** Elite sports bettors and top prediction models typically
  achieve 0.19-0.22 on 1X2 markets.

**Lower is better.** If you see the Brier score trending upward on the Model Health
dashboard, the model's predictions are degrading and may need recalibration.

**Why Brier score matters more than win rate:** Win rate is misleading. A model
that always picks the favourite will have a high win rate but terrible Brier scores
when its 85% predictions only win 60% of the time. A model that correctly
identifies 70% underdogs as having a 30% chance has a low win rate (30%) but
excellent calibration. The Brier score captures both accuracy and honesty of
probabilities.

### Calibration

**The question:** "When the model says 60%, does that actually happen 60% of the time?"

Calibration is about whether the probabilities are trustworthy at face value.
A well-calibrated model means that the numbers mean what they say.

To check calibration, predictions are grouped into probability buckets:

| Probability Bucket | Average Prediction | Actual Win Rate | Verdict |
|:---:|:---:|:---:|---|
| 50-55% | 52.5% | 51.0% | Well calibrated -- close match |
| 55-60% | 57.3% | 58.2% | Well calibrated -- very close |
| 60-65% | 62.1% | 53.0% | **Overconfident** -- model too bullish |
| 70-75% | 72.0% | 71.5% | Well calibrated -- spot on |

In the third row, the model says these outcomes have about a 62% chance, but they
only happen 53% of the time. The model is **overconfident** in this probability
range.

On a calibration plot, perfect calibration falls on the diagonal line (where
predicted probability = actual frequency). Points **above** the diagonal mean the
model is underconfident -- these outcomes happen more often than predicted, which
is actually advantageous for value betting. Points **below** the diagonal mean
the model is overconfident -- it is overestimating edges and may be flagging bets
that are not actually valuable.

BetVector's Model Health page shows this calibration curve so you can see at a
glance whether the probabilities are trustworthy.

### ROI (Return on Investment)

**The question:** "Am I making money?"

```
ROI = (Total Profit or Loss / Total Amount Staked) x 100%
```

**Example:** You have staked 2,000 pounds total across 100 bets and your net
profit is 80 pounds.

```
ROI = (80 / 2,000) x 100% = 4.0%
```

- **Positive ROI** = making money. Your edge is working.
- **Negative ROI** = losing money. The model may not have a real edge, or variance
  has not been overcome yet.
- **Professional target:** 2-5% long-term ROI is considered excellent in sports
  betting. Most professional syndicates would be delighted with 3%.

**The variance warning:** ROI is extremely noisy over small samples. Over 50 bets,
you might be at +15% ROI purely from luck, or at -10% despite having a genuine
edge. Think of it like a coin that is biased 52/48 -- you need thousands of flips
for the bias to become statistically visible. In betting, you need 500+ bets for
ROI to stabilise into a meaningful signal.

Do not draw conclusions from 50 bets. Do not celebrate after 100 winning bets or
panic after 100 losing ones. Track, measure, and wait for the sample size to speak.

### Closing Line Value (CLV)

**The question:** "Am I beating the market?"

CLV is the single best predictor of long-term profitability in sports betting.

The **closing line** is the final set of odds offered just before kickoff. By that
point, the odds have been shaped by millions of pounds in bets from the collective
intelligence of the entire market, including the sharpest professional syndicates
in the world. The closing line is the market's best and most informed estimate of
the true probability.

**Example:**

- BetVector flags Arsenal home win at odds of **2.10** at 7am (implied 47.6%).
- By kickoff at 3pm, the odds have shortened to **1.90** (implied 52.6%).
- The market moved in the direction the model predicted.
- CLV = 52.6% - 47.6% = **+5.0%** (positive).

You got odds of 2.10 on something the market eventually priced at 1.90. You were
ahead of the market. This is like buying a stock before positive news comes out --
the market moved your way.

**Why CLV matters so much:** Short-term P&L is dominated by luck. You can have a
genuine edge and still lose for weeks. But positive CLV over a large sample is
extremely hard to achieve by accident. If you are consistently getting better odds
than the closing line, there is strong evidence that your model is genuinely
identifying value that the wider market only catches up to later.

Positive average CLV over 200+ bets is the gold standard for validating a betting
model, even more reliable than ROI itself.

---

## 8. The Self-Improvement Engine -- How It Gets Smarter

BetVector is not a static system. It actively monitors its own performance and
adjusts. But -- and this is a critical "but" -- every adjustment is cautious,
gradual, and transparent.

**The core philosophy: inform, don't decide.** Every automatic change has a
minimum sample size (never react to small data), a maximum change rate (never make
dramatic shifts in one step), and a rollback mechanism (always be able to undo a
change that made things worse). The system never makes irreversible decisions
without your knowledge and consent.

### Automatic Recalibration

**What it fixes:** Probability drift.

Over time, a model's probabilities can drift away from reality. Maybe the model
was well-calibrated six months ago, but since then league dynamics have shifted --
teams are scoring more, defences are playing higher lines, or the model has a
systematic bias it did not have before. When the model says "65% chance" but those
outcomes only win 55% of the time, the probabilities are no longer trustworthy.

Recalibration applies a statistical correction that maps the model's raw
probabilities to probabilities that better match observed outcomes. BetVector
supports two techniques:

- **Platt scaling:** Fits a logistic (S-shaped) curve to transform probabilities.
  Works well when the drift has a consistent shape -- e.g., the model is
  uniformly overconfident. Requires fewer data points.
- **Isotonic regression:** A more flexible, non-parametric approach that can
  correct different biases at different probability ranges. More powerful but
  needs more data to avoid overfitting.

Think of recalibration like tuning a guitar. The strings were in tune when you
started, but after playing for a while they have drifted slightly sharp or flat.
Recalibration tunes them back to pitch.

**Guardrails (these are non-negotiable):**

- **Minimum sample:** Only triggers after **200 or more** resolved predictions.
  Below that, there is not enough data to distinguish real drift from random noise.
  Making changes based on 50 predictions would be like drawing conclusions from
  50 coin flips.
- **Significance threshold:** Only applies if the mean absolute calibration error
  exceeds **3 percentage points**. Small deviations are expected and natural.
- **Rollback protection:** Both the raw and calibrated probabilities are always
  stored. If recalibration makes predictions *worse* over the next 100 predictions,
  the system automatically reverts to the previous calibration.
- **Transparency:** The Model Health dashboard shows a before/after calibration
  plot whenever a recalibration is applied, with timestamps and sample sizes.

### Feature Importance Tracking

**What it monitors:** Which features contribute most to predictions over time.

Not all features are equally useful. Some (like rolling goals scored) might carry
heavy weight in predictions, while others (like season progress) might contribute
almost nothing. And these importances can change -- a feature that was vital six
months ago might have become irrelevant as the league landscape shifted.

For tree-based models like XGBoost or LightGBM (planned future models), the system
logs feature importance after every training cycle and tracks how it changes over
time.

**The key rule: the system NEVER automatically removes features.** If a feature
has been contributing less than 1% importance for 3 or more consecutive training
cycles, the system flags it with a suggestion in the dashboard: "Consider removing
[feature name] -- it has contributed less than 1% importance for the last 3
training cycles." But the decision is always yours.

Features can have periods of low importance that reverse. Removing them prematurely
could hurt the model when conditions change. The system informs; you decide.

### Adaptive Ensemble Weights

**What it adjusts:** The balance between multiple prediction models.

BetVector is designed to eventually run multiple models simultaneously -- for
example, Poisson regression, an Elo-based model, and an XGBoost model. The
**ensemble** combines their predictions by taking a weighted average of their
scoreline matrices.

Initially, all models get equal weight (1/3 each if there are three models). Over
time, the system adjusts these weights based on which model has been performing
best recently.

**How weights are calculated:** Each model's weight is proportional to the inverse
of its Brier score. A model with a Brier score of 0.18 (better) gets more weight
than one with 0.22 (worse).

**Guardrails:**

- **Minimum sample:** 300 resolved predictions per model before adaptive weighting
  activates. Before that threshold, all models get equal weight. Making weight
  decisions with less data is asking for trouble.
- **Gradual change:** Weights never change by more than **10 percentage points**
  per recalculation cycle. If the system calculates that XGBoost should jump from
  33% to 55%, it only moves to 43% this cycle. It might reach 53% next cycle. This
  prevents sudden, destabilising shifts.
- **Floor of 10%:** No active model can drop below 10% weight. This preserves
  ensemble diversity. Even a temporarily underperforming model adds value through
  model diversification -- its errors are often different from the other models'
  errors, and that diversity reduces overall prediction variance.
- **Ceiling of 60%:** No single model can exceed 60% weight. The ensemble should
  always be a genuine ensemble, not one dominant model with decorative sidekicks.
- **Smoothing:** 70% new calculation + 30% previous weight. This prevents the
  weights from overreacting to a short lucky or unlucky stretch by any model.

### Market Feedback Loop

**What it reveals:** Where the system has genuine edge and where it does not.

Not all markets are equally exploitable. BetVector might have a real edge on
Over/Under 2.5 Goals in the Premier League but consistently lose money on BTTS
in Serie A. The market feedback loop identifies these patterns.

Every week, the system recalculates ROI for each **league x market** combination
(for example, "EPL Over/Under 2.5," "La Liga 1X2," "Bundesliga BTTS") and
assigns one of four assessments:

- **Profitable** (green): ROI is positive AND the 95% confidence interval is
  entirely above zero AND at least 100 bets. This is a confirmed, statistically
  significant edge.
- **Promising** (yellow): ROI is positive but the confidence interval includes
  zero, or there are only 50-99 bets. More data is needed before drawing
  conclusions.
- **Insufficient data** (grey): Fewer than 50 bets. No meaningful assessment
  is possible yet.
- **Unprofitable** (red): ROI is negative AND the confidence interval is entirely
  below zero AND at least 100 bets. The system is confident there is no edge here.

**What confidence intervals mean:** When the system reports "EPL Over/Under 2.5:
ROI +7.2% (95% CI: -1.1% to +15.5%)," it is saying: "We estimate 7.2% ROI, but
given the sample size and variance, the true ROI could reasonably be anywhere from
-1.1% to +15.5%." Because the interval includes zero, we cannot be sure the edge
is real yet.

Compare that to "EPL 1X2: ROI +4.8% (95% CI: +1.2% to +8.4%)." The entire
interval is positive. The system is confident this edge is genuine.

The confidence intervals use **bootstrap resampling** -- a statistical technique
that simulates thousands of possible outcomes from your existing bet history to
estimate the range of plausible ROI values. It is more robust than simple
formulaic approaches for the type of data encountered in betting.

**Critical rule: the system never automatically stops flagging bets in any market.**
If "EPL BTTS" is assessed as unprofitable, you will still see those bets on the
Today's Picks page -- but with a warning: "BetVector has historically
underperformed in EPL BTTS (ROI: -3.2% over 120 bets). Proceed with caution."
The system recommends; you decide.

### Seasonal Re-training Triggers

**What it catches:** A stale model that needs fresh training.

Football changes over time. Tactical trends evolve. New managers impose different
playing styles. Transfer windows reshape squads. A model trained in August may be
less accurate by March because the landscape has shifted in ways the old parameters
do not capture.

The system monitors the **rolling Brier score** over the last 100 predictions and
compares it to the model's all-time average Brier score. If the rolling score is
more than **15% worse** than the all-time average, it triggers an automatic full
retrain.

**Example:** The all-time Brier score is 0.200. The rolling score over the last
100 predictions has drifted to 0.231. That is a 15.5% degradation. The automatic
retrain fires.

**Guardrails:**

- **30-day cooldown** between retrains. If the model just retrained last week and
  is still underperforming, the issue might be a fundamental limitation or data
  quality problem -- not staleness. Retraining again immediately will not help.
- **Full-history training:** Retrains use all available historical data, not just
  recent data. This prevents overfitting to recent trends.
- **Performance comparison:** After retraining, the system runs 50 predictions
  with both the old and new model. If the new model performs worse, it
  automatically rolls back to the old one.
- **Email notification:** You receive an alert whenever an automatic retrain fires,
  explaining what triggered it and what happened.

### The Philosophy: Inform, Don't Decide

Every self-improvement mechanism follows the same principles:

1. **Measure** over a statistically meaningful sample. Never react to small data.
2. **Change gradually.** Never make dramatic adjustments in a single step.
3. **Be transparent.** Always show what changed and why on the dashboard.
4. **Provide rollback.** Always be able to undo a change that made things worse.
5. **Recommend, don't mandate.** Surface the data. Let the human make the final
   call on anything consequential.

The system never silently removes a feature, drops a market, radically shifts
model weights, or makes any irreversible change. An overconfident self-improvement
system that "learns" from noise is worse than no self-improvement at all.

---

## 9. The Dashboard -- Your Command Centre

BetVector's dashboard is a Streamlit web application with a dark trading-terminal
aesthetic -- think Bloomberg Terminal meets football data. It is designed for
information density: every pixel earns its place. It works on both desktop and
mobile (designed for phone-in-hand Saturday afternoon use).

The dashboard has seven pages. Here is how to use each one effectively.

### Today's Picks

**What it is:** Your daily action page.
**When to check:** Every morning on match days.

This is where you see the value bets the system has identified for today's
fixtures. Each pick displays:

- The match (home team vs away team) and league.
- The market (Match Result, Over/Under 2.5, BTTS, etc.).
- The model's probability for the outcome.
- The bookmaker's odds and implied probability.
- The **edge** (the gap between model and bookmaker).
- The **confidence tier** (HIGH in green, MEDIUM in yellow).
- The **recommended stake** based on your staking method and current bankroll.

Picks are sorted by confidence, with the strongest edges first. You can expand
any pick to see the full 7x7 scoreline matrix and a complete probability breakdown
across all markets.

**How to use it:** Scan the morning picks. Check any that interest you against the
League Explorer for context. For bets you place with your bookmaker, mark them as
"placed" on the dashboard with the actual odds and stake you got. This lets the
system track your real performance separately from the theoretical system picks.

**Empty state:** "No value bets right now. Your bankroll thanks you for your
patience." Some of the most important days in betting are the days you do nothing.
Discipline means waiting for genuine value.

### Performance Tracker

**What it is:** Your feedback loop.
**When to check:** Weekly. Resist checking daily.

This page shows your results over time:

- **ROI chart:** An interactive line chart showing cumulative return on investment.
  Look for a consistent upward trend over months, not individual wins or losses.
- **P&L summary:** Daily, weekly, monthly, and all-time profit and loss.
- **Win rate by market:** How often value bets win for each market type.
- **System picks vs your placed bets:** Compares "what the model recommended" with
  "what you actually bet on." This reveals whether you are improving or hurting
  your results by selectively following the system.

**Key insight:** Short-term results are dominated by variance. A losing week means
nothing about the model's quality. Focus on 100-bet and 500-bet rolling trends.

### League Explorer

**What it is:** Context and research.
**When to check:** Before placing bets, to sanity-check the system's picks.

Explore any configured league in detail:

- Current league standings (table).
- Recent results for every team.
- Upcoming fixtures.
- Team form summaries (rolling goals, xG, points per game).

**How to use it:** After seeing a value bet on Today's Picks, come here to
sanity-check it. "The model says Over 2.5 in Everton vs Brighton, but what does
Everton's recent scoring look like?" If the data aligns with the model's view,
that increases your confidence. If something looks off (maybe a key player is
injured and you heard about it but the model does not know), you might skip that
particular bet.

### Match Deep Dive

**What it is:** Deep analysis of any individual match.
**When to check:** Whenever you want the full statistical picture.

Select any upcoming or recent match and see everything:

- The complete 7x7 scoreline probability matrix as a colour-coded grid.
- Market probability comparison: model vs bookmaker for every available market.
- Both teams' rolling form over the last 5 and 10 matches.
- Head-to-head record from recent meetings.
- Rest days and context factors.
- The specific feature values that went into the prediction.

**How to use it:** This is your research tool for matches you want to understand
deeply. It shows the complete reasoning behind the system's prediction -- not just
"value bet on Over 2.5" but *why*: the expected goals for both sides, the
historical scoring patterns, the matchup dynamics.

### Model Health

**What it is:** Technical monitoring of the prediction model.
**When to check:** Monthly, unless the system alerts you to something.

- **Brier score trend:** Is the model getting more or less accurate over time? A
  rising Brier score is a warning sign that the model may need recalibration or
  retraining. The self-improvement engine handles this automatically, but this
  chart lets you see what is happening.
- **Calibration curve:** The plot of predicted probabilities vs actual frequencies.
  Points should hug the diagonal line. If they consistently sit below it, the model
  is overconfident. If above, underconfident.
- **Market edge heatmap:** A grid showing league x market combinations, colour-coded
  by profitability assessment (green = profitable, yellow = promising, grey =
  insufficient data, red = unprofitable). This tells you where the system has
  genuine edge.

### Bankroll Manager

**What it is:** Your financial overview.
**When to check:** Weekly, or whenever you want a bankroll snapshot.

- Current bankroll amount and change from starting value.
- Peak bankroll and current drawdown percentage.
- Bankroll balance chart over time.
- Safety limit status: all green (normal), or warnings active.
- Recent bet history with individual P&L.

**How to use it:** A quick glance to confirm everything is healthy. If you see a
drawdown warning, do not panic -- drawdowns are a normal part of betting even with
a winning system. But it is worth reviewing your recent bets and the model's health
metrics to confirm nothing is fundamentally wrong.

### Settings

**What it is:** Your control panel.
**When to use:** During initial setup, and whenever you want to adjust parameters.

- **Edge threshold slider:** Adjust between 3% and 15%. Lower = more bets with
  smaller average edges. Higher = fewer bets with larger edges.
- **Staking method selector:** Switch between flat, percentage, and Kelly. Start
  with flat. Consider percentage after 200+ bets. Consider Kelly only after 500+
  bets with confirmed calibration.
- **Bankroll adjustment:** Update your current bankroll if you add or withdraw
  funds externally.
- **Notification preferences:** Toggle morning picks, evening review, and weekly
  summary emails.
- **League selection:** Enable or disable leagues.
- **Paper trading toggle:** Switch between paper mode and live mode.

---

## 10. Putting It All Together -- A Typical Week

Here is what a typical week of using BetVector looks like once the system is
running and you have settled into the routine.

### Monday Morning

You check your phone and see the BetVector morning email. Subject line:
"BetVector -- 3 Value Bets Today -- EPL."

Inside, three picks:

1. **Arsenal vs Fulham -- Over 2.5 Goals.** Model: 68%. Bet365: 1.80 (implied
   55.6%). Edge: 12.4%. Confidence: HIGH. Stake: 25 pounds. Explanation: Arsenal
   averaging 2.1 goals per game at home over last 5, Fulham conceding 1.6 away.
   Combined expected goals of 3.7 strongly favours the over.

2. **Brighton vs Brentford -- Home Win.** Model: 52%. Odds: 2.15 (implied 46.5%).
   Edge: 5.5%. Confidence: MEDIUM. Stake: 20 pounds.

3. **Crystal Palace vs Bournemouth -- BTTS Yes.** Model: 61%. Odds: 1.75
   (implied 57.1%). Edge: 3.9%. Confidence: MEDIUM. Stake: 20 pounds.

You open the dashboard for a quick check. The third pick -- Crystal Palace BTTS --
has a "promising but insufficient data" warning on EPL BTTS from the market
feedback loop. You decide to skip it and place the first two.

You mark both as "placed" on the dashboard, entering the actual odds you got from
your sportsbook (which might differ slightly from when the system ran).

### Monday Evening

The evening email arrives. Subject: "BetVector Evening -- +20.00 Today -- 1/2
Wins."

Arsenal beat Fulham 3-1. Over 2.5 bet won. Profit: +20 pounds (25 stake at 1.80,
payout 45, minus 25 stake).

Brighton drew 1-1 with Brentford. Home win bet lost. Loss: -20 pounds.

Net daily P&L: 0 pounds. A flat day. The system notes this is within normal
variance.

### Tuesday through Friday

The routine continues. Some days have zero value bets -- the email says "No value
bets today. The model found no edges above your 5% threshold." Other days have
1-2 picks. You place the ones you agree with after a quick check of the League
Explorer.

- **Tuesday:** 1 value bet. You place it. It loses. Running weekly P&L: -20 pounds.
- **Wednesday:** No value bets. No action. Discipline, not inactivity.
- **Thursday:** 2 value bets. You place both. One wins, one loses. Running P&L: -20.
- **Friday:** 1 value bet with a 14% edge -- the largest you have seen this week.
  HIGH confidence. You place it. It wins at odds of 2.40 for a healthy profit.
  Running P&L: +8 pounds.

### Saturday -- Big Matchday

Six Premier League fixtures. The morning email has 4 value bets. You review them
on the dashboard, check the League Explorer for form context, and place 3 of them
(skipping one where the model's view contradicts something you know about a
recent manager change that the data has not captured yet).

Results come in throughout the afternoon. Two of your three bets win. A good day.
Running weekly P&L: +52 pounds.

### Sunday Evening

The weekly summary email arrives. Highlights:

- **Bets this week:** 9 system picks, 7 placed by you.
- **Your placed bet win rate:** 4/7 (57.1%).
- **Weekly ROI:** +3.2%.
- **Cumulative ROI:** +1.8% (slowly climbing from the early weeks).
- **Model health:** Brier score stable at 0.205. Calibration within normal range.
  No recalibration triggered.
- **Best pick of the week:** Friday's 14% edge bet. Won at 2.40.
- **Worst pick of the week:** Tuesday's loss. Edge was only 5.2%, right at the
  threshold.

You open the Model Health page for a monthly check. The calibration curve is
hugging the diagonal -- the probabilities are honest. The market edge heatmap shows
"EPL 1X2" as promising and "EPL O/U 2.5" as profitable (your strongest market).
No markets are flagged as unprofitable yet (insufficient data -- you need more
bets to draw conclusions).

### The Long Game

This weekly cycle repeats. After 3-4 weeks, you have 40-60 tracked bets and an
emerging sense of whether the system has an edge. After 3 months, you have 200+
bets and the statistical picture becomes much clearer. After 6 months with 500+
bets, you know with reasonable confidence whether BetVector generates genuine
long-term profit.

The key mental shift happens somewhere around bet 200: you stop thinking about
individual bets and start thinking about the process. A losing bet at good odds
was still a good bet. A winning bet at bad odds was still a bad bet. What matters
is the edge over hundreds of repetitions. This is the mindset of a quantitative
bettor, and it is the mindset BetVector is designed to cultivate.

---

## 11. Glossary

An alphabetical reference for every technical term used throughout this guide and
in the BetVector system.

---

**Asian Handicap**

A betting market that applies a goal advantage or disadvantage to one team. "Arsenal
-1.5" means Arsenal must win by 2 or more goals for the bet to win. Half-goal
handicaps (like -0.5 or -1.5) eliminate draws. Whole-goal handicaps (like -1.0) can
result in a "push" where your stake is returned if the handicapped result is a draw.
Asian handicaps reduce the number of possible outcomes from three (home/draw/away) to
two, making them popular for more targeted betting.

---

**Bankroll**

The total amount of money set aside specifically for betting. It is ring-fenced
capital that you can afford to lose entirely without affecting your life. Your
bankroll is separate from living expenses, savings, and everything else. If your
bankroll goes to zero, nothing else in your life should be affected. This mental
and financial separation is a fundamental prerequisite for disciplined betting.

---

**Bootstrap Resampling**

A statistical technique for estimating how much a measurement might vary. It works
by repeatedly drawing random samples from your existing data (with replacement) and
recalculating the statistic of interest each time. After thousands of repetitions,
you get a distribution that shows the likely range of the true value. BetVector uses
bootstrap resampling to calculate 95% confidence intervals for ROI in the market
feedback loop, because it makes fewer assumptions about the data than standard
statistical formulas and handles the quirks of betting data more robustly.

---

**Brier Score**

A measure of how accurate probabilistic predictions are. Calculated as the mean of
(predicted probability - actual outcome) squared, where actual outcome is 1
(happened) or 0 (did not happen). Ranges from 0.0 (perfect) to 1.0 (perfectly
wrong). A score of 0.25 is equivalent to predicting 50/50 on everything -- the
baseline of uselessness. For football 1X2 markets, anything below 0.20 is
genuinely good. Lower is better. Named after Glenn Brier, who proposed it in 1950
for evaluating weather forecasts.

---

**Calibration**

Whether predicted probabilities match observed frequencies in reality. A model is
well-calibrated if, among all predictions it labels as "60% likely," roughly 60%
actually occur. Visualised as a calibration curve plotting predicted probability
(x-axis) against actual frequency (y-axis). A perfectly calibrated model follows
the diagonal line. Points below the diagonal indicate overconfidence (the model
predicts higher probabilities than reality delivers). Points above indicate
underconfidence (reality delivers more than the model predicts).

---

**CLV (Closing Line Value)**

The difference between the odds you got when you placed a bet and the final
("closing") odds at kickoff. The closing line represents the market's most
informed estimate, incorporating all available information and betting volume.
Positive CLV means you got better odds than the closing line -- you were ahead of
the market. Positive average CLV over a large sample (200+ bets) is the single
most reliable indicator of a genuine long-term edge in sports betting, even more
reliable than short-term ROI which can be dominated by luck.

---

**Confidence Interval**

A range of values that is likely to contain the true value of a measurement. A
"95% confidence interval of +1.2% to +8.4%" for ROI means that, based on the
data and its variability, the true long-run ROI is likely somewhere in that range.
If the entire interval is above zero, you have statistical evidence of a genuine
edge. If the interval includes zero, the edge might be real but you do not yet
have enough data to be sure.

---

**Drawdown**

The percentage decline from your bankroll's all-time peak to its current value. If
your bankroll peaked at 1,200 pounds and is now 900 pounds, your drawdown is
(1200 - 900) / 1200 = 25%. Drawdowns are a normal and inevitable part of betting,
even with a genuine edge. The question is not whether drawdowns happen, but how
deep they get and how long they last before recovery. BetVector alerts you at a
25% drawdown as a precaution.

---

**Edge**

The difference between your model's estimated probability and the bookmaker's
implied probability. Calculated as: model probability minus implied probability.
A positive edge means the bookmaker is offering better odds than the model thinks
are warranted -- the bet has value. Example: if the model says 55% and the implied
probability is 47.6%, the edge is 7.4%. This is BetVector's estimate of your
advantage on a particular bet.

---

**Ensemble**

A prediction technique that combines multiple models into a single, more robust
prediction. In BetVector, each model (Poisson, Elo, XGBoost) produces its own
7x7 scoreline matrix. The ensemble creates a weighted average of those matrices,
where the weights reflect each model's recent accuracy. Ensembles typically
outperform any individual model because different models capture different patterns,
and their errors tend to partially cancel each other out.

---

**Expected Value (EV)**

The average profit or loss per unit staked over many repetitions of the same type
of bet. Calculated as: (model probability x decimal odds) - 1.0. Positive EV
means the bet is profitable in the long run. Example: 0.55 probability x 2.10
odds = 1.155, minus 1.0 = +0.155, meaning 15.5p expected profit per pound staked.
A single bet might win or lose, but the EV tells you what happens on average
across many similar bets.

---

**Implied Probability**

The probability a bookmaker's odds suggest for an outcome. Calculated as 1 divided
by the decimal odds. Odds of 2.00 imply a 50% probability. Odds of 1.50 imply
66.7%. Odds of 4.00 imply 25%. Note that implied probabilities across all outcomes
in a market sum to more than 100% -- the excess is the overround (the bookmaker's
margin).

---

**Isotonic Regression**

A non-parametric calibration technique used in BetVector's automatic recalibration
system. It fits a non-decreasing (monotonically increasing) function to transform
predicted probabilities into calibrated probabilities. Unlike Platt scaling (which
assumes a specific logistic shape), isotonic regression makes no assumptions about
the form of the calibration curve. It is more flexible but requires more data
points to work reliably. It can correct different biases at different probability
ranges simultaneously.

---

**Kelly Criterion**

A formula from information theory that calculates the optimal bet size to maximise
the long-term growth rate of your bankroll. Formula: f* = (p x b - 1) / (b - 1),
where p is the true probability and b is the decimal odds. Full Kelly is
aggressive and assumes perfect probability estimates. BetVector uses fractional
Kelly (typically quarter-Kelly at 25% of the full amount) to account for the
inevitable imperfection in probability estimates. Named after John Kelly, who
published the formula in 1956 while working at Bell Labs.

---

**Lambda**

The rate parameter of the Poisson distribution. In BetVector, lambda represents
the expected number of goals a team will score in a specific match. A lambda of
1.5 does not mean the team will score exactly 1.5 goals -- it is the centre of a
probability distribution. The actual number of goals could be 0, 1, 2, 3, or
more, with each possibility having a specific probability determined by the
Poisson distribution with that lambda value.

---

**Overround (Margin / Vig / Vigorish / Juice)**

The bookmaker's built-in profit margin. In a fair market, the implied probabilities
for all outcomes sum to exactly 100%. Bookmakers set odds so they sum to 105-110%.
The excess is guaranteed profit for the bookmaker regardless of the match outcome.
Example: a coin flip should have each side at 50% (total 100%). A bookmaker might
price each side at 1.90 (implying 52.6% each, total 105.2%). That 5.2% is the
overround. It is the fundamental reason most bettors lose money over time.

---

**Paper Trading**

A mode where bets are tracked with full fidelity -- P&L, ROI, Brier score, CLV,
everything -- but no actual money is at risk. BetVector starts in paper trading
mode by default. All dashboard pages and email notifications work identically.
The purpose is to validate the model's edge before committing real capital. It is
the same concept as paper trading in stock markets: full simulation with no
financial exposure.

---

**Platt Scaling**

A calibration technique that fits a logistic regression model to transform raw
model probabilities into calibrated probabilities. Named after John Platt, who
proposed it in 1999. It assumes the calibration curve has a logistic (S-shaped)
form, which works well when the model has a consistent directional bias (e.g.,
uniformly overconfident or underconfident). BetVector uses Platt scaling as one
option in its automatic recalibration system.

---

**Poisson Distribution**

A probability distribution that models how many times a rare event occurs in a
fixed period, given a known average rate (lambda). In football, it models the
number of goals scored by a team in a match. If lambda = 1.5, the Poisson
distribution assigns: P(0 goals) = 22.3%, P(1 goal) = 33.5%, P(2 goals) = 25.1%,
P(3 goals) = 12.6%, P(4 goals) = 4.7%, and so on. The probabilities decrease for
higher values but never reach exactly zero. Named after Simeon Denis Poisson, the
French mathematician who published the distribution in 1837.

---

**ROI (Return on Investment)**

The total profit or loss as a percentage of total amount staked. Calculated as
(total PnL / total staked) x 100%. An ROI of +5% means you have earned 5p profit
for every pound staked. Professional sports bettors target 2-5% ROI over large
samples (500+ bets). ROI is extremely noisy over small samples and should not be
used to evaluate performance over fewer than 200 bets. A -4% ROI over 50 bets
tells you almost nothing; the same number over 1,000 bets is a meaningful signal.

---

**Rolling Window**

A method of calculating statistics using only the most recent N data points, where
the window "rolls" forward as new data arrives. In BetVector, a 5-match rolling
window for goals scored means the average goals scored over the team's last 5
completed matches. As each new match finishes, it enters the window and the oldest
match drops out. This captures recent form better than a full-season average
because football teams' performance fluctuates over a season due to injuries,
confidence, fatigue, and tactical changes.

---

**Scoreline Matrix**

A 7x7 grid of probabilities at the heart of BetVector's architecture. Each cell
(h, a) represents the probability of the match ending with the home team scoring
h goals and the away team scoring a goals. The matrix covers all scorelines from
0-0 to 6-6 (49 possibilities). All cells sum to 1.0 (100%). Every prediction
model in the system must produce this matrix as its output, and every market
probability (1X2, Over/Under, BTTS) is derived from it by summing the appropriate
cells. This makes the matrix the universal interface between models and the rest
of the system.

---

**Value Bet**

A bet where your estimated probability of the outcome exceeds the bookmaker's
implied probability. It does not mean the bet will win -- it means the price is
better than it should be relative to the true odds. Over many value bets, the law
of large numbers ensures profit if your probability estimates are well-calibrated.
The concept is analogous to a casino's house edge: individual hands of blackjack
are unpredictable, but the mathematical advantage guarantees the casino profits
over thousands of hands.

---

**Walk-Forward Validation**

The only valid backtesting method for time-series prediction like sports betting.
The process: train the model on all data up to date T, predict the next set of
matches, record the results, then advance T forward and repeat. This simulates
real-world conditions where you only have historical data when making predictions.
It is fundamentally different from random train/test splits (common in machine
learning) which would leak future information and produce artificially inflated
results that do not replicate in live betting.

---

**xG (Expected Goals)**

A statistical measure of the quality of goal-scoring chances created in a match.
Each shot is assigned a probability of being scored based on factors like distance
from goal, angle, body part used, type of assist, and game situation. A team's
match xG is the sum of all their shot probabilities. If a team had shots with
probabilities of 0.35, 0.12, 0.08, 0.04, and 0.02, their xG is 0.61. xG is more
predictive of future performance than actual goals scored because it is less
affected by the randomness of finishing. A team consistently generating 2.0 xG but
only scoring 1.2 actual goals per game is likely to start scoring more as luck
evens out.

---

*BetVector -- putting the data on your side.*
