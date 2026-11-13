from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import col

from data_jockey import conversions as conv
from data_jockey.build.utilities import latest, rides


def select_jockey_columns() -> list[Column]:
  return [
    col("ride.jockey.person_reference.id").alias("jockey_id"),
    conv.empty_to_null(col("ride.jockey.name")).alias("name"),
    col("race_date"),
  ]


def jockeys(races_raw: DataFrame) -> DataFrame:
  df = rides(races_raw).select(select_jockey_columns())
  df = df.where(col("jockey_id").isNotNull())
  return latest(df, ["jockey_id"], [col("name").isNull().asc(), col("race_date").desc()])
