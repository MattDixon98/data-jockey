from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import col, to_date

from data_jockey import conversions as conv
from data_jockey.build.utilities import latest, rides


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
  df = rides(races_raw).select(select_horse_columns())
  return latest(df, ["horse_id"], [col("name").isNull().asc(), col("race_date").desc()])
