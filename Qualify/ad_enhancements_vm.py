"""Display-only permissions for changes Meta may make to a brand's advertisements."""

from __future__ import annotations

from dataclasses import dataclass, field

FEATURES = ("image_touchups", "text_optimizations", "enhance_cta", "image_animation")
FEATURE_LABELS = {
    "image_touchups": "Retocar la imagen",
    "text_optimizations": "Variar el texto",
    "enhance_cta": "Cambiar el botón",
    "image_animation": "Animar la imagen",
}
FEATURE_DESCRIPTIONS = {
    "image_touchups": "Permitir que Meta haga retoques a la imagen del anuncio.",
    "text_optimizations": "Permitir que Meta use variaciones del texto del anuncio.",
    "enhance_cta": "Permitir que Meta modifique el botón del anuncio.",
    "image_animation": "Permitir que Meta convierta la imagen en una animación.",
}
AVAILABILITY_NOTICE = (
    "Estos permisos no activan anuncios. Todavía falta comprobar qué cambios admite Meta "
    "en las publicaciones ya publicadas. Si permites algún cambio, su uso quedará bloqueado "
    "hasta comprobar la compatibilidad y revisar una vista previa válida."
)
READ_FAILED = "No pudimos consultar estos permisos. Vuelve a intentarlo."
SAVE_FAILED = (
    "No pudimos guardar los permisos. Vuelve a consultarlos antes de intentar guardar otra vez."
)
SESSION_REQUIRED = "Inicia sesión y espera a que cargue tu marca para revisar sus permisos."


def all_off() -> dict[str, bool]:
    return dict.fromkeys(FEATURES, False)


@dataclass(frozen=True)
class BrandEnhancementsVM:
    brand_id: str = ""
    version: int = 0
    values: dict[str, bool] = field(default_factory=all_off)
    loaded: bool = False


def permission_summary(policy: BrandEnhancementsVM) -> str:
    if not policy.loaded:
        return "Permisos pendientes de consultar"
    enabled = [FEATURE_LABELS[key].lower() for key in FEATURES if policy.values.get(key) is True]
    return (
        "Permitidos: " + ", ".join(enabled)
        if enabled
        else "Ninguno de estos cuatro cambios permitido"
    )
