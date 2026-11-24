#!/usr/bin/env bash
# Build the website's images for the server (linux/arm64, a t4g) and push them to ECR.
#
#   ./scripts/push_images.sh        (from backend/)
#
# Builds web and caddy with compose.yaml alone (not the local override), tagged with
# the current git commit, plus -dirty when backend/ or frontend/ has uncommitted
# changes (the build context includes them). The repositories, data-jockey-web and
# data-jockey-caddy, are in the glue stack; each keeps its last 5 images.
# Needs Docker with arm64 emulation (Docker Desktop has it; `docker buildx ls`).
# The last line printed is IMAGE_TAG=<tag>, the tag the server should run.
set -euo pipefail

PROFILE=data-jockey
REGION=eu-west-2
AWS=(aws --profile "$PROFILE" --region "$REGION")

cd "$(dirname "$0")/.."

account_id=$("${AWS[@]}" sts get-caller-identity --query Account --output text)
registry="${account_id}.dkr.ecr.${REGION}.amazonaws.com"

tag=$(git rev-parse --short=12 HEAD)
if [ -n "$(git status --porcelain -- . ../frontend)" ]; then
  tag="${tag}-dirty"
fi

echo "== Logging in to $registry"
"${AWS[@]}" ecr get-login-password | docker login --username AWS --password-stdin "$registry"

export IMAGE_REGISTRY="$registry/"
export IMAGE_TAG="$tag"
# Compose builds every service for this platform (the frontend's Node stage still
# runs natively: it's pinned to $BUILDPLATFORM).
export DOCKER_DEFAULT_PLATFORM=linux/arm64

echo "== Building $tag (linux/arm64)"
# --pull: always start from the newest python/caddy/node base images, so OS security fixes
# (ECR's scan on push lists what's left) reach the server with the next deploy.
# --progress plain: deploy.sh pipes this script's output through tee, and compose's
# interactive progress display fails when stdout isn't a terminal ("failed to get console").
docker compose --progress plain -f compose.yaml build --pull web caddy

echo "== Pushing"
docker compose --progress plain -f compose.yaml push web caddy

echo "Pushed ${registry}/data-jockey-web:$tag and ${registry}/data-jockey-caddy:$tag"
echo "IMAGE_TAG=$tag"
