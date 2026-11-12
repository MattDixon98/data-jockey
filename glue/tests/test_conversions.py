"""Conversion tests. Inputs are real values from the crawler output, plus the
empty and "unknown" markers the source uses.

Each case puts the raw value in a one-row DataFrame, applies the conversion's
column expression and checks what Spark returns.
"""

from decimal import Decimal

import pytest
from pyspark.sql.functions import col

from data_jockey import conversions as c

HEADGEAR_TYPE = "array<struct<symbol:string,name:string,count:bigint>>"
LIFETIME_TYPE = "array<struct<ride_id:bigint,run_count:string,win_count:string,place_count:string>>"


def convert(spark, conversion, raw, dtype="string"):
  """Apply `conversion` to a single raw value and return the result."""
  df = spark.createDataFrame([(raw,)], f"v {dtype}")
  return df.select(conversion(col("v"))).first()[0]


@pytest.mark.parametrize(
  "raw, expected",
  [
    ("9/2", 5.5),
    ("1/3", 1.3333),
    ("10/11", 1.9091),
    ("100/30", 4.3333),
    ("50/1", 51.0),
    ("Evs", 2.0),
    ("evens", 2.0),
    ("1/0", None),
    ("SP", None),
    ("", None),
    (None, None),
  ],
)
def test_odds_decimal(spark, raw, expected):
  assert convert(spark, c.odds_decimal, raw) == expected


@pytest.mark.parametrize(
  "raw, expected",
  [
    ("6f", 1320),
    ("1m", 1760),
    ("5f 110y", 1210),
    ("1m 4f 148y", 2788),
    ("2m 4f", 4400),
    ("1m 70y", 1830),
    ("2m 2f 132y", 4092),
    ("0m 0f 110y", 110),
    ("1 mile", None),
    ("", None),
    (None, None),
  ],
)
def test_distance_yards(spark, raw, expected):
  assert convert(spark, c.distance_yards, raw) == expected


@pytest.mark.parametrize(
  "raw, expected",
  [
    ("1m 45.20s", 105.2),
    ("1m 9.31s", 69.31),
    ("58.31s", 58.31),
    ("4m 2s", 242.0),
    ("", None),
    (None, None),
    ("n/a", None),
  ],
)
def test_time_seconds(spark, raw, expected):
  assert convert(spark, c.time_seconds, raw) == expected


@pytest.mark.parametrize(
  "raw, expected",
  [
    ("8-12", 124),
    ("9-2", 128),
    ("10-9", 149),
    ("0-0", None),
    ("", None),
    (None, None),
  ],
)
def test_weight_lbs(spark, raw, expected):
  assert convert(spark, c.weight_lbs, raw) == expected


@pytest.mark.parametrize(
  "raw, amount, currency",
  [
    ("1500.0 EUR", Decimal("1500.00"), "EUR"),
    ("4187.0 GBP", Decimal("4187.00"), "GBP"),
    ("29700.0 USD", Decimal("29700.00"), "USD"),
    ("1,679.5 GBP", Decimal("1679.50"), "GBP"),
    ("250.0", Decimal("250.00"), None),
    ("TBC GBP", None, None),
    ("", None, None),
    (None, None, None),
  ],
)
def test_prize(spark, raw, amount, currency):
  assert convert(spark, c.prize_amount, raw) == amount
  assert convert(spark, c.prize_currency, raw) == currency


@pytest.mark.parametrize(
  "status, position, expected",
  [
    ("RUNNER", 1, 1),
    ("RUNNER", 12, 12),
    ("RUNNER", 0, None),  # pulled up, fell, or not recorded
    ("NONRUNNER", 0, None),
    ("WITHDRAWN", 0, None),
    ("RUNNER", None, None),
  ],
)
def test_finish_position(spark, status, position, expected):
  df = spark.createDataFrame([(status, position)], "status string, position bigint")
  result = df.select(c.finish_position(col("status"), col("position"))).first()[0]
  assert result == expected


@pytest.mark.parametrize(
  "raw, expected",
  [
    ({"reason": "PulledUp"}, "PulledUp"),
    ({"reason": "UnseatedRider"}, "UnseatedRider"),
    ({}, None),
    (None, None),
  ],
)
def test_non_finisher_reason(spark, raw, expected):
  assert convert(spark, c.non_finisher_reason, raw, "struct<reason:string>") == expected


@pytest.mark.parametrize(
  "raw, expected",
  [
    ("4", 4),
    ("1", 1),
    ("7", 7),
    ("0", None),
    ("18", None),
    ("34392", None),
    ("", None),
    (None, None),
    ("A", None),
  ],
)
def test_race_class(spark, raw, expected):
  assert convert(spark, c.race_class, raw) == expected


@pytest.mark.parametrize(
  "raw, expected",
  [
    ("WEIGHEDIN", "complete"),
    ("RESULT", "complete"),
    ("FINISHED", "complete"),
    ("ABANDONED", "abandoned"),
    ("RACEVOID", "abandoned"),
    ("DORMANT", "incomplete"),
    ("OFF", "incomplete"),
    ("GOINGBEHIND", "incomplete"),
    ("", None),
    (None, None),
  ],
)
def test_result_status(spark, raw, expected):
  assert convert(spark, c.result_status, raw) == expected


@pytest.mark.parametrize(
  "raw, expected",
  [
    (
      "<p>A case of sorts can be made for all 5 but <b>RIDE LIKE A GIRL</b> continued"
      " the excellent work.</p><p><b>Kamille Au Kanada</b> next.</p>",
      "A case of sorts can be made for all 5 but RIDE LIKE A GIRL continued"
      " the excellent work. Kamille Au Kanada next.",
    ),
    ("<ol><li>First</li><li>Second</li></ol>", "First Second"),
    ("<b>A BOY NAMED SUSIE</b>'s run", "A BOY NAMED SUSIE's run"),
    ("Fish &amp; Chips&nbsp;won", "Fish & Chips won"),
    ("line one<br>line two", "line one line two"),
    ("won over C&D", "won over C&D"),
    ("<p></p>", None),
    ("", None),
    (None, None),
  ],
)
def test_strip_html(spark, raw, expected):
  assert convert(spark, c.strip_html, raw) == expected


@pytest.mark.parametrize(
  "raw, expected",
  [
    ([{"symbol": "b", "name": "Blinkers", "count": 1}], "b"),
    ([{"symbol": "b"}, {"symbol": "t"}], "b,t"),
    ([{"symbol": ""}, {"symbol": "t"}], "t"),
    ([], None),
    (None, None),
  ],
)
def test_headgear_symbols(spark, raw, expected):
  assert convert(spark, c.headgear_symbols, raw, HEADGEAR_TYPE) == expected


@pytest.mark.parametrize(
  "raw, expected",
  [
    ([{"ride_id": 1, "run_count": "23", "win_count": "9", "place_count": "16"}], (23, 9, 16)),
    ([{"run_count": "5", "win_count": "", "place_count": None}], (5, None, None)),
    ([], (None, None, None)),
    (None, (None, None, None)),
  ],
)
def test_lifetime_stat(spark, raw, expected):
  results = tuple(
    convert(spark, lambda col, f=field: c.lifetime_stat(col, f), raw, LIFETIME_TYPE)
    for field in ("run_count", "win_count", "place_count")
  )
  assert results == expected


@pytest.mark.parametrize("raw, expected", [("Good", "Good"), ("", None), ("   ", None), (None, None)])
def test_empty_to_null(spark, raw, expected):
  assert convert(spark, c.empty_to_null, raw) == expected
