"""Builds the clean tables from the raw racecard and race DataFrames.

The transform step: pure transformations, no I/O. The Glue job reads the raw
JSON (with the schemas in raw_schemas) and writes what comes back here, and the
tests run the same functions against the fixtures. One module per table, with
the shared pieces in utilities.py.

Every run rebuilds from every raw file: past/, today/ and the future/ t-N
snapshots. A race has one file per snapshot, so each race is first cut down to
its most trusted file (past > today > t-1 > t-2 > t-3, see
conversions.snapshot_rank) and only that file's runners, prizes and form are
used: entries dropped between t-3 and t-1 don't linger, and results (finishing
positions, winning time) only ever come from past. Racecards are cut down the
same way, per date.

After that each table is de-duplicated on its key, keeping the copy from the
most recent race (and, for names, the most recent non-null value).
"""

from typing import Callable

from pyspark.sql import DataFrame

from data_jockey.build.utilities import as_of, conform, latest, race_files, racecard_files
from data_jockey.build.courses import courses
from data_jockey.build.horse_form import horse_form
from data_jockey.build.horses import horses
from data_jockey.build.jockeys import jockeys
from data_jockey.build.meetings import meetings
from data_jockey.build.model_odds import model_odds
from data_jockey.build.model_scorecard import graded_view_rows, model_calibration, model_scorecard
from data_jockey.build.model_value import model_value
from data_jockey.build.odds_history import odds_history
from data_jockey.build.odds_snapshots import odds_snapshots
from data_jockey.build.prizes import prizes
from data_jockey.build.races import races
from data_jockey.build.runner_features import runner_features
from data_jockey.build.runners import runners
from data_jockey.build.trainers import trainers

__all__ = ["as_of", "build_all", "cache", "checkpoint", "conform", "latest"]


def cache(df: DataFrame) -> DataFrame:
  return df.cache()


def checkpoint(df: DataFrame) -> DataFrame:
  """Computed once and kept on the executors, with the query plan behind it
  dropped: what comes after plans from here, not from the raw JSON."""
  return df.localCheckpoint(eager=True)


def build_all(
  racecards: DataFrame,
  races_raw: DataFrame,
  models: list[dict] | None = None,
  keep: Callable[[DataFrame], DataFrame] = cache,
  blend: dict | None = None,
) -> dict[str, DataFrame]:
  """Every clean table, keyed by table name (unconformed column order).

  `models` are the promoted win-odds models (models.usable_models). Without
  them there are no model tables (model_odds, model_value, model_scorecard,
  model_calibration), and every other table still builds. `blend`
  (models.check_blend) gives model_value its blended_prob; None = no blend.

  Takes the raw reads (with source_file) of every snapshot. Everything but
  odds_snapshots and runner_features use only each race's most trusted file.

  Anything another table is built from is cached: each table is written
  separately, and without the cache every model table would re-read the raw
  JSON and rebuild runner_features, model_odds and model_value from scratch.
  The data is small (tens of thousands of rows per table), so memory isn't a
  concern.

  `keep` is applied to the built tables others are built from. The default,
  `cache`, is lazy: nothing runs until a table is written. The job, run_local
  and the test fixtures pass `checkpoint`, which runs each one there and then
  and drops its query plan. Without it, every model table carries the plan of
  the whole chain, which grows with each promoted model (model_odds has one
  scoring branch per model): with two models the rebuild ran the driver out of
  memory planning model_calibration (27 Nov).
  """
  all_race_files = races_raw.cache()
  racecards = racecard_files(racecards).cache()
  races_raw = race_files(races_raw).cache()
  tables = {
    "courses": courses(racecards),
    "meetings": meetings(racecards),
    "races": keep(races(racecards, races_raw)),
    "runners": keep(runners(races_raw)),
    "horses": horses(races_raw),
    "jockeys": jockeys(races_raw),
    "trainers": trainers(races_raw),
    "prizes": prizes(races_raw),
    "horse_form": horse_form(races_raw),
    "odds_snapshots": keep(odds_snapshots(all_race_files)),
    "odds_history": odds_history(races_raw),
  }
  # Model features are built on top of the tables above.
  tables["runner_features"] = keep(runner_features(
    all_race_files,
    tables["races"],
    tables["runners"],
  ))
  if models:
    tables["model_odds"] = keep(model_odds(tables["runner_features"], models))
    tables["model_value"] = keep(model_value(
      tables["model_odds"],
      tables["odds_snapshots"],
      tables["runners"],
      tables["races"],
      blend,
    ))
    graded = keep(graded_view_rows(tables["model_value"], tables["races"]))
    tables["model_scorecard"] = model_scorecard(graded)
    tables["model_calibration"] = model_calibration(graded)
  return tables
