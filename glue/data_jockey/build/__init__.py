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

from pyspark.sql import DataFrame

from data_jockey.build.utilities import conform, latest, race_files, racecard_files
from data_jockey.build.courses import courses
from data_jockey.build.horse_form import horse_form
from data_jockey.build.horses import horses
from data_jockey.build.jockeys import jockeys
from data_jockey.build.meetings import meetings
from data_jockey.build.prizes import prizes
from data_jockey.build.races import races
from data_jockey.build.runners import runners
from data_jockey.build.trainers import trainers

__all__ = ["build_all", "conform", "latest"]


def build_all(racecards: DataFrame, races_raw: DataFrame) -> dict[str, DataFrame]:
  """Every clean table, keyed by table name (unconformed column order).

  Takes the raw reads (with source_file) of every snapshot.
  """
  racecards = racecard_files(racecards)
  races_raw = race_files(races_raw)
  return {
    "courses": courses(racecards),
    "meetings": meetings(racecards),
    "races": races(racecards, races_raw),
    "runners": runners(races_raw),
    "horses": horses(races_raw),
    "jockeys": jockeys(races_raw),
    "trainers": trainers(races_raw),
    "prizes": prizes(races_raw),
    "horse_form": horse_form(races_raw),
  }
