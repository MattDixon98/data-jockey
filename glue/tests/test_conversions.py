"""Conversion tests. Inputs are real values from the crawler output, plus the
empty and "unknown" markers the source uses."""

from decimal import Decimal

import pytest

from data_jockey import conversions as c


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
def test_odds_to_decimal(raw, expected):
    assert c.odds_to_decimal(raw) == expected


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
        ("1 mile", None),
        ("", None),
        (None, None),
    ],
)
def test_distance_to_yards(raw, expected):
    assert c.distance_to_yards(raw) == expected


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
def test_time_to_seconds(raw, expected):
    assert c.time_to_seconds(raw) == expected


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
def test_weight_to_lbs(raw, expected):
    assert c.weight_to_lbs(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1500.0 EUR", (Decimal("1500.00"), "EUR")),
        ("4187.0 GBP", (Decimal("4187.00"), "GBP")),
        ("29700.0 USD", (Decimal("29700.00"), "USD")),
        ("1,679.5 GBP", (Decimal("1679.50"), "GBP")),
        ("250.0", (Decimal("250.00"), None)),
        ("TBC GBP", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_prize(raw, expected):
    assert c.parse_prize(raw) == expected


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
def test_finish_position(status, position, expected):
    assert c.finish_position(status, position) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ({"reason": "PulledUp"}, "PulledUp"),
        ({"reason": "UnseatedRider"}, "UnseatedRider"),
        ({}, None),
        (None, None),
    ],
)
def test_non_finisher_reason(raw, expected):
    assert c.non_finisher_reason(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("4", 4), ("1", 1), ("7", 7), ("0", None), ("18", None), ("34392", None), ("", None), (None, None), ("A", None)],
)
def test_race_class(raw, expected):
    assert c.race_class(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "<p>A case of sorts can be made for all 5 but <b>RIDE LIKE A GIRL</b> continued"
            " the excellent work.</p><p><b>Kamille Au Kanada</b> next.</p>",
            "A case of sorts can be made for all 5 but RIDE LIKE A GIRL continued"
            " the excellent work. Kamille Au Kanada next.",
        ),
        ("Fish &amp; Chips&nbsp;won", "Fish & Chips won"),
        ("line one<br>line two", "line one line two"),
        ("<p></p>", None),
        ("", None),
        (None, None),
    ],
)
def test_strip_html(raw, expected):
    assert c.strip_html(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ([{"symbol": "b", "name": "Blinkers", "count": 1}], "b"),
        ([{"symbol": "b"}, {"symbol": "t"}], "b,t"),
        ([], None),
        (None, None),
    ],
)
def test_headgear_symbols(raw, expected):
    assert c.headgear_symbols(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ([{"ride_id": 1, "run_count": "23", "win_count": "9", "place_count": "16"}], (23, 9, 16)),
        ([{"run_count": "5", "win_count": "", "place_count": None}], (5, None, None)),
        ([], (None, None, None)),
        (None, (None, None, None)),
    ],
)
def test_lifetime_stats(raw, expected):
    assert c.lifetime_stats(raw) == expected
