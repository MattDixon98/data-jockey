"""Glue job: rebuild the clean Iceberg tables from the raw JSON.

Reads every racecard and race file under past/, today/ and future/ with the
explicit schemas, builds the tables (data_jockey.build, which picks the most
trusted snapshot of each race) and replaces each table's contents in a single
Iceberg commit, so Athena never sees a half-written table. Tables are created
from data_jockey.tables on the first run; a column added to the DDL later has
to be added to the live table with ALTER TABLE ... ADD COLUMNS, and the job
fails until it is.

Needs the data_jockey package on the path (--extra-py-files on Glue).
"""

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.conf import SparkConf
from pyspark.context import SparkContext
from pyspark.sql.functions import lit

from data_jockey import build, raw_schemas
from data_jockey.tables import TABLES, ddl_columns

CATALOG = "glue_catalog"

args = getResolvedOptions(sys.argv, ["JOB_NAME", "raw_bucket", "warehouse", "database"])

conf = (
  SparkConf()
  .set("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
  .set(f"spark.sql.catalog.{CATALOG}", "org.apache.iceberg.spark.SparkCatalog")
  .set(f"spark.sql.catalog.{CATALOG}.catalog-impl", "org.apache.iceberg.aws.glue.GlueCatalog")
  .set(f"spark.sql.catalog.{CATALOG}.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
  .set(f"spark.sql.catalog.{CATALOG}.warehouse", args["warehouse"])
  # Race dates are calendar dates; keep them from shifting with the cluster's zone.
  .set("spark.sql.session.timeZone", "UTC")
)

sc = SparkContext.getOrCreate(conf=conf)
glue_context = GlueContext(sc)
spark = glue_context.spark_session
job = Job(glue_context)
job.init(args["JOB_NAME"], args)

db = f"{CATALOG}.{args['database']}"
raw_root = f"s3://{args['raw_bucket']}"

# Every snapshot: past/, today/ and future/ (t-1, t-2, t-3 files).
racecard_files = f"{raw_root}/{{past,today,future}}/racecards/date=*/*.json"
race_files = f"{raw_root}/{{past,today,future}}/races/date=*/*.json"

racecards = raw_schemas.read_raw(spark, raw_schemas.RACECARD_MEETING, racecard_files)
races = raw_schemas.read_raw(spark, raw_schemas.RACE, race_files).cache()

for name, ddl in TABLES.items():
  spark.sql(ddl.format(db=db))
  # CREATE TABLE IF NOT EXISTS leaves an existing table alone, and conform()
  # follows the live schema, so a new DDL column would silently never be written.
  live_columns = spark.table(f"{db}.{name}").columns
  missing = [column for column in ddl_columns(name) if column not in live_columns]
  if missing:
    raise RuntimeError(f"{db}.{name} is missing DDL columns {missing}: ALTER TABLE ... ADD COLUMNS first")

for name, df in build.build_all(racecards, races).items():
  table = f"{db}.{name}"
  clean = build.conform(df, spark.table(table).schema)
  # Full rebuild: replace every row in one commit (the old version stays in
  # the table's history for time travel / rollback).
  clean.writeTo(table).overwrite(lit(True))
  print(f"{table}: {spark.table(table).count()} rows")

job.commit()
