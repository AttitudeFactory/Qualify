"""`qualify_api.meegle.settings` — the engine is off until every variable is set, and the
secret stays inside the package (static guard, same discipline as `test_auth_sanctity`)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from qualify_api.meegle import (
    MeegleNames,
    MeegleNotConfigured,
    MeegleSettings,
    meegle_configured,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MEEGLE_DIR = _REPO_ROOT / "packages" / "api" / "src" / "qualify_api" / "meegle"
_SOURCE_DIRS = (
    _REPO_ROOT / "packages" / "api" / "src",
    _REPO_ROOT / "packages" / "shared" / "src",
    _REPO_ROOT / "packages" / "scraper" / "src",
    _REPO_ROOT / "packages" / "creative" / "src",
    _REPO_ROOT / "Qualify",
)

FULL_ENV = {
    "QUALIFY_MEEGLE_PLUGIN_ID": "MII_TEST",
    "QUALIFY_MEEGLE_PLUGIN_SECRET": "s3cret",
    "QUALIFY_MEEGLE_CALLBACK_TOKEN": "tok",
    "QUALIFY_MEEGLE_PROJECT_KEY": "proj-test",
    "QUALIFY_MEEGLE_WORK_ITEM_TYPE": "alta_cliente",
    "QUALIFY_MEEGLE_USER_KEY": "7697105028321938981",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*FULL_ENV, "QUALIFY_MEEGLE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


def _set_all(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in FULL_ENV.items():
        monkeypatch.setenv(name, value)


def test_unconfigured_is_loud_and_names_what_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert meegle_configured() is False
    with pytest.raises(MeegleNotConfigured) as exc:
        MeegleSettings.from_env()
    assert "QUALIFY_MEEGLE_PLUGIN_ID" in str(exc.value)
    assert "QUALIFY_MEEGLE_USER_KEY" in str(exc.value)
    # Partial configuration is still off: a forgotten variable never defaults.
    _set_all(monkeypatch)
    monkeypatch.setenv("QUALIFY_MEEGLE_CALLBACK_TOKEN", "   ")
    assert meegle_configured() is False
    with pytest.raises(MeegleNotConfigured) as exc:
        MeegleSettings.from_env()
    assert str(exc.value).endswith("QUALIFY_MEEGLE_CALLBACK_TOKEN not set")


def test_configured_reads_everything_with_the_default_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_all(monkeypatch)
    settings = MeegleSettings.from_env()
    assert meegle_configured() is True
    assert settings.base_url == "https://meegle.com"
    assert settings.plugin_id == "MII_TEST" and settings.plugin_secret == "s3cret"
    assert settings.work_item_type == "alta_cliente" and settings.user_key.endswith("981")
    monkeypatch.setenv("QUALIFY_MEEGLE_BASE_URL", "https://project.larksuite.com/")
    assert MeegleSettings.from_env().base_url == "https://project.larksuite.com"


def test_names_default_to_the_plan_and_accept_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    names = MeegleNames.from_env()
    assert names.email == "Correo" and names.status == "Estado Qualify"
    assert names.node_data == "Datos" and names.node_registered == "Registrada"
    assert names.instagram == "Cuenta de Instagram"
    monkeypatch.setenv("QUALIFY_MEEGLE_FIELD_EMAIL", "Email")
    monkeypatch.setenv("QUALIFY_MEEGLE_FIELD_INSTAGRAM", "Instagram")
    monkeypatch.setenv("QUALIFY_MEEGLE_NODE_DATA", "Data")
    overridden = MeegleNames.from_env()
    assert overridden.email == "Email" and overridden.node_data == "Data"
    assert overridden.instagram == "Instagram"
    assert overridden.status == "Estado Qualify"  # untouched ones keep the plan's label


# --------------------------------------------------------------------------------------
# Static guard: the plugin secret is read nowhere but inside `qualify_api/meegle/`.
# --------------------------------------------------------------------------------------


def _offenders(pattern: str) -> list[str]:
    regex = re.compile(pattern)
    found: list[str] = []
    for base in _SOURCE_DIRS:
        for path in base.rglob("*.py"):
            if _MEEGLE_DIR in path.parents:
                continue
            if regex.search(path.read_text(encoding="utf-8")):
                found.append(str(path.relative_to(_REPO_ROOT)))
    return found


def test_plugin_secret_env_var_stays_inside_meegle() -> None:
    assert _offenders(r"QUALIFY_MEEGLE_PLUGIN_SECRET") == []


def test_the_client_module_is_imported_only_inside_meegle_and_its_assembly() -> None:
    # Everything else reaches Meegle through the package's use-cases, never the raw client.
    assert (
        _offenders(r"from qualify_api\.meegle\.client import|qualify_api\.meegle\.client\.") == []
    )
