"""Write infra/langfuse/.env with fresh random secrets — once.

`just langfuse-init` runs this. It never overwrites an existing .env: the secrets in it
encrypt Langfuse's data (ENCRYPTION_KEY) and hash its API keys (SALT), so replacing them
on a running instance would lock it out of its own database. To start over, run
`just langfuse-reset` (drops the volumes) and delete the file by hand.

Standard library only, so it runs before any dependency is installed.
"""

from __future__ import annotations

import base64
import secrets
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE / ".env"
TEMPLATE = HERE / ".env.example"


def _base64_32() -> str:
    """`openssl rand -base64 32`, as Langfuse documents for NEXTAUTH_SECRET and SALT."""
    return base64.b64encode(secrets.token_bytes(32)).decode()


def _password() -> str:
    """Hex only: it goes inside a postgresql:// URL, where `@`, `/` or `:` would break it."""
    return secrets.token_hex(24)


#: Every value the template leaves empty, and how to make it.
GENERATORS = {
    "NEXTAUTH_SECRET": _base64_32,
    "SALT": _base64_32,
    # 256 bits as 64 hex characters (`openssl rand -hex 32`), as Langfuse requires
    "ENCRYPTION_KEY": lambda: secrets.token_hex(32),
    "POSTGRES_PASSWORD": _password,
    "CLICKHOUSE_PASSWORD": _password,
    "REDIS_AUTH": _password,
    "MINIO_ROOT_PASSWORD": _password,
    "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": lambda: f"pk-lf-{uuid.uuid4()}",
    "LANGFUSE_INIT_PROJECT_SECRET_KEY": lambda: f"sk-lf-{uuid.uuid4()}",
    "LANGFUSE_INIT_USER_PASSWORD": lambda: secrets.token_urlsafe(18),
}


def render(template: str) -> str:
    """The template with every generated key filled in; other lines kept as they are."""
    out: list[str] = []
    for line in template.splitlines():
        key, sep, value = line.partition("=")
        name = key.strip()
        if sep and name in GENERATORS and not value.strip():
            line = f"{name}={GENERATORS[name]()}"
        out.append(line)
    return "\n".join(out) + "\n"


def main() -> int:
    if TARGET.exists():
        print(f"{TARGET.name} ya existe: no se toca (sus secretos cifran los datos de Langfuse).")
        return 0
    TARGET.write_text(render(TEMPLATE.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Escrito {TARGET}: secretos nuevos, usuario y claves del proyecto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
