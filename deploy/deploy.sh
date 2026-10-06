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
#   2. /opt/qualify/current -> that release (older releases stay for rollback; last 5 kept).
#   3. `docker compose build` + `up -d`: postgres/redis first, then the one-shot `migrate`
#      (alembic upgrade head + role passwords); api/reflex start only if it exits 0.
#   4. Health: /ping (Reflex), /api/connections/callback (FastAPI; 403 = reached), /login (UI).
#
# Rollback = `deploy/deploy.sh deploy <target> <previous-sha>`. Migrations are forward-only
# from the first production deploy, so a rollback across a migration needs a plan first.
set -euo pipefail

REMOTE_ROOT=/opt/qualify
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

COMPOSE="cd $REMOTE_ROOT/current && docker compose --env-file $ENV_FILE -f $COMPOSE_FILE"

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

  echo "==> Uploading release $sha"
  git archive --format=tar "$sha" | gzip -c | remote "
    set -e
    rm -rf $REMOTE_ROOT/releases/$sha
    mkdir -p $REMOTE_ROOT/releases/$sha
    tar -xzf - -C $REMOTE_ROOT/releases/$sha
    echo $sha > $REMOTE_ROOT/releases/$sha/RELEASE
    ln -sfn $REMOTE_ROOT/releases/$sha $REMOTE_ROOT/current
  "

  echo "==> Building images and starting the stack (migrations run first)"
  remote "
    set -e
    $COMPOSE build
    $COMPOSE up -d --remove-orphans
  "

  echo "==> Pruning old releases (keeping $KEEP_RELEASES) and dangling images"
  remote "
    cd $REMOTE_ROOT/releases && ls -1t | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf
    docker image prune -f >/dev/null
  "

  cmd_status
}

cmd_status() {
  remote "$COMPOSE ps"
  echo "==> Health (requested on the server, through Caddy)"
  # shellcheck disable=SC2016 # the script is expanded on the server, on purpose
  remote 'bash -s' <<EOF
set -u
val() { grep -E "^\$1=" $ENV_FILE | tail -n 1 | cut -d= -f2-; }
domain=\$(val QUALIFY_DOMAIN); http_port=\$(val QUALIFY_HTTP_PORT)
case "\$domain" in
  http://*) host=\${domain#http://}; base="http://\$host:\${http_port:-80}"; resolve=() ;;
  *) host=\${domain#https://}; base="https://\$host"; resolve=(--resolve "\$host:443:127.0.0.1") ;;
esac
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "\${resolve[@]}" "\$base\$1" || true; }
for _ in \$(seq 1 45); do [ "\$(code /ping)" = 200 ] && break; sleep 2; done
for path in /ping '/api/connections/callback?code=x&state=x' /login; do
  printf '  %-62s %s\n' "\$base\$path" "\$(code "\$path")"
done
EOF
  echo "  expected: /ping 200 · callback 403 (invalid state = FastAPI reached) · /login 200"
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
