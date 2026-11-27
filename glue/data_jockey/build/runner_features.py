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
Form is also kept per code (flat vs jumps, `conversions.race_code`): a jumper's
placings over hurdles say little about its chances on the flat.

Recent form of jockeys and trainers: win rates over the last 14 and 30 days,
shrunk towards their own long-run rate, so a quiet fortnight for a busy jockey
reads as "below their normal", not as a bad jockey.

Draw bias (flat only): for each course, surface and distance band, how much a
higher stall has gone with a worse finish in earlier races there (a slope,
shrunk towards no bias when there have been few races), times where this
runner is drawn. Draws are published with the race-morning declarations, so
earlier snapshots mostly have none (neutral 0).

Insights are the source's own flags (first-time headgear, wind surgery, hot
jockey/trainer...). They arrive with the race-morning file: t-1 and earlier
have none, so the flags are FALSE there.

Model inputs are never NULL: a gap (debut, unrated, no jockey booked yet at
t-3) gets a neutral value plus a flag column saying so.
"""

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql.functions import array_contains, avg, coalesce, col, count, datediff, exists, last, least, lit, when
from pyspark.sql.functions import row_number, transform
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
# Recent form: shrunk towards the jockey's/trainer's long-run rate with this
# many rides of prior, over these windows (days before the race day).
RECENT_PRIOR_RIDES = 10
RECENT_WINDOWS = [14, 30]
# Draw bias: shrunk towards no bias with this many earlier races of prior.
DRAW_PRIOR_RACES = 20
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
    ride.draw_number.cast("int").alias("draw"),
    transform(ride.insights, lambda insight: insight.type).alias("insight_types"),
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
    "has_handicap",
    "course_id",
    "surface",
    col("going_shortcode").alias("card_going_shortcode"),
  )
  df = df.join(race_info, "race_id")
  df = df.where(col("country_code").isin(conv.UK_IRE_COUNTRY_CODES))
  df = df.withColumn("race_code", conv.race_code(col("race_type")))
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
    conv.race_code(col("run_type")).alias("race_code"),
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
  recent_code_runs = (
    Window.partitionBy("horse_id", "race_code")
    .orderBy("race_date")
    .rowsBetween(-(RECENT_RUNS - 1), Window.currentRow)
  )
  return (
    df.withColumn("recent_form", avg("form_score").over(recent_runs))
    .withColumn("code_recent_form", avg("form_score").over(recent_code_runs))
  )


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


def draw_history(runners: DataFrame, races: DataFrame) -> DataFrame:
  """Each drawn runner in a complete UK/IRE flat race: where it was drawn
  (draw_x: -0.5 = lowest stall, +0.5 = highest) and how it finished (form
  score, 0 = won, 1 = last or didn't finish), with the sums a least-squares
  slope of form on draw needs. One row per race also carries race_start = 1."""
  is_uk_ire = col("country_code").isin(conv.UK_IRE_COUNTRY_CODES)
  is_complete = col("result_status") == "complete"
  is_flat = col("race_type") == "FLAT"
  flat_races = races.where(is_uk_ire & is_complete & is_flat).select(
    "race_id",
    "course_id",
    "surface",
    conv.distance_band(col("distance_yards")).alias("distance_band"),
  )

  is_drawn_runner = (col("snapshot") == "past") & (col("status") == "RUNNER") & col("draw").isNotNull()
  has_keys = col("course_id").isNotNull() & col("surface").isNotNull() & col("distance_band").isNotNull()
  df = runners.where(is_drawn_runner).join(flat_races.where(has_keys), "race_id")

  race = Window.partitionBy("race_id")
  field = count(lit(1)).over(race)
  highest_draw = spark_max("draw").over(race)
  draw_x = (col("draw") - 1) / (highest_draw - 1) - lit(0.5)
  did_not_finish = col("finish_position").isNull() & col("non_finisher_reason").isNotNull()
  has_placing = col("finish_position").isNotNull()
  share_beaten = least((col("finish_position") - 1) / (field - 1), lit(1.0))
  form_score = (
    when(did_not_finish, lit(1.0))
    .when(has_placing, share_beaten)
    .otherwise(lit(None))
  )
  first_in_race = row_number().over(race.orderBy("ride_id")) == 1

  df = (
    df.withColumn("_field", field)
    .withColumn("_highest_draw", highest_draw)
    .withColumn("draw_x", draw_x)
    .withColumn("form_score", form_score)
    .withColumn("race_start", first_in_race.cast("int"))
  )
  # A race needs two drawn runners for "high vs low" to mean anything.
  df = df.where((col("_field") > 1) & (col("_highest_draw") > 1) & col("form_score").isNotNull())
  return df.select(
    "course_id",
    "surface",
    "distance_band",
    "race_date",
    "race_start",
    lit(1).alias("run"),
    col("draw_x").alias("x"),
    col("form_score").alias("y"),
    (col("draw_x") * col("form_score")).alias("xy"),
    (col("draw_x") * col("draw_x")).alias("xx"),
  )


def draw_bias(history: DataFrame, rides: DataFrame) -> DataFrame:
  """Per (course, surface, distance band) and race day: the earlier races and
  the least-squares slope of form score on draw, before shrinking."""
  sums = as_of(
    history,
    rides,
    DRAW_KEYS,
    {
      "draw_races": spark_sum("race_start"),
      "_n": spark_sum("run"),
      "_sx": spark_sum("x"),
      "_sy": spark_sum("y"),
      "_sxy": spark_sum("xy"),
      "_sxx": spark_sum("xx"),
    },
  )
  covariance = col("_n") * col("_sxy") - col("_sx") * col("_sy")
  spread = col("_n") * col("_sxx") - col("_sx") * col("_sx")
  slope = (
    when(spread > 0, covariance / spread)
    .otherwise(lit(None))
  )
  return sums.select(*DRAW_KEYS, "race_date", "draw_races", slope.alias("draw_slope"))


DRAW_KEYS = ["course_id", "surface", "distance_band"]


def recent_rides(rider_runs: DataFrame, rides: DataFrame, key: str, prefix: str, days: int) -> DataFrame:
  """<prefix>_rides_<days>d and <prefix>_wins_<days>d in the `days` days before each race day."""
  history = rider_runs.where(col(key).isNotNull())
  aggregates = {
    f"{prefix}_rides_{days}d": spark_sum("run"),
    f"{prefix}_wins_{days}d": spark_sum("is_win"),
  }
  return as_of(history, rides, [key], aggregates, days=days)


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
  # A field average over two or three rated runners swings with each one.
  field_rated = count("official_rating").over(field)
  field_rating = avg("official_rating").over(field)
  field_weight = avg("weight_lbs").over(field)
  is_unrated = col("official_rating").isNull()
  rating_diff = coalesce(col("official_rating") - field_rating, lit(0.0))
  weight_diff = coalesce(col("weight_lbs") - field_weight, lit(0.0))
  rating_change = coalesce(col("official_rating") - col("last_type_rating"), lit(0))

  # In a handicap the weights are set to cancel out the rating gap, so the
  # model needs to know which races are handicaps.
  has_handicap = coalesce(col("has_handicap"), lit(False))

  def zero_if_null(name: str) -> Column:
    return coalesce(col(name), lit(0))

  horse_runs = zero_if_null("horse_runs")
  horse_wins = zero_if_null("horse_wins")
  horse_win_rate = shrunk_win_rate(horse_wins, horse_runs, HORSE_PRIOR_RUNS)
  is_debut = horse_runs == 0
  days_since_run = coalesce(datediff(col("race_date"), col("last_run_date")), lit(0))
  last_form = coalesce(col("last_form"), lit(NEUTRAL_FORM))
  recent_form = coalesce(col("recent_form"), lit(NEUTRAL_FORM))
  code_last_form = coalesce(col("code_last_form"), lit(NEUTRAL_FORM))
  code_recent_form = coalesce(col("code_recent_form"), lit(NEUTRAL_FORM))
  # Last run in the other code (flat vs jumps); FALSE on debut.
  switched_code = coalesce(col("last_code") != col("race_code"), lit(False))

  has_jockey = col("jockey_id").isNotNull()
  jockey_rides = zero_if_null("jockey_runs")
  jockey_win_rate = shrunk_win_rate(zero_if_null("jockey_wins"), jockey_rides, JOCKEY_PRIOR_RIDES)
  trainer_runs = zero_if_null("trainer_runs")
  trainer_win_rate = shrunk_win_rate(zero_if_null("trainer_wins"), trainer_runs, TRAINER_PRIOR_RUNS)

  def recent_rate(prefix: str, days: int, long_run_rate: Column) -> Column:
    """Shrunk towards the long-run rate, so no recent rides = the usual rate."""
    rides = zero_if_null(f"{prefix}_rides_{days}d")
    wins = zero_if_null(f"{prefix}_wins_{days}d")
    prior = lit(float(RECENT_PRIOR_RIDES))
    return (wins + long_run_rate * prior) / (rides + prior)

  recent_columns = []
  for prefix, long_run_rate in [("jockey", jockey_win_rate), ("trainer", trainer_win_rate)]:
    for days in RECENT_WINDOWS:
      recent_columns.append(zero_if_null(f"{prefix}_rides_{days}d").alias(f"{prefix}_rides_{days}d"))
      recent_columns.append(recent_rate(prefix, days, long_run_rate).alias(f"{prefix}_win_rate_{days}d"))

  # Draw: where this runner is drawn in this snapshot's field (-0.5 lowest
  # stall, +0.5 highest; 0 if no draw or not a flat race), and the course's
  # bias (change in form score from lowest to highest stall), shrunk.
  highest_draw = spark_max("draw").over(field)
  is_flat = col("race_type") == "FLAT"
  has_draw = is_flat & col("draw").isNotNull() & (highest_draw > 1)
  draw_position = (
    when(has_draw, (col("draw") - 1) / (highest_draw - 1) - lit(0.5))
    .otherwise(lit(0.0))
  )
  draw_races = zero_if_null("draw_races")
  shrink = draw_races / (draw_races + lit(float(DRAW_PRIOR_RACES)))
  course_draw_bias = (
    when(is_flat & col("draw_slope").isNotNull(), col("draw_slope") * shrink)
    .otherwise(lit(0.0))
  )

  insights = col("insight_types")

  def has_insight(insight_type: str) -> Column:
    return coalesce(array_contains(insights, insight_type), lit(False))

  first_time_headgear = coalesce(exists(insights, lambda insight: insight.startswith("FIRST_TIME_")), lit(False))

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
    has_handicap.alias("has_handicap"),
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
    field_rated.alias("field_rated"),
    zero_if_null("code_runs").alias("code_runs"),
    code_last_form.alias("code_last_form"),
    code_recent_form.alias("code_recent_form"),
    switched_code.alias("switched_code"),
    *recent_columns,
    has_draw.alias("has_draw"),
    draw_position.alias("draw_position"),
    draw_races.alias("draw_races"),
    course_draw_bias.alias("draw_bias"),
    first_time_headgear.alias("first_time_headgear"),
    has_insight("WIND_SURGERY_SINCE_LAST_RUN").alias("wind_surgery"),
    has_insight("AHEAD_OF_THE_HANDICAPPER").alias("ahead_of_handicapper"),
    has_insight("HOT_JOCKEY").alias("hot_jockey"),
    has_insight("HOT_TRAINER").alias("hot_trainer"),
    has_insight("TRAVELLERS_CHECK").alias("travellers_check"),
  ]


def runner_features(all_race_files: DataFrame, races: DataFrame, runners: DataFrame) -> DataFrame:
  """Takes every raw race file (all snapshots) plus the built races and runners tables."""
  df = targets(all_race_files, races)
  horse_runs = horse_history(all_race_files)
  rider_runs = ride_history(runners, races)
  drawn_runs = draw_history(runners, races)

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
      "last_code": last("race_code", ignorenulls=True),
    },
  )
  race_code = as_of(
    horse_runs.where(col("race_code").isNotNull()),
    df,
    ["horse_id", "race_code"],
    {
      "code_runs": spark_sum("run"),
      "code_last_form": last("form_score", ignorenulls=True),
      "code_recent_form": last("code_recent_form", ignorenulls=True),
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
    (race_code, ["horse_id", "race_code"]),
    (runs_and_wins(horse_runs, df, ["horse_id", "course_shortcode"], "course"), ["horse_id", "course_shortcode"]),
    (runs_and_wins(horse_runs, df, ["horse_id", "distance_band"], "distance"), ["horse_id", "distance_band"]),
    (runs_and_wins(horse_runs, df, ["horse_id", "going_group"], "going"), ["horse_id", "going_group"]),
    (runs_and_wins(rider_runs, df, ["jockey_id"], "jockey"), ["jockey_id"]),
    (runs_and_wins(rider_runs, df, ["trainer_id"], "trainer"), ["trainer_id"]),
    (draw_bias(drawn_runs, df), DRAW_KEYS),
  ]
  for key, prefix in [("jockey_id", "jockey"), ("trainer_id", "trainer")]:
    for days in RECENT_WINDOWS:
      history.append((recent_rides(rider_runs, df, key, prefix, days), [key]))
  for aggregates, keys in history:
    df = df.join(aggregates, [*keys, "race_date"], "left")

  return df.select(select_runner_feature_columns())
