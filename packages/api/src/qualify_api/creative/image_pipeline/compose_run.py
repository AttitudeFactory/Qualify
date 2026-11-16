"""Stage `compose` with Remotion inside a generation (ADR 49 §2 item 3, m-25040499) — only
with `QUALIFY_IMAGE_LAYER=on` and only for the slides the layer stage wrote a layer for. Off,
`compose_slides` returns at once: no call, no step, the Pillow stills exactly as before.

Each slide with a layer becomes ONE `layer_still` job (`compose_layer`, ADR 49 §2.2); the PNG
the service draws is converted to the publication JPEG and stored as the slide's file, with
its provenance (`compose_params`): the layer it drew, the base's sha256, the catalog
`layout_version`, the compositor's `engine_revision`, the layer's prompt version, the job id
and the layout actually rendered with its fallbacks.

**Replays pay nothing twice.** Inside a queue preparation every attempt of every slide is a
pipeline step in fixed negative slots (`attempt_step`), outside the router's numbering. A
completed compose is read back (its key) and never rendered nor stored again; a refusal is
read back and goes straight to the rewrite. An attempt left without an answer (a crash, the
service down) is made again with the SAME job id: the service hands back the same job, and a
render costs nothing.

**Failures** (founder 2026-11-16, ADR 49 §8.1 D4/D5):

- *Refused* (`LayerRefused`: no layout of the chain can draw the layer — a price wider than
  its box among them): never retried as such. Every refused slide is rewritten in ONE more
  layer call (`layer_run.rewrite_layers`, the piece's US$0.25 meter) and composed again; a
  slide still refused fails the piece. A priced piece is never published without its price —
  a report that dropped the price counts as a refusal.
- *Transient* (`ComposeJobFailed`, a job `wait` gave up on, any other 5xx): one more attempt
  as a NEW job (`attempt` is in the job id), at most `MAX_ATTEMPTS` per slide; then it fails.
- *Outage* (no answer at all: a transport error, 502/503/504): inside the queue the piece
  waits — the pass stops with `RenderWait` and the worker retries it — up to `OUTAGE_WINDOW`
  counted from the FIRST failure of the piece, saved once in step `FIRST_FAILURE_STEP` and
  never reset. Then it fails. A pass tries the service at most once per `OUTAGE_BACKOFF`
  (`raise_if_waiting`, called before anything is replayed). Outside the queue (inline)
  nothing can wait: it fails at once.
- *Rejected* (any other 4xx, an error of ours): the piece fails at once.
- Never the Pillow still instead: a failure is the piece's failure, under its own code
  (`price_does_not_fit`, `compose_unavailable`) so the owner reads one reason (a failed
  generation gives its creation back, `_refund_if_not_delivered`).

**The price** (founder 2026-11-16, D5; review 2026-11-16): a piece with `price_line` prints it
on its first image — a layer there without the price reference is refused like a price that
does not fit, and rewritten. A piece without `price_line` prints no price at all.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from qualify_creative.enums import FailureReason
from qualify_creative.photo.normalize import to_meta_jpeg
from qualify_creative.render.client import RenderServiceError, RenderTimeout
from qualify_creative.render.layer_compose import (
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    ComposedStill,
    ComposeJobFailed,
    LayerComposeRequest,
    LayerRefused,
    compose_layer,
    engine_revision,
)
from qualify_creative.schemas import BrandKit

from qualify_api.creative import pipeline
from qualify_api.creative.image_pipeline.base import BaseScene
from qualify_api.creative.image_pipeline.layer import layer_enabled
from qualify_api.creative.image_pipeline.layer_run import (
    QUEUE_SIGNALS,
    LayerOutcome,
    rewrite_layers,
)
from qualify_api.creative.media import JPEG, LayerWrite, _MediaFailed, _Saver
from qualify_api.creative.queue_dispatch import CheckpointError

if TYPE_CHECKING:
    from qualify_api.creative.media import MediaProducer

logger = logging.getLogger(__name__)

#: Attempts per slide and per layer (the first and two more) for a transient failure.
MAX_ATTEMPTS = 3
#: How long a piece waits for the render service, from its FIRST failure (D4).
OUTAGE_WINDOW = timedelta(minutes=10)
#: While the service is down, a piece tries it at most once per this long (review: no hot loop).
OUTAGE_BACKOFF = timedelta(seconds=45)
#: The step that keeps the piece's first render failure (saved once: never reset).
FIRST_FAILURE_STEP = -200
#: The composer's provenance tag in `image_assets.params`.
COMPOSE_PIPELINE = "layer_still"
#: A waiting piece logs at most once a minute.
_WAIT_LOG_EVERY = timedelta(minutes=1)
_last_wait_log: dict[tuple[UUID, UUID, int], datetime] = {}

#: The draft's failure codes: the owner's text is the screen's (`Qualify/creative_vm.py`
#: FAILURE_INFO), so the draft carries no second sentence (`failure_detail` empty).
PRICE_FAILURE = FailureReason.PRICE_DOES_NOT_FIT.value
COMPOSE_FAILURE = FailureReason.COMPOSE_UNAVAILABLE.value

#: Fixed namespace of the root layers' compose references (never change it).
_LAYER_REF_NAMESPACE = uuid.UUID("2b7d4f0e-9c1a-4e55-8f3b-6a0d1e2c3b4f")


def attempt_step(position: int, round_: int, attempt: int) -> int:
    """The pipeline step of one compose attempt: fixed and negative, below the layer's
    (`LAYER_STEPS`) — `round_` 0 is the layer as written, 1 the rewrite."""
    return -1000 - 100 * position - 10 * round_ - attempt


def outage_step(bucket: int) -> int:
    """The step that says «the service was tried in this `OUTAGE_BACKOFF` bucket and did not
    answer» (bucket 0 starts at the first failure): -201, -202, … — at most 14 in 10 min."""
    return FIRST_FAILURE_STEP - 1 - bucket


class RenderUnavailable(Exception):
    """No render service to call (not configured): waited for like an outage."""


class RenderWait(CheckpointError):
    """The piece waits for the render service: the pass stops, the worker retries later.
    Logged here at WARNING (at most once a minute per piece), never as a preparation error."""


@dataclass(frozen=True)
class ComposedSlide:
    """One slide drawn by the compositor and stored: its key, its JPEG, the layer it drew
    (the rewritten one when there was a rewrite) and the provenance for `image_assets`."""

    position: int
    key: str
    #: the JPEG, only for the positions the caller asked to keep (`keep_images`): a Reel
    #: pushes in its first still; every other slide is just its key
    image: bytes | None
    layer: LayerWrite
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Piece:
    tenant_id: UUID
    draft_id: UUID
    revision: int
    brand: dict[str, Any]
    logo_key: str | None
    logo: bytes | None
    prices: Mapping[str, str]
    save: _Saver
    composer: Callable[[LayerComposeRequest, Callable[[str], bytes]], ComposedStill]
    clock: Callable[[], datetime]
    #: the piece's printed price (`LayerRequest.price_line`): required on the first image
    price_line: str = ""
    first_failure: datetime | None = None

    def price_required(self, position: int) -> bool:
        return position == 0 and bool(self.price_line)


def compose_brand(kit: BrandKit, brand_name: str) -> dict[str, Any]:
    """The `brand` props of `layer_still`. The heading face is `BrandKit.typeface` — the SAME
    resolved title face the layer stage was given (`title_font`), so the render applies the
    catalog's script-title limit to the family Python checked (layer_compose contract)."""
    heading = kit.typeface
    body = " ".join(kit.font_body.split()) or heading
    fonts = {k: v for k, v in (("heading", heading), ("body", body)) if v}
    return {"name": brand_name, "palette": list(kit.palette_rgb), "fonts": fonts}


def layer_ref(draft_id: UUID, revision: int, position: int, spec_sha256: str) -> str:
    """The compose job's layer id for a ROOT layer: its `piece_layers` row is written only by
    `finish_generation`, so the job is keyed by what identifies it — the piece, the revision,
    the position and the spec (an edited layer, m-25017288, uses its own row id)."""
    name = f"{draft_id}|r{revision}|{position}|{spec_sha256}"
    return str(uuid.uuid5(_LAYER_REF_NAMESPACE, name))


def _default_composer(
    producer: MediaProducer,
) -> Callable[[LayerComposeRequest, Callable[[str], bytes]], ComposedStill]:
    remotion = getattr(producer, "_remotion", None)

    def compose(request: LayerComposeRequest, read_media: Callable[[str], bytes]) -> ComposedStill:
        if remotion is None:
            raise RenderUnavailable("no render service configured")
        return compose_layer(remotion.client, request, read_media=read_media)

    return compose


def _now() -> datetime:
    return datetime.now(UTC)


def compose_slides(
    producer: MediaProducer,
    *,
    outcome: LayerOutcome,
    tenant_id: UUID,
    draft_id: UUID,
    revision: int,
    kit: BrandKit,
    brand_name: str,
    logo_key: str | None,
    save: _Saver,
    keep_images: Collection[int] = (),
    env: Mapping[str, str] | None = None,
) -> dict[int, ComposedSlide]:
    """The composed slides by position, for every slide of `outcome` with a layer. Off, or
    with no layer: {} and nothing is called. Raises `_MediaFailed` (the piece's failure code)
    when a slide cannot be drawn, and `RenderWait` while the piece waits for the service.
    Inside the queue the run's lease is kept alive while the slides render."""
    if not outcome.layers or not layer_enabled(dict(env) if env is not None else None):
        return {}
    run = pipeline.current_preparation()
    if run is None:
        return _compose_slides(
            producer,
            outcome,
            tenant_id,
            draft_id,
            revision,
            kit,
            brand_name,
            logo_key,
            save,
            keep_images,
        )
    with pipeline.lease_kept(pipeline.PipelineStore(), run):
        return _compose_slides(
            producer,
            outcome,
            tenant_id,
            draft_id,
            revision,
            kit,
            brand_name,
            logo_key,
            save,
            keep_images,
        )


def _compose_slides(
    producer: MediaProducer,
    outcome: LayerOutcome,
    tenant_id: UUID,
    draft_id: UUID,
    revision: int,
    kit: BrandKit,
    brand_name: str,
    logo_key: str | None,
    save: _Saver,
    keep_images: Collection[int],
) -> dict[int, ComposedSlide]:
    logo_key = logo_key or kit.logo_asset_key
    logo = producer._logo(kit, logo_key) if logo_key else None
    piece = _Piece(
        tenant_id=tenant_id,
        draft_id=draft_id,
        revision=revision,
        brand=compose_brand(kit, brand_name),
        logo_key=logo_key if logo is not None else None,
        logo=logo,
        prices=outcome.prices,
        save=save,
        composer=getattr(producer, "_layer_composer", None) or _default_composer(producer),
        clock=getattr(producer, "_compose_clock", None) or _now,
        price_line=(outcome.request.price_line.strip() if outcome.request else ""),
    )
    layers = dict(outcome.layers)
    drawn: dict[int, dict[str, Any]] = {}
    refused: dict[int, dict[str, Any]] = {}
    for position in sorted(layers):
        if piece.price_required(position) and not layers[position].spec.get("price_ref"):
            refused[position] = _PRICE_MISSING  # the piece's price, left out: never drawn
            continue
        result = _compose(piece, position, 0, layers[position], outcome.scenes[position])
        (drawn if result["status"] == "composed" else refused)[position] = result
    if refused:
        notes = {p: _note(r, layers[p], piece.price_required(p)) for p, r in refused.items()}
        try:
            rewritten = rewrite_layers(producer, outcome, notes)
        except QUEUE_SIGNALS:
            raise
        except Exception as exc:  # noqa: BLE001 - no rewrite: the piece fails, never priceless
            logger.warning("draft %s: layer rewrite failed: %s", draft_id, type(exc).__name__)
            raise _refusal_failure(refused, layers) from exc
        still_refused: dict[int, dict[str, Any]] = {}
        for position in sorted(refused):
            layer = rewritten.get(position)
            if layer is None:
                still_refused[position] = refused[position]
                continue
            if piece.price_required(position) and not layer.spec.get("price_ref"):
                # a rewrite that gave the price up is not a fix: never priceless (D5)
                still_refused[position] = {**refused[position], "slot": "price"}
                continue
            layers[position] = layer
            result = _compose(piece, position, 1, layer, outcome.scenes[position])
            if result["status"] == "composed":
                drawn[position] = result
            else:
                still_refused[position] = result
        if still_refused:
            raise _refusal_failure(still_refused, layers)
    out: dict[int, ComposedSlide] = {}
    for position, result in sorted(drawn.items()):
        image = result.pop("_image", None)  # the JPEG just stored, when this pass made it
        if position not in keep_images:
            image = None  # nobody needs it: never kept in memory, never read back
        elif image is None:
            image = producer._store.read(str(result["key"]))  # a replay: read back once
        out[position] = ComposedSlide(
            position=position,
            key=str(result["key"]),
            image=image,
            layer=layers[position],
            params=compose_params(result, layers[position]),
        )
    return out


#: A first image without the piece's price reference (`LayerRequest.price_line` set).
_PRICE_MISSING: dict[str, Any] = {
    "status": "refused",
    "slot": "price",
    "reason": "price_missing",
    "detail": "the piece's price is not on its first image",
}


def compose_params(result: Mapping[str, Any], layer: LayerWrite) -> dict[str, Any]:
    """The compose provenance a composed slide carries in `image_assets.params` — and what it
    printed (it replaces the Pillow composer's `printed`)."""
    spec = layer.spec
    photo = spec.get("photo") if isinstance(spec.get("photo"), dict) else {}
    return {
        "printed": {
            "title": bool(spec.get("title")),
            "subtitle": bool(spec.get("subtitle")),
            "call_phrase": bool(spec.get("call_phrase")),
            "info_blocks": len(spec.get("info_blocks") or ()),
            # a layer with a price reference is drawn with its price or not at all (D5)
            "price": bool(spec.get("price_ref")),
        },
        # ADR 49 §2 item 1: the base was already made again once (or the claim was taken);
        # a base Claude still sees invented text in is composed as it is, and said so here
        "base_invented_text_kept": bool((photo or {}).get("base_has_invented_text")),
        "composer": COMPOSE_PIPELINE,
        "compose_template": f"{TEMPLATE_ID}@{TEMPLATE_VERSION}",
        "compose_job_id": result["job_id"],
        "compose_attempt": result["attempt"],
        "compose_layer_ref": result["layer_ref"],
        "compose_engine_revision": result["engine_revision"],
        "compose_layout_requested": result["layout_requested"],
        "compose_layout_rendered": result["layout_rendered"],
        "compose_fallbacks": list(result["fallbacks"]),
        "compose_dropped_slots": list(result["dropped_slots"]),
        "compose_sha256": result["sha256"],
        "layer_spec_sha256": layer.spec_sha256,
        "layer_layout_version": layer.layout_version,
        "layer_model_id": layer.model_id,
        "layer_prompt_version": layer.prompt_version,
        "base_sha256": result["base_sha256"],
        "compose_cost_usd": "0",
    }


# -- one slide ----------------------------------------------------------------------------


def _request(
    piece: _Piece, position: int, layer: LayerWrite, scene: BaseScene, attempt: int
) -> tuple[LayerComposeRequest, Callable[[str], bytes]]:
    stored = scene.stored
    base_key = (
        stored.key if stored is not None and stored.key else f"memory/base-{position + 1}.jpg"
    )
    base_sha = stored.sha256 if stored is not None else hashlib.sha256(scene.image).hexdigest()
    price_ref = layer.spec.get("price_ref") or {}
    product_id = str(price_ref.get("product_id") or "") if isinstance(price_ref, dict) else ""
    request = LayerComposeRequest(
        tenant_id=str(piece.tenant_id),
        draft_id=str(piece.draft_id),
        version_id=f"{piece.draft_id}/r{piece.revision}",
        layer_id=layer_ref(piece.draft_id, piece.revision, position, layer.spec_sha256),
        position=position,
        spec=layer.spec,
        brand=piece.brand,
        base_key=base_key,
        base_sha256=base_sha,
        logo_key=piece.logo_key,
        price_text=piece.prices.get(product_id, "") if product_id else "",
        spec_digest=layer.spec_sha256,
        attempt=attempt,
    )

    def read_media(key: str) -> bytes:
        if key == base_key:
            return scene.image  # the base this layer was written over, as the stage holds it
        if key == piece.logo_key and piece.logo is not None:
            return piece.logo
        raise KeyError(f"compose read an unexpected key {key!r}")

    return request, read_media


def _compose(
    piece: _Piece, position: int, round_: int, layer: LayerWrite, scene: BaseScene
) -> dict[str, Any]:
    """The slide's compose result — `composed` (stored), or `refused` — read back when an
    earlier pass has it. Raises `_MediaFailed` / `CheckpointError` (see the module)."""
    run = pipeline.current_preparation()
    store = pipeline.PipelineStore() if run is not None else None
    for attempt in range(MAX_ATTEMPTS):
        step = attempt_step(position, round_, attempt)
        request, read_media = _request(piece, position, layer, scene, attempt)
        if run is not None and store is not None:
            row = store.load_step(run, step)
            if row is not None and row["result"] is not None:
                return dict(row["result"])
            if row is not None and row["error"] is not None:
                continue  # this attempt failed for good in an earlier pass: the next one
            if row is None:
                store.save_step(
                    run,
                    step,
                    {
                        "provider": "remotion",
                        "template": f"{TEMPLATE_ID}@{TEMPLATE_VERSION}",
                        "position": position,
                        "round": round_,
                        "attempt": attempt,
                        "job_id": request.job_id(),
                        "spec_sha256": layer.spec_sha256,
                    },
                    None,
                )
        price_missing = _price_missing(request, layer)
        if price_missing is not None:
            return _done(run, store, step, price_missing)
        try:
            still = piece.composer(request, read_media)
        except QUEUE_SIGNALS:
            raise
        except LayerRefused as exc:
            return _done(
                run,
                store,
                step,
                {
                    "status": "refused",
                    "slot": exc.slot,
                    "reason": exc.reason,
                    "detail": exc.detail[:300],
                    "job_id": request.job_id(),
                },
            )
        except Exception as exc:  # noqa: BLE001 - classified right here
            kind = _kind(exc)
            if kind == "refused":
                return _done(
                    run,
                    store,
                    step,
                    {
                        "status": "refused",
                        "slot": "",
                        "reason": getattr(exc, "code", "invalid_parameters"),
                        "detail": str(getattr(exc, "message", exc))[:300],
                        "job_id": request.job_id(),
                    },
                )
            if kind == "fatal":
                raise _render_failure(exc, position, why="rejected") from exc
            first = _waited(piece, run, store, position, exc)
            if kind == "outage":
                if run is None or store is None:
                    raise _render_failure(exc, position) from exc
                now = piece.clock()
                bucket = int((now - first) / OUTAGE_BACKOFF)
                store.save_step(run, outage_step(bucket), {"at": now.isoformat()}, None)
                _log_wait(run, now, f"render service unavailable ({_code(exc)})")
                raise RenderWait(
                    f"render service unavailable for slide {position + 1}; the piece waits"
                ) from exc
            logger.warning(
                "draft %s slide %s: compose attempt %s failed: %s",
                piece.draft_id,
                position + 1,
                attempt,
                _code(exc),
            )
            if run is not None and store is not None:
                store.complete_step(
                    run.tenant_id,
                    identity={**run.params(), "s": step},
                    result=None,
                    error=f"transient: {_code(exc)}",
                    run=run,
                )
            continue
        dropped = [str(s) for s in still.report.get("dropped_slots") or ()]
        if "price" in dropped:  # an older service: the price is never dropped (D5)
            return _done(
                run,
                store,
                step,
                {
                    "status": "refused",
                    "slot": "price",
                    "reason": "price_dropped",
                    "detail": "the compositor dropped the price",
                    "job_id": still.job_id,
                },
            )
        jpeg = to_meta_jpeg(still.png)
        # under the revision's prefix, keyed like `LayerComposeRequest.object_key`: a new
        # layer, base or attempt is a new object, never an overwrite
        name = (
            f"compose/{request.layer_id}/{layer.spec_sha256[:16]}/{still.job_id}/"
            f"slide-{position + 1}.jpg"
        )
        key = piece.save(name, jpeg, JPEG)
        value = {
            "status": "composed",
            "key": key,
            "sha256": hashlib.sha256(jpeg).hexdigest(),
            "job_id": still.job_id,
            "attempt": attempt,
            "layer_ref": request.layer_id,
            "base_sha256": request.base_sha256,
            "engine_revision": int(still.provenance.get("engine_revision") or engine_revision()),
            "layout_requested": still.layout_requested,
            "layout_rendered": still.layout_rendered,
            "fallbacks": list(still.fallbacks),
            "dropped_slots": dropped,
            "width": still.width,
            "height": still.height,
        }
        _done(run, store, step, value)
        return {**value, "_image": jpeg}
    raise _render_failure(
        RuntimeError(f"{MAX_ATTEMPTS} attempts failed"), position, why=f"{MAX_ATTEMPTS} attempts"
    )


def _done(
    run: pipeline.Preparation | None,
    store: Any,
    step: int,
    value: dict[str, Any],
) -> dict[str, Any]:
    if run is not None and store is not None:
        store.complete_step(
            run.tenant_id, identity={**run.params(), "s": step}, result=value, run=run
        )
    return value


def _price_missing(request: LayerComposeRequest, layer: LayerWrite) -> dict[str, Any] | None:
    """A layer that names a catalog price the piece no longer has (the product lost it):
    drawing it would publish a priced piece without its price — refused, never drawn."""
    ref = layer.spec.get("price_ref")
    if ref and not request.price_text:
        return {
            "status": "refused",
            "slot": "price",
            "reason": "price_unavailable",
            "detail": "the catalog product has no printable price",
            "job_id": request.job_id(),
        }
    return None


#: HTTP statuses that mean «nobody answered» (a proxy in front of a service that is down).
_OUTAGE_STATUSES = frozenset({502, 503, 504})


def _kind(exc: BaseException) -> str:
    """`refused` (rewrite, never retried as such), `transient` (a new job, counted),
    `outage` (wait, not counted) or `fatal` (the piece fails at once)."""
    if isinstance(exc, ComposeJobFailed | RenderTimeout):
        return "transient"  # the job ran and failed, or ran too long and was cancelled
    if isinstance(exc, RenderServiceError):
        if exc.code == "invalid_parameters":
            return "refused"
        if exc.status in _OUTAGE_STATUSES:
            return "outage"
        if exc.status >= 500:
            return "transient"
        return "fatal"  # 4xx: the request is wrong, another try is the same request
    if isinstance(exc, RenderUnavailable | ConnectionError | TimeoutError) or _transport(exc):
        return "outage"
    return "fatal"


def _transport(exc: BaseException) -> bool:
    """An httpx transport error (connect, read, DNS): the service did not answer."""
    try:
        import httpx  # noqa: PLC0415 - lazy, like the client
    except ImportError:  # pragma: no cover - httpx is a dependency of the render client
        return False
    return isinstance(exc, httpx.TransportError)


def _code(exc: BaseException) -> str:
    return str(getattr(exc, "code", "") or type(exc).__name__)


def _log_wait(run: pipeline.Preparation, now: datetime, why: str) -> None:
    key = (run.tenant_id, run.draft_id, run.revision)
    last = _last_wait_log.get(key)
    if last is None or now - last >= _WAIT_LOG_EVERY:
        _last_wait_log[key] = now
        logger.warning("draft %s r%s waits: %s", run.draft_id, run.revision, why)


def raise_if_waiting(run: pipeline.Preparation, now: datetime | None = None) -> None:
    """Called before a queued generation replays anything: when the render service did not
    answer in this `OUTAGE_BACKOFF` bucket already, the pass stops at once (`RenderWait`) —
    no replay, no render call. Past `OUTAGE_WINDOW` the pass goes on, and fails the piece.
    Off (`QUALIFY_IMAGE_LAYER`): returns at once, without reading anything."""
    if not layer_enabled():
        return
    store = pipeline.PipelineStore()
    row = store.load_step(run, FIRST_FAILURE_STEP)
    if row is None:
        return
    now = now or _now()
    elapsed = now - datetime.fromisoformat(str(row["request"]["first_failure_at"]))
    if elapsed >= OUTAGE_WINDOW:
        return
    if store.load_step(run, outage_step(int(elapsed / OUTAGE_BACKOFF))) is None:
        return  # not tried in this bucket yet: this pass tries
    _log_wait(run, now, "render service tried in the last 45 s")
    raise RenderWait("the piece waits for the render service")


def _waited(
    piece: _Piece,
    run: pipeline.Preparation | None,
    store: Any,
    position: int,
    exc: BaseException,
) -> datetime:
    """Record the piece's FIRST render failure (once: a later one never resets it) and fail
    the piece once `OUTAGE_WINDOW` has passed since then. Returns the first failure."""
    now = piece.clock()
    if run is not None and store is not None:
        row = store.load_step(run, FIRST_FAILURE_STEP)
        if row is None:
            row = store.save_step(
                run,
                FIRST_FAILURE_STEP,
                {
                    "first_failure_at": now.isoformat(),
                    "position": position,
                    "error": getattr(exc, "code", type(exc).__name__),
                },
                None,
            )
        first = datetime.fromisoformat(str(row["request"]["first_failure_at"]))
    else:
        if piece.first_failure is None:
            piece.first_failure = now
        first = piece.first_failure
    if now - first >= OUTAGE_WINDOW:
        raise _render_failure(exc, position, why=f"waited {int((now - first).total_seconds())} s")
    return first


def _render_failure(
    exc: BaseException, position: int, *, why: str = "no queue to wait in"
) -> _MediaFailed:
    return _MediaFailed(
        COMPOSE_FAILURE,
        "",  # the screen's text is the code's (FAILURE_INFO): one reason, not two
        raw=f"compose of slide {position + 1} failed ({why}): {type(exc).__name__}: {exc}",
    )


def _note(result: Mapping[str, Any], layer: LayerWrite, price_required: bool) -> str:
    """Why the compositor refused this layer, for the rewrite (the model's language)."""
    if result.get("reason") == "price_unavailable" and not price_required:
        return "esta publicación no muestra precio: deja price_product_id vacío."
    if result.get("reason") in ("price_missing", "price_unavailable"):
        return (
            "esta imagen debe llevar el precio de la publicación: pon price_product_id con el "
            "producto que tiene precio y elige un diseño que lleve precio (plate o band)."
        )
    if result.get("slot") == "price":
        return (
            f"el precio no cabe en el diseño «{layer.layout_id}» ni en los de su cadena. "
            "Elige otro diseño de esta pieza con la caja de texto más ancha y conserva "
            "el precio (price_product_id)."
        )
    slot = str(result.get("slot") or "el texto")
    return (
        f"el compositor no pudo dibujar «{slot}» ({result.get('reason', '')}). "
        "Escríbelo más corto o elige otro diseño de esta pieza."
    )


def _refusal_failure(
    refused: Mapping[int, Mapping[str, Any]], layers: Mapping[int, LayerWrite]
) -> _MediaFailed:
    price = any(r.get("slot") == "price" for r in refused.values())
    detail = "; ".join(
        f"slide {p + 1} ({layers[p].layout_id}): {r.get('slot')} {r.get('reason')}"
        for p, r in sorted(refused.items())
    )
    return _MediaFailed(
        PRICE_FAILURE if price else COMPOSE_FAILURE,
        "",  # the screen's text is the code's (FAILURE_INFO)
        raw=f"the compositor refused the layer after its rewrite: {detail}",
    )
