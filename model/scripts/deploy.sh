#!/usr/bin/env bash
# Deploy the model stack, then build and upload the data_jockey_model wheel
# the training job imports.
#
#   ./scripts/deploy.sh        (from model/)
#
# Needs the data-jockey-glue stack deployed first: it owns the clean bucket
# the wheel, Athena results and model outputs go to.
set -euo pipefail

PROFILE=data-jockey
REGION=eu-west-2

cd "$(dirname "$0")/.."

sam deploy

account_id=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)

build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT

# A wheel, not a zip: Glue Python shell jobs take .whl/.egg in --extra-py-files.
# The file name (version 0.1.0) must match --extra-py-files in template.yaml.
python -m pip wheel . --no-deps --quiet --wheel-dir "$build_dir"
wheel=$(ls "$build_dir"/data_jockey_model-*.whl)
wheel_uri="s3://data-jockey-clean-${account_id}/code/$(basename "$wheel")"

aws s3 cp "$wheel" "$wheel_uri" --profile "$PROFILE" --region "$REGION"
echo "Uploaded $(basename "$wheel") to $wheel_uri"
