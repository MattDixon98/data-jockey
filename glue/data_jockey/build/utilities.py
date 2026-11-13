"""Shared building blocks for the table modules: de-duplication, conforming to
a table's schema, picking each race's most trusted snapshot, and flattening the
raw racecard and race DataFrames."""

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql.functions import col, explode, lit, row_number, to_date, when
from pyspark.sql.functions import min as spark_min
from pyspark.sql.types import StructType

from data_jockey import conversions as conv


def latest(df: DataFrame, keys: list[str], order_by: list[Column]) -> DataFrame:
  """One row per key: the first row by `order_by` (pass descending columns)."""
  window = Window.partitionBy(*keys).orderBy(*order_by)
  return (
    df.withColumn("_rank", row_number().over(window))
    .where(col("_rank") == 1)
    .drop("_rank")
  )


def conform(df: DataFrame, schema: StructType) -> DataFrame:
  """Select the table's columns, in its order, cast to its types; fail if any are missing."""
  missing = [field.name for field in schema.fields if field.name not in df.columns]
  if missing:
    raise ValueError(f"missing columns: {missing}")

  columns = []
  for field in schema.fields:
    column = col(field.name).cast(field.dataType).alias(field.name)
    columns.append(column)

  return df.select(columns)


# --- Snapshots --------------------------------------------------------------


def with_snapshot(raw: DataFrame) -> DataFrame:
  """Adds `snapshot` (past, today, t-N) and `snapshot_rank` from source_file."""
  snapshot = conv.snapshot(col("source_file"))
  rank = conv.snapshot_rank(snapshot)
  return raw.withColumn("snapshot", snapshot).withColumn("snapshot_rank", rank)


def most_trusted(df: DataFrame, keys: list[str]) -> DataFrame:
  """Every row from the most trusted snapshot of each key (lowest snapshot_rank), so all of one file's rows are kept together."""
  window = Window.partitionBy(*keys)
  best_rank = spark_min("snapshot_rank").over(window)
  return (
    df.withColumn("_best_rank", best_rank)
    .where(col("snapshot_rank") == col("_best_rank"))
    .drop("_best_rank")
  )


def race_files(races_raw: DataFrame) -> DataFrame:
  """One raw race file per race: its most trusted snapshot."""
  df = with_snapshot(races_raw)
  df = df.withColumn("race_id", col("race_summary.race_summary_reference.id"))
  df = most_trusted(df, ["race_id"])
  return df.drop("race_id")


def racecard_files(racecards: DataFrame) -> DataFrame:
  """Each date's meetings from its most trusted racecard file."""
  df = with_snapshot(racecards)
  df = df.withColumn("card_date", to_date(col("meeting_summary.date")))
  df = most_trusted(df, ["card_date"])
  return df.drop("card_date")


def from_past(value: Column) -> Column:
  """`value` if the row comes from past/, else NULL: results only come from past."""
  is_past = col("snapshot") == "past"

  return (
    when(is_past, value)
    .otherwise(lit(None))
  )


# --- Flattening -------------------------------------------------------------


def meetings_flat(racecards: DataFrame) -> DataFrame:
  """One row per meeting, with its course struct and its races array."""
  ms = col("meeting_summary")
  return racecards.select(
    ms.meeting_reference.id.alias("meeting_id"),
    to_date(ms.date).alias("meeting_date"),
    ms.course.alias("course"),
    conv.empty_to_null(ms.going).alias("going"),
    conv.empty_to_null(ms.surface_summary).alias("surface_summary"),
    conv.empty_to_null(ms.weather).alias("weather"),
    col("races"),
  )


def card_races(racecards: DataFrame) -> DataFrame:
  """Racecard-only race fields, keyed by race id, plus course and country."""
  meetings = meetings_flat(racecards)
  races = meetings.select(
    "meeting_date",
    col("course.course_reference.id").alias("course_id"),
    col("course.country.short_name").alias("country_code"),
    explode("races").alias("r"),
  )
  races = races.select(
    col("r.race_summary_reference.id").alias("race_id"),
    "course_id",
    "country_code",
    "meeting_date",
    conv.empty_to_null(col("r.course_shortcode")).alias("course_shortcode"),
    conv.empty_to_null(col("r.going_shortcode")).alias("going_shortcode"),
    col("r.course_surface.surface").alias("card_surface"),
    col("r.verdict").alias("card_verdict"),
  )
  return latest(races, ["race_id"], [col("meeting_date").desc()]).drop("meeting_date")


def rides(races: DataFrame) -> DataFrame:
  """One row per ride, with its race id, date and snapshot."""
  return races.select(
    col("race_summary.race_summary_reference.id").alias("race_id"),
    to_date("race_summary.date").alias("race_date"),
    col("snapshot"),
    explode("rides").alias("ride"),
  )
