"""The blend: our probability and the market's, combined per race.

When we disagree with the market, who's right? The blend answers with two
numbers per market, fitted like the model's weights (conditional logit, by
maximum likelihood) but on just two inputs:

  score = model_weight x ln(our probability) + market_weight x ln(market's)
  blended probability = softmax of the scores over the race

model_weight near 0 means our probability adds nothing the market doesn't
know; clearly above 0, we know something it doesn't, and the blend leans our
way in proportion. The flag is then decided from the blended probability
(glue build/model_value.py), so big disagreements, which are mostly our
mistakes, only count as far as they have earned it.

Fitted per market on the races our models priced out of sample
(model_value, in_sample = false), with the same two views as the scorecard:
"forecast" = the race-morning row (today, else t-1) against the forecast
price, which is what the site flags on; "SP" = after the race, against SP.

Adopted only once a market has MIN_RACES races, and only if, fitted on the
earlier days, it beats the market on the later ones (TEST_SHARE of the days).
Then refitted on every race for the published weights.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from data_jockey_model import evaluate
from data_jockey_model.fit import Races, fit_weights, win_probabilities

MIN_RACES = 1000
TEST_SHARE = 0.3
MARKETS = ["forecast", "SP"]


def blend_query(database: str) -> str:
  """Each out-of-sample priced runner of a settled race, once per market: the
  race-morning row against the forecast, the past row against SP."""
  return f"""
WITH value AS (
  SELECT *
  FROM {database}.model_value
  WHERE NOT in_sample AND won IS NOT NULL
),
pre_race AS (
  SELECT
    *,
    MAX(CASE WHEN snapshot = 'today' THEN 1 ELSE 0 END) OVER (PARTITION BY race_id) AS has_today
  FROM value
  WHERE snapshot IN ('today', 't-1')
)
SELECT 'SP' AS market, race_id, ride_id, race_date, model_prob, market_prob, won
FROM value
WHERE snapshot = 'past'
UNION ALL
SELECT 'forecast' AS market, race_id, ride_id, race_date, model_prob, market_prob, won
FROM pre_race
WHERE (has_today = 1 AND snapshot = 'today') OR (has_today = 0 AND snapshot = 't-1')
"""


def clean(rows: pd.DataFrame) -> pd.DataFrame:
  """Races with exactly one winner and two or more runners, every probability
  above 0; each race's runners together, in date order."""
  rows = rows.copy()
  rows["race_date"] = pd.to_datetime(rows["race_date"])
  for column in ["model_prob", "market_prob"]:
    rows[column] = pd.to_numeric(rows[column])
  rows["won"] = rows["won"].astype(str).str.lower().isin(["true", "1"])
  rows = rows[(rows["model_prob"] > 0) & (rows["market_prob"] > 0)]
  per_race = rows.groupby(["market", "race_id"]).agg(winners=("won", "sum"), runners=("ride_id", "count"))
  usable = per_race[(per_race["winners"] == 1) & (per_race["runners"] >= 2)].index
  rows = rows.set_index(["market", "race_id"]).loc[lambda df: df.index.isin(usable)].reset_index()
  return rows.sort_values(["market", "race_date", "race_id", "ride_id"]).reset_index(drop=True)


def to_races(rows: pd.DataFrame) -> Races:
  """One market's rows (from clean) as a Races block with inputs ln(ours), ln(market)."""
  inputs = np.column_stack([np.log(rows["model_prob"].to_numpy(float)), np.log(rows["market_prob"].to_numpy(float))])
  race_ids = rows["race_id"].to_numpy()
  is_new_race = np.ones(len(race_ids), dtype=bool)
  is_new_race[1:] = race_ids[1:] != race_ids[:-1]
  return Races(inputs, np.flatnonzero(is_new_race), np.flatnonzero(rows["won"].to_numpy()))


def split_by_date(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
  """Earlier days to fit on, the last TEST_SHARE of the days to test on."""
  days = np.sort(rows["race_date"].unique())
  first_test_day = days[int(len(days) * (1 - TEST_SHARE))]
  return rows[rows["race_date"] < first_test_day], rows[rows["race_date"] >= first_test_day]


def own_probabilities(races: Races, column: int) -> np.ndarray:
  """Ours (column 0) or the market's (column 1), back from the logs."""
  return np.exp(races.inputs[:, column])


@dataclass
class MarketFit:
  market: str
  races: int
  first_day: str
  last_day: str
  adopted: bool
  reason: str
  model_weight: float | None = None
  market_weight: float | None = None
  test: dict | None = None  # log-losses and differences on the later days


def fit_market(rows: pd.DataFrame, market: str) -> MarketFit:
  races = int(rows["race_id"].nunique())
  first_day = f"{rows['race_date'].min():%Y-%m-%d}" if races else ""
  last_day = f"{rows['race_date'].max():%Y-%m-%d}" if races else ""
  if races == 0:
    return MarketFit(market, 0, "", "", False, "no out-of-sample races yet")

  fit_rows, test_rows = split_by_date(rows)
  if fit_rows.empty or test_rows.empty:
    return MarketFit(market, races, first_day, last_day, False, "too few race days to test on")

  weights = fit_weights(to_races(fit_rows), 0.0)
  test_races = to_races(test_rows)
  blended = win_probabilities(weights, test_races)
  ours = own_probabilities(test_races, 0)
  theirs = own_probabilities(test_races, 1)
  test = {
    "races": test_races.race_count,
    "from": f"{test_rows['race_date'].min():%Y-%m-%d}",
    "log_loss_blend": evaluate.log_loss(blended, test_races),
    "log_loss_model": evaluate.log_loss(ours, test_races),
    "log_loss_market": evaluate.log_loss(theirs, test_races),
    "vs_market": evaluate.log_loss_difference(blended, theirs, test_races),
    "vs_model": evaluate.log_loss_difference(blended, ours, test_races),
    "fit_weights": [float(weights[0]), float(weights[1])],
  }

  beats_market = test["vs_market"]["mean"] < 0
  if races < MIN_RACES:
    adopted, reason = False, f"not enough races yet ({races} of {MIN_RACES})"
  elif not beats_market:
    adopted, reason = False, "doesn't beat the market on the later days"
  else:
    adopted, reason = True, "beats the market on the later days"

  # Published weights: refitted on every race (reported either way, to watch them settle).
  model_weight, market_weight = fit_weights(to_races(rows), 0.0)
  return MarketFit(market, races, first_day, last_day, adopted, reason, float(model_weight), float(market_weight), test)


@dataclass
class BlendResult:
  blend: dict | None  # what goes in model/blend.json; None = no market adopted
  fits: list[MarketFit]
  report: str


def train_blend(raw_rows: pd.DataFrame, version: str, created_at: str) -> BlendResult:
  rows = clean(raw_rows) if len(raw_rows) else raw_rows
  fits = []
  for market in MARKETS:
    market_rows = rows[rows["market"] == market] if len(rows) else rows
    fits.append(fit_market(market_rows, market))

  adopted = [fit for fit in fits if fit.adopted]
  blend = None
  if adopted:
    blend = {
      "version": version,
      "created_at": created_at,
      "markets": {
        fit.market: {
          "model_weight": fit.model_weight,
          "market_weight": fit.market_weight,
          "races": fit.races,
          "from": fit.first_day,
          "to": fit.last_day,
          "test": fit.test,
        }
        for fit in adopted
      },
    }
  return BlendResult(blend, fits, render_report(fits, blend))


def render_report(fits: list[MarketFit], blend: dict | None) -> str:
  if blend is None:
    decision = "**No blend published**: the flag keeps using our probability."
  else:
    decision = f"**Blend published** for {', '.join(blend['markets'])}: the flag uses the blended probability there."

  rows = []
  for fit in fits:
    test = fit.test or {}
    vs_market = test.get("vs_market")
    rows.append([
      fit.market,
      fit.races,
      f"{fit.first_day} to {fit.last_day}" if fit.races else "",
      "" if fit.model_weight is None else f"{fit.model_weight:+.3f}",
      "" if fit.market_weight is None else f"{fit.market_weight:+.3f}",
      "" if not test else f"{test['log_loss_blend']:.4f} / {test['log_loss_model']:.4f} / {test['log_loss_market']:.4f}",
      "" if vs_market is None else f"{vs_market['mean']:+.4f} ± {vs_market['se']:.4f}",
      ("**adopted**: " if fit.adopted else "") + fit.reason,
    ])
  header = ["Market", "Races", "Dates", "Model weight", "Market weight",
            "Test log-loss blend / ours / market", "Blend minus market", ""]
  table = "\n".join(
    ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    + ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
  )
  return (
    "## Blend\n\n"
    "Our probability and the market's combined per race: score = model weight x ln(ours) + market weight x "
    "ln(market's), softmaxed. Fitted on the earlier out-of-sample race days, tested on the last "
    f"{TEST_SHARE:.0%} of them; adopted with {MIN_RACES}+ races if it beats the market there. Weights shown are "
    "refitted on every race.\n\n"
    f"{decision}\n\n{table}\n"
  )
