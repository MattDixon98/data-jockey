"""Glue job: rebuild the clean Iceberg tables from raw past/ JSON.

Skeleton only for now: it sets up Spark with the Iceberg catalog so the
stack can be deployed and smoke-tested. Table building comes next.
"""

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.conf import SparkConf
from pyspark.context import SparkContext

CATALOG = "glue_catalog"

args = getResolvedOptions(sys.argv, ["JOB_NAME", "raw_bucket", "warehouse", "database"])

conf = (
    SparkConf()
    .set("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
    .set(f"spark.sql.catalog.{CATALOG}", "org.apache.iceberg.spark.SparkCatalog")
    .set(f"spark.sql.catalog.{CATALOG}.catalog-impl", "org.apache.iceberg.aws.glue.GlueCatalog")
    .set(f"spark.sql.catalog.{CATALOG}.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
    .set(f"spark.sql.catalog.{CATALOG}.warehouse", args["warehouse"])
)

sc = SparkContext.getOrCreate(conf=conf)
glue_context = GlueContext(sc)
spark = glue_context.spark_session
job = Job(glue_context)
job.init(args["JOB_NAME"], args)

raw_root = f"s3://{args['raw_bucket']}/past"
print(f"Raw source: {raw_root}")
print(f"Target: {CATALOG}.{args['database']} at {args['warehouse']}")

# Smoke test: proves the role can see the catalog database.
spark.sql(f"SHOW TABLES IN {CATALOG}.{args['database']}").show()

job.commit()
