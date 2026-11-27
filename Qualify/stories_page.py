"""The historia-only piece of «Publicar ahora» (`/publish`): «Abrir en Instagram».

Since 2026-11-12 a historia (one or several) is published by the same engine as any
other publication (`publish_engine.py`, driven by `PublishState`); before that it had
its own state (`StoriesState`, removed) and its own status block. What stays here is the
phone handoff for official music: with exactly one file, the review offers to open it in
Instagram's own composer instead. `/stories` redirects to `/publish?flow=stories`.

Since 2026-11-16 the gallery (`/aprobados`, `/drafts`) offers the same handoff on an
approved historia, on Android only, fetching the piece's own file
(`STORY_SHARE_FROM_URL_JS`); both scripts share `_SHARE_CORE_JS`.

History: QUA-106 V1 built this as its own screen; QUA-113 moved it inside `/publish`;
PUBLICAR-4 folded it into the assistant's steps.
"""

from __future__ import annotations

from collections.abc import Callable

import reflex as rx

from .publishing_state import PublishState
from .r2_media import BACKEND_BASE
from .ui import tokens as T
from .ui.video_preview import gallery_file_js

# ---------------------------------------------------------------------------
# "Abrir en Instagram" -- Web Share API handoff (PoC validated on real
# Android + iPhone devices: `navigator.share` with the video File opens
# Instagram's own Story composer with the video pre-loaded and the Music
# sticker fully available). An ALTERNATIVE to "Publicar", never a step of it:
# Meta's Graph API cannot attach a native Music sticker to a Story
# (`audio_configuration` only ever applies to Reels), so this hands the file
# to the phone's OS share sheet instead, and the owner finishes the historia
# inside Instagram. It never touches Meta's Graph API.
#
# The File itself never round-trips through Reflex state or the server:
# `ui/video_preview.py`'s drop/change capture listener stashes the raw File per
# gallery root, and the script reads the slot of the gallery it is given
# (`gallery_file_js(root_id)`). Since PUBLICAR-4 that is step 1's gallery; the
# page clears the slot whenever a file is removed (so a removed file can never
# be the one shared) and only offers the button with exactly one file selected.
#: The handoff itself, shared by `/publish` and the gallery: a JS function of the File
#: (and whether it was just fetched — then a share refused for want of a fresh tap says
#: «tap_again» and the File stays cached for that tap).
_SHARE_CORE_JS = """
function (file, fetched) {
  if (!file) { return "no_file"; }
  if (!navigator.canShare({ files: [file] })) { return "cannot_share_file"; }
  return navigator.share({ files: [file] }).then(
    function () { return "shared"; },
    function (err) {
      if (err && err.name === "AbortError") { return "cancelled"; }
      if (fetched && err && err.name === "NotAllowedError") { return "tap_again"; }
      return "error:" + (err && err.message ? err.message : String(err));
    }
  );
}
"""

#: The browser checks both handoffs need before touching any file.
_SHARE_GUARDS_JS = """
    if (!window.isSecureContext) { return "insecure"; }
    if (!navigator.share || !navigator.canShare) { return "unsupported"; }
"""

_SHARE_SCRIPT_TEMPLATE = (
    """
(function () {
  try {
    // Desktop OS share panels (Windows' "Compartir", macOS' share sheet) may list
    // "Instagram" too, but Instagram there is web/desktop -- it never registers
    // itself to actually RECEIVE the shared file into a Story composer the way the
    // real Instagram mobile app does. Selecting it just drops the user on a plain
    // "select a story" screen with nothing attached (reported 2026-09-23 testing
    // from a Windows PC). Gating on the OS keeps that dead-end out of reach.
    var isMobileOS = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || "");
    if (!isMobileOS) { return "desktop"; }
"""
    + _SHARE_GUARDS_JS
    + """
    return ("""
    + _SHARE_CORE_JS
    + """)(__STORIES_GALLERY_FILE__, false);
  } catch (e) {
    return "error:" + (e && e.message ? e.message : String(e));
  }
})()
"""
)

#: The gallery's handoff (founder 2026-11-16): ANDROID ONLY, and the File is fetched
#: from the piece's own `/r2media/` path (or http(s) URL) in the browser, never through
#: Reflex state. `navigator.share` needs the tap's transient activation, which Chrome on
#: Android keeps ~5 s — enough for one story. When the fetch outlasts it, the File stays
#: in ONE slot (`__qualifyStoryShare`, the last historia only) and the owner taps again.
STORY_SHARE_FROM_URL_JS = (
    """(function (url, buttonId) {
  var button = null;
  var done = function () {
    window.__qualifyStoryBusy = false;
    if (button) {
      button.disabled = false;
      button.removeAttribute("data-busy");
      button.removeAttribute("aria-busy");
    }
  };
  try {
    if (!/Android/i.test(navigator.userAgent || "")) { return "not_android"; }
"""
    + _SHARE_GUARDS_JS
    + """
    var share = ("""
    + _SHARE_CORE_JS
    + """);
    var slot = window.__qualifyStoryShare;
    if (slot && slot.url === url && slot.file) { return share(slot.file, false); }
    // One download at a time: a second tap while it runs does nothing.
    if (window.__qualifyStoryBusy) { return "busy"; }
    window.__qualifyStoryBusy = true;
    // The button says «Preparando tu historia…» and is off while the file downloads —
    // set here, not through state, so the tap keeps its activation for the share.
    button = document.getElementById(buttonId);
    if (button) {
      button.disabled = true;
      button.setAttribute("data-busy", "true");
      button.setAttribute("aria-busy", "true");
    }
    return fetch(url, { mode: "cors", credentials: "omit" }).then(function (response) {
      if (!response.ok) { done(); return "fetch_failed"; }
      return response.blob().then(function (blob) {
        var type = blob.type || "image/jpeg";
        var ext = type.indexOf("video/") === 0 ? ".mp4" : (type === "image/png" ? ".png" : ".jpg");
        var file = new File([blob], "historia" + ext, { type: type });
        window.__qualifyStoryShare = { url: url, file: file };
        done();
        return share(file, true);
      }, function () { done(); return "fetch_failed"; });
    }, function () { done(); return "fetch_failed"; }).catch(function (e) {
      done();
      return "error:" + (e && e.message ? e.message : String(e));
    });
  } catch (e) {
    done();
    return "error:" + (e && e.message ? e.message : String(e));
  }
})"""
)


def share_to_instagram_script(root_id: str) -> str:
    """The handoff script, reading the File stashed for gallery `root_id`."""
    return _SHARE_SCRIPT_TEMPLATE.replace("__STORIES_GALLERY_FILE__", gallery_file_js(root_id))


def share_to_instagram_button(*, root_id: str, enabled: rx.Var[bool]) -> rx.Component:
    """«Abrir en Instagram» plus its one-line reason — needs no connected account."""
    return rx.vstack(
        rx.button(
            rx.icon("share-2", size=16),
            "Abrir en Instagram ↗",
            on_click=rx.call_script(
                share_to_instagram_script(root_id), callback=PublishState.handle_share_result
            ),
            disabled=~enabled,
            variant="soft",
            size="3",
            width="100%",
            min_height="44px",
        ),
        rx.text(
            "¿Quieres ponerle música oficial? Ábrela en Instagram desde tu teléfono y "
            "termínala allá. Así no sale desde Qualify.",
            size="1",
            color=T.TEXT_FAINT,
        ),
        spacing="1",
        width="100%",
        align_items="stretch",
    )


def story_share_source_src(path: rx.Var[str]) -> rx.Var[str]:
    """Where the browser fetches a gallery historia's file: a `/r2media/` path is the
    backend's (another origin in development, as `download_buttons` knows), an http(s)
    URL is used as it is."""
    return rx.cond(path.startswith("/r2media"), BACKEND_BASE + path, path).to(str)


def story_share_button_id(post_id: rx.Var[str]) -> rx.Var[str]:
    """The DOM id the gallery script marks busy while it downloads (one per card)."""
    return ("story-share-" + post_id).to(str)


def js_literal(value: rx.Var[str]) -> rx.Var[str]:
    """`value` as a JSON string literal inside generated JS: no quote in a URL or an id
    can ever end the literal early (`JSON.stringify` runs on the value, in the page)."""
    return rx.Var(_js_expr=f"JSON.stringify({value!s})", _var_data=value._get_all_var_data()).to(
        str
    )


def story_share_from_url(
    path: rx.Var[str], button_id: rx.Var[str], callback: Callable
) -> rx.event.EventSpec:
    """The gallery's «Abrir en Instagram» click (Android only, `STORY_SHARE_FROM_URL_JS`):
    it runs in the browser straight from the tap, so the share keeps its user gesture."""
    src = js_literal(story_share_source_src(path))
    target = js_literal(button_id)
    return rx.call_script(f"{STORY_SHARE_FROM_URL_JS}({src}, {target})", callback=callback)
