from pyspark.sql import Column, DataFrame
from pyspark.sql.functions import col, transform
from pyspark.sql.functions import filter as spark_filter

from data_jockey import conversions as conv
from data_jockey.build.utilities import from_past, latest, rides


def select_runner_columns() -> list[Column]:
  stats = col("ride.horse_lifetime_stats")
  insight_types = transform(col("ride.insights"), lambda insight: insight.type)
  known_insight_types = spark_filter(insight_types, lambda insight_type: insight_type.isNotNull())
  finish_position = conv.finish_position(col("ride.ride_status"), col("ride.finish_position"))
  non_finisher_reason = conv.non_finisher_reason(col("ride.casualty"))

  return [
    col("ride.ride_reference.id").alias("ride_id"),
    col("race_id"),
    col("race_date"),
    col("ride.horse.horse_reference.id").alias("horse_id"),
    col("ride.jockey.person_reference.id").alias("jockey_id"),
    col("ride.trainer.business_reference.id").alias("trainer_id"),
    conv.empty_to_null(col("ride.owner.name")).alias("owner_name"),
    col("ride.cloth_number").alias("cloth_number"),
    col("ride.draw_number").alias("draw"),
    col("ride.ride_status").alias("status"),
    from_past(finish_position).alias("finish_position"),
    from_past(non_finisher_reason).alias("non_finisher_reason"),
    col("ride.horse.age").alias("horse_age"),
    conv.empty_to_null(col("ride.handicap")).alias("weight"),
    conv.weight_lbs(col("ride.handicap")).alias("weight_lbs"),
    col("ride.official_rating").alias("official_rating"),
    conv.empty_to_null(col("ride.betting.current_odds")).alias("odds"),
    conv.odds_decimal(col("ride.betting.current_odds")).alias("odds_decimal"),
    conv.empty_to_null(col("ride.betting.favourite.betting_favourite")).alias("favourite"),
    conv.headgear_symbols(col("ride.headgear")).alias("headgear"),
    col("ride.horse.last_ran_days").alias("days_since_last_run"),
    conv.lifetime_stat(stats, "run_count").alias("lifetime_runs"),
    conv.lifetime_stat(stats, "win_count").alias("lifetime_wins"),
    conv.lifetime_stat(stats, "place_count").alias("lifetime_places"),
    known_insight_types.alias("insights"),
    col("snapshot"),
  ]


def runners(races_raw: DataFrame) -> DataFrame:
  df = rides(races_raw).select(select_runner_columns())
  return latest(df, ["ride_id"], [col("race_date").desc()])
