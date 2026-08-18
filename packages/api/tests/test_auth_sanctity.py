"""Static guards for the auth seam (QUA-66), same discipline as the DB-door and
object-store sanctity tests: the properties are enforced by grep over the source tree,
not by convention.

1. The SECRET key env var is referenced only inside `qualify_api/auth/` — it is the
   admin credential that writes `app_metadata.tenant_id`, and its blast radius is the
   whole credential→tenant mapping.
2. The concrete Supabase provider module is imported only inside `qualify_api/auth/` —
   everything else (UI included) goes through the `qualify_api.auth` seam.
3. `admin_create_user` is called only from `qualify_api/auth/` — the UI registers
   through `register_business`, never by talking to the identity provider directly.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AUTH_DIR = _REPO_ROOT / "packages" / "api" / "src" / "qualify_api" / "auth"

# Every python source tree that ships to a runtime (tests excluded: they may stub).
_SOURCE_DIRS = (
    _REPO_ROOT / "packages" / "api" / "src",
    _REPO_ROOT / "packages" / "shared" / "src",
    _REPO_ROOT / "packages" / "scraper" / "src",
    _REPO_ROOT / "Qualify",
)


def _source_files_outside_auth() -> list[Path]:
    files: list[Path] = []
    for base in _SOURCE_DIRS:
        for path in base.rglob("*.py"):
            if _AUTH_DIR in path.parents:
                continue
            files.append(path)
    return files


def _offenders(pattern: str) -> list[str]:
    regex = re.compile(pattern)
    return [
        str(path.relative_to(_REPO_ROOT))
        for path in _source_files_outside_auth()
        if regex.search(path.read_text(encoding="utf-8"))
    ]


def test_secret_key_env_var_stays_inside_auth() -> None:
    assert _offenders(r"QUALIFY_SUPABASE_SECRET_KEY") == []


def test_supabase_provider_module_stays_inside_auth() -> None:
    assert _offenders(r"qualify_api\.auth\.supabase|from qualify_api\.auth import supabase") == []


def test_admin_create_user_called_only_inside_auth() -> None:
    assert _offenders(r"admin_create_user") == []
