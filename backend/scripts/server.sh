#!/usr/bin/env bash
# Take the web server down completely: delete the data-jockey-web stack.
#
#   ./scripts/server.sh kill     (from backend/; ./deploy web-kill)
#
# Deletes the instance, Elastic IP, role and security group, so the site costs
# nothing while it's down. Bring it back with ./deploy web (or web-start): a
# fresh instance, set up from scratch, on a NEW IP (update the domain's A
# record once there is one). The code bundle and snapshot are in the Glue
# stack's bucket and stay.
set -euo pipefail

PROFILE=data-jockey
REGION=eu-west-2
STACK=data-jockey-web
AWS=(aws --profile "$PROFILE" --region "$REGION")

if [ $# -ne 1 ] || [ "$1" != "kill" ]; then
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi

if ! "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" > /dev/null 2>&1; then
  echo "No $STACK stack: the server is already down. Bring it back with ./deploy web"
  exit 0
fi

echo "== Deleting the $STACK stack (instance, Elastic IP, role, security group)"
"${AWS[@]}" cloudformation delete-stack --stack-name "$STACK"
"${AWS[@]}" cloudformation wait stack-delete-complete --stack-name "$STACK"
echo "Deleted. Bring it back with ./deploy web (new IP)"
