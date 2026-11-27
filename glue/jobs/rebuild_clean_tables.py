"""Glue job: rebuild the clean Iceberg tables from the raw JSON.

First brings the staging table raw_files up to date with the raw bucket: only
new and changed files are read from S3 (data_jockey.staging). Then it reads
every racecard and race file under past/, today/ and future/ from there,
parsed with the explicit schemas, builds the tables (data_jockey.build, which picks the most
trusted snapshot of each race) and replaces each table's contents in a single
Iceberg commit, so Athena never sees a half-written table. Tables are created
from data_jockey.tables on the first run; a column added to the DDL later has
to be added to the live table with ALTER TABLE ... ADD COLUMNS, and the job
fails until it is.

model_odds is priced with the promoted win-odds models the training job
publishes under --model_location (promoted/*.json and current.json). If they
can't be loaded, every other table is still rebuilt, model_odds keeps its
previous rows, and the job fails at the end saying why.

Last, it writes the serving snapshot: the UK/IRE rows of the tables the website
uses, read back from Iceberg as committed, as one SQLite file
(data_jockey.serving), uploaded to --snapshot_location for the web server to
pick up. It's written even when model_odds failed, so results and racecards
still reach the site.

Needs the data_jockey package on the path (--extra-py-files on Glue).
"""

import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.conf import SparkConf
from pyspark.context import SparkContext
from pyspark.sql.functions import lit

from data_jockey import build, raw_schemas, serving, staging
from data_jockey.models import ModelError, usable_models
from data_jockey.tables import TABLES, ddl_columns

CATALOG = "glue_catalog"

args = getResolvedOptions(
  sys.argv,
  [
    "JOB_NAME",
    "raw_bucket",
    "warehouse",
    "database",
    "model_location",
    "snapshot_location",
    "restage_raw",
  ],
)

# Raw files fetched at once while staging, and per append to raw_files.
FETCH_THREADS = 32
STAGE_BATCH = 2000

def read_models(location: str) -> list[dict]:
  """Every promoted model under `location` (s3://bucket/model/): promoted/*.json plus current.json, checked and ordered."""
  bucket, prefix = location[len("s3://"):].split("/", 1)
  s3 = boto3.client("s3")

  keys = [f"{prefix}current.json"]
  for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"{prefix}promoted/"):
    for item in page.get("Contents", []):
      if item["Key"].endswith(".json"):
        keys.append(item["Key"])

  documents = {}
  for key in keys:
    source = f"s3://{bucket}/{key}"
    try:
      body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except s3.exceptions.NoSuchKey:
      continue
    try:
      documents[source] = json.loads(body)
    except json.JSONDecodeError as error:
      raise ModelError(f"{source}: not valid JSON ({error})")
  return usable_models(documents)


def list_raw_files(bucket: str) -> dict[str, str]:
  """Every raw racecard and race file in the bucket: source_file (s3://bucket/key, as read_raw names it) -> ETag."""
  s3 = boto3.client("s3")
  paginator = s3.get_paginator("list_objects_v2")
  listed = {}
  for phase in staging.PHASES:
    for page in paginator.paginate(Bucket=bucket, Prefix=phase):
      for item in page.get("Contents", []):
        key = item["Key"]
        if staging.file_kind(key) is not None:
          listed[f"s3://{bucket}/{key}"] = item["ETag"]
  return listed


def fetch_raw_file(s3, source_file: str) -> dict[str, str]:
  """One raw file as a raw_files row."""
  bucket, key = source_file.removeprefix("s3://").split("/", 1)
  response = s3.get_object(Bucket=bucket, Key=key)
  content = response["Body"].read().decode("utf-8")
  return {
    "source_file": source_file,
    "kind": staging.file_kind(key),
    # The ETag of what was actually read, in case the file changed since the listing.
    "etag": response["ETag"],
    "content": content,
  }


def stage_raw_files(staging_table: str, raw_bucket: str, restage: bool) -> None:
  """Bring raw_files up to date with the raw bucket (data_jockey.staging): remove changed and deleted files, then read and add new and changed ones."""
  if restage:
    spark.sql(f"DELETE FROM {staging_table}")

  listed = list_raw_files(raw_bucket)
  staged = {}
  staged_rows = spark.table(staging_table).select(
    "source_file", "etag"
  ).collect()
  for row in staged_rows:
    staged[row.source_file] = row.etag
  to_remove, to_add = staging.plan_staging(listed, staged)
  print(f"Raw files: {len(listed)} in the bucket, {len(staged)} staged; removing {len(to_remove)}, adding {len(to_add)}")

  if to_remove:
    removed_rows = []
    for source_file in to_remove:
      removed_rows.append((source_file,))
    removed = spark.createDataFrame(removed_rows, "source_file STRING")
    removed.createOrReplaceTempView("raw_files_to_remove")
    spark.sql(
      f"MERGE INTO {staging_table} AS staged USING raw_files_to_remove AS removed "
      f"ON staged.source_file = removed.source_file WHEN MATCHED THEN DELETE"
    )

  # One client shared by the threads (boto3 clients are safe to share; creating them isn't).
  s3 = boto3.client("s3")
  # Small files, so many at once; a batch at a time so the driver never holds them all.
  schema = spark.table(staging_table).schema
  with ThreadPoolExecutor(max_workers=FETCH_THREADS) as pool:
    for start in range(0, len(to_add), STAGE_BATCH):
      batch = to_add[start:start + STAGE_BATCH]
      fetches = []
      for source_file in batch:
        fetches.append(pool.submit(fetch_raw_file, s3, source_file))
      rows = []
      for fetch in fetches:
        rows.append(fetch.result())
      spark.createDataFrame(rows, schema).writeTo(staging_table).append()
      print(f"Staged {start + len(batch)} of {len(to_add)}")

  # Exactly one row per file in the bucket, or the rebuild would read stale or missing data.
  check = spark.table(staging_table).selectExpr("count(*) AS row_count", "count(DISTINCT source_file) AS file_count").first()
  if check.row_count != len(listed) or check.file_count != len(listed):
    raise RuntimeError(
      f"{staging_table} has {check.row_count} rows for {check.file_count} files, but the bucket has {len(listed)}: "
      f"rerun with --restage_raw true"
    )


conf = (
  SparkConf()
  .set("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
  .set(f"spark.sql.catalog.{CATALOG}", "org.apache.iceberg.spark.SparkCatalog")
  .set(f"spark.sql.catalog.{CATALOG}.catalog-impl", "org.apache.iceberg.aws.glue.GlueCatalog")
  .set(f"spark.sql.catalog.{CATALOG}.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
  .set(f"spark.sql.catalog.{CATALOG}.warehouse", args["warehouse"])
  # Race dates are calendar dates; keep them from shifting with the cluster's zone.
  .set("spark.sql.session.timeZone", "UTC")
  # Plan text (for the UI/listeners, built on every write) is uncapped by default, and the
  # model tables' plans are long (model_odds has one scoring branch per promoted model;
  # build_all checkpoints them, see keep=). Same cap as tests/conftest.py; only the
  # description is cut, results are the same.
  .set("spark.sql.maxPlanStringLength", "1m")
)

sc = SparkContext.getOrCreate(conf=conf)
sc.setLogLevel("WARN")
glue_context = GlueContext(sc)
spark = glue_context.spark_session
job = Job(glue_context)
job.init(args["JOB_NAME"], args)

# Read the models first, but hold any problem until the end: results,
# racecards and the rest should still update without them.
models = None
model_error = None
try:
  models = read_models(args["model_location"])
  print(f"Models: {[model['version'] for model in models]}")
except (ModelError, ClientError) as error:
  model_error = error
  print(f"Models not loaded, model_odds will be skipped: {error}")

db = f"{CATALOG}.{args['database']}"

# Every snapshot (past/, today/ and future/ t-N files), read from the staged
# copy rather than thousands of small files on S3.
staging_table = f"{db}.{staging.STAGING_TABLE}"
spark.sql(staging.RAW_FILES_DDL.format(db=db))
restage = args["restage_raw"].lower() == "true"
stage_raw_files(staging_table, args["raw_bucket"], restage)

raw_files = spark.table(staging_table)
racecards = staging.parse_staged(raw_files, "racecards", raw_schemas.RACECARD_MEETING)
races = staging.parse_staged(raw_files, "races", raw_schemas.RACE).cache()

for name, ddl in TABLES.items():
  spark.sql(ddl.format(db=db))
  # CREATE TABLE IF NOT EXISTS leaves an existing table alone, and conform()
  # follows the live schema, so a new DDL column would silently never be written.
  live_columns = spark.table(f"{db}.{name}").columns
  missing = [column for column in ddl_columns(name) if column not in live_columns]
  if missing:
    raise RuntimeError(f"{db}.{name} is missing DDL columns {missing}: ALTER TABLE ... ADD COLUMNS first")

for name, df in build.build_all(racecards, races, models, keep=build.checkpoint).items():
  table = f"{db}.{name}"
  clean = build.conform(df, spark.table(table).schema)
  # Full rebuild: replace every row in one commit (the old version stays in
  # the table's history for time travel / rollback).
  clean.writeTo(table).overwrite(lit(True))
  print(f"{table}: {spark.table(table).count()} rows")

# The serving snapshot, from the tables as committed (so a model_odds that
# kept its previous rows is exported as it stands).
committed_tables = {}
for name in TABLES:
  committed_tables[name] = spark.table(f"{db}.{name}")
served = serving.uk_ire_tables(committed_tables)

built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

# s3://bucket/serving/data_jockey.sqlite3 -> "bucket", "serving/data_jockey.sqlite3"
snapshot_location = args["snapshot_location"]
without_scheme = snapshot_location.removeprefix("s3://")
snapshot_bucket, snapshot_key = without_scheme.split("/", 1)

with tempfile.TemporaryDirectory() as scratch:
  local_snapshot = f"{scratch}/data_jockey.sqlite3"
  counts = serving.write_sqlite(served, local_snapshot, built_at)
  for name, rows in counts.items():
    print(f"snapshot {name}: {rows} rows")
  # One PUT: readers see the old file or the new one, never half of it.
  boto3.client("s3").upload_file(local_snapshot, snapshot_bucket, snapshot_key)
print(f"Snapshot built {built_at} uploaded to {args['snapshot_location']}")

job.commit()

if model_error is not None:
  raise RuntimeError(
    f"Every table was rebuilt except model_odds, which kept its previous rows: "
    f"the models couldn't be loaded from {args['model_location']}: {model_error}"
  )
