#!/usr/bin/env bash
# Qualify deploy helper — run from the founder's Mac, from anywhere inside the repo.
#
#   deploy/deploy.sh deploy <ssh-target> [git-ref]   ship a committed ref and (re)start the stack
#   deploy/deploy.sh status <ssh-target>             containers + health checks through Caddy
#   deploy/deploy.sh logs   <ssh-target> [service]   follow logs (all services, or one)
#   deploy/deploy.sh backup <ssh-target>             pg_dump now (same script as the nightly cron)
#   deploy/deploy.sh env-push <ssh-target> [--dry-run] KEY...
#                                                    copy KEYs from your local .env into .env.prod
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
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
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

# Keys env-push refuses, with the command that does change them correctly.
env_push_refusal() {
  case "$1" in
    QUALIFY_DB_*_PASSWORD) echo "a role password is applied by \`migrate\` (ALTER ROLE): edit .env.prod and \`just deploy\`" ;;
    QUALIFY_DEV_FERNET_KEY) echo "rotating the credential master key makes every stored OAuth credential undecryptable" ;;
    QUALIFY_PUBLIC_URL) echo "it is baked into the static frontend: edit .env.prod and \`just deploy\` (rebuild)" ;;
    COMPOSE_* | QUALIFY_IMAGE_*) echo "it changes the shape of the stack, not a secret: edit .env.prod and \`just deploy\`" ;;
  esac
}

# Runs ON THE SERVER: $1 = .env.prod, $2 = 1 for a dry run, stdin = KEY=VALUE lines. Values
# travel only over the ssh channel's stdin — never argv (visible in `ps`), never a terminal.
# shellcheck disable=SC2016  # expanded remotely
ENV_PUSH_REMOTE='
set -euo pipefail
env_file=$1 dry=$2
umask 077
payload=$(mktemp) out=""
trap '\''rm -f "$payload" ${out:+"$out"}'\'' EXIT
cat >"$payload"
fp() { printf %s "$1" | sha256sum | cut -c1-8; }
while IFS= read -r line; do
  key=${line%%=*} new=${line#*=}
  old=$( (grep -E "^${key}=" "$env_file" || true) | tail -n 1 | cut -d= -f2-)
  if ! grep -qE "^${key}=" "$env_file"; then state="add      (new $(fp "$new"))"
  elif [ "$old" = "$new" ]; then state="same     ($(fp "$new"))"
  else state="change   ($(fp "$old") -> $(fp "$new"))"; fi
  printf "  %-34s %s\n" "$key" "$state"
done <"$payload"
[ "$dry" = 1 ] && { echo "==> Dry run: .env.prod untouched"; exit 0; }
backup=$env_file.bak-$(date -u +%Y%m%dT%H%M%SZ)
cp -p "$env_file" "$backup"
out=$(mktemp "$env_file.XXXXXX")
awk -F= '\''
  NR == FNR { i = index($0, "="); val[substr($0, 1, i - 1)] = substr($0, i + 1); next }
  ($1 in val) { print $1 "=" val[$1]; done[$1] = 1; next }
  { print }
  END { for (k in val) if (!(k in done)) print k "=" val[k] }
'\'' "$payload" "$env_file" >"$out"
chmod --reference="$env_file" "$out"
chown --reference="$env_file" "$out"
mv "$out" "$env_file"
out=""
ls -1t "$env_file".bak-* | tail -n +11 | xargs -r rm -f
echo "==> .env.prod written (backup: $backup)"
'

cmd_env_push() {
  local dry=0
  if [[ "${1:-}" == --dry-run ]]; then
    dry=1
    shift
  fi
  [[ $# -ge 1 ]] || die "usage: env-push <ssh-target> [--dry-run] KEY..."

  # Your local .env: the checkout's own, else the main checkout's (worktrees have none).
  local src=${QUALIFY_ENV_SOURCE:-}
  if [[ -z $src ]]; then
    src=$(git rev-parse --show-toplevel)/.env
    [[ -f $src ]] || src=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/.env
  fi
  [[ -f $src ]] || die "no local env file at $src (set QUALIFY_ENV_SOURCE)"

  local payload="" key value why
  for key in "$@"; do
    [[ $key =~ ^[A-Z_][A-Z0-9_]*$ ]] || die "not an env var name: $key"
    why=$(env_push_refusal "$key")
    [[ -z $why ]] || die "refusing $key — $why"
    # Last occurrence wins, as in python-dotenv. Surrounding quotes and a CR are stripped.
    value=$( (grep -E "^${key}=" "$src" || true) | tail -n 1 | cut -d= -f2- | tr -d '\r')
    value=${value#\"}; value=${value%\"}; value=${value#\'}; value=${value%\'}
    [[ -n $value ]] || die "$key is missing or empty in $src"
    payload+="$key=$value"$'\n'
  done

  echo "==> $([[ $dry == 1 ]] && echo "Dry run: ")$# key(s) from $src -> $TARGET:$ENV_FILE"
  # The script itself is not secret; base64 keeps it one shell word whatever the login shell.
  printf %s "$payload" |
    remote "bash -c \"\$(echo $(printf %s "$ENV_PUSH_REMOTE" | base64 | tr -d '\n') | base64 -d)\" env-push $ENV_FILE $dry"
  [[ $dry == 1 ]] && return

  # Compose hashes the env_file into each service's config: `up` recreates exactly the
  # services that read .env.prod and nothing else (postgres/redis/caddy stay up). No build,
  # no migrate — the running release, only with the new environment.
  echo "==> Recreating the services whose environment changed"
  remote "$COMPOSE up -d --no-build"
  cmd_status
}

[[ $# -ge 1 ]] || usage
action=$1
shift
case "$action" in
  -h | --help | help) usage 0 ;;
  deploy | status | logs | backup | env-push) ;;
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
  env-push) cmd_env_push "$@" ;;
esac
