"""A tiny snapshot for the API tests.

The test run gives the "snapshot" database an in-memory SQLite (Django's default
for a sqlite test database), and migrations never touch it (SnapshotRouter), so
the racing tables are created here from the models instead.

The data: one meeting on RACE_DAY with two races (the 14:00 a past result, the
13:00 still at its race-morning crawl), plus a t-3 entry that was dropped before
race day and so is only in model_odds.
"""

import datetime
from decimal import Decimal

from django.apps import apps
from django.db import connections
from django.test import TestCase

from racing import models
from racing.routers import SNAPSHOT_DB

RACE_DAY = datetime.date(2026, 11, 19)
TODAY_RACE = 2001
PAST_RACE = 2002
DROPPED_RIDE = 3999


def create_snapshot_tables():
  connection = connections[SNAPSHOT_DB]
  existing = set(connection.introspection.table_names())
  with connection.schema_editor() as editor:
    for model in apps.get_app_config("racing").get_models():
      if model._meta.db_table not in existing:
        editor.create_model(model)


def _model_rows(ride_id, race_id, horse_id, snapshot, rank, prob, undervalued=None):
  models.ModelOdds.objects.create(
    ride_id=ride_id, snapshot=snapshot, snapshot_rank=rank, race_id=race_id, race_date=RACE_DAY,
    horse_id=horse_id, model_version="2026-11-13", in_sample=False, model_prob=prob,
    model_odds_decimal=1 / prob, model_odds=f"{1 / prob - 1:.0f}/1", model_rank=1,
  )
  if undervalued is not None:
    models.ModelValue.objects.create(
      ride_id=ride_id, snapshot=snapshot, snapshot_rank=rank, race_id=race_id, race_date=RACE_DAY,
      horse_id=horse_id, model_prob=prob, market="forecast", market_odds="4/1", market_odds_decimal=5.0,
      market_prob=0.2, expected_value=prob * 5.0 - 1, undervalued=undervalued,
    )


def load_snapshot():
  models.SnapshotInfo.objects.create(built_at=datetime.datetime(2026, 11, 19, 7, 30, tzinfo=datetime.UTC), format_version=1)
  models.Course.objects.create(course_id=1, name="Newcastle", country_code="ENG")
  models.Course.objects.create(course_id=2, name="Lingfield", country_code="ENG")
  models.Meeting.objects.create(meeting_id=10, meeting_date=RACE_DAY, course_id=1)
  models.Meeting.objects.create(meeting_id=11, meeting_date=RACE_DAY, course_id=2)
  models.Jockey.objects.create(jockey_id=50, name="A Jockey")
  models.Trainer.objects.create(trainer_id=60, name="A Trainer")

  models.Race.objects.create(
    race_id=PAST_RACE, meeting_id=11, course_id=2, race_date=RACE_DAY, race_time="14:00",
    name="Past Handicap Chase", race_type="CHASE", result_status="complete", snapshot="past",
  )
  models.Race.objects.create(
    race_id=TODAY_RACE, meeting_id=11, course_id=2, race_date=RACE_DAY, race_time="13:00",
    name="Morning Novice Hurdle", race_type="HURDLE", result_status="incomplete", snapshot="today",
  )
  models.Prize.objects.create(race_id=PAST_RACE, position=2, amount=Decimal("1000.00"), currency="GBP")
  models.Prize.objects.create(race_id=PAST_RACE, position=1, amount=Decimal("3000.00"), currency="GBP")

  # Today's race: cloth numbers created out of order, so ordering is tested.
  for ride_id, horse_id, cloth in [(3002, 102, 2), (3001, 101, 1), (3003, 103, 3)]:
    models.Horse.objects.create(horse_id=horse_id, name=f"Horse {horse_id}")
    models.Runner.objects.create(
      ride_id=ride_id, race_id=TODAY_RACE, race_date=RACE_DAY, horse_id=horse_id, jockey_id=50,
      trainer_id=60, cloth_number=cloth, odds="4/1", snapshot="today",
    )
  _model_rows(3001, TODAY_RACE, 101, "t-1", 2, 0.30, undervalued=True)
  _model_rows(3001, TODAY_RACE, 101, "today", 1, 0.25, undervalued=False)
  _model_rows(3002, TODAY_RACE, 102, "today", 1, 0.26, undervalued=True)
  _model_rows(DROPPED_RIDE, TODAY_RACE, 199, "t-3", 4, 0.10)

  # Past race: one runner, with the market's moves and its form.
  models.Horse.objects.create(horse_id=104, name="Fratas")
  models.Runner.objects.create(
    ride_id=3004, race_id=PAST_RACE, race_date=RACE_DAY, horse_id=104, cloth_number=1,
    finish_position=1, odds="7/2", snapshot="past",
  )
  for snapshot, rank, odds in [("past", 0, "7/2"), ("t-1", 2, "4/1"), ("today", 1, "9/2")]:
    models.OddsSnapshot.objects.create(ride_id=3004, snapshot=snapshot, snapshot_rank=rank, race_id=PAST_RACE, odds=odds)
  for seq, odds in [(2, "4/1"), (1, "9/2")]:
    models.OddsHistory.objects.create(ride_id=3004, race_id=PAST_RACE, horse_id=104, seq=seq, odds=odds)
  models.HorseForm.objects.create(horse_id=104, race_id=1500, race_date=datetime.date(2026, 10, 11), course_name="Naas")
  models.HorseForm.objects.create(horse_id=104, race_id=1600, race_date=datetime.date(2026, 11, 1), course_name="Thurles")

  models.ModelScorecard.objects.create(view="after_race", period_type="all", period="all", race_group="all", bets=10)
  models.ModelCalibration.objects.create(view="after_race", source="model", band=0, band_label="0-5%")


class SnapshotTestCase(TestCase):
  databases = {"default", SNAPSHOT_DB}

  @classmethod
  def setUpClass(cls):
    create_snapshot_tables()
    super().setUpClass()

  @classmethod
  def setUpTestData(cls):
    load_snapshot()
