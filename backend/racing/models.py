"""Read-only models over the serving snapshot (see racing/__init__.py).

One model per snapshot table; the column docs live with the DDL in
glue/data_jockey/tables.py. Foreign keys have no database constraints
(db_constraint=False) and are only used where the target row is always in the
snapshot. Rows that can refer to entries dropped before race day (odds
snapshots, model rows at t-3/t-2) keep plain ride_id/horse_id columns instead,
because those rides and horses aren't in runners/horses.

help_text is what the APIs show as each field's description (GraphQL via
STRAWBERRY_DJANGO's FIELD_DESCRIPTION_FROM_HELP_TEXT, DRF by default), so a
column is described once, here.
"""

from django.db import models


def _fk(to, column, related_name, null=False):
  return models.ForeignKey(
    to,
    on_delete=models.DO_NOTHING,
    db_column=column,
    db_constraint=False,
    related_name=related_name,
    null=null,
  )


class SnapshotModel(models.Model):
  class Meta:
    abstract = True
    managed = False


class SnapshotInfo(SnapshotModel):
  """One row: when the snapshot was built."""
  built_at = models.DateTimeField(primary_key=True)
  format_version = models.IntegerField()

  class Meta(SnapshotModel.Meta):
    db_table = "snapshot_info"


class Course(SnapshotModel):
  course_id = models.BigIntegerField(primary_key=True)
  name = models.TextField(null=True)
  shortcode = models.TextField(null=True)
  country_code = models.TextField(null=True, help_text="ENG, Scot, Wale, Nort or Eire.")
  country_name = models.TextField(null=True)
  feed_source = models.TextField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "courses"


class Meeting(SnapshotModel):
  meeting_id = models.BigIntegerField(primary_key=True)
  meeting_date = models.DateField(null=True)
  course = _fk(Course, "course_id", "meetings", null=True)
  going = models.TextField(null=True)
  surface_summary = models.TextField(null=True)
  weather = models.TextField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "meetings"


class Race(SnapshotModel):
  race_id = models.BigIntegerField(primary_key=True)
  meeting = _fk(Meeting, "meeting_id", "races", null=True)
  course = _fk(Course, "course_id", "races", null=True)
  country_code = models.TextField(null=True, help_text="ENG, Scot, Wale, Nort or Eire.")
  race_date = models.DateField(null=True)
  race_time = models.TextField(null=True, help_text="Scheduled time, UK local (HH:MM).")
  off_time = models.TextField(null=True)
  name = models.TextField(null=True)
  race_class = models.IntegerField(null=True)
  age_band = models.TextField(null=True)
  surface = models.TextField(null=True)
  distance = models.TextField(null=True)
  distance_yards = models.IntegerField(null=True)
  going = models.TextField(null=True)
  going_shortcode = models.TextField(null=True)
  has_handicap = models.BooleanField(null=True)
  race_stage = models.TextField(null=True)
  result_status = models.TextField(null=True, help_text="Only complete races have trustworthy positions.")
  ride_count = models.IntegerField(null=True)
  placed_count = models.IntegerField(null=True)
  winning_time = models.TextField(null=True)
  winning_time_seconds = models.FloatField(null=True)
  book_percentage = models.FloatField(null=True)
  betting_forecast = models.TextField(null=True)
  verdict = models.TextField(null=True)
  snapshot = models.TextField(null=True, help_text="Which crawl the race's details come from: its latest.")
  race_type = models.TextField(null=True, help_text="FLAT, HURDLE, CHASE or N_H_FLAT.")

  class Meta(SnapshotModel.Meta):
    db_table = "races"


class Horse(SnapshotModel):
  horse_id = models.BigIntegerField(primary_key=True)
  name = models.TextField(null=True)
  slug = models.TextField(null=True)
  sex = models.TextField(null=True)
  foaled = models.DateField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "horses"


class Jockey(SnapshotModel):
  jockey_id = models.BigIntegerField(primary_key=True)
  name = models.TextField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "jockeys"


class Trainer(SnapshotModel):
  trainer_id = models.BigIntegerField(primary_key=True)
  name = models.TextField(null=True)
  slug = models.TextField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "trainers"


class Runner(SnapshotModel):
  ride_id = models.BigIntegerField(primary_key=True)
  race = _fk(Race, "race_id", "runners")
  race_date = models.DateField(null=True)
  horse = _fk(Horse, "horse_id", "runners")
  jockey = _fk(Jockey, "jockey_id", "rides", null=True)
  trainer = _fk(Trainer, "trainer_id", "runners", null=True)
  owner_name = models.TextField(null=True)
  cloth_number = models.IntegerField(null=True)
  draw = models.IntegerField(null=True)
  status = models.TextField(null=True)
  finish_position = models.IntegerField(
    null=True,
    help_text="Only set once the race is in past (amended result if there was one).",
  )
  non_finisher_reason = models.TextField(null=True)
  horse_age = models.IntegerField(null=True)
  weight = models.TextField(null=True)
  weight_lbs = models.IntegerField(null=True)
  official_rating = models.IntegerField(null=True)
  odds = models.TextField(null=True, help_text="The latest price: forecast before the race, SP after it.")
  odds_decimal = models.FloatField(null=True)
  favourite = models.TextField(null=True)
  headgear = models.TextField(null=True)
  days_since_last_run = models.IntegerField(null=True)
  lifetime_runs = models.IntegerField(null=True)
  lifetime_wins = models.IntegerField(null=True)
  lifetime_places = models.IntegerField(null=True)
  insights = models.JSONField(null=True)
  snapshot = models.TextField(null=True, help_text="Which crawl the ride's details come from: its race's latest.")

  class Meta(SnapshotModel.Meta):
    db_table = "runners"


class Prize(SnapshotModel):
  pk = models.CompositePrimaryKey("race_id", "position")
  race = _fk(Race, "race_id", "prizes")
  position = models.IntegerField()
  amount = models.DecimalField(max_digits=12, decimal_places=2, null=True)
  currency = models.TextField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "prizes"


class HorseForm(SnapshotModel):
  """A horse's previous runs. race_id is plain: many of these races were never crawled."""
  pk = models.CompositePrimaryKey("horse_id", "race_id")
  horse = _fk(Horse, "horse_id", "form")
  race_id = models.BigIntegerField(help_text="The source's race id; many of these races were never crawled.")
  race_date = models.DateField(null=True)
  race_time = models.TextField(null=True)
  course_name = models.TextField(null=True)
  course_shortcode = models.TextField(null=True)
  race_name = models.TextField(null=True)
  race_class = models.IntegerField(null=True)
  run_type = models.TextField(null=True)
  distance = models.TextField(null=True)
  distance_yards = models.IntegerField(null=True)
  going = models.TextField(null=True)
  going_shortcode = models.TextField(null=True)
  runner_count = models.IntegerField(null=True)
  finish_position = models.IntegerField(null=True)
  non_finisher_reason = models.TextField(null=True)
  weight = models.TextField(null=True)
  weight_lbs = models.IntegerField(null=True)
  official_rating = models.IntegerField(null=True)
  odds = models.TextField(null=True)
  odds_decimal = models.FloatField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "horse_form"


class OddsSnapshot(SnapshotModel):
  """A runner's price at each crawl that had one. Reverse-only `ride`: see the module docstring."""
  pk = models.CompositePrimaryKey("ride_id", "snapshot")
  ride = _fk(Runner, "ride_id", "odds_snapshots")
  race = _fk(Race, "race_id", "odds_snapshots")
  race_date = models.DateField(null=True)
  horse_id = models.BigIntegerField(null=True)
  snapshot = models.TextField()
  snapshot_rank = models.IntegerField(null=True)
  status = models.TextField(null=True)
  odds = models.TextField(null=True)
  odds_decimal = models.FloatField(null=True)
  favourite = models.TextField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "odds_snapshots"


class OddsHistory(SnapshotModel):
  """On-course prices from past files, so the ride is always in runners."""
  pk = models.CompositePrimaryKey("ride_id", "seq")
  ride = _fk(Runner, "ride_id", "odds_history")
  race = _fk(Race, "race_id", "odds_history")
  race_date = models.DateField(null=True)
  horse_id = models.BigIntegerField(null=True)
  seq = models.IntegerField(help_text="1 = the opening show.")
  odds = models.TextField(null=True)
  odds_decimal = models.FloatField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "odds_history"


class ModelOdds(SnapshotModel):
  """Our win odds per runner and snapshot. Reverse-only `ride`: see the module docstring."""
  pk = models.CompositePrimaryKey("ride_id", "snapshot")
  ride = _fk(Runner, "ride_id", "model_odds")
  snapshot = models.TextField()
  snapshot_rank = models.IntegerField(null=True)
  race = _fk(Race, "race_id", "model_odds")
  race_date = models.DateField(null=True)
  horse_id = models.BigIntegerField(null=True)
  model_version = models.TextField(null=True)
  in_sample = models.BooleanField(null=True, help_text="The model was trained on this race, so it isn't a fair test.")
  score = models.FloatField(null=True)
  model_prob = models.FloatField(null=True)
  model_odds_decimal = models.FloatField(null=True)
  model_odds = models.TextField(null=True)
  model_rank = models.IntegerField(null=True, help_text="1 = our favourite.")
  field_size = models.IntegerField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "model_odds"
    verbose_name_plural = "model odds"


class ModelValue(SnapshotModel):
  """Our probability next to the market's, with the undervalued flag. Reverse-only `ride`."""
  pk = models.CompositePrimaryKey("ride_id", "snapshot")
  ride = _fk(Runner, "ride_id", "model_value")
  snapshot = models.TextField()
  snapshot_rank = models.IntegerField(null=True)
  race = _fk(Race, "race_id", "model_value")
  race_date = models.DateField(null=True)
  horse_id = models.BigIntegerField(null=True)
  model_version = models.TextField(null=True)
  in_sample = models.BooleanField(null=True, help_text="The model was trained on this race, so it isn't a fair test.")
  model_prob = models.FloatField(null=True)
  model_odds = models.TextField(null=True)
  market = models.TextField(null=True, help_text="sp for past rows, forecast before the race.")
  market_odds = models.TextField(null=True)
  market_odds_decimal = models.FloatField(null=True)
  market_prob = models.FloatField(null=True)
  book_percentage = models.FloatField(null=True)
  edge = models.FloatField(null=True, help_text="model_prob / market_prob - 1.")
  expected_value = models.FloatField(
    null=True,
    help_text="Return per unit staked at the market price if our probability is right.",
  )
  undervalued = models.BooleanField(null=True)
  won = models.BooleanField(null=True)
  finish_position = models.IntegerField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "model_value"


class ModelScorecard(SnapshotModel):
  pk = models.CompositePrimaryKey("view", "period_type", "period", "race_group")
  view = models.TextField(help_text="after_race (vs SP) or site_pick (the race-morning flags).")
  period_type = models.TextField(help_text="all, month or model_version.")
  period = models.TextField()
  race_group = models.TextField(help_text="all, flat or jumps.")
  first_race = models.DateField(null=True)
  last_race = models.DateField(null=True)
  races = models.BigIntegerField(null=True)
  runners = models.BigIntegerField(null=True)
  log_loss_model = models.FloatField(null=True)
  log_loss_market = models.FloatField(null=True)
  top_pick_won_model = models.FloatField(null=True)
  top_pick_won_market = models.FloatField(null=True)
  bets = models.BigIntegerField(null=True)
  bets_won = models.BigIntegerField(null=True)
  expected_wins_market = models.FloatField(null=True)
  expected_wins_model = models.FloatField(null=True)
  wins_z = models.FloatField(null=True)
  profit_units = models.FloatField(null=True)
  roi = models.FloatField(null=True)
  roi_low = models.FloatField(null=True)
  roi_high = models.FloatField(null=True)
  top_pick_profit_model = models.FloatField(
    null=True,
    help_text="Profit of 1 unit per race on our favourite at SP (joint favourites split the unit).",
  )
  top_pick_roi_model = models.FloatField(null=True, help_text="top_pick_profit_model per unit staked.")
  top_pick_profit_market = models.FloatField(
    null=True,
    help_text="The same on the market favourite (SP, or the forecast for site_pick).",
  )
  top_pick_roi_market = models.FloatField(null=True, help_text="top_pick_profit_market per unit staked.")

  class Meta(SnapshotModel.Meta):
    db_table = "model_scorecard"


class ModelCalibration(SnapshotModel):
  pk = models.CompositePrimaryKey("view", "source", "band")
  view = models.TextField(help_text="after_race (vs SP) or site_pick (the race-morning flags).")
  source = models.TextField(help_text="model or market.")
  band = models.IntegerField()
  band_label = models.TextField(null=True)
  runners = models.BigIntegerField(null=True)
  predicted = models.FloatField(null=True)
  actual = models.FloatField(null=True)

  class Meta(SnapshotModel.Meta):
    db_table = "model_calibration"
