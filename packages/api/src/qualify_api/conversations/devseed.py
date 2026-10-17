"""Development seed for the Conversaciones inbox (QUA-226): fills Postgres with sample
private conversations through the SAME path real ones take — the in-memory channel
(`memory_source.py`) read by `ConversationSyncService` — so the UI, the outbox and the
sender can be validated on localhost without Meta and without sending anything.

    QUALIFY_CONVERSATIONS_DM_CHANNEL=memory \\
        python -m qualify_api.conversations.devseed --tenant <uuid> [--connection <uuid>]

(`just conversations-seed --tenant <uuid>`.)

What it writes: three threads on the tenant's active Instagram connection (the first one
by `connected_at`, or `--connection`), channel `dm`, dedup by `mid` — re-running it adds
nothing. One thread is pending with an open window, one was answered, one is older than
24 h (window closed). Nothing is invented about Meta: every row is stamped with
`SHAPE_VERSION_MEMORY`, and the sync state records access as `ok` for the in-memory
channel — never for Instagram.

Refuses to run unless the environment selects the in-memory channel: the seed must never
land next to real conversations by accident.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from qualify_api.conversations.contracts import RemoteConversation, RemoteMessage
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSource,
)

logger = logging.getLogger("qualify_api.conversations.devseed")

EXIT_NOT_MEMORY_MODE = 2
EXIT_NO_CONNECTION = 3


def _msg(
    mid: str,
    *,
    direction: str,
    text: str,
    at: datetime,
    counterpart: str,
    own: str,
    username: str | None = None,
) -> RemoteMessage:
    inbound = direction == "inbound"
    return RemoteMessage(
        external_message_id=mid,
        direction=direction,  # type: ignore[arg-type]
        text=text,
        posted_at=at,
        shape_version=SHAPE_VERSION_MEMORY,
        author_external_id=counterpart if inbound else own,
        author_username=username if inbound else None,
    )


def fill_sample_conversations(
    source: MemoryConversationSource, *, own_account_id: str, now: datetime | None = None
) -> None:
    """Three conversations, deterministic ids, relative to `now`."""
    now = now or datetime.now(UTC)
    alice = RemoteConversation(
        counterpart_external_id="seed-igsid-alice",
        external_conversation_id="t_seed_alice",
        counterpart_username="alice.compras",
        updated_at=now - timedelta(minutes=12),
    )
    source.add_message(
        alice,
        _msg(
            "mid.seed.alice.1",
            direction="inbound",
            text="Hola, ¿tienen la chaqueta verde en talla M?",
            at=now - timedelta(minutes=40),
            counterpart=alice.counterpart_external_id,
            own=own_account_id,
            username=alice.counterpart_username,
        ),
    )
    source.add_message(
        alice,
        _msg(
            "mid.seed.alice.2",
            direction="inbound",
            text="Y si la tienen, ¿hacen envíos a Medellín?",
            at=now - timedelta(minutes=12),
            counterpart=alice.counterpart_external_id,
            own=own_account_id,
            username=alice.counterpart_username,
        ),
    )
    bruno = RemoteConversation(
        counterpart_external_id="seed-igsid-bruno",
        external_conversation_id="t_seed_bruno",
        counterpart_username="bruno.fit",
        updated_at=now - timedelta(hours=3),
    )
    source.add_message(
        bruno,
        _msg(
            "mid.seed.bruno.1",
            direction="inbound",
            text="¿Cuánto vale el combo de proteína?",
            at=now - timedelta(hours=5),
            counterpart=bruno.counterpart_external_id,
            own=own_account_id,
            username=bruno.counterpart_username,
        ),
    )
    source.add_message(
        bruno,
        _msg(
            "mid.seed.bruno.2",
            direction="outbound",
            text="¡Hola Bruno! El combo está en 89.900 con envío incluido.",
            at=now - timedelta(hours=3),
            counterpart=bruno.counterpart_external_id,
            own=own_account_id,
        ),
    )
    carla = RemoteConversation(
        counterpart_external_id="seed-igsid-carla",
        external_conversation_id="t_seed_carla",
        counterpart_username="carla.viaja",
        updated_at=now - timedelta(days=2),
    )
    source.add_message(
        carla,
        _msg(
            "mid.seed.carla.1",
            direction="inbound",
            text="Vi su reel del fin de semana, ¿siguen con la promo?",
            at=now - timedelta(days=2),
            counterpart=carla.counterpart_external_id,
            own=own_account_id,
            username=carla.counterpart_username,
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.conversations.devseed",
        description="Seed sample private conversations through the in-memory channel "
        "(development only).",
    )
    parser.add_argument("--tenant", type=UUID, required=True, metavar="UUID")
    parser.add_argument(
        "--connection",
        type=UUID,
        default=None,
        metavar="UUID",
        help="The Instagram connection to seed on (default: the tenant's oldest active one).",
    )
    return parser


async def _run(tenant_id: UUID, connection_id: UUID | None) -> int:
    from qualify_api.conversations.composition import (  # noqa: PLC0415
        DM_CHANNEL_ENV,
        DM_CHANNEL_MEMORY,
        dm_channel_mode,
        instagram_connections_for,
        memory_pair,
        production_sync_service,
        source_connection_for,
    )

    if dm_channel_mode() != DM_CHANNEL_MEMORY:
        print(
            f"refusing: set {DM_CHANNEL_ENV}=memory to seed (the seed never lands next to "
            "real conversations)",
            file=sys.stderr,
        )
        return EXIT_NOT_MEMORY_MODE
    if connection_id is not None:
        connection = await asyncio.to_thread(source_connection_for, tenant_id, connection_id)
    else:
        connections = await asyncio.to_thread(instagram_connections_for, tenant_id)
        connection = connections[0] if connections else None
    if connection is None:
        print("refusing: the tenant has no active Instagram connection to seed on", file=sys.stderr)
        return EXIT_NO_CONNECTION

    source, _sender = memory_pair()
    fill_sample_conversations(source, own_account_id=connection.external_account_id)
    report = await production_sync_service().sync_connection(connection, source)
    print(
        f"seeded connection={connection.connection_id} conversations={report.conversations_seen} "
        f"threads_created={report.threads_created} messages_created={report.messages_created} "
        f"duplicates={report.duplicates} status={report.status}"
    )
    return 0


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_dotenv()
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_run(args.tenant, args.connection))


if __name__ == "__main__":
    raise SystemExit(main())
