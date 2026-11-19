"""The Query root, the schema and its safety limits.

The API is public and read-only, so the limits are about cost: lists are
paginated (PAGINATION_MAX_LIMIT in settings), and the extensions below reject
queries that nest too deep, alias the same field many times or are simply huge,
before any SQL runs. Unexpected errors are masked outside DEBUG (the test run
included, so the tests see what a client would).
"""

from __future__ import annotations

import datetime
from typing import Annotated

import strawberry
import strawberry_django
from django.conf import settings
from graphql import GraphQLError
from strawberry.extensions import MaskErrors, MaxAliasesLimiter, MaxTokensLimiter, ParserCache, QueryDepthLimiter, ValidationCache
from strawberry_django.optimizer import DjangoOptimizerExtension
from strawberry_django.pagination import OffsetPaginated

from api import queries
from api.queries import ApiError
from racing import models

from .filters import RaceFilter, RunnerFilter
from .types import (
  CalibrationBand,
  Course,
  Horse,
  Jockey,
  Meeting,
  Race,
  Runner,
  ScorecardRow,
  Snapshot,
  SnapshotInfo,
  Trainer,
)

# Deep enough for meetings > races > runners > horse > form > field (6), with room to spare.
MAX_DEPTH = 8
MAX_ALIASES = 15
MAX_TOKENS = 2000


def _should_mask(error: GraphQLError) -> bool:
  """Hide only unexpected exceptions (they could leak internals). Errors with no
  original exception (syntax, validation, the limits above) and ApiErrors are
  the client's to fix, so they keep their message."""
  original = error.original_error
  if original is None:
    return False
  return not isinstance(original, (GraphQLError, ApiError))


@strawberry.type
class Query:
  @strawberry_django.field(description="When the data being served was built.")
  def snapshot_info(self) -> SnapshotInfo | None:
    return queries.snapshot_info()

  @strawberry_django.field(description="A day's racing, one meeting per course (by course name), races in time order.")
  def meetings(self, date: datetime.date) -> list[Meeting]:
    return queries.meetings_on(date)

  @strawberry_django.field(description="One race by its id.")
  def race(self, race_id: int) -> Race | None:
    return models.Race.objects.filter(race_id=race_id).first()

  races: OffsetPaginated[Race] = strawberry_django.offset_paginated(
    filters=RaceFilter,
    description="Races in date and time order.",
  )

  runners: OffsetPaginated[Runner] = strawberry_django.offset_paginated(
    filters=RunnerFilter,
    description="Rides, newest first: filter by horse, jockey or trainer for their record.",
  )

  @strawberry_django.field(description="Runners we flag as undervalued on a race day.")
  def undervalued(
    self,
    date: datetime.date,
    snapshot: Annotated[
      Snapshot | None,
      strawberry.argument(
        description="Whose flags: defaults to each race's latest crawl (vs SP once it's run). TODAY for the race-morning picks.",
      ),
    ] = None,
  ) -> list[Runner]:
    return queries.undervalued(date, snapshot.value if snapshot else None)

  @strawberry_django.field
  def course(self, course_id: int) -> Course | None:
    return models.Course.objects.filter(course_id=course_id).first()

  @strawberry_django.field(description="Every UK/IRE course, by name.")
  def courses(self) -> list[Course]:
    return queries.courses()

  @strawberry_django.field
  def horse(self, horse_id: int) -> Horse | None:
    return models.Horse.objects.filter(horse_id=horse_id).first()

  @strawberry_django.field
  def jockey(self, jockey_id: int) -> Jockey | None:
    return models.Jockey.objects.filter(jockey_id=jockey_id).first()

  @strawberry_django.field
  def trainer(self, trainer_id: int) -> Trainer | None:
    return models.Trainer.objects.filter(trainer_id=trainer_id).first()

  @strawberry_django.offset_paginated(OffsetPaginated[Horse], description="Horses whose name contains `name`.")
  def horses(self, name: str) -> list[Horse]:
    return queries.name_search(models.Horse, name)

  @strawberry_django.offset_paginated(OffsetPaginated[Jockey], description="Jockeys whose name contains `name`.")
  def jockeys(self, name: str) -> list[Jockey]:
    return queries.name_search(models.Jockey, name)

  @strawberry_django.offset_paginated(OffsetPaginated[Trainer], description="Trainers whose name contains `name`.")
  def trainers(self, name: str) -> list[Trainer]:
    return queries.name_search(models.Trainer, name)

  @strawberry_django.field(description="The track record: one row per view, period and race group.")
  def scorecard(self, view: str | None = None, period_type: str | None = None) -> list[ScorecardRow]:
    return queries.scorecard(view, period_type)

  @strawberry_django.field(description="Calibration bands, ours and the market's.")
  def calibration(self, view: str | None = None) -> list[CalibrationBand]:
    return queries.calibration(view)


def _extensions():
  extensions = [
    QueryDepthLimiter(max_depth=MAX_DEPTH),
    MaxAliasesLimiter(max_alias_count=MAX_ALIASES),
    MaxTokensLimiter(max_token_count=MAX_TOKENS),
    ParserCache(),
    ValidationCache(),
    DjangoOptimizerExtension(),
  ]
  if not settings.DEBUG:
    extensions.append(MaskErrors(should_mask_error=_should_mask))
  return extensions


schema = strawberry.Schema(query=Query, extensions=_extensions())
