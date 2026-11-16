"""Dry run of the training job from your machine: same code, real data from
Athena, but the model JSON and report are only written locally. Nothing is
published and current.json is never changed.

  python scripts/train_local.py [out dir]      (from model/; default local-runs/)

Needs AWS credentials for the data-jockey profile.
"""

import sys
from pathlib import Path

MODEL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODEL_ROOT))

import boto3  # noqa: E402

from data_jockey_model.run import run  # noqa: E402

PROFILE = "data-jockey"
REGION = "eu-west-2"


def main(out_dir: str) -> None:
  session = boto3.Session(profile_name=PROFILE, region_name=REGION)
  account_id = session.client("sts").get_caller_identity()["Account"]
  bucket = f"data-jockey-clean-{account_id}"
  run(
    athena=session.client("athena"),
    s3=session.client("s3"),
    bucket=bucket,
    database="data_jockey",
    athena_output=f"s3://{bucket}/tmp/athena/",
    local_dir=out_dir,
  )


if __name__ == "__main__":
  main(sys.argv[1] if len(sys.argv) > 1 else "local-runs")
