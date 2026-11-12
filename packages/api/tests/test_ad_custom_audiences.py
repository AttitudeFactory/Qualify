"""Audience approval, one-shot transport and promotion targeting without a network."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from qualify_api.ads import custom_audience_service as service
from qualify_api.ads.audience import AudienceDraft, AudienceUnavailable, LocationOption
from qualify_api.ads.audience_service import AudienceScope
from qualify_api.ads.custom_audience_client import CustomAudienceClient
from qualify_api.ads.custom_audiences import (
    CustomAudienceRequest,
    CustomAudienceSelection,
    accepted_terms,
    ready_audience,
)
from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.connections.ad_accounts import AdConnection


@pytest.fixture
def world(monkeypatch):
    ids = {
        key: uuid4()
        for key in ("tenant_id", "content_draft_id", "publish_attempt_id", "ad_account_id")
    }
    scope = AudienceScope(
        **ids,
        brand_id=uuid4(),
        connection=AdConnection(
            uuid4(), uuid4(), "42", 1, "active", ("ads_management",), None, True
        ),
        meta_account_id="12",
    )
    monkeypatch.setattr(service, "_scope", lambda **kwargs: scope)
    monkeypatch.setattr(service, "_same", lambda value: None)
    fake = FakeMarketingClient(account_id="12")
    fake.responses["GET", "act_12"] = {
        "account_id": "12",
        "tos_accepted": {"custom_audience_tos": 1},
    }

    class Client(CustomAudienceClient):
        async def create(self, params, *, before_write):
            remote_id = await super().create(params, before_write=before_write)
            fake.objects[remote_id].update(
                account_id="12", operation_status={"code": 200}, delivery_status={"code": 200}
            )
            if params["subtype"] == "LOOKALIKE":
                fake.objects[remote_id]["lookalike_spec"]["origin"] = [
                    {"id": params["origin_audience_id"]}
                ]
            return remote_id

    @asynccontextmanager
    async def client(value):
        yield Client(fake)

    monkeypatch.setattr(service, "_client", client)
    rows = {}

    def claim(value, request, key, payload):
        if key in rows:
            row = rows[key]
            if row["request_hash"] != request.fingerprint:
                raise AudienceUnavailable("La solicitud cambió.")
            return deepcopy(row), False
        row = {
            "id": uuid4(),
            "name": request.name,
            "kind": request.kind,
            "status": "creating",
            "request_hash": request.fingerprint,
            "payload": payload,
            "meta_audience_id": None,
        }
        rows[key] = row
        return deepcopy(row), True

    def get_row(value, identifier):
        return deepcopy(next(row for row in rows.values() if str(row["id"]) == identifier))

    def finish(value, identifier, remote_id):
        row = next(row for row in rows.values() if row["id"] == identifier)
        row.update(status="created" if remote_id else "unknown", meta_audience_id=remote_id)
        return deepcopy(row)

    monkeypatch.setattr(service.repository, "claim", claim)
    monkeypatch.setattr(service.repository, "get_row", get_row)
    monkeypatch.setattr(service.repository, "finish", finish)
    monkeypatch.setattr(
        service.repository, "list_rows", lambda value: tuple(deepcopy(list(rows.values())))
    )
    return ids, scope, fake, rows


@pytest.mark.asyncio
async def test_confirm_create_select_and_compile_promotion_targeting_without_spend(world):
    ids, _, fake, _ = world
    request, key = CustomAudienceRequest("Personas que conocen mi negocio"), uuid4()
    created = await service.create_custom_audience(
        **ids, request=request, request_key=key, confirmed=True
    )
    assert created.available and created.status == "created"
    catalog = await service.list_custom_audiences(**ids)
    assert catalog.terms_accepted is True and catalog.creation_available
    draft = AudienceDraft(
        LocationOption("CO", "Colombia", "country", "CO"),
        custom_audiences=(catalog.audiences[0].selection(),),
    )
    assert draft.targeting()["custom_audiences"] == [{"id": created.meta_audience_id}]
    assert AudienceDraft.from_snapshot(draft.snapshot()) == draft
    again = await service.create_custom_audience(
        **ids, request=request, request_key=key, confirmed=True
    )
    assert again.id == created.id
    posts = [(path, params) for method, path, params in fake.calls if method == "POST"]
    assert len(posts) == 1 and posts[0][0] == "act_12/customaudiences"
    assert not {"budget", "status", "campaign_id", "adset_id"} & posts[0][1].keys()


@pytest.mark.asyncio
async def test_unknown_write_never_posts_again_for_same_request(world):
    ids, _, fake, _ = world
    fake.responses["POST", "act_12/customaudiences"] = {}
    request, key = CustomAudienceRequest("Escribieron", "messages"), uuid4()
    first = await service.create_custom_audience(
        **ids, request=request, request_key=key, confirmed=True
    )
    second = await service.create_custom_audience(
        **ids, request=request, request_key=key, confirmed=True
    )
    assert first.status == second.status == "unknown" and not second.available
    assert sum(method == "POST" for method, _, _ in fake.calls) == 1
    assert "no se enviará de nuevo" in second.reason


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [None, False, True, "1", 0, 2])
async def test_unproven_terms_block_before_claim_or_post(world, accepted):
    ids, _, fake, rows = world
    fake.responses["GET", "act_12"]["tos_accepted"]["custom_audience_tos"] = accepted
    with pytest.raises(AudienceUnavailable, match="términos"):
        await service.create_custom_audience(
            **ids, request=CustomAudienceRequest("Mi público"), request_key=uuid4(), confirmed=True
        )
    assert not rows and all(method == "GET" for method, _, _ in fake.calls)


@pytest.mark.asyncio
async def test_confirmation_housing_and_foreign_seed_block_before_write(world):
    ids, _, fake, _ = world
    request = CustomAudienceRequest("Personas similares", "lookalike", seed_id=str(uuid4()))
    with pytest.raises(AudienceUnavailable, match="Confirma"):
        await service.create_custom_audience(
            **ids, request=request, request_key=uuid4(), confirmed=False
        )
    with pytest.raises(AudienceUnavailable, match="vivienda"):
        await service.create_custom_audience(
            **ids, request=request, request_key=uuid4(), confirmed=True, housing=True
        )
    assert not fake.calls


@pytest.mark.asyncio
async def test_lookalike_requires_confirmed_local_seed_and_exact_origin(world):
    ids, _, fake, _ = world
    seed = await service.create_custom_audience(
        **ids, request=CustomAudienceRequest("Interacciones"), request_key=uuid4(), confirmed=True
    )
    child = await service.create_custom_audience(
        **ids,
        request=CustomAudienceRequest("Similares", "lookalike", seed_id=str(seed.id)),
        request_key=uuid4(),
        confirmed=True,
    )
    assert child.available
    spec = fake.objects[child.meta_audience_id]["lookalike_spec"]
    assert spec["type"] == "custom_ratio" and spec["ratio"] == 0.01
    fake.objects[child.meta_audience_id]["lookalike_spec"]["origin"] = [{"id": "999"}]
    catalog = await service.list_custom_audiences(**ids)
    assert not next(row for row in catalog.audiences if row.id == child.id).available
    with pytest.raises(AudienceUnavailable, match="vivienda"):
        AudienceDraft(
            LocationOption("CO", "Colombia", "country", "CO"),
            housing=True,
            custom_audiences=(child.selection(),),
        ).targeting()


@pytest.mark.asyncio
async def test_changed_scope_during_client_wait_blocks_post_and_keeps_unknown(world, monkeypatch):
    ids, _, fake, rows = world
    calls = 0

    def changed(scope):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise AudienceUnavailable("La cuenta cambió.")

    monkeypatch.setattr(service, "_same", changed)
    result = await service.create_custom_audience(
        **ids, request=CustomAudienceRequest("Mi público"), request_key=uuid4(), confirmed=True
    )
    assert result.status == "unknown" and rows
    assert not any(method == "POST" for method, _, _ in fake.calls)


@pytest.mark.asyncio
async def test_remote_source_account_and_ready_state_are_not_trusted(world):
    ids, _, fake, _ = world
    summary = await service.create_custom_audience(
        **ids, request=CustomAudienceRequest("Interacciones"), request_key=uuid4(), confirmed=True
    )
    remote = fake.objects[summary.meta_audience_id]
    original = deepcopy(remote)
    for changes in (
        {"account_id": "99"},
        {"operation_status": {"code": True}},
        {"rule": {}},
        {"subtype": "LOOKALIKE"},
        {"delivery_status": {"code": 100}},
    ):
        remote.clear()
        remote.update(original | changes)
        catalog = await service.list_custom_audiences(**ids)
        assert not catalog.audiences[0].available


def test_legacy_snapshot_hash_unchanged_and_selection_fingerprint_covers_identity():
    audience = AudienceDraft(LocationOption("CO", "Colombia", "country", "CO"))
    snapshot = audience.snapshot()
    assert "custom_audiences" not in snapshot
    assert AudienceDraft.from_snapshot(snapshot).fingerprint == audience.fingerprint
    selection = CustomAudienceSelection(str(uuid4()), "123", "Mi público", "engagement")
    selected = replace(audience, custom_audiences=(selection,))
    assert selected.fingerprint != audience.fingerprint
    assert (
        replace(selected, custom_audiences=(replace(selection, kind="lookalike"),)).fingerprint
        != selected.fingerprint
    )
    with pytest.raises(AudienceUnavailable):
        replace(selected, custom_audiences=(selection, selection)).snapshot()


def test_exact_terms_identity_and_payload_contract():
    assert (
        accepted_terms({"account_id": "9", "tos_accepted": {"custom_audience_tos": 1}}, "12")
        is None
    )
    payload = CustomAudienceRequest("Mensajes", "messages", 30).payload("42")
    rule = payload["rule"]["inclusions"]["rules"][0]
    assert rule["event_sources"] == [{"id": "42", "type": "ig_business"}]
    assert rule["retention_seconds"] == 30 * 86400
    assert rule["filter"]["filters"][0]["value"] == "ig_user_messaged_business"
    assert not ready_audience({}, remote_id="1", account_id="12")
    assert service._json_object(json.dumps({"key": 1})) == {"key": 1}
