"""One training run, from query rows to a candidate model and a report.

1. Clean the rows (one winner, 2+ runners) and drop the warm-up weeks, when
   jockey and trainer rates had almost no history behind them.
2. Split by date: train, then validate (the next two weeks), then test (the
   last two weeks). Never shuffled: the model is always judged on races after
   the ones it learnt from, as it will be when it prices tomorrow's races.
3. Pick the penalty: fit on train with each L2 value, keep the one with the
   lowest log-loss on validate.
4. Test: fit on train + validate with that penalty and score the test weeks.
   The current model (if any) is scored on the same weeks.
5. Decide: the candidate is promoted if it beats the current model on test
   (or if there is no current model).
6. Refit on every usable race with that penalty: those are the published
   weights. The test numbers describe how well the method works.

`compare()` runs steps 1-4 for any two sets of inputs on the same split:
scripts/train_local.py's --add/--drop, to try a change locally.

Models are plain dicts (the weights JSON): each input's name, SQL, mean,
spread and weight, plus the penalty, date range and test scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from data_jockey_model import evaluate
from data_jockey_model.data import clean_races, to_races
from data_jockey_model.fit import Races, Standardiser, fit_weights, win_probabilities

WARMUP_DAYS = 21
VALIDATE_DAYS = 14
TEST_DAYS = 14
# Wide enough that the chosen value lands inside the range, not at an end.
L2_GRID = [0.001, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0]


@dataclass
class Split:
  train: pd.DataFrame
  validate: pd.DataFrame
  test: pd.DataFrame

  @property
  def train_and_validate(self) -> pd.DataFrame:
    return pd.concat([self.train, self.validate], ignore_index=True)

  @property
  def everything(self) -> pd.DataFrame:
    return pd.concat([self.train, self.validate, self.test], ignore_index=True)


@dataclass
class Tested:
  """One set of inputs fitted on train + validate and scored on test."""

  inputs: dict[str, str]
  l2: float
  validation_scores: dict[float, float]
  model: dict
  probs: np.ndarray
  scores: dict


@dataclass
class Comparison:
  baseline: Tested
  variant: Tested
  races: Races
  difference: dict  # evaluate.log_loss_difference(variant, baseline)


@dataclass
class TrainingResult:
  model: dict
  report: str
  promote: bool


def split_by_date(rows: pd.DataFrame) -> Split:
  """Drop the warm-up, then train / validate / test in date order."""
  first_day = rows["race_date"].min()
  last_day = rows["race_date"].max()
  test_start = last_day - timedelta(days=TEST_DAYS - 1)
  validate_start = test_start - timedelta(days=VALIDATE_DAYS)
  train_start = first_day + timedelta(days=WARMUP_DAYS)

  dates = rows["race_date"]
  split = Split(
    train=rows[(dates >= train_start) & (dates < validate_start)].reset_index(drop=True),
    validate=rows[(dates >= validate_start) & (dates < test_start)].reset_index(drop=True),
    test=rows[dates >= test_start].reset_index(drop=True),
  )
  if split.train.empty:
    raise ValueError(f"no training races between {train_start:%Y-%m-%d} and {validate_start:%Y-%m-%d}")
  return split


def fit_model(rows: pd.DataFrame, inputs: dict[str, str], aliases: dict[str, str], l2: float) -> tuple[Standardiser, np.ndarray]:
  races = to_races(rows, inputs, aliases)
  standardiser = Standardiser.fit(races.inputs)
  weights = fit_weights(standardiser.apply(races), l2)
  return standardiser, weights


def model_dict(inputs: dict[str, str], standardiser: Standardiser, weights: np.ndarray) -> dict:
  return {
    "inputs": [
      {"name": name, "sql": sql, "mean": float(mean), "std": float(std), "weight": float(weight)}
      for (name, sql), mean, std, weight in zip(inputs.items(), standardiser.means, standardiser.stds, weights)
    ],
  }


def model_probabilities(model: dict, rows: pd.DataFrame, aliases: dict[str, str]) -> tuple[np.ndarray, Races]:
  """A saved model's win probabilities for `rows`, exactly as Glue will score
  them: standardise each input with the model's own mean and spread, weight,
  sum, softmax per race."""
  inputs = {item["name"]: item["sql"] for item in model["inputs"]}
  races = to_races(rows, inputs, aliases)
  standardiser = Standardiser(
    means=np.array([item["mean"] for item in model["inputs"]]),
    stds=np.array([item["std"] for item in model["inputs"]]),
  )
  weights = np.array([item["weight"] for item in model["inputs"]])
  return win_probabilities(weights, standardiser.apply(races)), races


def choose_l2(split: Split, inputs: dict[str, str], aliases: dict[str, str]) -> tuple[float, dict[float, float]]:
  """The penalty with the lowest validation log-loss, and every score tried."""
  scores = {}
  for l2 in L2_GRID:
    standardiser, weights = fit_model(split.train, inputs, aliases, l2)
    model = model_dict(inputs, standardiser, weights)
    probs, races = model_probabilities(model, split.validate, aliases)
    scores[l2] = evaluate.log_loss(probs, races)
  best = min(scores, key=scores.get)
  return best, scores


def date_range(rows: pd.DataFrame) -> dict:
  return {
    "from": f"{rows['race_date'].min():%Y-%m-%d}",
    "to": f"{rows['race_date'].max():%Y-%m-%d}",
    "races": int(rows["race_id"].nunique()),
    "runners": int(len(rows)),
  }


def fit_and_test(split: Split, inputs: dict[str, str], aliases: dict[str, str]) -> tuple[Tested, Races]:
  """Steps 3-4 for one set of inputs."""
  l2, validation_scores = choose_l2(split, inputs, aliases)
  standardiser, weights = fit_model(split.train_and_validate, inputs, aliases, l2)
  model = model_dict(inputs, standardiser, weights)
  probs, races = model_probabilities(model, split.test, aliases)
  sp_decimal = split.test["sp_decimal"].to_numpy(dtype=float)
  scores = evaluate.scorecard(probs, sp_decimal, races)
  return Tested(inputs, l2, validation_scores, model, probs, scores), races


def prepare(raw_rows: pd.DataFrame) -> Split:
  split = split_by_date(clean_races(raw_rows))
  if split.validate.empty or split.test.empty:
    raise ValueError("not enough recent races for the validate and test weeks")
  return split


def compare_on(split: Split, baseline: dict[str, str], variant: dict[str, str], aliases: dict[str, str]) -> Comparison:
  tested_baseline, races = fit_and_test(split, baseline, aliases)
  tested_variant, _ = fit_and_test(split, variant, aliases)
  difference = evaluate.log_loss_difference(tested_variant.probs, tested_baseline.probs, races)
  return Comparison(tested_baseline, tested_variant, races, difference)


def compare(raw_rows: pd.DataFrame, baseline: dict[str, str], variant: dict[str, str], aliases: dict[str, str]) -> tuple[Comparison, str]:
  """Two sets of inputs on the same split, and a report of the difference."""
  split = prepare(raw_rows)
  comparison = compare_on(split, baseline, variant, aliases)
  return comparison, render_comparison(split, comparison)


def train(
  raw_rows: pd.DataFrame,
  inputs: dict[str, str],
  aliases: dict[str, str],
  current: dict | None,
  version: str,
  created_at: str,
) -> TrainingResult:
  split = prepare(raw_rows)
  candidate, test_races = fit_and_test(split, inputs, aliases)

  current_scores = None
  if current is not None:
    current_probs, _ = model_probabilities(current, split.test, aliases)
    sp_decimal = split.test["sp_decimal"].to_numpy(dtype=float)
    current_scores = evaluate.scorecard(current_probs, sp_decimal, test_races)
  promote = current_scores is None or candidate.scores["log_loss"] < current_scores["log_loss"]

  standardiser, weights = fit_model(split.everything, inputs, aliases, candidate.l2)
  model = {
    "version": version,
    "created_at": created_at,
    "l2": candidate.l2,
    "trained_on": date_range(split.everything),
    **model_dict(inputs, standardiser, weights),
    "test": {**date_range(split.test), **{k: v for k, v in candidate.scores.items() if k != "calibration"}},
  }

  report = render_report(model, split, candidate, current, current_scores, promote)
  return TrainingResult(model=model, report=report, promote=promote)


# --- Report -------------------------------------------------------------------


def _table(header: list[str], rows: list[list]) -> str:
  lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
  lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
  return "\n".join(lines)


def describe_difference(difference: dict, baseline_label: str) -> str:
  """e.g. "-0.0123 ± 0.0050 per race against the current inputs: better, beyond noise"."""
  mean, se = difference["mean"], difference["se"]
  if se == 0 and mean == 0:
    verdict = "identical"
  elif abs(mean) <= 2 * se:
    verdict = "within noise (less than 2 standard errors)"
  elif mean < 0:
    verdict = "better, beyond noise"
  else:
    verdict = "worse, beyond noise"
  return f"{mean:+.4f} ± {se:.4f} (standard error) per race against {baseline_label}, over {difference['races']} races: {verdict}"


def periods_table(split: Split, published: dict | None = None) -> str:
  periods = [
    ["Train", *date_range(split.train).values()],
    ["Validate", *date_range(split.validate).values()],
    ["Test", *date_range(split.test).values()],
  ]
  if published is not None:
    periods.append(["Published weights", *published.values()])
  return _table(["Period", "From", "To", "Races", "Runners"], periods)


def scores_table(columns: list[tuple[str, dict]]) -> str:
  """Test-week scores side by side; SP and random come from the first column
  (they don't depend on the model)."""
  first = columns[0][1]
  header = [""] + [label for label, _ in columns] + ["SP", "Random"]
  def row(label: str, key: str, sp_key: str | None, random_key: str | None, fmt: str) -> list:
    cells = [label] + [format(scores[key], fmt) for _, scores in columns]
    cells.append(format(first[sp_key], fmt) if sp_key else "")
    cells.append(format(first[random_key], fmt) if random_key else "")
    return cells
  return _table(header, [
    row("Log-loss per race (all test races)", "log_loss", None, "random_log_loss", ".4f"),
    row("Log-loss per race (races with SP)", "log_loss_priced", "sp_log_loss_priced", None, ".4f"),
    row("Top pick won", "top_pick_win_rate", "sp_favourite_win_rate", None, ".1%"),
  ])


def weights_table(model: dict) -> str:
  by_size = sorted(model["inputs"], key=lambda item: abs(item["weight"]), reverse=True)
  rows = [
    [item["name"], f"{item['weight']:+.3f}", f"{item['weight'] / item['std']:+.4f}", f"`{item['sql']}`"]
    for item in by_size
  ]
  return (
    "Standardised: the effect of a one-spread change in the input, comparable across inputs. "
    "Per unit: the effect of +1 in the input's own units (e.g. per lb).\n\n"
    + _table(["Input", "Standardised", "Per unit", "SQL"], rows)
  )


def penalty_table(tested: Tested) -> str:
  rows = [
    [l2, f"{score:.4f}", "chosen" if l2 == tested.l2 else ""] for l2, score in tested.validation_scores.items()
  ]
  return _table(["L2", "Validation log-loss", ""], rows)


def render_report(
  model: dict,
  split: Split,
  candidate: Tested,
  current: dict | None,
  current_scores: dict | None,
  promote: bool,
) -> str:
  if current is None:
    decision = "**Promoted**: first model, nothing to beat."
  elif promote:
    decision = (
      f"**Promoted**: test log-loss {candidate.scores['log_loss']:.4f} beats the current model "
      f"({current['version']}) at {current_scores['log_loss']:.4f}."
    )
  else:
    decision = (
      f"**Not promoted**: test log-loss {candidate.scores['log_loss']:.4f} doesn't beat the current model "
      f"({current['version']}) at {current_scores['log_loss']:.4f}."
    )

  columns = [("This model", candidate.scores)]
  if current_scores is not None:
    columns.append(("Current model", current_scores))

  calibration_rows = [
    [band["band"], band["runners"], f"{band['predicted']:.1%}", f"{band['actual']:.1%}"]
    for band in candidate.scores["calibration"]
  ]

  return "\n\n".join([
    f"# Model {model['version']}",
    decision,
    "## Data\n\n" + periods_table(split, model["trained_on"]),
    "## Penalty (L2), chosen on the validation weeks\n\n" + penalty_table(candidate),
    "## Test weeks\n\nLower log-loss is better. SP has its margin removed with Shin's method.\n\n"
    + scores_table(columns),
    "## Calibration (test weeks)\n\nRunners grouped by the probability this model gave them, and how often they won.\n\n"
    + _table(["Predicted", "Runners", "Average predicted", "Actually won"], calibration_rows),
    "## Weights (published)\n\n" + weights_table(model),
  ]) + "\n"


def render_comparison(split: Split, comparison: Comparison) -> str:
  """train_local.py --add/--drop: is the variant better than the baseline?"""
  baseline, variant = comparison.baseline, comparison.variant
  added = [name for name in variant.inputs if name not in baseline.inputs]
  dropped = [name for name in baseline.inputs if name not in variant.inputs]
  changed = [
    name for name in variant.inputs
    if name in baseline.inputs and variant.inputs[name] != baseline.inputs[name]
  ]
  changes = (
    [f"- added `{name}`: `{variant.inputs[name]}`" for name in added]
    + [f"- dropped `{name}`" for name in dropped]
    + [f"- changed `{name}`: `{variant.inputs[name]}`" for name in changed]
  )

  return "\n\n".join([
    "# Input comparison",
    "\n".join(changes) if changes else "No changes to the inputs.",
    "Variant minus baseline, test log-loss: " + describe_difference(comparison.difference, "the baseline")
    + ". Negative is better.",
    "## Data\n\n" + periods_table(split),
    "## Test weeks\n\nBoth fitted on train + validate with their own penalty "
    f"(baseline L2 {baseline.l2}, variant L2 {variant.l2}).\n\n"
    + scores_table([("Variant", variant.scores), ("Baseline", baseline.scores)]),
    "## Variant weights (fitted on train + validate)\n\n" + weights_table(variant.model),
  ]) + "\n"
