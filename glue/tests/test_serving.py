"""The serving snapshot: UK/IRE filtering and the SQLite file the website reads.

Uses the same built tables as test_build.py: 2026-11-10 has one UK race
(947829) and two abroad (948441 France, 948466 USA); the snapshot fixtures
(948004 Thurles, 946551 UK) have model rows.
"""

import json
import sqlite3

import pytest
from pyspark.sql.functions import col

from data_jockey import serving
from data_jockey.conversions import UK_IRE_COUNTRY_CODES
from data_jockey.tables import TABLE_KEYS, ddl_columns

UK_RACE, FR_RACE, US_RACE = 947829, 948441, 948466
BUILT_AT = "2026-11-16T07:10:00+00:00"


def _ids(df, column):
  return {row[column] for row in df.select(column).distinct().collect()}


@pytest.fixture(scope="module")
def served(tables):
  return serving.uk_ire_tables(tables)


@pytest.fixture(scope="module", params=["tables", "snapshot_tables"])
def snapshot_file(request, tmp_path_factory):
  """A SQLite snapshot of each set of fixture tables, with its served DataFrames and row counts."""
  served = serving.uk_ire_tables(request.getfixturevalue(request.param))
  path = tmp_path_factory.mktemp("serving") / "data_jockey.sqlite3"
  counts = serving.write_sqlite(served, str(path), BUILT_AT)
  connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
  yield connection, served, counts
  connection.close()


def test_only_uk_ire_races(tables, served):
  assert _ids(tables["races"], "race_id") >= {UK_RACE, FR_RACE, US_RACE}
  assert _ids(served["races"], "race_id") == {UK_RACE}
  assert _ids(served["courses"], "country_code") <= set(UK_IRE_COUNTRY_CODES)


@pytest.mark.parametrize("name", serving.RACE_TABLES)
def test_race_tables_follow_the_races(tables, served, name):
  kept = served[name]
  assert _ids(kept, "race_id") <= {UK_RACE}
  expected = tables[name].where(col("race_id") == UK_RACE).count()
  assert kept.count() == expected


def test_people_and_horses_are_the_ones_that_ran(served):
  runners = served["runners"]
  assert _ids(served["horses"], "horse_id") == _ids(runners, "horse_id")
  assert _ids(served["jockeys"], "jockey_id") == _ids(runners.where(col("jockey_id").isNotNull()), "jockey_id")
  assert _ids(served["trainers"], "trainer_id") == _ids(runners.where(col("trainer_id").isNotNull()), "trainer_id")


def test_horse_form_keeps_runs_abroad(tables, served):
  """A served horse's whole form, wherever it ran; only other horses' form is dropped."""
  horses = _ids(served["horses"], "horse_id")
  form = served["horse_form"]
  assert _ids(form, "horse_id") <= horses
  expected = tables["horse_form"].where(col("horse_id").isin(list(horses))).count()
  assert form.count() == expected > 0


def test_meetings_only_at_uk_ire_courses(served):
  assert _ids(served["meetings"], "course_id") <= _ids(served["courses"], "course_id")
  assert served["meetings"].count() > 0


def test_columns_keep_the_clean_tables_order(served):
  for name in serving.SERVED_TABLES:
    assert served[name].columns == ddl_columns(name), name


def test_every_served_table_is_written_with_its_columns(snapshot_file):
  connection, _, counts = snapshot_file
  for name in serving.SERVED_TABLES:
    columns = [row[1] for row in connection.execute(f"PRAGMA table_info({name})")]
    assert columns == ddl_columns(name), name
  assert set(counts) == set(serving.SERVED_TABLES)


def test_row_counts_match_the_served_tables(snapshot_file):
  connection, served, counts = snapshot_file
  for name in serving.SERVED_TABLES:
    rows = connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    assert rows == counts[name] == served[name].count(), name
  assert counts["races"] > 0 and counts["runners"] > 0


def test_primary_keys_are_the_table_keys(snapshot_file):
  connection, _, _ = snapshot_file
  for name in serving.SERVED_TABLES:
    info = connection.execute(f"PRAGMA table_info({name})").fetchall()
    # pk is the column's 1-based position in the key, 0 if not in it.
    key = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5] > 0]
    assert key == TABLE_KEYS[name], name


def test_values_are_stored_as_sqlite_types(snapshot_file):
  connection, _, _ = snapshot_file
  race = connection.execute(
    "SELECT race_date, typeof(race_date), has_handicap, typeof(distance_yards) FROM races LIMIT 1"
  ).fetchone()
  assert race[0][4] == "-" and race[1] == "text"
  assert race[2] in (0, 1)
  assert race[3] == "integer"

  insights = connection.execute("SELECT insights FROM runners WHERE insights IS NOT NULL LIMIT 1").fetchone()
  if insights is not None:
    assert isinstance(json.loads(insights[0]), list)

  amount = connection.execute("SELECT typeof(amount) FROM prizes WHERE amount IS NOT NULL LIMIT 1").fetchone()
  if amount is not None:
    assert amount[0] == "real"


def test_model_rows_are_exported(request):
  """The snapshot fixtures have model rows (the standard ones are all in sample)."""
  served = serving.uk_ire_tables(request.getfixturevalue("snapshot_tables"))
  assert served["model_odds"].count() > 0
  assert served["model_value"].count() > 0


def test_snapshot_info_and_format(snapshot_file):
  connection, _, _ = snapshot_file
  assert connection.execute("SELECT built_at, format_version FROM snapshot_info").fetchall() == [
    (BUILT_AT, serving.FORMAT_VERSION)
  ]
  assert connection.execute("PRAGMA user_version").fetchone()[0] == serving.FORMAT_VERSION
  assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_every_served_table_is_required(served, tmp_path):
  partial = {name: df for name, df in served.items() if name != "model_value"}
  with pytest.raises(ValueError, match="model_value"):
    serving.write_sqlite(partial, str(tmp_path / "partial.sqlite3"), BUILT_AT)


def test_rewrite_replaces_the_file(served, tmp_path):
  path = tmp_path / "data_jockey.sqlite3"
  first = serving.write_sqlite(served, str(path), BUILT_AT)
  second = serving.write_sqlite(served, str(path), "2026-11-17T07:10:00+00:00")
  assert first == second
  with sqlite3.connect(path) as connection:
    assert connection.execute("SELECT built_at FROM snapshot_info").fetchall() == [("2026-11-17T07:10:00+00:00",)]
