"""Glue job: rebuild the clean Iceberg tables from raw past/ JSON.

Reads every racecard and race file under past/ with the explicit schemas,
builds the tables (data_jockey.build) and replaces each table's contents in a
single Iceberg commit, so Athena never sees a half-written table. Tables are
created from data_jockey.tables on the first run.

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
from data_jockey.tables import TABLES

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
raw_root = f"s3://{args['raw_bucket']}/past"


def read_raw(kind: str, schema):
  return (
    spark.read.schema(schema)
    .option("multiLine", "true")
    # One malformed file should fail the run, not silently drop a race.
    .option("mode", "FAILFAST")
    .json(f"{raw_root}/{kind}/date=*/*.json")
  )


racecards = read_raw("racecards", raw_schemas.RACECARD_MEETING)
races = read_raw("races", raw_schemas.RACE).cache()

for name, ddl in TABLES.items():
  spark.sql(ddl.format(db=db))

for name, df in build.build_all(racecards, races).items():
  table = f"{db}.{name}"
  clean = build.conform(df, spark.table(table).schema)
  # Full rebuild: replace every row in one commit (the old version stays in
  # the table's history for time travel / rollback).
  clean.writeTo(table).overwrite(lit(True))
  print(f"{table}: {spark.table(table).count()} rows")

job.commit()
