#!/usr/bin/env bash
# Run the Athena check queries against the clean tables and print the results.
#
#   ./scripts/athena_checks.sh                       (from glue/; runs every athena/*.sql)
#   ./scripts/athena_checks.sh athena/winners.sql    (just one)
#
# Query results go to the warehouse bucket's tmp/ prefix, which expires after 7 days.
set -euo pipefail

PROFILE=data-jockey
REGION=eu-west-2

cd "$(dirname "$0")/.."

account_id=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
results_uri="s3://data-jockey-clean-${account_id}/tmp/athena/"

if [ $# -gt 0 ]; then
  files=("$@")
else
  files=(athena/*.sql)
fi

for file in "${files[@]}"; do
  echo "== $file"

  query_id=$(aws athena start-query-execution \
    --query-string "$(cat "$file")" \
    --result-configuration "OutputLocation=$results_uri" \
    --profile "$PROFILE" --region "$REGION" \
    --query QueryExecutionId --output text)

  while true; do
    state=$(aws athena get-query-execution --query-execution-id "$query_id" \
      --profile "$PROFILE" --region "$REGION" \
      --query QueryExecution.Status.State --output text)
    case "$state" in
      QUEUED | RUNNING) sleep 2 ;;
      *) break ;;
    esac
  done

  if [ "$state" != "SUCCEEDED" ]; then
    aws athena get-query-execution --query-execution-id "$query_id" \
      --profile "$PROFILE" --region "$REGION" \
      --query QueryExecution.Status.StateChangeReason --output text
    exit 1
  fi

  # Print as aligned columns; the first row is the headers, NULLs come back as {}.
  aws athena get-query-results --query-execution-id "$query_id" \
    --profile "$PROFILE" --region "$REGION" --output json \
    | python -c '
import json, sys

rows = json.load(sys.stdin)["ResultSet"]["Rows"]
table = [[cell.get("VarCharValue", "NULL") for cell in row["Data"]] for row in rows]
widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
for row in table:
  print("  ".join(value.ljust(width) for value, width in zip(row, widths)))
'
  echo
done
