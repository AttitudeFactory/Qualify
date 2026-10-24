#!/usr/bin/env bash
# Pull-based deploy, run ON THE SERVER as the ssh forced command of the CI deploy key
# (docs/plan-sre-devops-produccion.md §5, punto 4). GitHub Actions has already built and
# pushed, tagged with the full commit sha, four images to GHCR: qualify-app, qualify-web,
# qualify-deploy (the commit's deploy/ directory, `--target deploy-bundle`) and
# qualify-render (packages/render). This script never builds and never reads anything from
# the ssh client but the requested sha.
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
# Requests: `deploy <40-hex sha>`, or `rollback <40-hex sha>` = the same without `migrate`.
# A rollback across a migration needs it: the older image does not know the database's
# newer revision and `alembic upgrade head` fails with "Can't locate revision" (verified).
# Rolling back is only safe because migrations are expand -> contract: the previous code
# must run on the newer schema.
#
# Trust boundary: the key can only ask for one of those two, and the release's compose
# file and scripts come from qualify-deploy:<sha> in GHCR — so the key can only deploy a
# commit that CI published. Publishing to GHCR takes write access to the repository, which
# can already change what production runs.
#
# Steps: pull the images (qualify-render only when COMPOSE_PROFILES enables `render`) ->
# release dir from qualify-deploy (staged, then moved into place) -> `run --rm -T migrate`
# (skipped by `rollback`) -> `up -d` (only if migrate exited 0) -> /opt/qualify/current ->
# render healthy (when on) -> health checks. A failure BEFORE `up` (pull, bundle, migrate) exits
# non-zero with the running stack and `current` untouched. After `up` the new release is
# live and `current` points at it — so `dc` commands match what runs — and a failed health
# check exits non-zero: recover by deploying (or rolling back to) the previous sha.
set -euo pipefail

ROOT=${QUALIFY_REMOTE_ROOT:-/opt/qualify}
ENV_FILE=$ROOT/.env.prod
IMAGE_PREFIX=${QUALIFY_IMAGE_PREFIX:-ghcr.io/attitudefactory/}
KEEP_RELEASES=5
# Image sets (app/web/deploy/render) kept on disk: the live release and the one before it,
# so a rollback to the previous sha needs no pull. Older release dirs stay (they are a few
# KB and `ls releases/` is how the runbook finds a sha); rolling back to one of those pulls
# its images from GHCR again, which the script does first anyway.
KEEP_IMAGES=2

die() { echo "server-deploy: $*" >&2; exit 1; }

# A root shell over the releases dir, from the web image (Caddy on Alpine: busybox `sh`,
# `rm`) that every deploy pulls anyway. Needed to prune releases that `just deploy` from
# a Mac created: that path logs in as root (the `qualify-prod` alias) and `git archive`
# lands owned by root, which this user cannot remove. First seen 2026-10-09 (deploy
# 3890922): `rm: Permission denied` × every file of two such releases, exit 123, the run
# marked failed with the app already live. No sudo on the host, no extra image.
as_root() {
  docker run --rm --entrypoint /bin/sh -v "$ROOT/releases:/releases" \
    "${IMAGE_PREFIX}qualify-web:$sha" -c "$1"
}

# Under a forced command the requested command arrives in SSH_ORIGINAL_COMMAND; run by hand,
# it arrives as arguments.
read -r -a request <<<"${SSH_ORIGINAL_COMMAND:-$*}"
[[ ${#request[@]} -eq 2 && ${request[0]} =~ ^(deploy|rollback)$ ]] ||
  die "usage: deploy|rollback <40-hex commit sha>"
action=${request[0]}
sha=${request[1]}
[[ $sha =~ ^[0-9a-f]{40}$ ]] || die "not a full commit sha: $sha"
[[ -f $ENV_FILE ]] || die "$ENV_FILE is missing"
# One CI deploy at a time on this host: the workflow serializes its own runs, this also
# covers a manual run of the forced command. (`just deploy` from the Mac does not take it.)
exec 9>"$ROOT/.deploy.lock"
flock -n 9 || die "another deploy is running on this server"
# Profiles come from .env.prod alone (compose reads COMPOSE_PROFILES from the env file).
# CI publishes qualify-render for every sha since m-24803289; it is pulled — and waited
# for after `up` — only when the profile is on, so a server without it pays nothing.
profiles=$( (grep -E '^COMPOSE_PROFILES=' "$ENV_FILE" || true) | tail -n 1 | cut -d= -f2-)
images=(qualify-app qualify-web qualify-deploy)
render=false
if [[ ,$profiles, == *,render,* ]]; then
  render=true
  images+=(qualify-render)
fi

echo "==> Pulling ${IMAGE_PREFIX}{$(IFS=,; echo "${images[*]}")}:$sha"
for image in "${images[@]}"; do
  docker pull --quiet "$IMAGE_PREFIX$image:$sha" >/dev/null || {
    [[ $image != qualify-render ]] ||
      die "no ${IMAGE_PREFIX}qualify-render:$sha in GHCR (a commit from before CI published it?):" \
        "deploy a newer sha, or take \`render\` out of COMPOSE_PROFILES first"
    die "could not pull $IMAGE_PREFIX$image:$sha"
  }
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

if [[ $action == rollback ]]; then
  echo "==> Rollback: migrate skipped (the schema stays as it is; expand -> contract)"
else
  echo "==> Migrating"
  dc run --rm -T migrate
fi
echo "==> Starting"
dc up -d --no-build --remove-orphans

ln -sfn "$release" "$ROOT/current"
echo "==> $ROOT/current -> $sha"

# Render is healthy only once its Remotion bundle is ready (the image's HEALTHCHECK asks
# /health for bundleReady), so a release whose render cannot start fails the deploy here,
# before the pruning, like any other health check. Its start period plus retries give up
# after ~90 s; wait a bit longer than that.
if $render; then
  echo "==> Waiting for render to be healthy"
  health=missing
  for _ in $(seq 1 60); do
    cid=$(dc ps -q render)
    health=$( [[ -n $cid ]] && docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" || echo missing)
    [[ $health == healthy || $health == unhealthy ]] && break
    sleep 2.5
  done
  [[ $health == healthy ]] ||
    die "render is $health after up (see \`dc logs render\`): the release is live without templates"
  echo "    render healthy"
fi

# The verdict of the deploy is the health of what is now serving — so it comes BEFORE
# the housekeeping below, which must never turn a live, healthy release into a red run.
"$release/deploy/healthcheck.sh" "$ENV_FILE"

# Prune by mtime, keeping the newest KEEP_RELEASES — and never the live one: a rollback
# reuses an old release dir, so its mtime is refreshed first and it is skipped explicitly.
# Through `as_root`: the releases a Mac-side `just deploy` made are owned by root.
# Best effort — a release that will not go is reported, not fatal.
echo "==> Pruning old releases (keeping $KEEP_RELEASES)"
touch "$release"
(cd "$ROOT/releases" && ls -1t | { grep -vxF "$sha" || true; } | tail -n +"$KEEP_RELEASES") \
  | while read -r old; do
    [[ -n $old && $old != .* ]] || continue
    as_root "rm -rf /releases/$old" && echo "    pruned $old" \
      || echo "server-deploy: WARN could not prune release $old" >&2
  done
# Images. Tagged images are not "dangling", so `image prune` alone would keep every sha ever
# deployed (qualify-app is ~2.9 GB, its /app layer ~0.5 GB unique per commit) — 10 GB of
# images measured 2026-10-24 (m-24852229). Keep only the image sets of the newest
# KEEP_IMAGES releases (the live one was touched above, so it is first); drop the tags of
# every other sha, plus the `:latest` tags a Mac-side `just deploy` builds on the server.
# `docker image rm` without -f refuses an image a container still uses, which is the guard
# for anything running; nothing outside the qualify-* repositories is named here, so
# Pedidos' and the edge proxy's images are never candidates. Volumes are never pruned.
echo "==> Pruning images (keeping the image sets of $KEEP_IMAGES releases)"
keep=$(cd "$ROOT/releases" && ls -1t | { grep -v '^\.' || true; } | head -n "$KEEP_IMAGES")
for image in qualify-app qualify-web qualify-deploy qualify-render; do
  docker image ls --format '{{.Tag}}' "$IMAGE_PREFIX$image" | while read -r tag; do
    [[ $tag =~ ^[0-9a-f]{40}$ && $tag != "$sha" ]] || continue
    grep -qxF "$tag" <<<"$keep" && continue
    docker image rm "$IMAGE_PREFIX$image:$tag" >/dev/null 2>&1 && echo "    untagged $image:${tag:0:12}" || true
  done
  docker image rm "$image:latest" >/dev/null 2>&1 && echo "    untagged $image:latest" || true
done
docker image prune -f >/dev/null || true
# BuildKit cache. CI builds in GitHub, so this cache comes from builds ON the server:
# `just deploy` (5.9 GB measured 2026-10-24) and Pedidos' local image. Entries unused for
# 24 h go; a build from the last day keeps its cache. Best effort, like everything here.
docker builder prune -f --filter until=24h >/dev/null 2>&1 || true
echo "==> Disk after pruning: $(df -h "$ROOT" | awk 'NR==2 {print $3 " used, " $4 " free (" $5 ")"}')"
