"""Explicit read schemas for the raw crawler JSON.

Spark is given these instead of inferring a schema (and instead of a Glue
crawler), so a change in the source format shows up as nulls or a failed read
rather than a silently different table. Only the fields the clean tables use
are listed; everything else in the files is ignored.

Types follow the real files, which don't always match the TypeScript models in
crawlers/src/models (e.g. official_rating and bha are numbers, not strings).
"""

from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import col
from pyspark.sql.types import (
  ArrayType,
  BooleanType,
  DoubleType,
  LongType,
  StringType,
  StructField,
  StructType,
)


def _ref() -> StructType:
  """The `{ "id": 123 }` reference objects used throughout the source."""
  return StructType([StructField("id", LongType())])


def _struct(**fields) -> StructType:
  return StructType([StructField(name, dtype) for name, dtype in fields.items()])


S = StringType()
L = LongType()
B = BooleanType()

CASUALTY = _struct(reason=S)

COURSE = _struct(
  course_reference=_ref(),
  name=S,
  country=_struct(country_reference=_ref(), short_name=S, long_name=S),
  feed_source=S,
)

RACECARD_RACE = _struct(
  meeting_summary_reference=_ref(),
  race_summary_reference=_ref(),
  name=S,
  course_name=S,
  course_shortcode=S,
  course_surface=_struct(surface=S),
  age=S,
  race_class=S,
  distance=S,
  date=S,
  time=S,
  off_time=S,
  winning_time=S,
  ride_count=L,
  race_stage=S,
  going=S,
  going_shortcode=S,
  has_handicap=B,
  # Only the racecard carries the verdict; the race file doesn't.
  verdict=S,
)

# past/racecards/date=*/racecards.json: a JSON array, one element per meeting.
RACECARD_MEETING = _struct(
  meeting_summary=_struct(
    meeting_reference=_ref(),
    date=S,
    course=COURSE,
    going=S,
    surface_summary=S,
    weather=S,
  ),
  races=ArrayType(RACECARD_RACE),
)

PREVIOUS_RESULT = _struct(
  race_id=L,
  date=S,
  time=S,
  course_name=S,
  course_shortcode=S,
  distance=S,
  run_type=S,
  weight=S,
  casualty=CASUALTY,
  position=L,
  runner_count=L,
  bha=L,
  race_class=S,
  race_name=S,
  going=S,
  going_shortcode=S,
  odds=S,
)

HORSE = _struct(
  horse_reference=_ref(),
  name=S,
  slug=S,
  age=L,
  foaled=S,
  sex=_struct(type=S),
  last_ran_days=L,
  previous_results=ArrayType(PREVIOUS_RESULT),
)

RIDE = _struct(
  ride_reference=_ref(),
  cloth_number=L,
  draw_number=L,
  finish_position=L,
  ride_status=S,
  casualty=CASUALTY,
  handicap=S,
  official_rating=L,
  owner=_struct(name=S),
  trainer=_struct(business_reference=_ref(), name=S, slug=S),
  jockey=_struct(person_reference=_ref(), name=S),
  headgear=ArrayType(_struct(symbol=S, name=S, count=L)),
  betting=_struct(
    favourite=_struct(betting_favourite=S),
    current_odds=S,
    historical_odds=ArrayType(S),
  ),
  horse_lifetime_stats=ArrayType(
    _struct(ride_id=L, run_count=S, win_count=S, place_count=S)
  ),
  insights=ArrayType(_struct(type=S)),
  horse=HORSE,
)

# past/races/date=*/<race id>.json: one JSON object per race.
RACE = _struct(
  race_summary=_struct(
    meeting_summary_reference=_ref(),
    race_summary_reference=_ref(),
    name=S,
    age=S,
    course_name=S,
    course_surface=_struct(surface=S),
    date=S,
    time=S,
    off_time=S,
    winning_time=S,
    distance=S,
    going=S,
    race_class=S,
    race_stage=S,
    ride_count=L,
    has_handicap=B,
  ),
  prizes=_struct(prize=ArrayType(_struct(position=L, prize=S))),
  betting_forecast=S,
  on_course_book_percentage=DoubleType(),
  number_of_placed_rides=L,
  rides=ArrayType(RIDE),
)


def read_raw(spark: SparkSession, schema: StructType, paths: str | list[str] | list[Path]) -> DataFrame:
  """Read raw crawler JSON with one of the schemas above.

  `paths` is a glob (e.g. "s3://bucket/past/races/date=*/*.json") or a list of
  files. Each file is a single JSON document, and one malformed file fails the
  read rather than silently dropping a race.

  Adds `source_file`, the full path of the file each row came from: the
  snapshot (past, today, t-1...) is only in the path, not in the JSON.
  """
  if isinstance(paths, list):
    paths = [str(path) for path in paths]

  raw = (
    spark.read.schema(schema)
    .option("multiLine", "true")
    .option("mode", "FAILFAST")
    .json(paths)
  )
  source_file = col("_metadata.file_path")
  return raw.withColumn("source_file", source_file)
