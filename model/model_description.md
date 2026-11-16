# How the Data Jockey model works

Data Jockey works out its own odds for every UK and Irish runner, using only each horse's past performance,
then compares them with the betting market's odds. Where we think a horse has a better chance of winning than
the market does, the horse is flagged as **undervalued**. This page explains each step: what it does, how it
works, and why that method was chosen.

## Key terms

- **Odds and probability.** Two ways of saying the same thing. 
  
  Odds come in two forms:
  - *Fractional* (3/1): the profit per £1 bet. A winning £1 bet at 3/1 makes £3 profit.
  - *Decimal* (4.0): the total returned per £1 bet, stake included: £3 profit + your £1 back = £4.
    Decimal = fractional + 1.

  Probability = 1 / decimal odds, so 3/1 (4.0) is a 25% chance: one bet in four wins, and its £4 return
  covers the £4 staked across all four.
- **The market.** The odds the bookmakers offer: the combined opinion of everyone betting on the race.
- **Forecast price.** The odds printed on the racecard before a race (from the day before): a prediction of
  the price each horse will start at.
- **SP (starting price).** The official odds when the race starts: the price bets are settled at.
- **Snapshot.** We collect each race several times: 3, 2 and 1 days before (t-3, t-2, t-1), on the morning
  of the race (today), and the day after with the result (past). Each collection is a snapshot.

## Overview

```
race data (collected daily) → clean tables → runner features ──► training (monthly) ──► weights
                                                   │                                       │
                                                   └──────► our odds, every runner (daily) ◄┘
                                                                     │
                                       compared with the market's odds (forecast before, SP after)
                                                                     │
                                                      scorecard: how good have we been?
```

## 1. Features

Each runner is described by its **features** (around 20 numbers):

- Its official rating compared with the other runners in the race
- Its recent form (how close to the front it finished in its last few races)
- Days since its last run
- How many times it has run and won before, overall and at this course, distance and ground
- Its jockey's and trainer's win rates
- Whether the race is a handicap, and whether it's a flat or jumps race

**Only historical data.** Every feature uses only data from before the race, so the model learns from the
same information it will have when predicting, and its test results reflect real performance.

**Shrinkage for small samples.** A win rate from a handful of rides is mostly noise: 2 wins from 3 doesn't
make a 67% jockey. Jockey and trainer win rates are shrunk towards the overall average (10%) by adding 20
average rides to every record:

    rate = (wins + 0.10 × 20) / (rides + 20)

2 from 3 becomes about 17%, no rides at all gives exactly 10%, and as real rides accumulate the observed
rate dominates. (A Bayesian estimate: a prior, the average, updated by the evidence.)

**Relative features.** The official rating (the racing authorities' ability score, in pounds) only means
something against the other runners, so the feature is the rating minus the race average. Weight carried is
treated the same way. Ratings are kept separately per race type (flat, hurdle, chase), so changes are only
measured within a type.

**Missing values: imputation plus an indicator.** Some values don't exist yet (no form for a first-time
runner, no jockey booked three days out). Gaps are filled with a neutral value (e.g. form 0.5, midway between
winning and last) and paired with a 0/1 indicator such as `is_debut`, so the model can distinguish a real
average from an imputed one.

## 2. The model

1. **A linear score.** Each feature is multiplied by a learnt **weight** (section 3) and summed. A higher
   score means a better chance.
2. **Softmax within each race.** A race's scores become win probabilities that sum to exactly 100%:

       probability of a runner = e^(its score) / the sum of e^(score) for every runner in the race

   Only differences between scores matter: +1 point makes a runner e ≈ 2.7 times as likely to win. Regardless of the number of runners, scores are always normalised to 100%.
3. **Probabilities into odds.** Decimal odds = 1 / probability: 25% becomes 4.0, shown as 3/1.

**Why this model.** This is a *conditional logit*: logistic regression adapted to a one-winner-per-group
outcome, and the standard model in racing research. 
Treating each runner as an independent binary
classification gives probabilities that don't sum to 100% per race (a field might total 130%) and need
rescaling afterwards. It also has few parameters (about 20 weights), suiting a short history, and each weight
is directly interpretable, e.g. "+0.045 to the score per pound of rating advantage".

**Interaction terms.** A feature that's constant within a race (the ground, the race type) shifts every
score equally and cancels out of the softmax, so it can only enter through an interaction with a runner-level
feature. For example, rating advantage × handicap: in a handicap the weights carried are set to cancel out
the rating gap, so the gap should count for less.

## 3. Learning the weights

**Objective: log-loss.** The weights are fitted by maximum likelihood: they minimise the **log-loss**, the
average of −ln(probability given to the actual winner) across thousands of past races. Lower is better.
It penalises confident mistakes far more than near misses:

| Probability we gave the winner | −ln(probability) |
|---|---|
| 50% | 0.69 |
| 20% | 1.61 |
| 2% | 3.91 |

For a pricing model, confidently ruling out an eventual winner is the costliest error.

**Regularisation.** With a short history, some features match past results purely by chance, and the fit
would give them large weights (overfitting). An L2 penalty adds the sum of the squared weights to the
log-loss being minimised, so a weight only grows if the data strongly supports it; its strength is tuned on
the validation weeks (section 4).

**Standardisation.** Features have very different ranges (a rating gap ±20 lb, a win rate 0–0.3), so each
is rescaled to mean 0 and standard deviation 1 before fitting: (value − mean) / standard deviation. Examples
from the first model:

| Feature | Mean | Std dev | Example | Standardised |
|---|---|---|---|---|
| Rating vs field (lb) | 0.0 | 5.2 | +8 lb | +1.54 |
| Jockey win rate | 0.109 | 0.045 | 20% | +2.02 |
| Recent form (0 = won, 1 = last) | 0.483 | 0.224 | 0.10 | −1.71 |
| ln(1 + days since run) | 3.18 | 1.29 | 200 days (5.30) | +1.65 |
| First run (0/1) | 0.075 | 0.263 | 1 | +3.52 |

In raw units, +8 lb and a 20% jockey can't be compared; standardised, the 20% jockey is the more unusual of
the two. The penalty then treats all features alike, and their weights are comparable.

## 4. Training and evaluation

Training runs automatically once a month on AWS, with a time-based split:

| Races | Used for |
|---|---|
| The first 3 weeks of data | Nothing (see below) |
| The next ~6 weeks (train) | Fitting the weights |
| The 2 weeks after that (validation) | Tuning the penalty strength |
| The latest 2 weeks (test) | Measuring performance on races it never trained on |

**Why split by time, not at random.** In use, the model always predicts forward from what it has seen. A
random split would let it train on later races and be tested on earlier ones, which flatters it.

**Warm-up period.** Horse history arrives with the race data, going back years, but jockey and trainer win
rates are built from our own collected races, which start on 11 Aug 2026. In the first weeks almost every
jockey sits at the 10% prior, so those weeks would teach the model that jockeys don't matter. We treat the first 3 weeks of data as a warm-up period, which gets left out of the training.

**Refit and promotion.** After testing, the weights are refitted on all the data. Each month's model is
compared with the one in use on the same recent races; the better of the two is kept. Each run saves its weights and a short report
(dates used, test log-loss against the market and random picks, calibration, every feature's weight).

**No look-ahead in the history.** Upcoming races use the latest model. Past races are recalculated daily but
keep the model that was live when they were run, so no model ever scores races from its own training data.
Races before the first model are excluded from evaluation.

## 5. Comparing with the market

**Removing the bookmakers' margin.** The market's odds, turned into probabilities, add up to more than 100%
(typically 115–125% at SP). The extra is the bookmakers' margin, and it has to come off before comparing.
Scaling every horse down evenly isn't right, because bookmakers put more of their margin on the long-odds
horses (the *favourite–longshot bias*). **Shin's method** estimates how unevenly the margin is spread in each
race and takes more of it off the outsiders:

| SP | 1 / odds | Even scale-down | Shin's method |
|---|---|---|---|
| 6/4 (favourite) | 40.0% | 32.1% | 34.6% |
| 5/2 | 28.6% | 23.0% | 24.2% |
| 4/1 | 20.0% | 16.1% | 16.4% |
| 6/1 | 14.3% | 11.5% | 11.2% |
| 10/1 | 9.1% | 7.3% | 6.5% |
| 14/1 | 6.7% | 5.4% | 4.4% |
| 25/1 | 3.8% | 3.1% | 2.0% |
| 50/1 | 2.0% | 1.6% | 0.7% |
| **Total** | **124.4%** | **100%** | **100%** |

(There's no direct formula for it, so the calculation repeats a correction step until the answer stops
changing, about 30 times.)

**Undervalued.** Take a horse we give a 25% chance, at odds of 5/1 (decimal 6.0). If we're right, a £1 bet
returns £6 one time in four: £1.50 on average, a 50% profit. That's its **expected value**. A horse is flagged
when its expected value is at least +10% and we give it at least a 5% chance (so very long shots can't be
flagged on our say-so alone). Before the race the odds used are the forecast price; after it, SP.

For the race above, the chance we'd need to give each horse for it to be flagged:

| SP | Decimal | Market's chance (Shin) | Our chance needed to flag it | Set by |
|---|---|---|---|---|
| 6/4 (favourite) | 2.5 | 34.6% | 44.0% | +10% expected value |
| 5/2 | 3.5 | 24.2% | 31.4% | +10% expected value |
| … | … | … | … | … |
| 50/1 | 51.0 | 0.7% | 5.0% | 5% minimum |

e.g. the favourite: 0.44 × 2.5 − 1 = +10%. For the 50/1 shot the expected-value bar alone would be 2.2%, so
the 5% minimum sets it.

## 6. The scorecard: out-of-sample evaluation

The scorecard only uses races outside the model's training data. Each race is evaluated twice:

- **After the race:** our odds against SP, the price right at the start of the race.
- **The site's pick:** our odds as published on the morning of the race (against the forecast
  price), i.e. what a visitor would have seen.

Winnings are always worked out at SP: the forecast is only a prediction, SP is what a bet is paid at. It
reports:

- **Log-loss**, ours and the market's (section 3). Lower is better.
- **Top pick**: how often our most likely horse won, against the market favourite.
- **Calibration**: horses grouped by the chance we gave them, against how often they won. Horses we give
  10–20% should win 10–20% of the time.
- **Flagged horses' winners**: how many won, against how many SP expected (the sum of their SP
  probabilities). If the flags find value, more should win than expected. A z-score says whether the
  difference is bigger than luck would explain (above about 2).
- **Flagged horses' profit**: the return from £1 on every flag, with a 95% range. While the range includes 0%,
  the flags haven't shown they make or lose money.

  For example, 8 flagged horses backed with £1 each at SP:

  | Horse | A | B | C | D | E | F | G | H |
  |---|---|---|---|---|---|---|---|---|
  | SP | 12/1 | 9/2 | 7/1 | 20/1 | 5/1 | 10/1 | 6/1 | 14/1 |
  | Result | Lost | **Won** | Lost | Lost | Lost | Lost | Lost | Lost |
  | Profit | −£1 | +£4.50 | −£1 | −£1 | −£1 | −£1 | −£1 | −£1 |

  That's −£2.50 on £8 staked, a return of −31%, with a 95% range of −166% to +104% (average profit per bet
  ± 1.96 × the spread of the profits / √8). With so few bets one winner more or less changes everything, so
  the range is huge and includes 0%. It narrows as bets accumulate.

## 7. Where it stands (16 Nov 2026)

**The first model** (trained on races from 1 Sep to 12 Nov) scored a log-loss of 1.96 on its test weeks,
against 1.71 for SP and 2.13 for picking at random: about 40% of the way from guessing to the market.

**The first scorecard** (82 races, 13–15 Nov): on the horses we flagged as undervalued, SP has been right and
we've been wrong. The 227 flagged horses produced 12 winners, against 12.1 that SP predicted and more that our
own odds predicted, and backing them all at SP lost 53% (95% range −83% to −23%, a real loss rather than bad
luck). With only three months of history, the model overrates long-odds horses, which is exactly what the
flagging rule picks out; the rule will be revisited once a few hundred races have been graded.

**Known gaps:** only three months of data; career records only include runs we've seen (up to 6 before our
data begins); the starting stall and headgear (blinkers, visors) aren't used yet.
