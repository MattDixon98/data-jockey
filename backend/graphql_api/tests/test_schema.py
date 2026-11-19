import json
from unittest import mock

from django.db import connections
from django.test import Client
from django.test.utils import CaptureQueriesContext

from graphql_api.schema import MAX_DEPTH, schema
from racing import models
from racing.routers import SNAPSHOT_DB

from .snapshot import RACE_DAY as RACE_DAY_DATE
from .snapshot import DROPPED_RIDE, PAST_RACE, TODAY_RACE, SnapshotTestCase

RACE_DAY = '"2026-11-19"'


class QueryTestCase(SnapshotTestCase):
  def query(self, text):
    result = schema.execute_sync(text)
    self.assertIsNone(result.errors, result.errors)
    return result.data

  def errors(self, text):
    result = schema.execute_sync(text)
    self.assertIsNotNone(result.errors)
    return [error.message for error in result.errors]


class RacecardTests(QueryTestCase):
  HOMEPAGE = """{
    meetings(date: %s) {
      course { name }
      races {
        raceId raceTime snapshot
        runners { rideId clothNumber horse { name } jockey { name } modelOdds { snapshot modelProb } modelValue { undervalued } }
      }
    }
  }""" % RACE_DAY

  def test_meetings_by_course_name_races_by_time_runners_by_cloth(self):
    meetings = self.query(self.HOMEPAGE)["meetings"]
    self.assertEqual([meeting["course"]["name"] for meeting in meetings], ["Lingfield", "Newcastle"])
    races = meetings[0]["races"]
    self.assertEqual([race["raceId"] for race in races], [TODAY_RACE, PAST_RACE])
    self.assertEqual([runner["clothNumber"] for runner in races[0]["runners"]], [1, 2, 3])

  def test_model_rows_default_to_the_runners_own_snapshot(self):
    runner = self.query(self.HOMEPAGE)["meetings"][0]["races"][0]["runners"][0]
    self.assertEqual(runner["modelOdds"], {"snapshot": "TODAY", "modelProb": 0.25})
    self.assertEqual(runner["modelValue"], {"undervalued": False})

  def test_model_rows_at_an_earlier_snapshot(self):
    race = self.query("""{ race(raceId: %d) { runners {
      modelValue(snapshot: T_1) { undervalued }
      modelOddsSnapshots { snapshot }
    } } }""" % TODAY_RACE)["race"]
    first, second, third = race["runners"]
    self.assertEqual(first["modelValue"], {"undervalued": True})
    self.assertEqual([row["snapshot"] for row in first["modelOddsSnapshots"]], ["T_1", "TODAY"])
    self.assertIsNone(second["modelValue"])
    self.assertEqual(third["modelOddsSnapshots"], [])

  def test_dropped_entries_are_not_runners(self):
    race = self.query("{ race(raceId: %d) { runners { rideId } } }" % TODAY_RACE)["race"]
    self.assertNotIn(DROPPED_RIDE, [runner["rideId"] for runner in race["runners"]])

  def test_query_count_does_not_grow_with_runners(self):
    with CaptureQueriesContext(connections[SNAPSHOT_DB]) as before:
      self.query(self.HOMEPAGE)
    load_more_runners()
    with CaptureQueriesContext(connections[SNAPSHOT_DB]) as after:
      data = self.query(self.HOMEPAGE)
    self.assertEqual(len(data["meetings"][0]["races"][0]["runners"]), 13)
    self.assertEqual(len(after), len(before))
    self.assertLessEqual(len(after), 8)

  def test_past_race(self):
    race = self.query("""{ race(raceId: %d) {
      prizes { position amount }
      runners { finishPosition oddsSnapshots { snapshot odds } oddsHistory { seq odds } horse { form { courseName } } }
    } }""" % PAST_RACE)["race"]
    self.assertEqual(race["prizes"], [{"position": 1, "amount": "3000.00"}, {"position": 2, "amount": "1000.00"}])
    runner = race["runners"][0]
    self.assertEqual(runner["finishPosition"], 1)
    self.assertEqual(
      [(row["snapshot"], row["odds"]) for row in runner["oddsSnapshots"]],
      [("T_1", "4/1"), ("TODAY", "9/2"), ("PAST", "7/2")],
    )
    self.assertEqual([move["seq"] for move in runner["oddsHistory"]], [1, 2])
    self.assertEqual([run["courseName"] for run in runner["horse"]["form"]], ["Thurles", "Naas"])

  def test_unknown_race_is_null(self):
    self.assertIsNone(self.query("{ race(raceId: 1) { name } }")["race"])


class UndervaluedTests(QueryTestCase):
  def picks(self, arguments):
    data = self.query("{ undervalued(date: %s%s) { rideId } }" % (RACE_DAY, arguments))
    return [runner["rideId"] for runner in data["undervalued"]]

  def test_defaults_to_each_races_latest_snapshot(self):
    self.assertEqual(self.picks(""), [3002])

  def test_at_a_given_snapshot(self):
    self.assertEqual(self.picks(", snapshot: T_1"), [3001])


class ListTests(QueryTestCase):
  def test_race_filters(self):
    data = self.query('{ races(filters: {raceType: {exact: "CHASE"}}) { totalCount results { raceId } } }')
    self.assertEqual(data["races"], {"totalCount": 1, "results": [{"raceId": PAST_RACE}]})

  def test_page_size_is_capped(self):
    data = self.query("{ races(pagination: {limit: 100000}) { pageInfo { limit } } }")
    self.assertEqual(data["races"]["pageInfo"]["limit"], 200)

  def test_runner_filters(self):
    data = self.query("{ runners(filters: {jockeyId: 50}) { totalCount } }")
    self.assertEqual(data["runners"]["totalCount"], 3)

  def test_name_search(self):
    data = self.query('{ horses(name: "frat") { results { horseId } } }')
    self.assertEqual(data["horses"]["results"], [{"horseId": 104}])
    self.assertIn("Search for at least 3 characters", self.errors('{ horses(name: "fr") { totalCount } }'))

  def test_track_record(self):
    data = self.query('{ scorecard(view: "after_race") { bets } calibration { bandLabel } snapshotInfo { formatVersion } }')
    self.assertEqual(data, {"scorecard": [{"bets": 10}], "calibration": [{"bandLabel": "0-5%"}], "snapshotInfo": {"formatVersion": 1}})


class LimitTests(QueryTestCase):
  def test_too_deep(self):
    nested = "name"
    for _ in range(MAX_DEPTH):
      nested = "race { runners { %s } }" % nested
    self.assertIn("exceeds maximum operation depth", self.errors("{ race(raceId: %d) { %s } }" % (TODAY_RACE, nested))[0])

  def test_too_many_aliases(self):
    aliases = " ".join(f"a{index}: snapshotInfo {{ builtAt }}" for index in range(20))
    self.assertIn("aliases", self.errors("{ %s }" % aliases)[0])

  def test_unexpected_errors_are_masked(self):
    with mock.patch("racing.models.SnapshotInfo.objects.first", side_effect=RuntimeError("/srv/secret/path")):
      self.assertEqual(self.errors("{ snapshotInfo { builtAt } }"), ["Unexpected error."])

  def test_read_only(self):
    self.assertNotIn("type Mutation", schema.as_str())


class HttpTests(SnapshotTestCase):
  def test_post_without_csrf_token(self):
    client = Client(enforce_csrf_checks=True)
    response = client.post("/graphql/", json.dumps({"query": "{ snapshotInfo { formatVersion } }"}), content_type="application/json")
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json(), {"data": {"snapshotInfo": {"formatVersion": 1}}})

  def test_graphiql_in_a_browser(self):
    response = self.client.get("/graphql/", HTTP_ACCEPT="text/html")
    self.assertEqual(response.status_code, 200)
    self.assertIn(b"graphiql", response.content.lower())


def load_more_runners():
  for index in range(10):
    ride_id = 3100 + index
    models.Horse.objects.create(horse_id=1100 + index, name=f"Extra {index}")
    models.Runner.objects.create(
      ride_id=ride_id, race_id=TODAY_RACE, race_date=RACE_DAY_DATE,
      horse_id=1100 + index, jockey_id=50, cloth_number=10 + index, snapshot="today",
    )
