from unittest import mock

from django.core.cache import cache
from django.db import connections
from django.test.utils import CaptureQueriesContext
from rest_framework.settings import api_settings
from rest_framework.throttling import AnonRateThrottle

from api.graphql.schema import schema
from racing import models
from racing.routers import SNAPSHOT_DB
from .snapshot import DROPPED_RIDE, PAST_RACE, RACE_DAY, TODAY_RACE, SnapshotTestCase, add_runners

API = "/api/v1"
DAY = RACE_DAY.isoformat()


class ApiTestCase(SnapshotTestCase):
  def setUp(self):
    # The rate limit's counters live in the cache: start every test with none.
    cache.clear()

  def get(self, path, status=200, **headers):
    response = self.client.get(f"{API}{path}", HTTP_ACCEPT="application/json", **headers)
    self.assertEqual(response.status_code, status, response.content)
    return response

  def data(self, path):
    return self.get(path).json()


class RacecardTests(ApiTestCase):
  def test_meetings_by_course_name_races_by_time_runners_by_cloth(self):
    meetings = self.data(f"/meetings/?date={DAY}")
    self.assertEqual([meeting["course"]["name"] for meeting in meetings], ["Lingfield", "Newcastle"])
    races = meetings[0]["races"]
    self.assertEqual([race["race_id"] for race in races], [TODAY_RACE, PAST_RACE])
    self.assertEqual([runner["cloth_number"] for runner in races[0]["runners"]], [1, 2, 3])

  def test_model_rows_default_to_the_runners_own_snapshot(self):
    runner = self.data(f"/meetings/?date={DAY}")[0]["races"][0]["runners"][0]
    self.assertEqual(runner["horse"], {"horse_id": 101, "name": "Horse 101"})
    self.assertEqual((runner["model_odds"]["snapshot"], runner["model_odds"]["model_prob"]), ("today", 0.25))
    self.assertFalse(runner["model_value"]["undervalued"])

  def test_model_rows_at_an_earlier_snapshot(self):
    first, second, third = self.data(f"/races/{TODAY_RACE}/?snapshot=t-1")["runners"]
    self.assertTrue(first["model_value"]["undervalued"])
    self.assertEqual([row["snapshot"] for row in first["model_odds_snapshots"]], ["t-1", "today"])
    self.assertIsNone(second["model_value"])
    self.assertEqual(third["model_odds_snapshots"], [])

  def test_dropped_entries_are_not_runners(self):
    runners = self.data(f"/races/{TODAY_RACE}/")["runners"]
    self.assertNotIn(DROPPED_RIDE, [runner["ride_id"] for runner in runners])

  def test_past_race(self):
    race = self.data(f"/races/{PAST_RACE}/")
    self.assertEqual(race["prizes"], [
      {"position": 1, "amount": "3000.00", "currency": "GBP"},
      {"position": 2, "amount": "1000.00", "currency": "GBP"},
    ])
    runner = race["runners"][0]
    self.assertEqual(runner["finish_position"], 1)
    self.assertEqual(
      [(row["snapshot"], row["odds"]) for row in runner["odds_snapshots"]],
      [("t-1", "4/1"), ("today", "9/2"), ("past", "7/2")],
    )
    self.assertEqual([move["seq"] for move in runner["odds_history"]], [1, 2])

  def test_query_count_does_not_grow_with_runners(self):
    with CaptureQueriesContext(connections[SNAPSHOT_DB]) as before:
      self.get(f"/meetings/?date={DAY}")
    add_runners()
    with CaptureQueriesContext(connections[SNAPSHOT_DB]) as after:
      meetings = self.data(f"/meetings/?date={DAY}")
    self.assertEqual(len(meetings[0]["races"][0]["runners"]), 13)
    self.assertEqual(len(after), len(before))

  def test_unknown_race_is_404(self):
    self.get("/races/1/", status=404)

  def test_bad_parameters_are_400(self):
    self.assertIn("date", self.get("/meetings/", status=400).json())
    self.assertIn("snapshot", self.get(f"/meetings/?date={DAY}&snapshot=yesterday", status=400).json())
    self.assertIn("date", self.get("/meetings/?date=19-11-2026", status=400).json())


class UndervaluedTests(ApiTestCase):
  def picks(self, query=""):
    return [runner["ride_id"] for runner in self.data(f"/undervalued/?date={DAY}{query}")]

  def test_defaults_to_each_races_latest_snapshot(self):
    self.assertEqual(self.picks(), [3002])

  def test_at_a_given_snapshot(self):
    self.assertEqual(self.picks("&snapshot=t-1"), [3001])

  def test_shows_the_flagged_row(self):
    runner = self.data(f"/undervalued/?date={DAY}&snapshot=t-1")[0]
    self.assertEqual(runner["race"]["race_id"], TODAY_RACE)
    self.assertEqual(runner["model_value"]["snapshot"], "t-1")
    self.assertTrue(runner["model_value"]["undervalued"])

  def test_agrees_with_graphql(self):
    for rest_query, graphql_argument in [("", ""), ("&snapshot=t-1", ", snapshot: T_1"), ("&snapshot=today", ", snapshot: TODAY")]:
      result = schema.execute_sync('{ undervalued(date: "%s"%s) { rideId } }' % (DAY, graphql_argument))
      graphql_picks = [runner["rideId"] for runner in result.data["undervalued"]]
      self.assertEqual(self.picks(rest_query), graphql_picks)


class ListTests(ApiTestCase):
  def test_race_filters(self):
    data = self.data("/races/?race_type=CHASE")
    self.assertEqual(data["count"], 1)
    self.assertEqual([race["race_id"] for race in data["results"]], [PAST_RACE])
    self.assertEqual(self.data(f"/races/?date={DAY}&course_id=2")["count"], 2)
    self.assertEqual(self.data("/races/?date_from=2026-11-20")["count"], 0)

  def test_page_size_default_and_cap(self):
    # The page links carry the limit actually used.
    self.assertIn("limit=50", self.data("/runners/?offset=1")["previous"])
    self.assertIn("limit=200", self.data("/runners/?limit=100000&offset=1")["previous"])

  def test_runner_filters(self):
    self.assertEqual(self.data("/runners/?jockey_id=50")["count"], 3)
    rides = self.data("/runners/?horse_id=104")["results"]
    self.assertEqual([(ride["ride_id"], ride["race"]["name"]) for ride in rides], [(3004, "Past Handicap Chase")])

  def test_name_search(self):
    self.assertEqual([horse["horse_id"] for horse in self.data("/horses/?name=frat")["results"]], [104])
    self.assertEqual(self.get("/horses/?name=fr", status=400).json(), {"detail": "Search for at least 3 characters"})

  def test_horse_with_form_newest_first(self):
    horse = self.data("/horses/104/")
    self.assertEqual([run["course_name"] for run in horse["form"]], ["Thurles", "Naas"])

  def test_people_and_courses(self):
    self.assertEqual(self.data("/jockeys/50/"), {"jockey_id": 50, "name": "A Jockey"})
    self.assertEqual(self.data("/trainers/60/")["name"], "A Trainer")
    self.assertEqual([course["name"] for course in self.data("/courses/")], ["Lingfield", "Newcastle"])

  def test_track_record(self):
    self.assertEqual([row["bets"] for row in self.data("/scorecard/?view=after_race")], [10])
    self.assertEqual(self.data("/scorecard/?view=site_pick"), [])
    self.assertEqual([band["band_label"] for band in self.data("/calibration/")], ["0-5%"])
    self.assertEqual(self.data("/snapshot/"), {"built_at": "2026-11-19T07:30:00Z", "format_version": 1})


class HttpTests(ApiTestCase):
  def test_etag_and_cache_control(self):
    response = self.get("/courses/")
    self.assertTrue(response["ETag"].startswith('W/"'))
    self.assertIn("public", response["Cache-Control"])
    self.assertIn("max-age=300", response["Cache-Control"])
    self.assertIn("Accept", response["Vary"])

  def test_not_modified_without_touching_the_racing_tables(self):
    etag = self.get(f"/meetings/?date={DAY}")["ETag"]
    with CaptureQueriesContext(connections[SNAPSHOT_DB]) as queries:
      response = self.get(f"/meetings/?date={DAY}", status=304, HTTP_IF_NONE_MATCH=etag)
    self.assertEqual(response.content, b"")
    self.assertEqual(response["ETag"], etag)
    self.assertEqual([query["sql"] for query in queries if "snapshot_info" not in query["sql"]], [])

  def test_a_new_snapshot_changes_the_etag(self):
    etag = self.get("/courses/")["ETag"]
    models.SnapshotInfo.objects.update(built_at="2026-11-20T07:30:00Z")
    response = self.get("/courses/", HTTP_IF_NONE_MATCH=etag)
    self.assertNotEqual(response["ETag"], etag)

  def test_html_and_json_have_different_etags(self):
    json_etag = self.get("/courses/")["ETag"]
    html = self.client.get(f"{API}/courses/", HTTP_ACCEPT="text/html")
    self.assertEqual(html.status_code, 200)
    self.assertNotEqual(html["ETag"], json_etag)

  def test_errors_are_not_cached(self):
    response = self.get("/races/1/", status=404)
    self.assertNotIn("ETag", response)
    self.assertNotIn("Cache-Control", response)

  def test_read_only(self):
    response = self.client.post(f"{API}/courses/", {}, HTTP_ACCEPT="application/json")
    self.assertEqual(response.status_code, 405)

  def test_root_and_docs(self):
    self.assertIn("meetings", self.data("/"))
    self.assertEqual(self.client.get(f"{API}/docs/").status_code, 200)
    schema_response = self.client.get(f"{API}/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json")
    self.assertEqual(schema_response.status_code, 200)
    self.assertIn(f"{API}/meetings/", schema_response.json()["paths"])


class RateLimitTests(ApiTestCase):
  def limited_to(self, rate):
    # DRF reads the rate once, at import, so patch the throttle class itself.
    return mock.patch.object(AnonRateThrottle, "THROTTLE_RATES", {"anon": rate})

  def test_over_the_limit_is_429_with_retry_after(self):
    with self.limited_to("2/min"):
      self.get("/courses/")
      self.get("/courses/")
      response = self.get("/courses/", status=429)
    self.assertIn("Retry-After", response)
    self.assertNotIn("ETag", response)

  def test_counted_per_ip(self):
    with self.limited_to("1/min"):
      self.get("/courses/", REMOTE_ADDR="10.0.0.1")
      self.get("/courses/", status=429, REMOTE_ADDR="10.0.0.1")
      self.get("/courses/", REMOTE_ADDR="10.0.0.2")

  def test_forwarded_for_is_ignored_without_a_proxy(self):
    with self.limited_to("1/min"):
      self.get("/courses/", HTTP_X_FORWARDED_FOR="1.1.1.1")
      self.get("/courses/", status=429, HTTP_X_FORWARDED_FOR="2.2.2.2")

  def test_behind_one_proxy_the_forwarded_client_is_counted(self):
    with self.limited_to("1/min"), mock.patch.object(api_settings, "NUM_PROXIES", 1):
      self.get("/courses/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="1.1.1.1")
      self.get("/courses/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="2.2.2.2")
      self.get("/courses/", status=429, REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="1.1.1.1")
