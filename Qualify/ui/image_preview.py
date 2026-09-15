"""Real, client-side image thumbnails for the publish gallery (QUA-103) — the IMAGE
sibling of `video_preview.py`, extending the SAME shared mechanism rather than touching
it.

**Reuses, unmodified:** `window.__qualifyPreviews` (the shared, outside-React store) and
`video_frame_preview_src` (`video_preview.py`) — that reader is already a generic
`previews[filename] || ""` lookup, agnostic of whether the entry was written by a video
frame capture or, as this module adds, a plain image read. There is exactly ONE reader
for both kinds; `publishing_page.py` calls the same function for an image tile and a
video tile.

**What this module adds — a SECOND, independent capture anchor, not an edit to the
first.** `video_preview.py`'s own capture anchor (`gallery_preview_capture_anchor`)
already attaches `drop`/`change` listeners on the gallery root and is NOT touched by
this file — its `captureFile` only ever looks at files it can build a `<video>` from.
This module mounts its OWN listener on the SAME root id, which is completely safe:
multiple `addEventListener` calls for the same event type on the same element all fire,
independently, in the order they were attached; neither this module nor `video_preview.py`
calls `preventDefault`/`stopPropagation`, so mounting a second listener changes nothing
about the first. Each anchor filters to the file kind it cares about (this one:
`image/jpeg` or a `.jpg`/`.jpeg` name) and ignores everything else — a dropped video is
invisible to this module, a dropped image is invisible to `video_preview.py`'s.

**Why `FileReader.readAsDataURL`, not the `URL.createObjectURL` + `<canvas>` dance
`video_preview.py` needs:** a video frame has to be DECODED (there is no frame to read
until the browser plays/seeks the file) — an image file's bytes ARE already the picture.
`FileReader` reads the file directly into a `data:` URI; no blob URL, no revocation
lifecycle, no off-screen element, no seek timing. This is the "simpler case, not a
rewrite" the ticket asks for — the video path above is untouched precisely because this
one needed none of its machinery.
"""

from __future__ import annotations

from reflex.vars import VarData
from reflex.vars.base import Var
from reflex.vars.sequence import LiteralStringVar

# Same store-setup guard `video_preview.py` uses — idempotent, safe to prepend to every
# hook string in this module too; whichever of the two capture anchors mounts first
# initializes `window.__qualifyPreviews`, the other's setup is then a cheap no-op check.
_STORE_SETUP = """
    if (typeof window !== "undefined" && typeof window.__qualifyPreviews === "undefined") {
      window.__qualifyPreviews = { data: {}, listeners: new Set() };
      window.__qualifyPreviews.setPreview = function (filename, dataUri) {
        var next = Object.assign({}, window.__qualifyPreviews.data);
        next[filename] = dataUri;
        window.__qualifyPreviews.data = next;
        window.__qualifyPreviews.listeners.forEach(function (cb) { cb(); });
      };
    }
"""


def gallery_image_preview_capture_anchor(*, root_id: str) -> Var[str]:
    """Mount this UNCONDITIONALLY, once, wherever the gallery renders — same convention
    as `video_preview.gallery_preview_capture_anchor`, and meant to be mounted
    ALONGSIDE it, never instead of it. Attaches `drop`/`change` listeners on `root_id`
    that read only JPEG files (by declared type, falling back to the filename extension
    for the same reason `publishing_state._resolve_media` does — some browsers omit or
    mangle a dropped file's `type`) directly into the shared preview store. The returned
    `Var[str]` is always `""`; nothing reads it, it exists only so this has something to
    render (a hook needs an enclosing component to mount into).
    """
    root_id_var = LiteralStringVar.create(root_id)
    hook = f"""
    {_STORE_SETUP}
    useEffect(() => {{
      const root = document.getElementById({root_id_var!s});
      if (!root) {{ return undefined; }}
      const isJpeg = (file) => {{
        const type = (file.type || "").toLowerCase();
        if (type === "image/jpeg") {{ return true; }}
        const name = (file.name || "").toLowerCase();
        return name.endsWith(".jpg") || name.endsWith(".jpeg");
      }};
      const captureFile = (file) => {{
        if (!isJpeg(file)) {{ return; }}
        const reader = new FileReader();
        reader.onload = () => {{
          if (typeof reader.result === "string") {{
            window.__qualifyPreviews.setPreview(file.name, reader.result);
          }}
        }};
        // A read failure (corrupt file, browser quota) simply leaves no entry for this
        // filename — the tile's fallback icon stays showing, same as an uncaptured
        // video frame; nothing here needs to surface an error of its own.
        reader.readAsDataURL(file);
      }};
      const captureFrom = (fileList) => {{
        if (!fileList) {{ return; }}
        Array.from(fileList).forEach(captureFile);
      }};
      const onDrop = (event) => captureFrom(event.dataTransfer && event.dataTransfer.files);
      const onChange = (event) => captureFrom(event.target && event.target.files);
      root.addEventListener("drop", onDrop);
      root.addEventListener("change", onChange);
      return () => {{
        root.removeEventListener("drop", onDrop);
        root.removeEventListener("change", onChange);
      }};
    }}, []);
    """
    return Var(
        _js_expr='""',
        _var_type=str,
        _var_data=VarData(imports={"react": ["useEffect"]}, hooks={hook: None}),
    ).guess_type()
