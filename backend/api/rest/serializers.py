"""Response shapes, one serializer per racing model (plus slimmer "ref"
versions for nesting). Field descriptions come from the models' help_text
(shared with GraphQL). Snapshots are the raw values (t-3, t-2, t-1, today,
past), ids are the source's ids. Lists of related rows come prefetched and in
order from the views; these only shape them.
"""

from __future__ import annotations

from functools import cached_property

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api import queries
from racing import models

from .descriptions import column_help


class SnapshotInfoSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.SnapshotInfo
    fields = ["built_at", "format_version"]


class CourseSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.Course
    fields = ["course_id", "name", "shortcode", "country_code", "country_name"]


class CourseRefSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.Course
    fields = ["course_id", "name"]


class HorseSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.Horse
    fields = ["horse_id", "name", "slug", "sex", "foaled"]


class HorseRefSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.Horse
    fields = ["horse_id", "name"]


class JockeySerializer(serializers.ModelSerializer):
  class Meta:
    model = models.Jockey
    fields = ["jockey_id", "name"]


class TrainerSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.Trainer
    fields = ["trainer_id", "name", "slug"]


class PrizeSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.Prize
    fields = ["position", "amount", "currency"]


class HorseFormRunSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.HorseForm
    fields = [
      "race_id",
      "race_date",
      "race_time",
      "course_name",
      "course_shortcode",
      "race_name",
      "race_class",
      "run_type",
      "distance",
      "distance_yards",
      "going",
      "going_shortcode",
      "runner_count",
      "finish_position",
      "non_finisher_reason",
      "weight",
      "weight_lbs",
      "official_rating",
      "odds",
      "odds_decimal",
    ]


class HorseDetailSerializer(HorseSerializer):
  form = HorseFormRunSerializer(
    many=True,
    help_text="Previous runs as listed on its racecards (newest first), including ones before the crawl began and abroad.",
  )

  class Meta(HorseSerializer.Meta):
    fields = HorseSerializer.Meta.fields + ["form"]


class OddsSnapshotSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.OddsSnapshot
    fields = ["snapshot", "status", "odds", "odds_decimal", "favourite"]


class OddsMoveSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.OddsHistory
    fields = ["seq", "odds", "odds_decimal"]


class ModelOddsSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.ModelOdds
    fields = [
      "snapshot",
      "model_version",
      "in_sample",
      "model_prob",
      "model_odds_decimal",
      "model_odds",
      "model_rank",
      "field_size",
    ]


class ModelValueSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.ModelValue
    fields = [
      "snapshot",
      "model_version",
      "in_sample",
      "model_prob",
      "model_odds",
      "market",
      "market_odds",
      "market_odds_decimal",
      "market_prob",
      "book_percentage",
      "edge",
      "expected_value",
      "undervalued",
      "won",
      "finish_position",
    ]


RUNNER_FIELDS = [
  "ride_id",
  "race_date",
  "horse",
  "jockey",
  "trainer",
  "owner_name",
  "cloth_number",
  "draw",
  "status",
  "finish_position",
  "non_finisher_reason",
  "horse_age",
  "weight",
  "weight_lbs",
  "official_rating",
  "odds",
  "odds_decimal",
  "favourite",
  "headgear",
  "days_since_last_run",
  "lifetime_runs",
  "lifetime_wins",
  "lifetime_places",
  "insights",
  "snapshot",
  "model_odds",
  "model_value",
]


class RunnerSerializer(serializers.ModelSerializer):
  horse = HorseRefSerializer()
  jockey = JockeySerializer(allow_null=True)
  trainer = TrainerSerializer(allow_null=True)
  model_odds = serializers.SerializerMethodField()
  model_value = serializers.SerializerMethodField()

  class Meta:
    model = models.Runner
    fields = RUNNER_FIELDS

  # The nested serializers are built once and reused for every runner: building
  # a ModelSerializer's fields per row made a day's card ~3x slower.
  @cached_property
  def _model_odds(self):
    return ModelOddsSerializer()

  @cached_property
  def _model_value(self):
    return ModelValueSerializer()

  def _at_snapshot(self, rows, runner):
    return queries.at_snapshot(rows.all(), self.context.get("snapshot"), runner.snapshot)

  @extend_schema_field(ModelOddsSerializer(allow_null=True))
  def get_model_odds(self, runner):
    row = self._at_snapshot(runner.model_odds, runner)
    return self._model_odds.to_representation(row) if row else None

  @extend_schema_field(ModelValueSerializer(allow_null=True))
  def get_model_value(self, runner):
    row = self._at_snapshot(runner.model_value, runner)
    return self._model_value.to_representation(row) if row else None


class RaceRunnerSerializer(RunnerSerializer):
  odds_snapshots = serializers.SerializerMethodField()
  odds_history = OddsMoveSerializer(many=True, help_text="On-course price moves (past races only).")
  model_odds_snapshots = serializers.SerializerMethodField()

  class Meta(RunnerSerializer.Meta):
    fields = RUNNER_FIELDS + ["odds_snapshots", "odds_history", "model_odds_snapshots"]

  @cached_property
  def _odds_snapshot(self):
    return OddsSnapshotSerializer()

  @extend_schema_field(OddsSnapshotSerializer(many=True))
  def get_odds_snapshots(self, runner):
    rows = queries.oldest_first(runner.odds_snapshots.all())
    return [self._odds_snapshot.to_representation(row) for row in rows]

  @extend_schema_field(ModelOddsSerializer(many=True))
  def get_model_odds_snapshots(self, runner):
    rows = queries.oldest_first(runner.model_odds.all())
    return [self._model_odds.to_representation(row) for row in rows]


RACE_FIELDS = [
  "race_id",
  "meeting_id",
  "course",
  "country_code",
  "race_date",
  "race_time",
  "off_time",
  "name",
  "race_type",
  "race_class",
  "age_band",
  "surface",
  "distance",
  "distance_yards",
  "going",
  "going_shortcode",
  "has_handicap",
  "race_stage",
  "result_status",
  "ride_count",
  "placed_count",
  "winning_time",
  "winning_time_seconds",
  "book_percentage",
  "betting_forecast",
  "verdict",
  "snapshot",
]


class RaceSerializer(serializers.ModelSerializer):
  meeting_id = serializers.IntegerField(allow_null=True)
  course = CourseRefSerializer(allow_null=True)

  class Meta:
    model = models.Race
    fields = RACE_FIELDS


class RaceRefSerializer(serializers.ModelSerializer):
  """Enough of a race to list a ride under it."""
  course = CourseRefSerializer(allow_null=True)

  class Meta:
    model = models.Race
    fields = ["race_id", "race_date", "race_time", "name", "race_type", "course", "result_status", "snapshot"]


class RaceCardSerializer(RaceSerializer):
  runners = RunnerSerializer(many=True)

  class Meta(RaceSerializer.Meta):
    fields = RACE_FIELDS + ["runners"]


class RaceDetailSerializer(RaceSerializer):
  runners = RaceRunnerSerializer(many=True)
  prizes = PrizeSerializer(many=True)

  class Meta(RaceSerializer.Meta):
    fields = RACE_FIELDS + ["runners", "prizes"]


class MeetingSerializer(serializers.ModelSerializer):
  course = CourseRefSerializer(allow_null=True)
  races = RaceCardSerializer(many=True)

  class Meta:
    model = models.Meeting
    fields = ["meeting_id", "meeting_date", "course", "going", "surface_summary", "weather", "races"]


class RunnerWithRaceSerializer(RunnerSerializer):
  race = RaceRefSerializer()

  class Meta(RunnerSerializer.Meta):
    fields = ["race"] + RUNNER_FIELDS


class ScorecardRowSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.ModelScorecard
    fields = [
      "view",
      "period_type",
      "period",
      "race_group",
      "first_race",
      "last_race",
      "races",
      "runners",
      "log_loss_model",
      "log_loss_market",
      "top_pick_won_model",
      "top_pick_won_market",
      "bets",
      "bets_won",
      "expected_wins_market",
      "expected_wins_model",
      "wins_z",
      "profit_units",
      "roi",
      "roi_low",
      "roi_high",
      "top_pick_profit_model",
      "top_pick_roi_model",
      "top_pick_profit_market",
      "top_pick_roi_market",
    ]


class CalibrationBandSerializer(serializers.ModelSerializer):
  class Meta:
    model = models.ModelCalibration
    fields = ["view", "source", "band", "band_label", "runners", "predicted", "actual"]


# Query parameters (validated by the views, documented in the OpenAPI schema).

class SnapshotParams(serializers.Serializer):
  snapshot = serializers.ChoiceField(
    choices=queries.SNAPSHOTS,
    required=False,
    help_text="Which crawl's model odds/value to show. Defaults to each runner's own (its race's latest crawl).",
  )


class DateParams(SnapshotParams):
  date = serializers.DateField(help_text="Race day, YYYY-MM-DD.")


class NameSearchParams(serializers.Serializer):
  name = serializers.CharField(help_text=f"Part of the name, at least {queries.MIN_SEARCH_LENGTH} characters.")


class ScorecardParams(serializers.Serializer):
  view = serializers.CharField(required=False, help_text=column_help(models.ModelScorecard, "view"))
  period_type = serializers.CharField(required=False, help_text=column_help(models.ModelScorecard, "period_type"))


class CalibrationParams(serializers.Serializer):
  view = serializers.CharField(required=False, help_text=column_help(models.ModelCalibration, "view"))
