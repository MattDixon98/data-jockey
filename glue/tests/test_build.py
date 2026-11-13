"""Builds every clean table from the fixtures and checks the results.

Most tests use one day's past racecard (2026-11-10) and three of its races:
947829 (a UK jumps race with non-runners and fallers), 948441 (French, with
unplaced positions not recorded) and 948466 (USA).

The snapshot tests use every crawl of two more races, with their racecards:
948004 (Thurles, 2026-11-12: t-1, today and past) and 946551 (2026-11-14:
t-3, t-2 and t-1, with four entries dropped by t-1).
"""

import json
import shutil

import pytest
from pyspark.sql.functions import col

from conftest import FIXTURES
from data_jockey import build, raw_schemas
from data_jockey.tables import TABLE_KEYS, TABLES, local_ddl

RACE_FILES = sorted(FIXTURES.glob("past/races/date=2026-11-10/*.json"))
CARD_FILES = sorted(FIXTURES.glob("past/racecards/date=2026-11-10/*.json"))
UK_RACE, FR_RACE, US_RACE = 947829, 948441, 948466

SNAPSHOT_DATES = ("2026-11-12", "2026-11-14")
SNAPSHOT_RACE_FILES = sorted(
  path for date in SNAPSHOT_DATES for path in FIXTURES.glob(f"*/races/date={date}/*.json")
)
SNAPSHOT_CARD_FILES = sorted(
  path for date in SNAPSHOT_DATES for path in FIXTURES.glob(f"*/racecards/date={date}/*.json")
)
SETTLED_RACE, UPCOMING_RACE = 948004, 946551


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


def _build(spark, target_schemas, card_files, race_files):
  cards = raw_schemas.read_raw(spark, raw_schemas.RACECARD_MEETING, card_files)
  races = raw_schemas.read_raw(spark, raw_schemas.RACE, race_files)
  built = build.build_all(cards, races)
  return {
    name: build.conform(df, target_schemas[name]).cache() for name, df in built.items()
  }


@pytest.fixture(scope="module")
def tables(spark, target_schemas):
  return _build(spark, target_schemas, CARD_FILES, RACE_FILES)


@pytest.fixture(scope="module")
def snapshot_tables(spark, target_schemas):
  return _build(spark, target_schemas, SNAPSHOT_CARD_FILES, SNAPSHOT_RACE_FILES)


def _snapshot_json(race_id, snapshot):
  suffix = "" if snapshot in ("past", "today") else f"-{snapshot}"
  phase = "future" if snapshot.startswith("t-") else snapshot
  (path,) = FIXTURES.glob(f"{phase}/races/*/{race_id}{suffix}.json")
  return json.loads(path.read_text())


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


# --- Snapshots --------------------------------------------------------------


@pytest.mark.parametrize("name", list(TABLE_KEYS))
def test_snapshot_keys_are_unique(snapshot_tables, name):
  df = snapshot_tables[name]
  keys = TABLE_KEYS[name]
  assert df.select(*keys).distinct().count() == df.count()


def test_past_beats_today_and_earlier_snapshots(snapshot_tables):
  (race,) = _rows(snapshot_tables["races"], race_id=SETTLED_RACE)
  assert race["snapshot"] == "past"
  assert race["result_status"] == "complete"
  assert race["winning_time_seconds"] > 0
  assert race["country_code"] == "Eire"

  runners = _rows(snapshot_tables["runners"], race_id=SETTLED_RACE)
  starting_prices = {
    ride["ride_reference"]["id"]: ride["betting"].get("current_odds")
    for ride in _snapshot_json(SETTLED_RACE, "past")["rides"]
  }
  assert {r["ride_id"]: r["odds"] for r in runners} == starting_prices
  assert {r["snapshot"] for r in runners} == {"past"}
  assert any(r["finish_position"] == 1 for r in runners)


def test_upcoming_race_uses_latest_snapshot_only(snapshot_tables):
  (race,) = _rows(snapshot_tables["races"], race_id=UPCOMING_RACE)
  assert race["snapshot"] == "t-1"
  assert race["result_status"] == "incomplete"
  assert race["course_id"]

  t1_rides = {r["ride_reference"]["id"] for r in _snapshot_json(UPCOMING_RACE, "t-1")["rides"]}
  t3_rides = {r["ride_reference"]["id"] for r in _snapshot_json(UPCOMING_RACE, "t-3")["rides"]}
  assert t3_rides - t1_rides, "fixture should have entries dropped by t-1"

  runners = _rows(snapshot_tables["runners"], race_id=UPCOMING_RACE)
  assert {r["ride_id"] for r in runners} == t1_rides
  assert all(r["odds_decimal"] for r in runners if r["status"] == "RUNNER")
  assert all(r["finish_position"] is None for r in runners)


def test_meetings_come_from_latest_racecard(snapshot_tables):
  t1_card = json.loads(
    (FIXTURES / "future/racecards/date=2026-11-14/racecards-t-1.json").read_text()
  )
  t1_meetings = {m["meeting_summary"]["meeting_reference"]["id"] for m in t1_card}
  upcoming = snapshot_tables["meetings"].where("meeting_date = DATE'2026-11-14'")
  assert {r.meeting_id for r in upcoming.collect()} == t1_meetings


def test_results_only_come_from_past(spark, target_schemas, tmp_path):
  """The 2026-11-10 UK race (a full result) saved as if it were a today/ crawl."""
  (source,) = [f for f in RACE_FILES if f.stem == str(UK_RACE)]
  today_file = tmp_path / "today/races/date=2026-11-10" / source.name
  today_file.parent.mkdir(parents=True)
  shutil.copy(source, today_file)

  built = _build(spark, target_schemas, CARD_FILES, [today_file])
  (race,) = _rows(built["races"], race_id=UK_RACE)
  assert race["snapshot"] == "today"
  assert race["result_status"] == "incomplete"
  assert race["winning_time"] is None and race["winning_time_seconds"] is None

  runners = _rows(built["runners"], race_id=UK_RACE)
  assert runners
  assert all(r["finish_position"] is None for r in runners)
  assert all(r["non_finisher_reason"] is None for r in runners)


# --- Odds -------------------------------------------------------------------


def _prices(race_json):
  return {
    ride["ride_reference"]["id"]: ride["betting"].get("current_odds")
    for ride in race_json["rides"]
    if ride["betting"].get("current_odds")
  }


def test_odds_snapshots_keep_every_priced_crawl(snapshot_tables):
  rows = _rows(snapshot_tables["odds_snapshots"], race_id=SETTLED_RACE)
  by_snapshot = {}
  for row in rows:
    by_snapshot.setdefault(row["snapshot"], {})[row["ride_id"]] = row["odds"]

  assert set(by_snapshot) == {"t-1", "today", "past"}
  for snapshot, prices in by_snapshot.items():
    assert prices == _prices(_snapshot_json(SETTLED_RACE, snapshot))
  assert all(row["odds_decimal"] > 1 for row in rows)
  ranks = {row["snapshot"]: row["snapshot_rank"] for row in rows}
  assert ranks == {"past": 0, "today": 1, "t-1": 2}


def test_odds_snapshots_skip_unpriced_crawls(snapshot_tables):
  rows = _rows(snapshot_tables["odds_snapshots"], race_id=UPCOMING_RACE)
  assert {row["snapshot"] for row in rows} == {"t-1"}
  assert {row["ride_id"] for row in rows} == set(_prices(_snapshot_json(UPCOMING_RACE, "t-1")))


def test_odds_history_follows_the_on_course_market(snapshot_tables):
  rows = _rows(snapshot_tables["odds_history"], race_id=SETTLED_RACE)
  expected = {
    ride["ride_reference"]["id"]: ride["betting"]["historical_odds"]
    for ride in _snapshot_json(SETTLED_RACE, "past")["rides"]
    if ride["betting"].get("historical_odds")
  }
  assert expected, "fixture should have on-course prices"

  actual = {}
  for row in sorted(rows, key=lambda r: (r["ride_id"], r["seq"])):
    actual.setdefault(row["ride_id"], []).append(row["odds"])
  assert actual == expected
  assert min(row["seq"] for row in rows) == 1


def test_odds_history_only_from_past(snapshot_tables):
  upcoming = _rows(snapshot_tables["odds_history"], race_id=UPCOMING_RACE)
  assert upcoming == []
