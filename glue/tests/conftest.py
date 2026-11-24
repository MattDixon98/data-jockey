import json
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from data_jockey import build, raw_schemas
from data_jockey.tables import TABLES, local_ddl

# Real crawler output in the raw bucket's layout: {past,today,future}/{racecards,races}/date=*/
FIXTURES = Path(__file__).parent / "fixtures"

# One day's past racecard (2026-11-10) and three of its races: 947829 (UK
# jumps), 948441 (France) and 948466 (USA). See test_build.py.
RACE_FILES = sorted(FIXTURES.glob("past/races/date=2026-11-10/*.json"))
CARD_FILES = sorted(FIXTURES.glob("past/racecards/date=2026-11-10/*.json"))

SNAPSHOT_DATES = ("2026-11-12", "2026-11-14")
SNAPSHOT_RACE_FILES = sorted(
  path for date in SNAPSHOT_DATES for path in FIXTURES.glob(f"*/races/date={date}/*.json")
)
SNAPSHOT_CARD_FILES = sorted(
  path for date in SNAPSHOT_DATES for path in FIXTURES.glob(f"*/racecards/date={date}/*.json")
)

# The real first model (trained on races up to 2026-11-12), so its SQL inputs
# are checked against Spark here as well as Athena in training.
MODEL = json.loads((FIXTURES / "model" / "2026-11-13.json").read_text())


@pytest.fixture(scope="session")
def spark(tmp_path_factory):
  session = (
    SparkSession.builder.master("local[1]")
    .appName("data-jockey-tests")
    .config("spark.ui.enabled", "false")
    # Building every table (model_odds/model_value/scorecard have big plans)
    # ran the default 1g out of heap.
    .config("spark.driver.memory", "2g")
    # Plan text (for the UI/listeners, built on every action) is uncapped by default, and
    # on pyspark 3.5.4 the model tables' plans render to more than the 2g heap (OOM in
    # QueryExecution.explainString). Only the description is cut; results are the same.
    .config("spark.sql.maxPlanStringLength", "1m")
    .config("spark.sql.shuffle.partitions", "1")
    .config("spark.sql.session.timeZone", "UTC")
    .config("spark.sql.warehouse.dir", str(tmp_path_factory.mktemp("warehouse")))
    .getOrCreate()
  )
  yield session
  session.stop()


@pytest.fixture(scope="session")
def target_schemas(spark):
  """Each table's schema, from its DDL created as a local table."""
  spark.sql("CREATE DATABASE IF NOT EXISTS build_check")
  schemas = {}
  for name in TABLES:
    spark.sql(local_ddl(name, "build_check"))
    schemas[name] = spark.table(f"build_check.{name}").schema
  yield schemas
  spark.sql("DROP DATABASE build_check CASCADE")


def build_tables(spark, target_schemas, card_files, race_files):
  """Every table, built once and checkpointed: the data is kept but the long
  query plan behind it (raw JSON -> ... -> model_scorecard) is dropped, so each
  test runs on a small table instead of re-planning the whole chain."""
  cards = raw_schemas.read_raw(spark, raw_schemas.RACECARD_MEETING, card_files)
  races = raw_schemas.read_raw(spark, raw_schemas.RACE, race_files)
  built = build.build_all(cards, races, [MODEL])
  checkpointed = {
    name: build.conform(df, target_schemas[name]).localCheckpoint() for name, df in built.items()
  }
  # build_all's own caches were only needed to build the checkpoints.
  spark.catalog.clearCache()
  return checkpointed


@pytest.fixture(scope="session")
def tables(spark, target_schemas):
  return build_tables(spark, target_schemas, CARD_FILES, RACE_FILES)


@pytest.fixture(scope="session")
def snapshot_tables(spark, target_schemas):
  return build_tables(spark, target_schemas, SNAPSHOT_CARD_FILES, SNAPSHOT_RACE_FILES)
