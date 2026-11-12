"""Conversions from the source's display strings to clean values.

Each function takes Spark column(s) and returns a column expression built from
Spark's own functions, so everything runs inside Spark (no Python UDFs).
build.py calls these while building the tables, e.g.
`conversions.odds_decimal(ride.betting.current_odds)`.

Empty strings, unparseable values and the source's "unknown" markers (`0-0`
weight, position 0) all become NULL rather than failing the run. Formats are
the ones seen in the real crawler output.
"""

from pyspark.sql import Column
from pyspark.sql.functions import (
  array_join,
  coalesce,
  get,
  lit,
  lower,
  regexp_extract,
  regexp_replace,
  transform,
  trim,
  upper,
  when,
)
from pyspark.sql.functions import filter as spark_filter
from pyspark.sql.functions import round as spark_round

YARDS_PER_MILE = 1760
YARDS_PER_FURLONG = 220
LBS_PER_STONE = 14

ODDS_PATTERN = r"^\s*(\d+)\s*/\s*(\d+)\s*$"
EVENS = ["evs", "evens", "evn"]
DISTANCE_PATTERN = r"^\s*(\d+[mfy]\s*)+$"
TIME_PATTERN = r"^\s*(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s\s*$"
WEIGHT_PATTERN = r"^\s*(\d+)-(\d+)\s*$"
PRIZE_PATTERN = r"^\s*([\d,]+(?:\.\d+)?)(?:\s+([A-Za-z]{3}))?\s*$"

COMPLETE_STAGES = ["WEIGHEDIN", "RESULT", "FINISHED"]
ABANDONED_STAGES = ["ABANDONED", "RACEVOID"]
VALID_RACE_CLASSES = (1, 7)

# Verdicts only use <b>, <p>, <ol> and <li> and (so far) no entities; these
# cover the common ones in case that changes.
HTML_ENTITIES = {
  "&nbsp;": " ",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&amp;": "&",  # last, so "&amp;lt;" doesn't become "<"
}
BLOCK_TAG_PATTERN = r"(?i)</?\s*(p|br|div|li|ol|ul)\b[^>]*>"


def empty_to_null(value: Column) -> Column:
  """'' or whitespace -> NULL; anything else unchanged."""
  has_text = trim(value) != ""

  return (
    when(has_text, value)
    .otherwise(lit(None))
  )


def _extract_regex(value: Column, pattern: str, group: int) -> Column:
  """The text matched by capture group `group` of `pattern`, or NULL if it didn't match."""
  extracted = regexp_extract(value, pattern, group)  # '' when there's no match
  return empty_to_null(extracted)


def odds_decimal(odds: Column) -> Column:
  """Fractional odds to decimal (stake included): '9/2' -> 5.5, 'Evs' -> 2.0."""
  numerator = _extract_regex(odds, ODDS_PATTERN, 1).cast("double")
  denominator = _extract_regex(odds, ODDS_PATTERN, 2).cast("double")

  is_evens = lower(trim(odds)).isin(EVENS)
  is_fraction = denominator > 0
  decimal = spark_round(numerator / denominator + 1, 4)

  return (
    when(is_evens, lit(2.0))
    .when(is_fraction, decimal)
    .otherwise(lit(None))
  )


def _distance_part(distance: Column, unit: str) -> Column:
  """The number before `unit` ('m', 'f' or 'y') in a distance, or 0 if that unit isn't there."""
  number = _extract_regex(distance, rf"(\d+){unit}", 1).cast("int")
  return coalesce(number, lit(0))


def distance_yards(distance: Column) -> Column:
  """'1m 4f 148y' -> 2788. Any mix of miles, furlongs and yards."""
  is_distance = distance.rlike(DISTANCE_PATTERN)
  miles = _distance_part(distance, "m") * YARDS_PER_MILE
  furlongs = _distance_part(distance, "f") * YARDS_PER_FURLONG
  yards = _distance_part(distance, "y")
  total_yards = (miles + furlongs + yards).cast("int")

  return (
    when(is_distance, total_yards)
    .otherwise(lit(None))
  )


def time_seconds(time: Column) -> Column:
  """Winning time to seconds: '1m 45.20s' -> 105.2, '58.31s' -> 58.31."""
  minutes = _extract_regex(time, TIME_PATTERN, 1).cast("int")
  minutes = coalesce(minutes, lit(0))  # '58.31s' has no minutes part
  seconds = _extract_regex(time, TIME_PATTERN, 2).cast("double")

  is_time = time.rlike(TIME_PATTERN)
  total_seconds = spark_round(minutes * 60 + seconds, 2)

  return (
    when(is_time, total_seconds)
    .otherwise(lit(None))
  )


def weight_lbs(weight: Column) -> Column:
  """Stones-pounds to pounds: '8-12' -> 124. '0-0' means unknown -> NULL."""
  stones = _extract_regex(weight, WEIGHT_PATTERN, 1).cast("int")
  pounds = _extract_regex(weight, WEIGHT_PATTERN, 2).cast("int")

  lbs = stones * LBS_PER_STONE + pounds
  is_known = lbs > 0

  return (
    when(is_known, lbs)
    .otherwise(lit(None))
  )


def prize_amount(prize: Column) -> Column:
  """'1,500.0 EUR' -> 1500.00 (DECIMAL(12,2))."""
  amount = _extract_regex(prize, PRIZE_PATTERN, 1)
  without_commas = regexp_replace(amount, ",", "")
  return without_commas.cast("decimal(12,2)")


def prize_currency(prize: Column) -> Column:
  """'1500.0 EUR' -> 'EUR'; NULL if the amount isn't valid or there's no currency."""
  currency = _extract_regex(prize, PRIZE_PATTERN, 2)
  return upper(currency)


def finish_position(status: Column, position: Column) -> Column:
  """The source uses 0 for non-runners, non-finishers and positions that
  weren't recorded (common in France); all of those become NULL."""
  is_runner = status == "RUNNER"
  has_position = position > 0

  return (
    when(is_runner & has_position, position.cast("int"))
    .otherwise(lit(None))
  )


def non_finisher_reason(casualty: Column) -> Column:
  """casualty struct {'reason': 'PulledUp'} -> 'PulledUp'; {} -> NULL."""
  reason = casualty.getField("reason")
  return empty_to_null(reason)


def race_class(value: Column) -> Column:
  """'4' -> 4. UK/Irish classes run 1-7; '' (unclassified) and anything
  else (French races carry codes like '18' or '34392' here) -> NULL."""
  number = trim(value).cast("int")
  low, high = VALID_RACE_CLASSES
  is_valid_class = number.between(low, high)

  return (
    when(is_valid_class, number)
    .otherwise(lit(None))
  )


def result_status(race_stage: Column) -> Column:
  """Whether a race's result can be trusted, from the source's race_stage.

  'complete'   - result in (WEIGHEDIN, RESULT, FINISHED)
  'abandoned'  - no result will ever exist (ABANDONED, RACEVOID)
  'incomplete' - crawled before the result was in (DORMANT, OFF, ...)
  """
  stage = upper(trim(race_stage))
  is_complete = stage.isin(COMPLETE_STAGES)
  is_abandoned = stage.isin(ABANDONED_STAGES)
  has_stage = stage != ""

  return (
    when(is_complete, lit("complete"))
    .when(is_abandoned, lit("abandoned"))
    .when(has_stage, lit("incomplete"))
    .otherwise(lit(None))
  )


def strip_html(html: Column) -> Column:
  """Verdict HTML to plain text, entities decoded and whitespace collapsed."""
  # Block tags separate sentences/list items, so they become a space; inline
  # tags like <b> sit inside words ("<b>SUSIE</b>'s") and are just removed.
  text = regexp_replace(html, BLOCK_TAG_PATTERN, " ")
  text = regexp_replace(text, r"<[^>]*>", "")
  for entity, char in HTML_ENTITIES.items():
    text = regexp_replace(text, entity, char)
  text = regexp_replace(text, r"\s+", " ")
  text = trim(text)
  return empty_to_null(text)


def headgear_symbols(headgear: Column) -> Column:
  """headgear array [{'symbol': 'b'}, {'symbol': 't'}] -> 'b,t'; [] -> NULL."""
  symbols = transform(headgear, lambda item: item.getField("symbol"))
  non_empty_symbols = spark_filter(symbols, lambda symbol: symbol.isNotNull() & (symbol != ""))
  joined = array_join(non_empty_symbols, ",")
  return empty_to_null(joined)


def lifetime_stat(stats: Column, field: str) -> Column:
  """One count from horse_lifetime_stats, e.g. field='run_count'. The source
  sends a one-element list with the counts as strings; [] -> NULL."""
  first_entry = get(stats, 0)
  return first_entry.getField(field).cast("int")
