"""Spend control for evals that call paid generation vendors: price quotes from the
versioned pricing table, a thread-safe spending ceiling, an HTTP transport that reserves
before every request, reference-image encoding, path safety and a network guard for dry
runs. Reusable by any eval under `packages/api/evals/`; it imports nothing from a
specific eval.

Money rules:

1. **No price, no call.** `quote` resolves every component a request is billed for from
   the pricing table; a missing row raises `MissingPriceError` before anything is sent.
2. **The ceiling is checked before every request.** `SpendLedger` reserves the worst case
   under a lock before the bytes leave (`LedgerTransport` sits under the adapter, so the
   adapter's own retries are reservations too) and refuses the one that would cross the
   ceiling. The ceiling itself can never be set above `MAX_USD_CEILING`.
"""

from __future__ import annotations

import base64
import contextlib
import io
import sys
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from PIL import Image, ImageOps
from qualify_creative.photo.normalize import REFERENCE_MAX_SIDE, to_reference_jpeg
from qualify_creative.pricing import JsonPricingTable

#: Seedream 5.0 pro: the one tiered model `quote` knows (sizes, references, layers).
SEEDREAM_PRO = "dola-seedream-5-0-pro-260628"
#: Hard technical ceiling for one run, in USD. A larger `--max-usd` is rejected.
MAX_USD_CEILING = Decimal("10")
DEFAULT_MAX_USD = Decimal("10")

#: Seedream 5.0 pro / flash (docs.byteplus.com/en/docs/ModelArk/1541523, read 2026-10-23).
PRO_MAX_REFERENCES = 10
PRO_SIZE_LEVELS: Mapping[str, str] = {"1K": "1k", "1.5K": "1k", "2K": "2k"}
PRO_MIN_PIXELS = 921_600
PRO_MAX_PIXELS = 4_624_220
#: Up to 2.61 MP an image bills at the 1K price (model-pricing, read 2026-10-23).
TIER_1K_MAX_PIXELS = 2_610_000
#: Every billing tier `size_tier` can return.
IMAGE_TIERS: tuple[str, ...] = ("1k", "2k")
#: `layer_decomposition` returns a base image plus up to 16 layers. The count is only
#: known after the call: a dry run assumes `DEFAULT_EXPECTED_LAYERS`, the ledger reserves
#: the worst case and settles with the vendor's `usage.generated_images`.
MAX_LAYERS = 16
DEFAULT_EXPECTED_LAYERS = 8

#: The vendor takes up to 30 MB per image; references stay far below at the adapter's
#: own reference size (`REFERENCE_MAX_SIDE`, the same 2048 px as `to_reference_jpeg`).
MAX_REFERENCE_BYTES = 10 * 1024 * 1024
_PNG_FALLBACK_SIDES = (1536, 1024, 768)


class MissingPriceError(LookupError):
    """A paid item has a component with no row in the pricing table: the run must stop
    before any request is sent. A `LookupError` (not a `KeyError`) so `str(exc)` is the
    plain message, without the quotes `KeyError` adds."""


class CeilingExceededError(RuntimeError):
    """The next reservation would take the run over its spending ceiling."""


# ---------------------------------------------------------------------------
# Path safety


def unsafe_relative_path(path: str) -> bool:
    """Absolute or rooted (on any OS, `\\x` included) or climbing out with `..`."""
    posix, windows = PurePosixPath(path), PureWindowsPath(path)
    return (
        path.startswith(("/", "\\"))
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or bool(windows.root)
        or ".." in posix.parts
        or ".." in windows.parts
    )


def resolve_within(base: Path, relative: str | Path, *, what: str = "path") -> Path:
    """`base / relative`, resolved, refusing anything that lands outside `base`."""
    root = base.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"{what} {str(relative)!r} resolves outside {root}")
    return path


# ---------------------------------------------------------------------------
# Price quotes


@dataclass(frozen=True)
class PriceQuote:
    """What one request costs, from the pricing table.

    `unit_usd` is the price of one billed image: the image at its size tier, or, with
    layer decomposition, one layer at that tier (the base image is billed as a layer
    too). `total_usd` is the expected cost (what a dry run adds up); `max_usd` is the
    worst case the ledger reserves before the request; `actual_usd` prices the vendor's
    own count of generated images once the request is done.
    """

    model_id: str
    pricing_version: str
    size: str
    tier: str
    references: int
    layer_decomposition: bool
    unit_usd: Decimal
    references_usd: Decimal
    expected_images: int
    max_images: int

    @property
    def total_usd(self) -> Decimal:
        return self.unit_usd * self.expected_images + self.references_usd

    @property
    def max_usd(self) -> Decimal:
        return self.unit_usd * self.max_images + self.references_usd

    def actual_usd(self, generated_images: int) -> Decimal:
        """BytePlus bills only successfully generated images; the input images belong to
        a successful request."""
        if generated_images <= 0:
            return Decimal(0)
        return self.unit_usd * generated_images + self.references_usd


def size_tier(size: str, *, model_id: str = SEEDREAM_PRO) -> str:
    """The billing tier (`"1k"` up to 2.61 MP, `"2k"` above) of a size: a level (1K,
    1.5K, 2K, 3K, 4K) or ``WxH``. Seedream 5.0 pro sizes are checked against its range."""
    level = size.strip().upper()
    if model_id == SEEDREAM_PRO and level in ("3K", "4K"):
        raise ValueError(f"size {size!r}: Seedream 5.0 pro takes 1K, 1.5K or 2K")
    if level in PRO_SIZE_LEVELS:
        return PRO_SIZE_LEVELS[level]
    if level in ("3K", "4K"):
        return "2k"
    width, sep, height = level.lower().partition("x")
    if not sep or not width.isdigit() or not height.isdigit():
        raise ValueError(f"size {size!r}: use a level (1K, 1.5K, 2K...) or WxH")
    pixels = int(width) * int(height)
    if model_id == SEEDREAM_PRO and not PRO_MIN_PIXELS <= pixels <= PRO_MAX_PIXELS:
        raise ValueError(
            f"size {size!r}: {pixels} px is outside [{PRO_MIN_PIXELS}, {PRO_MAX_PIXELS}]"
        )
    return "1k" if pixels <= TIER_1K_MAX_PIXELS else "2k"


def _price(pricing: JsonPricingTable, model_id: str, unit: str) -> Decimal:
    try:
        return pricing.unit_price(model_id=model_id, unit=unit)
    except KeyError as exc:
        raise MissingPriceError(str(exc.args[0]) if exc.args else str(exc)) from None


def _has_unit(pricing: JsonPricingTable, model_id: str, unit: str) -> bool:
    try:
        pricing.unit_price(model_id=model_id, unit=unit)
    except KeyError:
        return False
    return True


def _image_price(pricing: JsonPricingTable, model_id: str, tier: str) -> Decimal:
    """A tiered model (any `per_image_<tier>` row, as 5.0 pro) prices per tier, and a
    missing tier is a `MissingPriceError` — never the flat `per_piece`. Only a model with
    no `per_image_*` row at all is priced by its flat `per_piece`."""
    if any(_has_unit(pricing, model_id, f"per_image_{t}") for t in IMAGE_TIERS):
        return _price(pricing, model_id, f"per_image_{tier}")
    return _price(pricing, model_id, "per_piece")


def quote(
    pricing: JsonPricingTable,
    *,
    model_id: str,
    size: str,
    references: int,
    layer_decomposition: bool = False,
    expected_layers: int = DEFAULT_EXPECTED_LAYERS,
) -> PriceQuote:
    """Price one generation.

    - The image: `per_image_<tier>` (5.0 pro) or the model's flat `per_piece`.
    - Input images from the second: `per_extra_reference_image`, looked up for every
      model. Only 5.0 pro charges them; the others carry an explicit 0 in v6, and a
      model without the row cannot be quoted with extra references.
    - Layer decomposition: (1 base + `expected_layers`) x `per_layer_<tier>`, with the
      worst case (1 + `MAX_LAYERS`) as `max_usd`; it takes exactly one input image.

    Every component that applies must have a row, or `MissingPriceError`.
    """
    if references < 0:
        raise ValueError("references cannot be negative")
    if model_id == SEEDREAM_PRO and references > PRO_MAX_REFERENCES:
        raise ValueError(f"{references} reference images; Seedream 5.0 pro takes at most 10")
    if not 0 <= expected_layers <= MAX_LAYERS:
        raise ValueError(f"expected_layers must be within 0..{MAX_LAYERS}")
    tier = size_tier(size, model_id=model_id)
    extra = max(references - 1, 0)
    refs = _price(pricing, model_id, "per_extra_reference_image") * extra if extra else Decimal(0)
    if layer_decomposition:
        if references != 1:
            raise ValueError("layer decomposition takes exactly one input image")
        unit = _price(pricing, model_id, f"per_layer_{tier}")
        expected, worst = 1 + expected_layers, 1 + MAX_LAYERS
    else:
        unit = _image_price(pricing, model_id, tier)
        expected = worst = 1
    return PriceQuote(
        model_id=model_id,
        pricing_version=pricing.version,
        size=size,
        tier=tier,
        references=references,
        layer_decomposition=layer_decomposition,
        unit_usd=unit,
        references_usd=refs,
        expected_images=expected,
        max_images=worst,
    )


# ---------------------------------------------------------------------------
# Spend ledger


def validate_ceiling(value: Decimal) -> Decimal:
    if not value.is_finite() or value <= 0:
        raise ValueError(f"the spending ceiling must be a positive amount, got {value}")
    if value > MAX_USD_CEILING:
        raise ValueError(
            f"the spending ceiling is at most USD {MAX_USD_CEILING} per run, got {value}"
        )
    return value


@dataclass(frozen=True)
class Reservation:
    number: int
    label: str
    amount_usd: Decimal


@dataclass
class SpendLedger:
    """Thread-safe spending ceiling for one run.

    `reserve` holds the quoted amount BEFORE a request is sent and raises
    `CeilingExceededError` when spent + held + that amount would pass the ceiling, so
    concurrent workers can never overrun it together. `settle` turns a reservation into
    spend (the request may have been billed); `release` drops it (the vendor answered
    that nothing was done). Each attempt — a retry included — is its own reservation,
    and each reservation closes exactly once.

    Nothing is clamped: when the vendor reports more than was reserved, `spent_usd`
    takes the real amount, `overage_usd` records the difference, and `over_ceiling_usd`
    says by how much the run passed its ceiling (the next reservation is then refused).
    """

    ceiling_usd: Decimal
    spent_usd: Decimal = Decimal(0)
    held_usd: Decimal = Decimal(0)
    reserved_usd: Decimal = Decimal(0)  # every amount ever reserved, retries included
    overage_usd: Decimal = Decimal(0)
    reservations: int = 0
    settlements: int = 0
    releases: int = 0
    _open: dict[int, Reservation] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.ceiling_usd = validate_ceiling(Decimal(self.ceiling_usd))

    @property
    def remaining_usd(self) -> Decimal:
        with self._lock:
            return self.ceiling_usd - self.spent_usd - self.held_usd

    @property
    def over_ceiling_usd(self) -> Decimal:
        with self._lock:
            return max(Decimal(0), self.spent_usd - self.ceiling_usd)

    @property
    def open_reservations(self) -> int:
        with self._lock:
            return len(self._open)

    def snapshot(self) -> dict[str, object]:
        """The ledger's numbers at one instant, as strings for a JSON report."""
        with self._lock:
            return {
                "ceiling_usd": str(self.ceiling_usd),
                "spent_usd": str(self.spent_usd),
                "held_usd": str(self.held_usd),
                "reserved_usd": str(self.reserved_usd),
                "overage_usd": str(self.overage_usd),
                "over_ceiling_usd": str(max(Decimal(0), self.spent_usd - self.ceiling_usd)),
                "reservations": self.reservations,
                "settlements": self.settlements,
                "releases": self.releases,
                "open_reservations": len(self._open),
            }

    def reserve(self, amount_usd: Decimal, *, label: str) -> Reservation:
        if amount_usd < 0:
            raise ValueError("a reservation cannot be negative")
        with self._lock:
            committed = self.spent_usd + self.held_usd
            if committed + amount_usd > self.ceiling_usd:
                raise CeilingExceededError(
                    f"{label}: reserving USD {amount_usd} would take the run to USD "
                    f"{committed + amount_usd}, over its ceiling of USD {self.ceiling_usd}"
                )
            self.reservations += 1
            reservation = Reservation(self.reservations, label, amount_usd)
            self._open[reservation.number] = reservation
            self.held_usd += amount_usd
            self.reserved_usd += amount_usd
            return reservation

    def _close(self, reservation: Reservation) -> None:
        if self._open.pop(reservation.number, None) is None:
            raise ValueError(f"reservation #{reservation.number} is not open")
        self.held_usd -= reservation.amount_usd

    def settle(self, reservation: Reservation, actual_usd: Decimal | None = None) -> Decimal:
        """Record what the request cost (the reserved amount when the vendor did not
        say) and return it. More than reserved is recorded as overage, never clamped."""
        with self._lock:
            self._close(reservation)
            amount = reservation.amount_usd if actual_usd is None else actual_usd
            if amount > reservation.amount_usd:
                self.overage_usd += amount - reservation.amount_usd
            self.spent_usd += amount
            self.settlements += 1
            return amount

    def release(self, reservation: Reservation) -> None:
        with self._lock:
            self._close(reservation)
            self.releases += 1


try:  # httpx ships with qualify-api; the transport is only needed by the paid path
    import httpx

    class LedgerTransport(httpx.BaseTransport):
        """Sits under the adapter's client: every outgoing POST reserves `quote` first,
        so the adapter's own retries are counted and stopped by the ceiling too.

        The reservation is the quote's worst case (`max_usd`). Only a 2xx settles it, at
        the vendor's `usage.generated_images` (0 for an error answer without usage, such
        as a moderated input; the worst case when the answer cannot be read). Any other
        status (3xx, 4xx, 5xx) releases it (BytePlus bills only successfully generated images). A
        `ConnectError` or `ConnectTimeout` releases it too: the request never reached
        the vendor. Any other transport error (a dropped connection, a read, write or
        pool timeout) settles the worst case: the vendor may have started.
        """

        def __init__(
            self,
            inner: httpx.BaseTransport,
            ledger: SpendLedger,
            planned_quote: PriceQuote,
            *,
            label: str,
            owns_inner: bool = False,
        ) -> None:
            self._inner = inner
            self._ledger = ledger
            self._quote = planned_quote
            self._label = label
            # A borrowed inner transport (shared by a whole run) is closed by its owner:
            # the adapter's `with httpx.Client(...)` closes this transport after every
            # request, and must not take the shared connection pool down with it.
            self._owns_inner = owns_inner

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if request.method != "POST":
                return self._inner.handle_request(request)
            reservation = self._ledger.reserve(self._quote.max_usd, label=self._label)
            # Each path below closes the reservation exactly once.
            try:
                response = self._inner.handle_request(request)
            except (httpx.ConnectError, httpx.ConnectTimeout):  # never reached the vendor
                self._ledger.release(reservation)
                raise
            except BaseException:  # dropped or timed out: the vendor may have billed
                self._ledger.settle(reservation)
                raise
            if not 200 <= response.status_code < 300:  # 3xx/4xx/5xx: nothing generated
                self._ledger.release(reservation)
                return response
            try:
                response.read()
            except BaseException:  # the answer was on its way: settle the worst case
                self._ledger.settle(reservation)
                raise
            self._ledger.settle(reservation, _actual_usd(response, self._quote))
            return response

        def close(self) -> None:
            if self._owns_inner:
                self._inner.close()

    def _actual_usd(response: httpx.Response, planned_quote: PriceQuote) -> Decimal | None:
        """The vendor's own count (`usage.generated_images`) priced. An answer that
        carries an error and no usage (a moderated input) generated nothing: 0, since
        BytePlus bills only successfully generated images. None (settle the reserved
        worst case) when the answer cannot be read."""
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        usage = body.get("usage")
        if usage is None:
            items = body.get("data") if isinstance(body.get("data"), list) else []
            errored = isinstance(body.get("error"), dict) or (
                bool(items)
                and all(isinstance(i, dict) and isinstance(i.get("error"), dict) for i in items)
            )
            return Decimal(0) if errored else None
        generated = usage.get("generated_images") if isinstance(usage, dict) else None
        if isinstance(generated, bool) or not isinstance(generated, int):
            return None  # missing or not an integer: the worst case
        return planned_quote.actual_usd(generated)

except ImportError:  # pragma: no cover - httpx is a qualify-api dependency
    pass


# ---------------------------------------------------------------------------
# Reference images


def _has_alpha(image: Image.Image) -> bool:
    if image.mode == "P" and "transparency" in image.info:
        return True
    if image.mode in ("RGB", "L") and "transparency" in image.info:
        return True  # tRNS chunk: one color is transparent
    return image.mode in ("RGBA", "LA", "PA")


def has_transparency(image: Image.Image) -> bool:
    """True when at least one pixel is not fully opaque."""
    if not _has_alpha(image):
        return False
    return image.convert("RGBA").getchannel("A").getextrema()[0] < 255


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def encode_reference(
    data: bytes,
    *,
    max_side: int = REFERENCE_MAX_SIDE,
    max_bytes: int = MAX_REFERENCE_BYTES,
) -> tuple[str, bytes]:
    """A reference image as (media type, bytes) for the model.

    With transparency it stays a PNG with its alpha (upright, at most `max_side` px,
    smaller if it does not fit `max_bytes`) — a logo's alpha is never flattened into a
    JPEG. Opaque images go through production's `to_reference_jpeg`.
    """
    image = Image.open(io.BytesIO(data))
    if not has_transparency(image):
        out = to_reference_jpeg(data, max_side=max_side)
        if len(out) > max_bytes:
            raise ValueError(f"reference JPEG is {len(out)} bytes, over {max_bytes}")
        return "image/jpeg", out
    image = ImageOps.exif_transpose(image).convert("RGBA")
    image.thumbnail((max_side, max_side), Image.LANCZOS)
    out = png_bytes(image)
    for side in _PNG_FALLBACK_SIDES:
        if len(out) <= max_bytes:
            break
        smaller = image.copy()
        smaller.thumbnail((side, side), Image.LANCZOS)
        out = png_bytes(smaller)
    if len(out) > max_bytes:
        raise ValueError(f"reference PNG is {len(out)} bytes, over {max_bytes}")
    return "image/png", out


def reference_data_url(data: bytes, **limits: int) -> str:
    media_type, out = encode_reference(data, **limits)
    return f"data:{media_type};base64,{base64.b64encode(out).decode('ascii')}"


# ---------------------------------------------------------------------------
# Network guard for the dry run

_guard_lock = threading.Lock()
_guard_state = {"installed": False, "depth": 0, "blocked": 0}
_NETWORK_EVENTS = frozenset(
    {
        "socket.bind",
        "socket.connect",
        "socket.getaddrinfo",
        "socket.gethostbyaddr",
        "socket.gethostbyname",
        "socket.getnameinfo",
        "socket.sendmsg",
        "socket.sendto",
    }
)


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if _guard_state["depth"] and event in _NETWORK_EVENTS:
        _guard_state["blocked"] += 1
        raise RuntimeError(f"network access blocked during a dry run ({event})")


@contextlib.contextmanager
def network_guard() -> Iterator[dict[str, int]]:
    """While active, any socket connect or DNS lookup in this process raises, and is
    counted in the yielded `stats["blocked"]` — a dry run proves it sent nothing.

    The audit hook is installed once per process (hooks cannot be removed) and does
    nothing outside the guard.
    """
    with _guard_lock:
        if not _guard_state["installed"]:
            sys.addaudithook(_audit)
            _guard_state["installed"] = True
        _guard_state["depth"] += 1
        before = _guard_state["blocked"]
    stats = {"blocked": 0}
    try:
        yield stats
    finally:
        with _guard_lock:
            _guard_state["depth"] -= 1
            stats["blocked"] = _guard_state["blocked"] - before
