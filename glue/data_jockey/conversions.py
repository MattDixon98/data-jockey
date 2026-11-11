"""Conversions from the source's display strings to clean values.

Plain Python so they're easy to test; the job wraps them as Spark UDFs. Every
function takes the raw value (which may be None) and returns None for empty or
"unknown" input rather than raising, so one odd value never fails a run.
Formats are the ones seen in the real crawler output.
"""

import re
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser

YARDS_PER = {"m": 1760, "f": 220, "y": 1}
LBS_PER_STONE = 14

_FRACTION = re.compile(r"\s*(\d+)\s*/\s*(\d+)\s*")
_DISTANCE_PART = re.compile(r"(\d+)([mfy])")
_TIME = re.compile(r"\s*(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s\s*")
_WEIGHT = re.compile(r"\s*(\d+)-(\d+)\s*")
_EVENS = {"evs", "evens", "evn"}


def odds_to_decimal(odds: str | None) -> float | None:
    """Fractional odds to decimal (stake included): '9/2' -> 5.5, 'Evs' -> 2.0."""
    if not odds:
        return None
    if odds.strip().lower() in _EVENS:
        return 2.0
    match = _FRACTION.fullmatch(odds)
    if not match:
        return None
    numerator, denominator = int(match[1]), int(match[2])
    if denominator == 0:
        return None
    return round(numerator / denominator + 1, 4)


def distance_to_yards(distance: str | None) -> int | None:
    """'1m 4f 148y' -> 2788. Any mix of miles, furlongs and yards."""
    if not distance or not distance.strip():
        return None
    parts = distance.split()
    matches = [_DISTANCE_PART.fullmatch(p) for p in parts]
    if not all(matches):
        return None
    return sum(int(m[1]) * YARDS_PER[m[2]] for m in matches)


def time_to_seconds(time: str | None) -> float | None:
    """Winning time to seconds: '1m 45.20s' -> 105.2, '58.31s' -> 58.31."""
    if not time:
        return None
    match = _TIME.fullmatch(time)
    if not match:
        return None
    minutes = int(match[1]) if match[1] else 0
    return round(minutes * 60 + float(match[2]), 2)


def weight_to_lbs(weight: str | None) -> int | None:
    """Stones-pounds to pounds: '8-12' -> 124. '0-0' means unknown -> None."""
    if not weight:
        return None
    match = _WEIGHT.fullmatch(weight)
    if not match:
        return None
    lbs = int(match[1]) * LBS_PER_STONE + int(match[2])
    return lbs or None


def parse_prize(prize: str | None) -> tuple[Decimal | None, str | None]:
    """'1500.0 EUR' -> (Decimal('1500.00'), 'EUR')."""
    if not prize or not prize.strip():
        return None, None
    amount, _, currency = prize.strip().rpartition(" ")
    if not amount:
        # No currency given, just a number.
        amount, currency = currency, ""
    try:
        value = Decimal(amount.replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None, None
    return value, (currency.upper() or None)


def finish_position(status: str | None, position: int | None) -> int | None:
    """The source uses 0 for non-runners, non-finishers and positions that
    weren't recorded (common in France); all of those become None."""
    if status != "RUNNER" or not position or position < 0:
        return None
    return position


def non_finisher_reason(casualty: dict | None) -> str | None:
    """{'reason': 'PulledUp'} -> 'PulledUp'; {} -> None."""
    if not casualty:
        return None
    return casualty.get("reason") or None


VALID_RACE_CLASSES = range(1, 8)


def race_class(value: str | None) -> int | None:
    """'4' -> 4. UK/Irish classes run 1-7; '' (unclassified) and anything
    else (French races carry codes like '18' or '34392' here) -> None."""
    if value is None:
        return None
    value = str(value).strip()
    if not value.isdigit():
        return None
    number = int(value)
    return number if number in VALID_RACE_CLASSES else None


class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "br", "div", "li"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)


def strip_html(html: str | None) -> str | None:
    """Verdict HTML to plain text, entities decoded and whitespace collapsed."""
    if not html:
        return None
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = " ".join(unescape("".join(parser.parts)).split())
    return text or None


def headgear_symbols(headgear: list[dict] | None) -> str | None:
    """[{'symbol': 'b'}, {'symbol': 't'}] -> 'b,t'; [] -> None."""
    symbols = [h.get("symbol") for h in headgear or [] if h and h.get("symbol")]
    return ",".join(symbols) or None


def lifetime_stats(stats: list[dict] | None) -> tuple[int | None, int | None, int | None]:
    """horse_lifetime_stats -> (runs, wins, places). The source sends a
    one-element list of strings; [] -> all None."""
    if not stats:
        return None, None, None
    first = stats[0] or {}

    def as_int(key):
        value = first.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return as_int("run_count"), as_int("win_count"), as_int("place_count")
