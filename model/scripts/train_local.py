"""Dry run of the training job from your machine: same code, real data from
Athena, but the model JSON and report are only written locally. Nothing is
published and current.json is never changed.

  python scripts/train_local.py [out dir]      (from model/; default local-runs/)

Try a change to the inputs before putting it in inputs.py: the inputs as they
are (the baseline) and the changed set are both fitted and tested on the same
weeks, and the report says whether the change helps or is within noise.

  python scripts/train_local.py --drop has_jockey
  python scripts/train_local.py --add "rating_sq=rating_diff * rating_diff"
  python scripts/train_local.py --add "a=..." --add "b=..." --drop c [out dir]

--add NAME=SQL also replaces an existing input of that name. The SQL runs
against runner_features in Athena, so a new column must be in the live table.

Needs AWS credentials for the data-jockey profile.
"""

import argparse
import sys
from pathlib import Path

MODEL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODEL_ROOT))

import boto3  # noqa: E402

from data_jockey_model.run import compare_inputs, run  # noqa: E402

PROFILE = "data-jockey"
REGION = "eu-west-2"


def parse_add(value: str) -> tuple[str, str]:
  name, separator, sql = value.partition("=")
  if not separator or not name.strip() or not sql.strip():
    raise argparse.ArgumentTypeError(f"expected NAME=SQL, got {value!r}")
  return name.strip(), sql.strip()


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("out_dir", nargs="?", default="local-runs")
  parser.add_argument("--add", action="append", type=parse_add, default=[], metavar="NAME=SQL")
  parser.add_argument("--drop", action="append", default=[], metavar="NAME")
  args = parser.parse_args()

  session = boto3.Session(profile_name=PROFILE, region_name=REGION)
  account_id = session.client("sts").get_caller_identity()["Account"]
  bucket = f"data-jockey-clean-{account_id}"
  athena_output = f"s3://{bucket}/tmp/athena/"

  if args.add or args.drop:
    compare_inputs(
      athena=session.client("athena"),
      s3=session.client("s3"),
      database="data_jockey",
      athena_output=athena_output,
      add=dict(args.add),
      drop=args.drop,
      local_dir=args.out_dir,
    )
    return

  run(
    athena=session.client("athena"),
    s3=session.client("s3"),
    bucket=bucket,
    database="data_jockey",
    athena_output=athena_output,
    local_dir=args.out_dir,
  )


if __name__ == "__main__":
  main()
