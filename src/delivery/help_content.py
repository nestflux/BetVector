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
             "once: P = 1 − e^(−λ), where his λ is his goal-share of the team's expected "
             "goals. It is the model's own ranking, not a market line."),
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
            ("Flat staking", "Bet a fixed percentage of your bankroll each time (e.g. "
             "2%). In BetVector, flat and percentage staking use the same "
             "current-bankroll formula, so they come out almost identical — the real "
             "choice is between these and Kelly."),
            ("Percentage staking", "Bet a fixed percentage of your current bankroll, so "
             "the stake recomputes as the balance moves (it shrinks in a downswing — "
             "automatic protection)."),
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
                "wipe you out. Flat and Percentage both bet a fixed % of your current "
                "bankroll (in BetVector they come out almost the same); Kelly instead "
                "sizes each bet by its edge — bigger edge, bigger bet — which grows "
                "faster but swings harder, so it's used as a fraction.",
        "example": "On a $1,000 bankroll at 2%, your next bet is about $20 (2% of the "
                   "balance), recomputed as the balance moves.",
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
