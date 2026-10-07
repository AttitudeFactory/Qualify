#!/usr/bin/env bash
# Qualify deploy helper — run from the founder's Mac, from anywhere inside the repo.
#
#   deploy/deploy.sh deploy <ssh-target> [git-ref]   ship a committed ref and (re)start the stack
#   deploy/deploy.sh status <ssh-target>             containers + health checks through Caddy
#   deploy/deploy.sh logs   <ssh-target> [service]   follow logs (all services, or one)
#   deploy/deploy.sh backup <ssh-target>             pg_dump now (same script as the nightly cron)
#
# <ssh-target> is e.g. `deploy@203.0.113.10`, or a Host alias from ~/.ssh/config.
# [git-ref] defaults to `origin/main` (fetched first).
#
# What `deploy` does, in order:
#   1. `git archive` of the ref — only COMMITTED files: never your dirty working tree, never
#      .env — streamed over ssh into /opt/qualify/releases/<sha>. The server needs no GitHub
#      access and no deploy key.
#   2. FROM THAT RELEASE DIR: `docker compose build`, then `run --rm migrate` (alembic
#      upgrade head + role passwords; starts postgres first), then `up -d` ONLY if migrate
#      exited 0. migrate is an explicit step, not a depends_on of api/reflex, so a deploy
#      that changes no image recreates nothing (no 502 window). The PREVIOUS release keeps
#      serving while migrate runs (as it already did when migrate was a dependency), so
#      every migration must be backward compatible with it: expand -> contract over two
#      deploys (docs/despliegue-hetzner.md §7).
#   3. Only if that succeeded: /opt/qualify/current -> the release. A failed build or
#      migration leaves `current` (and with it `status`, `logs`, the backup cron) on the last
#      good release. Older releases stay for rollback; the last 5 are kept.
#   4. Health: /ping (Reflex), /api/connections/callback (FastAPI; 303 = reached), /login (UI).
#
# Rollback = `deploy/deploy.sh deploy <target> <previous-sha>`. Migrations are forward-only
# from the first production deploy, so a rollback across a migration needs a plan first.
set -euo pipefail

REMOTE_ROOT=${QUALIFY_REMOTE_ROOT:-/opt/qualify}
ENV_FILE=$REMOTE_ROOT/.env.prod
COMPOSE_FILE=deploy/docker-compose.prod.yml
KEEP_RELEASES=5

die() { echo "deploy.sh: $*" >&2; exit 1; }

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-1}"
}

remote() {
  ssh -o BatchMode=yes "$TARGET" "$@"
}

# `compose_in <dir>`: the compose invocation for a release directory. The project name is
# fixed in the compose file (`qualify-prod`), so any release dir drives the same stack.
# A release deployed by CI (deploy/server-deploy.sh) pins its GHCR images in
# deploy/release.env; it is passed when present, or compose would look for local images.
compose_in() {
  echo "cd $1 && docker compose --env-file $ENV_FILE \$(test -f deploy/release.env && echo --env-file deploy/release.env) -f $COMPOSE_FILE"
}
COMPOSE=$(compose_in "$REMOTE_ROOT/current")

cmd_deploy() {
  local ref="${1:-origin/main}"
  git rev-parse --git-dir >/dev/null 2>&1 || die "run me from inside the Qualify repo"
  if [[ "$ref" == origin/* ]]; then
    git fetch --quiet origin
  fi
  local sha
  sha=$(git rev-parse --verify --short=12 "${ref}^{commit}") || die "unknown ref: $ref"
  echo "==> Deploying $ref ($sha) to $TARGET"

  remote "test -f $ENV_FILE" ||
    die "$ENV_FILE is missing on the server (docs/despliegue-hetzner.md, primer despliegue)"

  local release=$REMOTE_ROOT/releases/$sha
  echo "==> Uploading release $sha"
  git archive --format=tar "$sha" | gzip -c | remote "
    set -e
    rm -rf $release
    mkdir -p $release
    tar -xzf - -C $release
    echo $sha > $release/RELEASE
  "

  echo "==> Building images, migrating, then starting the stack from $release"
  local in_release
  in_release=$(compose_in "$release")
  remote "
    set -e
    $in_release build
    $in_release run --rm -T migrate
    $in_release up -d --remove-orphans
  " || die "build, migration or start failed — $REMOTE_ROOT/current still points at the previous release"

  remote "ln -sfn $release $REMOTE_ROOT/current"
  echo "==> $REMOTE_ROOT/current -> $sha"

  echo "==> Pruning old releases (keeping $KEEP_RELEASES) and dangling images"
  remote "
    cd $REMOTE_ROOT/releases && ls -1t | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf
    docker image prune -f >/dev/null
  "

  cmd_status
}

cmd_status() {
  remote "$COMPOSE ps"
  # Exits non-zero when any probe misses its expected code, so `deploy` fails loudly. The
  # LOCAL copy of the script is piped, so `status` works even before a release carries it.
  remote "bash -s -- $ENV_FILE" <"$(git rev-parse --show-toplevel)/deploy/healthcheck.sh"
}

cmd_logs() {
  ssh -t "$TARGET" "$COMPOSE logs -f --tail=200 ${1:-}"
}

cmd_backup() {
  remote "$REMOTE_ROOT/current/deploy/backup-db.sh"
}

[[ $# -ge 1 ]] || usage
action=$1
shift
case "$action" in
  -h | --help | help) usage 0 ;;
  deploy | status | logs | backup) ;;
  *) usage ;;
esac
[[ $# -ge 1 ]] || die "missing <ssh-target> (e.g. deploy@203.0.113.10)"
TARGET=$1
shift

case "$action" in
  deploy) cmd_deploy "$@" ;;
  status) cmd_status ;;
  logs) cmd_logs "$@" ;;
  backup) cmd_backup ;;
esac
