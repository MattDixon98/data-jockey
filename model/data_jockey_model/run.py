"""A full training run against AWS: query, train, then publish (or save
locally for a dry run).

S3 layout under the clean bucket (`model_prefix`, default model/):
  current.json                  the weights the daily rebuild scores with
  versions/<YYYY-MM-DD>.json    every candidate, promoted or not
  versions/<YYYY-MM-DD>.md      its report
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from data_jockey_model import pipeline
from data_jockey_model.aws.athena import query
from data_jockey_model.aws.s3 import read_json, write_text
from data_jockey_model.data import input_aliases, training_query
from data_jockey_model.inputs import INPUTS

CURRENT = "current.json"


def run(
  athena,
  s3,
  bucket: str,
  database: str,
  athena_output: str,
  model_prefix: str = "model/",
  local_dir: str | None = None,
) -> pipeline.TrainingResult:
  """Train a candidate and compare it with the current model.

  Publishes to S3 (and promotes it to current.json if it wins) unless
  `local_dir` is given, in which case the JSON and report are only written
  there: a dry run that never changes what the rebuild scores with."""
  now = datetime.now(ZoneInfo("Europe/London"))
  version = f"{now:%Y-%m-%d}"

  current = read_json(s3, bucket, f"{model_prefix}{CURRENT}")
  # The current model's inputs (name -> SQL), so the query fetches them too
  # and both models can be scored on the same races. Empty on the first run.
  current_inputs = {}
  if current is not None:
    for item in current["inputs"]:
      current_inputs[item["name"]] = item["sql"]

  aliases = input_aliases(INPUTS, current_inputs)

  rows = query(athena, s3, training_query(database, aliases), athena_output)
  print(f"Training rows: {len(rows):,}")

  result = pipeline.train(rows, INPUTS, aliases, current, version, now.isoformat(timespec="seconds"))
  model_json = json.dumps(result.model, indent=2) + "\n"
  print(result.report)

  if local_dir is not None:
    out = Path(local_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{version}.json").write_text(model_json)
    (out / f"{version}.md").write_text(result.report)
    print(f"Dry run: wrote {out / version}.json/.md (nothing published)")
    return result

  write_text(s3, bucket, f"{model_prefix}versions/{version}.json", model_json, "application/json")
  write_text(s3, bucket, f"{model_prefix}versions/{version}.md", result.report, "text/markdown")
  if result.promote:
    write_text(s3, bucket, f"{model_prefix}{CURRENT}", model_json, "application/json")
  print(f"Published {version} to s3://{bucket}/{model_prefix}versions/ (promoted: {result.promote})")
  return result
