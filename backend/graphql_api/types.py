"""GraphQL types, one per racing model.

Ids are plain Ints (the source's ids, all well inside GraphQL's 32-bit Int).
Lists that can grow without bound (a jockey's rides, a course's races) aren't
fields here: they're paginated top-level queries with filters (schema.py).
Default orderings live in each type's get_queryset, which the optimizer also
applies to prefetched lists (a race's runners come in cloth-number order).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

import strawberry
import strawberry_django
from strawberry import auto
from strawberry.scalars import JSON

from racing import models


@strawberry.enum(description="Which crawl a row comes from: t-3..t-1 days before the race, the race-morning crawl, or the result.")
class Snapshot(Enum):
  T_3 = "t-3"
  T_2 = "t-2"
  T_1 = "t-1"
  TODAY = "today"
  PAST = "past"


@strawberry_django.type(models.SnapshotInfo, description="When the data being served was built.")
class SnapshotInfo:
  built_at: auto
  format_version: auto


@strawberry_django.type(models.Course)
class Course:
  course_id: int
  name: auto
  shortcode: auto
  country_code: auto
  country_name: auto


@strawberry_django.type(models.Meeting, description="A day's racing at one course.")
class Meeting:
  meeting_id: int
  meeting_date: auto
  course: Course | None
  going: auto
  surface_summary: auto
  weather: auto
  races: list[Race]


@strawberry_django.type(models.Horse)
class Horse:
  horse_id: int
  name: auto
  slug: auto
  sex: auto
  foaled: auto
  runners: list[Runner] = strawberry_django.field(description="Its rides in crawled UK/IRE races, newest first.")
  form: list[HorseFormRun] = strawberry_django.field(
    description="Previous runs as listed on its racecards (newest first), including ones before the crawl began and abroad.",
  )


@strawberry_django.type(models.Jockey)
class Jockey:
  jockey_id: int
  name: auto


@strawberry_django.type(models.Trainer)
class Trainer:
  trainer_id: int
  name: auto
  slug: auto


@strawberry_django.type(models.Prize)
class Prize:
  position: auto
  amount: auto
  currency: auto

  @classmethod
  def get_queryset(cls, queryset, info, **kwargs):
    return queryset.order_by("position")


@strawberry_django.type(models.HorseForm, name="HorseFormRun")
class HorseFormRun:
  race_id: int = strawberry_django.field(description="The source's race id; many of these races were never crawled.")
  race_date: auto
  race_time: auto
  course_name: auto
  course_shortcode: auto
  race_name: auto
  race_class: auto
  run_type: auto
  distance: auto
  distance_yards: auto
  going: auto
  going_shortcode: auto
  runner_count: auto
  finish_position: auto
  non_finisher_reason: auto
  weight: auto
  weight_lbs: auto
  official_rating: auto
  odds: auto
  odds_decimal: auto

  @classmethod
  def get_queryset(cls, queryset, info, **kwargs):
    return queryset.order_by("-race_date", "-race_time")


@strawberry_django.type(models.OddsSnapshot, description="The market price at one crawl (forecast before the race, SP in past).")
class OddsSnapshot:
  snapshot: Snapshot | None
  status: auto
  odds: auto
  odds_decimal: auto
  favourite: auto


@strawberry_django.type(models.OddsHistory, description="An on-course price move; seq 1 is the opening show.")
class OddsMove:
  seq: auto
  odds: auto
  odds_decimal: auto

  @classmethod
  def get_queryset(cls, queryset, info, **kwargs):
    return queryset.order_by("seq")


@strawberry_django.type(models.ModelOdds, description="Our fair win odds (a 100% book) for a runner at one snapshot.")
class ModelOdds:
  snapshot: Snapshot | None
  model_version: auto
  in_sample: bool | None = strawberry_django.field(description="The model was trained on this race, so it isn't a fair test.")
  model_prob: auto
  model_odds_decimal: auto
  model_odds: auto
  model_rank: int | None = strawberry_django.field(description="1 = our favourite.")
  field_size: auto


@strawberry_django.type(models.ModelValue, description="Our probability next to the market's (margin removed), and the undervalued flag.")
class ModelValue:
  snapshot: Snapshot | None
  model_version: auto
  in_sample: auto
  model_prob: auto
  model_odds: auto
  market: str | None = strawberry_django.field(description="sp for past rows, forecast before the race.")
  market_odds: auto
  market_odds_decimal: auto
  market_prob: auto
  book_percentage: auto
  edge: float | None = strawberry_django.field(description="model_prob / market_prob - 1.")
  expected_value: float | None = strawberry_django.field(description="Return per unit staked at the market price if our probability is right.")
  undervalued: auto
  won: auto
  finish_position: auto


def _at_snapshot(rows, snapshot: Snapshot | None, own_snapshot: str | None):
  """The row for one snapshot out of a prefetched per-snapshot list. Fields that
  call this read runner.snapshot, so they ask the optimizer for it (only=...):
  otherwise it's left out of the query and fetched once per runner."""
  wanted = snapshot.value if snapshot else own_snapshot
  for row in rows:
    if row.snapshot == wanted:
      return row
  return None


def _oldest_first(rows):
  return sorted(rows, key=lambda row: -row.snapshot_rank)


SnapshotArgument = Annotated[
  Snapshot | None,
  strawberry.argument(description="Defaults to the runner's own snapshot (its race's latest crawl)."),
]


@strawberry_django.type(models.Runner, description="A horse's ride in one race.")
class Runner:
  ride_id: int
  race: Race
  race_date: auto
  horse: Horse
  jockey: Jockey | None
  trainer: Trainer | None
  owner_name: auto
  cloth_number: auto
  draw: auto
  status: auto
  finish_position: int | None = strawberry_django.field(description="Only set once the race is in past (amended result if there was one).")
  non_finisher_reason: auto
  horse_age: auto
  weight: auto
  weight_lbs: auto
  official_rating: auto
  odds: str | None = strawberry_django.field(description="The latest price: forecast before the race, SP after it.")
  odds_decimal: auto
  favourite: auto
  headgear: auto
  days_since_last_run: auto
  lifetime_runs: auto
  lifetime_wins: auto
  lifetime_places: auto
  insights: JSON | None
  snapshot: Snapshot | None
  odds_history: list[OddsMove] = strawberry_django.field(description="On-course price moves (past races only).")

  @classmethod
  def get_queryset(cls, queryset, info, **kwargs):
    return queryset.order_by("-race_date", "cloth_number")

  @strawberry_django.field(prefetch_related=["odds_snapshots"], description="The market price at each crawl, oldest first.")
  def odds_snapshots(self) -> list[OddsSnapshot]:
    return _oldest_first(self.odds_snapshots.all())

  @strawberry_django.field(only=["snapshot"], prefetch_related=["model_odds"], description="Our odds at one snapshot.")
  def model_odds(self, snapshot: SnapshotArgument = None) -> ModelOdds | None:
    return _at_snapshot(self.model_odds.all(), snapshot, self.snapshot)

  @strawberry_django.field(prefetch_related=["model_odds"], description="Our odds at every snapshot, oldest first.")
  def model_odds_snapshots(self) -> list[ModelOdds]:
    return _oldest_first(self.model_odds.all())

  @strawberry_django.field(only=["snapshot"], prefetch_related=["model_value"], description="Ours vs the market at one snapshot (none at t-2/t-3: no prices).")
  def model_value(self, snapshot: SnapshotArgument = None) -> ModelValue | None:
    return _at_snapshot(self.model_value.all(), snapshot, self.snapshot)


Runner.get_queryset(models.Runner.objects.all(), None)  # type: ignore

@strawberry_django.type(models.Race)
class Race:
  race_id: int
  meeting: Meeting | None
  course: Course | None
  country_code: auto
  race_date: auto
  race_time: str | None = strawberry_django.field(description="Scheduled time, UK local (HH:MM).")
  off_time: auto
  name: auto
  race_type: str | None = strawberry_django.field(description="FLAT, HURDLE, CHASE or N_H_FLAT.")
  race_class: auto
  age_band: auto
  surface: auto
  distance: auto
  distance_yards: auto
  going: auto
  going_shortcode: auto
  has_handicap: auto
  race_stage: auto
  result_status: str | None = strawberry_django.field(description="Only complete races have trustworthy positions.")
  ride_count: auto
  placed_count: auto
  winning_time: auto
  winning_time_seconds: auto
  book_percentage: auto
  betting_forecast: auto
  verdict: auto
  snapshot: Snapshot | None
  runners: list[Runner]
  prizes: list[Prize]

  @classmethod
  def get_queryset(cls, queryset, info, **kwargs):
    return queryset.order_by("race_date", "race_time", "race_id")


@strawberry_django.type(models.ModelScorecard, description="How our odds and undervalued picks have done, out of sample.")
class ScorecardRow:
  view: str = strawberry_django.field(description="after_race (vs SP) or site_pick (the race-morning flags).")
  period_type: str = strawberry_django.field(description="all, month or model_version.")
  period: auto
  race_group: str = strawberry_django.field(description="all, flat or jumps.")
  first_race: auto
  last_race: auto
  races: auto
  runners: auto
  log_loss_model: auto
  log_loss_market: auto
  top_pick_won_model: auto
  top_pick_won_market: auto
  bets: auto
  bets_won: auto
  expected_wins_market: auto
  expected_wins_model: auto
  wins_z: auto
  profit_units: auto
  roi: auto
  roi_low: auto
  roi_high: auto


@strawberry_django.type(models.ModelCalibration, description="Predicted vs actual win rate per probability band.")
class CalibrationBand:
  view: auto
  source: str = strawberry_django.field(description="model or market.")
  band: auto
  band_label: auto
  runners: auto
  predicted: auto
  actual: auto
