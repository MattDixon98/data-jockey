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

With a blend (model/blend.json, see data_jockey.models), blended_prob combines
our probability with the market's for the same race and snapshot (softmax of
model_weight x ln(model_prob) + market_weight x ln(market_prob)), and the flag
is decided from it: when we disagree with the market, the blend says how far
to trust us. Without one, or for a market it has no weights for, blended_prob
is NULL and the flag uses model_prob.
"""

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql.functions import coalesce, col, collect_list, count, exp, lit, log, when
from pyspark.sql.functions import max as spark_max
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


def market_name() -> Column:
  is_past = col("snapshot") == "past"
  return (
    when(is_past, lit("SP"))
    .otherwise(lit("forecast"))
  )


def blend_weight(blend: dict, key: str) -> Column:
  """The blend's `key` weight for each row's market; NULL for a market it doesn't cover."""
  weight = lit(None).cast("double")
  for market, weights in blend["markets"].items():
    weight = when(col("market") == market, lit(float(weights[key]))).otherwise(weight)
  return weight


def with_blend(df: DataFrame, blend: dict | None) -> DataFrame:
  """blended_prob and blend_version (NULL without a blend for the row's market)."""
  df = df.withColumn("market", market_name())
  if blend is None:
    return (
      df.withColumn("blended_prob", lit(None).cast("double"))
      .withColumn("blend_version", lit(None).cast("string"))
    )

  model_weight = blend_weight(blend, "model_weight")
  market_weight = blend_weight(blend, "market_weight")
  score = model_weight * log(col("model_prob")) + market_weight * log(col("market_prob"))
  field = Window.partitionBy("race_id", "snapshot")
  # Subtract the race's highest score first, so exp() can't overflow.
  shifted = exp(col("_blend_score") - spark_max("_blend_score").over(field))
  df = df.withColumn("_blend_score", score).withColumn("_blend_exp", shifted)
  blended_prob = col("_blend_exp") / spark_sum("_blend_exp").over(field)
  has_weights = model_weight.isNotNull()
  blend_version = (
    when(has_weights, lit(blend["version"]))
    .otherwise(lit(None).cast("string"))
  )
  return (
    df.withColumn("blended_prob", blended_prob)
    .withColumn("blend_version", blend_version)
    .drop("_blend_score", "_blend_exp")
  )


def select_model_value_columns() -> list[Column]:
  edge = col("model_prob") / col("market_prob") - lit(1.0)
  expected_value = col("model_prob") * col("market_odds_decimal") - lit(1.0)
  blended_expected_value = col("blended_prob") * col("market_odds_decimal") - lit(1.0)

  # The flag: from the blend where there is one, else from our probability.
  flag_prob = coalesce(col("blended_prob"), col("model_prob"))
  flag_expected_value = flag_prob * col("market_odds_decimal") - lit(1.0)
  is_value = flag_expected_value >= lit(MIN_EXPECTED_VALUE)
  is_strong_chance = flag_prob >= lit(MIN_MODEL_PROB)
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
    col("market"),
    col("market_odds"),
    col("market_odds_decimal"),
    col("market_prob"),
    col("book_percentage"),
    edge.alias("edge"),
    expected_value.alias("expected_value"),
    undervalued.alias("undervalued"),
    col("won"),
    col("finish_position"),
    col("blend_version"),
    col("blended_prob"),
    blended_expected_value.alias("blended_expected_value"),
  ]


def model_value(
  model_odds: DataFrame,
  odds_snapshots: DataFrame,
  runners: DataFrame,
  races: DataFrame,
  blend: dict | None = None,
) -> DataFrame:
  """Takes the built model_odds, odds_snapshots, runners and races tables, and the blend if there is one."""
  df = with_market_prices(model_odds, odds_snapshots)
  df = with_market_probabilities(df)
  df = with_blend(df, blend)
  df = with_results(df, runners, races)
  return df.select(select_model_value_columns())
