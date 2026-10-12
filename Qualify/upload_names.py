"""The name a dropped file is staged under (PR #86 review, PR #100 review): its last
path component only, without separators, control characters or leading dots, so a
crafted multipart filename can never write outside the tenant's folder. Reflex already
reduces `UploadFile.name` to a basename; nothing here relies on that. One helper for
every upload handler — the Brand Kit wizard, the generator's photos, the slide editor."""

from __future__ import annotations

import re
from pathlib import PurePath

#: What an uploaded file's name may keep in its staged key: letters (any script),
#: digits, spaces, dots, dashes and underscores.
_UNSAFE_NAME_CHARS = re.compile(r"[^\w .-]+")


def safe_upload_name(raw: str | None) -> str:
    """`raw` as the client sent it → a single safe file name (`archivo` when nothing
    usable is left)."""
    name = PurePath((raw or "").replace("\\", "/")).name
    name = _UNSAFE_NAME_CHARS.sub("_", name).lstrip(". ")[-120:]
    return name or "archivo"
