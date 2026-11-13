from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import col
from pyspark.sql.functions import max as spark_max

from data_jockey.build.utilities import card_races, latest, meetings_flat


def _course_shortcodes(racecards: DataFrame) -> DataFrame:
  """One shortcode (e.g. PUN) per course. Only the races carry it, not the course."""
  races = card_races(racecards)
  with_shortcode = races.where(col("course_shortcode").isNotNull())

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
  df = meetings_flat(racecards).select(select_course_columns())
  df = latest(df, ["course_id"], [col("meeting_date").desc()])
  return df.join(_course_shortcodes(racecards), "course_id", "left")
