"""The historia pieces of «Publicar ahora» (`/publish`).

Since PUBLICAR-4 (m-24842986) `/publish` is ONE three-step assistant
(`publishing_page.py`): the photo or video is picked in step 1, «Historia (24 h)» and
the account in step 2, and step 3 reviews and publishes — through `StoriesState`
when the owner chose a historia (`PublishHubState.publish_now` hands the one file
over). What stays here is only what is specific to a historia: its progress/result
block and the «Abrir en Instagram» phone handoff for official music. `/stories`
redirects to `/publish?flow=stories`, which arrives with «Historia» already chosen.

History: QUA-106 V1 built this as its own screen; QUA-113 moved it inside `/publish`
as a second form; PUBLICAR-4 folded that form into the assistant's steps.
"""

from __future__ import annotations

import reflex as rx

from .stories_state import StoriesState
from .ui import callout, loading_spinner
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
_SHARE_SCRIPT_TEMPLATE = """
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
    if (!window.isSecureContext) { return "insecure"; }
    if (!navigator.share || !navigator.canShare) { return "unsupported"; }
    var file = __STORIES_GALLERY_FILE__;
    if (!file) { return "no_file"; }
    if (!navigator.canShare({ files: [file] })) { return "cannot_share_file"; }
    return navigator.share({ files: [file] }).then(
      function () { return "shared"; },
      function (err) {
        if (err && err.name === "AbortError") { return "cancelled"; }
        return "error:" + (err && err.message ? err.message : String(err));
      }
    );
  } catch (e) {
    return "error:" + (e && e.message ? e.message : String(e));
  }
})()
"""


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
                share_to_instagram_script(root_id), callback=StoriesState.handle_share_result
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


def stories_status_block() -> rx.Component:
    """Progress and failure of a historia being published. Success has no arm: the
    page replaces the whole assistant with its «listo» (N3)."""
    return rx.match(
        StoriesState.phase,
        (
            "staging_and_starting",
            callout(
                rx.hstack(
                    loading_spinner("sm"),
                    rx.text("Subiendo tu historia...", size="2"),
                    spacing="2",
                    align="center",
                ),
                "neutral",
                icon="upload",
            ),
        ),
        (
            "polling",
            callout(
                rx.vstack(
                    rx.hstack(
                        loading_spinner("sm"),
                        rx.text(
                            "Publicando, esperando que Instagram lo confirme...",
                            size="2",
                            weight="medium",
                        ),
                        rx.cond(
                            StoriesState.elapsed_label != "",
                            rx.text(
                                StoriesState.elapsed_label,
                                size="1",
                                color=T.TEXT_FAINT,
                                class_name="q-mono q-nums",
                            ),
                            rx.fragment(),
                        ),
                        spacing="2",
                        align="center",
                        width="100%",
                    ),
                    rx.text(
                        "Instagram está preparando tu historia. Puede tardar unos minutos.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                "warn",
                icon="clock",
            ),
        ),
        ("failure", callout(StoriesState.error, "error")),
        rx.fragment(),
    )
