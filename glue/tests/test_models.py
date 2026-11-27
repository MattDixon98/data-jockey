"""Checking model files and choosing which model prices which race."""

import copy
import json

import pytest

from conftest import FIXTURES
from data_jockey.models import ModelError, check_blend, check_model, date_ranges, usable_models

MODEL = json.loads((FIXTURES / "model" / "2026-11-13.json").read_text())


def _model(version, trained_to):
  model = copy.deepcopy(MODEL)
  model["version"] = version
  model["trained_on"]["to"] = trained_to
  return model


def test_real_model_passes():
  assert check_model(MODEL, "fixture") is MODEL


@pytest.mark.parametrize(
  "break_it, message",
  [
    (lambda m: m.pop("inputs"), "missing ['inputs']"),
    (lambda m: m["trained_on"].pop("to"), "no 'to' date"),
    (lambda m: m.update(inputs=[]), "no inputs"),
    (lambda m: m["inputs"][0].pop("weight"), "missing ['weight']"),
    (lambda m: m["inputs"][0].update(std=0.0), "std 0.0"),
  ],
)
def test_broken_models_say_what_is_wrong(break_it, message):
  model = copy.deepcopy(MODEL)
  break_it(model)
  with pytest.raises(ModelError, match="s3://bucket/model/x.json") as error:
    check_model(model, "s3://bucket/model/x.json")
  assert message in str(error.value)


def test_no_models_points_at_the_training_job():
  with pytest.raises(ModelError, match="data-jockey-train-model"):
    usable_models({})


def test_current_json_and_its_promoted_copy_count_once():
  latest = _model("2026-12-01", "2026-11-30")
  models = usable_models({
    "model/current.json": latest,
    "model/promoted/2026-12-01.json": latest,
    "model/promoted/2026-11-13.json": MODEL,
  })
  assert [m["version"] for m in models] == ["2026-11-13", "2026-12-01"]


def test_date_ranges_hand_over_when_training_ends():
  first, second, third = _model("a", "2026-11-12"), _model("b", "2026-11-30"), _model("c", "2026-12-31")
  ranges = [(m["version"], after, up_to) for m, after, up_to in date_ranges([first, second, third])]
  assert ranges == [
    ("a", None, "2026-11-30"),  # everything up to the day b's training ends
    ("b", "2026-11-30", "2026-12-31"),
    ("c", "2026-12-31", None),
  ]


def test_single_model_prices_everything():
  assert [(after, up_to) for _, after, up_to in date_ranges([MODEL])] == [(None, None)]


BLEND = {
  "version": "2026-12-15",
  "markets": {
    "forecast": {"model_weight": 0.48, "market_weight": 0.61},
    "SP": {"model_weight": 0.0, "market_weight": 1.0},
  },
}


def test_blend_passes():
  assert check_blend(copy.deepcopy(BLEND), "s3://bucket/model/blend.json") == BLEND


@pytest.mark.parametrize(
  "break_it, message",
  [
    (lambda b: b.pop("version"), "missing 'version'"),
    (lambda b: b.update(markets={}), "no markets"),
    (lambda b: b["markets"].update(tote={"model_weight": 1, "market_weight": 1}), "unknown market 'tote'"),
    (lambda b: b["markets"]["SP"].pop("market_weight"), "SP has no number for 'market_weight'"),
    (lambda b: b["markets"]["forecast"].update(model_weight="0.5"), "forecast has no number for 'model_weight'"),
  ],
)
def test_broken_blend_says_what_is_wrong(break_it, message):
  blend = copy.deepcopy(BLEND)
  break_it(blend)
  with pytest.raises(ModelError, match="blend.json") as error:
    check_blend(blend, "s3://bucket/model/blend.json")
  assert message in str(error.value)
