#!/usr/bin/env bash
# Backfill race data by invoking the deployed scraper Lambda once per date.
#
# Usage: scripts/backfill.sh START_DATE END_DATE [PARALLEL]
#   e.g. scripts/backfill.sh 2026-08-11 2026-11-09 3
#
# Dates whose racecard is already in S3 are skipped, so it's safe to re-run
# after a failure — it picks up where it left off.
set -euo pipefail

START=${1:?start date YYYY-MM-DD required}
END=${2:?end date YYYY-MM-DD required}
PARALLEL=${3:-3}   # concurrent Lambda runs; keep low to be polite to the source site

export AWS_PROFILE=${AWS_PROFILE:-data-jockey}
export AWS_REGION=${AWS_REGION:-eu-west-2}
STACK=data-jockey-scraper

output() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
export FUNCTION=$(output FunctionName)
export BUCKET=$(output BucketName)
echo "Function: $FUNCTION"
echo "Bucket:   $BUCKET"

scrape_date() {
  local date=$1 out error
  if aws s3api head-object --bucket "$BUCKET" \
       --key "past/racecards/date=$date/racecards.json" >/dev/null 2>&1; then
    echo "$date  skipped (already in S3)"
    return 0
  fi
  out=$(mktemp)
  # Lambda can run up to 15 min; don't let the CLI time out and retry it.
  # FunctionError is "None" on success, or e.g. "Unhandled" if the scraper threw.
  error=$(aws lambda invoke --function-name "$FUNCTION" \
    --cli-binary-format raw-in-base64-out \
    --cli-read-timeout 900 --cli-connect-timeout 30 \
    --payload "{\"date\":\"$date\"}" \
    --query FunctionError --output text "$out" 2>&1) || true
  if [[ "$error" == "None" ]]; then
    echo "$date  $(cat "$out")"
  else
    echo "$date  FAILED ($error): $(cat "$out" 2>/dev/null)"
  fi
  rm -f "$out"
}
export -f scrape_date

d=$START
while [[ ! "$d" > "$END" ]]; do
  echo "$d"
  d=$(date -I -d "$d + 1 day")
done | xargs -P "$PARALLEL" -I{} bash -c 'scrape_date {}'

echo "Backfill finished: $START to $END"
