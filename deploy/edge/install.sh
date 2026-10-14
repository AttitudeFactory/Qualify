#!/usr/bin/env bash
# Install or update the VPS edge proxy (deploy/edge/) in /opt/edge. Run ON THE SERVER, as a
# user that can talk to Docker — usually through `just edge-install <ssh-target>`, which copies
# this directory over and runs it.
#
#   install.sh [--wait-for-ports [SECONDS]]
#
# Idempotent. What it does, in order:
#   1. Ensures the two external networks exist: `qualify-edge` (Qualify's internal Caddy joins
#      it) and `pedidos` (the Pedidos backend joins it). The edge owns them, so it starts no
#      matter which product is up.
#   2. Copies Caddyfile + docker-compose.yml into /opt/edge; creates /opt/edge/.env from
#      .env.example the first time and stops there until it is filled in.
#   3. `docker compose create` (volumes + container, ports not bound yet). If the edge's
#      certificate volume is still empty and Qualify's former Caddy volume exists, copies the
#      certificates over, so the switch needs no new Let's Encrypt issuance.
#   4. Starts the edge. If 80/443 are still held by Qualify's former Caddy (the one-time
#      cutover), `--wait-for-ports` waits until the next Qualify deploy releases them and starts
#      the edge the moment they are free; without the flag it explains and exits 1.
#   5. Probes both hosts through the edge.
set -euo pipefail

EDGE_DIR=${EDGE_DIR:-/opt/edge}
LEGACY_CERT_VOLUME=${LEGACY_CERT_VOLUME:-qualify-prod_caddy_data}
CADDY_IMAGE=caddy:2.11-alpine
SRC=$(cd "$(dirname "$0")" && pwd)

wait_ports=0
wait_seconds=900
if [[ ${1:-} == --wait-for-ports ]]; then
  wait_ports=1
  wait_seconds=${2:-900}
fi

die() { echo "edge-install: $*" >&2; exit 1; }
command -v docker >/dev/null || die "docker is not available for this user"

echo "==> 1. Networks"
for net in qualify-edge pedidos; do
  if docker network inspect "$net" >/dev/null 2>&1; then
    echo "    $net exists"
  else
    docker network create "$net" >/dev/null && echo "    $net created"
  fi
done

echo "==> 2. Files in $EDGE_DIR"
[[ -d $EDGE_DIR && -w $EDGE_DIR ]] \
  || die "$EDGE_DIR missing or not writable — once, as root: install -d -o \$USER -g \$USER $EDGE_DIR"
install -m 0644 "$SRC/Caddyfile" "$EDGE_DIR/Caddyfile"
install -m 0644 "$SRC/docker-compose.yml" "$EDGE_DIR/docker-compose.yml"
if [[ ! -f $EDGE_DIR/.env ]]; then
  install -m 0644 "$SRC/.env.example" "$EDGE_DIR/.env"
  die "created $EDGE_DIR/.env from the template — set EDGE_ACME_EMAIL (and check the domains), then run this again"
fi
grep -qE '^EDGE_ACME_EMAIL=.+' "$EDGE_DIR/.env" || die "EDGE_ACME_EMAIL is empty in $EDGE_DIR/.env"

dc() { (cd "$EDGE_DIR" && docker compose "$@"); }

echo "==> 3. Container + certificate volume"
dc create edge >/dev/null
cert_volume=edge_edge_data
# "Empty" means no certificates yet, not an empty directory: Docker seeds a new named volume
# with the image's own /data (an empty caddy/ folder), so `ls -A` would never see it empty.
if [[ -z $(docker run --rm -v "$cert_volume:/to" "$CADDY_IMAGE" \
  sh -c 'ls -A /to/caddy/certificates 2>/dev/null') ]]; then
  if docker volume inspect "$LEGACY_CERT_VOLUME" >/dev/null 2>&1; then
    docker run --rm -v "$LEGACY_CERT_VOLUME:/from:ro" -v "$cert_volume:/to" "$CADDY_IMAGE" \
      sh -c 'cp -a /from/. /to/'
    echo "    certificates copied from $LEGACY_CERT_VOLUME (no new issuance needed)"
  else
    echo "    no previous certificates — Caddy will request them from Let's Encrypt on start"
  fi
else
  echo "    certificate volume already holds certificates"
fi

port_busy() {
  # A port is "ours" when the edge container itself publishes it — then it is not busy.
  local holders
  holders=$(docker ps --filter "publish=$1" --format '{{.Names}}' | grep -vx 'edge-edge-1' || true)
  [[ -n $holders ]]
}

echo "==> 4. Start"
if port_busy 443 || port_busy 80; then
  holder=$(docker ps --filter publish=443 --format '{{.Names}}' | head -1)
  if [[ $wait_ports -eq 0 ]]; then
    die "80/443 are held by '$holder'. This is the one-time cutover: run with --wait-for-ports, then deploy Qualify — the edge starts the moment that deploy releases the ports"
  fi
  echo "    80/443 held by '$holder' — waiting up to ${wait_seconds}s for the Qualify deploy to release them"
  deadline=$((SECONDS + wait_seconds))
  while port_busy 443 || port_busy 80; do
    (( SECONDS < deadline )) || die "timed out; nothing changed on the edge side (the container is created, not started)"
    sleep 1
  done
  echo "    ports free"
fi
dc up -d edge

echo "==> 5. Probes through the edge"
set -a
# shellcheck source=/dev/null
. "$EDGE_DIR/.env"
set +a
probe() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve "$1:443:127.0.0.1" "https://$1$2" || true
}
for _ in $(seq 1 30); do [[ $(probe "$QUALIFY_DOMAIN" /ping) == 200 ]] && break; sleep 2; done
printf '    %-45s %s (want 200; 502 = Qualify not attached to qualify-edge yet)\n' \
  "https://$QUALIFY_DOMAIN/ping" "$(probe "$QUALIFY_DOMAIN" /ping)"
printf '    %-45s %s (any HTTP code; 502 = Pedidos backend not running)\n' \
  "https://$PEDIDOS_DOMAIN/" "$(probe "$PEDIDOS_DOMAIN" /)"
echo "==> Edge up. Logs: cd $EDGE_DIR && docker compose logs -f edge"
