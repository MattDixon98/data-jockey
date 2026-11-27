"""S3 reads and writes: the current model, new versions and their reports."""

from __future__ import annotations

import json


def split_s3_uri(uri: str) -> tuple[str, str]:
  """s3://bucket/some/key -> ("bucket", "some/key")."""
  without_scheme = uri[len("s3://"):]
  bucket, _, key = without_scheme.partition("/")
  return bucket, key


def read_json(s3, bucket: str, key: str) -> dict | None:
  """The JSON object at s3://bucket/key, or None if there isn't one."""
  try:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
  except s3.exceptions.NoSuchKey:
    return None
  return json.loads(body)


def write_text(s3, bucket: str, key: str, text: str, content_type: str) -> None:
  s3.put_object(
    Bucket=bucket,
    Key=key,
    Body=text.encode("utf-8"),
    ContentType=content_type
  )


def delete(s3, bucket: str, key: str) -> None:
  """Remove s3://bucket/key (nothing happens if it isn't there)."""
  s3.delete_object(Bucket=bucket, Key=key)
