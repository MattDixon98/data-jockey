"""The blend on synthetic races: winners drawn from a known blend of our
probability and the market's, so the fit should find those weights again."""

import json

import numpy as np
import pandas as pd

from data_jockey_model import blend


def _softmax_by_race(scores, race_ids):
  frame = pd.DataFrame({"s": scores, "r": race_ids})
  shifted = np.exp(frame["s"] - frame.groupby("r")["s"].transform("max"))
  return (shifted / shifted.groupby(frame["r"]).transform("sum")).to_numpy()


def make_rows(model_weight, market_weight, races=1500, field=8, races_per_day=30, seed=3, markets=("forecast", "SP")):
  """Rows shaped like blend_query's: per race, a market and a model probability
  (the model a noisy copy of the market) and a winner drawn from the blend."""
  rng = np.random.default_rng(seed)
  race_ids = np.repeat(np.arange(races), field)
  market_scores = rng.normal(scale=1.0, size=len(race_ids))
  model_scores = 0.6 * market_scores + rng.normal(scale=0.6, size=len(race_ids))
  market_prob = _softmax_by_race(market_scores, race_ids)
  model_prob = _softmax_by_race(model_scores, race_ids)
  true_prob = _softmax_by_race(model_weight * np.log(model_prob) + market_weight * np.log(market_prob), race_ids)

  won = np.zeros(len(race_ids), dtype=bool)
  for race in range(races):
    rows = np.arange(race * field, (race + 1) * field)
    won[rng.choice(rows, p=true_prob[rows] / true_prob[rows].sum())] = True
  dates = pd.Timestamp("2026-11-13") + pd.to_timedelta(race_ids // races_per_day, unit="D")
  frames = []
  for market in markets:
    frames.append(pd.DataFrame({
      "market": market,
      "race_id": race_ids,
      "ride_id": np.arange(len(race_ids)),
      "race_date": dates.strftime("%Y-%m-%d"),
      "model_prob": model_prob,
      "market_prob": market_prob,
      "won": won,
    }))
  return pd.concat(frames, ignore_index=True)


def _fit(result, market):
  return next(fit for fit in result.fits if fit.market == market)


def test_fit_recovers_the_weights():
  result = blend.train_blend(make_rows(0.5, 0.7, races=4000), "2026-12-15", "2026-12-15T08:30:00+00:00")
  fit = _fit(result, "forecast")
  assert abs(fit.model_weight - 0.5) < 0.1
  assert abs(fit.market_weight - 0.7) < 0.1


def test_adopted_when_it_beats_the_market_with_enough_races():
  result = blend.train_blend(make_rows(0.5, 0.7), "2026-12-15", "2026-12-15T08:30:00+00:00")
  assert result.blend is not None
  assert set(result.blend["markets"]) == {"forecast", "SP"}
  forecast = result.blend["markets"]["forecast"]
  assert forecast["test"]["vs_market"]["mean"] < 0
  assert forecast["races"] == 1500
  assert json.loads(json.dumps(result.blend)) == result.blend
  # The shape the glue rebuild checks (data_jockey.models.check_blend).
  for weights in result.blend["markets"].values():
    assert isinstance(weights["model_weight"], float) and isinstance(weights["market_weight"], float)
  assert "**Blend published**" in result.report


def test_not_adopted_below_the_minimum_races():
  result = blend.train_blend(make_rows(0.5, 0.7, races=500), "2026-12-15", "2026-12-15T08:30:00+00:00")
  assert result.blend is None
  fit = _fit(result, "forecast")
  assert not fit.adopted
  assert fit.reason == "not enough races yet (500 of 1000)"
  assert fit.model_weight is not None  # still fitted and reported, to watch it settle
  assert "No blend published" in result.report


def test_not_adopted_when_our_probability_adds_nothing():
  # Winners follow the market alone: the blend can't beat it on later days.
  result = blend.train_blend(make_rows(0.0, 1.0, races=2000, seed=5), "2026-12-15", "2026-12-15T08:30:00+00:00")
  fit = _fit(result, "forecast")
  assert abs(fit.model_weight) < 0.15
  assert not fit.adopted
  assert fit.reason == "doesn't beat the market on the later days"


def test_only_the_markets_that_qualify_are_published():
  rows = pd.concat([
    make_rows(0.5, 0.7, markets=("forecast",)),
    make_rows(0.5, 0.7, races=300, markets=("SP",)),
  ], ignore_index=True)
  result = blend.train_blend(rows, "2026-12-15", "2026-12-15T08:30:00+00:00")
  assert set(result.blend["markets"]) == {"forecast"}


def test_clean_drops_dead_heats_and_zero_probabilities():
  rows = pd.DataFrame({
    "market": "forecast",
    "race_id": [1, 1, 2, 2, 3, 3],
    "ride_id": [1, 2, 3, 4, 5, 6],
    "race_date": "2026-11-20",
    "model_prob": [0.5, 0.5, 0.5, 0.5, 0.0, 1.0],
    "market_prob": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
    "won": ["true", "true", "true", "false", "false", "true"],
  })
  cleaned = blend.clean(rows)
  # Race 1: dead heat; race 3: a zero probability leaves one runner.
  assert set(cleaned["race_id"]) == {2}


def test_no_rows_yet_means_no_blend():
  empty = pd.DataFrame(columns=["market", "race_id", "ride_id", "race_date", "model_prob", "market_prob", "won"])
  result = blend.train_blend(empty, "2026-12-15", "2026-12-15T08:30:00+00:00")
  assert result.blend is None
  assert all(fit.reason == "no out-of-sample races yet" for fit in result.fits)


def test_query_reads_out_of_sample_settled_value_rows():
  sql = blend.blend_query("data_jockey")
  assert "data_jockey.model_value" in sql
  assert "NOT in_sample" in sql and "won IS NOT NULL" in sql
