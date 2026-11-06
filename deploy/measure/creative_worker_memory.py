"""Real queue preparation and concurrent download memory, with fake vendor boundaries.

Run only through creative-worker-memory.sh (isolated DB/network and production deps).
No service/preparation/download implementation is replaced. Providers return synthetic
copy/images, and httpx's transport streams synthetic video chunks without allocating
an entire fake body first. Memory includes kernel page cache (cgroup memory.peak).

VE-10a: the last phase is a video by parts' `join` (`d-join`): a real parent (its text
by the real preparation), its real parts (`PartsService.create_parts`) and, at the vendor
boundary, each part's vista previa = one synthetic 1080p part of `/parts` (made outside
this container by `join_memory.py make`) put in the fake R2 as the part's preview; then
the real `PipelinePreparation` runs the parent's `join` phase (R2 -> disk -> PyAV ->
R2). Only `part_join.JOIN_PREVIEW_SIZE` (a constant: the encoded size) is set from
`--join-size`; nothing of the join is replaced. The synthetic brand has a logo, so the
join lays it (one `overlay` stage in each part's filter graph), as production does;
`--no-join-logo` measures without it.

The join phase reports its OWN peak (the highest cgroup `memory.current` and RSS seen
while it runs), also when it fails: a `MEASURE-JOIN-PROGRESS` line every 5 s survives an
OOM kill, and a join that saves nothing ends in `MEASURE-JOIN-FAILED` (exit 1) instead
of a traceback. `--only-join` measures it in a FRESH worker process (no carousel nor
downloads before it): the second figure next to the whole-process one.
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


class PhasePeak:
    """The highest memory seen while one phase runs (cgroup `memory.current` and the
    process RSS), sampled every 20 ms; a progress line every 5 s so an OOM kill still
    leaves the last value in the log."""

    def __init__(self, phase):
        import threading

        self.phase = phase
        self.cgroup = 0
        self.rss_kib = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @staticmethod
    def _cgroup_now():
        try:
            return int(Path("/sys/fs/cgroup/memory.current").read_text())
        except (OSError, ValueError):
            return 0

    @staticmethod
    def _rss_now():
        try:
            for line in Path("/proc/self/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
        except (OSError, ValueError):
            pass
        return 0

    def snapshot(self):
        return {
            "phase": self.phase,
            "phase_cgroup_peak_mib": round(self.cgroup / 2**20, 1),
            "phase_rss_peak_mib": round(self.rss_kib / 1024, 1),
        }

    def _run(self):
        import time

        last = 0.0
        while not self._stop.is_set():
            self.cgroup = max(self.cgroup, self._cgroup_now())
            self.rss_kib = max(self.rss_kib, self._rss_now())
            if time.monotonic() - last >= 5:
                last = time.monotonic()
                print("MEASURE-JOIN-PROGRESS " + json.dumps(self.snapshot()), flush=True)
            time.sleep(0.02)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        return False


def join_phase(service, tenant, brand, user, folder, size, logo=True):
    """VE-10a: the parent's `join` phase over the synthetic 1080p parts in `folder`."""
    import time

    import av
    from qualify_api.creative import part_join
    from qualify_api.creative.media import generated_object_key
    from qualify_api.creative.parts import PartsService, mark_parent_dirty
    from qualify_api.creative.pipeline import PipelineStore
    from qualify_api.creative.worker.pipeline import PipelinePreparation
    from qualify_creative.schemas import ContentBrief
    from qualify_shared.db.session import tenant_session, tenant_unit_of_work
    from sqlalchemy import text

    files = sorted(Path(folder).glob("part-*.mp4"))
    assert files, f"no synthetic parts in {folder}"
    with av.open(str(files[0])) as probe:
        stream = probe.streams.video[0]
        seconds = max(1, min(10, round(float(stream.duration * stream.time_base))))
    part_join.JOIN_PREVIEW_SIZE = size
    preparation = PipelinePreparation(service, PipelineStore(), (tenant,))
    logo_key = None
    if logo:
        # the synthetic brand's logo (Deivid, 2026-11-06: the joined preview carries it):
        # the join then lays it over every frame — the overlay stage is measured too
        from PIL import Image

        out = io.BytesIO()
        Image.effect_noise((600, 600), 80).convert("RGBA").save(out, "PNG")
        logo_key = f"t/{tenant}/brand/measure-logo-{uuid4().hex[:8]}.png"
        assert service._media._store.keep(tenant, logo_key, out.getvalue(), "image/png")
        from qualify_api.creative import models as orm

        with tenant_session(tenant) as session:  # a Brand Kit logo, as the owner uploads it
            session.add(
                orm.BrandKitAsset(
                    tenant_id=tenant,
                    brand_id=brand,
                    kind="logo",
                    object_key=logo_key,
                    filename="logo.png",
                    content_type="image/png",
                )
            )
    brief = ContentBrief.model_validate(
        dict(
            brand_id=brand,
            objective="sale",
            content_type="menu",
            topic="Arepas artesanales",
            kind="shot_video",
            format="reels_9_16",
            image_route="template_only",
            variants_requested=1,
            media=dict(
                parts=[
                    dict(seconds=seconds, description=f"Plano {n + 1} de las arepas")
                    for n in range(len(files))
                ],
                brand_logo_key=logo_key,
            ),
        )
    )
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, user_id=user, brief=brief)
    preparation()  # the parent's text only: it ends `generated`, never waits in drafting
    with tenant_session(tenant) as session:
        status = session.scalar(
            text("SELECT status FROM content_drafts WHERE id=:d"), {"d": parent}
        )
    assert status == "generated", status
    children = PartsService(service).create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    store = service._media._store
    for index, (child, path) in enumerate(zip(children, files, strict=True), start=1):
        # the vendor boundary: this part's vista previa is the synthetic 1080p file
        key = generated_object_key(tenant, child, 1, "clip.mp4")
        assert store.keep_file(tenant, key, path, "video/mp4")
        params = {
            "part": {
                "index": index,
                "mode": "reference",
                "seconds": seconds,
                "generation_seconds": seconds,
                "window": None,
            },
            "draft": {
                "status": "draft",
                "created_at": time.time(),
                "model": "seedance-2-5",
                "finish": "clip",
            },
        }
        with tenant_unit_of_work(tenant) as session:
            version = session.execute(
                text(
                    "INSERT INTO piece_versions (tenant_id, brand_id, draft_id, revision, "
                    "model_id, requires_ai_disclosure) VALUES (:t, :b, :d, 1, "
                    "'seedance-2-5', true) RETURNING id"
                ),
                {"t": tenant, "b": brand, "d": child},
            ).scalar_one()
            session.execute(
                text(
                    "INSERT INTO image_assets (tenant_id, draft_id, version_id, media_url, "
                    "object_key, content_type, width, height, aspect_ratio, model_id, provider, "
                    "params, media_type, position) VALUES (:t, :d, :v, :k, :k, 'video/mp4', "
                    "1080, 1920, '9:16', 'seedance-2-5', 'byteplus', CAST(:p AS jsonb), "
                    "'video', 0)"
                ),
                {"t": tenant, "d": child, "v": version, "k": key, "p": json.dumps(params)},
            )
            session.execute(
                text(
                    "UPDATE content_drafts SET status='generated', active_version_id=:v WHERE id=:d"
                ),
                {"v": version, "d": child},
            )
            # the part's own generation is what the vendor boundary just stood in for
            session.execute(
                text(
                    "UPDATE creative_pipeline_runs SET prepared_version=dirty_version "
                    "WHERE draft_id=:d"
                ),
                {"d": child},
            )
            session.execute(
                text("UPDATE creative_jobs SET status='succeeded' WHERE draft_id=:d"),
                {"d": child},
            )
            mark_parent_dirty(session, child)
    reading("d-join-ready", f"{len(files)} parts of {seconds}s kept in R2; parent {parent}")
    began = time.perf_counter()
    with PhasePeak("d-join") as peak:
        preparation()  # the real `join` phase
    took = time.perf_counter() - began
    own = peak.snapshot()
    with tenant_session(tenant) as session:
        row = session.execute(
            text(
                "SELECT object_key, params FROM image_assets "
                "WHERE draft_id=:d AND params->'draft'->>'finish'='join'"
            ),
            {"d": parent},
        ).first()
    if row is None or row.params["draft"]["status"] != "join_preview":
        print(
            "MEASURE-JOIN-FAILED "
            + json.dumps(
                {
                    **own,
                    "seconds": round(took, 1),
                    "why": "the join phase saved no joined preview: see the "
                    "creative.pipeline.* line above (preparation_failed / lease_lost)",
                }
            ),
            flush=True,
        )
        raise SystemExit(1)
    joined = row.params["join"]
    reading(
        "d-join",
        f"real PipelinePreparation join phase: {len(files)}x{seconds}s 1080p parts -> "
        f"{size[0]}x{size[1]}, frames={joined['frames']}, {took:.1f}s; own peak: "
        f"cgroup {own['phase_cgroup_peak_mib']} MiB, rss {own['phase_rss_peak_mib']} MiB",
    )
    print("MEASURE-JOIN " + json.dumps({**own, "seconds": round(took, 1)}), flush=True)
    return row


def fresh_service():
    """`--only-join`: the worker as it starts — the production service wired, the same
    synthetic copy/image boundary, one idle preparation — and nothing else before the
    join."""
    from qualify_api.creative.composition import production_content_service
    from qualify_api.creative.pipeline import PipelineStore
    from qualify_api.creative.worker.pipeline import PipelinePreparation

    service = production_content_service()
    service._router.router._providers = {name: Provider(name) for name in ("anthropic", "seedream")}
    tenant, _, _ = seed()
    PipelinePreparation(service, PipelineStore(), (tenant,))()
    reading("a-idle", "fresh worker process: production service wired; nothing before the join")
    return service, tenant


def _brand_and_user(tenant):
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import text

    with tenant_session(tenant) as session:
        brand = session.scalar(text("SELECT id FROM brands LIMIT 1"))
        user = session.scalar(text("SELECT id FROM users LIMIT 1"))
    return brand, user


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--download-mib", type=int, default=200)
    parser.add_argument("--join-parts", type=int, default=6)
    parser.add_argument("--join-folder", default="/parts")
    parser.add_argument("--join-size", default="1080x1920")
    parser.add_argument(
        "--no-join-logo",
        action="store_true",
        help="join without the synthetic brand logo (no overlay stage)",
    )
    parser.add_argument(
        "--only-join",
        action="store_true",
        help="a fresh worker process: the production service and the join phase only",
    )
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
    if args.only_join:
        service, tenant = fresh_service()
    else:
        service, tenant, draft = prepare()
        downloads(args.download_mib, service, tenant, draft)
    if args.join_parts > 0:
        width, height = (int(side) for side in args.join_size.split("x"))
        brand, user = _brand_and_user(tenant)
        join_phase(
            service,
            tenant,
            brand,
            user,
            args.join_folder,
            (width, height),
            logo=not args.no_join_logo,
        )
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
