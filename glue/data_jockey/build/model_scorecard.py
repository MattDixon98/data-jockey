"""How good our odds and our undervalued picks have been: model_scorecard and
model_calibration.

Only out-of-sample rows (in_sample = false) of races that have been run,
from model_value. Two views of each race:
  after_race  the past rows: our odds vs SP, on the final field
  site_pick   the race-morning (today) row, or t-1 if there was no today
              crawl: what the site showed before the race

Profit and "did flagged runners beat the market's expectation" always use
SP, the final official price a bet is settled at, whichever view flagged
the runner. A flagged runner that didn't run (won is NULL) is a void bet.

Next to the flags, two simple strategies to measure them against: 1 unit per
race on our favourite (model_rank 1) and on the market's (market_rank 1, SP
for after_race, the forecast for site_pick), also settled at SP. Joint
favourites split the unit, so each strategy stakes exactly 1 unit per race.

model_scorecard has one row per view, period (all time, each month, each
day, each model version) and race group (all, flat, jumps). With few races the
numbers swing a lot by chance, so the flags carry a z-score and a 95% range
on their return.
"""

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql.functions import (
  array,
  avg,
  coalesce,
  col,
  count,
  countDistinct,
  date_format,
  explode,
  lit,
  ln,
  stddev_samp,
  struct,
  when,
)
from pyspark.sql.functions import max as spark_max
from pyspark.sql.functions import min as spark_min
from pyspark.sql.functions import rank as spark_rank
from pyspark.sql.functions import sqrt as spark_sqrt
from pyspark.sql.functions import sum as spark_sum

# Probability bands for model_calibration (lower bound inclusive).
CALIBRATION_BANDS = [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0]
# 95% of a normal distribution lies within this many standard errors.
Z_95 = 1.96


# --- The two views ----------------------------------------------------------


def site_pick_rows(value: DataFrame) -> DataFrame:
  """Each race's race-morning (today) rows, or its t-1 rows if it has no today rows."""
  pre_race = value.where(col("snapshot").isin("today", "t-1"))
  race = Window.partitionBy("race_id")
  is_today = (col("snapshot") == "today").cast("int")
  # Window results have to be columns before they can be filtered on.
  pre_race = pre_race.withColumn("_has_today", spark_max(is_today).over(race) == 1)
  wanted = (
    when(col("_has_today"), col("snapshot") == "today")
    .otherwise(col("snapshot") == "t-1")
  )
  return pre_race.where(wanted).drop("_has_today").withColumn("view", lit("site_pick"))


def graded_view_rows(value: DataFrame, races: DataFrame) -> DataFrame:
  """Both views' rows for out-of-sample races that have been run (exactly one
  winner among the view's runners), with each runner's SP and SP probability,
  our and the market's rank in the race, and its race group."""
  after_race = value.where(col("snapshot") == "past").withColumn("view", lit("after_race"))
  df = after_race.unionByName(site_pick_rows(value))
  df = df.where(~col("in_sample") & col("won").isNotNull())

  view_race = Window.partitionBy("view", "race_id")
  winners = spark_sum(col("won").cast("int")).over(view_race)
  df = df.withColumn("_winners", winners).where(col("_winners") == 1).drop("_winners")

  # SP for every row, from the race's past row (also for site_pick rows).
  sp = value.where(col("snapshot") == "past").select(
    col("ride_id"),
    col("market_odds_decimal").alias("sp_decimal"),
    col("market_prob").alias("sp_prob"),
  )
  df = df.join(sp, "ride_id", "left")

  by_model = Window.partitionBy("view", "race_id").orderBy(col("model_prob").desc())
  by_market = Window.partitionBy("view", "race_id").orderBy(col("market_prob").desc())
  race_type = races.select("race_id", "race_type")
  df = df.join(race_type, "race_id", "left")
  is_flat = col("race_type") == "FLAT"
  race_group = (
    when(is_flat, lit("flat"))
    .when(col("race_type").isNotNull(), lit("jumps"))
    .otherwise(lit("unknown"))
  )
  return (
    df.withColumn("model_rank", spark_rank().over(by_model))
    .withColumn("market_rank", spark_rank().over(by_market))
    .withColumn("race_group", race_group)
  )


# --- model_scorecard --------------------------------------------------------


def with_breakdowns(df: DataFrame) -> DataFrame:
  """Each row once per period (all time, its month, its day, its model version) and race group (all, and its own flat/jumps): eight copies, ready to group."""
  periods = array(
    struct(lit("all").alias("period_type"), lit("all").alias("period")),
    struct(lit("month").alias("period_type"), date_format("race_date", "yyyy-MM").alias("period")),
    struct(lit("day").alias("period_type"), date_format("race_date", "yyyy-MM-dd").alias("period")),
    struct(lit("model_version").alias("period_type"), col("model_version").alias("period")),
  )
  groups = array(lit("all"), col("race_group"))
  df = df.withColumn("_period", explode(periods)).withColumn("_group", explode(groups))
  return df.select(
    "*",
    col("_period.period_type").alias("period_type"),
    col("_period.period").alias("period"),
  ).drop("_period", "race_group").withColumnRenamed("_group", "race_group")


def with_top_pick_stakes(df: DataFrame) -> DataFrame:
  """Adds _model_pick_stake and _market_pick_stake: 1 unit per race on the
  favourite, split between joint favourites, NULL for every other runner
  (and for a favourite with no SP, a void bet)."""
  view_race = Window.partitionBy("view", "race_id")
  has_sp = col("sp_decimal").isNotNull()
  for source in ("model", "market"):
    is_pick = (col(f"{source}_rank") == 1) & has_sp
    picks_in_race = spark_sum(is_pick.cast("int")).over(view_race)
    stake = (
      when(is_pick, lit(1.0) / picks_in_race)
      .otherwise(lit(None))
    )
    df = df.withColumn(f"_{source}_pick_stake", stake)
  return df


def top_pick_profit(stake: Column) -> Column:
  """Profit of a top-pick stake at SP: stake x (SP - 1) if it won, else -stake."""
  return (
    when(col("won"), stake * (col("sp_decimal") - lit(1.0)))
    .otherwise(-stake)
  )


def select_scorecard_aggregates() -> list[Column]:
  won = col("won")
  is_bet = col("undervalued") & col("sp_decimal").isNotNull()
  bet_profit = (
    when(is_bet & won, col("sp_decimal") - lit(1.0))
    .when(is_bet, lit(-1.0))
    .otherwise(lit(None))
  )
  winner_model_loss = when(won, -ln(col("model_prob")))
  winner_market_loss = when(won, -ln(col("market_prob")))
  top_pick_won = (won & (col("model_rank") == 1)).cast("int")
  favourite_won = (won & (col("market_rank") == 1)).cast("int")
  bet_sp_variance = when(is_bet, col("sp_prob") * (lit(1.0) - col("sp_prob")))

  return [
    spark_min("race_date").alias("first_race"),
    spark_max("race_date").alias("last_race"),
    countDistinct("race_id").alias("races"),
    count(lit(1)).alias("runners"),
    spark_sum(winner_model_loss).alias("_model_loss"),
    spark_sum(winner_market_loss).alias("_market_loss"),
    spark_sum(top_pick_won).alias("_top_picks_won"),
    spark_sum(favourite_won).alias("_favourites_won"),
    spark_sum(is_bet.cast("int")).alias("bets"),
    spark_sum((is_bet & won).cast("int")).alias("bets_won"),
    spark_sum(when(is_bet, col("sp_prob"))).alias("expected_wins_market"),
    spark_sum(when(is_bet, col("model_prob"))).alias("expected_wins_model"),
    spark_sum(bet_sp_variance).alias("_wins_variance"),
    spark_sum(bet_profit).alias("profit_units"),
    stddev_samp(bet_profit).alias("_profit_spread"),
    spark_sum("_model_pick_stake").alias("_model_pick_staked"),
    spark_sum(top_pick_profit(col("_model_pick_stake"))).alias("top_pick_profit_model"),
    spark_sum("_market_pick_stake").alias("_market_pick_staked"),
    spark_sum(top_pick_profit(col("_market_pick_stake"))).alias("top_pick_profit_market"),
  ]


def select_scorecard_columns() -> list[Column]:
  races = col("races")
  bets = col("bets")
  roi = col("profit_units") / bets
  roi_margin = lit(Z_95) * col("_profit_spread") / spark_sqrt(bets)
  wins_above_expected = col("bets_won") - col("expected_wins_market")
  wins_z = wins_above_expected / spark_sqrt(col("_wins_variance"))
  top_pick_roi_model = col("top_pick_profit_model") / col("_model_pick_staked")
  top_pick_roi_market = col("top_pick_profit_market") / col("_market_pick_staked")

  return [
    col("view"),
    col("period_type"),
    col("period"),
    col("race_group"),
    col("first_race"),
    col("last_race"),
    races.alias("races"),
    col("runners"),
    (col("_model_loss") / races).alias("log_loss_model"),
    (col("_market_loss") / races).alias("log_loss_market"),
    (col("_top_picks_won") / races).alias("top_pick_won_model"),
    (col("_favourites_won") / races).alias("top_pick_won_market"),
    coalesce(bets, lit(0)).alias("bets"),
    coalesce(col("bets_won"), lit(0)).alias("bets_won"),
    col("expected_wins_market"),
    col("expected_wins_model"),
    wins_z.alias("wins_z"),
    col("profit_units"),
    roi.alias("roi"),
    (roi - roi_margin).alias("roi_low"),
    (roi + roi_margin).alias("roi_high"),
    col("top_pick_profit_model"),
    top_pick_roi_model.alias("top_pick_roi_model"),
    col("top_pick_profit_market"),
    top_pick_roi_market.alias("top_pick_roi_market"),
  ]


def model_scorecard(graded: DataFrame) -> DataFrame:
  """One row per view, period and race group. Takes graded_view_rows()."""
  df = with_breakdowns(with_top_pick_stakes(graded))
  df = df.groupBy("view", "period_type", "period", "race_group").agg(*select_scorecard_aggregates())
  return df.select(select_scorecard_columns())


# --- model_calibration ------------------------------------------------------


def probability_band(prob: Column) -> Column:
  """Which CALIBRATION_BANDS band a probability is in: 1 = '0%-5%', 2 = '5%-10%'..."""
  last_band = len(CALIBRATION_BANDS) - 1
  band = when(prob.isNull(), lit(None))
  for number, high in enumerate(CALIBRATION_BANDS[1:-1], start=1):
    band = band.when(prob < lit(high), lit(number))
  return band.otherwise(lit(last_band))


def band_label(band: Column) -> Column:
  """1 -> '0%-5%', 2 -> '5%-10%'..."""
  label = when(band.isNull(), lit(None))
  for number, (low, high) in enumerate(zip(CALIBRATION_BANDS[:-1], CALIBRATION_BANDS[1:]), start=1):
    label = label.when(band == lit(number), lit(f"{low:.0%}-{high:.0%}"))
  return label.otherwise(lit(None))


def model_calibration(graded: DataFrame) -> DataFrame:
  """All time, per view: runners grouped by the probability we gave them, and
  by the probability the view's market gave them, with how often they won."""
  sources = array(
    struct(lit("model").alias("source"), col("model_prob").alias("prob")),
    struct(lit("market").alias("source"), col("market_prob").alias("prob")),
  )
  df = graded.withColumn("_source", explode(sources))
  df = df.select("view", "won", col("_source.source").alias("source"), col("_source.prob").alias("prob"))
  df = df.withColumn("band", probability_band(col("prob")))
  df = df.groupBy("view", "source", "band").agg(
    count(lit(1)).alias("runners"),
    avg("prob").alias("predicted"),
    avg(col("won").cast("double")).alias("actual"),
  )
  return df.withColumn("band_label", band_label(col("band")))
