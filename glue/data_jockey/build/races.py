from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import coalesce, col, lit, to_date, when

from data_jockey import conversions as conv
from data_jockey.build.utilities import card_races, from_past, latest


def select_race_columns() -> list[Column]:
  betting_forecast = conv.empty_to_null(col("betting_forecast"))
  has_forecast = betting_forecast != "No Forecast Available."
  forecast = (
    when(has_forecast, betting_forecast)
    .otherwise(lit(None))
  )

  # A result is only trusted from past/; a later crawl can still show an
  # upcoming race as abandoned.
  stage_status = conv.result_status(col("race_summary.race_stage"))
  is_past = col("snapshot") == "past"
  is_early_complete = (stage_status == "complete") & ~is_past
  result_status = (
    when(is_early_complete, lit("incomplete"))
    .otherwise(stage_status)
  )
  winning_time = conv.empty_to_null(col("race_summary.winning_time"))
  winning_time_seconds = conv.time_seconds(col("race_summary.winning_time"))

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
    result_status.alias("result_status"),
    col("race_summary.ride_count").alias("ride_count"),
    col("number_of_placed_rides").alias("placed_count"),
    from_past(winning_time).alias("winning_time"),
    from_past(winning_time_seconds).alias("winning_time_seconds"),
    col("on_course_book_percentage").alias("book_percentage"),
    forecast.alias("betting_forecast"),
    col("snapshot"),
  ]


def races(racecards: DataFrame, races_raw: DataFrame) -> DataFrame:
  df = races_raw.select(select_race_columns())
  df = latest(df, ["race_id"], [col("race_date").desc()])

  # The racecard adds course, country, going shortcode, surface and verdict.
  df = df.join(card_races(racecards), "race_id", "left")
  df = df.withColumn("surface", coalesce("race_surface", "card_surface"))
  return df.withColumn("verdict", conv.strip_html(col("card_verdict")))
