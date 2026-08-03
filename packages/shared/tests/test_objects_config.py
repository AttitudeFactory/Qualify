"""`R2Settings` (QUA-19). The interesting assertion is the ABSENCE of dev fallbacks."""

from __future__ import annotations

import pytest

from qualify_shared.objects.config import (
    R2_REGION_NAME,
    R2_SIGNATURE_VERSION,
    R2ConfigurationError,
    R2Settings,
)

_ENV = {
    "QUALIFY_R2_ENDPOINT_URL": "https://accountid.r2.cloudflarestorage.com",
    "QUALIFY_R2_ACCESS_KEY_ID": "access-key",
    "QUALIFY_R2_SECRET_ACCESS_KEY": "secret-key",
    "QUALIFY_R2_BUCKET": "qualify-media",
}


@pytest.fixture
def r2_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)


def test_from_env_reads_every_field(r2_env: None) -> None:
    settings = R2Settings.from_env()
    assert settings.endpoint_url == _ENV["QUALIFY_R2_ENDPOINT_URL"]
    assert settings.access_key_id == _ENV["QUALIFY_R2_ACCESS_KEY_ID"]
    assert settings.secret_access_key == _ENV["QUALIFY_R2_SECRET_ACCESS_KEY"]
    assert settings.bucket == _ENV["QUALIFY_R2_BUCKET"]


def test_r2_constants_match_the_provider(r2_env: None) -> None:
    """R2 requires SigV4 and the `auto` pseudo-region; neither is a deployment choice."""
    settings = R2Settings.from_env()
    assert settings.region_name == R2_REGION_NAME == "auto"
    assert settings.signature_version == R2_SIGNATURE_VERSION == "s3v4"


@pytest.mark.parametrize("missing", sorted(_ENV))
def test_from_env_raises_when_any_variable_is_absent(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """No dev fallback, by design. A default endpoint or bucket lets a forgotten override
    SUCCEED against the wrong bucket — indistinguishable from working until someone goes
    looking for a file that is not there."""
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing)
    with pytest.raises(R2ConfigurationError) as excinfo:
        R2Settings.from_env()
    assert missing in str(excinfo.value)


def test_from_env_treats_an_empty_string_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exported-but-empty variable is the shape a half-filled `.env` takes, and it must
    fail like a missing one rather than configure an empty bucket name."""
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("QUALIFY_R2_BUCKET", "")
    with pytest.raises(R2ConfigurationError):
        R2Settings.from_env()


def test_repr_does_not_leak_the_secret(r2_env: None) -> None:
    """A settings object routinely reaches a traceback, and a traceback reaches a log."""
    text = repr(R2Settings.from_env())
    assert _ENV["QUALIFY_R2_SECRET_ACCESS_KEY"] not in text
    assert _ENV["QUALIFY_R2_ACCESS_KEY_ID"] not in text
    assert "redacted" in text


def test_settings_are_frozen(r2_env: None) -> None:
    settings = R2Settings.from_env()
    with pytest.raises(Exception):
        settings.bucket = "other-bucket"  # type: ignore[misc]
