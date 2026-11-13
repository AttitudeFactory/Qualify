"""Stage `layer` of the image and carousel pipeline (ADR 49 §2.1, §2.3) — not built yet.

In: the base photograph(s) of stage `base` (or the owner's Galería media, §2.6), the brief
and the catalog. Out: one `LayerSpec` per slide — title, subtitle, optional call to
action, information blocks, a `layout_id` from the closed, versioned set shared with
`packages/render`, and `base_has_invented_text` (§8.2) — written by one Claude call that
sees the photos, and stored in `piece_layers` with its provenance.

m-25017283 builds it. Until then the words a still prints are the copy's hook and call to
action, set by stage `compose` exactly as before ADR 49.
"""
