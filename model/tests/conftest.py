"""Synthetic races: runners with random inputs, winners drawn from the model
itself with known weights, so a correct fit must find those weights again."""

import numpy as np
import pandas as pd
import pytest

from data_jockey_model.fit import Races


def make_races(true_weights, race_count=3000, field=8, seed=1) -> Races:
  rng = np.random.default_rng(seed)
  sizes = rng.integers(2, field + 1, size=race_count)
  inputs = rng.normal(size=(sizes.sum(), len(true_weights)))
  starts = np.cumsum(sizes) - sizes

  scores = inputs @ np.asarray(true_weights)
  winner_rows = []
  for start, size in zip(starts, sizes):
    race_scores = scores[start:start + size]
    probs = np.exp(race_scores - race_scores.max())
    probs /= probs.sum()
    winner_rows.append(start + rng.choice(size, p=probs))
  return Races(inputs, starts, np.array(winner_rows))


def make_rows(inputs: dict, true_weights, aliases: dict, days=100, races_per_day=30, seed=2) -> pd.DataFrame:
  """Rows shaped like the Athena training query, one column per alias, with
  winners drawn from the true weights and a noisy SP."""
  races = make_races(true_weights, race_count=days * races_per_day, seed=seed)
  rng = np.random.default_rng(seed)
  sizes = races.sizes
  race_ids = np.repeat(np.arange(len(sizes)), sizes)
  dates = pd.Timestamp("2026-08-01") + pd.to_timedelta(race_ids // races_per_day, unit="D")

  finish = np.full(len(race_ids), 2.0)
  finish[races.winner_rows] = 1.0
  true_scores = races.inputs @ np.asarray(true_weights)
  noisy = np.exp(true_scores + rng.normal(scale=0.3, size=len(true_scores)))
  totals = np.add.reduceat(noisy, races.starts)
  sp_probs = noisy / np.repeat(totals, sizes) / 1.15  # 15% overround
  rows = pd.DataFrame({
    "ride_id": np.arange(len(race_ids)),
    "race_id": race_ids,
    "race_date": dates.strftime("%Y-%m-%d"),
    "finish_position": finish,
    "sp_decimal": 1.0 / sp_probs,
  })
  for column, sql in zip(range(races.inputs.shape[1]), inputs.values()):
    rows[aliases[sql]] = races.inputs[:, column]
  return rows


@pytest.fixture
def small_inputs():
  return {"a": "col_a", "b": "col_b", "c": "col_c"}


TRUE_WEIGHTS = [0.8, -0.5, 0.0]
