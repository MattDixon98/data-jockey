"""Query-string filters for the paginated lists (django-filter).

A filter on one column borrows that column's help_text (column_help), so it's
described once, in racing/models.py.
"""

from __future__ import annotations

from django_filters import rest_framework as filters

from racing import models

from .descriptions import column_help


class RaceFilter(filters.FilterSet):
  date = filters.DateFilter(field_name="race_date", help_text="Race day, YYYY-MM-DD.")
  date_from = filters.DateFilter(field_name="race_date", lookup_expr="gte")
  date_to = filters.DateFilter(field_name="race_date", lookup_expr="lte")
  course_id = filters.NumberFilter(field_name="course_id")
  meeting_id = filters.NumberFilter(field_name="meeting_id")
  country_code = filters.CharFilter(help_text=column_help(models.Race, "country_code"))
  race_type = filters.CharFilter(help_text=column_help(models.Race, "race_type"))
  result_status = filters.CharFilter(help_text=column_help(models.Race, "result_status"))
  has_handicap = filters.BooleanFilter()

  class Meta:
    model = models.Race
    fields = []


class RunnerFilter(filters.FilterSet):
  date_from = filters.DateFilter(field_name="race_date", lookup_expr="gte")
  date_to = filters.DateFilter(field_name="race_date", lookup_expr="lte")
  race_id = filters.NumberFilter(field_name="race_id")
  horse_id = filters.NumberFilter(field_name="horse_id")
  jockey_id = filters.NumberFilter(field_name="jockey_id")
  trainer_id = filters.NumberFilter(field_name="trainer_id")
  finish_position = filters.NumberFilter(help_text=column_help(models.Runner, "finish_position"))

  class Meta:
    model = models.Runner
    fields = []
