"""The only code that talks to AWS: Athena queries (athena.py) and S3 reads
and writes (s3.py). Functions take boto3 clients, so the Glue job and the
local script can each make their own."""
