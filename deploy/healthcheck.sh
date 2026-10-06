#!/usr/bin/env bash
# Health checks of the running stack, run ON THE SERVER through Caddy (same origin the
# browser uses). Shared by `deploy/deploy.sh status|deploy` (piped over ssh) and
# deploy/server-deploy.sh (the CI deploy). Exits non-zero when any probe misses its code.
#
#   healthcheck.sh [/opt/qualify/.env.prod]
#
# Expected: /ping 200 (Reflex backend) · /api/connections/callback 403 (invalid state =
# FastAPI reached; a 502 would be a failure) · /login 200 (static frontend).
set -u
ENV_FILE=${1:-/opt/qualify/.env.prod}

val() { grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2-; }
domain=$(val QUALIFY_DOMAIN)
http_port=$(val QUALIFY_HTTP_PORT)
case "$domain" in
  http://*) host=${domain#http://}; base="http://$host:${http_port:-80}"; resolve=() ;;
  *) host=${domain#https://}; base="https://$host"; resolve=(--resolve "$host:443:127.0.0.1") ;;
esac
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 ${resolve[@]+"${resolve[@]}"} "$base$1" || true; }

echo "==> Health (through Caddy): /ping 200 · callback 403 · /login 200"
for _ in $(seq 1 45); do [ "$(code /ping)" = 200 ] && break; sleep 2; done
failed=0
for probe in '/ping 200' '/api/connections/callback?code=x&state=x 403' '/login 200'; do
  path=${probe% *}
  want=${probe##* }
  got=$(code "$path")
  mark=ok
  [ "$got" = "$want" ] || { mark=FAIL; failed=1; }
  printf '  %-4s %-62s %s (want %s)\n' "$mark" "$base$path" "$got" "$want"
done
exit $failed
