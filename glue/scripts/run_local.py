"""Build the clean tables locally from a folder of raw JSON, no AWS needed.

  python scripts/run_local.py <raw dir containing past/> [out dir]

Download the raw data first, e.g.:

  aws s3 sync s3://data-jockey-raw-2026-11-11/past/ ./raw/past/ --profile data-jockey

Runs the same build code as the Glue job, then writes each table as Parquet to
the out dir (Iceberg isn't needed locally) and prints row counts plus a few
sanity checks, so changes can be tried on real data before deploying.
"""

import re
import sys
from pathlib import Path

GLUE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GLUE_ROOT))

from pyspark.sql import SparkSession  # noqa: E402
from pyspark.sql.functions import col  # noqa: E402

from data_jockey import build, raw_schemas  # noqa: E402
from data_jockey.tables import TABLES  # noqa: E402

KEYS = {
  "courses": ["course_id"],
  "meetings": ["meeting_id"],
  "races": ["race_id"],
  "runners": ["ride_id"],
  "horses": ["horse_id"],
  "jockeys": ["jockey_id"],
  "trainers": ["trainer_id"],
  "prizes": ["race_id", "position"],
  "horse_form": ["horse_id", "race_id"],
}


def main(raw_dir: str, out_dir: str) -> None:
  out = Path(out_dir).resolve()
  spark = (
    SparkSession.builder.master("local[*]")
    .appName("data-jockey-local")
    .config("spark.ui.enabled", "false")
    .config("spark.driver.memory", "4g")
    .config("spark.sql.session.timeZone", "UTC")
    .config("spark.sql.warehouse.dir", str(out / "_warehouse"))
    .getOrCreate()
  )
  spark.sparkContext.setLogLevel("ERROR")

  def read(kind, schema):
    return (
      spark.read.schema(schema)
      .option("multiLine", "true")
      .option("mode", "FAILFAST")
      .json(f"{raw_dir}/past/{kind}/date=*/*.json")
    )

  cards = read("racecards", raw_schemas.RACECARD_MEETING)
  races = read("races", raw_schemas.RACE).cache()

  spark.sql("CREATE DATABASE IF NOT EXISTS local_schema")
  for name, df in build.build_all(cards, races).items():
    ddl = re.sub(r"USING iceberg.*", "USING parquet", TABLES[name].format(db="local_schema"), flags=re.S)
    spark.sql(ddl)
    clean = build.conform(df, spark.table(f"local_schema.{name}").schema)
    clean.write.mode("overwrite").parquet(str(out / name))

    written = spark.read.parquet(str(out / name))
    rows = written.count()
    distinct_keys = written.select(*KEYS[name]).distinct().count()

    null_cols = []
    for column in written.columns:
      has_value = col(column).isNotNull()
      if written.where(has_value).limit(1).count() == 0:
        null_cols.append(column)

    if distinct_keys == rows:
      status = "ok"
    else:
      status = f"DUPLICATE KEYS ({rows - distinct_keys})"

    line = f"{name:11} {rows:>9,} rows  keys {status}"
    if null_cols:
      line += f"  all-null: {null_cols}"
    print(line)

  spark.stop()


if __name__ == "__main__":
  if len(sys.argv) < 2:
    sys.exit(__doc__)
  main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "local-tables")
