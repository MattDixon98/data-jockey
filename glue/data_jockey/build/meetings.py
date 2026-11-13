from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import col

from data_jockey.build.utilities import latest, meetings_flat


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
  df = meetings_flat(racecards).select(select_meeting_columns())
  return latest(df, ["meeting_id"], [col("meeting_date").desc()])
