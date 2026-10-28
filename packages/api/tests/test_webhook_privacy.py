"""Offline guards for consent-bound webhook processing and malformed intake."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from qualify_api.mentions.resolve import ResolutionOutcome
from qualify_api.webhooks.ownership import event_owners, resolve_owned_external_account
from qualify_api.webhooks.receiver import record_delivery


@pytest.mark.parametrize("owners,count", [((), 0), (((uuid4(), uuid4()),), 1)])
def test_frozen_resolution_never_queries_current_account_owner(monkeypatch, owners, count) -> None:
    def forbidden(**kwargs):
        raise AssertionError("a delayed webhook must not resolve a new account owner")

    monkeypatch.setattr("qualify_api.webhooks.ownership.resolve_external_account", forbidden)
    token = event_owners.set(owners)
    try:
        result = asyncio.run(
            asyncio.to_thread(
                resolve_owned_external_account, platform="instagram", external_account_id="account"
            )
        )
    finally:
        event_owners.reset(token)
    assert result.outcome == (ResolutionOutcome.RESOLVED if count else ResolutionOutcome.ORPHAN)
    if count:
        assert (result.tenant_id, result.connection_id) == owners[0]


def test_shared_snapshot_remains_ambiguous() -> None:
    token = event_owners.set(((uuid4(), uuid4()), (uuid4(), uuid4())))
    try:
        assert (
            resolve_owned_external_account(
                platform="instagram", external_account_id="account"
            ).outcome
            == ResolutionOutcome.AMBIGUOUS
        )
    finally:
        event_owners.reset(token)


@pytest.mark.parametrize("body", [b"not-json", b'{"object":"instagram","entry":"bad"}'])
def test_unclassifiable_meta_raw_is_discarded_without_opening_a_database(monkeypatch, body) -> None:
    def forbidden():
        raise AssertionError("unclassifiable raw must never reach storage")

    monkeypatch.setattr("qualify_api.webhooks.receiver.webhook_session", forbidden)
    result = record_delivery(body=body, signature_header="verified-before-receiver")
    assert result.parse_status == "discarded" and result.changes_new == 0
