#!/usr/bin/env bash
# Pull-based deploy, run ON THE SERVER as the ssh forced command of the CI deploy key
# (docs/plan-sre-devops-produccion.md §5, punto 4). GitHub Actions has already built the
# images and pushed them to GHCR tagged with the full commit sha; this script never builds.
#
# Installed once by the founder (it must NOT live inside a release dir, which the deploy
# itself replaces):
#
#   install -D -m 755 deploy/server-deploy.sh /opt/qualify/bin/server-deploy.sh
#
# and wired in ~deploy/.ssh/authorized_keys, one line, so the key can do nothing else:
#
#   command="/opt/qualify/bin/server-deploy.sh",restrict ssh-ed25519 AAAA... qualify-ci-deploy
#
# Protocol: the client runs `ssh deploy@<host> deploy <40-hex sha>` and streams on stdin a
# tar.gz holding that commit's `deploy/` directory (`git archive <sha> deploy | gzip`). Only
# `deploy/` is extracted: the release dir needs the compose file and the scripts, never code.
#
# Steps: extract -> pull qualify-app + qualify-web :<sha> -> `run --rm -T migrate` -> `up -d`
# (only if migrate exited 0) -> /opt/qualify/current -> health checks. Any failure exits
# non-zero and leaves `current` on the previous release. Rollback = deploy an older sha
# whose images are still in GHCR.
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

release=$ROOT/releases/$sha
echo "==> Release $sha"
rm -rf "$release"
mkdir -p "$release"
tar -xzf - -C "$release" deploy
echo "$sha" >"$release/RELEASE"
[[ -f $release/deploy/docker-compose.prod.yml ]] || die "the archive holds no deploy/docker-compose.prod.yml"

# The release pins its images in deploy/release.env, a SECOND env file (the later one wins)
# that every compose invocation on this release must pass — deploy.sh and the runbook's
# `dc` alias do, when it exists. Without it a later `up` would look for qualify-app:latest
# and build on the server.
printf 'QUALIFY_IMAGE_PREFIX=%s\nQUALIFY_IMAGE_TAG=%s\n' "$IMAGE_PREFIX" "$sha" >"$release/deploy/release.env"
dc() {
  (cd "$release" && docker compose --env-file "$ENV_FILE" --env-file deploy/release.env \
    -f deploy/docker-compose.prod.yml "$@")
}

echo "==> Pulling ${IMAGE_PREFIX}qualify-{app,web}:$sha"
dc pull --quiet api caddy
echo "==> Migrating"
dc run --rm -T migrate
echo "==> Starting"
dc up -d --no-build --remove-orphans

ln -sfn "$release" "$ROOT/current"
echo "==> $ROOT/current -> $sha"

(cd "$ROOT/releases" && ls -1t | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf)
docker image prune -f >/dev/null

"$release/deploy/healthcheck.sh" "$ENV_FILE"
