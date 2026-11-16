"""Our own fair win odds for every runner at every snapshot.

For each runner_features row:
  input       = the model's SQL expression (e.g. rating_diff * CASE WHEN has_handicap THEN 1 ELSE 0 END)
  standardised = (input - mean) / std, with the model's own mean and spread
  score       = sum of weight x standardised input
  probability = e^score / sum of e^score over the race's runners at that snapshot
  odds        = 1 / probability (and the nearest bookmaker price, for display)

The SQL expressions come from the model JSON, written so Athena (training)
and Spark (here) run them the same way. Each race uses the model chosen by
models.date_ranges(): the newest one trained only on earlier races.
"""

from functools import reduce
from operator import add

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql.functions import col, count, exp, expr, lit, rank
from pyspark.sql.functions import max as spark_max
from pyspark.sql.functions import sum as spark_sum

from data_jockey import conversions as conv
from data_jockey.models import date_ranges


def model_score(model: dict) -> Column:
  terms = []
  for item in model["inputs"]:
    value = expr(f"CAST({item['sql']} AS DOUBLE)")
    standardised = (value - lit(item["mean"])) / lit(item["std"])
    terms.append(standardised * lit(item["weight"]))
  return reduce(add, terms)


def model_priced_by(features: DataFrame, model: dict, after: str | None, up_to: str | None) -> DataFrame:
  in_range = lit(True)
  if after is not None:
    in_range = in_range & (col("race_date") > lit(after).cast("date"))
  if up_to is not None:
    in_range = in_range & (col("race_date") <= lit(up_to).cast("date"))
  trained_on_race = col("race_date") <= lit(model["trained_on"]["to"]).cast("date")

  return features.where(in_range).select(
    "ride_id",
    "snapshot",
    "snapshot_rank",
    "race_id",
    "race_date",
    "horse_id",
    lit(model["version"]).alias("model_version"),
    trained_on_race.alias("in_sample"),
    model_score(model).alias("score"),
  )


def select_model_odds_columns() -> list[Column]:
  field = Window.partitionBy("race_id", "snapshot")
  by_probability = Window.partitionBy("race_id", "snapshot").orderBy(col("model_prob").desc())
  model_odds_decimal = lit(1.0) / col("model_prob")

  return [
    col("ride_id"),
    col("snapshot"),
    col("snapshot_rank"),
    col("race_id"),
    col("race_date"),
    col("horse_id"),
    col("model_version"),
    col("in_sample"),
    col("score"),
    col("model_prob"),
    model_odds_decimal.alias("model_odds_decimal"),
    conv.fractional_odds(model_odds_decimal).alias("model_odds"),
    rank().over(by_probability).alias("model_rank"),
    count(lit(1)).over(field).alias("field_size"),
  ]


def normalise_odds(df: DataFrame) -> DataFrame:
  """Normalising all odds to add up to 100% in each race and snapshot."""
  field = Window.partitionBy("race_id", "snapshot")
  # Minus the race's top score so exp() can't overflow; it cancels out in the division.
  shifted = exp(col("score") - spark_max("score").over(field))
  df = df.withColumn("_shifted", shifted)
  model_prob = col("_shifted") / spark_sum("_shifted").over(field)
  return df.withColumn("model_prob", model_prob)


def model_odds(runner_features: DataFrame, models: list[dict]) -> DataFrame:
  priced = []
  for model, after, up_to in date_ranges(models):
    model_rows = model_priced_by(runner_features, model, after, up_to)
    priced.append(model_rows)
  df = reduce(DataFrame.unionByName, priced)

  df = normalise_odds(df)
  return df.select(select_model_odds_columns())
