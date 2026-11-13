"""Athena queries: run one, wait for it, read the result back as a DataFrame."""

from __future__ import annotations

import io
import time

import pandas as pd

from data_jockey_model.aws.s3 import split_s3_uri

FINISHED = ("SUCCEEDED", "FAILED", "CANCELLED")


def wait_for(athena, query_id: str, poll_seconds: float = 2.0) -> dict:
  """Check on the query every few seconds until it has finished; return its final details."""
  execution = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
  while execution["Status"]["State"] not in FINISHED:
    time.sleep(poll_seconds)
    execution = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
  return execution


def query(athena, s3, sql: str, output_location: str) -> pd.DataFrame:
  """Run `sql` in Athena and return the result as a DataFrame (read from the CSV Athena writes under `output_location`)."""
  query_id = athena.start_query_execution(
    QueryString=sql,
    ResultConfiguration={"OutputLocation": output_location},
  )["QueryExecutionId"]

  execution = wait_for(athena, query_id)
  status = execution["Status"]
  if status["State"] != "SUCCEEDED":
    raise RuntimeError(f"Athena query {query_id} {status['State']}: {status.get('StateChangeReason', '')}")

  bucket, key = split_s3_uri(execution["ResultConfiguration"]["OutputLocation"])
  body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
  return pd.read_csv(io.BytesIO(body))
