"""Checking a snapshot file before it's served."""

import sqlite3
from pathlib import Path


class SnapshotError(Exception):
  pass


def check_snapshot(path: Path, format_version: int) -> str:
  """Open `path` read-only, make sure it's a whole, healthy snapshot of the
  layout the site expects, and return its built_at."""
  try:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
  except sqlite3.Error as error:
    raise SnapshotError(f"{path}: can't open ({error})")
  try:
    check = connection.execute("PRAGMA quick_check").fetchone()[0]
    if check != "ok":
      raise SnapshotError(f"{path}: integrity check failed ({check})")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != format_version:
      raise SnapshotError(f"{path}: snapshot format {version}, this site expects {format_version}")
    rows = connection.execute("SELECT built_at FROM snapshot_info").fetchall()
  except sqlite3.Error as error:
    raise SnapshotError(f"{path}: not a snapshot ({error})")
  finally:
    connection.close()
  if len(rows) != 1:
    raise SnapshotError(f"{path}: snapshot_info has {len(rows)} rows, expected 1")
  return rows[0][0]
