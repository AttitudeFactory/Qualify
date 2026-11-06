"""m-24820836: replication without a VLM, through the existing Clip pipeline."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.referentes import reel_reference
from qualify_api.referentes.reels_ai import REPLICATION_ANALYSIS_VERSION
from qualify_creative.prompt_text import REEL_METADATA_MARKER, replication_prose


def source_reel_provenance(card: dict[str, str]) -> dict[str, str]:
    """m-24820837: the structured origin of the reel behind a replica — the same fields
    `MediaInputs.source_reel` stores, as strings, ready for the generator's media payload.
    The card lives only in this session; the stored brief is what lets the piece name its
    origin later, after the reel has left discovery."""
    return {
        "platform": card.get("network", ""),
        "post_id": card.get("id", ""),
        "url": card.get("url", ""),
        "handle": card.get("handle", ""),
        "analysis_version": str(REPLICATION_ANALYSIS_VERSION),
    }


def import_reference(tenant_id: UUID, card: dict[str, str]) -> dict[str, str]:
    """Store a prepared motion reference like an upload, scoped to this session's tenant.

    The reference is prepared on the server from the copy of the idea's video the run
    kept (`reel_reference.prepare_idea_reference`, founder 2026-11-04), by the card's
    network and reel id — never from a URL: the CDN link dies in a day and the browser
    must not choose what the server downloads. Raises `ReelReferenceUnavailable` with a
    plain sentence when that copy is not there."""
    fitted = reel_reference.prepare_idea_reference(card.get("network", ""), card.get("id", ""))
    key = f"uploads/{tenant_id}/{uuid4().hex}_referencia-reel.mp4"
    target = rx.get_upload_dir() / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(fitted.data)
    return {
        "key": key,
        "name": f"Referencia de {card.get('handle', 'un reel')} · {fitted.duration_sec:.0f} s",
        "seconds": str(fitted.duration_sec),
    }


def replication_context(card: dict[str, str], product: str) -> str:
    """Build the «copiar» background layer: the reel's structure as a sequence guide,
    never its visual style. The brand identity (Brand Kit + the operator's context) is
    applied on top and takes priority; this text is the *background* layer that
    ``_effective_topic`` merges under the operator's foreground words.

    Use only observed metadata; never claim to have inferred shots or timestamps."""
    data = {
        key: card.get(key, "")[:1200]
        for key in (
            "network",
            "id",
            "url",
            "handle",
            "caption",
            "transcript",
            "sound",
            "format",
            "hook",
        )
    }
    # m-24820842: the guidance is the versioned template the edit compiler recognizes
    # (`qualify_creative.prompt_text`), never a second copy of its wording.
    return replication_prose(product) + REEL_METADATA_MARKER + json.dumps(data, ensure_ascii=False)


#: How many of the Brand Kit's phrases the replica's brand-text option names.
CTA_PREVIEW_LIMIT = 3
#: «Resumen»'s «Textos del video» row on a reel replica (m-24820842).
REPLICA_TEXT_ON = "Con tus frases para invitar a comprar"
#: Off, the edit removes the other brand's slogans and adds no Brand Kit phrase — only
#: neutral or mandatory labels stay (`qualify_api.creative.media`'s replica text rule).
#: Not «como en el reel original» (UX review 2026-11-03): its texts do not stay.
REPLICA_TEXT_OFF = "Quitamos los textos de la otra marca y no agregamos tus frases"


def has_reel_video(videos: list[dict[str, str]]) -> bool:
    """The clip edits a discovered reel: its original video is still among its videos."""
    return any(item.get("source") == "reel" for item in videos)


def cta_lines(phrases: list[str], limit: int = CTA_PREVIEW_LIMIT) -> list[str]:
    """m-24820842: the Brand Kit phrases a replica may use, one a line as the owner reads
    them — at most ``limit``, then «y N más»; [] when there is none."""
    lines = [f"«{phrase}»" for phrase in phrases[:limit]]
    rest = len(phrases) - len(lines)
    return [*lines, f"y {rest} más"] if rest > 0 else lines
