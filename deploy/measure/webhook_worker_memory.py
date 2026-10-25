"""Peak memory of the `webhook-worker` process, phase by phase (m-24852538).

Run INSIDE the production Python image under the production cap, against a throwaway
Postgres on a docker network with no route out — `deploy/measure/webhook-worker-memory.sh`
sets all of that up; do not run this file against a real database.

One process, like the worker: each phase adds to what the earlier ones left loaded, and the
numbers printed after each are the running peaks.

  a. idle     — what `webhooks.worker._run_loop` builds at start (processor, prefill runner,
                queue), the start-up purge and sweeps, one empty batch + prefill pass.
  b. batch    — `DEFAULT_BATCH` recorded webhook changes (Instagram comments, mentions,
                Direct messages, WhatsApp messages) through the REAL processor and queue, twice.
  c. prefill  — one Alta job through the REAL `AltaPrefillRunner` and `prefill_brand_kit`:
                the real ScrapeCreators client, httpx, the Anthropic SDK (two Claude runs:
                rubro + catalog with tool turns) and Pillow on a 1080x1080 JPEG profile
                picture. Only the far ends are fake: the vendors answer from recorded-shape
                bodies through `httpx.MockTransport`, the job queue/claims/cache/Brand Kit
                store are the in-memory fakes, and the Meegle comment goes to a list.
  d. sentiment (optional, `--sentiment`) — one robertuito classification, what the
                comment-analysis sweep of the same loop does when comments are pending.

Nothing here can reach a vendor or Meegle: the container has no network route out, and
every HTTP client of phase c is a MockTransport.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import io
import json
import os
import random
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

FIXTURES = Path(os.environ.get("MEASURE_FIXTURES", "/fixtures"))
CGROUP = Path("/sys/fs/cgroup")


# --------------------------------------------------------------------------------------
# readings
# --------------------------------------------------------------------------------------


def _status_kib(key: str) -> int:
    status = Path("/proc/self/status")
    if not status.exists():  # not Linux: only a dry run of the script itself
        return -1
    for line in status.read_text().splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1])
    return -1


def _cgroup_mib(name: str) -> float | None:
    try:
        return int((CGROUP / name).read_text().strip()) / 1024 / 1024
    except (OSError, ValueError):
        return None


def _limit_mib() -> float | None:
    try:
        raw = (CGROUP / "memory.max").read_text().strip()
    except OSError:
        return None
    return None if raw == "max" else int(raw) / 1024 / 1024


RESULTS: list[dict[str, Any]] = []


def reading(phase: str, note: str = "") -> None:
    gc.collect()
    row = {
        "phase": phase,
        "rss_mib": round(_status_kib("VmRSS") / 1024, 1),
        "peak_rss_mib": round(_status_kib("VmHWM") / 1024, 1),
        "cgroup_current_mib": _round(_cgroup_mib("memory.current")),
        "cgroup_peak_mib": _round(_cgroup_mib("memory.peak")),
        "limit_mib": _round(_limit_mib()),
        "note": note,
    }
    RESULTS.append(row)
    print("MEASURE " + json.dumps(row, ensure_ascii=False), flush=True)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


# --------------------------------------------------------------------------------------
# a. idle
# --------------------------------------------------------------------------------------


def phase_idle() -> tuple[Any, Any]:
    from qualify_api.webhooks import worker
    from qualify_api.webhooks.processor import DEFAULT_BATCH, production_processor
    from qualify_api.webhooks.repository import WebhookQueue

    reading("0-interpreter", "python + the worker module imported")
    wid = worker.worker_id()
    processor = production_processor(worker_id=wid)
    prefill = worker._prefill_runner(wid)  # noqa: SLF001 - the loop's own start-up
    assert prefill is not None, "Meegle settings missing: the runner would not be built"
    queue = WebhookQueue()
    worker._auto_purge(queue)  # noqa: SLF001
    asyncio.run(worker._sentiment_sweep())  # noqa: SLF001
    asyncio.run(worker._comment_analysis_sweep())  # noqa: SLF001
    report = asyncio.run(processor.run_once(limit=DEFAULT_BATCH))
    asyncio.run(worker._alta_prefill_pass(prefill))  # noqa: SLF001
    reading("a-idle", f"empty batch claimed={report.claimed}")
    return processor, prefill


# --------------------------------------------------------------------------------------
# b. a batch of webhook changes
# --------------------------------------------------------------------------------------

_WORDS = (
    "hola quiero saber el precio del helado de yogur con fresas y si hacen domicilios "
    "a la zona norte de cucuta gracias que rico se ve todo @heladeria.demo"
).split()


def _text(rng: random.Random, words: int = 40) -> str:
    return " ".join(rng.choice(_WORDS) for _ in range(words))


def _deliveries(rng: random.Random, per_kind: int) -> list[bytes]:
    now = int(time.time())
    out: list[dict[str, Any]] = []
    # Instagram: comments + mentions on accounts no tenant connected (orphan/unsupported)
    out.append(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": f"1784{rng.randrange(10**11):011d}",
                    "time": now,
                    "changes": [
                        {
                            "field": "comments",
                            "value": {
                                "from": {"id": str(rng.randrange(10**15)), "username": "cliente"},
                                "media": {
                                    "id": str(rng.randrange(10**17)),
                                    "media_product_type": "REELS",
                                },
                                "id": str(rng.randrange(10**17)),
                                "text": _text(rng),
                            },
                        }
                    ],
                }
                for _ in range(per_kind)
            ],
        }
    )
    out.append(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": f"1784{rng.randrange(10**11):011d}",
                    "time": now,
                    "changes": [
                        {
                            "field": "mentions",
                            "value": {
                                "media_id": str(rng.randrange(10**17)),
                                "comment_id": str(rng.randrange(10**17)),
                            },
                        }
                    ],
                }
                for _ in range(per_kind)
            ],
        }
    )
    out.append(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": f"1784{rng.randrange(10**11):011d}",
                    "time": now,
                    "messaging": [
                        {
                            "sender": {"id": str(rng.randrange(10**15))},
                            "recipient": {"id": str(rng.randrange(10**15))},
                            "timestamp": now * 1000,
                            "message": {"mid": f"aWdf{uuid4().hex}", "text": _text(rng, 25)},
                        }
                    ],
                }
                for _ in range(per_kind)
            ],
        }
    )
    out.append(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": str(rng.randrange(10**15)),
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "573000000000",
                                    "phone_number_id": str(rng.randrange(10**15)),
                                },
                                "contacts": [
                                    {"profile": {"name": "Cliente"}, "wa_id": "573001112233"}
                                ],
                                "messages": [
                                    {
                                        "from": "573001112233",
                                        "id": f"wamid.{uuid4().hex}",
                                        "timestamp": str(now),
                                        "type": "text",
                                        "text": {"body": _text(rng, 25)},
                                    }
                                ],
                            },
                        }
                    ],
                }
                for _ in range(per_kind)
            ],
        }
    )
    return [json.dumps(d, ensure_ascii=False).encode() for d in out]


def phase_batch(processor: Any, rounds: int) -> None:
    from qualify_api.webhooks.processor import DEFAULT_BATCH
    from qualify_api.webhooks.receiver import record_delivery

    rng = random.Random(24852538)
    outcomes: dict[str, int] = {}
    claimed = 0
    for _ in range(rounds):
        for body in _deliveries(rng, per_kind=DEFAULT_BATCH // 4 + 1):
            record_delivery(body=body, signature_header="sha256=measure")
        report = asyncio.run(processor.run_once(limit=DEFAULT_BATCH))
        claimed += report.claimed
        for key, value in report.outcomes.items():
            outcomes[str(key)] = outcomes.get(str(key), 0) + value
    reading("b-batch", f"{rounds} x run_once(limit={DEFAULT_BATCH}) claimed={claimed} {outcomes}")


# --------------------------------------------------------------------------------------
# c. one Alta prefill job
# --------------------------------------------------------------------------------------


def _profile_picture(size: int) -> bytes:
    """A photo-like JPEG (gradient + noise + shapes), as Instagram's CDN serves them."""
    from PIL import Image, ImageDraw, ImageFilter

    rng = random.Random(size)
    image = Image.effect_noise((size, size), 64).convert("RGB")
    overlay = Image.linear_gradient("L").resize((size, size)).convert("RGB")
    image = Image.blend(image, overlay, 0.5)
    draw = ImageDraw.Draw(image)
    for _ in range(40):
        x, y = rng.randrange(size), rng.randrange(size)
        r = rng.randrange(size // 20, size // 4)
        fill = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)
    image = image.filter(ImageFilter.GaussianBlur(2))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def _pad(rng: random.Random, kib: int) -> dict[str, str]:
    """Bulk the recorded bodies up to what the live endpoints return (tens of KiB per
    post: image candidates, user objects, tracking strings)."""
    return {f"extra_{i}": "x" * 1024 for i in range(kib)} | {"seed": str(rng.random())}


class _Vendor:
    """ScrapeCreators + the Instagram CDN, from the test fixtures, bulked to live size."""

    def __init__(self, picture: bytes) -> None:
        rng = random.Random(7)
        self.profile = json.loads((FIXTURES / "instagram_profile_heladeria.json").read_text())
        self.profile["data"]["user"]["padding"] = _pad(rng, 120)
        posts = json.loads((FIXTURES / "instagram_posts_heladeria.json").read_text())
        items = posts["items"]
        now = int(time.time())
        grown = []
        for i in range(12):  # a full page
            item = json.loads(json.dumps(items[i % len(items)]))
            item["taken_at"] = now - (i + 1) * 3600 * 10
            item["padding"] = _pad(rng, 30)
            grown.append(item)
        posts["items"] = grown
        self.posts = posts
        self.picture = picture
        self.requests: list[str] = []

    def handler(self, request: Any) -> Any:
        import httpx

        self.requests.append(f"{request.url.host}{request.url.path}")
        if request.url.host.endswith("cdninstagram.com"):
            return httpx.Response(200, content=self.picture, headers={"content-type": "image/jpeg"})
        if request.url.path == "/v1/instagram/profile":
            return httpx.Response(200, json=self.profile)
        if request.url.path == "/v2/instagram/user/posts":
            return httpx.Response(200, json=self.posts)
        return httpx.Response(404, json={"success": False})


class _Claude:
    """The Messages API at the HTTP level, so the real Anthropic SDK builds, sends and
    parses every turn. Answers what each tool loop needs to finish."""

    def __init__(self) -> None:
        self.turns = 0

    def handler(self, request: Any) -> Any:
        import httpx2 as httpx  # the Anthropic SDK carries its own HTTP stack

        body = json.loads(request.content)
        self.turns += 1
        tools = {t["name"] for t in body.get("tools", [])}
        answered = any(
            isinstance(m.get("content"), list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"])
            for m in body.get("messages", [])
        )
        if "proponer_hashtags" in tools:
            name, payload = (
                "proponer_hashtags",
                {
                    "rubro": "heladería de yogur artesanal",
                    "hashtags": [
                        {"tag": t, "reason": "Lo dice la bio de la cuenta."}
                        for t in ("heladeriadeyogur", "helados", "postres", "cucuta", "yogurt")
                    ],
                },
            )
        elif "elegir_hashtags" in tools and not answered:
            name, payload = "buscar_hashtags", {"consulta": "helados"}
        elif "elegir_hashtags" in tools:
            name, payload = (
                "elegir_hashtags",
                {"picks": [{"tag": "helados", "fit": "alta", "reason": "Mismo producto."}]},
            )
        else:
            return httpx.Response(400, json={"type": "error", "error": {"type": "x"}})
        content = [
            {"type": "thinking", "thinking": "Razonamiento. " * 400, "signature": "s" * 2000},
            {"type": "tool_use", "id": f"toolu_{uuid4().hex[:24]}", "name": name, "input": payload},
        ]
        return httpx.Response(
            200,
            json={
                "id": f"msg_{uuid4().hex[:24]}",
                "type": "message",
                "role": "assistant",
                "model": body.get("model", "claude-sonnet-5"),
                "content": content,
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 2500,
                    "output_tokens": 900,
                    "cache_creation_input_tokens": 1800,
                    "cache_read_input_tokens": 0,
                },
            },
        )


class _Claims:
    def claim(self, *a: Any) -> bool:
        return True

    def release(self, *a: Any) -> None:
        return None

    def keep_only(self, *a: Any) -> None:
        return None


class _Cache:
    def __init__(self) -> None:
        self.entries: dict[tuple[Any, ...], dict[str, Any]] = {}

    def get(self, tenant_id: UUID, network: str, handle: str) -> dict[str, Any] | None:
        return self.entries.get((tenant_id, network, handle))

    def put(self, tenant_id: UUID, network: str, handle: str, profile: dict[str, Any]) -> None:
        self.entries[(tenant_id, network, handle)] = profile


class _Store:
    def __init__(self) -> None:
        self.written: list[Any] = []

    def set_document_key(self, **kwargs: Any) -> bool:
        json.dumps(kwargs["value"], default=str)  # what the real one serializes
        self.written.append(kwargs["value"])
        return True


class _FakeR2:
    """A local S3 endpoint that accepts every PUT, so the REAL keeper → `ObjectGate` →
    boto3 path of m-24852537 runs (`QUALIFY_R2_ENDPOINT_URL` points here). Stdlib only,
    a daemon thread of this process: its own footprint is a few hundred KiB."""

    puts: list[tuple[str, int]] = []

    @classmethod
    def start(cls) -> str:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self) -> None:  # noqa: N802 - http.server's naming
                size = int(self.headers.get("content-length") or 0)
                self.rfile.read(size)
                cls.puts.append((self.path, size))
                self.send_response(200)
                self.send_header("ETag", '"measure"')
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{server.server_address[1]}"


def phase_prefill(picture_px: int, label: str) -> None:
    import anthropic
    import httpx
    import httpx2
    from qualify_api.creative.brand_prefill import CatalogHashtags, PrefillPorts, prefill_brand_kit
    from qualify_api.hashtags import MemoryHashtagRepository, from_profile
    from qualify_api.hashtags import ai as hashtag_ai
    from qualify_api.meegle import prefill as alta
    from qualify_api.meegle.prefill_jobs import InMemoryPrefillJobs, NewPrefillJob

    picture = _profile_picture(picture_px)
    vendor = _Vendor(picture)
    claude = _Claude()

    def client_factory(api_key: str) -> Any:
        # `prefill.bounded_claude_client`, with the far end replaced
        return anthropic.Anthropic(
            api_key=api_key,
            timeout=alta.CLAUDE_TIMEOUT_SECONDS,
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(claude.handler)),
        )

    store = _Store()
    ports = PrefillPorts(
        claims=_Claims(),
        cache=_Cache(),
        store=store,
        catalog=CatalogHashtags(
            repository=MemoryHashtagRepository(),
            selector=partial(hashtag_ai.select_hashtags, client_factory=client_factory),
        ),
        generate=partial(from_profile.generate, client_factory=client_factory),
        transport=httpx.MockTransport(vendor.handler),
    )
    comments: list[tuple[int, str]] = []
    jobs = InMemoryPrefillJobs()
    settings = alta.AltaPrefillSettings.from_env()
    assert settings.active, f"prefill settings inactive: {settings.reason}"
    tenant, brand, item = uuid4(), uuid4(), 24852538
    jobs.enqueue(
        NewPrefillJob(
            tenant_id=tenant,
            brand_id=brand,
            meegle_work_item_id=item,
            network=alta.NETWORK,
            handle="@heladeria.demo",
            max_usd=settings.max_usd or Decimal("1"),
            pipeline_version=alta.PIPELINE_VERSION,
        )
    )
    runner = alta.AltaPrefillRunner(
        jobs,
        lambda work_item_id, text: comments.append((work_item_id, text)),
        worker_id="measure",
        settings=lambda: settings,
        prefill=partial(prefill_brand_kit, ports=ports),
        clock=lambda: datetime.now(UTC),
    )
    report = runner.run_once()
    proposal = (store.written[-1] or {}).get("proposal") if store.written else None
    palette = (proposal or {}).get("palette") or {}
    kept = ((proposal or {}).get("profile") or {}).get("pic_key", "")
    assert kept and _FakeR2.puts, "the profile picture did not reach the (fake) R2"
    reading(
        label,
        f"picture {picture_px}px {len(picture) // 1024} KiB; report={dict(report)}; "
        f"claude_turns={claude.turns}; vendor_requests={len(vendor.requests)}; "
        f"r2_puts={len(_FakeR2.puts)}; palette={palette.get('logo_colors')}; "
        f"comments={[c for _, c in comments]}",
    )


# --------------------------------------------------------------------------------------
# d. robertuito (the comment-analysis sweep of the same loop)
# --------------------------------------------------------------------------------------


def phase_sentiment() -> None:
    from qualify_models.sentiment import run_sentiment

    labels = [
        run_sentiment(_text(random.Random(i), 30), f"c{i}", "measure").label for i in range(25)
    ]
    reading("d-sentiment", f"robertuito over {len(labels)} comments: {sorted(set(labels))}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=2, help="phase b: batches")
    parser.add_argument("--picture", type=int, default=1080, help="phase c: picture side, px")
    parser.add_argument(
        "--big-picture", type=int, default=0, help="phase c2: a second job with this side"
    )
    parser.add_argument("--sentiment", action="store_true", help="phase d: robertuito")
    args = parser.parse_args()

    import logging

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    os.environ["QUALIFY_R2_ENDPOINT_URL"] = _FakeR2.start()
    for name, value in (
        ("QUALIFY_R2_ACCESS_KEY_ID", "measure"),
        ("QUALIFY_R2_SECRET_ACCESS_KEY", "measure"),
        ("QUALIFY_R2_BUCKET", "measure"),
    ):
        os.environ[name] = value
    processor, _prefill = phase_idle()
    phase_batch(processor, args.rounds)
    phase_prefill(args.picture, "c-prefill")
    if args.big_picture:
        phase_prefill(args.big_picture, "c2-prefill-big-picture")
    if args.sentiment:
        phase_sentiment()
    print("MEASURE-DONE " + json.dumps(RESULTS, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
