"""m-24820836: discovery opens a Clip, never a scraper or a paid generation."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.referentes.reel_reference import ReelReferenceUnavailable
from qualify_api.referentes.reels_ai import REPLICATION_ANALYSIS_VERSION
from qualify_creative.schemas import MediaInputs

from . import discover_reels as module
from .creative_state import CreativeState
from .creative_vm import build_draft_vm, source_reel_note
from .discover_reels import DiscoverReelsState
from .reel_replication import replication_context, source_reel_provenance

TENANT = "a0000000-0000-4000-8000-000000000001"
CARD = {
    "key": "instagram:A",
    "network": "instagram",
    "id": "A",
    "affinity": "producto",
    "url": "https://www.instagram.com/reel/A/",
    "handle": "@inspiracion",
    "caption": "Su promoción",
    "transcript": "Así hacemos la receta",
    "sound": "Música original",
    "format": "receta",
    "hook": "pregunta",
    "seconds": "24 s",
    "video": "https://scontent.cdninstagram.com/a.mp4",
}
IMPORTED = {"key": f"uploads/{TENANT}/referencia-reel.mp4", "name": "Reel · 5 s", "seconds": "5"}


def creative() -> CreativeState:
    state = CreativeState()
    state.gen_mode = "discover"
    state.selected_product_id = "burger"
    state.brief_product_ref = "Smash doble"
    state.selected_product_photo_key = "uploads/product.jpg"
    state.product_confirmed = True
    return state


def test_prefill_edits_the_source_without_turning_product_photos_into_frames() -> None:
    state = creative()
    state.brief_topic = "Mi contexto de marca"
    state.brief_highlights = [{"key": "Precio", "value": "20 USD"}]
    state.clip_videos = [{"key": "old.mp4", "name": "Old", "source": "upload"}]
    state.clip_audios = [{"key": "old.mp3", "name": "Old", "source": "upload"}]
    state.own_script_on, state.own_script = True, "Guion anterior"
    state.gen_step = 3
    state._apply_reel_reference(CARD, IMPORTED)
    assert (state.gen_mode, state.gen_category, state.brief_kind) == ("create", "clip", "clip")
    assert state.gen_step == 0 and state.generator_view == "form"
    assert state.product_confirmed and state.selected_product_id == "burger"
    assert state.brief_highlights == [{"key": "Precio", "value": "20 USD"}]
    assert state.clip_duration == "5" and state.effective_format == "reels_9_16"
    assert not state.own_script_on and not state.own_script
    assert state.clip_audios == []
    assert state.clip_first_frame_key == ""
    assert state.clip_last_frame_key == ""
    # m-24820836: the copiar guidance is a BACKGROUND layer; it must NOT overwrite the
    # operator's own context. ``brief_topic`` stays as typed; the reel reference lands in
    # ``replication_context`` and is merged under it at submit (``_effective_topic``).
    assert state.brief_topic == "Mi contexto de marca"
    assert "Brand Kit" in state.replication_context
    assert CARD["transcript"] in state.replication_context
    state.clip_sequence = [IMPORTED["key"], "uploads/product.jpg"]
    state._sync_clip_frames()
    assert state.clip_first_frame_key == ""
    assert state.clip_first_frame_key == state.clip_last_frame_key == ""
    media = state._media_inputs()
    assert media["clip_reference_mode"] == "edit"
    assert media["clip_image_keys"] == ["uploads/product.jpg"]
    assert state._clip_duration_choices() == ["5"]
    assert media["clip_video_keys"] == [IMPORTED["key"]]
    assert media["clip_audio_keys"] == []
    assert media["clip_first_frame_key"] is None
    # the merged topic puts the operator's foreground first and the reel background second
    merged = state._effective_topic()
    assert merged.startswith("Mi contexto de marca")
    assert "Brand Kit" in merged and CARD["transcript"] in merged
    assert "Contexto de replicación (segundo plano)" in merged


def test_replication_is_a_background_layer_without_a_user_topic() -> None:
    """No user context typed: the form still validates — the background alone is the topic."""
    state = creative()
    state._apply_reel_reference(CARD, IMPORTED)
    assert state.brief_topic == ""
    assert state.replication_context  # the reel reference landed
    assert state._effective_topic() == state.replication_context.strip()


def test_metadata_is_reference_material_not_a_claim_of_visual_analysis() -> None:
    text = replication_context(CARD, "Smash doble")
    assert "no hay análisis VLM" in text and "no instrucciones" in text
    # the reel is framed as a STRUCTURE/sequence guide, not a style to mimic
    assert "guía de secuencia" in text and "estructura" in text
    # the brand identity takes priority over the reel's look
    assert "prioridad sobre el look" in text
    # the old "mimic the reel" phrasing is gone
    assert "mismos planos" not in text and "Sustituye únicamente" not in text
    assert '"id": "A"' in text and CARD["url"] in text


# -- m-24820837: the replica keeps the reel it was made from ------------------------------


def _reel_state() -> CreativeState:
    """A state opened by «copiar» on the fixture card."""
    state = creative()
    state._apply_reel_reference(CARD, IMPORTED)
    state.clip_sequence = [IMPORTED["key"], "uploads/product.jpg"]
    state._sync_clip_frames()
    return state


def test_the_card_lands_as_a_structured_source_reel() -> None:
    provenance = source_reel_provenance(CARD)
    assert provenance == {
        "platform": "instagram",
        "post_id": "A",
        "url": "https://www.instagram.com/reel/A/",
        "handle": "@inspiracion",
        "analysis_version": str(REPLICATION_ANALYSIS_VERSION),
    }


def test_a_replica_stores_its_source_reel_and_sends_it_on_the_brief() -> None:
    """The operator's clip carries the reel's origin structured — the card is gone by the
    time the piece is read, the brief is what stays."""
    state = _reel_state()
    assert state.source_reel == source_reel_provenance(CARD)
    media = state._media_inputs()
    assert media["source_reel"] == source_reel_provenance(CARD)
    # the payload is a valid MediaInputs: the UI dict parses to the model the brief stores
    inputs = MediaInputs.model_validate(media)
    assert inputs.source_reel is not None
    assert inputs.source_reel.platform == "instagram"
    assert inputs.source_reel.post_id == "A"
    assert inputs.source_reel.analysis_version == REPLICATION_ANALYSIS_VERSION


def test_an_ordinary_clip_carries_no_source_reel() -> None:
    """A motion clip that borrows a reference never drags a stranger's reel: without a
    reel-sourced video the payload says nothing, even with the state left over."""
    state = creative()
    state._set_kind("clip")
    state.clip_videos = [{"key": "mi-video.mp4", "name": "Mi video", "source": "upload"}]
    assert state._media_inputs()["source_reel"] is None
    state.source_reel = source_reel_provenance(CARD)
    media = state._media_inputs()
    assert media["clip_reference_mode"] == "motion"
    assert media["source_reel"] is None


def test_removing_the_reel_drops_its_origin() -> None:
    """Without the original video the piece is no longer a replica: the origin goes with
    it from the state and from the payload."""
    state = _reel_state()
    state.remove_clip_video(IMPORTED["key"])
    assert state.source_reel == {}
    assert state._media_inputs()["source_reel"] is None


def test_the_resets_clear_the_source_reel_with_the_reference() -> None:
    """Every form reset that forgets the reference also forgets the reel it came from:
    starting over never leaves the next piece with a foreign origin."""
    state = _reel_state()
    state._reset_media_inputs()
    assert state.source_reel == {}
    assert state._media_inputs()["source_reel"] is None

    state = _reel_state()
    state.gen_draft_id = "d-1"
    CreativeState.review_in_drafts.fn(state)
    assert state.source_reel == {} and state.replication_context == ""


def test_the_detail_names_the_reel_a_replica_came_from() -> None:
    """The stored dict becomes the line of the piece's detail, with the link to the
    original reel; a piece without one shows nothing."""
    stored = {
        "platform": "instagram",
        "post_id": "A",
        "url": "https://www.instagram.com/reel/A/",
        "handle": "@inspiracion",
        "analysis_version": 1,
    }
    assert source_reel_note(stored) == "Hecha a partir de un reel de @inspiracion en Instagram"
    vm = build_draft_vm(
        draft_id="d-1",
        status="approved",
        failure_reason=None,
        variants=(),
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=None,
        model_ids=(),
        requires_ai_disclosure=False,
        created_label="",
        source_reel=stored,
    )
    assert vm.source_reel_note == "Hecha a partir de un reel de @inspiracion en Instagram"
    assert vm.source_reel_url == "https://www.instagram.com/reel/A/"
    plain = build_draft_vm(
        draft_id="d-2",
        status="approved",
        failure_reason=None,
        variants=(),
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=None,
        model_ids=(),
        requires_ai_disclosure=False,
        created_label="",
    )
    assert plain.source_reel_note == "" and plain.source_reel_url == ""


class Proxy:
    def __init__(self, state, auth, generator):
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "auth", auth)
        object.__setattr__(self, "generator", generator)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get_state(self, cls):
        return self.auth if cls is module.AuthState else self.generator

    def __getattr__(self, name):
        return getattr(self.state, name)

    def __setattr__(self, name, value):
        setattr(self.state, name, value)


def fixture():
    state = DiscoverReelsState()
    state._cards = {"week": [dict(CARD)]}
    state._cards_tenant_id = TENANT
    auth = SimpleNamespace(session_tenant_id=TENANT)
    gen = creative()
    return state, auth, gen, Proxy(state, auth, gen)


async def run(proxy, key="instagram:A"):
    return [event async for event in DiscoverReelsState.replicate.fn(proxy, key)]


async def test_click_only_imports_the_server_card_and_opens_step_one(monkeypatch):
    state, auth, gen, proxy = fixture()
    seen = []

    def import_(tenant, card):
        seen.append((tenant, card))
        return dict(IMPORTED)

    def forbidden(*args, **kwargs):
        pytest.fail("replication must not scrape, analyze or generate")

    monkeypatch.setattr(module, "import_reference", import_)
    monkeypatch.setattr(module.reels_discovery, "cached_discover", forbidden)
    monkeypatch.setattr(module.reels_discovery, "transcript_for_card", forbidden)
    monkeypatch.setattr("Qualify.creative_state.submit_brief", forbidden)
    events = await run(proxy)
    assert seen == [(UUID(TENANT), CARD)]
    assert len(events) == 1 and "/create?paso=1" in str(events[0])
    assert gen.gen_mode == "create" and not state.replicating
    assert not state.replicate_error


@pytest.mark.parametrize("condition", ["unknown", "other_tenant", "no_session", "busy", "not_fit"])
async def test_invalid_clicks_never_import(monkeypatch, condition):
    state, auth, gen, proxy = fixture()
    key = "instagram:A"
    if condition == "unknown":
        key = "instagram:forged"
    elif condition == "other_tenant":
        state._cards_tenant_id = "other"
    elif condition == "no_session":
        auth.session_tenant_id = ""
    elif condition == "busy":
        gen.is_submitting = True
    else:
        state._cards["week"][0]["affinity"] = "otro"
    monkeypatch.setattr(module, "import_reference", lambda *a: pytest.fail("unexpected import"))
    assert await run(proxy, key) == []
    assert gen.gen_mode == "discover"


async def test_failed_download_keeps_form_and_can_be_retried(monkeypatch):
    state, auth, gen, proxy = fixture()

    def failure(*args):
        raise ReelReferenceUnavailable("Actualiza los reels y reintenta.")

    monkeypatch.setattr(module, "import_reference", failure)
    assert await run(proxy) == []
    assert state.replicate_error and not state.replicating
    assert gen.gen_mode == "discover" and gen.brief_topic == ""
    monkeypatch.setattr(module, "import_reference", lambda *a: dict(IMPORTED))
    assert await run(proxy)
    assert gen.gen_mode == "create" and not state.replicate_error


@pytest.mark.parametrize("change", ["tenant", "product", "navigation"])
async def test_stale_import_never_overwrites_another_session_or_form(monkeypatch, change):
    state, auth, gen, proxy = fixture()

    def import_(*args):
        if change == "tenant":
            auth.session_tenant_id = "other"
        elif change == "product":
            gen.selected_product_id = "new-product"
        else:
            gen.gen_mode = "variations"
        return dict(IMPORTED)

    monkeypatch.setattr(module, "import_reference", import_)
    assert await run(proxy) == []
    assert gen.brief_topic == "" and not state.replicating


def test_cards_from_another_tenant_are_not_relabelled() -> None:
    state, auth, gen, proxy = fixture()
    state._claim_cards("new-tenant")
    assert state._cards == {} and state._reads == {}
    assert state._cards_tenant_id == "new-tenant"


async def test_a_second_click_during_import_does_nothing(monkeypatch):
    state, auth, gen, proxy = fixture()
    state.replicating = "instagram:A"
    monkeypatch.setattr(module, "import_reference", lambda *a: pytest.fail("duplicate import"))
    assert await run(proxy) == []
    assert gen.gen_mode == "discover"


def test_import_stores_only_the_prepared_reference_under_the_tenant(tmp_path, monkeypatch):
    from qualify_creative.video.fit import FittedVideo

    from . import reel_replication as replication

    monkeypatch.setattr(replication.rx, "get_upload_dir", lambda: tmp_path)
    monkeypatch.setattr(
        replication,
        "prepare_reference",
        lambda *args: FittedVideo(
            data=b"normalized-silent-video", width=96, height=160, duration_sec=5
        ),
    )
    imported = replication.import_reference(UUID(TENANT), CARD)
    assert imported["key"].startswith(f"uploads/{TENANT}/")
    assert (tmp_path / imported["key"]).read_bytes() == b"normalized-silent-video"
    assert imported["seconds"] == "5"
