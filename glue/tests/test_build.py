"""Builds every clean table from the fixtures and checks the results.

The fixtures are one day's racecard (2026-11-10) and three of its races:
947829 (a UK jumps race with non-runners and fallers), 948441 (French, with
unplaced positions not recorded) and 948466 (USA).
"""

import json

import pytest
from pyspark.sql.functions import col

from conftest import FIXTURES
from data_jockey import build, raw_schemas
from data_jockey.tables import TABLE_KEYS, TABLES, local_ddl

RACE_FILES = sorted(FIXTURES.glob("races/*/*.json"))
CARD_FILES = sorted(FIXTURES.glob("racecards/*/*.json"))
UK_RACE, FR_RACE, US_RACE = 947829, 948441, 948466


def _raw_json(race_id):
  return json.loads(next(f for f in RACE_FILES if f.stem == str(race_id)).read_text())


@pytest.fixture(scope="module")
def target_schemas(spark):
  """Each table's schema, from its DDL created as a local table."""
  spark.sql("CREATE DATABASE IF NOT EXISTS build_check")
  schemas = {}
  for name in TABLES:
    spark.sql(local_ddl(name, "build_check"))
    schemas[name] = spark.table(f"build_check.{name}").schema
  yield schemas
  spark.sql("DROP DATABASE build_check CASCADE")


@pytest.fixture(scope="module")
def tables(spark, target_schemas):
  cards = raw_schemas.read_raw(spark, raw_schemas.RACECARD_MEETING, CARD_FILES)
  races = raw_schemas.read_raw(spark, raw_schemas.RACE, RACE_FILES)
  built = build.build_all(cards, races)
  return {
    name: build.conform(df, target_schemas[name]).cache() for name, df in built.items()
  }


def _rows(df, **where):
  for column, value in where.items():
    df = df.where(col(column) == value)
  return [r.asDict() for r in df.collect()]


def test_every_table_is_built(tables):
  assert set(tables) == set(TABLES)


@pytest.mark.parametrize("name", list(TABLE_KEYS))
def test_keys_are_unique_and_not_null(tables, name):
  df = tables[name]
  keys = TABLE_KEYS[name]
  assert df.count() > 0
  null_key_conditions = [f"{key} IS NULL" for key in keys]
  any_key_null = " OR ".join(null_key_conditions)
  assert df.where(any_key_null).count() == 0
  assert df.select(*keys).distinct().count() == df.count()


def test_row_counts_match_raw(tables):
  raw = [_raw_json(r) for r in (UK_RACE, FR_RACE, US_RACE)]
  assert tables["races"].count() == 3
  assert tables["runners"].count() == sum(len(r["rides"]) for r in raw)
  assert tables["prizes"].count() == sum(len(r["prizes"]["prize"]) for r in raw)
  cards = json.loads(CARD_FILES[0].read_text())
  assert tables["meetings"].count() == len(cards)


def test_races_get_racecard_fields_and_conversions(tables):
  (race,) = _rows(tables["races"], race_id=UK_RACE)
  assert race["country_code"] in {"ENG", "Eire", "Wale"}
  assert race["course_id"]
  assert race["going_shortcode"]
  assert race["distance_yards"] > 0
  assert race["winning_time_seconds"] > 0
  assert race["surface"]
  assert race["result_status"] == "complete"
  for race in tables["races"].collect():
    assert race["verdict"] is None or "<" not in race["verdict"]


def test_runner_statuses(tables):
  uk = _rows(tables["runners"], race_id=UK_RACE)
  raw = {r["ride_reference"]["id"]: r for r in _raw_json(UK_RACE)["rides"]}

  winners = [r for r in uk if r["finish_position"] == 1]
  assert len(winners) == 1
  for runner in uk:
    source = raw[runner["ride_id"]]
    if runner["status"] != "RUNNER":
      assert runner["finish_position"] is None
    if source.get("casualty"):
      assert runner["non_finisher_reason"] == source["casualty"]["reason"]
      assert runner["finish_position"] is None
  assert any(r["non_finisher_reason"] for r in uk)
  assert any(r["status"] == "NONRUNNER" for r in uk)


def test_runner_conversions(tables):
  uk = _rows(tables["runners"], race_id=UK_RACE)
  priced = [r for r in uk if r["odds"]]
  assert priced and all(r["odds_decimal"] > 1 for r in priced)
  weighted = [r for r in uk if r["weight"] and r["weight"] != "0-0"]
  assert weighted and all(r["weight_lbs"] > 100 for r in weighted)
  assert all(r["horse_id"] and r["trainer_id"] for r in uk)
  assert any(r["lifetime_runs"] is not None for r in uk)


def test_unrecorded_positions_are_null_not_zero(tables):
  fr = _rows(tables["runners"], race_id=FR_RACE)
  assert all(r["finish_position"] != 0 for r in fr)
  assert any(r["status"] == "RUNNER" and r["finish_position"] is None for r in fr)


def test_prizes_have_amount_and_currency(tables):
  for prize in tables["prizes"].collect():
    assert prize["amount"] > 0
    assert prize["currency"] in {"GBP", "EUR", "USD", "ZAR", "AED"}
  us = _rows(tables["prizes"], race_id=US_RACE)
  assert {p["currency"] for p in us} == {"USD"}


def test_horse_form(tables):
  form = tables["horse_form"]
  raw_pairs = {
    (ride["horse"]["horse_reference"]["id"], pr["race_id"])
    for race in (_raw_json(r) for r in (UK_RACE, FR_RACE, US_RACE))
    for ride in race["rides"]
    for pr in ride["horse"].get("previous_results") or []
  }
  assert form.count() == len(raw_pairs)
  assert form.where("finish_position = 0").count() == 0
  assert form.where("race_date IS NULL").count() == 0
  assert form.where("odds IS NOT NULL AND odds_decimal IS NULL").count() == 0
  assert form.where("distance IS NOT NULL AND distance_yards IS NULL").count() == 0


def test_dimension_names(tables):
  assert tables["horses"].where("name IS NULL").count() == 0
  assert tables["trainers"].where("name IS NULL").count() == 0
  assert tables["courses"].where("name IS NULL OR country_code IS NULL").count() == 0


def test_latest_keeps_most_recent_copy(spark):
  df = spark.createDataFrame(
    [(1, "old", "2026-01-01"), (1, "new", "2026-02-01"), (2, "only", "2026-01-01")],
    "id INT, name STRING, d STRING",
  )
  result = {r.id: r.name for r in build.latest(df, ["id"], [col("d").desc()]).collect()}
  assert result == {1: "new", 2: "only"}


def test_conform_rejects_missing_columns(spark, target_schemas):
  df = spark.createDataFrame([(1,)], "jockey_id BIGINT")
  with pytest.raises(ValueError, match="name"):
    build.conform(df, target_schemas["jockeys"])
