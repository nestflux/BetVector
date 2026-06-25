"""
BetVector — Help Center content (HC-01)
========================================
The SINGLE SOURCE OF TRUTH for the in-app manual. Streamlit-free, pure data +
one pure search filter — no DB, no I/O, no rendering. Authoring lives here so
every surface reads one definition and nothing drifts:

  * the in-app Help page (``views/help.py``, HC-01)
  * later, the downloadable manual export (HC-06)
  * later, the per-page glossaries (picks / performance / bankroll /
    match_detail / wc_deep_dive) once they are migrated to read from here (HC-06)

The glossary below consolidates the five page-level glossaries that existed
before the Help Center. Where the same term was defined differently across pages
(drift), the clearest/most-correct wording was chosen and the conflict resolved:
  * **Edge** — defined against the bookmaker's RAW implied probability (1 ÷ odds),
    which is exactly what the value finder flags on (value_finder.py: implied =
    1/odds, edge = model − implied). De-vig is a deep-dive DISPLAY refinement only,
    not the flagging basis — an earlier draft wrongly said edge used the de-vigged
    price (corrected in HC-03). Kept the plain "+8%" example.
  * **BTTS** — "score at least one goal" (one consistent verb).
  * **Confidence** — all three tiers (HIGH / MEDIUM / LOW); match_detail had
    dropped MEDIUM.
  * **Squad value** — reconciled the 1.5x vs 2x threshold into one honest line.
Terms the app shows but no page had ever defined (calibration, Brier, ensemble,
MODEL badge, trust tiers, verdict states, line shopping, O/U 3.5, capped edge)
are authored fresh here.
"""

from __future__ import annotations

from html import escape

# ---------------------------------------------------------------------------
# Start here — a two-minute orientation (structured so the doc export and the
# page can both render it; plain text, emphasis comes from the layout).
# ---------------------------------------------------------------------------

START_HERE_INTRO = (
    "BetVector is a quantitative football-betting assistant. A statistical model "
    "rates every match, compares its view to the bookmakers' prices, and flags the "
    "spots where a price looks too generous — a “value bet”. It never places a bet "
    "for you: it surfaces the edge and the reasoning, and you decide."
)

# The daily loop — (step label, what to do). Ordered.
DAILY_LOOP = [
    ("See what's on", "Open Fixtures (or Today's Picks) for the upcoming matches. "
     "Each carries colour-coded badges showing where the model sees value."),
    ("Read a match", "Click into a Deep Dive for the full picture — the model's "
     "scoreline grid, its probabilities beside every bookmaker, team form, and (for "
     "the World Cup) lineups and player insight."),
    ("Log your bets", "In My Bets, build a slip from the fixtures and record what you "
     "actually backed, so the app can track your real results."),
    ("Review", "Performance Tracker and Bankroll Manager show how you and the model "
     "are doing over time — profit, ROI, and how your bankroll is holding up."),
    ("Check the model", "Model Health shows whether the model's probabilities can be "
     "trusted (calibration, Brier score) and where it has actually been profitable."),
]

# Good to know — (title, text). The framing that keeps expectations honest.
GOOD_TO_KNOW = [
    ("It suggests; you decide", "Every figure here is decision-support. A green badge "
     "is the model's opinion, not a guarantee — you place the bets yourself, at your "
     "own judgement."),
    ("Green marks the model, not a result", "A MODEL badge marks numbers that come "
     "from BetVector's own model rather than from bookmaker odds. Colour shows where "
     "the model sees value — not whether a bet won."),
    ("“Shadow” features are for insight only", "Some panels (the World Cup model, the "
     "Bayesian comparison, the lineup what-ifs) are shadow features. They are shown "
     "to inform you and never change or place a value bet."),
    ("Stuck on a word?", "Anything you don't recognise — a term, a badge, a colour — "
     "is in the Glossary tab. Use the search box to jump straight to it."),
]


# ---------------------------------------------------------------------------
# Master glossary — one entry per term, grouped. Each group has a short blurb and
# a list of (term, definition) pairs. Definitions are 1-2 plain-English sentences.
# ---------------------------------------------------------------------------

GLOSSARY_GROUPS = [
    {
        "group": "Betting basics",
        "blurb": "The core ideas the whole app is built on — what a good bet is and "
                 "how we measure it.",
        "terms": [
            ("Value bet", "A bet where the model thinks the outcome is more likely "
             "than the bookmaker's price implies — the price looks too generous, and "
             "that gap is the opportunity. Backing value consistently is how the model "
             "aims to profit over time."),
            ("Edge", "The model's probability minus the bookmaker's implied probability "
             "(1 ÷ the odds). A positive edge means the model rates the selection higher "
             "than the price implies, so the bet looks underpriced — e.g. +8% is an "
             "8 percentage-point advantage over the bookmaker's price. (On the deep dive "
             "the prices are also de-vigged for a fair side-by-side comparison; the value "
             "finder itself flags on the raw price.)"),
            ("Edge threshold", "The minimum edge a pick needs before it is shown. A "
             "higher threshold means fewer but stronger picks; adjust it to match your "
             "risk appetite (Settings, or the slider on Fixtures)."),
            ("Capped edge", "An edge so large it more likely signals a model error or "
             "stale price than real value. The app flags these (amber) and does not "
             "treat them as backable — a huge edge is a warning, not a jackpot."),
            ("Odds (decimal)", "The bookmaker's price as a decimal. 2.50 means you get "
             "$2.50 back for every $1 staked (your stake included). Lower odds = the "
             "bookmaker thinks the outcome is more likely."),
            ("Implied probability", "What a price implies the true chance is: 1 ÷ "
             "decimal odds. Odds of 2.50 imply a 40% chance. It still contains the "
             "bookmaker's margin until you de-vig it."),
            ("Overround (vig / margin)", "The bookmaker's built-in profit. Add up the "
             "implied probabilities for every outcome of a market and they total more "
             "than 100%; the excess is the overround. E.g. 45% + 28% + 32% = 105% → a "
             "5% overround. Lower = fairer odds for you."),
            ("De-vig", "Stripping the overround out of a bookmaker's odds so the "
             "implied probabilities of a market sum to 100% — giving a fair number to "
             "compare against the model."),
            ("Line shopping", "Comparing the same selection across several bookmakers "
             "and taking the best price. A better price is free edge; the deep dives "
             "mark the best available with a ★."),
            ("Line movement", "How a price changes over time. The app holds a few real "
             "snapshots — open → your entry → current → close — rather than a "
             "tick-by-tick history."),
            ("CLV (Closing-Line Value)", "Your entry price versus the closing price. "
             "Beating the close (positive CLV) is the single best sign a bet was struck "
             "at genuine value, even before you know if it won."),
            ("Expected value (EV)", "The average profit or loss a bet would return if "
             "it were repeated many times: EV = (model probability × payout) − stake. "
             "Positive EV (+EV) means it is profitable in the long run."),
        ],
    },
    {
        "group": "Markets",
        "blurb": "The kinds of bet the model prices. Everything is derived from its "
                 "scoreline grid.",
        "terms": [
            ("Market", "The type of bet on offer: Match Result (1X2), Over/Under goals "
             "(1.5 / 2.5 / 3.5), or Both Teams to Score (BTTS)."),
            ("Selection", "The specific outcome the model recommends within a market, "
             "e.g. “Home Win”, “Over 2.5 Goals”, or “BTTS Yes”."),
            ("1X2 (Match Result)", "The three match outcomes: Home Win (1), Draw (X), "
             "Away Win (2). The most common football market."),
            ("Over / Under 1.5", "Whether the total goals will be 2 or more (Over) or "
             "0–1 (Under). Under 1.5 is fairly rare in top leagues."),
            ("Over / Under 2.5", "Whether the total goals will be 3 or more (Over) or 2 "
             "or fewer (Under). The most popular goals line — usually close to 50/50."),
            ("Over / Under 3.5", "Whether the total goals will be 4 or more (Over) or 3 "
             "or fewer (Under). A higher goals line for more open matches."),
            ("BTTS (Both Teams to Score)", "Will each team score at least one goal? "
             "Derived from the scoreline grid by adding every cell where both teams' "
             "scores are above zero."),
            ("Asian handicap", "A market that gives one team a virtual goal start or "
             "deficit to even the match (e.g. −1.5 means they must win by 2+). It "
             "removes the draw. The model uses Pinnacle's handicap lines as an input "
             "but does not yet publish its own handicap prices."),
            ("Market codes", "Short labels used in tables: 1X2 = Match Result, "
             "OU15 = O/U 1.5, OU25 = O/U 2.5, OU35 = O/U 3.5, BTTS = Both Teams to "
             "Score."),
        ],
    },
    {
        "group": "The model",
        "blurb": "How BetVector turns data into probabilities — and the player/team "
                 "stats it reads along the way.",
        "terms": [
            ("Poisson model", "The statistical model that predicts how many goals each "
             "team will score from historical performance, outputting an expected-goals "
             "number (lambda) per team. Every market price is built from it."),
            ("Lambda (λ)", "The model's expected goals for one team in this match. "
             "λ = 1.8 means it expects roughly 1–2 goals, with 3+ possible but less "
             "likely."),
            ("Scoreline matrix", "The model's 7×7 grid of the probability of every "
             "scoreline from 0–0 to 6–6. Darker green = more likely. Every market "
             "probability (1X2, O/U, BTTS) is derived from this grid."),
            ("xG (Expected Goals)", "The sum of the scoring probability of each shot, "
             "based on its position, angle, and type. It measures chance quality, not "
             "luck — a team with 2.1 xG that scored 0 was unlucky."),
            ("NPxG (Non-Penalty xG)", "xG with penalties removed — a cleaner measure of "
             "a team's open-play attacking quality."),
            ("xGA (Expected Goals Against)", "The quality of chances opponents create "
             "against a team. Lower = harder to break down."),
            ("NPxGA (Non-Penalty xGA)", "Defensive quality with penalties conceded "
             "removed."),
            ("NPxG Diff", "NPxG minus NPxGA. Positive means a team creates better "
             "chances than it allows — the single best summary of open-play quality."),
            ("PPDA", "Passes Per Defensive Action — how many passes the opponent "
             "completes before a team wins the ball back. Low = aggressive pressing "
             "(≈8); high = a deep block / counter-attacking style (≈18)."),
            ("Deep completions", "Passes that reach the opponent's penalty area — a "
             "measure of how often a team creates danger in the final third."),
            ("Squad value", "The combined Transfermarkt market value of a team's squad "
             "— a proxy for long-term quality (an €800m squad is usually deeper and more "
             "talented than a €200m one). A gap of roughly 1.5× between two teams is "
             "already meaningful; the dashboard flags a large gap (around 2× or more) as "
             "a context badge on the pick."),
            ("Calibration", "How well the model's probabilities match reality. If it is "
             "well calibrated, outcomes it calls 70% really do happen about 70% of the "
             "time. Shown as the scatter on Model Health (a perfect model sits on the "
             "diagonal)."),
            ("Brier score", "A measure of how accurate the model's probabilities are, "
             "from 0 (perfect) to 1 (terrible). Lower is better; it is the model's "
             "headline accuracy metric and rewards being both right and well-calibrated."),
            ("Confidence", "How strong an edge is, shown as HIGH / MEDIUM / LOW. HIGH = "
             "a large edge the model is certain about; MEDIUM = a moderate edge; LOW = a "
             "marginal edge — real but weaker, so proceed with caution."),
            ("MODEL badge", "A small green tag marking numbers that come from "
             "BetVector's own model rather than from bookmaker odds — so you always know "
             "whose opinion you are looking at."),
            ("Ensemble", "A blended prediction that combines the Poisson model with a "
             "second model (e.g. XGBoost). The blend weight is shown on Model Health."),
            ("Feature importance", "A ranking of which inputs (form, xG, venue, rest, "
             "etc.) most influence the model's predictions."),
            ("Bayesian (shadow)", "A second model run alongside the staked Poisson for "
             "comparison only. It never places a bet; promoting it to live staking is a "
             "manual decision."),
            ("Adjusted xG", "A display-only what-if: the model's λ rescaled by how the "
             "confirmed lineup's attacking firepower compares to the team's last XI. It "
             "never changes the model or a bet — the value finder still uses the model's "
             "own xG."),
            ("Goal-share", "A player's share of his team's attacking output, from his "
             "recent goals per 90 minutes. Used to split a team's expected goals across "
             "its XI."),
            ("Anytime scorer %", "The model's estimate that a player scores at least "
             "once: P = 1 − e^(−λ), where his λ is his goal-share of the team's adjusted "
             "expected goals. It is the model's own ranking, not a market line."),
            ("Penalty taker", "The team's designated penalty taker. His spot-kicks are "
             "already counted in his goals per 90, so the flag just marks who takes them "
             "— it does not add an extra bump (that would double-count)."),
            ("Rotation flag", "Raised when a confirmed XI changes heavily from the "
             "team's last one — a hypothesis to re-check, never a model input."),
            ("Booking risk", "A starter whose recent club yellow-card rate is high "
             "(yellows per 90). A card-prone heads-up — not a tournament caution count, "
             "and never a model input."),
            ("Star absence", "A high-value or high-scoring player who started the team's "
             "previous XI but is missing from this one — rotated out or unavailable. "
             "Matchup context, not a bet signal."),
        ],
    },
    {
        "group": "Performance & bankroll",
        "blurb": "How results and risk are tracked — your money, your staking, and how "
                 "you're doing.",
        "terms": [
            ("P&L (Profit and Loss)", "Total money gained or lost across all resolved "
             "bets. Positive (green) = net profit; negative (red) = net loss."),
            ("P&L (per bet)", "The result of a single bet: Won = stake × (odds − 1); "
             "Lost = −stake. E.g. $20 at 2.50 → +$30 if it wins, −$20 if it loses."),
            ("ROI (Return on Investment)", "Profit ÷ total staked, as a percentage. "
             "+5% means $5 earned per $100 wagered. Professional bettors target roughly "
             "+2% to +5% long-term. (Monthly ROI is the same, scoped to one month.)"),
            ("Win rate", "The percentage of bets that won. On its own it does not show "
             "profitability — 40% at high odds can profit, while 60% at low odds can "
             "lose. Odds matter as much as hit rate."),
            ("Total staked", "The sum of every stake placed — the denominator used to "
             "calculate ROI."),
            ("Cumulative P&L", "A running total of profit/loss over time. Watch the "
             "overall trajectory, not individual swings — dips are normal."),
            ("Monthly P&L", "Profit or loss per calendar month (green = up, red = "
             "down). Even a profitable model has losing months."),
            ("Current bankroll", "Your betting capital right now: starting amount plus "
             "all profits, minus all losses. This is what future stakes are sized from."),
            ("Starting bankroll", "The capital you first allocated to betting; shown as "
             "a reference line on the bankroll chart."),
            ("Peak bankroll", "The highest your bankroll has ever reached — used to "
             "measure drawdown."),
            ("Drawdown", "How far the bankroll has fallen from its peak, as a "
             "percentage. Peak $1,100 → now $990 = a 10% drawdown. 10–20% is normal; at "
             "25% the app raises a safety alert."),
            ("Flat staking", "Level staking: the SAME fixed amount every bet — a set "
             "percentage of your STARTING bankroll (e.g. 2% of a $1,000 start = $20 each "
             "time), regardless of your current balance. The simplest, steadiest method, "
             "good for beginners. Contrast with percentage staking, which moves with your "
             "current balance."),
            ("Percentage staking", "Bet a fixed percentage of your current bankroll, so "
             "the stake recomputes as the balance moves (it shrinks in a downswing — "
             "automatic protection). Unlike flat, it compounds over a run of bets."),
            ("Kelly Criterion", "A formula that sizes bets in proportion to the edge "
             "and the odds, to maximise long-term growth. It is volatile, so BetVector "
             "uses fractional (e.g. quarter) Kelly for safety."),
            ("Stake %", "The percentage of your bankroll wagered on a bet. Lower is "
             "more conservative; professionals typically use 1–3%."),
            ("Suggested stake", "How much to bet, worked out from your bankroll settings "
             "with a deliberately conservative formula so no single bet risks too much."),
            ("Safety limits", "Guardrails that pause betting suggestions: a Daily Loss "
             "Limit (max loss in a day), a Drawdown Alert (a set % below peak), and a "
             "Minimum Bankroll floor. Each shows OK / APPROACHING / TRIGGERED."),
            ("System pick vs User placed", "A System Pick is auto-logged by the model "
             "whenever it finds value — it tracks the model's performance independently "
             "of you. A User Placed bet is one you confirmed yourself — it tracks your "
             "actual results and bankroll."),
            ("Won / Lost / Pending", "A bet's state. Won = stake × (odds − 1); Lost = "
             "−stake; Pending = the match has not finished yet."),
        ],
    },
    {
        "group": "World Cup",
        "blurb": "Extras that only appear during the tournament, on the World Cup hub "
                 "and its deep dive.",
        "terms": [
            ("Qualification status", "“Through” / “out” is shown only when it is "
             "mathematically certain (a top-two finish). The race for the eight best "
             "third-placed teams depends on other groups, so it stays “in contention”."),
            ("Trust tiers (🟢 🟡 🔴)", "How much confidence a league or fixture has "
             "earned: 🟢 proven, 🟡 promising, 🔴 unproven. The tier sets how much "
             "emphasis a verdict gets and how exposure is scaled."),
            ("Verdict (value / capped / none)", "The fixture-level call on the strip: "
             "value = a backable edge inside the trusted range, capped = an edge past "
             "the ceiling (likely model noise — re-check), none = no model edge."),
            ("Line movement & CLV", "On the World Cup deep dive, each backable "
             "selection is traced open → entry → current → close, with the closing-line "
             "value shown — did the price you took beat where it closed?"),
        ],
    },
]


# ---------------------------------------------------------------------------
# Screen tour (HC-02) — one friendly card per page: what it's for, the three things
# to look at first, and the colours/badges decoded. Authored from the real dashboard
# (every page in dashboard.get_pages). Each entry:
#   {icon, page, what, first: [..], decode: [(label, meaning), ..]}
# ``decode`` may be empty (a page with no special badges renders without that block).
# ---------------------------------------------------------------------------

TOUR = [
    {
        "icon": "📅", "page": "Fixtures",
        "what": "Every upcoming match across your active leagues, with a colour-coded "
                "read on where the model sees value. This is your usual landing page.",
        "first": [
            "The Top Value Picks banner at the top — the few strongest edges right now.",
            "The market badges on each row (1X2, O/U, BTTS) — green means a real edge.",
            "The edge-threshold slider — drag it for fewer, stronger picks or more, "
            "looser ones.",
        ],
        "decode": [
            ("Green double ring + glow", "A genuine value bet — the edge clears your "
             "threshold."),
            ("Blue ring", "The model's best guess for the match, but the edge is below "
             "your threshold."),
            ("★ before a badge", "The model's single best selection in that match."),
            ("Green card border", "This fixture has a backable value bet."),
            ("Green / red border (Recent Results)", "A settled value bet that won / lost."),
            ("🟢 🟡 🔴 league trust chip", "The league's trust tier — how proven it is: "
             "proven / promising / unproven."),
        ],
    },
    {
        "icon": "🎯", "page": "Today's Picks",
        "what": "The model's actionable value bets — the bets it would make — as cards "
                "you can browse by date.",
        "first": [
            "The summary row — how many value bets, the average edge, how many are "
            "high-confidence.",
            "Each card's Edge and Suggested Stake — the opportunity and how much to risk.",
            "Slide the date range back to see how past picks actually resolved.",
        ],
        "decode": [
            ("HIGH / MEDIUM / LOW", "The model's confidence — green / yellow / muted."),
            ("🌧️ Weather", "Extreme match-day conditions that tend to lower scoring."),
            ("Squad value", "One squad is worth far more than the other (a talent gap)."),
            ("FT score (past picks)", "A finished pick shows the final score and whether "
             "the pick won or lost."),
        ],
    },
    {
        "icon": "📋", "page": "My Bets",
        "what": "Your personal bet log and a slip builder — record what you actually "
                "backed so the app can track your real results.",
        "first": [
            "The fixture browser — tap the odds buttons to add selections to your slip.",
            "The slip builder — set your stake and log everything in one go.",
            "Your bet history, with a status and P&L for each bet.",
        ],
        "decode": [
            ("🟡 Pending", "The match hasn't finished yet."),
            ("🟢 Won / 🔴 Lost / ⚪ Void", "The settled outcome of a bet."),
            ("🎯 N in slip (sidebar)", "How many selections are queued in your slip."),
        ],
    },
    {
        "icon": "📈", "page": "Performance Tracker",
        "what": "How you're doing over time — profit, ROI, win rate, and the bets "
                "behind them.",
        "first": [
            "The four metric cards — Total P&L, ROI, total bets, win rate.",
            "The cumulative P&L line — the trajectory matters more than daily swings.",
            "The Bet Type filter — System Pick (the model's record) vs User Placed (yours).",
        ],
        "decode": [
            ("Green / red numbers", "Profit / loss."),
            ("System Pick vs User Placed", "The model's auto-logged bets vs the ones "
             "you confirmed yourself."),
        ],
    },
    {
        "icon": "🏟️", "page": "League Explorer",
        "what": "Standings, form, and quality metrics for any one of your active leagues.",
        "first": [
            "The standings table for the league you pick.",
            "Each team's last-five form strip.",
            "The NPxG table — who actually creates and concedes the best chances.",
        ],
        "decode": [
            ("W / D / L form badges", "A team's last five results, most recent on the right."),
            ("NPxG Diff", "Chances created minus conceded — the best one-number quality "
             "read."),
        ],
    },
    {
        "icon": "🏆", "page": "World Cup",
        "what": "The tournament hub — today's matches, group tables, value bets, and who "
                "is winning it. During the World Cup this becomes your landing page.",
        "first": [
            "Today's fixtures with the verdict chip — value / re-check / no edge.",
            "The group standings and who is qualifying.",
            "The winner-probability bar and the model's tournament record.",
        ],
        "decode": [
            ("✓ green verdict", "A backable model edge on that fixture."),
            ("⚠ amber verdict", "An edge so big it's likely model noise — re-check."),
            ("— muted verdict", "No model edge."),
            ("🟢 🟡 🔴 group dots", "A team's qualification position in the group table — "
             "top two through (green), third in the play-off race (yellow), bottom out "
             "(red)."),
            ("🔒 lineups", "XIs aren't announced yet (they post about an hour before "
             "kickoff)."),
        ],
    },
    {
        "icon": "🔬", "page": "Model Health",
        "what": "Whether the model can be trusted — calibration, accuracy (Brier), CLV, "
                "and where it has actually been profitable.",
        "first": [
            "The Brier score and calibration plot — are the probabilities honest?",
            "The CLV trend — is the model beating the closing line?",
            "The market edge map — which leagues × markets actually profit.",
        ],
        "decode": [
            ("Calibration points on the diagonal", "Well-calibrated — 70% calls really "
             "win about 70%."),
            ("Edge map green / yellow / red", "Profitable / promising / unprofitable by "
             "league × market."),
        ],
    },
    {
        "icon": "💰", "page": "Bankroll Manager",
        "what": "Your capital, your staking method, and the safety rails that keep a bad "
                "run from becoming a disaster.",
        "first": [
            "Current vs peak bankroll, and the drawdown number.",
            "Your staking method and stake size.",
            "The safety-limit traffic lights.",
        ],
        "decode": [
            ("🟢 OK / 🟡 APPROACHING / 🔴 TRIGGERED", "A safety limit's status — "
             "TRIGGERED pauses suggestions."),
            ("Monthly breakdown", "Bets, wins, losses, P&L and ROI for each month."),
        ],
    },
    {
        "icon": "⚙️", "page": "Settings",
        "what": "Your preferences — staking method, edge threshold, which leagues are "
                "active, and your email digests.",
        "first": [
            "Your staking method and stake %.",
            "The edge threshold that filters every pick across the app.",
            "Which leagues are active (they drive the filters everywhere).",
        ],
        "decode": [],
    },
    {
        "icon": "🔍", "page": "Match Deep Dive",
        "what": "The full picture for one league match — open it from any fixture or pick.",
        "first": [
            "The scoreline heatmap — the model's most likely scores.",
            "Model probability beside each bookmaker, with the edge highlighted.",
            "Team form, head-to-head, and the advanced stats.",
        ],
        "decode": [
            ("MODEL badge", "This number is the model's, not a bookmaker's."),
            ("Green highlight + edge", "The model rates this selection above the "
             "market — value."),
            ("FanDuel / Best Edge / All toggle", "Switch which bookmaker's price the "
             "model is compared against."),
        ],
    },
    {
        "icon": "🔬", "page": "WC Deep Dive",
        "what": "The same full match analysis for a World Cup fixture, plus lineups and "
                "player insight.",
        "first": [
            "Model vs every book, with line movement and CLV.",
            "Confirmed lineups, the adjusted-xG what-if, and the anytime-scorer board.",
            "Player watch — booking risk, star absences, and milestones.",
        ],
        "decode": [
            ("MODEL badge", "A model number, not a market line."),
            ("Green value / amber capped", "A backable edge vs an edge too big to trust."),
            ("Adjusted xG / Anytime % (grey)", "Display-only model estimates — never bets."),
            ("⚠ rotation flag", "The XI changed heavily from last time — a hypothesis to "
             "re-check."),
        ],
    },
]


# ---------------------------------------------------------------------------
# FAQ (HC-03) — the common "why is this happening?" questions, in plain English.
# Each entry: (question, answer). Kept short; deep concepts live in Betting 101 (HC-04).
# ---------------------------------------------------------------------------

FAQ = [
    ("Why does a fixture say “No odds” or “No pred”?",
     "Odds and predictions are produced by separate pipeline steps. “No odds” means no "
     "bookmaker price has been pulled for that match yet; “No pred” means the model "
     "hasn't scored it yet (often because a feature it needs, like recent form, isn't "
     "in place). Both fill in as the daily pipeline runs."),
    ("What's the difference between a System Pick and one of my bets?",
     "A System Pick is logged automatically whenever the model finds value — it tracks "
     "how the model itself would do, independently of you. A bet you add on My Bets is "
     "a User Placed bet — it tracks your actual results and moves your bankroll."),
    ("Why did the model's number change since I last looked?",
     "Predictions refresh as new data lands — updated prices, team news, and results "
     "from other matches. The model re-runs each pipeline cycle, so a probability or "
     "edge can shift right up to kickoff."),
    ("Where do the picks actually come from?",
     "For each match the model builds a 7×7 grid of likely scorelines (the scoreline "
     "matrix), derives every market probability from it, and flags any selection whose "
     "model probability beats the bookmaker's implied price (1 ÷ the odds) by more than "
     "your edge threshold. (On the deep dive it also de-vigs the prices for a fair "
     "side-by-side comparison.)"),
    ("Why did a bet with a positive edge still lose?",
     "Edge is a long-run advantage, not a guarantee. A +8% edge means you'd expect to "
     "profit over many bets like it — any single one can still lose. Variance is "
     "normal; judge the model over hundreds of bets, not one. (More in Betting 101.)"),
    ("Why are some leagues marked 🟢 / 🟡 / 🔴?",
     "Those are trust tiers — how proven a league's edge is on out-of-sample data. "
     "🟢 proven leagues get full stakes, 🟡 promising ones are tracked at standard "
     "size, and 🔴 unproven ones are kept small until they earn trust."),
    ("Is the World Cup model the same as the league model?",
     "No — it's a separate model with its own data, and it runs in shadow: it shows "
     "you its view (and a Bayesian comparison) but never places a bet. Promoting it to "
     "real staking is a manual decision."),
    ("Do I have to bet what the model says?",
     "No. BetVector is decision-support — it surfaces where the value is and the "
     "reasoning behind it. You decide what, if anything, to back, and you log it "
     "yourself."),
]


# ---------------------------------------------------------------------------
# Betting 101 (HC-04) — short plain-English lessons, each with a WORKED numeric
# example. Each entry: {title, body, example}. The maths is kept exact (Gate 2 checks
# it), and the edge lesson uses the RAW implied price (1/odds) to match the value
# finder — de-vig is only the deep-dive display refinement (see the glossary).
# ---------------------------------------------------------------------------

CONCEPTS = [
    {
        "title": "Odds and implied probability",
        "body": "Decimal odds are what you get back per $1 staked (your stake "
                "included). Flip them over and you get the bookmaker's implied "
                "probability: 1 ÷ the odds. The lower the odds, the more likely the "
                "bookmaker thinks it is.",
        "example": "Odds of 2.50 → implied probability 1 ÷ 2.50 = 40%. If you believe "
                   "it's more likely than 40%, the price looks generous.",
    },
    {
        "title": "Value and edge",
        "body": "A value bet is one where your probability is higher than the price "
                "implies. Edge measures the gap: your model's probability minus the "
                "bookmaker's implied probability (1 ÷ odds). A positive edge means the "
                "selection is underpriced — that's the whole game.",
        "example": "Model 48%, odds 2.50 (implied 40%) → edge = 48% − 40% = +8%. That "
                   "8-point gap is the value the model is backing.",
    },
    {
        "title": "The bookmaker's margin (overround) and de-vig",
        "body": "Add up the implied probabilities of every outcome in a market and "
                "they total more than 100% — the excess is the bookmaker's built-in "
                "margin (the overround or “vig”). “De-vigging” strips it out so the "
                "numbers sum to 100% and you can compare books fairly. (BetVector "
                "de-vigs only on the deep dive, for display; a pick is flagged against "
                "the raw price.)",
        "example": "Home 45% + Draw 28% + Away 32% = 105% → a 5% margin. De-vigged "
                   "(divide each by 1.05): 42.9% / 26.7% / 30.5%, which sum to ~100%.",
    },
    {
        "title": "Closing-Line Value (CLV) — the truest scoreboard",
        "body": "The closing price is the market's sharpest estimate, just before "
                "kickoff. If the price you took was better than the close, you got "
                "value — and that's true whether or not the bet wins. Beating the "
                "close over many bets is the single best sign you're doing it right.",
        "example": "You back at 2.20 (implies 45.5%); it closes at 2.00 (implies 50%). "
                   "You beat the close by ~4.5 points — a good bet even if it loses.",
    },
    {
        "title": "Why a +edge bet can still lose (variance)",
        "body": "Edge is an average over many bets, not a promise on any one. A "
                "positive-edge bet can — and often will — lose; that's normal. The edge "
                "only shows up over a large sample, so judge the model over hundreds of "
                "bets, never a handful.",
        "example": "A +8% edge at roughly even odds still loses around 45% of the time. "
                   "Over 1 bet that's almost a coin flip; over 500 bets the edge wins.",
    },
    {
        "title": "Bankroll and staking",
        "body": "Stake a small, consistent slice of your bankroll so a bad run can't "
                "wipe you out. Flat staking bets a fixed amount each time (a % of your "
                "STARTING bankroll); Percentage staking bets a % of your CURRENT balance, "
                "so it shrinks in a downswing; Kelly sizes each bet by its edge — bigger "
                "edge, bigger bet — which grows faster but swings harder, so it's used as "
                "a fraction.",
        "example": "Start $1,000 at 2%: flat stakes a level $20 every bet, while "
                   "percentage stakes 2% of the current balance — $20 now, less after a "
                   "loss, more after a win.",
    },
    {
        "title": "Drawdown",
        "body": "A drawdown is how far your bankroll has fallen from its highest point. "
                "Downswings are part of betting even with a real edge; the job is to "
                "size stakes so a normal drawdown never becomes a fatal one.",
        "example": "Peak $1,200, now $1,000 → a 16.7% drawdown. 10–20% is routine; at "
                   "25% BetVector raises a safety flag and you should ease off.",
    },
    {
        "title": "Reading the scoreline matrix",
        "body": "For each match the model fills a 7×7 grid with the probability of "
                "every scoreline. Every market is just a sum of the right cells — which "
                "is how one model produces 1X2, Over/Under and BTTS all at once.",
        "example": "Add the diagonal (1-1, 2-2, …) for the draw; add every cell where "
                   "home > away for a home win; add every cell where both teams scored "
                   "for BTTS Yes.",
    },
    {
        "title": "Calibration and the Brier score",
        "body": "A model is well calibrated when the things it calls 70% actually "
                "happen about 70% of the time. The Brier score measures exactly that "
                "(lower is better), rewarding probabilities that are both confident and "
                "correct — and punishing overconfidence.",
        "example": "Take every pick rated ~70%. If roughly 70 of each 100 win, the "
                   "model is honest. One that calls everything 90% but wins 60% is "
                   "overconfident, and its Brier score will be worse.",
    },
    {
        "title": "ROI beats win rate",
        "body": "Win rate ignores the odds, so on its own it tells you little. Return "
                "on investment — profit per dollar staked — is what actually matters, "
                "because a few winners at big prices can outweigh many at short ones.",
        "example": "40% winners at average odds 3.00 returns +20% ROI; 60% winners at "
                   "1.40 returns −16%. The higher win rate is the losing strategy.",
    },
]


# ---------------------------------------------------------------------------
# Pure helpers (no Streamlit) — used by the view, the tests, and (later) the export.
# ---------------------------------------------------------------------------

_TOUR_BY_PAGE = {entry["page"]: entry for entry in TOUR}


def tour_for_page(page: str):
    """The tour entry for a page title (as registered in dashboard.get_pages), or
    ``None`` when that page has no tour card (the Help page itself, Admin, onboarding).
    Lets the per-page “How to read this page” link know whether to show, and the Help
    page surface a focused card. Pure — no Streamlit."""
    return _TOUR_BY_PAGE.get(page)


# ---------------------------------------------------------------------------
# Interactive-tool maths (HC-05) — pure, unit-tested. The view supplies the live
# inputs and the config bounds (edge_threshold / max_actionable_edge / kelly_fraction),
# so these helpers stay Streamlit- and config-free. Percentages are PERCENTAGE POINTS
# (0–100); the edge basis is the RAW implied price (1 ÷ odds), matching value_finder.
# ---------------------------------------------------------------------------

def implied_pct_from_odds(odds):
    """Bookmaker implied probability (%) from decimal odds: 100 ÷ odds. ``None`` for an
    invalid price (decimal odds must be > 1)."""
    try:
        odds = float(odds)
    except (TypeError, ValueError):
        return None
    if odds <= 1.0:
        return None
    return 100.0 / odds


def edge_pp(model_pct, odds):
    """Edge in percentage points: the model's probability minus the bookmaker's implied
    probability (1 ÷ odds) — the RAW price the value finder flags on. ``None`` if the
    price is invalid or the model probability is missing."""
    implied = implied_pct_from_odds(odds)
    if implied is None or model_pct is None:
        return None
    return float(model_pct) - implied


def verdict_for_edge(edge, threshold_pp, ceiling_pp):
    """Classify an edge (pp) the way the value finder does, given the config bounds:
    ``"value"`` when threshold ≤ edge ≤ ceiling, ``"capped"`` above the ceiling (an edge
    so big it's likely model error), ``"none"`` below the threshold (including negative)."""
    if edge is None or edge < threshold_pp:
        return "none"
    if edge > ceiling_pp:
        return "capped"
    return "value"


def flat_stake(bankroll, stake_pct):
    """Stake in dollars = bankroll × stake%. Pass your STARTING bankroll for flat
    (level) staking, or your CURRENT balance for percentage staking. 0 for bad /
    negative inputs."""
    try:
        return max(0.0, float(bankroll)) * max(0.0, float(stake_pct)) / 100.0
    except (TypeError, ValueError):
        return 0.0


def kelly_fraction_of_bankroll(model_pct, odds):
    """Full-Kelly fraction of bankroll for a bet: f* = (p·odds − 1) ÷ (odds − 1), with
    p = model_pct/100, floored at 0 (no bet without an edge). ``None`` for an invalid
    price."""
    try:
        odds = float(odds)
        p = float(model_pct) / 100.0
    except (TypeError, ValueError):
        return None
    if odds <= 1.0:
        return None
    return max(0.0, (p * odds - 1.0) / (odds - 1.0))


def kelly_stake(bankroll, model_pct, odds, kelly_fraction):
    """Suggested Kelly stake in dollars = bankroll × kelly_fraction × f*. The
    ``kelly_fraction`` (e.g. 0.25 — quarter-Kelly) comes from config for safety. 0 when
    there's no edge or a bad input."""
    f = kelly_fraction_of_bankroll(model_pct, odds)
    if f is None:
        return 0.0
    try:
        return max(0.0, float(bankroll)) * max(0.0, float(kelly_fraction)) * f
    except (TypeError, ValueError):
        return 0.0

def all_terms() -> list:
    """Flat ``[(term, definition), ...]`` across every group, in order. Used by the
    integrity tests and (HC-06) the downloadable-doc export."""
    return [pair for grp in GLOSSARY_GROUPS for pair in grp["terms"]]


def term_count() -> int:
    """Total number of glossary terms across all groups."""
    return len(all_terms())


def filter_glossary(query: str) -> list:
    """Return ``GLOSSARY_GROUPS`` filtered to entries whose term OR definition contains
    ``query`` (case-insensitive, substring). A blank/whitespace query returns every
    group unchanged; a group with no surviving terms is dropped entirely. Pure — no
    Streamlit, so the search behaviour is unit-testable on its own."""
    q = (query or "").strip().lower()
    if not q:
        return GLOSSARY_GROUPS
    out = []
    for grp in GLOSSARY_GROUPS:
        hits = [(term, defn) for (term, defn) in grp["terms"]
                if q in term.lower() or q in defn.lower()]
        if hits:
            out.append({"group": grp["group"], "blurb": grp["blurb"], "terms": hits})
    return out


# ---------------------------------------------------------------------------
# Per-page glossaries (HC-06) — the five dashboard pages that used to carry their
# own inline glossaries (Today's Picks, Performance Tracker, Bankroll Manager,
# Match Deep Dive, WC Deep Dive) now read their DEFINITIONS from here, so every
# shared term is written exactly once and the page glossaries can never drift from
# the master above. Each page keeps its own term selection, section layout and
# display labels (behaviour-preserving); only the definition text is centralised.
#
# ``GLOSSARY_BY_TERM`` is the single lookup (term -> definition) built from the
# master groups. In the page specs, ``_T["Master term"]`` pulls a shared definition;
# rows that are page-only presentation (raw stats, UI labels, confidence tiers,
# traffic-light states) keep a local definition string because they appear on one
# page only and so cannot drift. A row is ``(label, definition)`` or
# ``(label, definition, colour_hex)`` — the optional colour tints the term label
# (used for the HIGH/MEDIUM/LOW tiers and the OK/APPROACHING/TRIGGERED states).
# ---------------------------------------------------------------------------

GLOSSARY_BY_TERM = {term: defn for grp in GLOSSARY_GROUPS for (term, defn) in grp["terms"]}


def glossary_def(term: str) -> str:
    """The single authoritative definition for a master glossary term. Raises
    ``KeyError`` if the term isn't in the master glossary — so a typo in a page spec
    fails loudly at import (and in the tests) rather than rendering a blank row."""
    return GLOSSARY_BY_TERM[term]


_T = GLOSSARY_BY_TERM  # local alias for the page specs below

# Design-system colours for tinted term labels (kept here so the page specs are
# self-contained; the view supplies the rest of the chrome).
_GL_GREEN = "#3FB950"
_GL_YELLOW = "#D29922"
_GL_RED = "#F85149"
_GL_MUTED = "#8B949E"

PAGE_GLOSSARIES = {
    # --- Today's Picks (picks.py) ------------------------------------------------
    "Today's Picks": [
        ("The Pick Card", [
            ("Value Bet", _T["Value bet"]),
            ("Market", _T["Market"]),
            ("Selection", _T["Selection"]),
        ]),
        ("Key Numbers", [
            ("Model Prob", "The model's estimated probability of this outcome actually "
             "happening, based on team form, xG, venue, and other features. E.g. 62% means "
             "the model thinks this happens roughly 6 times out of 10."),
            ("Odds", _T["Odds (decimal)"]),
            ("Edge", _T["Edge"]),
            ("Suggested Stake", _T["Suggested stake"]),
        ]),
        ("Confidence Levels", [
            ("HIGH", "Large edge with strong model certainty. These are the bets the model "
             "is most confident about.", _GL_GREEN),
            ("MEDIUM", "Moderate edge. Worth considering but less conviction than "
             "high-confidence picks.", _GL_YELLOW),
            ("LOW", "Marginal edge. The model sees slight value but the signal is weaker. "
             "Proceed with caution.", _GL_MUTED),
        ]),
        ("Context Badges", [
            ("🌧️ Weather", "Appears when match-day conditions are extreme (heavy rain, "
             "strong wind, snow). Bad weather typically reduces goal-scoring and favours "
             "defensive teams."),
            ("Squad Value", _T["Squad value"]),
        ]),
        ("Summary Metrics (Top of Page)", [
            ("Value Bets", "Total number of value bets found above your edge threshold. "
             "More isn't always better — quality matters."),
            ("Avg Edge", "The average edge across all picks shown. Higher average edge "
             "means the model sees stronger overall opportunities today."),
            ("High Confidence", "How many of today's picks the model is most certain about. "
             "These are your best bets to focus on."),
        ]),
        ("Filters & Controls", [
            ("Date Range", "Slide forward to see future matchday picks, or backward to "
             "review recent picks and their results. Defaults to today ± 3 days."),
            ("Edge Threshold", _T["Edge threshold"]),
            ("Best Bookmaker", "Each pick shows the bookmaker offering the highest edge. "
             "Different bookmakers price the same outcome differently."),
            ("Alt. Bookmakers", "How many additional bookmakers also offer value for this "
             "selection. Shown as \"X other bookmakers also offer value\" on each card."),
        ]),
    ],
    # --- Performance Tracker (performance.py) ------------------------------------
    "Performance Tracker": [
        ("Key Metrics", [
            ("Total P&L", _T["P&L (Profit and Loss)"]),
            ("ROI %", _T["ROI (Return on Investment)"]),
            ("Win Rate", _T["Win rate"]),
            ("Total Staked", _T["Total staked"]),
        ]),
        ("Charts", [
            ("Cumulative P&L", _T["Cumulative P&L"]),
            ("Monthly P&L", _T["Monthly P&L"]),
        ]),
        ("Market Types", [
            ("Match Result", _T["1X2 (Match Result)"]),
            ("O/U 1.5 / 2.5", "Over/Under goals markets. O/U 1.5 = will there be 2+ goals? "
             "O/U 2.5 = will there be 3+ goals?"),
            ("BTTS", _T["BTTS (Both Teams to Score)"]),
        ]),
        ("Bet Types & Outcomes", [
            ("System Pick", "A bet automatically logged by the model when it finds value. "
             "Tracks model performance independently of whether you actually placed the bet."),
            ("User Placed", "A bet you manually confirmed as placed on your sportsbook. "
             "Tracks your actual betting performance and bankroll."),
            ("Won / Lost", "Resolved outcomes. Won = P&L is stake × (odds − 1). "
             "Lost = P&L is −stake."),
            ("Pending", "Match hasn't finished yet — result is not known."),
        ]),
    ],
    # --- Bankroll Manager (bankroll.py) ------------------------------------------
    "Bankroll Manager": [
        ("Bankroll Basics", [
            ("Current Bankroll", _T["Current bankroll"]),
            ("Starting Bankroll", _T["Starting bankroll"]),
            ("Peak Bankroll", _T["Peak bankroll"]),
            ("Drawdown", _T["Drawdown"]),
        ]),
        ("Staking Methods", [
            ("Flat Staking", _T["Flat staking"]),
            ("Percentage Staking", _T["Percentage staking"]),
            ("Kelly Criterion", _T["Kelly Criterion"]),
            ("Stake %", _T["Stake %"]),
        ]),
        ("Safety Limits", [
            ("Daily Loss Limit", "Maximum amount you can lose in one day before the system "
             "stops suggesting bets. Prevents catastrophic single-day losses."),
            ("Drawdown Alert", "Warning triggered when your bankroll falls a certain "
             "percentage below its peak. A signal to review strategy or reduce stakes."),
            ("Minimum Bankroll", "The floor below which all betting stops. If your bankroll "
             "drops to this level, the system pauses until you add funds or reassess your "
             "strategy."),
            ("OK", "Safety limit is not close to being triggered. Normal operation.", _GL_GREEN),
            ("APPROACHING", "Safety limit is within range. Consider reducing stakes or "
             "pausing.", _GL_YELLOW),
            ("TRIGGERED", "Safety limit has been reached. Betting is paused until the "
             "condition clears.", _GL_RED),
        ]),
        ("Bet History", [
            ("Market Codes", _T["Market codes"]),
            ("P&L", _T["P&L (per bet)"]),
            ("Monthly ROI", _T["ROI (Return on Investment)"]),
        ]),
    ],
    # --- Match Deep Dive (match_detail.py) ---------------------------------------
    "Match Deep Dive": [
        ("Form & Performance", [
            ("Form (5 / 10)", "Points per game (PPG) over the last 5 or 10 matches. "
             "3.0 = won every game, 0.0 = lost every game. A gap of 0.5+ PPG is significant."),
            ("Goals Scored", "Average goals scored per match in the rolling window. "
             "Higher = more attacking output."),
            ("Goals Conceded", "Average goals allowed per match. Lower = better defensive "
             "record."),
            ("Rest Days", "Days since the team's last competitive match. A gap of 2+ days "
             "between teams gives the rested side an edge."),
        ]),
        ("Expected Goals (xG)", [
            ("xG", _T["xG (Expected Goals)"]),
            ("xGA", _T["xGA (Expected Goals Against)"]),
            ("NPxG", _T["NPxG (Non-Penalty xG)"]),
            ("NPxGA", _T["NPxGA (Non-Penalty xGA)"]),
            ("NPxG Diff", _T["NPxG Diff"]),
        ]),
        ("Pressing & Penetration", [
            ("PPDA", _T["PPDA"]),
            ("PPDA Allowed", "The reverse: how many passes this team makes before the "
             "opponent wins it back. Reflects how much pressing this team faces."),
            ("Deep Comps", _T["Deep completions"]),
            ("Deep Allowed", "How many deep completions the opponent achieves against this "
             "team. Lower = better at keeping opponents away from the box."),
        ]),
        ("Model & Predictions", [
            ("Poisson Model", _T["Poisson model"]),
            ("Lambda (λ)", _T["Lambda (λ)"]),
            ("Scoreline Matrix", _T["Scoreline matrix"]),
        ]),
        ("Market Probabilities", [
            ("Model-Generated", "All probabilities in this section come from the BetVector "
             "Poisson model, NOT from bookmaker odds. The model predicts each scoreline "
             "independently and derives all market probabilities (1X2, O/U, BTTS) from the "
             "7×7 scoreline matrix. Compare these to bookmaker implied probabilities in the "
             "Value Bets section below."),
            ("1X2", _T["1X2 (Match Result)"]),
            ("Over / Under 1.5", _T["Over / Under 1.5"]),
            ("Over / Under 2.5", _T["Over / Under 2.5"]),
            ("BTTS", _T["BTTS (Both Teams to Score)"]),
            ("Asian Handicap", _T["Asian handicap"]),
        ]),
        ("Value Betting", [
            ("Value Bet", _T["Value bet"]),
            ("Edge", _T["Edge"]),
            ("Implied Probability", _T["Implied probability"]),
            ("Model vs Implied", "Shows the model's probability alongside the bookmaker's "
             "implied probability. The gap between them is the edge."),
            ("Confidence", _T["Confidence"]),
            ("Bookmaker Toggle", "Switch between FanDuel odds (default), the highest-edge "
             "bookmaker, or expand all bookmakers. Different bookmakers price the same "
             "outcome differently — the toggle lets you compare."),
            ("Other Bookmakers", "How many additional bookmakers also offer value for this "
             "selection. More bookmakers = more confidence the value is real."),
            ("Overround", _T["Overround (vig / margin)"]),
            ("Expected Value (EV)", _T["Expected value (EV)"]),
        ]),
        ("Squad & Context", [
            ("Squad Value", _T["Squad value"]),
            ("H2H Record", "Head-to-Head — historical results between these two teams. Some "
             "teams consistently struggle against specific opponents regardless of form."),
            ("Venue Form", "A team's record specifically at home or away, which can differ "
             "significantly from their overall form. Some teams are \"fortress\" at home but "
             "weak on the road."),
            ("Weather Impact", "Heavy rain, strong wind, or snow can reduce passing accuracy "
             "and goal-scoring. The model flags these as contextual factors when conditions "
             "are extreme."),
        ]),
        ("Analysis Icons", [
            ("▲ Green", "Factor supports the model's prediction (e.g. strong form for the "
             "favoured team).", _GL_GREEN),
            ("▼ Red", "Factor works against the prediction (e.g. poor away form for the team "
             "expected to win).", _GL_RED),
            ("— Grey", "Neutral context — worth knowing but doesn't clearly favour either "
             "side (e.g. even H2H record).", _GL_MUTED),
        ]),
    ],
    # --- WC Deep Dive (wc_deep_dive.py) ------------------------------------------
    # One untitled section (the deep dive renders a flat list). Every term maps to a
    # master entry — these were authored straight into the master glossary.
    "WC Deep Dive": [
        (None, [
            ("Scoreline matrix", _T["Scoreline matrix"]),
            ("De-vig", _T["De-vig"]),
            ("Edge", _T["Edge"]),
            ("Line movement", _T["Line movement"]),
            ("CLV", _T["CLV (Closing-Line Value)"]),
            ("Rotation flag", _T["Rotation flag"]),
            ("Qualification status", _T["Qualification status"]),
            ("Bayesian (shadow)", _T["Bayesian (shadow)"]),
            ("Adjusted xG", _T["Adjusted xG"]),
            ("Goal-share", _T["Goal-share"]),
            ("Anytime scorer %", _T["Anytime scorer %"]),
            ("Penalty taker", _T["Penalty taker"]),
            ("Booking risk", _T["Booking risk"]),
            ("Star absence", _T["Star absence"]),
        ]),
    ],
}

PAGE_GLOSSARY_KEYS = list(PAGE_GLOSSARIES)


def glossary_sections_html(page_key: str) -> str:
    """Escaped HTML body (``.gloss-section`` / ``.gloss-title`` / ``.gloss-row``) for a
    page's glossary, built from ``PAGE_GLOSSARIES``. No ``<style>`` and no Streamlit —
    the view supplies the expander and the CSS chrome, so this stays pure and unit-
    testable. Every dynamic string (term, definition, section title) is HTML-escaped;
    the only un-escaped value is the colour hex, which comes from the fixed module
    constants above. Returns ``""`` for an unknown page key."""
    sections = PAGE_GLOSSARIES.get(page_key, [])
    out = []
    for title, rows in sections:
        parts = ['<div class="gloss-section">']
        if title:
            parts.append(f'<div class="gloss-title">{escape(title)}</div>')
        for row in rows:
            term, defn = row[0], row[1]
            colour = row[2] if len(row) > 2 else None
            style = f' style="color: {colour};"' if colour else ""
            parts.append(
                f'<div class="gloss-row">'
                f'<span class="gloss-term"{style}>{escape(term)}</span>'
                f'<span class="gloss-def">{escape(defn)}</span>'
                f'</div>'
            )
        parts.append("</div>")
        out.append("".join(parts))
    return "".join(out)


# ---------------------------------------------------------------------------
# Downloadable manual (HC-06) — render the whole Help Center to a single document
# from the same content constants, so the download can never drift from the in-app
# page. ``build_manual_markdown`` is the primary export (universal, opens anywhere);
# ``build_manual_html`` is a print-friendly variant the browser can save as a PDF.
# Both are pure string builders — no new dependency, no I/O.
# ---------------------------------------------------------------------------

_MANUAL_INTRO = (
    "Your in-app guide to reading the dashboard, the betting concepts behind it, and "
    "every term it shows. Generated from the Help Center, so it always matches the app."
)


def build_manual_markdown() -> str:
    """The full manual as one Markdown string: Start here, the screen tour, Betting 101,
    the FAQ, and the master glossary — assembled from the same constants the in-app Help
    page renders. Deterministic (no timestamp) so it's easy to unit-test."""
    out = ["# BetVector — User Manual", "", f"_{_MANUAL_INTRO}_", ""]

    out += ["## Start here", "", START_HERE_INTRO, "", "### Your daily loop", ""]
    for i, (label, text) in enumerate(DAILY_LOOP, 1):
        out.append(f"{i}. **{label}** — {text}")
    out += ["", "### Good to know", ""]
    for title, text in GOOD_TO_KNOW:
        out.append(f"- **{title}** — {text}")
    out.append("")

    out += ["## Screen tour", ""]
    for card in TOUR:
        out += [f"### {card['icon']} {card['page']}", "", card["what"], "",
                "**Look at first**", ""]
        out += [f"- {item}" for item in card["first"]]
        out.append("")
        if card["decode"]:
            out += ["**Badges & colours**", ""]
            out += [f"- **{label}** — {meaning}" for label, meaning in card["decode"]]
            out.append("")

    out += ["## Betting 101", ""]
    for c in CONCEPTS:
        out += [f"### {c['title']}", "", c["body"], "", f"> **Example.** {c['example']}", ""]

    out += ["## FAQ", ""]
    for question, answer in FAQ:
        out += [f"**{question}**", "", answer, ""]

    out += ["## Glossary", ""]
    for grp in GLOSSARY_GROUPS:
        out += [f"### {grp['group']}", "", f"_{grp['blurb']}_", ""]
        out += [f"- **{term}** — {defn}" for term, defn in grp["terms"]]
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def build_manual_html() -> str:
    """The full manual as a self-contained, print-friendly HTML document (light theme,
    a small print stylesheet) — the browser's Print → Save as PDF turns it into a PDF
    with no extra dependency. Same content as ``build_manual_markdown``; every dynamic
    string is HTML-escaped."""
    def esc(value) -> str:
        return escape(str(value))

    out = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>BetVector — User Manual</title>",
        "<style>",
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;"
        "max-width:820px;margin:40px auto;padding:0 22px;color:#1b1f24;line-height:1.55;}",
        "h1{font-size:28px;margin-bottom:4px;}",
        "h2{margin-top:34px;border-bottom:2px solid #d0d7de;padding-bottom:5px;}",
        "h3{margin-top:24px;margin-bottom:6px;}",
        ".blurb{color:#57606a;font-style:italic;}",
        ".example{background:#f3faf4;border-left:3px solid #2da44e;padding:8px 12px;"
        "margin:8px 0 14px;}",
        "dl{margin:6px 0 14px;} dt{font-weight:700;color:#1b1f24;}",
        "dd{margin:0 0 8px 0;color:#3a4149;}",
        "ul{margin:6px 0 14px;}",
        "@media print{body{margin:0;max-width:none;}}",
        "</style></head><body>",
        f"<h1>BetVector — User Manual</h1>",
        f'<p class="blurb">{esc(_MANUAL_INTRO)}</p>',
    ]

    out.append("<h2>Start here</h2>")
    out.append(f"<p>{esc(START_HERE_INTRO)}</p>")
    out.append("<h3>Your daily loop</h3><ol>")
    out += [f"<li><strong>{esc(label)}</strong> — {esc(text)}</li>"
            for label, text in DAILY_LOOP]
    out.append("</ol>")
    out.append("<h3>Good to know</h3><ul>")
    out += [f"<li><strong>{esc(title)}</strong> — {esc(text)}</li>"
            for title, text in GOOD_TO_KNOW]
    out.append("</ul>")

    out.append("<h2>Screen tour</h2>")
    for card in TOUR:
        out.append(f"<h3>{esc(card['icon'])} {esc(card['page'])}</h3>")
        out.append(f"<p>{esc(card['what'])}</p>")
        out.append("<p><strong>Look at first</strong></p><ul>")
        out += [f"<li>{esc(item)}</li>" for item in card["first"]]
        out.append("</ul>")
        if card["decode"]:
            out.append("<p><strong>Badges &amp; colours</strong></p><dl>")
            for label, meaning in card["decode"]:
                out.append(f"<dt>{esc(label)}</dt><dd>{esc(meaning)}</dd>")
            out.append("</dl>")

    out.append("<h2>Betting 101</h2>")
    for c in CONCEPTS:
        out.append(f"<h3>{esc(c['title'])}</h3>")
        out.append(f"<p>{esc(c['body'])}</p>")
        out.append(f'<div class="example"><strong>Example.</strong> {esc(c["example"])}</div>')

    out.append("<h2>FAQ</h2>")
    for question, answer in FAQ:
        out.append(f"<p><strong>{esc(question)}</strong><br>{esc(answer)}</p>")

    out.append("<h2>Glossary</h2>")
    for grp in GLOSSARY_GROUPS:
        out.append(f"<h3>{esc(grp['group'])}</h3>")
        out.append(f'<p class="blurb">{esc(grp["blurb"])}</p><dl>')
        for term, defn in grp["terms"]:
            out.append(f"<dt>{esc(term)}</dt><dd>{esc(defn)}</dd>")
        out.append("</dl>")

    out.append("</body></html>")
    return "".join(out)
