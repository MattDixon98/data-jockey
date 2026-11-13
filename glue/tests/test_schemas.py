"""Checks the explicit schemas against real crawler output (tests/fixtures).

Reading with an explicit schema fails in two ways: a wrong type makes the read
error out (caught by FAILFAST), and a misspelt field name just becomes NULL
everywhere. The second test catches that by counting non-null values per field
in Spark and in the raw JSON and requiring them to match.
"""

import json
from collections import Counter

import pytest
from pyspark.sql import Row
from pyspark.sql.types import ArrayType, StructType

from conftest import FIXTURES
from data_jockey import raw_schemas
from data_jockey.tables import TABLES, local_ddl

SOURCES = {
  "racecards": (raw_schemas.RACECARD_MEETING, sorted(FIXTURES.glob("racecards/*/*.json"))),
  "races": (raw_schemas.RACE, sorted(FIXTURES.glob("races/*/*.json"))),
}


def _non_null_counts(value, dtype, path="", counts=None) -> Counter:
  """Non-null count for every leaf field of `dtype`, walking `value` in step."""
  counts = Counter() if counts is None else counts
  if value is None:
    return counts
  if isinstance(dtype, StructType):
    for field in dtype.fields:
      child = value[field.name] if field.name in value else None
      _non_null_counts(child, field.dataType, f"{path}.{field.name}", counts)
  elif isinstance(dtype, ArrayType):
    for item in value:
      _non_null_counts(item, dtype.elementType, f"{path}[]", counts)
  else:
    counts[path] += 1
  return counts


def _as_plain(value):
  """Spark Rows -> dicts, recursively, so both sides walk the same way."""
  if isinstance(value, Row):
    return {k: _as_plain(v) for k, v in value.asDict().items()}
  if isinstance(value, list):
    return [_as_plain(v) for v in value]
  return value


@pytest.mark.parametrize("source", SOURCES)
def test_fixtures_read_with_explicit_schema(spark, source):
  schema, files = SOURCES[source]
  assert files, f"no {source} fixtures found"
  assert raw_schemas.read_raw(spark, schema, files).count() > 0


@pytest.mark.parametrize("source", SOURCES)
def test_no_field_silently_null(spark, source):
  schema, files = SOURCES[source]

  expected = Counter()
  for f in files:
    data = json.loads(f.read_text())
    for record in data if isinstance(data, list) else [data]:
      _non_null_counts(record, schema, counts=expected)

  actual = Counter()
  for row in raw_schemas.read_raw(spark, schema, files).collect():
    _non_null_counts(_as_plain(row), schema, counts=actual)

  assert actual == expected
  # Every leaf should hold data somewhere in the fixtures, otherwise the
  # comparison above proves nothing for it (e.g. a typo on both sides).
  all_leaves = set(_non_null_counts(_example_of(schema), schema))
  assert all_leaves - set(expected) == set(), "fields never populated in fixtures"


def _example_of(dtype):
  """A dummy value with every leaf filled, to list the schema's leaf paths."""
  if isinstance(dtype, StructType):
    return {f.name: _example_of(f.dataType) for f in dtype.fields}
  if isinstance(dtype, ArrayType):
    return [_example_of(dtype.elementType)]
  return 0


def test_table_ddl_is_valid(spark):
  """Runs each DDL as a plain local table (no Iceberg jar needed locally),
  which still checks the column list, types and comments parse."""
  spark.sql("CREATE DATABASE IF NOT EXISTS ddl_check")
  for name in TABLES:
    spark.sql(local_ddl(name, "ddl_check"))
    assert spark.table(f"ddl_check.{name}").columns
  spark.sql("DROP DATABASE ddl_check CASCADE")


@pytest.mark.parametrize("source", SOURCES)
def test_rows_know_their_source_file(spark, source):
  schema, files = SOURCES[source]
  df = raw_schemas.read_raw(spark, schema, files)
  source_files = [row.source_file for row in df.select("source_file").distinct().collect()]

  # Spark gives a URI (file:/..., s3://...); compare from past/ onwards.
  expected = sorted(path.relative_to(FIXTURES.parent).as_posix() for path in files)
  actual = sorted(source_file.split("/fixtures/", 1)[1] for source_file in source_files)
  assert actual == expected
