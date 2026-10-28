"""Connection erasure never widens tenant or connection object boundaries."""

from uuid import uuid4

import pytest

from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.keys import TenantPrefixViolation


class Store:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_keys(self, keys: list[str]) -> None:
        self.deleted.extend(keys)


def test_validate_entire_manifest_before_deleting_anything() -> None:
    tenant, connection, other = uuid4(), uuid4(), uuid4()
    store = Store()
    good = f"t/{tenant}/inbox/thumbs/{connection}/1"
    for bad in (
        f"t/{other}/inbox/thumbs/{connection}/1",
        f"t/{tenant}/media/{other}/1",
        f"t/{tenant}/generated/{connection}/1",
        f"t/{tenant}/inbox/thumbs/{connection}extra/1",
        f"t/{tenant}/fp/whatsapp/{connection}/1",
    ):
        with pytest.raises(TenantPrefixViolation):
            ObjectGate(store).delete_connection_objects(
                tenant, connection, "instagram", [good, bad]
            )
        assert store.deleted == []


def test_manifest_deletion_deduplicates_and_batches_without_listing_unrelated_objects() -> None:
    tenant, connection = uuid4(), uuid4()
    store = Store()
    keys = [f"t/{tenant}/fp/instagram/{connection}/{number}" for number in range(1001)]
    ObjectGate(store).delete_connection_objects(tenant, connection, "instagram", keys + keys)
    assert store.deleted == keys
