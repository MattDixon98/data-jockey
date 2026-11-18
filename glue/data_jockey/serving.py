"""The serving snapshot: the clean tables the website uses, as one SQLite file.

The rebuild job writes it after every table is committed and uploads it to
the clean bucket (serving/data_jockey.sqlite3), where the web server picks it
up (backend: `manage.py fetch_snapshot`). Django opens it read-only, so the
file is rebuilt from scratch each day and never changed in place.

Two steps, kept apart like the rest of the package:
- `uk_ire_tables()`: pure DataFrame transformations. Only UK/IRE races and
  what hangs off them (runners, prizes, odds, model rows, the horses, jockeys
  and trainers that ran in them, and those horses' form, which can include
  races abroad). The model scorecard and calibration are already UK/IRE only.
  runner_features (model inputs) is left out: the site shows model_value.
- `write_sqlite()`: writes the DataFrames to a local SQLite file.

Column names and order are the clean tables' own (tables.py). SQLite types:
integers and booleans (0/1) are INTEGER, doubles and decimals REAL, strings and
dates (ISO, YYYY-MM-DD) TEXT, arrays JSON TEXT. Each table's primary key is its
TABLE_KEYS, plus the indexes in INDEXES for the lookups the site makes.
"""

import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from pyspark.sql import DataFrame
from pyspark.sql.functions import col
from pyspark.sql.types import (
  BooleanType,
  DataType,
  DecimalType,
  DoubleType,
  FloatType,
  IntegerType,
  LongType,
  ShortType,
)

from data_jockey.conversions import UK_IRE_COUNTRY_CODES
from data_jockey.tables import TABLE_KEYS

# Bump when the snapshot's layout changes in a way the site has to know about.
FORMAT_VERSION = 1

# Tables in the snapshot, in write order.
SERVED_TABLES = [
  "courses",
  "meetings",
  "races",
  "runners",
  "horses",
  "jockeys",
  "trainers",
  "prizes",
  "horse_form",
  "odds_snapshots",
  "odds_history",
  "model_odds",
  "model_value",
  "model_scorecard",
  "model_calibration",
]

# Tables whose rows belong to one race: kept when the race is UK/IRE.
RACE_TABLES = ["runners", "prizes", "odds_snapshots", "odds_history", "model_odds", "model_value"]

# Secondary indexes (the primary key already covers lookups on its first column).
INDEXES: dict[str, list[list[str]]] = {
  "meetings": [["meeting_date"], ["course_id"]],
  "races": [["race_date", "race_time"], ["meeting_id"], ["course_id"]],
  "runners": [["race_id"], ["horse_id", "race_date"], ["jockey_id"], ["trainer_id"], ["race_date"]],
  "horse_form": [["race_id"]],
  "odds_snapshots": [["race_id"]],
  "odds_history": [["race_id"]],
  "model_odds": [["race_id", "snapshot"]],
  "model_value": [["race_id", "snapshot"], ["race_date", "undervalued"]],
}

INSERT_BATCH = 5000


def uk_ire_tables(tables: dict[str, DataFrame]) -> dict[str, DataFrame]:
  """The served tables, cut down to UK/IRE racing. Takes every clean table by name (runner_features isn't needed)."""
  is_uk_ire = col("country_code").isin(UK_IRE_COUNTRY_CODES)

  courses = tables["courses"].where(is_uk_ire)
  races = tables["races"].where(is_uk_ire)
  race_ids = races.select("race_id")

  served = {
    "courses": courses,
    "meetings": tables["meetings"].join(courses.select("course_id"), "course_id", "left_semi"),
    "races": races,
  }
  for name in RACE_TABLES:
    served[name] = tables[name].join(race_ids, "race_id", "left_semi")

  runners = served["runners"]
  # Kept when they appear in the kept runners: (table, its key on runners).
  runner_tables = [("horses", "horse_id"), ("jockeys", "jockey_id"), ("trainers", "trainer_id")]
  for name, key in runner_tables:
    ids = runners.select(key).where(col(key).isNotNull()).distinct()
    served[name] = tables[name].join(ids, key, "left_semi")
  served["horse_form"] = tables["horse_form"].join(served["horses"].select("horse_id"), "horse_id", "left_semi")

  served["model_scorecard"] = tables["model_scorecard"]
  served["model_calibration"] = tables["model_calibration"]

  # The joins can reorder columns; keep each table's own order.
  return {name: served[name].select(*tables[name].columns) for name in SERVED_TABLES}


def convert_type(data_type: DataType) -> str:
  if isinstance(data_type, (LongType, IntegerType, ShortType, BooleanType)):
    return "INTEGER"
  if isinstance(data_type, (DoubleType, FloatType, DecimalType)):
    return "REAL"
  return "TEXT"


def convert_value(value):
  if value is None:
    return None
  if isinstance(value, bool):
    return int(value)
  if isinstance(value, (date, datetime)):
    return value.isoformat()
  if isinstance(value, Decimal):
    return float(value)
  if isinstance(value, list):
    return json.dumps(value)
  return value


def create_table_sql(name: str, df: DataFrame) -> str:
  columns = [f"  {field.name} {convert_type(field.dataType)}" for field in df.schema.fields]
  primary_key = f"  PRIMARY KEY ({', '.join(TABLE_KEYS[name])})"
  body = ",\n".join(columns + [primary_key])
  return f"CREATE TABLE {name} (\n{body}\n)"


def create_index_sql(name: str, columns: list[str]) -> str:
  index_name = f"{name}_{'_'.join(columns)}"
  return f"CREATE INDEX {index_name} ON {name} ({', '.join(columns)})"


def insert_rows(db_connection: sqlite3.Connection, name: str, df: DataFrame) -> int:
  placeholders = ", ".join("?" for _ in df.columns)
  insert = f"INSERT INTO {name} ({', '.join(df.columns)}) VALUES ({placeholders})"

  count = 0
  batch = []
  sorted_df = df.orderBy(*TABLE_KEYS[name])
  for row in sorted_df.toLocalIterator():
    values = []
    for value in row:
      values.append(convert_value(value))
    batch.append(values)

    # Every INSERT_BATCH rows, write them to SQLite (one INSERT per row,
    # each filling the ?s from that row) and start a new batch.
    batch_is_full = len(batch) == INSERT_BATCH
    if batch_is_full:
      db_connection.executemany(insert, batch)
      count += len(batch)
      batch = []

  # The rows left over after the last full batch.
  db_connection.executemany(insert, batch)
  count += len(batch)
  return count


def write_sqlite(tables: dict[str, DataFrame], path: str, built_at: str) -> dict[str, int]:
  missing = []
  for name in SERVED_TABLES:
    if name not in tables:
      missing.append(name)
  if missing:
    raise ValueError(f"Snapshot needs every served table; missing {missing}")

  target = Path(path)
  target.unlink(missing_ok=True)
  db_connection = sqlite3.connect(target)
  try:
    # A file built once and then only read: no journal needed while writing.
    db_connection.execute("PRAGMA journal_mode = OFF")
    db_connection.execute("PRAGMA synchronous = OFF")
    db_connection.execute(f"PRAGMA user_version = {FORMAT_VERSION}")

    counts = {}
    for name in SERVED_TABLES:
      df = tables[name]
      db_connection.execute(create_table_sql(name, df))
      counts[name] = insert_rows(db_connection, name, df)
      for columns in INDEXES.get(name, []):
        db_connection.execute(create_index_sql(name, columns))

    db_connection.execute("CREATE TABLE snapshot_info (built_at TEXT PRIMARY KEY, format_version INTEGER)")
    db_connection.execute("INSERT INTO snapshot_info VALUES (?, ?)", (built_at, FORMAT_VERSION))
    db_connection.commit()

    # Query planner statistics, then compact the file.
    db_connection.execute("ANALYZE")
    db_connection.commit()
    db_connection.execute("VACUUM")

    check = db_connection.execute("PRAGMA integrity_check").fetchone()[0]
    if check != "ok":
      raise RuntimeError(f"SQLite integrity check failed on {path}: {check}")
  finally:
    db_connection.close()
  return counts