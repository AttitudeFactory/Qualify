#!/usr/bin/env bash
# Pull-based deploy, run ON THE SERVER as the ssh forced command of the CI deploy key
# (docs/plan-sre-devops-produccion.md §5, punto 4). GitHub Actions has already built and
# pushed, tagged with the full commit sha, three images to GHCR: qualify-app, qualify-web
# and qualify-deploy (the commit's deploy/ directory, `--target deploy-bundle`). This script
# never builds and never reads anything from the ssh client but the requested sha.
#
# Installed once by the founder (it must NOT live inside a release dir, which the deploy
# itself replaces):
#
#   install -D -m 755 deploy/server-deploy.sh /opt/qualify/bin/server-deploy.sh
#
# and wired in ~deploy/.ssh/authorized_keys, one line:
#
#   command="/opt/qualify/bin/server-deploy.sh",restrict ssh-ed25519 AAAA... qualify-ci-deploy
#
# Trust boundary: the key can only ask for `deploy <40-hex sha>`, and the release's compose
# file and scripts come from qualify-deploy:<sha> in GHCR — so the key can only deploy a
# commit that CI published. Publishing to GHCR takes write access to the repository, which
# can already change what production runs.
#
# Steps: pull the 3 images -> release dir from qualify-deploy (staged, then moved into place)
# -> `run --rm -T migrate` -> `up -d` (only if migrate exited 0) -> /opt/qualify/current ->
# health checks. Any failure exits non-zero and leaves `current` where it was. Rollback =
# deploy an older sha whose images are still in GHCR.
set -euo pipefail

ROOT=${QUALIFY_REMOTE_ROOT:-/opt/qualify}
ENV_FILE=$ROOT/.env.prod
IMAGE_PREFIX=${QUALIFY_IMAGE_PREFIX:-ghcr.io/attitudefactory/}
KEEP_RELEASES=5

die() { echo "server-deploy: $*" >&2; exit 1; }

# Under a forced command the requested command arrives in SSH_ORIGINAL_COMMAND; run by hand,
# it arrives as arguments.
read -r -a request <<<"${SSH_ORIGINAL_COMMAND:-$*}"
[[ ${#request[@]} -eq 2 && ${request[0]} == deploy ]] || die "usage: deploy <40-hex commit sha>"
sha=${request[1]}
[[ $sha =~ ^[0-9a-f]{40}$ ]] || die "not a full commit sha: $sha"
[[ -f $ENV_FILE ]] || die "$ENV_FILE is missing"
# CI publishes qualify-app and qualify-web only. qualify-render joins with punto 6 of the
# plan; until then a stack with the `render` profile is deployed with `just deploy`.
profiles=$( (grep -E '^COMPOSE_PROFILES=' "$ENV_FILE" || true) | tail -n 1 | cut -d= -f2-)
[[ ,$profiles, != *,render,* ]] ||
  die "COMPOSE_PROFILES enables render, whose image CI does not publish yet — use \`just deploy\`"

echo "==> Pulling ${IMAGE_PREFIX}qualify-{app,web,deploy}:$sha"
for image in qualify-app qualify-web qualify-deploy; do
  docker pull --quiet "$IMAGE_PREFIX$image:$sha" >/dev/null
done

release=$ROOT/releases/$sha
if [[ -d $release ]]; then
  # Same sha, same bundle: reuse it. Never delete it first — `current` may point at it.
  echo "==> Release $sha already on disk, reusing it"
else
  echo "==> Release $sha"
  staging=$ROOT/releases/.incoming-$sha
  rm -rf "$staging"
  mkdir -p "$staging"
  cid=$(docker create "${IMAGE_PREFIX}qualify-deploy:$sha" /none)
  docker cp "$cid:/deploy" "$staging/deploy" >/dev/null || { docker rm "$cid" >/dev/null; die "no deploy/ in the bundle"; }
  docker rm "$cid" >/dev/null
  [[ -f $staging/deploy/docker-compose.prod.yml ]] || die "the bundle holds no deploy/docker-compose.prod.yml"
  echo "$sha" >"$staging/RELEASE"
  # The release pins its images in deploy/release.env, a SECOND env file (the later one
  # wins) that every compose invocation on this release must pass — deploy.sh and the
  # runbook's `dc` alias do, when it exists. Without it a later `up` would look for
  # qualify-app:latest and build on the server.
  printf 'QUALIFY_IMAGE_PREFIX=%s\nQUALIFY_IMAGE_TAG=%s\n' "$IMAGE_PREFIX" "$sha" \
    >"$staging/deploy/release.env"
  mv "$staging" "$release"
fi

dc() {
  (cd "$release" && docker compose --env-file "$ENV_FILE" --env-file deploy/release.env \
    -f deploy/docker-compose.prod.yml "$@")
}

echo "==> Migrating"
dc run --rm -T migrate
echo "==> Starting"
dc up -d --no-build --remove-orphans

ln -sfn "$release" "$ROOT/current"
echo "==> $ROOT/current -> $sha"

(cd "$ROOT/releases" && ls -1t | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf)
docker image prune -f >/dev/null

"$release/deploy/healthcheck.sh" "$ENV_FILE"
