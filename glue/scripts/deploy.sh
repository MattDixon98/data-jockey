#!/usr/bin/env bash
# Deploy the Glue stack, then upload the data_jockey package the job imports.
#
#   ./scripts/deploy.sh        (from glue/)
#
# `sam deploy` uploads the job script itself, but not the data_jockey package:
# that's zipped here and copied to s3://data-jockey-clean-<account>/code/, which
# the job loads with --extra-py-files (see template.yaml). The upload runs after
# the deploy because the first deploy is what creates the bucket.
set -euo pipefail

PROFILE=data-jockey
REGION=eu-west-2

cd "$(dirname "$0")/.."

sam deploy

account_id=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
package_uri="s3://data-jockey-clean-${account_id}/code/data_jockey.zip"

build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT

# data_jockey/ must be at the root of the zip so `import data_jockey` works.
python - "$build_dir/data_jockey.zip" <<'EOF'
import sys
import zipfile
from pathlib import Path

with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as package:
  for path in sorted(Path("data_jockey").rglob("*.py")):
    package.write(path)
    print(f"  {path}")
EOF

aws s3 cp "$build_dir/data_jockey.zip" "$package_uri" --profile "$PROFILE" --region "$REGION"
echo "Uploaded data_jockey to $package_uri"
