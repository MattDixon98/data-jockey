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
  aggregate,
  array_join,
  coalesce,
  concat,
  get,
  lit,
  lower,
  regexp_extract,
  regexp_replace,
  sequence,
  size,
  sqrt,
  transform,
  trim,
  upper,
  when,
)
from pyspark.sql.functions import filter as spark_filter
from pyspark.sql.functions import greatest, least
from pyspark.sql.functions import round as spark_round

YARDS_PER_MILE = 1760
YARDS_PER_FURLONG = 220
LBS_PER_STONE = 14

ODDS_PATTERN = r"^\s*(\d+)\s*/\s*(\d+)\s*$"
EVENS = ["evs", "evens", "evn"]
# The standard prices bookmakers quote, shortest first. Our own odds are
# exact (1 / probability) and get shown as the nearest of these.
ODDS_LADDER = [
  "1/10", "1/9", "1/8", "2/15", "1/7", "2/13", "1/6", "2/11", "1/5", "2/9", "1/4", "2/7", "3/10",
  "1/3", "4/11", "2/5", "4/9", "1/2", "8/15", "4/7", "8/13", "4/6", "8/11", "4/5", "5/6", "10/11",
  "Evens", "11/10", "6/5", "5/4", "11/8", "6/4", "13/8", "7/4", "15/8", "2/1", "9/4", "5/2", "11/4",
  "3/1", "10/3", "7/2", "4/1", "9/2", "5/1", "11/2", "6/1", "13/2", "7/1", "15/2", "8/1", "17/2",
  "9/1", "10/1", "11/1", "12/1", "14/1", "16/1", "18/1", "20/1", "22/1", "25/1", "28/1", "33/1",
  "40/1", "50/1", "66/1", "80/1", "100/1", "125/1", "150/1", "200/1", "250/1", "500/1",
]
DISTANCE_PATTERN = r"^\s*(\d+[mfy]\s*)+$"
TIME_PATTERN = r"^\s*(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s\s*$"
WEIGHT_PATTERN = r"^\s*(\d+)-(\d+)\s*$"
PRIZE_PATTERN = r"^\s*([\d,]+(?:\.\d+)?)(?:\s+([A-Za-z]{3}))?\s*$"

# {past|today|future}/{racecards|races}/date=YYYY-MM-DD/{name}[-t-N].json
SNAPSHOT_PATH_PATTERN = r"/(past|today|future)/(?:racecards|races)/date=[^/]+/[^/]*?(?:-t-(\d+))?\.json$"

COMPLETE_STAGES =["WEIGHEDIN", "RESULT", "FINISHED"]
ABANDONED_STAGES = ["ABANDONED", "RACEVOID"]
VALID_RACE_CLASSES = (1, 7)

# Distance bands for "has won at this sort of trip": (upper limit in yards,
# label), limits half a furlong above each band's longest trip.
DISTANCE_BANDS = [
  (1430, "5-6f"),
  (1870, "7-8f"),
  (2530, "9-11f"),
  (3190, "12-14f"),
  (4070, "15-18f"),
  (4950, "19-22f"),
]
LONGEST_DISTANCE_BAND = "23f+"
# going_shortcode -> going group. Yielding is Ireland's word for good to soft.
GOING_GROUPS = {
  "HRD": "FIRM",
  "FRM": "FIRM",
  "GF": "FIRM",
  "GD": "GOOD",
  "GS": "GOOD_TO_SOFT",
  "YLD": "GOOD_TO_SOFT",
  "SFT": "SOFT",
  "HVY": "HEAVY",
  "ST": "STANDARD",
  "STF": "STANDARD",
  "STS": "STANDARD",
  "SLW": "STANDARD",
}

# Courses' country short_name for Great Britain and Ireland.
UK_IRE_COUNTRY_CODES = ["ENG", "Scot", "Wale", "Nort", "Eire"]
# The last race-type word in a race name. Greedy `.*` makes it the last one, so
# a sponsor's word earlier in the name doesn't count. "Flat Race" is how Irish
# bumpers are named ("(Pro/Am) Flat Race"); flat-season races carry no type word.
RACE_TYPE_PATTERN = r"(?i)^.*\b(hurdles?|(?:steeple)?chase|flat race|(?:n\.?h\.?|national hunt) flat|bumper)\b"

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


def _ladder_decimal(price: str) -> float:
  if price == "Evens":
    return 2.0
  numerator, denominator = price.split("/")
  return int(numerator) / int(denominator) + 1


def fractional_odds(decimal: Column) -> Column:
  prices = []
  for ladder_price in ODDS_LADDER:
    ladder_decimal = _ladder_decimal(ladder_price)
    prices.append((ladder_decimal, ladder_price))

  price = when(decimal.isNull(), lit(None))
  for index in range(len(prices) - 1):
    this_decimal, this_price = prices[index]
    next_decimal, _ = prices[index + 1]
    halfway = (this_decimal + next_decimal) / 2
    price = price.when(decimal < halfway, lit(this_price))

  return price.otherwise(lit(ODDS_LADDER[-1]))


# Shin's method: repeats of the update for z (30 settle a real race to ~1e-13)
# and the range z is kept in, so odd prices can't push it towards 1.
SHIN_ITERATIONS = 30
SHIN_MAX_Z = 0.5


def _shin_root(implied: Column, book: Column, z: Column) -> Column:
  """sqrt(z^2 + 4(1 - z) p^2 / B): the part of Shin's formula shared by z and the probabilities."""
  return sqrt(z * z + lit(4.0) * (lit(1.0) - z) * implied * implied / book)


def shin_z(implied: Column) -> Column:
  """Shin's z for one race, from the array of its runners' 1/decimal odds.

  z is how lopsided the bookmakers' margin is: 0 spreads it evenly
  (proportional), higher takes more of it off the longshots. It has no
  closed form, so the update z = (sum of roots - 2) / (runners - 2) is
  repeated SHIN_ITERATIONS times, inside Spark (aggregate over a sequence).
  Two-runner races can't be solved this way and get 0 (proportional)."""
  book = aggregate(implied, lit(0.0), lambda total, p: total + p)
  runners = size(implied)

  def update(z: Column, _: Column) -> Column:
    roots = aggregate(implied, lit(0.0), lambda total, p: total + _shin_root(p, book, z))
    next_z = (roots - lit(2.0)) / (runners - lit(2))
    return least(greatest(next_z, lit(0.0)), lit(SHIN_MAX_Z))

  iterated = aggregate(sequence(lit(1), lit(SHIN_ITERATIONS)), lit(0.0), update)
  has_enough_runners = runners > 2

  return (
    when(has_enough_runners, iterated)
    .otherwise(lit(0.0))
  )


def shin_probability(implied: Column, book: Column, z: Column) -> Column:
  """One runner's fair win probability under Shin's method, from its 1/odds,
  the race's book (sum of 1/odds) and the race's z. The race's runners add up
  to 1 (to ~1e-13; build/model_value.py rescales away the remainder).
  z = 0 (two runners, or no margin to take off) is an even split: 1/odds over
  the book. Shin's formula gives 1/odds over sqrt(book) there, which doesn't add up to 1."""
  root = _shin_root(implied, book, z)
  shin = (root - z) / (lit(2.0) * (lit(1.0) - z))
  proportional = implied / book
  is_even_split = z == lit(0.0)

  return (
    when(is_even_split, proportional)
    .otherwise(shin)
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


def official_position(position: Column, amended_position: Column) -> Column:
  """The result after any stewards' inquiry. The source only sends amended_position for some races (e.g. 948004: Fratas finished 2nd and was awarded the race);
  when it is there it is the official placing, otherwise position is."""
  has_amendment = amended_position > 0

  return (
    when(has_amendment, amended_position)
    .otherwise(position)
  )


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


def distance_band(yards: Column) -> Column:
  """Distance in yards -> band label, e.g. 2200 (1m 2f) -> '9-11f'; NULL stays NULL."""
  band = when(yards.isNull(), lit(None))
  for upper_limit, label in DISTANCE_BANDS:
    band = band.when(yards <= upper_limit, lit(label))
  return band.otherwise(lit(LONGEST_DISTANCE_BAND))


def going_group(going_shortcode: Column) -> Column:
  """going_shortcode -> FIRM, GOOD, GOOD_TO_SOFT, SOFT, HEAVY or STANDARD (all-weather); dirt codes (FST, SLP) and anything unknown -> NULL."""
  code = upper(trim(going_shortcode))
  group = when(code.isNull(), lit(None))
  for shortcode, name in GOING_GROUPS.items():
    group = group.when(code == shortcode, lit(name))
  return group.otherwise(lit(None))


def race_type(name: Column, country_code: Column) -> Column:
  """UK/Irish race type from the race name, the source has no field for it:
  '... Handicap Hurdle' -> HURDLE, '... Novices' Chase' -> CHASE,
  '... Open NH Flat Race' / '... (Pro/Am) Flat Race' -> N_H_FLAT, no type word
  -> FLAT. Same values as horse_form.run_type. NULL outside UK/Ireland, where
  names don't follow these words (French trotting races, US 'Race 1 - Claiming')."""
  type_word = lower(regexp_extract(name, RACE_TYPE_PATTERN, 1))
  is_uk_ire = coalesce(country_code.isin(UK_IRE_COUNTRY_CODES), lit(False))
  is_known = is_uk_ire & name.isNotNull()
  is_hurdle = type_word.startswith("hurdle")
  is_chase = type_word.endswith("chase")
  is_nh_flat = type_word != ""

  return (
    when(~is_known, lit(None))
    .when(is_hurdle, lit("HURDLE"))
    .when(is_chase, lit("CHASE"))
    .when(is_nh_flat, lit("N_H_FLAT"))
    .otherwise(lit("FLAT"))
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


def snapshot(source_file: Column) -> Column:
  """Which crawl a raw file is from, by its path: 'past', 'today' or 't-N'
  (future files, N days before the race). Any other path -> NULL."""
  phase = _extract_regex(source_file, SNAPSHOT_PATH_PATTERN, 1)
  days_ahead = _extract_regex(source_file, SNAPSHOT_PATH_PATTERN, 2)
  is_future = phase == "future"
  future_snapshot = concat(lit("t-"), days_ahead)

  return (
    when(is_future, future_snapshot)
    .when(phase.isNotNull(), phase)
    .otherwise(lit(None))
  )


def snapshot_rank(snapshot_name: Column) -> Column:
  """Order of trust, lowest first: past 0, today 1, t-1 2, t-2 3, t-3 4.
  Results only exist in past; later snapshots have fresher odds and entries."""
  days_ahead = _extract_regex(snapshot_name, r"^t-(\d+)$", 1).cast("int")
  is_past = snapshot_name == "past"
  is_today = snapshot_name == "today"
  is_future = days_ahead.isNotNull()

  return (
    when(is_past, lit(0))
    .when(is_today, lit(1))
    .when(is_future, days_ahead + 1)
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
