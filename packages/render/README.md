# `packages/render` — Qualify render service (Remotion)

Node + Remotion package that turns a template + props into video/stills, exposed over
HTTP so the Python side (`qualify_creative.render`) never imports Node. The contract
both sides build against is **[`CONTRACT.md`](./CONTRACT.md)**; decision record in
`docs/plan-mvp-plantillas-remotion.md` §2.

```
Python (qualify_creative.render)  ──HTTP──►  server.mjs  ──►  @remotion/renderer  ──►  Chrome Headless Shell
                                              │  in-memory jobs, FIFO queue, TTL sweeper
                                              └─ /data/assets (uploads)  /data/renders/<jobId>/<port>.{mp4,png}
```

## Layout

| Path | What |
|---|---|
| `templates/<id>/manifest.json` | Template manifest (CONTRACT §1): typed input ports, output ports → composition ids, duration bounds, cost model. Served as-is by `GET /templates`. |
| `src/Root.tsx` | Registers one `<Composition>`/`<Still>` per output port, reading ids/dimensions/bounds **from the manifests** (single source). |
| `src/props.ts` | zod schema + `Props` type for the props JSON (CONTRACT §2), palette convention. |
| `src/fonts.ts` | Google Fonts by family name via `@remotion/google-fonts`, with the `Noto Sans` fallback and a timeout. |
| `src/components.tsx` | Shared primitives: `CoverPhoto` (contain over a blurred cover copy), `PricePill`, `Headline`, `Logo`. |
| `src/templates/hello_world/` | Smoke-test template (3 s reel). |
| `src/templates/promo_producto/` | `script.ts` (deterministic scene timing + clamp), `PromoReel.tsx`, `PromoStill.tsx`. |
| `server.mjs` + `server/*.mjs` | The HTTP API (CONTRACT §4): config, manifests, validation, assets, jobs/queue, font warnings. |
| `Dockerfile` | `node:22-bookworm-slim` + Remotion's documented libs + Noto fonts + Chrome Headless Shell, pre-bundled, non-root, HEALTHCHECK. |
| `scripts/smoke.sh` | End-to-end check against a running service (`just render-smoke`). |
| `scripts/render-cli.mjs` | Render one composition from the CLI without the server (debugging). |

## Running

```bash
just up                 # postgres + redis + render (docker compose up -d --wait)
just render-build       # rebuild the image after changing src/, templates/, server/
just render-logs        # follow the container's JSON logs
just render-smoke       # upload 2 photos, render both templates, download + `file` every output
just render-dev         # Remotion Studio on the host with hot reload (authoring)
```

Without Docker: `cd packages/render && npm install && npx remotion browser ensure && npm run serve`
(uses `./out/{renders,assets}` and bundles at startup, ~10 s).
`npm run typecheck` runs `tsc --noEmit`.

Env (CONTRACT §5): `PORT` 3200 · `RENDER_CONCURRENCY` 1 (outputs rendered in parallel) ·
`REMOTION_CONCURRENCY` (Chromium tabs per render, default Remotion's) · `RENDERS_DIR` ·
`ASSETS_DIR` · `TEMPLATES_DIR` · `BUNDLE_DIR` (prebuilt bundle; falls back to bundling at
startup when missing) · `LOG_LEVEL` · `RENDERS_TTL_HOURS` 24 · `ASSETS_TTL_HOURS` 24 ·
`RENDER_TIMEOUT_SEC` 900 (wall-clock per output → `timeout`) · `DELAY_RENDER_TIMEOUT_MS` 60000.

## How the server works

1. **Startup**: loads every `templates/*/manifest*.json`, then uses the prebuilt bundle in
   `BUNDLE_DIR` (Docker) or runs `@remotion/bundler` once (host). `/health` reports
   `bundleReady`; the compose healthcheck only passes when it is `true`, so
   `docker compose up --wait` blocks until renders can start.
2. **Assets**: `POST /assets` (multipart `file` or raw body) stores the bytes under
   `ASSETS_DIR`, content-addressed (`assetId` = sha256 hex, so re-uploads are idempotent),
   with a JSON sidecar for the mime type (sniffed from magic bytes, else the declared one).
   Props reference them as `asset://<assetId>`; right before rendering the server rewrites
   them to `http://127.0.0.1:PORT/assets/<assetId>` so Chromium fetches them locally.
3. **Validation** (`server/validate.mjs`): props vs the manifest's input ports — required,
   `max` chars, `min`/`max` images, asset-ref shape, and that every referenced asset exists.
   Any problem → `422 invalid_parameters` with `problems: [...]`.
4. **Jobs**: client-supplied `jobId`; a second `POST /render` with the same id returns the
   existing job (`200`). Each requested output becomes a queue entry (stills before videos
   so the cheap outputs are ready while the video renders); `RENDER_CONCURRENCY` entries
   run at a time. Per output: `selectComposition` (runs the composition's
   `calculateMetadata` → duration) then `renderMedia` (h264 mp4, progress 0..0.99) or
   `renderStill` (png, frame 0). Status rolls up per CONTRACT §4.1.
5. **Failures** map to CONTRACT §4.2: wall-clock cap or Remotion `delayRender` timeout →
   `timeout`; missing/expired asset, image/font load failure → `dependency_failed`;
   anything Chromium/Remotion threw → `render_error`; otherwise `internal_error`.
6. **Cancel**: pending outputs → `cancelled`; a running one gets Remotion's `cancelSignal`.
7. **Sweeper** (every 10 min): finished jobs older than `RENDERS_TTL_HOURS` (files + map
   entry, plus orphan dirs from a previous process) and assets older than `ASSETS_TTL_HOURS`.

Error codes Python will see: `not_found` (404), `invalid_parameters` (422),
`bad_request` (400, malformed JSON / multipart without `file`), `payload_too_large` (413),
`not_ready` (409, output not completed — the body carries its current `status`),
`bundle_not_ready` (503, before the bundle exists), `internal_error` (500).

## Adding a template

1. `templates/<id>/manifest.json` — copy `promo_producto`'s shape. Output `composition`
   ids must be Remotion-legal: **`a-z A-Z 0-9 -` only** (see deviations), convention
   `<id-with-dashes>-v<version>--<port>`.
2. `src/templates/<id>/` — one component per output kind. Read props through
   `normalizeProps`/`textOf`/`paletteOf`, fonts through `useBrandFonts`. No network,
   no `Math.random`, no `Date.now()`: same props → same bytes.
3. For a video port, put scene timing in a pure `script.ts` (like promo_producto) and use
   it both in `calculateMetadata` and in the component, clamped to the manifest bounds.
4. Register in `src/Root.tsx` reading ids/dimensions from the manifest JSON import.
5. `npm run typecheck`, `just render-build`, `just render-smoke` (extend the script).

Publishing a change to an existing template = bump `version`, keep the old file as
`manifest.v<N>.json` and the old composition registered (CONTRACT §1).

## Deviations from CONTRACT.md (read before touching the Python client)

- **Composition ids**: Remotion rejects `_` in composition ids ("Composition id can only
  contain a-z, A-Z, 0-9, CJK characters and -"), so `hello_world_v1__reel` cannot exist.
  Implemented as `hello-world-v1--reel`, `promo-producto-v1--reel`, `promo-producto-v1--feed`,
  `promo-producto-v1--story`. The manifest's `outputs.<port>.composition` carries the real
  id — Python should read it from there, never derive it from `template_id`.
- **`assetId` is the sha256 of the content** (64 hex chars), not an opaque random id:
  re-uploading the same bytes returns the same id (and refreshes its TTL).
- **Unknown asset at submit time** → `422 invalid_parameters` (`problems: ["asset '…' not found"]`),
  because Python must upload first. An asset that expires between submit and render →
  the output fails with `dependency_failed`.
- **Output ordering**: within a job, stills are queued before videos regardless of the
  `outputs` order in the request.
- **Fonts do hit the network**: `@remotion/google-fonts` loads from `fonts.gstatic.com`
  inside Chromium (CONTRACT §2 asks for Google Fonts by name; §3's "no network" is
  satisfied for everything else). An unknown family, or a load that takes > 12 s, falls
  back to `Noto Sans` (installed in the image); unknown families are also reported in
  `warnings` by the server (same catalogue, so job and picture agree). An offline host
  renders with the fallback instead of failing.
- **Bundle at build time**: the Docker image runs `remotion bundle` at build and the server
  uses it (`BUNDLE_DIR`), so `bundleReady` is true within ~1 s of start. Without a prebuilt
  bundle the server bundles at startup exactly as §5 says.
- **`GET /jobs/{id}/outputs/{port}` on a failed/cancelled output** answers `409 not_ready`
  with `status: "failed"|"cancelled"` (the contract only names the not-finished case).
- **`version` omitted in `/estimate` / `/render`** resolves to the latest manifest instead
  of being an error.
- `hello_world`'s manifest declares `brand` as an optional `brand_kit` and
  `duration.from = "fixed"` (3 s) — it has no script to derive from.

## Verification status (2026-10-05)

Verified on the host (macOS, node 22.14, Remotion 4.0.532) with `scripts/smoke.sh`:

| Step | Result |
|---|---|
| `npm install`, `npm run typecheck` | pass |
| bundle at startup | 9.8 s |
| `POST /assets` multipart + raw body, `GET /assets/{id}` | 201 / 200, sha256 ids |
| `hello_world` reel (1080x1920, 3 s) | **6 s** wall-clock, 564 KB h264 MP4 |
| `POST /estimate` promo_producto (2 photos) | `reel 9.5 s / eta 19 s`, stills 4 s each, total 27 s |
| bad props (hook 70 chars, 1 photo) | `422 invalid_parameters` |
| `promo_producto` reel + feed + story | **14 s** wall-clock for the 3 outputs: reel 1.57 MB MP4 (h264 1080x1920 30 fps 9.5 s), feed 367 KB PNG 1080x1350, story 458 KB PNG 1080x1920 |
| idempotent `POST /render` with the same `jobId` | 200 + the existing job |

**Not verified: the Docker image and the compose `render` service.** On the build machine
Docker Desktop could not pull *any* image (`node:22-bookworm-slim`, its ECR mirror, even
`hello-world` hang indefinitely while containers inside the VM reach the registries in
0.2 s) — see `.claude/sprint-state-2026-10-05-render-service.md`. After Docker Desktop is
restarted, run `just render-build && docker compose up -d --wait render && just render-smoke`.
