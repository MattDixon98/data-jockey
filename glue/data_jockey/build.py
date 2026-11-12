"""Builds the clean tables from the raw racecard and race DataFrames.

Pure transformations, no I/O: the Glue job reads the raw JSON (with the
schemas in raw_schemas) and writes what comes back here, and the tests run the
same functions against the fixtures.

Every run rebuilds from all of past/, so each table is de-duplicated on its
key, keeping the copy from the most recent race file (and, for names, the most
recent non-null value).
"""

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql.functions import (
  coalesce,
  col,
  explode,
  lit,
  row_number,
  substring,
  to_date,
  transform,
  when,
)
from pyspark.sql.functions import filter as spark_filter
from pyspark.sql.functions import max as spark_max
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


# --- Flattening -------------------------------------------------------------


def _meetings_flat(racecards: DataFrame) -> DataFrame:
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


def _card_races(racecards: DataFrame) -> DataFrame:
  """Racecard-only race fields, keyed by race id, plus course and country."""
  meetings = _meetings_flat(racecards)
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


def _rides(races: DataFrame) -> DataFrame:
  """One row per ride, with its race id and date."""
  return races.select(
    col("race_summary.race_summary_reference.id").alias("race_id"),
    to_date("race_summary.date").alias("race_date"),
    explode("rides").alias("ride"),
  )


# --- Tables -----------------------------------------------------------------


def _course_shortcodes(racecards: DataFrame) -> DataFrame:
  """One shortcode (e.g. PUN) per course. Only the races carry it, not the course."""
  card_races = _card_races(racecards)
  with_shortcode = card_races.where(col("course_shortcode").isNotNull())

  # Every race at a course should have the same shortcode; spark_max() just picks one.
  by_course = with_shortcode.groupBy("course_id")
  return by_course.agg(spark_max("course_shortcode").alias("shortcode"))


def select_course_columns() -> list[Column]:
  return [
    col("course.course_reference.id").alias("course_id"),
    col("course.name").alias("name"),
    col("course.country.short_name").alias("country_code"),
    col("course.country.long_name").alias("country_name"),
    col("course.feed_source").alias("feed_source"),
    col("meeting_date"),
  ]


def courses(racecards: DataFrame) -> DataFrame:
  df = _meetings_flat(racecards).select(select_course_columns())
  df = latest(df, ["course_id"], [col("meeting_date").desc()])
  return df.join(_course_shortcodes(racecards), "course_id", "left")


def select_meeting_columns() -> list[Column]:
  return [
    col("meeting_id"),
    col("meeting_date"),
    col("course.course_reference.id").alias("course_id"),
    col("going"),
    col("surface_summary"),
    col("weather"),
  ]


def meetings(racecards: DataFrame) -> DataFrame:
  df = _meetings_flat(racecards).select(select_meeting_columns())
  return latest(df, ["meeting_id"], [col("meeting_date").desc()])


def select_race_columns() -> list[Column]:
  betting_forecast = conv.empty_to_null(col("betting_forecast"))
  has_forecast = betting_forecast != "No Forecast Available."
  forecast = (
    when(has_forecast, betting_forecast)
    .otherwise(lit(None))
  )

  return [
    col("race_summary.race_summary_reference.id").alias("race_id"),
    col("race_summary.meeting_summary_reference.id").alias("meeting_id"),
    to_date(col("race_summary.date")).alias("race_date"),
    col("race_summary.time").alias("race_time"),
    conv.empty_to_null(col("race_summary.off_time")).alias("off_time"),
    col("race_summary.name").alias("name"),
    conv.race_class(col("race_summary.race_class")).alias("race_class"),
    conv.empty_to_null(col("race_summary.age")).alias("age_band"),
    col("race_summary.course_surface.surface").alias("race_surface"),
    col("race_summary.distance").alias("distance"),
    conv.distance_yards(col("race_summary.distance")).alias("distance_yards"),
    conv.empty_to_null(col("race_summary.going")).alias("going"),
    col("race_summary.has_handicap").alias("has_handicap"),
    col("race_summary.race_stage").alias("race_stage"),
    conv.result_status(col("race_summary.race_stage")).alias("result_status"),
    col("race_summary.ride_count").alias("ride_count"),
    col("number_of_placed_rides").alias("placed_count"),
    conv.empty_to_null(col("race_summary.winning_time")).alias("winning_time"),
    conv.time_seconds(col("race_summary.winning_time")).alias("winning_time_seconds"),
    col("on_course_book_percentage").alias("book_percentage"),
    forecast.alias("betting_forecast"),
  ]


def races(racecards: DataFrame, races_raw: DataFrame) -> DataFrame:
  df = races_raw.select(select_race_columns())
  df = latest(df, ["race_id"], [col("race_date").desc()])

  # The racecard adds course, country, going shortcode, surface and verdict.
  df = df.join(_card_races(racecards), "race_id", "left")
  df = df.withColumn("surface", coalesce("race_surface", "card_surface"))
  return df.withColumn("verdict", conv.strip_html(col("card_verdict")))


def select_runner_columns() -> list[Column]:
  stats = col("ride.horse_lifetime_stats")
  insight_types = transform(col("ride.insights"), lambda insight: insight.type)
  known_insight_types = spark_filter(insight_types, lambda insight_type: insight_type.isNotNull())

  return [
    col("ride.ride_reference.id").alias("ride_id"),
    col("race_id"),
    col("race_date"),
    col("ride.horse.horse_reference.id").alias("horse_id"),
    col("ride.jockey.person_reference.id").alias("jockey_id"),
    col("ride.trainer.business_reference.id").alias("trainer_id"),
    conv.empty_to_null(col("ride.owner.name")).alias("owner_name"),
    col("ride.cloth_number").alias("cloth_number"),
    col("ride.draw_number").alias("draw"),
    col("ride.ride_status").alias("status"),
    conv.finish_position(col("ride.ride_status"), col("ride.finish_position")).alias("finish_position"),
    conv.non_finisher_reason(col("ride.casualty")).alias("non_finisher_reason"),
    col("ride.horse.age").alias("horse_age"),
    conv.empty_to_null(col("ride.handicap")).alias("weight"),
    conv.weight_lbs(col("ride.handicap")).alias("weight_lbs"),
    col("ride.official_rating").alias("official_rating"),
    conv.empty_to_null(col("ride.betting.current_odds")).alias("odds"),
    conv.odds_decimal(col("ride.betting.current_odds")).alias("odds_decimal"),
    conv.empty_to_null(col("ride.betting.favourite.betting_favourite")).alias("favourite"),
    conv.headgear_symbols(col("ride.headgear")).alias("headgear"),
    col("ride.horse.last_ran_days").alias("days_since_last_run"),
    conv.lifetime_stat(stats, "run_count").alias("lifetime_runs"),
    conv.lifetime_stat(stats, "win_count").alias("lifetime_wins"),
    conv.lifetime_stat(stats, "place_count").alias("lifetime_places"),
    known_insight_types.alias("insights"),
  ]


def runners(races_raw: DataFrame) -> DataFrame:
  df = _rides(races_raw).select(select_runner_columns())
  return latest(df, ["ride_id"], [col("race_date").desc()])


def select_horse_columns() -> list[Column]:
  return [
    col("ride.horse.horse_reference.id").alias("horse_id"),
    conv.empty_to_null(col("ride.horse.name")).alias("name"),
    conv.empty_to_null(col("ride.horse.slug")).alias("slug"),
    conv.empty_to_null(col("ride.horse.sex.type")).alias("sex"),
    to_date(col("ride.horse.foaled")).alias("foaled"),
    col("race_date"),
  ]


def horses(races_raw: DataFrame) -> DataFrame:
  df = _rides(races_raw).select(select_horse_columns())
  return latest(df, ["horse_id"], [col("name").isNull().asc(), col("race_date").desc()])


def select_jockey_columns() -> list[Column]:
  return [
    col("ride.jockey.person_reference.id").alias("jockey_id"),
    conv.empty_to_null(col("ride.jockey.name")).alias("name"),
    col("race_date"),
  ]


def jockeys(races_raw: DataFrame) -> DataFrame:
  df = _rides(races_raw).select(select_jockey_columns())
  df = df.where(col("jockey_id").isNotNull())
  return latest(df, ["jockey_id"], [col("name").isNull().asc(), col("race_date").desc()])


def select_trainer_columns() -> list[Column]:
  return [
    col("ride.trainer.business_reference.id").alias("trainer_id"),
    conv.empty_to_null(col("ride.trainer.name")).alias("name"),
    conv.empty_to_null(col("ride.trainer.slug")).alias("slug"),
    col("race_date"),
  ]


def trainers(races_raw: DataFrame) -> DataFrame:
  df = _rides(races_raw).select(select_trainer_columns())
  df = df.where(col("trainer_id").isNotNull())
  return latest(df, ["trainer_id"], [col("name").isNull().asc(), col("race_date").desc()])


def select_prize_columns() -> list[Column]:
  return [
    col("race_id"),
    col("race_date"),
    col("prize.position").alias("position"),
    conv.prize_amount(col("prize.prize")).alias("amount"),
    conv.prize_currency(col("prize.prize")).alias("currency"),
  ]


def prizes(races_raw: DataFrame) -> DataFrame:
  prize_rows = races_raw.select(
    col("race_summary.race_summary_reference.id").alias("race_id"),
    to_date(col("race_summary.date")).alias("race_date"),
    explode("prizes.prize").alias("prize"),
  )
  df = prize_rows.select(select_prize_columns())
  df = df.where(col("amount").isNotNull())
  return latest(df, ["race_id", "position"], [col("race_date").desc()])


def select_horse_form_columns() -> list[Column]:
  # Form rows have no ride status; 0 still means no recorded position.
  position = col("result.position")
  has_position = position > 0
  finish_position = (
    when(has_position, position)
    .otherwise(lit(None))
  )

  return [
    col("horse_id"),
    col("source_date"),
    col("result.race_id").alias("race_id"),
    to_date(col("result.date")).alias("race_date"),
    substring(col("result.time"), 1, 5).alias("race_time"),
    conv.empty_to_null(col("result.course_name")).alias("course_name"),
    conv.empty_to_null(col("result.course_shortcode")).alias("course_shortcode"),
    conv.empty_to_null(col("result.race_name")).alias("race_name"),
    conv.race_class(col("result.race_class")).alias("race_class"),
    conv.empty_to_null(col("result.run_type")).alias("run_type"),
    conv.empty_to_null(col("result.distance")).alias("distance"),
    conv.distance_yards(col("result.distance")).alias("distance_yards"),
    conv.empty_to_null(col("result.going")).alias("going"),
    conv.empty_to_null(col("result.going_shortcode")).alias("going_shortcode"),
    col("result.runner_count").alias("runner_count"),
    finish_position.alias("finish_position"),
    conv.non_finisher_reason(col("result.casualty")).alias("non_finisher_reason"),
    conv.empty_to_null(col("result.weight")).alias("weight"),
    conv.weight_lbs(col("result.weight")).alias("weight_lbs"),
    col("result.bha").alias("official_rating"),
    conv.empty_to_null(col("result.odds")).alias("odds"),
    conv.odds_decimal(col("result.odds")).alias("odds_decimal"),
  ]


def horse_form(races_raw: DataFrame) -> DataFrame:
  """One row per previous run listed on each runner (horse.previous_results)."""
  results = _rides(races_raw).select(
    col("ride.horse.horse_reference.id").alias("horse_id"),
    col("race_date").alias("source_date"),
    explode("ride.horse.previous_results").alias("result"),
  )
  df = results.select(select_horse_form_columns())
  has_keys = col("race_id").isNotNull() & col("horse_id").isNotNull()
  df = df.where(has_keys)
  return latest(df, ["horse_id", "race_id"], [col("source_date").desc()])


def build_all(racecards: DataFrame, races_raw: DataFrame) -> dict[str, DataFrame]:
  """Every clean table, keyed by table name (unconformed column order)."""
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
