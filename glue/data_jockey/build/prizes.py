from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import col, explode, to_date

from data_jockey import conversions as conv
from data_jockey.build.utilities import latest


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
