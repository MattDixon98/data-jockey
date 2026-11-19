"""Staging: planning which raw files to (re)stage, and parsing staged text into
exactly what read_raw() reads from the files."""

import pytest
from pyspark.errors import PySparkException
from py4j.protocol import Py4JJavaError

from conftest import FIXTURES
from data_jockey import raw_schemas, staging

SCHEMAS = {"racecards": raw_schemas.RACECARD_MEETING, "races": raw_schemas.RACE}


@pytest.mark.parametrize(
  ("key", "expected"),
  [
    ("past/races/date=2026-11-10/947829.json", "races"),
    ("future/races/date=2026-11-14/946551-t-3.json", "races"),
    ("today/racecards/date=2026-11-12/racecards.json", "racecards"),
    ("past/races/date=2026-11-10/notes.txt", None),
    ("other/races/date=2026-11-10/947829.json", None),
    ("past/horses/date=2026-11-10/1.json", None),
  ],
)
def test_file_kind(key, expected):
  assert staging.file_kind(key) == expected


def test_plan_staging_adds_new_and_changed_and_removes_changed_and_gone():
  listed = {"a": "1", "b": "2-new", "c": "3", "d": "4"}
  staged = {"a": "1", "b": "2", "c": "3", "gone": "5"}
  to_remove, to_add = staging.plan_staging(listed, staged)
  assert to_remove == ["b", "gone"]
  assert to_add == ["b", "d"]


def test_plan_staging_nothing_to_do():
  files = {"a": "1", "b": "2"}
  assert staging.plan_staging(files, dict(files)) == ([], [])


def test_plan_staging_first_run_stages_everything():
  assert staging.plan_staging({"b": "2", "a": "1"}, {}) == ([], ["a", "b"])


def _fixture_files(kind):
  return sorted(FIXTURES.glob(f"*/{kind}/date=*/*.json"))


def _staged(spark, kind, files):
  """raw_files rows for `files`, with source_file as read_raw names them."""
  read_names = [
    row.source_file
    for row in raw_schemas.read_raw(spark, SCHEMAS[kind], files).select("source_file").distinct().collect()
  ]
  rows = []
  for path in files:
    relative = str(path.relative_to(FIXTURES))
    (source_file,) = [name for name in read_names if name.endswith(relative)]
    rows.append((source_file, kind, "etag", path.read_text()))
  return spark.createDataFrame(rows, "source_file string, kind string, etag string, content string")


def _sorted_rows(df):
  return sorted(df.collect(), key=lambda row: (row.source_file, str(row)))


@pytest.mark.parametrize("kind", ["racecards", "races"])
def test_parse_staged_matches_read_raw(spark, kind):
  files = _fixture_files(kind)
  assert files
  from_files = raw_schemas.read_raw(spark, SCHEMAS[kind], files)
  from_staged = staging.parse_staged(_staged(spark, kind, files), kind, SCHEMAS[kind])

  # Same columns and types (read_raw's source_file is non-nullable, staged one isn't).
  assert from_staged.schema.simpleString() == from_files.schema.simpleString()
  assert _sorted_rows(from_staged) == _sorted_rows(from_files)


def test_parse_staged_keeps_only_its_kind(spark):
  cards = _staged(spark, "racecards", _fixture_files("racecards"))
  races = _staged(spark, "races", _fixture_files("races"))
  both = cards.unionByName(races)
  parsed = staging.parse_staged(both, "races", raw_schemas.RACE)
  assert parsed.count() == races.count()


def test_parse_staged_fails_on_malformed_json(spark):
  rows = [("s3://bucket/past/races/date=2026-11-10/1.json", "races", "etag", '{"race_summary": ')]
  bad = spark.createDataFrame(rows, "source_file string, kind string, etag string, content string")
  with pytest.raises((PySparkException, Py4JJavaError)):
    staging.parse_staged(bad, "races", raw_schemas.RACE).collect()
