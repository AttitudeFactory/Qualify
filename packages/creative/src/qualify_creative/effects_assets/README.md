# Effects assets (EF-02, ADR 50)

The files an effect's `preview_asset` names in `../effects_data/vN.json`: what the live
preview in the browser lays over the video (a layer's recorded loop, a «Con IA» effect's
example). A `preview_asset` of `effects/<id>/v<n>/<file>` is the file `<id>/v<n>/<file>`
in THIS folder (`qualify_creative.effects.preview_file`). The library does not load if a
non-null `preview_asset` has no file here (`MissingPreviewAsset`).

Empty in v1: every offered effect of v1 is simulated by the browser (the text, the
transitions), and the layers and «Con IA» effects are not offered yet. The ticket that
records the smoke, ember and steam loops adds them here and marks them `offered`.

Global and read-only: never a business's file, never under `t/`.
