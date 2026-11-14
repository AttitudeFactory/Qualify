# Render service contract (Remotion) — v1

Decision record: `docs/plan-mvp-plantillas-remotion.md` §2 (founder, 2026-10-05: Remotion
replaces Pillow; Docker from phase 1; option **B** = one long-running Node process in the
container exposing HTTP). This file is the contract both sides build against:
`packages/render/` (Node, Remotion) and `qualify_creative.render` (Python client/adapter).
Change it here first, then both sides.

Principles (copied from ElevenCreative's Templates API, see backlog §7):
typed ports · immutable template versions · several outputs per run · status per output,
run status rolled up · typed failure reasons · assets passed by reference.

The service holds **no business logic**: it receives props, renders, serves files. Python
decides everything else (which template, which texts, which photos, cost, approval).

## 1. Template manifest (`templates/<template_id>/manifest.json`)

One directory per template, one `manifest.json` per **version** is NOT used; instead the
manifest carries `version` and a published version is never edited — bump `version` and
keep the old composition working (compositions are named with the version, see §3).

```json
{
  "id": "promo_producto",
  "version": 1,
  "name": "Promo de producto",
  "niche": ["shawarma", "helado"],
  "serves_angles": ["product", "new_product", "promotion", "price", "sold_out"],
  "inputs": {
    "hook":       {"type": "string", "max": 60},
    "price_line": {"type": "string", "max": 24, "optional": true},
    "cta":        {"type": "string", "max": 40},
    "photos":     {"type": "image[]", "min": 2, "max": 4},
    "brand":      {"type": "brand_kit"}
  },
  "outputs": {
    "reel":  {"kind": "video", "width": 1080, "height": 1920, "composition": "promo-producto-v1--reel"},
    "feed":  {"kind": "still", "width": 1080, "height": 1350, "composition": "promo-producto-v1--feed"},
    "story": {"kind": "still", "width": 1080, "height": 1920, "composition": "promo-producto-v1--story"}
  },
  "duration": {"from": "script", "min_sec": 8, "max_sec": 30},
  "cost_model": {"seconds_per_video_sec": 2.0, "seconds_per_still": 4.0}
}
```

Port types: `string` (with `max`, optional `enum`), `number`, `boolean`, `image`,
`image[]` (with `min`/`max`), `video`, `brand_kit`, `product[]`. `optional` defaults to
false. Python validates a Post against the manifest **before** asking for a render; the
service re-validates and answers `422 invalid_parameters` if props do not match.

Optional `sheet` block (m-24987158, the `sticker` template): `{"cell": 512, "columns": 6,
"frames": 30, "fps": 15}` says that a still output holds every frame of a short loop as a
grid, left to right, top to bottom, on a transparent background — the way to get an
animation WITH ALPHA out of the service (its videos are H.264, which has none). Python
slices the grid and encodes the animation itself (`qualify_creative.seasonal.sticker_c`);
one still output must be exactly `columns × cell` by `ceil(frames / columns) × cell`. A
template meant only for such a caller lists an angle no post has (`"serves_angles":
["seasonal_sticker"]`) so the post recipes never pick it.

`sticker` **v2** (m-25017372, product stickers) adds the «caption» mode: an image motion
(`latido`, `rebote`, `giro`, `brillo`) WITH a `text` draws the art above a 1–2 line message on
its own die-cut, in the brand's heading face, inked `texts.captionInk` over `texts.captionBacking`
(both `#RRGGBB`, chosen by contrast in Python — `qualify_creative.seasonal.backing`). The
geometry (`src/templates/sticker/caption.ts`) keeps every motion inside the 16 px margin and
above the caption; `server/sticker-caption.test.mjs` checks it frame by frame. v1 is kept
(`manifest.v1.json`, `sticker-v1--sheet`) and still ignores the text of an image motion.

Optional `render` block (m-25016848, the `seasonal_video` template): `{"concurrency": 1}`
caps the Chromium tabs of that template's renders (Remotion's `concurrency`), never above
the service's own `REMOTION_CONCURRENCY` — a 720p video on the 1536 MB container renders on
one tab. A video composition may also take its **size** from the props through
`calculateMetadata` (seasonal_video: 720 px wide, `texts.height` 720–1280 tall); the
manifest's `width`/`height` are then the largest frame, and the job reports the size it
actually rendered.

`layer_still` **v1** (m-25017285, ADR 49 §2, catalog `docs/catalogo-disenos-imagen-carrusel.md`)
renders ONE still per job from a `LayerSpec`: ports `feed` (4:5), `square` (1:1), `story`
(9:16), each output carrying its catalog `format`. One port type exists only for it:
`layer_spec` (`props.layer`), the `LayerSpec` v1 of m-25017283 as its pydantic model dumps
it — `format` (must equal the port's), `photo {subject_box, logo_in_photo,
base_has_invented_text}`, `price_ref {product_id}`, `highlight_content {kind, icon_id, word}`,
`info_blocks [{kind, label, value}]` (fixed labels), `photo_strip`, and the carousel place
`carousel {role, index, count}` with a **0-based** `index` below `count` (2–10), the role
following the index (0 = `cover`, last = `closing`), no carousel in 9:16. The counter
`index+1/count` and the logo on the first and last slide come from it. `layer_id` (optional)
is echoed in the report. The manifest's `layer_catalog` block is what the render enforces
(safe zones, font sizes, slot limits per layout and format, info kinds, icon set); the layer
stage keeps its own `qualify_creative/layer_spec/catalog_v1.json` — a test comparing the two
lands with whichever branch merges second. `src/templates/layer_still/spec.mjs` checks a
layer against `layer_catalog` — the server answers `422 invalid_parameters` per requested
port (unknown `layout_id`, unknown field, slot over its character limit, a parameter the
layout does not take, a format other than the port's) and the composition re-checks. Brand
colours are drawn opaque (an `#RRGGBBAA` alpha is dropped). `texts.price_text` (the catalog
price, formatted whole by Python) and `texts.is_food` are the only texts. The checks of
catalog §1.7 (subject box, safe zones, fit at the minimum size, contrast, logo once) and the
fixed fallback chain to `band` run in the composition's `calculateMetadata` (the brand's
fonts — or the fallback after FONT_TIMEOUT, the same face the still is then drawn with —
and canvas measurement; `engine.ts`); the decision is returned on the job output as
`report` (§4.1). A layout whose text does not fit its lines or crosses the safe zone counts
as failed and the chain moves on; when every layout of the chain fails, the output fails
with `invalid_parameters` and a machine-readable `refusal` (§4.1) — never an image with
overflowing text. A carousel is N jobs (ADR 49 §2.2).

**Engine revision** (`layer_catalog.engine_revision`, today 2). The template version pins the
props contract; the engine revision pins the pixels. It is bumped with ANY change to
`engine.ts`, `LayerStill.tsx`, `icons.tsx` or the font loading that can move a pixel, it is
echoed as `report.engine_revision`, and Python puts it in the compose job id (and therefore in
the object key, which carries the job id): a recompose after an engine change is a new job and a
new object, never «same key, different pixels». Fonts follow the same rule: a brand family the
Google Fonts catalogue knows is measured AND drawn with that face or the job fails (`timeout` /
`dependency_failed`) — it never silently falls back to Noto Sans under the same key; only an
unknown family uses the fallback, deterministically, with a `warnings` entry.

Order of the 422 checks (changed with m-25017285): `POST /estimate` and `/render` now check
that every `asset://` exists **before** validating the props against the manifest, because a
layer's limits depend on the requested ports. A request with both problems answers the
unknown-asset 422 first; both are `invalid_parameters`.

`cost_model` is **render time**, not money: the service runs on our own machine (cost 0
beyond the server). Python turns ETA into money only if a paid runtime (Lambda, license)
is configured.

## 2. Props (the JSON a composition receives)

Same shape for every template; a template reads the ports it declares.

```json
{
  "meta":  {"templateId": "promo_producto", "version": 1, "port": "reel",
            "tenantId": "…", "draftId": "…", "locale": "es-VE"},
  "brand": {"name": "Polette", "palette": ["#F4C2C2", "#5A2A27", "#FFFFFF"],
            "fonts": {"heading": "Poppins", "body": "Inter"},
            "logo": "asset://a1b2…", "tone": "cálida"},
  "texts": {"hook": "El yogurt que se come con cuchara", "price_line": "$4", "cta": "Pide el tuyo"},
  "photos": ["asset://c3d4…", "asset://e5f6…"],
  "video": null,
  "products": [{"name": "Fresa", "price": "$4", "photo": "asset://…"}]
}
```

- Media is referenced as `asset://<assetId>`; the service resolves it to its own URL
  (`http://127.0.0.1:<port>/assets/<assetId>`) before handing props to Chromium.
  Compositions never see storage keys or signed R2 URLs.
- Fonts: Google Fonts by family name (loaded with `@remotion/google-fonts`); an unknown
  family falls back to the template default and is reported in the job (`warnings`).
- `texts` values are already validated against `max`; the composition may still auto-fit.

## 3. Compositions

`src/Root.tsx` registers one `<Composition>` / `<Still>` per output port, id =
`<template-id>-v<version>--<port>` with the template id's underscores turned into hyphens
(Remotion allows only `[A-Za-z0-9-]` in a composition id) — exactly the `composition`
field in the manifest, e.g. `promo-producto-v1--reel`.
Video compositions derive their duration with `calculateMetadata` from the props (number
of photos/scenes and text lengths), bounded by `duration.min_sec`/`max_sec`. Stills pick
a representative frame. Dimensions come from the manifest. **No network, no business
logic, no randomness** inside a composition: same props → same bytes.

## 4. HTTP API (default port `3200`, bind `0.0.0.0` inside the container)

All bodies JSON unless noted. Errors: `{"error": "<code>", "message": "…"}` with the HTTP
status below. `jobId` is **client-supplied** (a UUID) so a retry of `POST /render` with the
same id is idempotent and returns the existing job.

| Method & path | Body → Response | Notes |
|---|---|---|
| `GET /health` | → `200 {"ok": true, "bundleReady": bool, "version": "<pkg version>", "templates": [{"id","version"}]}` | compose healthcheck |
| `GET /templates` | → `200 {"templates": [<manifest>, …]}` | manifests as on disk |
| `GET /templates/{id}` | → `200 <manifest>` (latest) · `404 not_found` | `?version=N` for a pinned one |
| `POST /assets` | multipart `file` (or raw body + `Content-Type`) → `201 {"assetId", "url", "mimeType", "bytes"}` | stored under `ASSETS_DIR`, TTL 24 h, max 200 MB |
| `GET /assets/{assetId}` | → the file | used by Chromium during render only; `Access-Control-Allow-Origin` echoed for loopback origins only (`http://localhost|127.0.0.1|[::1][:port]`, the bundle's page) so `FontFace` can load an uploaded brand font (m-24993425) |
| `POST /estimate` | `{"templateId","version","props"}` → `200 {"outputs": {"<port>": {"kind","etaSec","durationSec"?}}, "totalEtaSec", "warnings": []}` · `422 invalid_parameters` | no render |
| `POST /render` | `{"jobId","templateId","version","props","outputs"?: ["reel","feed"]}` → `202 <job>` · `200 <job>` if jobId exists · `422 invalid_parameters` · `404 not_found` (template) · `409 busy` never (queue instead) | queued, concurrency `RENDER_CONCURRENCY` (default 1) |
| `GET /jobs/{jobId}` | → `200 <job>` · `404 not_found` | poll "at a modest interval" (Python: 2 s) |
| `GET /jobs/{jobId}/outputs/{port}` | → the rendered file (`video/mp4` / `image/png`) · `409 not_ready` · `404` | Python downloads and stores in its own media store |
| `POST /jobs/{jobId}/cancel` | → `200 <job>` | cancels pending outputs; a running one is aborted |

### 4.1 Job object

```json
{
  "jobId": "…", "templateId": "promo_producto", "version": 1,
  "status": "pending|generating|completed|failed|cancelled",
  "outputs": {
    "reel":  {"kind": "video", "status": "generating", "progress": 0.42},
    "feed":  {"kind": "still", "status": "completed", "progress": 1,
              "mimeType": "image/png", "bytes": 412331, "width": 1080, "height": 1350},
    "story": {"kind": "still", "status": "pending", "progress": 0}
  },
  "durationSec": 14.0,
  "warnings": ["font 'Poppins' unavailable, used 'Inter'"],
  "createdAt": "…", "startedAt": "…", "finishedAt": null
}
```

A failed output adds `"failureReason"` and `"errorMessage"`. A `layer_still` output adds
`"report"` once its composition was selected: `{layer_id, layout_requested, layout_rendered,
anchor, format, fallbacks[], dropped_slots[], sizes{}, contrast{}, logo, counter, overflow[],
fonts{heading, body}, title_metrics{line_height, gap_after}}` — `overflow` is always empty on
a completed output; `fonts` are the families measured and drawn. Python records
`layout_rendered` and `fallbacks` with the piece. A layer the composition refuses fails the
output with `invalid_parameters`; when no layout of the chain could draw it the output also
carries `"refusal": {code: "layer_unrenderable", slot, reason, detail, format,
layout_requested, attempts[]}` — `slot` names what to rewrite (`title`,
`info_blocks[1].value`, `highlight_content.word`…), `reason` is `word_too_wide` ·
`too_many_lines` · `title_does_not_fit` · `no_room_beside_subject` · `too_tall` ·
`outside_safe_zone`. The jobId is deterministic, so a retry returns the same failed job: the
fix is a new layer (new text → new spec → new jobId). Rollup rule (ElevenCreative):
`pending` until an output starts; `generating` while any output is unfinished; `completed`
once every output completed; `failed` once every output finished and at least one failed;
`cancelled` if cancelled before completion.

### 4.1b Error codes (as implemented, 2026-10-05)

`not_found` 404 · `invalid_parameters` 422 (body also carries `problems: string[]`) ·
`bad_request` 400 (malformed JSON, multipart without `file`) · `payload_too_large` 413 ·
`not_ready` 409 (+ `status`) · `bundle_not_ready` 503 · `internal_error` 500. `assetId` is
the sha256 hex of the bytes (content-addressed: re-uploading the same file is idempotent
and refreshes its TTL). An unknown asset at submit time is `422 invalid_parameters`; an
asset that expired between submit and render fails that output with `dependency_failed`.
Stills are queued before videos within a job. Fonts are fetched from Google Fonts at
render time (the one network call a composition makes); an unknown family or a load
over 12 s falls back to Noto Sans and is reported in `warnings`.

### 4.2 Failure reasons

`timeout` · `render_error` (Chromium/Remotion threw) · `invalid_parameters` (props vs
manifest) · `dependency_failed` (an asset could not be fetched, a font failed) ·
`internal_error`. Python maps them onto `qualify_creative.enums.FailureReason`.

## 5. Process & container

- Bundle once at startup (`@remotion/bundler`), keep the bundle for the life of the
  process; `bundleReady=false` in `/health` until then.
- Renders with `@remotion/renderer` `renderMedia` / `renderStill`,
  `chromiumOptions.enableMultiProcessOnLinux: true`, `concurrency` from env.
- Env: `PORT` (3200), `RENDER_CONCURRENCY` (1), `RENDERS_DIR` (`/data/renders`),
  `ASSETS_DIR` (`/data/assets`), `TEMPLATES_DIR` (`/app/templates`), `LOG_LEVEL`.
- Outputs on disk `RENDERS_DIR/<jobId>/<port>.<ext>`; a sweeper deletes finished jobs
  older than `RENDERS_TTL_HOURS` (default 24). Jobs are **in memory** (a restart loses
  them): Python owns durable state (`template_runs`) and re-submits if a job vanished.
- Image `node:22-bookworm-slim` + the shared libs Remotion documents + `npx remotion
  browser ensure` at build time; fonts: `fonts-noto-core`, `fonts-noto-color-emoji`.
  No FFmpeg install (Remotion bundles its own). Non-root user. `HEALTHCHECK` on `/health`.
- Compose service name `render`, port `3200:3200`, volume `renders:/data`; `just up`
  starts it with Postgres and Redis. `just render-dev` runs Remotion Studio on the host
  (authoring with hot reload); `just render-build` rebuilds the image.

## 6. Python side (`qualify_creative.render`)

`RemotionRenderClient` (httpx) implements exactly §4; `RemotionTemplateAdapter` wraps it
as a `GenerationProvider` (`GenerationTask.TEMPLATE_RENDER`) so the router, budget check
and usage events treat it like any other engine. `estimate` → `estimate_cost_usd` (0 on
our own server, ETA kept in params); `generate` → upload assets, `POST /render`, poll,
download each completed output, one `MediaWrite` per output with `output_port`.
