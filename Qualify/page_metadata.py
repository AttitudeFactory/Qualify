"""Static, non-indexable page metadata for the operational app.

The marketing site lives at qualify.la. App screens, account recovery, OAuth returns
and business data must not become search results. Metadata describes the screen only:
never a business, user, draft identifier, recovery token or query string.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import reflex as rx

# The public sharing/canonical host is independent of Reflex's technical deploy
# URL, which can still name a legacy endpoint used by API/auth/OAuth configuration.
# Updating metadata must not change those runtime endpoints.
APP_PUBLIC_ORIGIN = "https://app.qualify.la"
SOCIAL_IMAGE_URL = "https://qualify.la/og/es.png"
DEFAULT_DESCRIPTION = (
    "Gestiona las publicaciones, las conversaciones y las cuentas de tu negocio en Qualify."
)

PAGE_DESCRIPTIONS: dict[str, str] = {
    "/": "Revisa las tareas pendientes y los próximos pasos de tu negocio en Qualify.",
    "/login": "Entra a Qualify para gestionar el contenido y las conversaciones de tu negocio.",
    "/registro": "Registra tu negocio en Qualify con tu invitación y crea tu cuenta de acceso.",
    "/signup": "Registra tu negocio en Qualify con tu invitación y crea tu cuenta de acceso.",
    "/forgot": "Solicita un enlace para recuperar la contraseña de tu cuenta de Qualify.",
    "/reset": "Elige una nueva contraseña para volver a entrar a tu cuenta de Qualify.",
    "/elegir-negocio": "Elige el negocio con el que quieres trabajar en Qualify.",
    "/cambiar": "Cambia al negocio que quieres gestionar con tu cuenta de Qualify.",
    "/brand/start": "Empieza a preparar la identidad de tu negocio en Qualify.",
    "/brand": "Prepara la identidad, los colores y el tono de tu negocio en Qualify.",
    "/brand/kit": "Actualiza la identidad, los colores y el tono de tu negocio en Qualify.",
    "/brand/manual": "Completa la información y la identidad de tu negocio paso a paso en Qualify.",
    "/brand/connect": "Usa el perfil de tu negocio para preparar su identidad en Qualify.",
    "/brand/connect/setup": "Prepara la cuenta social de tu negocio para continuar en Qualify.",
    "/responder": "Revisa los comentarios, las conversaciones y las consultas de tu negocio.",
    "/inbox": "Revisa los comentarios y las respuestas pendientes de tu negocio en Qualify.",
    "/conversations": "Revisa las conversaciones y las consultas de tu negocio en Qualify.",
    "/leads": "Revisa las consultas de personas interesadas en comprar a tu negocio.",
    "/whatsapp": "Gestiona los números y las conversaciones de WhatsApp de tu negocio en Qualify.",
    "/catalog": "Organiza los productos, las fotos y los videos de tu negocio en Qualify.",
    "/create": "Prepara una publicación con la identidad y los productos de tu negocio en Qualify.",
    "/drafts": "Revisa las publicaciones de tu negocio pendientes de aprobación en Qualify.",
    "/drafts/[draft_id]": "Revisa una publicación de tu negocio antes de aprobarla en Qualify.",
    "/drafts/[draft_id]/promote": "Prepara un anuncio para una publicación de tu negocio.",
    "/planner": "Organiza las publicaciones de tu negocio y su programación semanal en Qualify.",
    "/publish": "Publica el contenido aprobado de tu negocio en sus cuentas conectadas.",
    "/stories": "Prepara las historias de tu negocio desde la pantalla de publicación de Qualify.",
    "/promotions": "Revisa los anuncios de tu negocio y sus resultados en Qualify.",
    "/promotions/[promotion_id]": "Consulta el estado y los resultados de un anuncio en Qualify.",
    "/resultados": "Consulta los resultados de las redes, WhatsApp y la página web de tu negocio.",
    "/creadores": "Busca creadores para evaluar colaboraciones con tu negocio en Qualify.",
    "/creadores/comparar": "Compara creadores para evaluar una colaboración con tu negocio.",
    "/creadores/[creator_id]": "Revisa un creador para evaluar una colaboración con tu negocio.",
    "/signals": "Consulta las oportunidades y las próximas funciones para tu negocio en Qualify.",
    "/connections": "Conecta las redes de tu negocio y revisa cuáles están listas en Qualify.",
    "/settings": "Revisa los datos de tu negocio y los ajustes de tu cuenta de Qualify.",
    "/canva/callback": "Completa la conexión de Canva para preparar contenido en Qualify.",
    "/canva/return": "Vuelve a Qualify para continuar con el contenido que preparaste en Canva.",
    "/design": "Consulta la guía interna de componentes y estilos de Qualify.",
    "/design/pasos": "Consulta la muestra interna de los pasos de los formularios de Qualify.",
    "/vitrina": "Vuelve al inicio de Qualify para continuar con las tareas de tu negocio.",
    "/404": "No encontramos esta página de Qualify. Vuelve al inicio para continuar.",
}

_ALIASES = {
    "/signup": "/registro",
    "/inbox": "/responder",
    "/conversations": "/responder",
    "/leads": "/responder",
    "/stories": "/publish",
    "/vitrina": "/",
}


def page_metadata(route: str, title: str) -> dict[str, Any]:
    """Build public head tags from a registration route, never from live router state."""
    path = "/" + urlsplit(route).path.strip("/")
    if path == "/index":
        path = "/"
    description = PAGE_DESCRIPTIONS.get(path, DEFAULT_DESCRIPTION)
    dynamic = "[" in path
    public_path = (path.split("[", 1)[0].rstrip("/") or "/") if dynamic else path
    public_path = _ALIASES.get(public_path, public_path)
    url = APP_PUBLIC_ORIGIN + public_path
    tags: list[Mapping[str, Any] | rx.Component] = [
        {"name": "robots", "content": "noindex, follow"},
        {"property": "og:title", "content": title},
        {"property": "og:description", "content": description},
        {"property": "og:type", "content": "website"},
        {"property": "og:site_name", "content": "Qualify"},
        {"property": "og:locale", "content": "es_CO"},
        {"property": "og:url", "content": url},
        {"property": "og:image:width", "content": "1200"},
        {"property": "og:image:height", "content": "630"},
        {
            "property": "og:image:alt",
            "content": "Qualify: marketing con inteligencia artificial para tu negocio",
        },
        {"name": "twitter:card", "content": "summary_large_image"},
        {"name": "twitter:title", "content": title},
        {"name": "twitter:description", "content": description},
        {"name": "twitter:image", "content": SOCIAL_IMAGE_URL},
        {
            "name": "twitter:image:alt",
            "content": "Qualify: marketing con inteligencia artificial para tu negocio",
        },
    ]
    # A template is not a real canonical URL. Do not emit identifiers or parameters
    # from the logged-in session just to fill it in; these screens are noindex.
    if not dynamic and path != "/404":
        tags.append(rx.el.link(rel="canonical", href=url))
    return {"description": description, "image": SOCIAL_IMAGE_URL, "meta": tags}


class QualifyApp(rx.App):
    """Apply the operational app's metadata policy to every page registration."""

    def add_page(
        self,
        component: rx.Component | Callable[..., rx.Component] | None = None,
        route: str | None = None,
        title: str | rx.Var | None = None,
        **kwargs: Any,
    ) -> None:
        context = kwargs.pop("context", None) or {}
        # A compatibility registration can name its current destination without
        # teaching the metadata layer retired addresses or changing its redirect.
        metadata_route = context.get("metadata_route", route or "/")
        metadata = page_metadata(metadata_route, title if isinstance(title, str) else "Qualify")
        # Metadata is owned here so a page cannot accidentally restore Reflex's
        # relative favicon or make an operational screen indexable. Other head
        # components and registration options (especially on_load) are preserved.
        extra_meta = kwargs.pop("meta", ()) or ()
        owned_keys = {
            item.get("name", item.get("property"))
            for item in metadata["meta"]
            if isinstance(item, Mapping)
        } | {"description", "og:image"}
        owned_literal_keys = {f'"{key}"' for key in owned_keys}
        for item in extra_meta:
            if isinstance(item, Mapping) and item.get("name", item.get("property")) in owned_keys:
                continue
            if isinstance(item, rx.Component):
                if item.tag == "link" and str(getattr(item, "rel", None)) == '"canonical"':
                    continue
                if item.tag == "meta" and any(
                    str(getattr(item, attr, None)) in owned_literal_keys
                    for attr in ("name", "property")
                ):
                    continue
            metadata["meta"].append(item)
        kwargs.pop("description", None)
        kwargs.pop("image", None)
        context = {**context, "sitemap": None}
        super().add_page(component, route=route, title=title, context=context, **metadata, **kwargs)
