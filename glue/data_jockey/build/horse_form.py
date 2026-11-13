from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import col, explode, lit, substring, to_date, when

from data_jockey import conversions as conv
from data_jockey.build.utilities import latest, rides


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
  results = rides(races_raw).select(
    col("ride.horse.horse_reference.id").alias("horse_id"),
    col("race_date").alias("source_date"),
    explode("ride.horse.previous_results").alias("result"),
  )
  df = results.select(select_horse_form_columns())
  has_keys = col("race_id").isNotNull() & col("horse_id").isNotNull()
  df = df.where(has_keys)
  return latest(df, ["horse_id", "race_id"], [col("source_date").desc()])
