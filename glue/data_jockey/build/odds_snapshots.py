from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import col

from data_jockey import conversions as conv
from data_jockey.build.utilities import latest, rides, with_snapshot


def select_odds_snapshot_columns() -> list[Column]:
  return [
    col("ride.ride_reference.id").alias("ride_id"),
    col("race_id"),
    col("race_date"),
    col("ride.horse.horse_reference.id").alias("horse_id"),
    col("snapshot"),
    conv.snapshot_rank(col("snapshot")).alias("snapshot_rank"),
    col("ride.ride_status").alias("status"),
    conv.empty_to_null(col("ride.betting.current_odds")).alias("odds"),
    conv.odds_decimal(col("ride.betting.current_odds")).alias("odds_decimal"),
    conv.empty_to_null(col("ride.betting.favourite.betting_favourite")).alias("favourite"),
  ]


def odds_snapshots(races_raw: DataFrame) -> DataFrame:
  """Each runner's price in every snapshot that has one: forecast prices at t-1 and today, the starting price from past. 
  Built from every race file, not just the most trusted one; rows without a price (most t-2/t-3 crawls, non-runners) are left out."""
  df = rides(with_snapshot(races_raw)).select(select_odds_snapshot_columns())
  df = df.where(col("odds").isNotNull())
  return latest(df, ["ride_id", "snapshot"], [col("race_date").desc()])
