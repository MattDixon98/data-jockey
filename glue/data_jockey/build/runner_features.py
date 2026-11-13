"""Point-in-time model features: one row per declared runner per snapshot.

Every feature for a race on date D comes only from races before D (`as_of`),
so the past snapshot's rows (the model's training data) see exactly what a
t-1 crawl of the same race would have seen. The source's own lifetime counts,
form figures and last_ran_days are not used: in a past file they already
include the race itself.

UK/IRE races only, and only rides that are RUNNERs at that snapshot (the
field the odds are shared across). Built from every snapshot's file, like
odds_snapshots: entries come and go between t-3 and the off, and the field
features follow them.

Horse history is horse_form rebuilt from every snapshot's file (the
horse_form table only reads each race's most trusted file), so an entry that
drops out before t-1 still has its form at t-3. Horses hold separate flat,
hurdle and chase ratings, so ratings are only compared within a race type.

Model inputs are never NULL: a gap (debut, unrated, no jockey booked yet at
t-3) gets a neutral value plus a flag column saying so.
"""

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql.functions import avg, coalesce, col, count, datediff, last, least, lit, when
from pyspark.sql.functions import max as spark_max
from pyspark.sql.functions import sum as spark_sum

from data_jockey import conversions as conv
from data_jockey.build.horse_form import horse_form
from data_jockey.build.utilities import as_of, from_past, latest, rides, with_snapshot

# Shrinkage: a win rate is (wins + PRIOR_WIN_RATE * n) / (runs + n), so a small
# sample stays close to the average (about one winner per ten runners) and
# no history at all gives exactly the average.
PRIOR_WIN_RATE = 0.1
HORSE_PRIOR_RUNS = 3
JOCKEY_PRIOR_RIDES = 20
TRAINER_PRIOR_RUNS = 20
# Form score for a horse with no form: halfway between winning (0) and last (1).
NEUTRAL_FORM = 0.5
RECENT_RUNS = 3


def shrunk_win_rate(wins: Column, runs: Column, prior_runs: int) -> Column:
  prior_wins = lit(PRIOR_WIN_RATE * prior_runs)
  return (wins + prior_wins) / (runs + lit(prior_runs))


# --- The runners being scored ------------------------------------------------


def select_target_columns() -> list[Column]:
  ride = col("ride")
  position = conv.official_position(ride.finish_position, ride.amended_position)
  finish_position = conv.finish_position(ride.ride_status, position)
  distance_yards = conv.distance_yards(col("race_distance"))

  return [
    ride.ride_reference.id.alias("ride_id"),
    col("snapshot"),
    conv.snapshot_rank(col("snapshot")).alias("snapshot_rank"),
    col("race_id"),
    col("race_date"),
    ride.horse.horse_reference.id.alias("horse_id"),
    ride.jockey.person_reference.id.alias("jockey_id"),
    ride.trainer.business_reference.id.alias("trainer_id"),
    ride.ride_status.alias("status"),
    conv.empty_to_null(col("course_shortcode")).alias("course_shortcode"),
    conv.distance_band(distance_yards).alias("distance_band"),
    col("snapshot_going_shortcode"),
    ride.official_rating.cast("int").alias("official_rating"),
    conv.weight_lbs(ride.handicap).alias("weight_lbs"),
    from_past(finish_position).alias("finish_position"),
  ]


def targets(all_race_files: DataFrame, races: DataFrame) -> DataFrame:
  """Every UK/IRE runner at every snapshot, with its race's type and going."""
  race_columns = [
    col("race_summary.course_shortcode").alias("course_shortcode"),
    col("race_summary.distance").alias("race_distance"),
    col("race_summary.going_shortcode").alias("snapshot_going_shortcode"),
  ]
  df = rides(with_snapshot(all_race_files), *race_columns).select(select_target_columns())
  df = df.where(col("status") == "RUNNER")
  df = latest(df, ["ride_id", "snapshot"], [col("race_date").desc()])

  # Country and race type from the races table; going from the snapshot's own
  # file when it has one (future files usually don't), else the racecard's.
  race_info = races.select(
    "race_id",
    "country_code",
    "race_type",
    col("going_shortcode").alias("card_going_shortcode"),
  )
  df = df.join(race_info, "race_id")
  df = df.where(col("country_code").isin(conv.UK_IRE_COUNTRY_CODES))
  going_shortcode = coalesce(conv.empty_to_null(col("snapshot_going_shortcode")), col("card_going_shortcode"))
  return df.withColumn("going_group", conv.going_group(going_shortcode))


# --- History -----------------------------------------------------------------


def horse_history(all_race_files: DataFrame) -> DataFrame:
  """Each known run of each horse, from every snapshot's previous_results, with a form score: 0 = won, 1 = last or didn't finish, scaled by field size in between."""
  position = col("finish_position")
  runner_count = col("runner_count")
  did_not_finish = position.isNull() & col("non_finisher_reason").isNotNull()
  has_placing = position.isNotNull() & (runner_count > 1)
  share_beaten = least((position - 1) / (runner_count - 1), lit(1.0))
  form_score = (
    when(did_not_finish, lit(1.0))
    .when(has_placing, share_beaten)
    .otherwise(lit(None))
  )
  is_win = coalesce((position == 1).cast("int"), lit(0))
  is_place = coalesce((position <= 3).cast("int"), lit(0))

  form = horse_form(with_snapshot(all_race_files))
  df = form.where(col("race_date").isNotNull()).select(
    "horse_id",
    "race_date",
    col("race_date").alias("run_date"),
    col("run_type").alias("race_type"),
    "course_shortcode",
    conv.distance_band(col("distance_yards")).alias("distance_band"),
    conv.going_group(col("going_shortcode")).alias("going_group"),
    col("official_rating").alias("run_rating"),
    lit(1).alias("run"),
    is_win.alias("is_win"),
    is_place.alias("is_place"),
    form_score.alias("form_score"),
  )

  recent_runs = (
    Window.partitionBy("horse_id")
    .orderBy("race_date")
    .rowsBetween(-(RECENT_RUNS - 1), Window.currentRow)
  )
  return df.withColumn("recent_form", avg("form_score").over(recent_runs))


def ride_history(runners: DataFrame, races: DataFrame) -> DataFrame:
  """Every ride in a complete UK/IRE race, for jockey and trainer win rates."""
  is_uk_ire = col("country_code").isin(conv.UK_IRE_COUNTRY_CODES)
  is_complete = col("result_status") == "complete"
  complete_races = races.where(is_uk_ire & is_complete).select("race_id")

  is_past_runner = (col("snapshot") == "past") & (col("status") == "RUNNER")
  is_win = coalesce((col("finish_position") == 1).cast("int"), lit(0))
  return runners.where(is_past_runner).join(complete_races, "race_id").select(
    "jockey_id",
    "trainer_id",
    "race_date",
    lit(1).alias("run"),
    is_win.alias("is_win"),
  )


def runs_and_wins(history: DataFrame, rides: DataFrame, keys: list[str], prefix: str) -> DataFrame:
  """<prefix>_runs and <prefix>_wins before each race day, per key."""
  has_keys = [col(key).isNotNull() for key in keys]
  for has_key in has_keys:
    history = history.where(has_key)
  aggregates = {
    f"{prefix}_runs": spark_sum("run"),
    f"{prefix}_wins": spark_sum("is_win"),
  }
  return as_of(history, rides, keys, aggregates)


# --- The table ---------------------------------------------------------------


def select_runner_feature_columns() -> list[Column]:
  field = Window.partitionBy("race_id", "snapshot")
  field_size = count(lit(1)).over(field)
  field_rating = avg("official_rating").over(field)
  field_weight = avg("weight_lbs").over(field)
  is_unrated = col("official_rating").isNull()
  rating_diff = coalesce(col("official_rating") - field_rating, lit(0.0))
  weight_diff = coalesce(col("weight_lbs") - field_weight, lit(0.0))
  rating_change = coalesce(col("official_rating") - col("last_type_rating"), lit(0))

  def zero_if_null(name: str) -> Column:
    return coalesce(col(name), lit(0))

  horse_runs = zero_if_null("horse_runs")
  horse_wins = zero_if_null("horse_wins")
  horse_win_rate = shrunk_win_rate(horse_wins, horse_runs, HORSE_PRIOR_RUNS)
  is_debut = horse_runs == 0
  days_since_run = coalesce(datediff(col("race_date"), col("last_run_date")), lit(0))
  last_form = coalesce(col("last_form"), lit(NEUTRAL_FORM))
  recent_form = coalesce(col("recent_form"), lit(NEUTRAL_FORM))

  has_jockey = col("jockey_id").isNotNull()
  jockey_rides = zero_if_null("jockey_runs")
  jockey_win_rate = shrunk_win_rate(zero_if_null("jockey_wins"), jockey_rides, JOCKEY_PRIOR_RIDES)
  trainer_runs = zero_if_null("trainer_runs")
  trainer_win_rate = shrunk_win_rate(zero_if_null("trainer_wins"), trainer_runs, TRAINER_PRIOR_RUNS)

  return [
    col("ride_id"),
    col("snapshot"),
    col("snapshot_rank"),
    col("race_id"),
    col("race_date"),
    col("horse_id"),
    col("jockey_id"),
    col("trainer_id"),
    col("race_type"),
    col("distance_band"),
    col("going_group"),
    field_size.alias("field_size"),
    col("official_rating"),
    rating_diff.alias("rating_diff"),
    is_unrated.alias("is_unrated"),
    rating_change.alias("rating_change"),
    col("weight_lbs"),
    weight_diff.alias("weight_diff"),
    horse_runs.alias("horse_runs"),
    horse_wins.alias("horse_wins"),
    zero_if_null("horse_places").alias("horse_places"),
    horse_win_rate.alias("horse_win_rate"),
    is_debut.alias("is_debut"),
    days_since_run.alias("days_since_run"),
    last_form.alias("last_form"),
    recent_form.alias("recent_form"),
    zero_if_null("type_runs").alias("type_runs"),
    zero_if_null("type_wins").alias("type_wins"),
    zero_if_null("course_runs").alias("course_runs"),
    zero_if_null("course_wins").alias("course_wins"),
    zero_if_null("distance_runs").alias("distance_runs"),
    zero_if_null("distance_wins").alias("distance_wins"),
    zero_if_null("going_runs").alias("going_runs"),
    zero_if_null("going_wins").alias("going_wins"),
    has_jockey.alias("has_jockey"),
    jockey_rides.alias("jockey_rides"),
    jockey_win_rate.alias("jockey_win_rate"),
    trainer_runs.alias("trainer_runs"),
    trainer_win_rate.alias("trainer_win_rate"),
    col("finish_position"),
  ]


def runner_features(all_race_files: DataFrame, races: DataFrame, runners: DataFrame) -> DataFrame:
  """Takes every raw race file (all snapshots) plus the built races and runners tables."""
  df = targets(all_race_files, races)
  horse_runs = horse_history(all_race_files)
  rider_runs = ride_history(runners, races)

  horse = as_of(
    horse_runs,
    df,
    ["horse_id"],
    {
      "horse_runs": spark_sum("run"),
      "horse_wins": spark_sum("is_win"),
      "horse_places": spark_sum("is_place"),
      "last_run_date": spark_max("run_date"),
      "last_form": last("form_score", ignorenulls=True),
      "recent_form": last("recent_form", ignorenulls=True),
    },
  )
  race_type = as_of(
    horse_runs.where(col("race_type").isNotNull()),
    df,
    ["horse_id", "race_type"],
    {
      "type_runs": spark_sum("run"),
      "type_wins": spark_sum("is_win"),
      "last_type_rating": last("run_rating", ignorenulls=True),
    },
  )
  history = [
    (horse, ["horse_id"]),
    (race_type, ["horse_id", "race_type"]),
    (runs_and_wins(horse_runs, df, ["horse_id", "course_shortcode"], "course"), ["horse_id", "course_shortcode"]),
    (runs_and_wins(horse_runs, df, ["horse_id", "distance_band"], "distance"), ["horse_id", "distance_band"]),
    (runs_and_wins(horse_runs, df, ["horse_id", "going_group"], "going"), ["horse_id", "going_group"]),
    (runs_and_wins(rider_runs, df, ["jockey_id"], "jockey"), ["jockey_id"]),
    (runs_and_wins(rider_runs, df, ["trainer_id"], "trainer"), ["trainer_id"]),
  ]
  for aggregates, keys in history:
    df = df.join(aggregates, [*keys, "race_date"], "left")

  return df.select(select_runner_feature_columns())
