"""Filter inputs for the paginated top-level queries."""

from __future__ import annotations

import strawberry_django
from strawberry import auto

from racing import models


@strawberry_django.filter_type(models.Race, lookups=True)
class RaceFilter:
  race_date: auto
  country_code: auto
  race_type: auto
  result_status: auto
  has_handicap: auto
  course_id: int | None
  meeting_id: int | None


@strawberry_django.filter_type(models.Runner)
class RunnerFilter:
  race_date: strawberry_django.DateFilterLookup | None
  horse_id: int | None
  jockey_id: int | None
  trainer_id: int | None
  finish_position: int | None

