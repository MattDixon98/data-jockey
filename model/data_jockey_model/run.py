"""A full training run against AWS: query, train, then publish (or save
locally for a dry run).

S3 layout under the clean bucket (`model_prefix`, default model/):
  current.json                  the latest promoted weights
  promoted/<YYYY-MM-DD>.json    every promoted model, kept: the daily rebuild prices
                                each race with the newest one trained before it
  versions/<YYYY-MM-DD>.json    every candidate, promoted or not
  versions/<YYYY-MM-DD>.md      its report (with the blend's section)
  blend.json                    the blend (blend.py), only while one is adopted: the
                                rebuild flags on the blended probability when it's there
  blend/<YYYY-MM-DD>.json       every adopted blend, kept
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from data_jockey_model import blend as blending
from data_jockey_model import pipeline
from data_jockey_model.aws.athena import query
from data_jockey_model.aws.s3 import delete, read_json, write_text
from data_jockey_model.data import input_aliases, training_query
from data_jockey_model.inputs import INPUTS

CURRENT = "current.json"
BLEND = "blend.json"


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

  created_at = now.isoformat(timespec="seconds")
  result = pipeline.train(rows, INPUTS, aliases, current, version, created_at)
  model_json = json.dumps(result.model, indent=2) + "\n"

  # The blend learns from the races our earlier models priced out of sample.
  blend_rows = query(athena, s3, blending.blend_query(database), athena_output)
  blend = blending.train_blend(blend_rows, version, created_at)
  report = result.report + "\n" + blend.report
  print(report)

  if local_dir is not None:
    out = Path(local_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{version}.json").write_text(model_json)
    (out / f"{version}.md").write_text(report)
    if blend.blend is not None:
      (out / f"blend-{version}.json").write_text(json.dumps(blend.blend, indent=2) + "\n")
    print(f"Dry run: wrote {out / version}.json/.md (nothing published)")
    return result

  write_text(s3, bucket, f"{model_prefix}versions/{version}.json", model_json, "application/json")
  write_text(s3, bucket, f"{model_prefix}versions/{version}.md", report, "text/markdown")
  if result.promote:
    write_text(s3, bucket, f"{model_prefix}promoted/{version}.json", model_json, "application/json")
    write_text(s3, bucket, f"{model_prefix}{CURRENT}", model_json, "application/json")
  print(f"Published {version} to s3://{bucket}/{model_prefix}versions/ (promoted: {result.promote})")

  if blend.blend is not None:
    blend_json = json.dumps(blend.blend, indent=2) + "\n"
    write_text(s3, bucket, f"{model_prefix}blend/{version}.json", blend_json, "application/json")
    write_text(s3, bucket, f"{model_prefix}{BLEND}", blend_json, "application/json")
    print(f"Blend {version} published for {list(blend.blend['markets'])}")
  else:
    # A blend that no longer beats the market shouldn't keep deciding the flags.
    delete(s3, bucket, f"{model_prefix}{BLEND}")
    print("No blend adopted: blend.json removed (flags use our probability)")
  return result


def changed_inputs(base: dict[str, str], add: dict[str, str], drop: list[str]) -> dict[str, str]:
  """`base` with inputs dropped by name and added (or replaced) by name -> SQL."""
  unknown = [name for name in drop if name not in base]
  if unknown:
    raise ValueError(f"can't drop unknown inputs: {', '.join(unknown)}")
  variant = {name: sql for name, sql in base.items() if name not in drop}
  variant.update(add)
  return variant


def compare_inputs(
  athena,
  s3,
  database: str,
  athena_output: str,
  add: dict[str, str],
  drop: list[str],
  local_dir: str,
) -> pipeline.Comparison:
  """Local only: INPUTS (the baseline) against INPUTS with `add`/`drop`
  applied, on the same split. Writes a report; publishes nothing."""
  variant = changed_inputs(INPUTS, add, drop)
  aliases = input_aliases(INPUTS, variant)
  rows = query(athena, s3, training_query(database, aliases), athena_output)
  print(f"Training rows: {len(rows):,}")

  comparison, report = pipeline.compare(rows, INPUTS, variant, aliases)
  print(report)
  out = Path(local_dir)
  out.mkdir(parents=True, exist_ok=True)
  now = datetime.now(ZoneInfo("Europe/London"))
  path = out / f"compare-{now:%Y-%m-%d-%H%M%S}.md"
  path.write_text(report)
  print(f"Wrote {path} (nothing published)")
  return comparison
