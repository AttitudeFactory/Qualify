"""The ways a seasonal recipe fails, as short machine codes the job stores in
`mark_failed(reason=...)` (the screen turns them into Spanish, never shows them raw)."""

from __future__ import annotations

#: The output is over its hard limit even at the lowest quality / fewest frames tried.
TOO_LARGE = "too_large"
#: FFmpeg exited with an error, timed out, or is missing / lacks a needed encoder.
FFMPEG_FAILED = "ffmpeg_failed"
#: The recipe needs a source the brand does not have (no logo, no approved image, a
#: product photo with no transparency to cut it out by).
NO_SOURCE = "no_source"
#: A source file exists but is not a readable image.
UNREADABLE_SOURCE = "unreadable_source"
#: `ffmpeg` is not on PATH, or this build lacks an encoder the recipe needs (`libx264`).
FFMPEG_MISSING = "ffmpeg_missing"
#: A recipe name this pipeline version does not know.
UNKNOWN_RECIPE = "unknown_recipe"


class RecipeError(Exception):
    """A recipe could not produce a valid output. `code` is one of the constants above;
    `transient` says whether running the same job again may succeed (FFmpeg killed by a
    signal — the container's OOM killer — or a timeout under load)."""

    def __init__(self, code: str, detail: str = "", *, transient: bool = False) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.transient = transient
