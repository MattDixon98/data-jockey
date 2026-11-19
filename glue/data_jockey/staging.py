"""Staging: every raw crawler file's text in one Iceberg table, raw_files."""

import re

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, explode, from_json
from pyspark.sql.types import ArrayType, StructType

STAGING_TABLE = "raw_files"

RAW_FILES_DDL = """
    CREATE TABLE IF NOT EXISTS {db}.raw_files (
        source_file     STRING  COMMENT 'Full S3 path of the raw file, as read_raw gives it',
        kind            STRING  COMMENT 'racecards or races',
        etag            STRING  COMMENT 'S3 ETag when staged; a different one means the file changed',
        content         STRING  COMMENT 'The whole file as JSON text, unparsed'
    ) USING iceberg
"""

# The raw files the rebuild reads: {past,today,future}/{racecards,races}/date=*/*.json
RAW_FILE_PATTERN = re.compile(r"^(?:past|today|future)/(racecards|races)/date=[^/]+/[^/]+\.json$")
PHASES = ["past/", "today/", "future/"]


def file_kind(key: str) -> str | None:
  """'racecards' or 'races' for a raw file's S3 key, None for anything else."""
  match = RAW_FILE_PATTERN.match(key)
  if match is None:
    return None
  return match.group(1)


def plan_staging(listed: dict[str, str], staged: dict[str, str]) -> tuple[list[str], list[str]]:
  """What to change in raw_files to match the bucket.

  Both arguments map source_file -> ETag: `listed` from the bucket, `staged`
  from raw_files. Returns (to_remove, to_add): the rows to delete first
  (changed or no longer in the bucket), then the files to read and add (new
  or changed). A changed file is in both.
  """
  to_remove = []
  for source_file, etag in staged.items():
    is_gone = source_file not in listed
    if is_gone or listed[source_file] != etag:
      to_remove.append(source_file)

  to_add = []
  for source_file, etag in listed.items():
    is_new = source_file not in staged
    if is_new or staged[source_file] != etag:
      to_add.append(source_file)

  return sorted(to_remove), sorted(to_add)


def parse_staged(raw_files: DataFrame, kind: str, schema: StructType) -> DataFrame:
  """One kind of staged file parsed with `schema`: the same rows and columns
  read_raw() gives from the files themselves (the schema's fields, then
  source_file). A malformed file fails the read, as in read_raw()."""
  files = raw_files.where(col("kind") == kind)
  options = {"mode": "FAILFAST"}

  # A racecard file is a JSON array of meetings (one row each); a race file
  # is one JSON object (one row).
  if kind == "racecards":
    meetings = from_json(col("content"), ArrayType(schema), options)
    records = files.select(explode(meetings).alias("record"), col("source_file"))
  else:
    race = from_json(col("content"), schema, options)
    records = files.select(race.alias("record"), col("source_file"))

  return records.select("record.*", "source_file")
