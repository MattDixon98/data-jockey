"""The questions the API asks of the snapshot, answered once.

The GraphQL API (api/graphql/) builds its responses from these querysets and
rules: what a day's card is, which runners are undervalued and what order
things come in. Kept apart from the API code so any other way of serving the
data answers them the same way. The API adds only how it loads related rows
(the GraphQL optimizer) and how it shapes the response.
"""

from __future__ import annotations

import datetime
from enum import Enum

from django.db.models import F

from racing import models


class Snapshot(Enum):
  """Which crawl a row comes from, oldest first: t-3..t-1 days before the race,
  the race-morning crawl, then the result. The values are the snapshot columns'."""
  T_3 = "t-3"
  T_2 = "t-2"
  T_1 = "t-1"
  TODAY = "today"
  PAST = "past"


SNAPSHOTS = tuple(snapshot.value for snapshot in Snapshot)

# Default orderings.
MEETING_ORDER = ("course__name",)
RACE_ORDER = ("race_date", "race_time", "race_id")
# A race's runners by cloth number; a horse's (jockey's...) rides newest first.
RUNNER_ORDER = ("-race_date", "cloth_number")
PRIZE_ORDER = ("position",)
FORM_ORDER = ("-race_date", "-race_time")
ODDS_MOVE_ORDER = ("seq",)
SCORECARD_ORDER = ("view", "period_type", "period", "race_group")
CALIBRATION_ORDER = ("view", "source", "band")

# Name searches shorter than this would match most of the table.
MIN_SEARCH_LENGTH = 3


class ApiError(Exception):
  """A mistake in the request, with a message meant for the client."""


def snapshot_info() -> models.SnapshotInfo | None:
  return models.SnapshotInfo.objects.first()


def meetings_on(date: datetime.date):
  """A day's racing, one meeting per course."""
  return models.Meeting.objects.filter(meeting_date=date).order_by(*MEETING_ORDER)


def races():
  return models.Race.objects.order_by(*RACE_ORDER)


def runners():
  return models.Runner.objects.order_by(*RUNNER_ORDER)


def prizes():
  return models.Prize.objects.order_by(*PRIZE_ORDER)


def horse_form():
  return models.HorseForm.objects.order_by(*FORM_ORDER)


def odds_moves():
  return models.OddsHistory.objects.order_by(*ODDS_MOVE_ORDER)


def courses():
  return models.Course.objects.order_by("name")


def check_snapshot(snapshot: str | None) -> str | None:
  if snapshot is not None and snapshot not in SNAPSHOTS:
    raise ApiError(f"Unknown snapshot {snapshot!r}: one of {', '.join(SNAPSHOTS)}")
  return snapshot


def undervalued(date: datetime.date, snapshot: str | None = None):
  """Runners flagged undervalued on a race day: at `snapshot`, or by default
  at each race's latest crawl (vs SP once it has run)."""
  wanted_snapshot = check_snapshot(snapshot) or F("snapshot")
  return models.Runner.objects.filter(
    race_date=date,
    model_value__snapshot=wanted_snapshot,
    model_value__undervalued=True,
  ).order_by("race__race_time", "cloth_number")


def name_search(model, name: str):
  """Horses, jockeys or trainers whose name contains `name`."""
  name = name.strip()
  if len(name) < MIN_SEARCH_LENGTH:
    raise ApiError(f"Search for at least {MIN_SEARCH_LENGTH} characters")
  return model.objects.filter(name__icontains=name).order_by("name")


def scorecard(view: str | None = None, period_type: str | None = None):
  rows = models.ModelScorecard.objects.order_by(*SCORECARD_ORDER)
  if view:
    rows = rows.filter(view=view)
  if period_type:
    rows = rows.filter(period_type=period_type)
  return rows


def calibration(view: str | None = None):
  rows = models.ModelCalibration.objects.order_by(*CALIBRATION_ORDER)
  if view:
    rows = rows.filter(view=view)
  return rows


def at_snapshot(rows, snapshot: str | None, own_snapshot: str | None):
  """The row for one snapshot out of a runner's (prefetched) per-snapshot model
  rows: `snapshot`, or by default the runner's own (its race's latest crawl)."""
  wanted = snapshot or own_snapshot
  for row in rows:
    if row.snapshot == wanted:
      return row
  return None


def oldest_first(rows):
  """Per-snapshot rows (odds snapshots, model odds) from t-3 to past."""
  return sorted(rows, key=lambda row: -row.snapshot_rank)
