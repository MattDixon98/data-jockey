import json

import numpy as np

from conftest import TRUE_WEIGHTS, make_rows
from data_jockey_model import pipeline
from data_jockey_model.data import input_aliases


def _train(small_inputs, current=None, seed=2):
  aliases = input_aliases(small_inputs, {} if current is None else {i["name"]: i["sql"] for i in current["inputs"]})
  rows = make_rows(small_inputs, TRUE_WEIGHTS, aliases, seed=seed)
  return pipeline.train(rows, small_inputs, aliases, current, "2026-12-01", "2026-12-01T08:30:00+00:00")


def test_split_is_in_date_order_after_the_warm_up(small_inputs):
  aliases = input_aliases(small_inputs)
  rows = make_rows(small_inputs, TRUE_WEIGHTS, aliases)
  from data_jockey_model.data import clean_races
  split = pipeline.split_by_date(clean_races(rows))
  first = clean_races(rows)["race_date"].min()
  assert split.train["race_date"].min() >= first + np.timedelta64(pipeline.WARMUP_DAYS, "D")
  assert split.train["race_date"].max() < split.validate["race_date"].min()
  assert split.validate["race_date"].max() < split.test["race_date"].min()
  assert split.test["race_date"].nunique() == pipeline.TEST_DAYS


def test_first_model_is_promoted_and_learns_the_weights(small_inputs):
  result = _train(small_inputs)
  assert result.promote
  weights = {i["name"]: i["weight"] / i["std"] for i in result.model["inputs"]}
  assert abs(weights["a"] - 0.8) < 0.1
  assert abs(weights["b"] + 0.5) < 0.1
  assert abs(weights["c"]) < 0.1
  test = result.model["test"]
  assert test["log_loss"] < test["random_log_loss"]
  assert "Promoted" in result.report


def test_worse_current_model_is_replaced(small_inputs):
  current = _train(small_inputs).model
  for item in current["inputs"]:
    item["weight"] = -item["weight"]  # backwards
  result = _train(small_inputs, current=current, seed=3)
  assert result.promote


def test_better_current_model_is_kept(small_inputs):
  current = _train(small_inputs).model
  # A "candidate" that can't learn anything useful: inputs are pure noise.
  noise_inputs = {"n1": "noise_1", "n2": "noise_2", "n3": "noise_3"}
  aliases = input_aliases(noise_inputs, {i["name"]: i["sql"] for i in current["inputs"]})
  rows = make_rows(small_inputs, TRUE_WEIGHTS, aliases, seed=3)
  rng = np.random.default_rng(0)
  for sql in noise_inputs.values():
    rows[aliases[sql]] = rng.normal(size=len(rows))
  result = pipeline.train(rows, noise_inputs, aliases, current, "2027-01-01", "2027-01-01T08:30:00+00:00")
  assert not result.promote
  assert "Not promoted" in result.report


def test_model_json_round_trips(small_inputs):
  model = _train(small_inputs).model
  assert json.loads(json.dumps(model)) == model
  assert [i["name"] for i in model["inputs"]] == list(small_inputs)
  for item in model["inputs"]:
    assert set(item) == {"name", "sql", "mean", "std", "weight"}
