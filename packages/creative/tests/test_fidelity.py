"""MC-11 layer 1: every hard rule detects its violation, passes clean copy, and the
banned-word/claim matching is case- and accent-insensitive."""

from __future__ import annotations

from uuid import UUID

from qualify_creative.brand import check_hard_rules, check_route_allowed, fit_caption
from qualify_creative.brand.fidelity import (
    RULE_BANNED_WORD,
    RULE_CAPTION_LENGTH,
    RULE_EMOJI_POLICY,
    RULE_FORBIDDEN_CLAIM,
    RULE_HASHTAG_POLICY,
    RULE_ROUTE_BLOCKED,
)
from qualify_creative.enums import EmojiPolicy, ImageRoute
from qualify_creative.schemas import (
    BrandKit,
    CopyPayload,
    HashtagPolicy,
    ImagePolicy,
    LengthTargets,
    ToneAxes,
)

BRAND_ID = UUID("a3b1c2d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")


def make_kit(**overrides: object) -> BrandKit:
    base: dict[str, object] = {
        "brand_id": BRAND_ID,
        "positioning": "Cakes that taste like your grandmother's kitchen",
        "audience": "Young families in Bogota ordering for celebrations",
        "tone_axes": ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        "banned_words": ("barato", "gratis"),
        "forbidden_claims": ("el mejor de la ciudad",),
        "hashtag_policy": HashtagPolicy(minimum=1, maximum=5, always=("bianki",), never=("ad",)),
        "length_targets": LengthTargets(caption_min_chars=20, caption_max_chars=200),
        "emoji_policy": EmojiPolicy.SPARSE,
    }
    base.update(overrides)
    return BrandKit(**base)  # type: ignore[arg-type]


def make_copy(**overrides: object) -> CopyPayload:
    base: dict[str, object] = {
        "hook": "Nueva torta de chocolate",
        "caption": (
            "Salio del horno nuestra torta de chocolate, hecha con cacao de origen y mucho carino."
        ),
        "hashtags": ("bianki", "reposteria"),
        "cta": "Escribenos al DM para reservar la tuya.",
    }
    base.update(overrides)
    return CopyPayload(**base)  # type: ignore[arg-type]


def rules_of(failures: tuple[object, ...]) -> list[str]:
    return [failure.rule for failure in failures]  # type: ignore[attr-defined]


def test_clean_copy_passes_every_rule() -> None:
    assert check_hard_rules(make_copy(), make_kit()) == ()


# --- banned words -------------------------------------------------------------------


def test_banned_word_detected_case_insensitively() -> None:
    copy = make_copy(caption="Aprovecha: hoy todo esta Barato en nuestra tienda online.")
    failures = check_hard_rules(copy, make_kit())
    assert RULE_BANNED_WORD in rules_of(failures)
    assert any("barato" in failure.detail for failure in failures)


def test_banned_word_detected_accent_insensitively() -> None:
    # The kit bans the unaccented form; the copy uses the accented one.
    copy = make_copy(caption="Pide hoy tu domicilio grátis en toda la ciudad de Bogota.")
    assert RULE_BANNED_WORD in rules_of(check_hard_rules(copy, make_kit()))
    # And the reverse: an accented ban catches the unaccented spelling.
    kit = make_kit(banned_words=("grátis",))
    copy = make_copy(caption="Pide hoy tu domicilio gratis en toda la ciudad de Bogota.")
    assert RULE_BANNED_WORD in rules_of(check_hard_rules(copy, kit))


def test_banned_word_respects_word_boundaries() -> None:
    # "abaratado" contains "barato"-adjacent letters but is not the banned word.
    copy = make_copy(caption="Hemos abaratado nuestros costos sin tocar la calidad de nada.")
    assert check_hard_rules(copy, make_kit()) == ()


def test_banned_word_found_in_ads_slots_too() -> None:
    copy = make_copy(ads_primary_text="El postre mas barato que probaras esta semana.")
    assert RULE_BANNED_WORD in rules_of(check_hard_rules(copy, make_kit()))


# --- forbidden claims ---------------------------------------------------------------


def test_forbidden_claim_detected_as_substring_across_case_and_accents() -> None:
    copy = make_copy(
        caption="Nos dicen que somos El Mejor de la Ciudad y hoy queremos celebrarlo contigo."
    )
    failures = check_hard_rules(copy, make_kit())
    assert RULE_FORBIDDEN_CLAIM in rules_of(failures)


def test_absent_claim_passes() -> None:
    copy = make_copy(caption="Nuestra torta favorita vuelve al menu esta semana, por fin.")
    assert RULE_FORBIDDEN_CLAIM not in rules_of(check_hard_rules(copy, make_kit()))


# --- caption length -----------------------------------------------------------------


def test_caption_below_minimum_fails() -> None:
    failures = check_hard_rules(make_copy(caption="Muy corta."), make_kit())
    assert RULE_CAPTION_LENGTH in rules_of(failures)


def test_caption_above_maximum_fails() -> None:
    failures = check_hard_rules(make_copy(caption="x" * 201), make_kit())
    assert RULE_CAPTION_LENGTH in rules_of(failures)


def test_caption_within_targets_passes() -> None:
    failures = check_hard_rules(make_copy(caption="x" * 200), make_kit())
    assert RULE_CAPTION_LENGTH not in rules_of(failures)


# --- emoji policy -------------------------------------------------------------------


def test_emoji_policy_none_rejects_a_single_emoji() -> None:
    kit = make_kit(emoji_policy=EmojiPolicy.NONE)
    copy = make_copy(cta="Escribenos al DM para reservar la tuya 🎂")
    assert RULE_EMOJI_POLICY in rules_of(check_hard_rules(copy, kit))


def test_emoji_policy_none_passes_plain_text() -> None:
    kit = make_kit(emoji_policy=EmojiPolicy.NONE)
    assert RULE_EMOJI_POLICY not in rules_of(check_hard_rules(make_copy(), kit))


def test_emoji_policy_sparse_rejects_more_than_three() -> None:
    copy = make_copy(cta="Reserva ya 🎂🍰☕✨")
    assert RULE_EMOJI_POLICY in rules_of(check_hard_rules(copy, make_kit()))


def test_emoji_policy_sparse_allows_up_to_three() -> None:
    copy = make_copy(cta="Reserva ya 🎂🍰☕")
    assert RULE_EMOJI_POLICY not in rules_of(check_hard_rules(copy, make_kit()))


def test_emoji_policy_free_never_fails_on_emoji() -> None:
    kit = make_kit(emoji_policy=EmojiPolicy.FREE)
    copy = make_copy(cta="Reserva ya 🎂🍰☕✨🎉🎈")
    assert RULE_EMOJI_POLICY not in rules_of(check_hard_rules(copy, kit))


# --- hashtag policy -----------------------------------------------------------------


def test_hashtags_below_minimum_fail() -> None:
    failures = check_hard_rules(make_copy(hashtags=()), make_kit())
    assert RULE_HASHTAG_POLICY in rules_of(failures)


def test_hashtags_above_maximum_fail() -> None:
    tags = ("bianki", "uno", "dos", "tres", "cuatro", "cinco")
    failures = check_hard_rules(make_copy(hashtags=tags), make_kit())
    assert RULE_HASHTAG_POLICY in rules_of(failures)


def test_hashtag_from_never_list_fails_even_with_case_and_hash_prefix() -> None:
    failures = check_hard_rules(make_copy(hashtags=("bianki", "#Ad")), make_kit())
    assert RULE_HASHTAG_POLICY in rules_of(failures)


def test_missing_always_hashtag_fails() -> None:
    failures = check_hard_rules(make_copy(hashtags=("reposteria",)), make_kit())
    assert RULE_HASHTAG_POLICY in rules_of(failures)
    assert any("bianki" in failure.detail for failure in failures)


def test_compliant_hashtags_pass() -> None:
    failures = check_hard_rules(make_copy(hashtags=("Bianki", "reposteria")), make_kit())
    assert RULE_HASHTAG_POLICY not in rules_of(failures)


# --- image route policy -------------------------------------------------------------


def test_blocked_route_returns_failure_with_the_policy_reason() -> None:
    policy = ImagePolicy(
        allowed_routes=frozenset({ImageRoute.TEMPLATE_ONLY, ImageRoute.FROM_UPLOAD}),
        blocked_reason={ImageRoute.GENERATE: "Los productos de esta marca nunca se generan."},
    )
    failure = check_route_allowed(route=ImageRoute.GENERATE, policy=policy)
    assert failure is not None
    assert failure.rule == RULE_ROUTE_BLOCKED
    assert failure.detail == "Los productos de esta marca nunca se generan."


def test_blocked_route_without_explicit_reason_uses_the_default() -> None:
    failure = check_route_allowed(route=ImageRoute.GENERATE, policy=ImagePolicy())
    assert failure is not None
    assert failure.detail == "No habilitada para esta marca."


def test_allowed_route_returns_none() -> None:
    assert check_route_allowed(route=ImageRoute.FROM_UPLOAD, policy=ImagePolicy()) is None


# --- caption fit (2026-10-22: 601 against 600 threw a whole clip away) --------------


def _sentences(n: int) -> str:
    return " ".join(f"Frase numero {i} de la torta de chocolate." for i in range(1, n + 1))


def test_a_caption_within_the_maximum_is_returned_untouched() -> None:
    copy = make_copy()
    fitted, note = fit_caption(copy, make_kit())
    assert fitted is copy and note is None


def test_a_caption_one_character_over_is_cut_at_the_last_sentence_that_fits() -> None:
    # The measured case: one character past the cap. The last whole sentence goes —
    # its end sits within the last fifth of the maximum.
    caption = _sentences(4) + " Y una frase final corta aqui."
    limit = len(caption) - 1
    assert len(_sentences(4)) >= limit * 0.8
    kit = make_kit(length_targets=LengthTargets(caption_min_chars=20, caption_max_chars=limit))
    copy = make_copy(caption=caption)
    fitted, note = fit_caption(copy, kit)
    assert fitted.caption == _sentences(4)
    assert fitted.hook == copy.hook and fitted.cta == copy.cta and fitted.hashtags == copy.hashtags
    assert note == (
        f"caption trimmed from {len(caption)} to {len(_sentences(4))} characters to fit the"
        f" brand maximum of {limit}"
    )
    assert check_hard_rules(fitted, kit) == ()


def test_a_sentence_end_far_below_the_maximum_is_not_taken() -> None:
    # Review 2026-10-23: 605 characters against 600 whose only sentence end is at 95
    # were cut to 95. Now the cut is at the last whole word within the maximum.
    head = "Primera frase de la torta de chocolate que sale hoy del horno con cacao de origen."
    head = head + " " * (95 - len(head) - 1) + "." if len(head) < 94 else head[:94] + "."
    words = " ".join(["palabra"] * 80)
    caption = (head + " " + words)[:605].rstrip()
    caption = caption + "x" * (605 - len(caption))
    assert len(caption) == 605 and caption.rfind(".", 0, 600) == 94
    kit = make_kit(length_targets=LengthTargets(caption_min_chars=50, caption_max_chars=600))
    fitted, note = fit_caption(make_copy(caption=caption), kit)
    assert note is not None
    assert 480 <= len(fitted.caption) <= 600
    assert fitted.caption.endswith("palabra")
    assert caption.startswith(fitted.caption)
    assert check_hard_rules(fitted, kit) == ()


def test_a_cut_at_the_maximum_keeps_a_last_word_that_ends_there() -> None:
    caption = "Una frase sin puntos que termina justo en el limite ya"
    limit = len("Una frase sin puntos que termina justo en el limite")
    kit = make_kit(length_targets=LengthTargets(caption_min_chars=20, caption_max_chars=limit))
    fitted, _ = fit_caption(make_copy(caption=caption), kit)
    assert fitted.caption == "Una frase sin puntos que termina justo en el limite"


def test_a_single_sentence_a_little_over_is_cut_at_a_word_boundary() -> None:
    caption = "Una sola frase larga sin puntos intermedios que se pasa un poquito del limite"
    limit = len(caption) - 1
    kit = make_kit(length_targets=LengthTargets(caption_min_chars=20, caption_max_chars=limit))
    fitted, note = fit_caption(make_copy(caption=caption), kit)
    assert fitted.caption == (
        "Una sola frase larga sin puntos intermedios que se pasa un poquito del"
    )
    assert note is not None and len(fitted.caption) <= limit
    assert check_hard_rules(fitted, kit) == ()


def test_a_caption_far_over_the_maximum_is_left_for_the_hard_rule() -> None:
    kit = make_kit(length_targets=LengthTargets(caption_min_chars=20, caption_max_chars=60))
    copy = make_copy(caption=_sentences(3))  # 125 chars, way past 60 × 1.10
    fitted, note = fit_caption(copy, kit)
    assert fitted is copy and note is None
    assert RULE_CAPTION_LENGTH in rules_of(check_hard_rules(copy, kit))


def test_the_fit_never_cuts_below_the_brand_minimum_on_a_sentence() -> None:
    # The only sentence end that fits sits below the minimum: the cut falls back to the
    # last word boundary, which keeps the caption above it.
    caption = "Corta. " + "palabra " * 10 + "fin de la frase que se pasa"
    limit = len(caption) - 1
    kit = make_kit(length_targets=LengthTargets(caption_min_chars=50, caption_max_chars=limit))
    fitted, _ = fit_caption(make_copy(caption=caption), kit)
    assert 50 <= len(fitted.caption) <= limit
    assert fitted.caption.startswith("Corta. palabra") and fitted.caption.endswith("que se")
