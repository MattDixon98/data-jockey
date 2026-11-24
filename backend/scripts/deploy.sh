#!/usr/bin/env bash
# Deploy the website: the data-jockey-web stack, then the code onto the server.
#
#   ./scripts/deploy.sh        (from backend/)
#
# 1. Builds the site's images (web, caddy: Django, the React app, Caddy) for
#    linux/arm64 and pushes them to ECR, tagged with the git commit
#    (scripts/push_images.sh).
# 2. Uploads the server bundle (compose.yaml + deploy/setup.sh) to
#    s3://data-jockey-clean-<account>/code/web/.
# 3. `sam deploy` (instance, Elastic IP, role, security group).
# 4. Runs deploy/setup.sh on the instance through SSM Run Command, which sets up
#    a fresh box or updates a running one (Docker, pull, compose up), then checks
#    the site answers.
#
# Needs the data-jockey-glue stack (it owns the ECR repositories, the clean bucket
# the bundle goes to and the snapshot the site serves).
set -euo pipefail

PROFILE=data-jockey
REGION=eu-west-2
STACK=data-jockey-web
# The site's domain (Porkbun; A records for it and www point at the Elastic IP).
# Passed to Caddy as SITE_DOMAIN (deploy/caddy/Caddyfile).
SITE_DOMAIN=mattdixon.uk
AWS=(aws --profile "$PROFILE" --region "$REGION")
# No pager: AWS CLI v2 pipes long output (setup.sh's log) into less, which stalls the deploy at a ':' prompt.
export AWS_PAGER=""

cd "$(dirname "$0")/.."

account_id=$("${AWS[@]}" sts get-caller-identity --query Account --output text)
registry="${account_id}.dkr.ecr.${REGION}.amazonaws.com"
bundle_uri="s3://data-jockey-clean-${account_id}/code/web/bundle.tar.gz"
snapshot_uri="s3://data-jockey-clean-${account_id}/serving/data_jockey.sqlite3"

build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT

echo "== Images"
./scripts/push_images.sh | tee "$build_dir/push.log"
image_tag=$(sed -n 's/^IMAGE_TAG=//p' "$build_dir/push.log" | tail -n 1)
if [ -z "$image_tag" ]; then
  echo "push_images.sh didn't print IMAGE_TAG=<tag>" >&2
  exit 1
fi

echo "== Uploading the server bundle"
# Everything else (code, React app, Caddyfile) is in the images.
tar -czf "$build_dir/bundle.tar.gz" compose.yaml deploy/setup.sh
"${AWS[@]}" s3 cp "$build_dir/bundle.tar.gz" "$bundle_uri" --only-show-errors

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

echo "== Running deploy/setup.sh on $instance_id ($image_tag)"
# The AWS CLI isn't on Ubuntu's AMI; the snap is AWS's own build (setup.sh uses it for ECR too).
python3 - "$build_dir/command.json" "$bundle_uri" "$snapshot_uri" "$SITE_DOMAIN,localhost" "$REGION" \
  "$SITE_DOMAIN" "$registry" "$image_tag" <<'EOF'
import json
import sys

# Django sees the bare domain through Caddy (which redirects www and drops requests to the IP),
# and localhost through the SSM tunnel to the admin (Caddy never forwards Host: localhost).
path, bundle_uri, snapshot_uri, allowed_hosts, region, site_domain, registry, image_tag = sys.argv[1:]
commands = [
  "set -eu",
  "[ -x /snap/bin/aws ] || snap install aws-cli --classic",
  "work=$(mktemp -d)",
  f"/snap/bin/aws s3 cp {bundle_uri} $work/bundle.tar.gz --region {region} --only-show-errors",
  "tar -xzf $work/bundle.tar.gz -C $work",
  f"bash $work/deploy/setup.sh $work {snapshot_uri} {allowed_hosts} {site_domain} {registry} {image_tag}",
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

echo "== Checking https://$SITE_DOMAIN/"
# Needs the domain's A records on this box's IP (they change after web-kill + web-start);
# Caddy gets the certificate once they do. A warning, not a failure: the box itself is fine.
resolved=$(python3 -c "import socket, sys; print(socket.gethostbyname(sys.argv[1]))" "$SITE_DOMAIN" 2>/dev/null || true)
if [ "$resolved" != "$public_ip" ]; then
  echo "WARNING: $SITE_DOMAIN resolves to '${resolved:-nothing}', not $public_ip." >&2
  echo "  Point the A records for $SITE_DOMAIN and www.$SITE_DOMAIN at $public_ip in Porkbun's DNS;" >&2
  echo "  Caddy gets the HTTPS certificate once they do." >&2
else
  status=000
  for attempt in $(seq 1 12); do
    status=$(curl -s -o /dev/null -w '%{http_code}' "https://$SITE_DOMAIN/api/v1/snapshot/" || true)
    if [ "$status" = "200" ]; then
      break
    fi
    sleep 5
  done
  if [ "$status" = "200" ]; then
    echo "GET https://$SITE_DOMAIN/api/v1/snapshot/ -> 200"
  else
    echo "WARNING: https://$SITE_DOMAIN/api/v1/snapshot/ -> $status; the certificate may still be on its way" >&2
    echo "  (docker compose -f /opt/data-jockey/compose.yaml logs caddy, on the box via SSM)" >&2
  fi
fi

echo "== Deployed: https://$SITE_DOMAIN/ (Elastic IP $public_ip)"
