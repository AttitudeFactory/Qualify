"""D3 — the three creative routes (design §5), exercised with zero network and zero DB.

Everything below the routes is faked at the `dependency_overrides` seam: a duck-typed
content service (the generate route touches exactly `get_draft` and `dispatcher`), a
dict-backed image reader and a dict-backed approved-creative reader. The principal is
overridden directly, so cross-tenant tests are just a harness built with the OTHER
tenant's principal against data keyed to the first — the routes must answer 404, never
403, and never leak which of the misses happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from uuid import UUID

import httpx
import pytest
from qualify_creative.enums import BriefIntent, FailureReason
from qualify_creative.schemas import CopyPayload

from qualify_api.creative.read import ApprovedCreative
from qualify_api.http import creative_routes, deps
from qualify_api.http.app import create_app

TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")
DRAFT = UUID("44444444-4444-4444-8444-444444444444")


@dataclass
class FakeDetail:
    """The generate route reads exactly one attribute of `DraftDetail`."""

    status: str


class FakeDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    def dispatch_generation(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        self.calls.append((tenant_id, draft_id))


class FakeContentService:
    """Duck-typed stand-in: `(tenant_id, draft_id) -> status`, plus the public
    `dispatcher` seam the route dispatches through."""

    def __init__(self) -> None:
        self.drafts: dict[tuple[UUID, UUID], str] = {}
        self.dispatcher: FakeDispatcher | None = FakeDispatcher()

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> FakeDetail | None:
        status = self.drafts.get((tenant_id, draft_id))
        return None if status is None else FakeDetail(status=status)


def _artifact(draft_id: UUID = DRAFT) -> ApprovedCreative:
    return ApprovedCreative(
        draft_id=draft_id,
        brand_id=UUID("55555555-5555-4555-8555-555555555555"),
        copy=CopyPayload(hook="A hook", caption="A caption", hashtags=("qualify",), cta="Go"),
        intent=BriefIntent.ORGANIC,
        voice_profile_version=3,
        approved_at=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
        requires_ai_disclosure=False,
        image_media_url="https://v3.fal.media/files/some-image.png",
        image_object_key=None,
        image_width=1080,
        image_height=1350,
        aspect_ratio="4:5",
        provenance=MappingProxyType({"pipeline_version": "creative-v1", "copy_model_id": "m-1"}),
    )


class Harness:
    """One app per test, faked at the seams; the principal decides the tenant."""

    def __init__(self, *, tenant: UUID = TENANT) -> None:
        self.service = FakeContentService()
        self.images: dict[tuple[UUID, UUID], creative_routes.DraftImage] = {}
        self.artifacts: dict[tuple[UUID, UUID], ApprovedCreative] = {}

        def read_image(*, tenant_id: UUID, draft_id: UUID) -> creative_routes.DraftImage | None:
            return self.images.get((tenant_id, draft_id))

        def read_artifact(*, tenant_id: UUID, draft_id: UUID) -> ApprovedCreative | None:
            return self.artifacts.get((tenant_id, draft_id))

        app = create_app(configure_production=False)
        app.dependency_overrides[creative_routes.get_content_service] = lambda: self.service
        app.dependency_overrides[creative_routes.get_draft_image_reader] = lambda: read_image
        app.dependency_overrides[creative_routes.get_approved_creative_reader] = lambda: (
            read_artifact
        )
        app.dependency_overrides[deps.current_principal] = lambda: deps.Principal(
            tenant_id=tenant, user_id=USER
        )
        self._transport = httpx.ASGITransport(app=app)

    def client(self) -> httpx.AsyncClient:
        # follow_redirects stays False (the default): the 302's Location IS the assertion.
        return httpx.AsyncClient(transport=self._transport, base_url="http://test")


# ---------------------------------------------------------------------------
# GET /drafts/{id}/image


async def test_image_redirects_to_media_url() -> None:
    harness = Harness()
    url = "https://v3.fal.media/files/fresh.png"
    harness.images[(TENANT, DRAFT)] = creative_routes.DraftImage(
        media_url=url, media_expires_at=datetime.now(UTC) + timedelta(days=6)
    )
    async with harness.client() as client:
        response = await client.get(f"/api/creative/drafts/{DRAFT}/image")
    assert response.status_code == 302
    assert response.headers["location"] == url


async def test_image_without_expiry_redirects() -> None:
    """`media_expires_at` NULL means the provider promised no expiry (fal, null
    lifecycle) — never a 410."""
    harness = Harness()
    harness.images[(TENANT, DRAFT)] = creative_routes.DraftImage(
        media_url="https://v3.fal.media/files/eternal.png", media_expires_at=None
    )
    async with harness.client() as client:
        response = await client.get(f"/api/creative/drafts/{DRAFT}/image")
    assert response.status_code == 302


async def test_image_404_when_draft_has_no_image() -> None:
    harness = Harness()
    async with harness.client() as client:
        response = await client.get(f"/api/creative/drafts/{DRAFT}/image")
    assert response.status_code == 404


async def test_image_404_for_other_tenants_draft() -> None:
    """404, not 403: the other tenant's image must be indistinguishable from a missing
    one."""
    harness = Harness(tenant=OTHER_TENANT)
    harness.images[(TENANT, DRAFT)] = creative_routes.DraftImage(
        media_url="https://v3.fal.media/files/private.png", media_expires_at=None
    )
    async with harness.client() as client:
        response = await client.get(f"/api/creative/drafts/{DRAFT}/image")
    assert response.status_code == 404


async def test_image_410_when_expired_names_the_typed_reason() -> None:
    """§5.1: never redirect to a URL known dead. The body names the typed reason so the
    UI can branch on it."""
    harness = Harness()
    harness.images[(TENANT, DRAFT)] = creative_routes.DraftImage(
        media_url="https://replicate.delivery/gone.png",
        media_expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    async with harness.client() as client:
        response = await client.get(f"/api/creative/drafts/{DRAFT}/image")
    assert response.status_code == 410
    assert response.json()["detail"]["failure_reason"] == FailureReason.MEDIA_EXPIRED.value


# ---------------------------------------------------------------------------
# GET /drafts/{id}


async def test_read_draft_returns_approved_creative() -> None:
    harness = Harness()
    harness.artifacts[(TENANT, DRAFT)] = _artifact()
    async with harness.client() as client:
        response = await client.get(f"/api/creative/drafts/{DRAFT}")
    assert response.status_code == 200
    body = response.json()
    assert body["draft_id"] == str(DRAFT)
    assert body["copy"]["hook"] == "A hook"
    assert body["intent"] == "organic"
    assert body["requires_ai_disclosure"] is False
    assert body["image_media_url"] == "https://v3.fal.media/files/some-image.png"
    assert body["provenance"]["pipeline_version"] == "creative-v1"


async def test_read_draft_404_when_not_an_artifact() -> None:
    """The reader returns None for a GENERATED (unapproved) draft exactly as for a
    missing one — one 404 covers both."""
    harness = Harness()
    async with harness.client() as client:
        response = await client.get(f"/api/creative/drafts/{DRAFT}")
    assert response.status_code == 404


async def test_read_draft_404_for_other_tenants_artifact() -> None:
    harness = Harness(tenant=OTHER_TENANT)
    harness.artifacts[(TENANT, DRAFT)] = _artifact()
    async with harness.client() as client:
        response = await client.get(f"/api/creative/drafts/{DRAFT}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /drafts/{id}/generate


async def test_generate_202_dispatches_drafting_work() -> None:
    harness = Harness()
    harness.service.drafts[(TENANT, DRAFT)] = "drafting"
    async with harness.client() as client:
        response = await client.post(f"/api/creative/drafts/{DRAFT}/generate")
    assert response.status_code == 202
    assert response.json() == {"draft_id": str(DRAFT), "status": "drafting"}
    assert harness.service.dispatcher is not None
    assert harness.service.dispatcher.calls == [(TENANT, DRAFT)]


async def test_generate_double_post_is_idempotent() -> None:
    """Two accepts, two dispatches — safety is `run_generation`'s idempotency by state,
    so the route neither dedupes nor errors on the retry."""
    harness = Harness()
    harness.service.drafts[(TENANT, DRAFT)] = "drafting"
    async with harness.client() as client:
        first = await client.post(f"/api/creative/drafts/{DRAFT}/generate")
        second = await client.post(f"/api/creative/drafts/{DRAFT}/generate")
    assert (first.status_code, second.status_code) == (202, 202)
    assert harness.service.dispatcher is not None
    assert harness.service.dispatcher.calls == [(TENANT, DRAFT), (TENANT, DRAFT)]


async def test_generate_202_no_op_state_still_accepted() -> None:
    """A draft past DRAFTING is accepted too — the dispatch settles as a state no-op
    inside `run_generation`, which is the documented meaning of this 202."""
    harness = Harness()
    harness.service.drafts[(TENANT, DRAFT)] = "generated"
    async with harness.client() as client:
        response = await client.post(f"/api/creative/drafts/{DRAFT}/generate")
    assert response.status_code == 202
    assert response.json()["status"] == "generated"


async def test_generate_404_unknown_draft() -> None:
    harness = Harness()
    async with harness.client() as client:
        response = await client.post(f"/api/creative/drafts/{DRAFT}/generate")
    assert response.status_code == 404


async def test_generate_404_for_other_tenants_draft() -> None:
    harness = Harness(tenant=OTHER_TENANT)
    harness.service.drafts[(TENANT, DRAFT)] = "drafting"
    async with harness.client() as client:
        response = await client.post(f"/api/creative/drafts/{DRAFT}/generate")
    assert response.status_code == 404
    assert harness.service.dispatcher is not None
    assert harness.service.dispatcher.calls == []


@pytest.mark.parametrize("status", ["failed", "published"])
async def test_generate_409_for_terminal_states(status: str) -> None:
    """The FSM has no edge from `failed` or `published` back to `drafting`; accepting
    the retry would be a 202 that lies."""
    harness = Harness()
    harness.service.drafts[(TENANT, DRAFT)] = status
    async with harness.client() as client:
        response = await client.post(f"/api/creative/drafts/{DRAFT}/generate")
    assert response.status_code == 409
    assert harness.service.dispatcher is not None
    assert harness.service.dispatcher.calls == []


async def test_generate_503_when_dispatcher_unwired() -> None:
    """An assembly bug answers 503, not a 202 that accepts work that provably cannot
    run."""
    harness = Harness()
    harness.service.drafts[(TENANT, DRAFT)] = "drafting"
    harness.service.dispatcher = None
    async with harness.client() as client:
        response = await client.post(f"/api/creative/drafts/{DRAFT}/generate")
    assert response.status_code == 503
