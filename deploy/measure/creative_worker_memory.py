"""Real queue preparation and concurrent download memory, with fake vendor boundaries.

Run only through creative-worker-memory.sh (isolated DB/network and production deps).
No service/preparation/download implementation is replaced. Providers return synthetic
copy/images, and httpx's transport streams synthetic video chunks without allocating
an entire fake body first. Memory includes kernel page cache (cgroup memory.peak).
"""

from __future__ import annotations

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from webhook_worker_memory import RESULTS, reading


def fake_r2(*, serve=False):
    import hashlib
    import tempfile
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    root = Path(tempfile.mkdtemp(prefix="memory-r2-"))

    class Handler(BaseHTTPRequestHandler):
        def path_for(self):
            return root / hashlib.sha256(self.path.split("?")[0].encode()).hexdigest()

        def do_PUT(self):
            remaining = int(self.headers["content-length"])
            with self.path_for().open("wb") as out:
                while remaining:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise RuntimeError("truncated fake upload")
                    out.write(chunk)
                    remaining -= len(chunk)
            self.send_response(200)
            self.send_header("ETag", '"measure"')
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_HEAD(self):
            path = self.path_for()
            if not path.exists():
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()

        def do_GET(self):
            path = self.path_for()
            if not path.exists():
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(
        ("0.0.0.0" if serve else "127.0.0.1", 8080 if serve else 0), Handler
    )
    if serve:
        server.serve_forever()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def seed():
    from qualify_api.creative import models as orm
    from qualify_api.tenancy.models import Brand, Tenant, User
    from qualify_shared.db.admin import admin_session
    from qualify_shared.db.session import tenant_session

    tenant = uuid4()
    tone = dict(formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=40)
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="memory-only", country="CO", timezone="UTC", currency="COP")
        )
        session.flush()
        brand = Brand(tenant_id=tenant, name="Synthetic memory fixture")
        user = User(tenant_id=tenant, email=f"{uuid4()}@example.invalid", display_name="Measure")
        session.add_all([brand, user])
        session.flush()
        brand_id, user_id = brand.id, user.id
    with tenant_session(tenant) as session:
        session.add(
            orm.BrandKit(
                tenant_id=tenant,
                brand_id=brand_id,
                positioning="Arepas artesanales",
                audience="Clientes de Cali",
                language="es",
                regional_variant="es-CO",
                tone_axes=tone,
                banned_words=[],
                emoji_policy="sparse",
                image_policy={"allowed_routes": ["template_only", "from_upload", "generate"]},
            )
        )
        session.add(
            orm.BrandVoiceProfile(
                tenant_id=tenant,
                brand_id=brand_id,
                version=1,
                status="active",
                profile={"tone_axes": tone},
                sources=[{"kind": "manual_kit", "ref": "seed", "excerpt": "synthetic"}],
                distilled_by_model="measure",
            )
        )
    return tenant, brand_id, user_id


class Provider:
    def __init__(self, name):
        from qualify_creative.enums import GenerationTask

        self.name = name
        self.supports = frozenset(GenerationTask)
        self.calls = 0

    def estimate_cost_usd(self, *args, **kwargs):
        return Decimal("0.01")

    def generate(self, request, *, api_key):
        from qualify_creative.enums import GenerationTask
        from qualify_creative.providers import GenerationResult, Usage

        self.calls += 1
        if request.task == GenerationTask.COPY:
            payload = {
                "hook": "Arepas recién hechas",
                "caption": (
                    "Maíz molido en casa y queso fresco para compartir en Cali. "
                    "Pide tus arepas artesanales hoy y disfruta el sabor de nuestra cocina."
                ),
                "hashtags": ["arepas", "cali"],
                "cta": "Pide hoy",
            }
        else:
            from PIL import Image

            image = Image.effect_noise((2048, 2048), 50).convert("RGB")
            out = io.BytesIO()
            image.save(out, "PNG")
            payload = {"images": [out.getvalue()]}
        return GenerationResult(
            payload=payload,
            model_id="claude-opus-5" if self.name == "anthropic" else "seedream-5-0-lite-260128",
            provider=self.name,
            usage=Usage(input_tokens=1200, output_tokens=400)
            if self.name == "anthropic"
            else Usage(pieces=1),
        )


def prepare():
    from qualify_api.creative.composition import production_content_service
    from qualify_api.creative.pipeline import PipelineStore
    from qualify_api.creative.worker.pipeline import PipelinePreparation
    from qualify_creative.schemas import ContentBrief
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import text

    service = production_content_service()
    router = service._router.router
    providers = {name: Provider(name) for name in ("anthropic", "seedream")}
    router._providers = providers  # Only remote vendor boundary, real router/checkpoint/media/DB.
    tenant, brand, user = seed()
    preparation = PipelinePreparation(service, PipelineStore(), (tenant,))
    preparation()
    reading("a-idle", "production service wired; real preparation over empty tenant")
    brief = ContentBrief.model_validate(
        dict(
            brand_id=brand,
            objective="sale",
            content_type="menu",
            topic="Arepas artesanales",
            kind="carousel",
            image_route="template_only",
            variants_requested=1,
            media=dict(
                slides=[
                    dict(source="generated", scene_prompt=f"Arepas en plato {n}") for n in range(10)
                ]
            ),
        )
    )
    draft = service.create_draft(tenant_id=tenant, brand_id=brand, user_id=user, brief=brief)
    preparation()
    with tenant_session(tenant) as session:
        status = session.scalar(text("SELECT status FROM content_drafts WHERE id=:d"), {"d": draft})
        images = session.scalar(
            text("SELECT count(*) FROM image_assets WHERE draft_id=:d"), {"d": draft}
        )
    assert status == "generated" and images == 10, (status, images)
    assert providers["seedream"].calls == 10
    reading(
        "b-carousel",
        f"real preparation, 10 generated 2048px PNG slides; assets={images}; vendor_calls="
        + str({k: v.calls for k, v in providers.items()}),
    )
    video_brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "slides": tuple(
                        slide.model_copy(
                            update={
                                "source": __import__(
                                    "qualify_creative.enums", fromlist=["SlideSource"]
                                ).SlideSource.ANIMATED
                            }
                        )
                        for slide in brief.media.slides[:2]
                    )
                }
            )
        }
    )
    video = service.create_draft(tenant_id=tenant, brand_id=brand, user_id=user, brief=video_brief)
    preparation()
    return service, tenant, video


def downloads(size_mib, service, tenant, draft):
    from unittest.mock import patch

    import httpx
    from qualify_api.creative.worker.downloads import DownloadGate

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            chunk = b"x" * (1024 * 1024)
            for _ in range(size_mib):
                yield chunk

    def handle(request):
        return httpx.Response(200, stream=Body())

    original = httpx.Client

    def client(*args, **kwargs):
        return original(*args, **kwargs, transport=httpx.MockTransport(handle))

    from types import SimpleNamespace

    from qualify_api.creative.pipeline import PipelineStore
    from qualify_api.creative.worker.executor import JobContext
    from qualify_api.creative.worker.pipeline import PipelineExecutor
    from qualify_creative.providers import GenerationResult, Usage
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import text

    class Adapter:
        def poll(self, *args, **kwargs):
            return SimpleNamespace(status="succeeded")

        def result(self, request, state):
            return GenerationResult(
                payload={},
                model_id="seedance-2-5",
                provider="seedance",
                usage=Usage(),
                media_url="https://vendor.invalid/synthetic.mp4",
            )

    with tenant_session(tenant) as session:
        rows = (
            session.execute(
                text(
                    "SELECT j.* FROM creative_jobs j "
                    "JOIN creative_pipeline_steps s ON s.job_id=j.id "
                    "WHERE j.draft_id=:d ORDER BY j.position"
                ),
                {"d": draft},
            )
            .mappings()
            .all()
        )
    assert len(rows) == 2, len(rows)
    jobs = [
        JobContext(
            row["id"],
            tenant,
            draft,
            row["kind"],
            row["revision"],
            row["position"],
            row["vendor_model"],
            row["lane"],
            0,
            row["deadline"],
        )
        for row in rows
    ]
    executor = PipelineExecutor(service, PipelineStore(), Adapter(), "seedance")
    gate = DownloadGate(2)

    def one(job):
        with gate.hold():
            executor.finish(job, "synthetic-task", "succeeded")
        return job.job_id

    with patch.object(httpx, "Client", client), ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(one, jobs))) == 2
    assert gate.peak == 2
    reading(
        "c-downloads",
        "two concurrent real PipelineExecutor.finish including guarded download/R2/checkpoint; "
        f"{size_mib} MiB each; gate_peak={gate.peak}",
    )


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--download-mib", type=int, default=200)
    args = parser.parse_args()
    reading("0-interpreter", "production dependency image, current source mounted read-only")
    os.environ.update(
        QUALIFY_R2_ENDPOINT_URL=os.environ.get("QUALIFY_R2_ENDPOINT_URL") or fake_r2(),
        QUALIFY_R2_ACCESS_KEY_ID="measure",
        QUALIFY_R2_SECRET_ACCESS_KEY="measure",
        QUALIFY_R2_BUCKET="measure",
    )
    import threading
    import time

    high = {"current": 0, "stat": ""}
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            current = int(Path("/sys/fs/cgroup/memory.current").read_text())
            if current > high["current"]:
                high.update(current=current, stat=Path("/sys/fs/cgroup/memory.stat").read_text())
            time.sleep(0.02)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    service, tenant, draft = prepare()
    downloads(args.download_mib, service, tenant, draft)
    stop.set()
    sampler.join()
    print("MEASURE-PEAK-STAT " + json.dumps(high), flush=True)
    peak = int(Path("/sys/fs/cgroup/memory.peak").read_text())
    cap = int(Path("/sys/fs/cgroup/memory.max").read_text())
    events = Path("/sys/fs/cgroup/memory.events").read_text()
    print(
        "MEASURE-DONE "
        + json.dumps(
            {"phases": RESULTS, "peak_percent": round(100 * peak / cap, 2), "events": events}
        ),
        flush=True,
    )
    return 0 if peak < cap * 0.95 and "oom_kill 0" in events else 1


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--serve-r2"]:
        fake_r2(serve=True)
    else:
        raise SystemExit(main())
