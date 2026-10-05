#!/usr/bin/env bash
# End-to-end smoke test against a running render service (CONTRACT §4).
#   scripts/smoke.sh [BASE_URL]      default http://127.0.0.1:3200
# Uploads two sample photos, renders hello_world and promo_producto, downloads every
# output, checks it with `file`, prints wall-clock render times. Exit 1 on any failure.
set -euo pipefail
BASE="${1:-http://127.0.0.1:3200}"
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/smoke-out"
mkdir -p "$OUT"

json() { node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const j=JSON.parse(s);const v=process.argv[1].split(".").reduce((a,k)=>a?.[k],j);console.log(typeof v==="object"?JSON.stringify(v):v)})' "$1"; }
uuid() { node -e 'console.log(require("crypto").randomUUID())'; }
now() { node -e 'console.log(Date.now())'; }

echo "== health ($BASE)"
for i in $(seq 1 90); do
  if curl -fsS "$BASE/health" 2>/dev/null | json bundleReady | grep -q true; then break; fi
  sleep 2
  [ "$i" = 90 ] && { echo "bundle never became ready"; exit 1; }
done
curl -fsS "$BASE/health"; echo

echo "== upload assets"
A1=$(curl -fsS -X POST "$BASE/assets" -F "file=@$HERE/../public/sample/photo-1.jpg;type=image/jpeg" | json assetId)
A2=$(curl -fsS -X POST "$BASE/assets" -H 'content-type: image/jpeg' --data-binary "@$HERE/../public/sample/photo-2.jpg" | json assetId)
echo "asset 1: $A1"; echo "asset 2: $A2"
curl -fsS -o /dev/null -w "GET /assets/%{http_code} %{size_download}B\n" "$BASE/assets/$A1"

poll() { # poll <jobId> → prints final status, exits 1 if not completed
  local id="$1" status
  while :; do
    status=$(curl -fsS "$BASE/jobs/$id" | json status)
    case "$status" in
      completed) echo "$status"; return 0 ;;
      failed|cancelled) curl -fsS "$BASE/jobs/$id"; echo; return 1 ;;
    esac
    sleep 2
  done
}

echo "== render hello_world"
J1=$(uuid); T0=$(now)
curl -fsS -o /dev/null -w "POST /render → %{http_code}\n" -X POST "$BASE/render" -H 'content-type: application/json' \
  -d "{\"jobId\":\"$J1\",\"templateId\":\"hello_world\",\"version\":1,\"props\":{\"brand\":{\"name\":\"Qualify\",\"palette\":[\"#0F766E\",\"#FFFFFF\"],\"fonts\":{\"heading\":\"Poppins\",\"body\":\"Inter\"}},\"texts\":{},\"photos\":[],\"video\":null,\"products\":[]}}"
curl -fsS -o /dev/null -w "idempotent re-POST → %{http_code}\n" -X POST "$BASE/render" -H 'content-type: application/json' \
  -d "{\"jobId\":\"$J1\",\"templateId\":\"hello_world\",\"version\":1,\"props\":{\"texts\":{},\"photos\":[]}}"
poll "$J1"; T1=$(now); echo "hello_world wall-clock: $(( (T1 - T0) / 1000 )) s"
curl -fsS -o "$OUT/hello_world.mp4" "$BASE/jobs/$J1/outputs/reel"
file "$OUT/hello_world.mp4"

echo "== estimate promo_producto"
PROPS="{\"meta\":{\"templateId\":\"promo_producto\",\"version\":1,\"port\":\"reel\",\"locale\":\"es-VE\"},\"brand\":{\"name\":\"Polette\",\"palette\":[\"#F4C2C2\",\"#5A2A27\",\"#FFFFFF\"],\"fonts\":{\"heading\":\"Poppins\",\"body\":\"Inter\"},\"logo\":\"asset://$A2\"},\"texts\":{\"hook\":\"El yogurt que se come con cuchara\",\"price_line\":\"\$4\",\"cta\":\"Pide el tuyo\"},\"photos\":[\"asset://$A1\",\"asset://$A2\"],\"video\":null,\"products\":[]}"
curl -fsS -X POST "$BASE/estimate" -H 'content-type: application/json' -d "{\"templateId\":\"promo_producto\",\"version\":1,\"props\":$PROPS}"; echo

echo "== 422 on bad props"
curl -sS -o /dev/null -w "hook too long + 1 photo → %{http_code}\n" -X POST "$BASE/estimate" -H 'content-type: application/json' \
  -d "{\"templateId\":\"promo_producto\",\"version\":1,\"props\":{\"brand\":{},\"texts\":{\"hook\":\"$(printf 'x%.0s' $(seq 1 70))\",\"cta\":\"ok\"},\"photos\":[\"asset://$A1\"]}}"

echo "== render promo_producto (reel + feed + story)"
J2=$(uuid); T0=$(now)
curl -fsS -o /dev/null -w "POST /render → %{http_code}\n" -X POST "$BASE/render" -H 'content-type: application/json' \
  -d "{\"jobId\":\"$J2\",\"templateId\":\"promo_producto\",\"version\":1,\"props\":$PROPS}"
poll "$J2"; T1=$(now); echo "promo_producto wall-clock (3 outputs): $(( (T1 - T0) / 1000 )) s"
curl -fsS "$BASE/jobs/$J2"; echo
for port in reel feed story; do
  ext=mp4; [ "$port" != reel ] && ext=png
  curl -fsS -o "$OUT/promo_$port.$ext" "$BASE/jobs/$J2/outputs/$port"
  file "$OUT/promo_$port.$ext"
done
ls -la "$OUT"
echo "== OK"
