"""`PublicMediaSettings` (QUA-68). Same convention as `qualify_shared.objects.config`'s
`test_objects_config.py` — the interesting assertion is the ABSENCE of a dev fallback."""

from __future__ import annotations

import pytest

from qualify_api.config import PublicMediaConfigurationError, PublicMediaSettings

_BASE_URL = "https://qualify.example.attitudefactory.co"


def test_from_env_reads_the_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_PUBLIC_MEDIA_BASE_URL", _BASE_URL)

    settings = PublicMediaSettings.from_env()

    assert settings.base_url == _BASE_URL


def test_from_env_raises_when_the_variable_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """No dev fallback, by design — a forgotten override would embed `http://localhost:...`
    into an `image_url` Meta's fetcher will dutifully (and uselessly) try to reach."""
    monkeypatch.delenv("QUALIFY_PUBLIC_MEDIA_BASE_URL", raising=False)

    with pytest.raises(PublicMediaConfigurationError, match="QUALIFY_PUBLIC_MEDIA_BASE_URL"):
        PublicMediaSettings.from_env()


def test_from_env_treats_an_empty_string_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_PUBLIC_MEDIA_BASE_URL", "")

    with pytest.raises(PublicMediaConfigurationError):
        PublicMediaSettings.from_env()


def test_public_media_url_builds_the_expected_path() -> None:
    settings = PublicMediaSettings(base_url=_BASE_URL)

    assert settings.public_media_url("tok-123") == f"{_BASE_URL}/public/media/tok-123"


def test_public_media_url_strips_a_trailing_slash_on_the_base() -> None:
    settings = PublicMediaSettings(base_url=f"{_BASE_URL}/")

    assert settings.public_media_url("tok-123") == f"{_BASE_URL}/public/media/tok-123"


def test_settings_are_frozen() -> None:
    settings = PublicMediaSettings(base_url=_BASE_URL)
    with pytest.raises(Exception):
        settings.base_url = "https://other"  # type: ignore[misc]


def test_repr_is_safe_to_print() -> None:
    """Nothing secret lives here, but the repr should still name the field rather than
    dumping the dataclass's default repr — matches `R2Settings`'s own convention."""
    settings = PublicMediaSettings(base_url=_BASE_URL)
    assert repr(settings) == f"<PublicMediaSettings base_url={_BASE_URL!r}>"
