"""The REST API's views: read-only (GET/HEAD only), public and cookie-free.

Each view takes its queryset from api.queries (shared with GraphQL) and adds
the prefetches its serializer needs, so a list costs a fixed number of SQL
queries however many rows it has. Unbounded lists are paginated (?limit=&offset=);
the rest are small, fixed lists.
"""

from __future__ import annotations

from functools import cached_property

from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView
from rest_framework.views import exception_handler as drf_exception_handler

from api import queries
from racing import models

from . import serializers
from .caching import SnapshotCachingMixin
from .filters import RaceFilter, RunnerFilter


def exception_handler(exc, context):
  """queries.ApiError is the client's mistake: a 400 with its message."""
  if isinstance(exc, queries.ApiError):
    exc = ParseError(str(exc))
  return drf_exception_handler(exc, context)


def _runner_lookups(prefix: str = "", race_page: bool = False) -> list:
  """select_related/prefetch lookups for runners at `prefix` ("" = the queryset itself is runners)."""
  path = f"{prefix}__" if prefix else ""
  lookups = [f"{path}model_odds", f"{path}model_value"]
  if race_page:
    lookups += [f"{path}odds_snapshots", Prefetch(f"{path}odds_history", queryset=queries.odds_moves())]
  return lookups


def _runners_with_people():
  return queries.runners().select_related("horse", "jockey", "trainer")


class ApiView(SnapshotCachingMixin, generics.GenericAPIView):
  """Base view. `params_class` validates the query string (400 on a bad value)
  and documents it; its `snapshot`, if any, reaches the serializers."""
  params_class = None

  def schema_only(self) -> bool:
    """drf-spectacular builds the docs with no query string to read params from."""
    return getattr(self, "swagger_fake_view", False)

  @cached_property
  def params(self) -> dict:
    if self.params_class is None:
      return {}
    serializer = self.params_class(data=self.request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data

  def get_serializer_context(self):
    context = super().get_serializer_context()
    context["snapshot"] = self.params.get("snapshot")
    return context


class ListView(ApiView, generics.ListAPIView):
  pass


class DetailView(ApiView, generics.RetrieveAPIView):
  pass


class SnapshotInfoView(DetailView):
  """When the data being served was built."""
  serializer_class = serializers.SnapshotInfoSerializer

  def get_object(self):
    info = queries.snapshot_info()
    if info is None:
      raise NotFound("No snapshot loaded")
    return info


@extend_schema_view(get=extend_schema(parameters=[serializers.DateParams]))
class MeetingListView(ListView):
  """A day's racing: one meeting per course (by course name), races in time
  order, runners by cloth number, each with our odds and value."""
  serializer_class = serializers.MeetingSerializer
  params_class = serializers.DateParams
  pagination_class = None

  def get_queryset(self):
    if self.schema_only():
      return models.Meeting.objects.none()
    races = queries.races().select_related("course")
    return (
      queries.meetings_on(self.params["date"])
      .select_related("course")
      .prefetch_related(
        Prefetch("races", queryset=races),
        Prefetch("races__runners", queryset=_runners_with_people()),
        *_runner_lookups("races__runners"),
      )
    )


class RaceListView(ListView):
  """Races in date and time order (without runners: see /races/{race_id}/)."""
  serializer_class = serializers.RaceSerializer
  filterset_class = RaceFilter

  def get_queryset(self):
    return queries.races().select_related("course")


@extend_schema_view(get=extend_schema(parameters=[serializers.SnapshotParams]))
class RaceDetailView(DetailView):
  """One race: runners by cloth number with every snapshot's prices and our odds, and prizes."""
  serializer_class = serializers.RaceDetailSerializer
  params_class = serializers.SnapshotParams
  lookup_field = "race_id"

  def get_queryset(self):
    return (
      queries.races()
      .select_related("course")
      .prefetch_related(
        Prefetch("runners", queryset=_runners_with_people()),
        *_runner_lookups("runners", race_page=True),
        Prefetch("prizes", queryset=queries.prizes()),
      )
    )


class RunnerListView(ListView):
  """Rides, newest first: filter by horse, jockey or trainer for their record."""
  serializer_class = serializers.RunnerWithRaceSerializer
  filterset_class = RunnerFilter

  def get_queryset(self):
    return (
      _runners_with_people()
      .select_related("race__course")
      .prefetch_related(*_runner_lookups())
    )


@extend_schema_view(get=extend_schema(parameters=[serializers.DateParams]))
class UndervaluedView(ListView):
  """Runners we flag as undervalued on a race day: at `snapshot` (TODAY for the
  race-morning picks), by default at each race's latest crawl (vs SP once it's run)."""
  serializer_class = serializers.RunnerWithRaceSerializer
  params_class = serializers.DateParams
  pagination_class = None

  def get_queryset(self):
    if self.schema_only():
      return models.Runner.objects.none()
    return (
      queries.undervalued(self.params["date"], self.params.get("snapshot"))
      .select_related("race__course", "horse", "jockey", "trainer")
      .prefetch_related(*_runner_lookups())
    )


class CourseListView(ListView):
  """Every UK/IRE course, by name."""
  serializer_class = serializers.CourseSerializer
  pagination_class = None

  def get_queryset(self):
    return queries.courses()


class CourseDetailView(DetailView):
  serializer_class = serializers.CourseSerializer
  lookup_field = "course_id"
  queryset = models.Course.objects.all()


class NameSearchView(ListView):
  """Base for the name searches (paginated, by name)."""
  params_class = serializers.NameSearchParams
  model = None

  def get_queryset(self):
    if self.schema_only():
      return self.model.objects.none()
    return queries.name_search(self.model, self.params["name"])


@extend_schema_view(get=extend_schema(parameters=[serializers.NameSearchParams]))
class HorseListView(NameSearchView):
  """Horses whose name contains `name`. Their rides: /runners/?horse_id=."""
  serializer_class = serializers.HorseSerializer
  model = models.Horse


class HorseDetailView(DetailView):
  """A horse and its form (previous runs, newest first)."""
  serializer_class = serializers.HorseDetailSerializer
  lookup_field = "horse_id"

  def get_queryset(self):
    return models.Horse.objects.prefetch_related(Prefetch("form", queryset=queries.horse_form()))


@extend_schema_view(get=extend_schema(parameters=[serializers.NameSearchParams]))
class JockeyListView(NameSearchView):
  """Jockeys whose name contains `name`. Their rides: /runners/?jockey_id=."""
  serializer_class = serializers.JockeySerializer
  model = models.Jockey


class JockeyDetailView(DetailView):
  serializer_class = serializers.JockeySerializer
  lookup_field = "jockey_id"
  queryset = models.Jockey.objects.all()


@extend_schema_view(get=extend_schema(parameters=[serializers.NameSearchParams]))
class TrainerListView(NameSearchView):
  """Trainers whose name contains `name`. Their runners: /runners/?trainer_id=."""
  serializer_class = serializers.TrainerSerializer
  model = models.Trainer


class TrainerDetailView(DetailView):
  serializer_class = serializers.TrainerSerializer
  lookup_field = "trainer_id"
  queryset = models.Trainer.objects.all()


@extend_schema_view(get=extend_schema(parameters=[serializers.ScorecardParams]))
class ScorecardView(ListView):
  """The track record: how our odds and undervalued picks have done out of
  sample, one row per view, period and race group."""
  serializer_class = serializers.ScorecardRowSerializer
  params_class = serializers.ScorecardParams
  pagination_class = None

  def get_queryset(self):
    return queries.scorecard(self.params.get("view"), self.params.get("period_type"))


@extend_schema_view(get=extend_schema(parameters=[serializers.CalibrationParams]))
class CalibrationView(ListView):
  """Predicted vs actual win rate per probability band, ours and the market's."""
  serializer_class = serializers.CalibrationBandSerializer
  params_class = serializers.CalibrationParams
  pagination_class = None

  def get_queryset(self):
    return queries.calibration(self.params.get("view"))


ROOT_LINKS = [
  "snapshot",
  "meetings",
  "races",
  "runners",
  "undervalued",
  "courses",
  "horses",
  "jockeys",
  "trainers",
  "scorecard",
  "calibration",
  "docs",
  "schema",
]


class ApiRootView(APIView):
  """Data Jockey's REST API: UK/IRE racing, our win odds and the track record.
  Read-only. OpenAPI docs at /api/v1/docs/."""

  @extend_schema(exclude=True)
  def get(self, request):
    links = {name: reverse(f"rest:{name}", request=request) for name in ROOT_LINKS}
    return Response(links)
