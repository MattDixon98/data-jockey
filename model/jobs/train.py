"""Glue Python shell job: train a candidate model and publish it.

Reads runner_features (past snapshot) from Athena, fits the weights, writes
the candidate and its report to s3://<bucket>/model/versions/ and promotes it
to model/current.json if it beats the current model on the test weeks.

Needs the data_jockey_model wheel (--extra-py-files, uploaded by
scripts/deploy.sh). Runs monthly on a schedule; see template.yaml.
"""

import sys

import boto3
from awsglue.utils import getResolvedOptions

from data_jockey_model.run import run

args = getResolvedOptions(sys.argv, ["bucket", "database", "athena_output", "model_prefix"])

run(
  athena=boto3.client("athena"),
  s3=boto3.client("s3"),
  bucket=args["bucket"],
  database=args["database"],
  athena_output=args["athena_output"],
  model_prefix=args["model_prefix"],
)
