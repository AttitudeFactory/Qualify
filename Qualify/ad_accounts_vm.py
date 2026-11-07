"""Credential-free display models for a brand's advertising account (m-24828972)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .ad_health_vm import AccountHealthVM


@dataclass(frozen=True)
class AdAccountVM:
    id: str
    name: str
    reference: str
    currency: str
    timezone: str
    status_label: str
    status_tone: str
    selected: bool
    health: AccountHealthVM = field(default_factory=AccountHealthVM)


@dataclass(frozen=True)
class AdBrandVM:
    id: str
    name: str


@dataclass(frozen=True)
class AdAccountsVM:
    accounts: list[AdAccountVM] = field(default_factory=list)
    enabled: bool = False
    reason: str = ""
    selected_name: str = ""
    brand_id: str = ""
    brands: list[AdBrandVM] = field(default_factory=list)
    requires_reconnect: bool = False


def account_status(account_status: int | None) -> tuple[str, str]:
    """Meta account status, kept distinct from permission to create an advertisement."""
    return {
        1: ("Activa", "ok"),
        2: ("Inhabilitada", "error"),
    }.get(account_status, ("Estado por comprobar", "neutral"))


LOAD_FAILED = "No pudimos cargar tus cuentas publicitarias. Vuelve a intentarlo en un momento."
REFRESH_FAILED = "No pudimos comprobar tus cuentas con Meta. Vuelve a intentarlo en un momento."
SELECT_FAILED = "No pudimos guardar esa cuenta. Actualiza la lista y vuelve a elegirla."
BRAND_FAILED = "No pudimos guardar la marca. Recarga la página y vuelve a elegirla."
CONNECT_FAILED = "No pudimos iniciar la conexión para anuncios. Vuelve a intentarlo en un momento."
NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
NO_CHARGE_NOTE = "Conectar o elegir una cuenta no crea anuncios ni genera cobros."
