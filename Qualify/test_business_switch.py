"""The single-use business-switch pass (S4 m-24849191, ADR 43 §2.2, A7) and the pure
copy/helpers of the selector (S3 m-24849190)."""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from . import business_vm as vm
from .business_switch import (
    PASS_TTL_SECONDS,
    SwitchPassStore,
    pass_from_fragment,
    switch_script,
)

LOGIN = UUID("11111111-1111-4111-8111-111111111111")
POLETTE = UUID("22222222-2222-4222-8222-222222222222")
TOKEN = "eyJhbGciOi.supabase-access-token.sig"


class _FakeRedis:
    """`SET … EX` and `GETDEL`, the two commands the store uses."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int | None] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> bool:
        self.data[name] = value
        self.ttl[name] = ex
        return True

    def getdel(self, name: str) -> str | None:
        self.ttl.pop(name, None)
        return self.data.pop(name, None)


def _store() -> tuple[SwitchPassStore, _FakeRedis]:
    redis = _FakeRedis()
    return SwitchPassStore(redis), redis


def test_a_pass_opens_its_business_once() -> None:
    store, _ = _store()
    pass_value = store.issue(auth_user_id=LOGIN, tenant_id=POLETTE, access_token=TOKEN)
    target = store.redeem(pass_value)
    assert target is not None
    assert (target.auth_user_id, target.tenant_id, target.access_token) == (LOGIN, POLETTE, TOKEN)
    assert store.redeem(pass_value) is None  # used: GETDEL removed it


def test_the_pass_lives_sixty_seconds_and_redis_never_sees_it_or_the_token() -> None:
    store, redis = _store()
    pass_value = store.issue(auth_user_id=LOGIN, tenant_id=POLETTE, access_token=TOKEN)
    assert PASS_TTL_SECONDS == 60
    [(key, stored)] = redis.data.items()
    assert redis.ttl[key] == 60
    assert pass_value not in key and pass_value not in stored
    assert TOKEN not in stored  # encrypted with a key derived from the pass
    assert json.loads(stored)["tenant_id"] == str(POLETTE)


def test_passes_are_random_and_256_bits() -> None:
    store, _ = _store()
    passes = {
        store.issue(auth_user_id=LOGIN, tenant_id=POLETTE, access_token=TOKEN) for _ in range(20)
    }
    assert len(passes) == 20
    assert all(len(p) >= 43 for p in passes)  # token_urlsafe(32)


@pytest.mark.parametrize("bad", ["", "x", "a" * 200, "no-such-pass-at-all-0000000000000000000000"])
def test_an_unknown_or_malformed_pass_opens_nothing(bad: str) -> None:
    store, _ = _store()
    store.issue(auth_user_id=LOGIN, tenant_id=POLETTE, access_token=TOKEN)
    assert store.redeem(bad) is None


def test_a_tampered_entry_opens_nothing() -> None:
    store, redis = _store()
    pass_value = store.issue(auth_user_id=LOGIN, tenant_id=POLETTE, access_token=TOKEN)
    [key] = redis.data
    entry = json.loads(redis.data[key])
    entry["token"] = entry["token"][:-4] + "AAAA"
    redis.data[key] = json.dumps(entry)
    assert store.redeem(pass_value) is None


def test_an_expired_pass_opens_nothing() -> None:
    store, redis = _store()
    pass_value = store.issue(auth_user_id=LOGIN, tenant_id=POLETTE, access_token=TOKEN)
    redis.data.clear()  # what Redis does after EX seconds
    assert store.redeem(pass_value) is None


def test_the_browser_drops_its_reflex_token_and_loads_cambiar_with_the_pass_in_the_fragment() -> (
    None
):
    script = switch_script("abc_DEF-123")
    assert script.index('sessionStorage.removeItem("token")') < script.index("location.replace")
    assert '"/cambiar#pase=abc_DEF-123"' in script
    assert "?pase=" not in script  # never in the query: it would reach the server logs


def test_the_pass_is_read_back_from_the_fragment() -> None:
    assert pass_from_fragment("#pase=abc_DEF-123") == "abc_DEF-123"
    assert pass_from_fragment("pase=abc") == "abc"
    assert pass_from_fragment("") == ""
    assert pass_from_fragment("#otra=1") == ""


# -- the view model -----------------------------------------------------------------------


def test_the_exact_copy_of_the_epic() -> None:
    assert vm.CHOOSE_TITLE == "¿Con qué negocio quieres trabajar?"
    assert vm.CHOOSE_HELP == "Puedes cambiar de negocio cuando quieras desde la parte de arriba."
    assert vm.chip_label("Bianki") == "Estás en Bianki"
    assert vm.SWITCH_MENU_LABEL == "Cambiar de negocio"
    assert vm.opening_label("Polette") == "Abriendo Polette…"
    assert vm.CHOOSE_TAB_TITLE == "Elige tu negocio · Qualify"


@pytest.mark.parametrize(
    ("raw", "count", "expected"),
    [
        ("0", 2, 0),
        ("1", 2, 1),
        (1, 2, 1),
        ("2", 2, None),
        ("-1", 2, None),
        (-1, 2, None),
        (True, 2, None),
        ("1.0", 2, None),
        (str(POLETTE), 2, None),  # a tenant id typed by hand is not a position
        ([0], 2, None),
        (None, 2, None),
        ("0", 0, None),
    ],
)
def test_only_a_listed_position_is_accepted(raw: object, count: int, expected: int | None) -> None:
    assert vm.parse_choice_index(raw, count) == expected


def test_the_menu_offers_every_other_business_with_its_position() -> None:
    names = ["Bianki", "Korner", "Polette"]
    assert vm.switch_choices(names, 0) == [
        {"index": "1", "name": "Korner"},
        {"index": "2", "name": "Polette"},
    ]
    assert vm.switch_choices(names, -1)[0] == {"index": "0", "name": "Bianki"}
