#!/usr/bin/env bash
# Deploy the website: the data-jockey-web stack, then the code onto the server.
#
#   ./scripts/deploy.sh        (from backend/)
#
# 0. Builds the React frontend (../frontend, npm run build) and uploads it beside the bundle.
# 1. Bundles backend/ (tracked and new files, nothing git-ignored: no .env, no
#    snapshot, no db.sqlite3) to s3://data-jockey-clean-<account>/code/web/.
# 2. `sam deploy` (instance, Elastic IP, role, security group).
# 3. Runs deploy/setup.sh on the instance through SSM Run Command, which sets up
#    a fresh box or updates a running one, then checks the site answers.
#
# Needs the data-jockey-glue stack (it owns the clean bucket the bundle goes to
# and the snapshot the site serves).
set -euo pipefail

PROFILE=data-jockey
REGION=eu-west-2
STACK=data-jockey-web
AWS=(aws --profile "$PROFILE" --region "$REGION")

cd "$(dirname "$0")/.."

account_id=$("${AWS[@]}" sts get-caller-identity --query Account --output text)
bundle_uri="s3://data-jockey-clean-${account_id}/code/web/backend.tar.gz"
snapshot_uri="s3://data-jockey-clean-${account_id}/serving/data_jockey.sqlite3"

echo "== Bundling backend/"
build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT
# Paths relative to backend/, so deploy/setup.sh sits at deploy/setup.sh in the bundle.
git ls-files --cached --others --exclude-standard -z . > "$build_dir/files"
tar -czf "$build_dir/backend.tar.gz" --null -T "$build_dir/files"
"${AWS[@]}" s3 cp "$build_dir/backend.tar.gz" "$bundle_uri" --only-show-errors
echo "Uploaded $(tr -cd '\0' < "$build_dir/files" | wc -c) files to $bundle_uri"

echo "== Building the frontend"
# The React app (../frontend) is built here and shipped as plain files; the box has no Node.
(cd ../frontend && npm ci --silent && npm run build)
tar -czf "$build_dir/site.tar.gz" -C ../frontend/dist .
site_uri="s3://data-jockey-clean-${account_id}/code/web/site.tar.gz"
"${AWS[@]}" s3 cp "$build_dir/site.tar.gz" "$site_uri" --only-show-errors

echo "== Deploying the $STACK stack"
sam deploy

output() {
  "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
instance_id=$(output InstanceId)
public_ip=$(output PublicIp)

echo "== Waiting for $instance_id to register with SSM"
for attempt in $(seq 1 60); do
  ping=$("${AWS[@]}" ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=$instance_id" \
    --query 'InstanceInformationList[0].PingStatus' --output text)
  if [ "$ping" = "Online" ]; then
    break
  fi
  if [ "$attempt" = 60 ]; then
    echo "$instance_id isn't online in SSM after 5 minutes" >&2
    exit 1
  fi
  sleep 5
done

echo "== Running deploy/setup.sh on $instance_id"
# The AWS CLI isn't on Ubuntu's AMI; the snap is AWS's own build.
python3 - "$build_dir/command.json" "$bundle_uri" "$snapshot_uri" "$public_ip" "$REGION" "$site_uri" <<'EOF'
import json
import sys

path, bundle_uri, snapshot_uri, public_ip, region, site_uri = sys.argv[1:]
commands = [
  "set -eu",
  "[ -x /snap/bin/aws ] || snap install aws-cli --classic",
  "work=$(mktemp -d)",
  f"/snap/bin/aws s3 cp {bundle_uri} $work/backend.tar.gz --region {region} --only-show-errors",
  "mkdir $work/backend",
  "tar -xzf $work/backend.tar.gz -C $work/backend",
  f"/snap/bin/aws s3 cp {site_uri} $work/site.tar.gz --region {region} --only-show-errors",
  "mkdir $work/backend/site",
  "tar -xzf $work/site.tar.gz -C $work/backend/site",
  f"bash $work/backend/deploy/setup.sh $work/backend {snapshot_uri} {public_ip}",
  "rm -rf $work",
]
with open(path, "w") as out:
  json.dump({"commands": commands, "executionTimeout": ["1800"]}, out)
EOF
command_id=$("${AWS[@]}" ssm send-command \
  --instance-ids "$instance_id" \
  --document-name AWS-RunShellScript \
  --comment "data-jockey web deploy" \
  --parameters "file://$build_dir/command.json" \
  --query Command.CommandId --output text)

status=Pending
while [[ "$status" =~ ^(Pending|InProgress|Delayed)$ ]]; do
  sleep 5
  # Not found for the first second or two after sending.
  status=$("${AWS[@]}" ssm get-command-invocation --command-id "$command_id" --instance-id "$instance_id" \
    --query Status --output text 2>/dev/null || echo Pending)
done

# Run Command keeps the last 24,000 characters of each stream.
"${AWS[@]}" ssm get-command-invocation --command-id "$command_id" --instance-id "$instance_id" \
  --query StandardOutputContent --output text
errors=$("${AWS[@]}" ssm get-command-invocation --command-id "$command_id" --instance-id "$instance_id" \
  --query StandardErrorContent --output text)
if [ "$status" != "Success" ]; then
  echo "$errors" >&2
  echo "setup.sh: $status (command $command_id)" >&2
  exit 1
fi

echo "== Deployed: http://$public_ip/"
