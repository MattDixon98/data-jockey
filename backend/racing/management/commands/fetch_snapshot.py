"""Download the serving snapshot from S3 when it has changed, and swap it in.

  python manage.py fetch_snapshot [--force]

Run every ~15 minutes on the server by a systemd timer (backend/deploy/systemd/).
Compares the S3 object's ETag with the one saved next to the file
(<snapshot>.etag) and does nothing if they match. Otherwise it downloads to a
temporary file in the same directory, checks it (integrity, format version,
snapshot_info) and moves it into place with os.replace: an atomic rename, so a
request opens either the old file or the new one, and requests already reading
the old file finish on it. Nothing restarts.

Needs DATA_JOCKEY_SNAPSHOT_S3_URI and AWS credentials (the instance role on the
server; locally e.g. AWS_PROFILE=data-jockey).
"""

import os
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from racing.snapshot import SnapshotError, check_snapshot


def split_s3_uri(uri: str) -> tuple[str, str]:
  if not uri.startswith("s3://") or "/" not in uri[len("s3://"):]:
    raise CommandError(f"Not an s3://bucket/key URI: {uri!r}")
  bucket, key = uri[len("s3://"):].split("/", 1)
  return bucket, key


def write_atomically(path: Path, text: str) -> None:
  temp = path.with_name(f"{path.name}.tmp")
  temp.write_text(text)
  os.replace(temp, path)


class Command(BaseCommand):
  help = "Download the serving snapshot from S3 if it has changed and swap it in atomically."

  def add_arguments(self, parser):
    parser.add_argument("--force", action="store_true", help="download even if the ETag hasn't changed")

  def handle(self, *args, force=False, **options):
    if not settings.SNAPSHOT_S3_URI:
      raise CommandError("DATA_JOCKEY_SNAPSHOT_S3_URI isn't set")
    bucket, key = split_s3_uri(settings.SNAPSHOT_S3_URI)
    path = Path(settings.SNAPSHOT_PATH)
    etag_file = path.with_name(f"{path.name}.etag")

    s3 = boto3.client("s3", region_name=settings.AWS_REGION)
    try:
      etag = s3.head_object(Bucket=bucket, Key=key)["ETag"]
    except ClientError as error:
      raise CommandError(f"Can't read {settings.SNAPSHOT_S3_URI}: {error}")

    if not force and path.exists() and etag_file.exists() and etag_file.read_text() == etag:
      self.stdout.write(f"Up to date ({etag})")
      return

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = path.with_name(f".{path.name}.{uuid.uuid4().hex}.download")
    try:
      # IfMatch: if the object is replaced between the HEAD and here, fail
      # rather than save the new file under the old ETag; the next run gets it.
      s3.download_file(bucket, key, str(temp_file), ExtraArgs={"IfMatch": etag})
      built_at = check_snapshot(temp_file, settings.SNAPSHOT_FORMAT_VERSION)
      # Readable by the web server whatever user it runs as.
      temp_file.chmod(0o644)
      os.replace(temp_file, path)
    except (ClientError, SnapshotError) as error:
      raise CommandError(f"Snapshot not updated: {error}")
    finally:
      temp_file.unlink(missing_ok=True)

    # After the swap: if this is lost, the next run just downloads it again.
    write_atomically(etag_file, etag)
    self.stdout.write(f"Swapped in the snapshot built {built_at} ({etag}, {path.stat().st_size / 1e6:.1f} MB)")
