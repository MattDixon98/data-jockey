from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import col, posexplode

from data_jockey import conversions as conv
from data_jockey.build.utilities import latest, rides


def select_odds_history_columns() -> list[Column]:
  seq = col("position") + 1

  return [
    col("ride.ride_reference.id").alias("ride_id"),
    col("race_id"),
    col("race_date"),
    col("ride.horse.horse_reference.id").alias("horse_id"),
    seq.alias("seq"),
    conv.empty_to_null(col("price")).alias("odds"),
    conv.odds_decimal(col("price")).alias("odds_decimal"),
  ]


def odds_history(races_raw: DataFrame) -> DataFrame:
  """The on-course market for each runner, one row per price shown (betting.historical_odds, opening show first). Only past files have it."""
  past = rides(races_raw).where(col("snapshot") == "past")
  prices = past.select("*", posexplode("ride.betting.historical_odds").alias("position", "price"))
  df = prices.select(select_odds_history_columns())
  df = df.where(col("odds").isNotNull())
  return latest(df, ["ride_id", "seq"], [col("race_date").desc()])
