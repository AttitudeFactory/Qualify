"""Measure the real connection purge scheduler and resumable R2 retry under cgroup limits.

Run only through connection-purge-worker-memory.sh against its disposable no-egress DB.
Seed mode uses app/admin doors only to create synthetic fixtures; the measured process has
only the dedicated connection-purge DSN and fake local R2 endpoint.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

CGROUP = Path("/sys/fs/cgroup")
HEARTBEAT = Path("/tmp/qualify-connection-purge.json")


def reading(phase: str, note: str = "") -> None:
    gc.collect()
    status = Path("/proc/self/status").read_text()
    rss_kib = next(
        (int(line.split()[1]) for line in status.splitlines() if line.startswith("VmRSS:")), -1
    )
    try:
        current = int((CGROUP / "memory.current").read_text()) / 1048576
        peak = int((CGROUP / "memory.peak").read_text()) / 1048576
        cap = (CGROUP / "memory.max").read_text().strip()
        limit = None if cap == "max" else int(cap) / 1048576
    except (OSError, ValueError):
        current = peak = limit = None
    print(
        "MEASURE "
        + json.dumps(
            {
                "phase": phase,
                "rss_mib": round(rss_kib / 1024, 1),
                "cgroup_current_mib": round(current, 1) if current is not None else None,
                "cgroup_peak_mib": round(peak, 1) if peak is not None else None,
                "limit_mib": round(limit, 1) if limit is not None else None,
                "note": note,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def seed() -> tuple[UUID, UUID]:
    from qualify_api.connections.models import PlatformApp, SocialConnection
    from qualify_api.connections.purge import request_connection_purge
    from qualify_api.tenancy.models import Tenant, User
    from qualify_shared.db.admin import admin_session
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import text

    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name="Synthetic purge memory",
                country="CO",
                timezone="UTC",
                currency="COP",
            )
        )
        session.flush()
        user = User(
            tenant_id=tenant_id,
            email=f"{uuid4()}@example.invalid",
            display_name="Synthetic measure",
        )
        app = PlatformApp(app_id=f"measure-{uuid4()}", secret_ref="synthetic", api_version="v21.0")
        session.add_all((user, app))
        session.flush()
        user_id, app_id = user.id, app.id

    with tenant_session(tenant_id) as session:
        connection = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"synthetic-{uuid4()}",
            external_username="synthetic_measure",
            linked_page_id="synthetic-page",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=1,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        connection_id = connection.id
        object_key = f"t/{tenant_id}/inbox/thumbs/{connection_id}/synthetic.jpg"
        session.execute(
            text(
                """INSERT INTO oauth_credentials
                (connection_id,tenant_id,version,token_type,ciphertext,key_id,issued_at)
                VALUES (:cid,:tid,1,'page',:ciphertext,'synthetic',now())"""
            ),
            {"cid": connection_id, "tid": tenant_id, "ciphertext": b"synthetic-encrypted-token"},
        )
        session.execute(
            text(
                """INSERT INTO monitored_media
                (tenant_id,connection_id,external_media_id,is_monitored,thumbnail_key,
                 thumbnail_content_type,thumbnail_source,thumbnail_stored_at)
                VALUES (:tid,:cid,'synthetic-media',true,:key,'image/jpeg',
                        'meta_thumbnail_url',now())"""
            ),
            {"tid": tenant_id, "cid": connection_id, "key": object_key},
        )

    request_connection_purge(tenant_id=tenant_id, connection_id=connection_id, reason="manual")
    # Keep the real request dormant for the first measured scheduler pass. The measured
    # worker role moves it due after that pass; it never receives app/admin credentials.
    with tenant_session(tenant_id) as session:
        session.execute(
            text("UPDATE connection_purge_requests SET due_at=:due WHERE connection_id=:cid"),
            {"due": datetime.now(UTC) + timedelta(hours=1), "cid": connection_id},
        )
    print(f"{tenant_id} {connection_id}")
    return tenant_id, connection_id


def fake_r2() -> tuple[ThreadingHTTPServer, dict[str, object]]:
    state: dict[str, object] = {"keys": set(), "delete_attempts": 0, "failed_once": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            prefix = parse_qs(urlparse(self.path).query).get("prefix", [""])[0]
            keys = sorted(key for key in state["keys"] if key.startswith(prefix))
            root = ET.Element("ListBucketResult", xmlns="http://s3.amazonaws.com/doc/2006-03-01/")
            ET.SubElement(root, "Name").text = "measure-bucket"
            ET.SubElement(root, "Prefix").text = prefix
            ET.SubElement(root, "KeyCount").text = str(len(keys))
            ET.SubElement(root, "MaxKeys").text = "1000"
            ET.SubElement(root, "IsTruncated").text = "false"
            for key in keys:
                item = ET.SubElement(root, "Contents")
                ET.SubElement(item, "Key").text = key
                ET.SubElement(item, "Size").text = "128"
                ET.SubElement(item, "StorageClass").text = "STANDARD"
            body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            request = ET.fromstring(self.rfile.read(length))
            keys = [
                node.text or ""
                for node in request.iter()
                if node.tag.endswith("}Key") or node.tag == "Key"
            ]
            state["delete_attempts"] = int(state["delete_attempts"]) + 1
            if not state["failed_once"]:
                state["failed_once"] = True
                result = ET.Element("DeleteResult", xmlns="http://s3.amazonaws.com/doc/2006-03-01/")
                for key in keys:
                    error = ET.SubElement(result, "Error")
                    ET.SubElement(error, "Key").text = key
                    ET.SubElement(error, "Code").text = "ServiceUnavailable"
                    ET.SubElement(error, "Message").text = "synthetic retry"
                body = ET.tostring(result, encoding="utf-8", xml_declaration=True)
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            for key in keys:
                stored_keys = state["keys"]
                assert isinstance(stored_keys, set)
                stored_keys.discard(key)
            body = b'<DeleteResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"></DeleteResult>'
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


def measure(tenant_id: UUID, connection_id: UUID) -> None:
    from qualify_api.connections.purge_worker import PurgeRunner, run_worker
    from qualify_shared.db.connection_purge import connection_purge_session
    from qualify_shared.objects.config import R2Settings
    from qualify_shared.objects.gate import ObjectGate
    from qualify_shared.objects.s3 import R2ObjectStore
    from sqlalchemy import text

    key = f"t/{tenant_id}/inbox/thumbs/{connection_id}/synthetic.jpg"
    server, state = fake_r2()
    keys = state["keys"]
    assert isinstance(keys, set)
    keys.add(key)
    os.environ["QUALIFY_R2_ENDPOINT_URL"] = f"http://127.0.0.1:{server.server_address[1]}"
    os.environ["QUALIFY_R2_ACCESS_KEY_ID"] = "synthetic"
    os.environ["QUALIFY_R2_SECRET_ACCESS_KEY"] = "synthetic"
    os.environ["QUALIFY_R2_BUCKET"] = "measure-bucket"
    objects = ObjectGate(R2ObjectStore(R2Settings.from_env()))
    runner = PurgeRunner(tenants=None, execute=True, limit=100, objects=objects)

    reading("a-idle", "real all-tenant discovery with no due work")
    code = run_worker(runner, once=True, heartbeat_path=HEARTBEAT)
    if code != 0:
        raise RuntimeError(f"idle worker pass failed with status {code}")
    with connection_purge_session(tenant_id) as session:
        session.execute(
            text("UPDATE connection_purge_requests SET due_at=:now WHERE connection_id=:cid"),
            {"now": datetime.now(UTC) - timedelta(seconds=1), "cid": connection_id},
        )

    # Compose's healthcheck is a separate, short-lived Python process importing this worker.
    # Overlap one real invocation with the next full purge pass under the same cgroup cap.
    healthcheck = subprocess.Popen(
        [sys.executable, "-m", "qualify_api.connections.purge_worker", "--healthcheck"]
    )
    code = run_worker(runner, once=True, heartbeat_path=HEARTBEAT)
    healthcheck_code = healthcheck.wait(timeout=15)
    # Exit 1 is also correct if the check races the expected retry/error heartbeat.
    if healthcheck_code not in {0, 1}:
        raise RuntimeError(f"concurrent worker healthcheck exited {healthcheck_code}")
    if code != 1 or not state["failed_once"]:
        raise RuntimeError("synthetic R2 failure did not exercise the worker retry path")
    reading("b-r2-retry", "real discovery, purge engine and first DeleteObjects failure")

    code = run_worker(runner, once=True, heartbeat_path=HEARTBEAT)
    if code != 0 or state["delete_attempts"] != 2 or keys:
        raise RuntimeError("real purge retry did not complete the synthetic deletion")
    reading("c-completed", "real retry, credential deletion and fake R2 object removal")
    server.shutdown()
    server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--tenant", type=UUID)
    parser.add_argument("--connection", type=UUID)
    args = parser.parse_args()
    if args.seed:
        seed()
        return
    if args.tenant is None or args.connection is None:
        parser.error("measured mode requires --tenant and --connection")
    reading("0-startup", "imports complete; dedicated worker DSN only")
    measure(args.tenant, args.connection)


if __name__ == "__main__":
    main()
