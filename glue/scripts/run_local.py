"""Build the clean tables locally from a folder of raw JSON, no AWS needed.

  python scripts/run_local.py <raw dir containing past/, today/, future/> [out dir] [--model model.json ...]

--model adds model_odds, priced with that weights JSON (repeat it for several
models, e.g. files copied from s3://data-jockey-clean-<account>/model/promoted/
or a training dry run in model/local-runs/). Without it model_odds is skipped.

Download the raw data first, e.g.:

  aws s3 sync s3://data-jockey-raw-2026-11-11/ ./raw/ --profile data-jockey

Runs the same build code as the Glue job, then writes each table as Parquet to
the out dir (Iceberg isn't needed locally) and prints row counts plus a few
sanity checks, so changes can be tried on real data before deploying. It also
writes the website's SQLite snapshot to <out dir>/data_jockey.sqlite3, as the
job does (model tables empty without --model); point the backend's
DATA_JOCKEY_SNAPSHOT at it to run the site on local data.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

GLUE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GLUE_ROOT))

from pyspark.sql import SparkSession  # noqa: E402
from pyspark.sql.functions import col  # noqa: E402

from data_jockey import build, raw_schemas, serving  # noqa: E402
from data_jockey.models import usable_models  # noqa: E402
from data_jockey.tables import TABLE_KEYS, TABLES, local_ddl  # noqa: E402


def main(raw_dir: str, out_dir: str, model_files: list[str]) -> None:
  models = None
  if model_files:
    models = usable_models({path: json.loads(Path(path).read_text()) for path in model_files})
    print(f"Pricing model_odds with {[model['version'] for model in models]}")
  else:
    print("No --model given: skipping model_odds")

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

  racecard_files = f"{raw_dir}/{{past,today,future}}/racecards/date=*/*.json"
  race_files = f"{raw_dir}/{{past,today,future}}/races/date=*/*.json"

  cards = raw_schemas.read_raw(spark, raw_schemas.RACECARD_MEETING, racecard_files)
  races = raw_schemas.read_raw(spark, raw_schemas.RACE, race_files).cache()

  spark.sql("CREATE DATABASE IF NOT EXISTS local_schema")
  for name in TABLES:
    spark.sql(local_ddl(name, "local_schema"))

  # Every table as written; tables not built (model ones without --model) stay
  # empty, like the local_schema table of the same name.
  written_tables = {name: spark.table(f"local_schema.{name}") for name in TABLES}
  for name, df in build.build_all(cards, races, models).items():
    clean = build.conform(df, spark.table(f"local_schema.{name}").schema)
    clean.write.mode("overwrite").parquet(str(out / name))

    written = spark.read.parquet(str(out / name))
    written_tables[name] = written
    rows = written.count()
    distinct_keys = written.select(*TABLE_KEYS[name]).distinct().count()

    null_cols = []
    for column in written.columns:
      has_value = col(column).isNotNull()
      if written.where(has_value).limit(1).count() == 0:
        null_cols.append(column)

    if distinct_keys == rows:
      status = "ok"
    else:
      status = f"DUPLICATE KEYS ({rows - distinct_keys})"

    line = f"{name:14} {rows:>9,} rows  keys {status}"
    if null_cols:
      line += f"  all-null: {null_cols}"
    print(line)

  snapshot = out / "data_jockey.sqlite3"
  built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
  counts = serving.write_sqlite(serving.uk_ire_tables(written_tables), str(snapshot), built_at)
  print(f"\nSQLite snapshot (UK/IRE only): {snapshot}, {snapshot.stat().st_size / 1e6:.1f} MB")
  for name, rows in counts.items():
    print(f"  {name:17} {rows:>9,} rows")

  spark.stop()


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("raw_dir")
  parser.add_argument("out_dir", nargs="?", default="local-tables")
  parser.add_argument("--model", action="append", default=[], help="weights JSON; repeatable")
  args = parser.parse_args()
  main(args.raw_dir, args.out_dir, args.model)
