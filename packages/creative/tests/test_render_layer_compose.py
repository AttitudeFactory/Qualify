"""`layer_still` from Python (m-25017285): one compose job per layer and port, keys that change
with the content, the effective layout handed back — against an in-memory render service."""

from __future__ import annotations

import json
from typing import Any

import pytest

from qualify_creative.render.adapter import RemotionTemplateAdapter
from qualify_creative.render.client import RemotionRenderClient, RenderServiceError
from qualify_creative.render.layer_compose import (
    LayerComposeRequest,
    LayerRefused,
    build_layer_props,
    compose_layer,
    spec_sha256,
)
from qualify_creative.render.registry import TemplateRegistry


class _Response:
    def __init__(self, status: int, body: Any = None, content: bytes = b"", headers: Any = None):
        self.status_code = status
        self._body = body
        self.content = content if content else json.dumps(body).encode()
        self.headers = headers or {"content-type": "application/json"}
        self.text = self.content.decode(errors="replace")

    def json(self) -> Any:
        return self._body


class FakeRenderService:
    """CONTRACT §4 in memory for `layer_still`: the job completes on the first poll with the
    report the composition would compute (or fails with `invalid_parameters`)."""

    def __init__(
        self,
        *,
        rendered: str = "band",
        fail: str | None = None,
        refusal: dict[str, Any] | None = None,
        overflow: list[str] | None = None,
    ) -> None:
        self.rendered = rendered
        self.fail = fail
        self.refusal = refusal
        self.overflow = overflow or []
        self.assets: dict[str, bytes] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.posts: list[dict[str, Any]] = []

    def __call__(self, **_: Any) -> FakeRenderService:
        return self

    def __enter__(self) -> FakeRenderService:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def post(self, path: str, json: Any = None, files: Any = None) -> _Response:
        if path == "/assets":
            _name, data, ctype = files["file"]
            asset_id = f"sha{len(self.assets) + 1}"
            self.assets[asset_id] = data
            return _Response(
                201, {"assetId": asset_id, "url": "", "mimeType": ctype, "bytes": len(data)}
            )
        if path == "/render":
            self.posts.append(json)
            if json["jobId"] in self.jobs:
                return _Response(200, self.jobs[json["jobId"]])
            (port,) = json["outputs"]
            self.jobs[json["jobId"]] = {
                "jobId": json["jobId"],
                "templateId": json["templateId"],
                "version": json["version"],
                "status": "pending",
                "outputs": {port: {"kind": "still", "status": "pending", "progress": 0}},
                "warnings": [],
            }
            return _Response(202, self.jobs[json["jobId"]])
        raise AssertionError(path)

    def get(self, path: str) -> _Response:
        parts = path.split("/")
        job = self.jobs[parts[2]]
        if "/outputs/" in path:
            return _Response(200, None, b"\x89PNG-still", {"content-type": "image/png"})
        port, out = next(iter(job["outputs"].items()))
        if self.fail:
            out.update(
                status="failed",
                failureReason=self.fail,
                errorMessage="invalid_parameters: layer.title: 40 chars exceeds 28",
            )
            if self.refusal:
                out["refusal"] = self.refusal
            job["status"] = "failed"
        else:
            layer = next(p for p in self.posts if p["jobId"] == job["jobId"])["props"]["layer"]
            out.update(
                status="completed",
                progress=1,
                mimeType="image/png",
                bytes=10,
                width=1080,
                height=1350,
                report={
                    "layer_id": layer.get("layer_id"),
                    "layout_requested": layer["layout_id"],
                    "layout_rendered": self.rendered,
                    "anchor": "bottom",
                    "format": "4:5",
                    "fallbacks": ["plate/top_left: covers_subject"],
                    "dropped_slots": [],
                    "sizes": {"title": 96},
                    "contrast": {"text": 7.1},
                    "logo": "top_right",
                    "counter": None,
                    "overflow": self.overflow,
                },
            )
            job["status"] = "completed"
        return _Response(200, job)


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


def _client(service: FakeRenderService) -> RemotionRenderClient:
    return RemotionRenderClient(
        "http://render:3200", http_factory=service, sleep=lambda _s: None, clock=_Clock()
    )


#: a LayerSpec v1 as m-25017283 dumps it (`LayerSpec.model_dump(mode="json")`)
SPEC = {
    "spec_version": 1,
    "layout_id": "plate",
    "layout_version": 1,
    "format": "4:5",
    "photo": {
        "subject_box": [0.25, 0.4, 0.75, 0.8],
        "logo_in_photo": False,
        "base_has_invented_text": False,
    },
    "anchor": "top_left",
    "container_color": "surface",
    "accent_word": None,
    "title": "Tu pan, recién horneado",
    "subtitle": None,
    "call_phrase": None,
    "info_blocks": [],
    "price_ref": None,
    "highlight_content": None,
    "photo_strip": False,
    "carousel": None,
    "fallbacks": [],
}
MEDIA = {"t/ten/generated/d1/base/b.jpg": b"jpeg-base", "brand/logo.png": b"png-logo"}


def _request(**over: Any) -> LayerComposeRequest:
    base: dict[str, Any] = {
        "tenant_id": "ten",
        "draft_id": "d1",
        "version_id": "v1",
        "layer_id": "L1",
        "position": 0,
        "spec": SPEC,
        "brand": {
            "name": "Panadería",
            "palette": ["#B5532A", "#FFFFFF"],
            "fonts": {"heading": "Poppins"},
        },
        "base_key": "t/ten/generated/d1/base/b.jpg",
        "base_sha256": "ab" * 32,
        "logo_key": "brand/logo.png",
    }
    base.update(over)
    return LayerComposeRequest(**base)


def test_compose_returns_the_still_and_the_layout_actually_rendered() -> None:
    service = FakeRenderService(rendered="band")
    stored: dict[str, bytes] = {}
    out = compose_layer(
        _client(service), _request(), read_media=MEDIA.__getitem__, store=stored.__setitem__
    )
    assert out.layout_requested == "plate"
    assert out.layout_rendered == "band"
    assert out.fallbacks == ("plate/top_left: covers_subject",)
    assert out.png == b"\x89PNG-still"
    assert stored == {out.object_key: b"\x89PNG-still"}
    assert out.provenance["template"] == "layer_still@1"
    assert out.provenance["spec_sha256"] == spec_sha256(SPEC)
    # one job, one port; media went up as assets, never as store keys
    (post,) = service.posts
    assert post["templateId"] == "layer_still" and post["outputs"] == ["feed"]
    assert post["props"]["photos"] == ["asset://sha1"]
    assert post["props"]["brand"]["logo"] == "asset://sha2"
    assert post["props"]["layer"]["layout_id"] == "plate"


def test_the_adapter_exposes_compose_layer() -> None:
    service = FakeRenderService(rendered="plate")
    adapter = RemotionTemplateAdapter(_client(service), read_media=MEDIA.__getitem__)
    out = adapter.compose_layer(_request())
    assert out.layout_rendered == "plate"
    assert out.stored is False


def test_keys_change_with_the_content_and_never_collide() -> None:
    a = _request()
    assert a.job_id() == _request().job_id()  # a retry is the same job (idempotent)
    assert a.object_key().startswith("t/ten/generated/d1/compose/L1/")
    assert a.object_key().endswith("/slide-1.jpg")
    assert spec_sha256(SPEC)[:16] in a.object_key() and a.job_id() in a.object_key()
    edited = _request(layer_id="L2", spec={**SPEC, "title": "Tu pan de hoy"})
    variants = [
        edited,
        _request(spec={**SPEC, "layout_id": "band", "anchor": "bottom"}),  # «Probar otro diseño»
        _request(base_sha256="cd" * 32),
        _request(spec={**SPEC, "format": "1:1"}),
        _request(position=1),
        _request(price_text="$ 12.000"),
        _request(brand={**a.brand, "palette": ["#000000"]}),
        _request(spec={**SPEC, "carousel": {"role": "cover", "index": 0, "count": 3}}),
        _request(logo_key="brand/logo-2.png"),
    ]
    ids = {a.job_id(), *(v.job_id() for v in variants)}
    keys = {a.object_key(), *(v.object_key() for v in variants)}
    assert len(ids) == len(variants) + 1
    assert len(keys) == len(variants) + 1
    # the stored digest wins when the caller has it (piece_layers.spec_sha256)
    assert _request(spec_digest="f" * 64).object_key().split("/")[6] == "f" * 16


def test_a_refused_layer_raises_and_stores_nothing() -> None:
    service = FakeRenderService(fail="invalid_parameters")
    stored: dict[str, bytes] = {}
    with pytest.raises(RenderServiceError) as err:
        compose_layer(
            _client(service), _request(), read_media=MEDIA.__getitem__, store=stored.__setitem__
        )
    assert err.value.code == "invalid_parameters"
    assert not isinstance(err.value, LayerRefused)
    assert stored == {}


def test_an_unrenderable_layer_surfaces_the_slot_to_rewrite() -> None:
    refusal = {
        "code": "layer_unrenderable",
        "slot": "title",
        "reason": "word_too_wide",
        "detail": "«Supercalifragilisticoespiral» is 1210 px at 72 px; the box is 952 px",
        "format": "4:5",
        "layout_requested": "plate",
        "attempts": ["plate/top_left: word_too_wide"],
    }
    service = FakeRenderService(fail="invalid_parameters", refusal=refusal)
    stored: dict[str, bytes] = {}
    with pytest.raises(LayerRefused) as err:
        compose_layer(
            _client(service), _request(), read_media=MEDIA.__getitem__, store=stored.__setitem__
        )
    assert err.value.code == "invalid_parameters"
    assert (err.value.slot, err.value.reason) == ("title", "word_too_wide")
    assert "Supercalifragilisticoespiral" in err.value.detail
    assert stored == {}


def test_a_report_with_overflow_is_never_stored() -> None:
    service = FakeRenderService(rendered="info_card", overflow=["info_blocks[0].value|3 lines"])
    stored: dict[str, bytes] = {}
    with pytest.raises(RenderServiceError) as err:
        compose_layer(
            _client(service), _request(), read_media=MEDIA.__getitem__, store=stored.__setitem__
        )
    assert err.value.code == "invalid_parameters"
    assert stored == {}


def test_a_base_photo_needs_its_fingerprint() -> None:
    with pytest.raises(ValueError, match="base_sha256"):
        _request(base_sha256=None)
    assert _request(base_key=None, base_sha256=None).job_id()  # no photo, no fingerprint


def test_the_layer_id_is_in_the_job_key_and_reaches_the_report() -> None:
    assert _request(layer_id="L1").job_id() != _request(layer_id="L9").job_id()
    props = build_layer_props(_request(), photo_ref=None, logo_ref=None)
    assert props["layer"]["layer_id"] == "L1"
    assert "layer_id" not in SPEC  # the spec's hash is taken without it


def test_props_carry_the_layer_price_and_the_port_of_its_format() -> None:
    carousel = {"role": "body", "index": 1, "count": 5}
    req = _request(
        spec={**SPEC, "format": "1:1", "carousel": carousel}, price_text="$ 9.500", is_food=True
    )
    props = build_layer_props(req, photo_ref="asset://p", logo_ref=None)
    assert props["meta"]["port"] == "square"
    assert props["texts"] == {"is_food": True, "price_text": "$ 9.500"}
    assert props["layer"]["carousel"] == carousel  # the counter and logo rule ride on the spec
    assert props["brand"]["logo"] is None
    with pytest.raises(ValueError):
        _ = _request(spec={**SPEC, "format": "16:9"}).port


def test_the_manifest_parses_and_never_serves_a_post_recipe() -> None:
    reg = TemplateRegistry.from_dir()
    m = reg.get("layer_still")
    assert m.version == 1
    assert {p: o.format for p, o in m.outputs.items()} == {
        "feed": "4:5",
        "square": "1:1",
        "story": "9:16",
    }
    assert m.layer_catalog is not None and m.layer_catalog["layout_version"] == 1
    assert set(m.layer_catalog["layouts"]) == {
        "photo_only",
        "plate",
        "scrim",
        "band",
        "info_card",
        "brand_fill",
        "highlight_circle",
    }
    for angle in ("product", "promotion", "price", "new_product"):
        assert "layer_still" not in {t.id for t in reg.for_post(angle=angle, niche=None)}
