"""Real, client-side video-frame thumbnails for the publish gallery (QUA-99 UX
follow-up, part 2 — "thumbnail real"). Native browser APIs only, no npm dependency, no
backend change: `URL.createObjectURL`, an off-screen `<video>` + `<canvas>`,
`canvas.toDataURL()`, a plain native `addEventListener`, and React's own
`useSyncExternalStore` — no Reflex upload internals.

**Three dead ends before this shape, each reproduced against a real build (not
theoretical) — worth keeping because the SAME mistake is easy to make again:**

1. **A per-tile hook reading the tile's OWN filename does not work inside
   `rx.foreach`.** Reflex's compiler hoists every hook to the TOP of the generated
   `Foreach_...` wrapper function — the per-item Var only comes into scope INSIDE the
   `.map()` call at the BOTTOM of that same function. `ReferenceError:
   item_rx_state_ is not defined` the moment a hoisted hook's body reaches for it.
2. **Reusing `rx.upload`'s own `filesById`/`UploadFilesContext` is not composable with
   this screen's `on_drop` wiring.** `filesById` is populated by `upload_file(id)`, a
   raw JS `Var` designed to be `on_drop`'s SOLE value — mixed into `on_drop`'s list
   alongside `PublishState.add_files` it raises `ValueError: Invalid event`.
3. **A single shared `useState` (QUA-99, first working version) only shares state
   WITHIN one compiled function scope.** All tiles live inside the SAME `Foreach_...`
   function, so a `useState` hoisted there is genuinely shared across tiles — that
   version worked for every video added AFTER the first tile existed. But the very
   FIRST video is always picked while the gallery still shows the EMPTY-STATE prompt
   (`_upload_widget(compact=False)`, `publishing_page.py`) — `rx.foreach` (and
   therefore `Foreach_...`, and therefore its `useState`) does not exist until
   `pending_items` is non-empty, which only happens AFTER that first file's own
   `change` event has already fired and is gone. Reported exactly this way: "el primer
   video no sale la imagen, los demás sí" (2026-09-10) — every video after the first
   already had a mounted, listening tile scope; the first never did.

**The fix: a store OUTSIDE React entirely** (`window.__qualifyPreviews`), written by a
capture listener that mounts UNCONDITIONALLY (`publishing_page._preview_capture_
anchor`, a sibling of the gallery's own `rx.cond`, never inside either of its
branches — mounted before ANY file is ever picked), and read by every tile via
`useSyncExternalStore` — the standard, native React 18+ API for exactly this "shared
mutable state outside a component tree, read from possibly-different component
scopes" situation. No `useState` anywhere in this module — the JS-level global is the
only source of truth, so it does not matter which compiled function a given
`useSyncExternalStore` call ends up hoisted into; they all read the SAME object.

**How one frame gets captured:** a `drop`/`change` event on the gallery root
(`_GALLERY_ROOT_ID`) triggers, for each file in it, a transient `blob:` URL → an
off-screen `<video>` → seek a fraction of a second in (frame 0 is sometimes still
black) → once `seeked` fires, draw that frame into an off-screen `<canvas>` → read it
back as a `data:` URI via `toDataURL()` → write it into the shared store, keyed by
filename, notifying every subscribed tile. The `blob:` URL is revoked IMMEDIATELY after
capture (success or failure) — never held onto, so there is nothing to leak; the
`data:` URI that replaces it is a plain string.

This never calls `preventDefault`/`stopPropagation`, so `rx.upload`'s own handling of
the identical `drop`/`change` event (`PublishState.add_files`) is completely
unaffected.
"""

from __future__ import annotations

from reflex.vars import VarData
from reflex.vars.base import Var
from reflex.vars.sequence import LiteralStringVar

# Guards `window.__qualifyPreviews`'s one-time setup — plain, idempotent statements
# (never a hook call itself), so it is safe to prepend to EVERY hook string in this
# module: whichever mounts first (the always-on capture anchor, or a tile's lookup)
# initializes it, every later one is a cheap no-op check.
#
# `typeof window !== "undefined"` FIRST, always: this file's component functions also
# run during SERVER-side rendering (this app prerenders/SSRs), where `window` itself is
# not declared — `typeof window.__qualifyPreviews` alone still throws there, because
# the `.` property access has to resolve `window` before `typeof` can act on the
# result; only a bare `typeof window` is safe against an undeclared identifier. Missing
# this the first time broke the production build outright (`ReferenceError: window is
# not defined`, 2026-09-10) — worth a comment precisely because the mistake is subtle
# and easy to reintroduce.
_STORE_SETUP = """
    if (typeof window !== "undefined" && typeof window.__qualifyPreviews === "undefined") {
      window.__qualifyPreviews = { data: {}, listeners: new Set(), lastFile: null };
      window.__qualifyPreviews.setPreview = function (filename, dataUri) {
        var next = Object.assign({}, window.__qualifyPreviews.data);
        next[filename] = dataUri;
        window.__qualifyPreviews.data = next;
        window.__qualifyPreviews.listeners.forEach(function (cb) { cb(); });
      };
    }
"""


def gallery_preview_capture_anchor(*, root_id: str) -> Var[str]:
    """Mount this UNCONDITIONALLY, once, wherever the gallery renders at all (see
    `publishing_page._preview_capture_anchor`) — its only job is to attach the
    `drop`/`change` listeners on `root_id` from the very first render onward, before
    any file has ever been picked. The returned `Var[str]` is always `""`; nothing
    reads it, it exists only so this has something to render (a hook needs an
    enclosing component to mount into).
    """
    root_id_var = LiteralStringVar.create(root_id)
    hook = f"""
    {_STORE_SETUP}
    useEffect(() => {{
      const root = document.getElementById({root_id_var!s});
      if (!root) {{ return undefined; }}
      const captureFile = (file) => {{
        // Kept alongside the thumbnail capture below so the "Abrir en
        // Instagram" button (`stories_page.py`) has a real File object to hand
        // to `navigator.share()` -- Stories is single-file, so the LAST one
        // dropped is always the one currently in the gallery.
        window.__qualifyPreviews.lastFile = file;
        let blobUrl = null;
        const releaseBlob = () => {{
          if (blobUrl) {{ URL.revokeObjectURL(blobUrl); blobUrl = null; }}
        }};
        const video = document.createElement("video");
        blobUrl = URL.createObjectURL(file);
        video.preload = "metadata";
        video.muted = true;
        video.playsInline = true;
        video.src = blobUrl;
        video.addEventListener("loadeddata", () => {{
          try {{
            video.currentTime = Math.min(0.1, (video.duration || 1) / 2);
          }} catch (seekErr) {{
            // Some codecs refuse a seek before more data arrives — 'seeked' below
            // simply never fires for this file, and the fallback icon stays showing.
          }}
        }});
        video.addEventListener("seeked", () => {{
          try {{
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth || 320;
            canvas.height = video.videoHeight || 180;
            canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
            window.__qualifyPreviews.setPreview(file.name, canvas.toDataURL("image/jpeg", 0.7));
          }} catch (captureErr) {{
            // Capture failed (e.g. a codec the browser can decode but not paint to a
            // canvas) -- leave the fallback icon in place rather than a broken image.
          }} finally {{
            releaseBlob();
          }}
        }});
        video.addEventListener("error", releaseBlob);
      }};
      const captureFrom = (fileList) => {{
        if (!fileList) {{ return; }}
        Array.from(fileList).forEach(captureFile);
      }};
      const onDrop = (event) => captureFrom(event.dataTransfer && event.dataTransfer.files);
      const onChange = (event) => captureFrom(event.target && event.target.files);
      // Delegation only -- never preventDefault/stopPropagation, so rx.upload's own
      // handling of the SAME event is completely unaffected. Attached ONCE (empty
      // dependency array): `root_id` names the gallery's own OUTER wrapper, which
      // stays mounted for the page's whole lifetime even while its INNER content
      // (the empty prompt vs. the tile grid) swaps — never re-attached, never lost.
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


def video_frame_preview_src(*, filename: Var[str]) -> Var[str]:
    """A reactive `Var[str]` — a `data:` URI of `filename`'s first video frame, once the
    gallery-wide capture anchor (`gallery_preview_capture_anchor`) has seen and
    processed it. Empty until then, or if a frame could never be captured (an
    unsupported codec) — callers treat empty as "not ready", not as an error, and show
    a fallback. `filename` is `PendingItemVM.filename`, a Var — it comes from
    `rx.foreach`.

    Reads the SAME shared store the anchor writes to via `useSyncExternalStore` — never
    its own `useState` (that only shared correctly within one compiled function scope,
    see the module docstring for why that was not enough).
    """
    # `getServerSnapshot` (the third argument) is what keeps `useSyncExternalStore`
    # itself SSR-safe: without it, React calls `getSnapshot` during server rendering
    # too, which would reach for `window` there. The empty-object snapshot is exactly
    # right for a server render anyway — no file has ever been dropped on the server.
    hook = f"""
    {_STORE_SETUP}
    const previews = useSyncExternalStore(
      (cb) => {{
        if (typeof window === "undefined" || !window.__qualifyPreviews) {{ return () => {{}}; }}
        window.__qualifyPreviews.listeners.add(cb);
        return () => window.__qualifyPreviews.listeners.delete(cb);
      }},
      () => {{
        if (typeof window === "undefined" || !window.__qualifyPreviews) {{ return {{}}; }}
        return window.__qualifyPreviews.data;
      }},
      () => ({{}})
    );
    """
    return Var(
        _js_expr=f'(previews[{filename!s}] || "")',
        _var_type=str,
        _var_data=VarData.merge(
            VarData(imports={"react": ["useSyncExternalStore"]}, hooks={hook: None}),
            filename._get_all_var_data(),
        ),
    ).guess_type()
