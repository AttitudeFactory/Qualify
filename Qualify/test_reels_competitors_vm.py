"""RF-05 (m-25119465): the competitors panel's words and rules, without Reflex nor a
database (`reels_competitors_vm`)."""

from __future__ import annotations

from qualify_api.referentes import competitors as rivals
from qualify_api.referentes.reels import CompetitorAccount

from . import reels_competitors_vm as vm


def _accounts(n: int, weekly: int = 6, *, picked: bool = False) -> list[CompetitorAccount]:
    return [
        CompetitorAccount(
            network="instagram" if i % 2 == 0 else "tiktok",
            handle=f"rival{i}",
            picked=picked and i < weekly,
            weekly=i < weekly,
        )
        for i in range(n)
    ]


def test_the_owners_words_are_the_tickets() -> None:
    assert vm.PICKER_TITLE == "Tus competidores"  # option A, Deivid 2026-11-25
    assert vm.PICKER_BODY == (
        "Marca hasta 6: cada lunes te traemos sus reels nuevos. Para ver ya los de otro, "
        "pulsa «Ver sus reels ahora»."
    )
    assert vm.READ_NOW == "Ver sus reels ahora"
    assert vm.TOO_MANY == "Puedes elegir hasta 6 competidores."
    assert rivals.DAILY_LIMIT_TEXT == (
        "Hoy ya se alcanzó el límite de lecturas de tu negocio. Inténtalo mañana."
    )
    # plain Spanish: no English word, no slang, no credits or money
    for text in (vm.PICKER_BODY, vm.KEEP_ONE, vm.SAVE_FAILED, vm.WEEKLY_DETAIL):
        low = text.lower()
        assert not any(w in low for w in ("crédito", "usd", "$", "scrape", "click", "check"))


def test_a_row_per_competitor_says_whether_monday_reads_it() -> None:
    table = vm.rows(_accounts(8))
    assert [r["label"] for r in table] == [f"@rival{i}" for i in range(8)]
    assert [bool(r["weekly"]) for r in table] == [True] * 6 + [False] * 2
    assert table[0]["detail"] == "Instagram · Lo revisamos cada lunes"
    assert table[7]["detail"] == "TikTok"
    assert table[0]["key"] == "instagram:rival0"
    assert vm.picked_count(table) == "6 de 6 marcados"
    assert vm.button_label(table) == "Tus competidores: 6 de 6 los revisamos cada lunes"


def test_each_read_state_gets_its_words_and_tone() -> None:
    states = {
        "tiktok:rival7": vm.ReadState(rivals.STATE_READING, rivals.READING_TEXT),
        "instagram:rival6": vm.ReadState(rivals.STATE_LIMIT, rivals.DAILY_LIMIT_TEXT),
    }
    table = vm.rows(_accounts(8), states)
    by_key = {r["key"]: r for r in table}
    assert by_key["tiktok:rival7"]["tone"] == "info"
    assert by_key["tiktok:rival7"]["message"] == rivals.READING_TEXT
    assert by_key["instagram:rival6"]["tone"] == "warn"
    assert by_key["instagram:rival0"]["state"] == ""
    assert vm.reading(table)
    assert vm.STATE_TONES == {
        rivals.STATE_READING: "info",
        rivals.STATE_DONE: "ok",
        rivals.STATE_LIMIT: "warn",
        rivals.STATE_FAILED: "error",
    }


def test_ticking_a_seventh_is_refused_and_unticking_frees_a_place() -> None:
    table = vm.rows(_accounts(8))
    refused = vm.toggle(table, "instagram:rival6")
    assert refused is not None and refused.error == vm.TOO_MANY and refused.picks == ()
    freed = vm.toggle(table, "tiktok:rival1")
    assert freed is not None and freed.error == ""
    assert [h for _, h in freed.picks] == ["rival0", "rival2", "rival3", "rival4", "rival5"]


def test_ticking_keeps_the_lists_order_and_a_stale_key_does_nothing() -> None:
    table = vm.rows(_accounts(8, weekly=2, picked=True))
    added = vm.toggle(table, "tiktok:rival5")
    assert added is not None
    assert added.picks == (
        ("instagram", "rival0"),
        ("tiktok", "rival1"),
        ("tiktok", "rival5"),
    )
    assert vm.toggle(table, "instagram:nadie") is None


def test_the_last_one_cannot_be_unticked() -> None:
    table = vm.rows(_accounts(3, weekly=1, picked=True))
    kept = vm.toggle(table, "instagram:rival0")
    assert kept is not None and kept.error == vm.KEEP_ONE
