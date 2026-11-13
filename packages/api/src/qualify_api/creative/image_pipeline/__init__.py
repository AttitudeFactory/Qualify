"""The image and carousel pipeline (ADR 49, signed 2026-11-13; epic m-25017272).

Four stages with typed hand-offs between them (ADR 49 §2.3):

| Stage | Module | In → out |
|---|---|---|
| `base` | `base`, `base_prompt` | brief, products, format → the Seedream photograph (`BaseScene`) |
| `layer` | `layer` | base photo(s), brief, catalog → one text layer per slide (m-25017283) |
| `compose` | `compose` | base photo + text → the finished stills as `MediaWrite`s |
| `check` | `check` | the composed stills → approved, or one corrected layer (m-25017287) |

m-25017278 moved the image and carousel code here out of `media.py` with no change in
behaviour: the same prompts, the same vendor calls, the same rows. Composition is still
Pillow's (`qualify_creative.compose`) until m-25017285 / m-25017293; `layer` and `check`
are empty seams their stories fill. `media.py` keeps the dispatch by `ContentKind`, the
video paths and every helper the video paths share (the prompt budget, the text rules,
`_physical_scene_plan`, the gallery resume helpers); this package imports them.
"""

# Load order (m-25017278): the stages import `media`'s shared helpers at their top, and
# `media` imports the stages at its bottom. Loading `media` first — whichever module of
# the two is imported first — means `media` always reaches its bottom with every helper
# defined before a stage asks for one.
from qualify_api.creative import media as _media  # noqa: F401
