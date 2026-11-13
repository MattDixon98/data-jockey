"""The training data: the Athena query, and turning its rows into races.

Training uses the past snapshot of runner_features (the features as they
stood before each race, plus its official finish_position), for complete
races only, with SP from runners for the comparison. SP is never a model
input.

Each distinct input SQL expression gets a short column alias (x0, x1...), so
the same query can carry the inputs of two models (the candidate and the
current one) even when they differ.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data_jockey_model.fit import Races


def input_aliases(*input_sets: dict[str, str]) -> dict[str, str]:
  """SQL expression -> column alias, for every distinct expression."""
  aliases: dict[str, str] = {}
  for inputs in input_sets:
    for sql in inputs.values():
      if sql not in aliases:
        aliases[sql] = f"x{len(aliases)}"
  return aliases


def training_query(database: str, aliases: dict[str, str]) -> str:
  """Past-snapshot runners of complete races, with every input and SP.

  The inputs are evaluated against runner_features alone (inside the CTE), so
  their column names can't clash with races or runners columns."""
  input_columns = ",\n    ".join(f"CAST({sql} AS DOUBLE) AS {alias}" for sql, alias in aliases.items())
  return f"""
WITH features AS (
  SELECT
    ride_id,
    race_id,
    race_date,
    finish_position,
    {input_columns}
  FROM {database}.runner_features
  WHERE snapshot = 'past'
)
SELECT
  features.*,
  runners.odds_decimal AS sp_decimal
FROM features
JOIN {database}.races races
  ON races.race_id = features.race_id
  AND races.result_status = 'complete'
JOIN {database}.runners runners
  ON runners.ride_id = features.ride_id
"""


def clean_races(rows: pd.DataFrame) -> pd.DataFrame:
  """Races the model can learn from: exactly one winner (no dead heats, no
  missing result) and at least two runners. Sorted by date then race, so
  each race's runners are contiguous."""
  rows = rows.copy()
  rows["race_date"] = pd.to_datetime(rows["race_date"])
  rows["is_winner"] = rows["finish_position"] == 1

  per_race = rows.groupby("race_id").agg(
    winners=("is_winner", "sum"),
    runners=("ride_id", "count"),
  )
  usable = per_race[(per_race["winners"] == 1) & (per_race["runners"] >= 2)].index
  rows = rows[rows["race_id"].isin(usable)]
  return rows.sort_values(["race_date", "race_id", "ride_id"]).reset_index(drop=True)


def to_races(rows: pd.DataFrame, inputs: dict[str, str], aliases: dict[str, str]) -> Races:
  """One model's inputs as a Races block. `rows` must come from clean_races."""
  columns = [aliases[sql] for sql in inputs.values()]
  matrix = rows[columns].to_numpy(dtype=float)
  if np.isnan(matrix).any():
    raise ValueError("model inputs contain NULLs; runner_features should never have them")

  race_ids = rows["race_id"].to_numpy()
  is_new_race = np.ones(len(race_ids), dtype=bool)
  is_new_race[1:] = race_ids[1:] != race_ids[:-1]
  starts = np.flatnonzero(is_new_race)
  winner_rows = np.flatnonzero(rows["is_winner"].to_numpy())
  return Races(matrix, starts, winner_rows)
