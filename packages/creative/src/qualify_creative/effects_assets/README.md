# Effects assets (EF-02, EF-08, ADR 50)

The files an effect's `preview_asset` names in `../effects_data/vN.json`: what the live
preview in the browser lays over the video (a layer's recorded loop, a «Con IA» effect's
example). A `preview_asset` of `effects/<id>/v<n>/<file>` is the file `<id>/v<n>/<file>`
in THIS folder (`qualify_creative.effects.preview_file`). The library does not load if a
non-null `preview_asset` has no file here (`MissingPreviewAsset`).

## The smoke, ember and steam loops (EF-08, m-25029102)

| Effect | File | What it is |
|---|---|---|
| Humo | `humo_capa/v1/preview.webm` | Grey wisps drifting up slowly over the top half of the frame |
| Brasas | `brasas_capa/v1/preview.webm` | Large orange-yellow sparks (70) rising from the bottom, wobbling, flickering and fading as they rise |
| Vapor | `vapor_capa/v1/preview.webm` | A soft, diffuse white column (rounded puffs over a veil) rising from the middle (a hot plate) and coming apart as it rises — no strands |

- **Format:** VP9 WebM, 720×1280 (9:16), 30 fps, 4 s (120 frames), yuv420p BT.709 limited
  range (tagged), on **pure black**. With a `screen` blend black changes nothing, so no
  alpha channel is needed. Recorded at intensity 1.0; the owner's intensity scales the
  loop's light before the blend (the same as CSS `opacity` on a `mix-blend-mode: screen`
  layer).
- **One file for the preview and the final video:** the browser lays it full-frame with
  `mix-blend-mode: screen`; the compose (`video/layer_overlay.py`) lays it with
  `blend=all_mode=screen` in RGB. The same pixels in the preview and in the published video.
- **Exact loop:** every motion turns a whole number of times per loop (Fourier noise with
  whole temporal frequencies; particles with whole cycles), so frame 120 would be frame 0:
  no jump on repeat (last→first difference ≈ one normal frame step, ≤ 1.5 of 255).
- **How they are made:**
  `uv run --no-sync python packages/creative/scripts/make_effect_loops.py [--only ID] [--force]`
  (fixed seeds 801/802/803; numpy + PyAV only). It writes here and copies byte for byte to
  the repo-root `assets/effects/<id>/v1/preview.webm` the editor screen serves. A test
  (`test_video_layer_overlay.py`) requires both copies to have the same sha256: they never
  drift. **It refuses to overwrite an existing `preview.webm` unless `--force`** (or
  `--out DIR` to write elsewhere): the published `v1/` bytes are what each composed video's
  provenance names (`loop_sha256`), and another libvpx would write other bytes.
- **A change of look** is new bytes, so it goes to a new folder (`<id>/v2/`) with a new
  library entry at version 2 — never new bytes in a published `v1/`.
- **Cost: US$0.** Procedurally generated: no vendor, no download, no third-party licence.
- **Decision (m-25029102):** record them ourselves, procedurally, instead of buying them or
  generating them with AI — zero cost per piece, no third-party rights, reproducible and as
  small as we need (< 150 KB each). The library v3 (`effects_data/v3.json`) offers them
  («Gratis»); v1 and v2 still do not.
- **Why the entries stay at version 1 (an explicit exception):** v3 offers the three layers
  at entry version 1, fills their empty `preview_asset` and adds `categories`, while their
  params and asset folder did not change. Nobody could use version 1 while it was not
  offered, and the editor sends version 1. A future change of a loop (other bytes in `v1/`)
  does require `v2/` and an entry at version 2.

## Where they live, and why

Global and read-only: never a business's file, never under `t/`, never in R2 (nothing can
purge them — the bucket's lifecycle and retention rules never see them). They ship inside
the package (and so inside the image). The compose reads a loop only through
`qualify_creative.effects.layer_loop_file(entry)`, a read-only door that refuses anything
that is not a library layer or that resolves outside this folder. Nothing writes here at
runtime.
