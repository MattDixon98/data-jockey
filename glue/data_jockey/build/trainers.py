from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import col

from data_jockey import conversions as conv
from data_jockey.build.utilities import latest, rides


def select_trainer_columns() -> list[Column]:
  return [
    col("ride.trainer.business_reference.id").alias("trainer_id"),
    conv.empty_to_null(col("ride.trainer.name")).alias("name"),
    conv.empty_to_null(col("ride.trainer.slug")).alias("slug"),
    col("race_date"),
  ]


def trainers(races_raw: DataFrame) -> DataFrame:
  df = rides(races_raw).select(select_trainer_columns())
  df = df.where(col("trainer_id").isNotNull())
  return latest(df, ["trainer_id"], [col("name").isNull().asc(), col("race_date").desc()])
