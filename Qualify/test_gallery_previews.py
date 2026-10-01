"""Tests for the per-gallery isolation of the shared preview store (QUA-113, Fase 1) —
`ui/video_preview.py` / `ui/image_preview.py`. Two galleries can now share one page
(Publicaciones and Stories), so every thumbnail and every kept `File` must be scoped
to the gallery root that captured it. These are string-level pins on the generated
JS: the store itself only exists in a browser (manual check in the QUA-113 report).
"""

from __future__ import annotations

import reflex as rx

from .ui import image_preview, video_preview

_PUBLISH_ROOT = "publish-gallery-root"
_STORIES_ROOT = "stories-gallery-root"


def _hooks(var: rx.Var) -> str:
    var_data = var._get_all_var_data()
    assert var_data is not None
    return "\n".join(var_data.hooks)


def test_preview_keys_are_scoped_to_their_gallery_root() -> None:
    publish_key = video_preview.preview_key_js(_PUBLISH_ROOT, "file.name")
    stories_key = video_preview.preview_key_js(_STORIES_ROOT, "file.name")

    assert publish_key != stories_key
    assert f'"{_PUBLISH_ROOT}"' in publish_key
    assert f'"{_STORIES_ROOT}"' in stories_key


def test_thumbnail_reader_looks_up_its_own_gallerys_key() -> None:
    filename = rx.Var.create("clip.mp4")

    publish_src = video_preview.video_frame_preview_src(root_id=_PUBLISH_ROOT, filename=filename)
    stories_src = video_preview.video_frame_preview_src(root_id=_STORIES_ROOT, filename=filename)

    assert _PUBLISH_ROOT in str(publish_src) and _STORIES_ROOT not in str(publish_src)
    assert _STORIES_ROOT in str(stories_src) and _PUBLISH_ROOT not in str(stories_src)


def test_video_capture_keeps_the_file_per_gallery_not_page_globally() -> None:
    hooks = _hooks(video_preview.gallery_preview_capture_anchor(root_id=_STORIES_ROOT))

    assert "lastFile" not in hooks
    assert f'filesByRoot["{_STORIES_ROOT}"] = file' in hooks
    assert video_preview.preview_key_js(_STORIES_ROOT, "file.name") in hooks


def test_image_capture_writes_thumbnails_under_its_gallery_key() -> None:
    hooks = _hooks(image_preview.gallery_image_preview_capture_anchor(root_id=_PUBLISH_ROOT))

    assert video_preview.preview_key_js(_PUBLISH_ROOT, "file.name") in hooks
    assert "setPreview(file.name" not in hooks


def test_image_capture_keeps_the_file_per_gallery_for_an_image_story() -> None:
    """QUA-113: "Abrir en Instagram" can share an image Story too — so the image
    anchor keeps the raw File in the SAME per-gallery slot the video anchor uses."""
    hooks = _hooks(image_preview.gallery_image_preview_capture_anchor(root_id=_STORIES_ROOT))

    assert f'filesByRoot["{_STORIES_ROOT}"] = file' in hooks
    assert "lastFile" not in hooks


def test_both_capture_anchors_share_one_store_definition() -> None:
    """Whichever anchor mounts first creates `window.__qualifyPreviews` — the two must
    never disagree on its shape (e.g. one without `filesByRoot`)."""
    assert image_preview._STORE_SETUP is video_preview._STORE_SETUP
    assert "filesByRoot: {}" in video_preview._STORE_SETUP


def test_gallery_file_reads_only_the_named_root() -> None:
    expr = video_preview.gallery_file_js(_STORIES_ROOT)

    assert f'filesByRoot["{_STORIES_ROOT}"]' in expr
    assert _PUBLISH_ROOT not in expr
    assert expr.endswith("|| null)")
