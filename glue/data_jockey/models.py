"""The win-odds models the rebuild prices runners with.

A model is the weights JSON the training job writes (see the model/
subproject): its version, the dates it was trained on, and for each input
its SQL expression over runner_features, mean, spread (std) and weight.
The rebuild reads every promoted model from S3 (the job script does the
reading; this module only checks and orders them).

Point in time: each race is priced by the newest model trained only on
races before it (trained_on.to < race_date), so a model never prices races
it learnt from, and the track record is out of sample. Races before the
first model's training ended can only use that model; they are flagged
in_sample and left out of the scorecard.
"""

REQUIRED_KEYS = ["version", "trained_on", "inputs"]
REQUIRED_INPUT_KEYS = ["name", "sql", "mean", "std", "weight"]


class ModelError(Exception):
  """A model is missing or unusable; the message says which and why."""


def check_model(model: dict, source: str) -> dict:
  missing = [key for key in REQUIRED_KEYS if key not in model]
  if missing:
    raise ModelError(f"{source}: missing {missing}")
  if "to" not in model["trained_on"]:
    raise ModelError(f"{source}: trained_on has no 'to' date")
  if not model["inputs"]:
    raise ModelError(f"{source}: no inputs")
  for item in model["inputs"]:
    missing = [key for key in REQUIRED_INPUT_KEYS if key not in item]
    if missing:
      raise ModelError(f"{source}: input {item.get('name', '?')} is missing {missing}")
    if not item["std"] > 0:
      raise ModelError(f"{source}: input {item['name']} has std {item['std']}")
  return model


def usable_models(documents: dict[str, dict]) -> list[dict]:
  """Every distinct model (by version), checked, oldest training first.

  `documents` maps where each model came from (an S3 key) to its parsed
  JSON. The same version can appear twice (current.json is a copy of the
  latest promoted model); that's expected and kept once."""
  if not documents:
    raise ModelError("no models found: run the data-jockey-train-model Glue job")

  by_version = {}
  for source, model in documents.items():
    checked = check_model(model, source)
    by_version[checked["version"]] = checked
  return sorted(by_version.values(), key=lambda model: model["trained_on"]["to"])


def date_ranges(models: list[dict]) -> list[tuple[dict, str | None, str | None]]:
  """Each model's race dates: from the end of its own training to the end of the next model's (None = open-ended)."""
  ranges = []
  for index, model in enumerate(models):
    is_first = index == 0
    is_last = index == len(models) - 1
    after = None if is_first else model["trained_on"]["to"]
    up_to = None if is_last else models[index + 1]["trained_on"]["to"]
    ranges.append((model, after, up_to))
  return ranges
