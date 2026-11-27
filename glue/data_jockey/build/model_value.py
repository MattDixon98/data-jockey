"""Our probability next to the market's, and whether the market underrates a runner.

One row per model_odds row whose race has a full set of market prices at
that snapshot: past rows against SP, today / t-1 (and the odd priced t-2)
against the forecast price. t-3 and most t-2 crawls have no prices, so
those runners only have our odds (model_odds).

The market's probabilities have the bookmakers' margin removed with Shin's
method (conversions.shin_z / shin_probability), which takes more of it off
the longshots than dividing evenly would.

Once the race has been run, every row gets the result (won,
finish_position), so the pre-race flags the site showed can be graded too.
A runner that didn't run gets won = NULL: a bet on it would have been void.
"""

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql.functions import coalesce, col, collect_list, count, lit, when
from pyspark.sql.functions import sum as spark_sum

from data_jockey import conversions as conv

# Undervalued: a bet at the market price is worth at least this much on
# average if our probability is right, we give it at least this chance, and
# the market price is no longer than this. Chosen 27 Nov (athena/flag_analysis.sql,
# 449 out-of-sample races): the old rule (EV >= 10%, prob >= 5%, any price)
# lost 32% race-morning, mostly on longshots, where the margin is heaviest and
# our odds least reliable; strong chances at 5/1 or shorter broke even in both
# weeks tested. Break-even, not an edge yet.
MIN_EXPECTED_VALUE = 0.0
MIN_MODEL_PROB = 0.20
MAX_MARKET_ODDS_DECIMAL = 6.0  # 5/1


def with_market_prices(model_odds: DataFrame, odds_snapshots: DataFrame) -> DataFrame:
  """model_odds rows whose race is fully priced at that snapshot, with the price."""
  prices = odds_snapshots.select(
    col("ride_id"),
    col("snapshot"),
    col("odds").alias("market_odds"),
    col("odds_decimal").alias("market_odds_decimal"),
  )
  df = model_odds.join(prices, ["ride_id", "snapshot"], "left")

  field = Window.partitionBy("race_id", "snapshot")
  has_price = col("market_odds_decimal") > 1
  priced_runners = spark_sum(has_price.cast("int")).over(field)
  runners = count(lit(1)).over(field)
  df = df.withColumn("_fully_priced", priced_runners == runners)
  return df.where(col("_fully_priced")).drop("_fully_priced")


def with_market_probabilities(df: DataFrame) -> DataFrame:
  """market_prob (Shin, adding up to 1 per race and snapshot) and book_percentage."""
  df = df.withColumn("_implied", lit(1.0) / col("market_odds_decimal"))

  races = df.groupBy("race_id", "snapshot").agg(
    collect_list("_implied").alias("_implied_all"),
    spark_sum("_implied").alias("_book"),
  )
  races = races.withColumn("_z", conv.shin_z(col("_implied_all"))).drop("_implied_all")
  df = df.join(races, ["race_id", "snapshot"])

  # Shin's probabilities already add up to 1 to ~1e-13; rescale the rest away.
  shin = conv.shin_probability(col("_implied"), col("_book"), col("_z"))
  df = df.withColumn("_shin", shin)
  field = Window.partitionBy("race_id", "snapshot")
  market_prob = col("_shin") / spark_sum("_shin").over(field)
  return df.withColumn("market_prob", market_prob).withColumn("book_percentage", col("_book") * 100)


def with_results(df: DataFrame, runners: DataFrame, races: DataFrame) -> DataFrame:
  """won / finish_position once the race has been run; NULL before, and for runners that didn't run (non-runners, or entries dropped before the off)."""
  results = runners.select(
    col("ride_id"),
    col("status").alias("_final_status"),
    col("finish_position"),
  )
  settled = races.select("race_id", (col("result_status") == "complete").alias("_settled"))
  df = df.join(results, "ride_id", "left").join(settled, "race_id", "left")

  ran = col("_final_status") == "RUNNER"
  is_graded = coalesce(col("_settled"), lit(False)) & coalesce(ran, lit(False))
  is_winner = coalesce(col("finish_position") == 1, lit(False))
  won = (
    when(is_graded, is_winner)
    .otherwise(lit(None))
  )
  finish_position = (
    when(is_graded, col("finish_position"))
    .otherwise(lit(None))
  )
  return df.withColumn("won", won).withColumn("finish_position", finish_position)


def select_model_value_columns() -> list[Column]:
  is_past = col("snapshot") == "past"
  market = (
    when(is_past, lit("SP"))
    .otherwise(lit("forecast"))
  )
  edge = col("model_prob") / col("market_prob") - lit(1.0)
  expected_value = col("model_prob") * col("market_odds_decimal") - lit(1.0)
  is_value = expected_value >= lit(MIN_EXPECTED_VALUE)
  is_strong_chance = col("model_prob") >= lit(MIN_MODEL_PROB)
  is_short_price = col("market_odds_decimal") <= lit(MAX_MARKET_ODDS_DECIMAL)
  undervalued = is_value & is_strong_chance & is_short_price

  return [
    col("ride_id"),
    col("snapshot"),
    col("snapshot_rank"),
    col("race_id"),
    col("race_date"),
    col("horse_id"),
    col("model_version"),
    col("in_sample"),
    col("model_prob"),
    col("model_odds"),
    market.alias("market"),
    col("market_odds"),
    col("market_odds_decimal"),
    col("market_prob"),
    col("book_percentage"),
    edge.alias("edge"),
    expected_value.alias("expected_value"),
    undervalued.alias("undervalued"),
    col("won"),
    col("finish_position"),
  ]


def model_value(model_odds: DataFrame, odds_snapshots: DataFrame, runners: DataFrame, races: DataFrame) -> DataFrame:
  """Takes the built model_odds, odds_snapshots, runners and races tables."""
  df = with_market_prices(model_odds, odds_snapshots)
  df = with_market_probabilities(df)
  df = with_results(df, runners, races)
  return df.select(select_model_value_columns())
