"""Builds every clean table from the fixtures and checks the results.

Most tests use one day's past racecard (2026-11-10) and three of its races:
947829 (a UK jumps race with non-runners and fallers), 948441 (French, with
unplaced positions not recorded) and 948466 (USA).

The snapshot tests use every crawl of two more races, with their racecards:
948004 (Thurles, 2026-11-12: t-1, today and past) and 946551 (2026-11-14:
t-3, t-2 and t-1, with four entries dropped by t-1).
"""

import json
import math
import shutil

import pytest
from pyspark.sql.functions import col, count, expr, to_date
from pyspark.sql.functions import sum as spark_sum

from conftest import CARD_FILES, FIXTURES, MODEL, RACE_FILES, build_tables
from data_jockey import build, conversions, raw_schemas
from data_jockey.build.model_odds import model_odds
from data_jockey.build.model_scorecard import graded_view_rows, model_calibration, model_scorecard
from data_jockey.build.model_value import MIN_EXPECTED_VALUE, MIN_MODEL_PROB, model_value
from data_jockey.tables import TABLE_KEYS, TABLES

UK_RACE, FR_RACE, US_RACE = 947829, 948441, 948466

SETTLED_RACE, UPCOMING_RACE = 948004, 946551


def _raw_json(race_id):
  return json.loads(next(f for f in RACE_FILES if f.stem == str(race_id)).read_text())


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


# Empty on the standard fixtures by design: the fixture model was trained on
# the only settled race. Their keys are checked on the out-of-sample build.
EMPTY_ON_FIXTURES = {"model_scorecard", "model_calibration"}


@pytest.mark.parametrize("name", list(TABLE_KEYS))
def test_keys_are_unique_and_not_null(tables, name):
  df = tables[name]
  keys = TABLE_KEYS[name]
  if name not in EMPTY_ON_FIXTURES:
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


@pytest.mark.parametrize("fixture", ["tables", "snapshot_tables"])
def test_race_type_matches_source_run_type(request, fixture):
  """The source only gives a race's type in each runner's previous_results,
  which for a past race includes the race itself: race_type (from the name)
  must agree with it."""
  built = request.getfixturevalue(fixture)
  run_types = built["horse_form"].select("race_id", "run_type").distinct()
  uk_ire = col("country_code").isin(conversions.UK_IRE_COUNTRY_CODES)
  races = built["races"].where(uk_ire)
  checked = races.join(run_types, "race_id").where("run_type IS NOT NULL").collect()
  assert checked
  for race in checked:
    assert race["race_type"] == race["run_type"], race["name"]


def test_race_type_null_outside_uk_ire(tables):
  for race_id in (FR_RACE, US_RACE):
    (race,) = _rows(tables["races"], race_id=race_id)
    assert race["race_type"] is None


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


def test_as_of_only_counts_earlier_days(spark):
  history = spark.createDataFrame(
    [
      ("a", "2026-01-01", 1),
      ("a", "2026-01-02", 0),
      ("a", "2026-01-03", 1),
      ("b", "2026-01-05", 1),
    ],
    "k STRING, d STRING, is_win INT",
  ).select("k", to_date("d").alias("race_date"), "is_win")
  targets = spark.createDataFrame(
    [("a", "2026-01-01"), ("a", "2026-01-03"), ("a", "2026-01-10"), ("b", "2026-01-05"), ("c", "2026-01-05")],
    "k STRING, d STRING",
  ).select("k", to_date("d").alias("race_date"))

  aggregates = {"runs": count("is_win"), "wins": spark_sum("is_win")}
  result = build.as_of(history, targets, ["k"], aggregates).collect()
  totals = {(r.k, str(r.race_date)): (r.runs, r.wins) for r in result}
  assert totals == {
    ("a", "2026-01-01"): (0, None),  # nothing earlier
    ("a", "2026-01-03"): (2, 1),  # the 3rd itself doesn't count
    ("a", "2026-01-10"): (3, 2),  # earlier target rows don't count as runs
    ("b", "2026-01-05"): (0, None),  # same day only
    ("c", "2026-01-05"): (0, None),  # no history at all
  }


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

  built = build_tables(spark, target_schemas, CARD_FILES, [today_file])
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


# --- Model features ---------------------------------------------------------

# Columns that may be NULL in runner_features: ids and raw context. Every
# other column is a model input and must always have a value.
NULLABLE_FEATURE_COLUMNS = {
  "jockey_id",
  "distance_band",
  "going_group",
  "official_rating",
  "weight_lbs",
  "finish_position",
}
# Built from earlier races only, so the same for every snapshot of a ride.
HISTORY_COLUMNS = [
  "horse_runs",
  "horse_wins",
  "horse_places",
  "days_since_run",
  "last_form",
  "recent_form",
  "type_runs",
  "type_wins",
  "course_runs",
  "course_wins",
  "distance_runs",
  "distance_wins",
  "going_runs",
  "going_wins",
  "trainer_runs",
  "trainer_win_rate",
]


@pytest.mark.parametrize("fixture", ["tables", "snapshot_tables"])
def test_runner_features_model_inputs_never_null(request, fixture):
  features = request.getfixturevalue(fixture)["runner_features"]
  assert features.count() > 0
  for column in features.columns:
    if column not in NULLABLE_FEATURE_COLUMNS:
      assert features.where(col(column).isNull()).count() == 0, column


def test_runner_features_only_uk_ire_runners(tables):
  features = tables["runner_features"]
  assert {r.race_id for r in features.select("race_id").distinct().collect()} == {UK_RACE}
  runners = _rows(tables["runners"], race_id=UK_RACE)
  assert features.count() == sum(1 for r in runners if r["status"] == "RUNNER")


def test_runner_features_dont_see_the_race_itself(snapshot_tables):
  """The past file's form already includes the race (Fratas: 948004 is its
  first previous result there); features must match the t-1 crawl's."""
  features = snapshot_tables["runner_features"].where(col("race_id") == SETTLED_RACE)
  by_snapshot = {}
  for row in features.collect():
    by_snapshot.setdefault(row.ride_id, {})[row.snapshot] = row

  past_form = _snapshot_json(SETTLED_RACE, "past")["rides"]
  fratas = next(r for r in past_form if r["horse"]["name"] == "Fratas")
  assert fratas["horse"]["previous_results"][0]["race_id"] == SETTLED_RACE

  compared = 0
  for snapshots in by_snapshot.values():
    if "past" not in snapshots:
      continue
    for column in HISTORY_COLUMNS:
      assert snapshots["past"][column] == snapshots["t-1"][column], column
    assert snapshots["t-1"].finish_position is None
    compared += 1
  assert compared == 10


def test_runner_features_carry_has_handicap(tables, snapshot_tables):
  (race,) = _rows(tables["races"], race_id=UK_RACE)
  features = _rows(tables["runner_features"], race_id=UK_RACE)
  assert {r["has_handicap"] for r in features} == {race["has_handicap"]}
  # 948004 is a handicap hurdle.
  settled = _rows(snapshot_tables["runner_features"], race_id=SETTLED_RACE)
  assert {r["has_handicap"] for r in settled} == {True}


def test_runner_features_ratings_compare_within_race_type(snapshot_tables):
  # Fratas: rated 115 over hurdles; last ran on the flat (76), last hurdle 112.
  (row,) = _rows(snapshot_tables["runner_features"], race_id=SETTLED_RACE, snapshot="t-1", horse_id=1082171)
  assert row["official_rating"] == 115
  assert row["rating_change"] == 3


def test_runner_features_field_follows_each_snapshot(snapshot_tables):
  features = snapshot_tables["runner_features"].where(col("race_id") == UPCOMING_RACE)
  for snapshot in ("t-3", "t-2", "t-1"):
    raw_runners = [r for r in _snapshot_json(UPCOMING_RACE, snapshot)["rides"] if r["ride_status"] == "RUNNER"]
    rows = features.where(col("snapshot") == snapshot).collect()
    assert len(rows) == len(raw_runners)
    assert {r.field_size for r in rows} == {len(raw_runners)}
    assert abs(sum(r.rating_diff for r in rows if not r.is_unrated)) < 1e-6


def test_runner_features_before_jockeys_are_booked(snapshot_tables):
  t3 = snapshot_tables["runner_features"].where((col("race_id") == UPCOMING_RACE) & (col("snapshot") == "t-3"))
  unbooked = [r for r in t3.collect() if r.jockey_id is None]
  assert unbooked, "fixture should have rides with no jockey yet at t-3"
  for row in unbooked:
    assert not row.has_jockey
    assert row.jockey_rides == 0
    assert row.jockey_win_rate == pytest.approx(0.1)


def test_runner_features_dropped_entries_keep_their_form(snapshot_tables):
  t1_rides = {r["ride_reference"]["id"] for r in _snapshot_json(UPCOMING_RACE, "t-1")["rides"]}
  dropped = [
    r for r in _snapshot_json(UPCOMING_RACE, "t-3")["rides"]
    if r["ride_reference"]["id"] not in t1_rides and r["horse"].get("previous_results")
  ]
  assert dropped
  features = snapshot_tables["runner_features"].where((col("race_id") == UPCOMING_RACE) & (col("snapshot") == "t-3"))
  runs = {r.ride_id: r.horse_runs for r in features.collect()}
  for ride in dropped:
    assert runs[ride["ride_reference"]["id"]] > 0


def test_amended_result_is_used(snapshot_tables):
  """948004: Shoda passed the post first, Fratas was awarded the race."""
  fratas = 1082171
  past = _snapshot_json(SETTLED_RACE, "past")["rides"]
  shoda = next(r for r in past if r["horse"]["name"] == "Shoda")["horse"]["horse_reference"]["id"]

  runners = {r["horse_id"]: r["finish_position"] for r in _rows(snapshot_tables["runners"], race_id=SETTLED_RACE)}
  assert runners[fratas] == 1
  assert runners[shoda] == 2

  (form,) = _rows(snapshot_tables["horse_form"], race_id=SETTLED_RACE, horse_id=fratas)
  assert form["finish_position"] == 1

  (features,) = _rows(snapshot_tables["runner_features"], race_id=SETTLED_RACE, snapshot="past", horse_id=fratas)
  assert features["finish_position"] == 1


# --- Model odds -------------------------------------------------------------


def test_no_models_means_no_model_odds(spark):
  # build_all only defines DataFrames (nothing runs), so this is cheap.
  cards = raw_schemas.read_raw(spark, raw_schemas.RACECARD_MEETING, CARD_FILES)
  races = raw_schemas.read_raw(spark, raw_schemas.RACE, RACE_FILES)
  built = build.build_all(cards, races)
  assert "model_odds" not in built
  assert "runner_features" in built
  spark.catalog.clearCache()  # build_all registers caches even though nothing ran


@pytest.mark.parametrize("fixture", ["tables", "snapshot_tables"])
def test_model_inputs_run_in_spark_and_are_never_null(request, fixture):
  features = request.getfixturevalue(fixture)["runner_features"]
  for item in MODEL["inputs"]:
    value = expr(f"CAST({item['sql']} AS DOUBLE)")
    assert features.where(value.isNull()).count() == 0, item["name"]


@pytest.mark.parametrize("fixture", ["tables", "snapshot_tables"])
def test_model_odds_price_every_runner_and_sum_to_one(request, fixture):
  built = request.getfixturevalue(fixture)
  odds = built["model_odds"]
  assert odds.count() == built["runner_features"].count()
  totals = odds.groupBy("race_id", "snapshot").agg(spark_sum("model_prob").alias("total")).collect()
  assert totals and all(abs(row.total - 1.0) < 1e-9 for row in totals)
  for row in odds.collect():
    assert row.model_odds_decimal == pytest.approx(1 / row.model_prob)
    assert row.model_odds is not None


def test_model_odds_favourite_is_rank_one(snapshot_tables):
  odds = snapshot_tables["model_odds"]
  for race in odds.select("race_id", "snapshot").distinct().collect():
    rows = odds.where((col("race_id") == race.race_id) & (col("snapshot") == race.snapshot)).collect()
    favourite = max(rows, key=lambda r: r.model_prob)
    assert favourite.model_rank == 1
    assert {r.field_size for r in rows} == {len(rows)}


def test_model_odds_reshare_as_the_field_shrinks(snapshot_tables):
  """946551 loses entries between t-3 and t-1: the horses still in it share
  100% at t-1 instead of whatever was left after the dropped ones."""
  odds = snapshot_tables["model_odds"].where(col("race_id") == UPCOMING_RACE)
  by_snapshot = {}
  for row in odds.collect():
    by_snapshot.setdefault(row.snapshot, {})[row.ride_id] = row.model_prob
  stayed = set(by_snapshot["t-1"]) & set(by_snapshot["t-3"])
  assert len(by_snapshot["t-3"]) > len(by_snapshot["t-1"])
  assert sum(by_snapshot["t-3"][ride] for ride in stayed) < 1.0
  assert sum(by_snapshot["t-1"][ride] for ride in stayed) == pytest.approx(1.0)


def test_model_odds_flag_races_the_model_learnt_from(snapshot_tables):
  # The fixture model was trained on races up to 2026-11-12.
  odds = snapshot_tables["model_odds"]
  flags = {(str(r.race_date), r.in_sample) for r in odds.select("race_date", "in_sample").distinct().collect()}
  assert flags == {("2026-11-12", True), ("2026-11-14", False)}
  assert {r.model_version for r in odds.select("model_version").distinct().collect()} == {"2026-11-13"}


def test_each_race_priced_by_the_newest_model_trained_before_it(snapshot_tables):
  older = {**MODEL, "version": "2026-11-10", "trained_on": {**MODEL["trained_on"], "to": "2026-11-09"}}
  odds = model_odds(snapshot_tables["runner_features"], [older, MODEL])
  used = {
    (str(r.race_date), r.model_version, r.in_sample)
    for r in odds.select("race_date", "model_version", "in_sample").distinct().collect()
  }
  # 12 Nov: the older model had finished training (9 Nov), the newer one hadn't.
  assert used == {("2026-11-12", "2026-11-10", False), ("2026-11-14", "2026-11-13", False)}


# --- Model value ------------------------------------------------------------


def _fully_priced(built):
  """(race_id, snapshot) pairs where every model_odds runner has a price."""
  prices = {(r.ride_id, r.snapshot): r.odds_decimal for r in built["odds_snapshots"].collect()}
  races = {}
  for row in built["model_odds"].collect():
    priced = (prices.get((row.ride_id, row.snapshot)) or 0) > 1
    races.setdefault((row.race_id, row.snapshot), []).append(priced)
  return {key for key, flags in races.items() if all(flags)}


@pytest.mark.parametrize("fixture", ["tables", "snapshot_tables"])
def test_model_value_only_for_fully_priced_races(request, fixture):
  built = request.getfixturevalue(fixture)
  value = built["model_value"]
  pairs = {(r.race_id, r.snapshot) for r in value.select("race_id", "snapshot").distinct().collect()}
  assert pairs and pairs == _fully_priced(built)
  assert value.where(col("snapshot") == "t-3").count() == 0


def test_model_value_market_is_sp_after_the_race(snapshot_tables):
  markets = {(r.snapshot, r.market) for r in snapshot_tables["model_value"].select("snapshot", "market").distinct().collect()}
  assert ("past", "SP") in markets and ("t-1", "forecast") in markets
  assert all((snapshot == "past") == (market == "SP") for snapshot, market in markets)


@pytest.mark.parametrize("fixture", ["tables", "snapshot_tables"])
def test_model_value_numbers(request, fixture):
  value = request.getfixturevalue(fixture)["model_value"]
  totals = value.groupBy("race_id", "snapshot").agg(spark_sum("market_prob").alias("total")).collect()
  assert all(abs(row.total - 1.0) < 1e-9 for row in totals)
  for row in value.collect():
    assert row.book_percentage > 100
    assert row.edge == pytest.approx(row.model_prob / row.market_prob - 1)
    assert row.expected_value == pytest.approx(row.model_prob * row.market_odds_decimal - 1)
    expected_flag = row.expected_value >= MIN_EXPECTED_VALUE and row.model_prob >= MIN_MODEL_PROB
    assert row.undervalued == expected_flag


def test_model_value_grades_every_snapshot_once_run(snapshot_tables):
  """948004 has been run: Fratas (awarded the race) won at every snapshot; the
  late non-runner Mastertown Miss had a t-1 price but no result (bet void).
  946551 hasn't been run yet, so nothing is graded."""
  value = snapshot_tables["model_value"]
  settled = {}
  for row in value.where(col("race_id") == SETTLED_RACE).collect():
    settled[(row.horse_id, row.snapshot)] = row
  fratas = 1082171
  assert {settled[(fratas, s)].won for s in ("t-1", "today", "past")} == {True}
  assert settled[(fratas, "t-1")].finish_position == 1

  past = _snapshot_json(SETTLED_RACE, "past")["rides"]
  non_runner = next(r for r in past if r["ride_status"] == "NONRUNNER")["horse"]["horse_reference"]["id"]
  assert settled[(non_runner, "t-1")].won is None
  assert (non_runner, "past") not in settled

  graded = [r for r in settled.values() if r.won is not None]
  assert sum(r.won for r in graded if r.snapshot == "past") == 1

  upcoming = value.where(col("race_id") == UPCOMING_RACE).collect()
  assert upcoming and all(r.won is None and r.finish_position is None for r in upcoming)


# --- Scorecard --------------------------------------------------------------

# Trained up to 9 Nov, so 948004 (12 Nov, run) is out of sample for it.
OLDER_MODEL = {**MODEL, "version": "2026-11-10", "trained_on": {**MODEL["trained_on"], "to": "2026-11-09"}}


@pytest.fixture(scope="module")
def out_of_sample(snapshot_tables):
  """model_value and the graded view rows, priced with OLDER_MODEL."""
  odds = model_odds(snapshot_tables["runner_features"], [OLDER_MODEL])
  value = model_value(odds, snapshot_tables["odds_snapshots"], snapshot_tables["runners"], snapshot_tables["races"])
  value = value.localCheckpoint()
  graded = graded_view_rows(value, snapshot_tables["races"]).localCheckpoint()
  return value, graded


def test_in_sample_races_are_never_scored(snapshot_tables):
  # The fixture model was trained on 948004, the only settled race.
  assert snapshot_tables["model_scorecard"].count() == 0
  assert snapshot_tables["model_calibration"].count() == 0


def test_views_use_past_and_the_race_morning_row(out_of_sample):
  _, graded = out_of_sample
  snapshots = {(r.view, r.race_id, r.snapshot) for r in graded.select("view", "race_id", "snapshot").distinct().collect()}
  # 948004 had a today crawl; 946551 hasn't been run, so isn't graded.
  assert snapshots == {("after_race", SETTLED_RACE, "past"), ("site_pick", SETTLED_RACE, "today")}


def test_site_pick_falls_back_to_t1(out_of_sample, snapshot_tables):
  value, _ = out_of_sample
  no_today = value.where(col("snapshot") != "today")
  graded = graded_view_rows(no_today, snapshot_tables["races"])
  site_pick = {r.snapshot for r in graded.where(col("view") == "site_pick").select("snapshot").distinct().collect()}
  assert site_pick == {"t-1"}


def test_scorecard_numbers_match_the_rows(out_of_sample):
  _, graded = out_of_sample
  scorecard = model_scorecard(graded)
  for view in ("after_race", "site_pick"):
    rows = graded.where(col("view") == view).collect()
    (card,) = [
      r for r in scorecard.where(col("view") == view).collect()
      if r.period_type == "all" and r.race_group == "all"
    ]
    winner = next(r for r in rows if r.won)
    assert card.races == 1 and card.runners == len(rows)
    assert card.log_loss_model == pytest.approx(-math.log(winner.model_prob))
    assert card.log_loss_market == pytest.approx(-math.log(winner.market_prob))

    bets = [r for r in rows if r.undervalued and r.sp_decimal is not None]
    profit = sum((r.sp_decimal - 1) if r.won else -1 for r in bets)
    assert card.bets == len(bets)
    assert card.bets_won == sum(r.won for r in bets)
    if bets:
      assert card.profit_units == pytest.approx(profit)
      assert card.roi == pytest.approx(profit / len(bets))
      assert card.expected_wins_market == pytest.approx(sum(r.sp_prob for r in bets))
    for source in ("model", "market"):
      picks = [r for r in rows if getattr(r, f"{source}_rank") == 1]
      stake = 1 / len(picks)
      pick_profit = sum(stake * (r.sp_decimal - 1) if r.won else -stake for r in picks)
      assert getattr(card, f"top_pick_profit_{source}") == pytest.approx(pick_profit)
      assert getattr(card, f"top_pick_roi_{source}") == pytest.approx(pick_profit)  # 1 race = 1 unit
    # SP is the same for both views: site_pick bets are settled at the race's SP too.
    assert all(r.sp_prob is not None for r in rows)


def test_scorecard_breakdowns(out_of_sample):
  _, graded = out_of_sample
  keys = {(r.period_type, r.period, r.race_group) for r in model_scorecard(graded).collect()}
  periods = {("all", "all"), ("month", "2026-11"), ("model_version", "2026-11-10")}
  groups = {"all", "jumps"}  # 948004 is a hurdle race
  assert keys == {(pt, p, g) for pt, p in periods for g in groups}


def test_calibration_covers_every_graded_runner(out_of_sample):
  _, graded = out_of_sample
  calibration = model_calibration(graded).collect()
  for view in ("after_race", "site_pick"):
    runners = graded.where(col("view") == view).count()
    for source in ("model", "market"):
      bands = [r for r in calibration if r.view == view and r.source == source]
      assert sum(r.runners for r in bands) == runners
      assert all(r.band_label and 0 <= r.actual <= 1 for r in bands)


def test_scorecard_tables_match_their_ddl(out_of_sample, target_schemas):
  _, graded = out_of_sample
  build.conform(model_scorecard(graded), target_schemas["model_scorecard"]).collect()
  build.conform(model_calibration(graded), target_schemas["model_calibration"]).collect()


@pytest.mark.parametrize(
  "name, make",
  [("model_scorecard", model_scorecard), ("model_calibration", model_calibration)],
)
def test_scorecard_keys_are_unique_and_not_null(out_of_sample, name, make):
  _, graded = out_of_sample
  df = make(graded)
  keys = TABLE_KEYS[name]
  assert df.count() > 0
  any_key_null = " OR ".join(f"{key} IS NULL" for key in keys)
  assert df.where(any_key_null).count() == 0
  assert df.select(*keys).distinct().count() == df.count()
