import pandas as pd
import pytest

from data_jockey_model.data import clean_races, input_aliases, to_races, training_query
from data_jockey_model.inputs import INPUTS


def test_aliases_are_shared_between_models():
  current = {"old_name": INPUTS["rating_diff"], "dropped": "some_old_sql"}
  aliases = input_aliases(INPUTS, current)
  assert len(aliases) == len(set(INPUTS.values())) + 1
  assert aliases[INPUTS["rating_diff"]] == "x0"


def test_query_selects_every_input_from_past_rows():
  aliases = input_aliases(INPUTS)
  sql = training_query("data_jockey", aliases)
  assert "snapshot = 'past'" in sql
  assert "result_status = 'complete'" in sql
  for expression, alias in aliases.items():
    assert f"CAST({expression} AS DOUBLE) AS {alias}" in sql


def test_inputs_are_unique_and_plain_sql():
  assert len(set(INPUTS.values())) == len(INPUTS)
  for sql in INPUTS.values():
    # Spark-only or Trino-only syntax would break one side.
    for forbidden in ("::", "`", "log1p", "IF(", "TRY_CAST"):
      assert forbidden not in sql


def _rows(race_id, finishes, date="2026-09-01"):
  return [
    {"ride_id": race_id * 10 + i, "race_id": race_id, "race_date": date, "finish_position": f, "x0": float(i)}
    for i, f in enumerate(finishes)
  ]


def test_clean_races_keeps_only_one_winner_and_two_runners():
  rows = pd.DataFrame(
    _rows(1, [1, 2, 3])  # fine
    + _rows(2, [1, 1, 3])  # dead heat
    + _rows(3, [None, 2])  # no winner recorded
    + _rows(4, [1])  # walkover
  )
  cleaned = clean_races(rows)
  assert set(cleaned["race_id"]) == {1}


def test_to_races_marks_starts_and_winners():
  rows = clean_races(pd.DataFrame(_rows(1, [2, 1, 3]) + _rows(2, [1, 2], date="2026-09-02")))
  races = to_races(rows, {"x": "sql"}, {"sql": "x0"})
  assert list(races.starts) == [0, 3]
  assert list(races.winner_rows) == [1, 3]


def test_to_races_rejects_nulls():
  rows = clean_races(pd.DataFrame(_rows(1, [1, 2])))
  rows.loc[0, "x0"] = None
  with pytest.raises(ValueError):
    to_races(rows, {"x": "sql"}, {"sql": "x0"})
