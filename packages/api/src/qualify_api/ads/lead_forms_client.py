"""Fixed-host Meta form boundary; headers from CredentialResolver, never next URLs."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from qualify_api.ads.client import MarketingSettings
from qualify_api.ads.lead_forms import LeadFormUnavailable


def meta_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,40}", value):
        raise LeadFormUnavailable("Meta no devolvió una identificación válida.")
    return value


@dataclass(frozen=True)
class LeadPage:
    rows: tuple[dict, ...]
    after: str | None


class LeadFormsClient:
    def __init__(
        self, client: Any, *, settings: MarketingSettings | None = None, ad_client: Any = None
    ) -> None:
        self.client = client
        self.ad_client = ad_client
        self.root = (settings or MarketingSettings.from_env()).graph_url

    async def read(self, object_id: str, *, fields: str) -> dict:
        return await self._request("GET", meta_id(object_id), params={"fields": fields})

    async def read_ad(self, ad_id: str, *, fields: str) -> dict:
        if self.ad_client is None:
            raise LeadFormUnavailable("No pudimos comprobar el acceso al anuncio.")
        try:
            response = await self.ad_client.get(
                f"{self.root}/{meta_id(ad_id)}", params={"fields": fields}
            )
            body = response.json()
        except Exception:
            raise LeadFormUnavailable("No pudimos comprobar el anuncio en Meta.") from None
        if response.status_code != 200 or not isinstance(body, dict) or "error" in body:
            raise LeadFormUnavailable("No pudimos comprobar el anuncio en Meta.")
        return body

    async def create_form(self, page_id: str, payload: dict) -> str:
        # A POST is NEVER retried by this boundary. Caller claims before reaching it.
        data = {
            key: json.dumps(value, ensure_ascii=False)
            if isinstance(value, (dict, list))
            else str(value)
            for key, value in payload.items()
        }
        result = await self._request("POST", f"{meta_id(page_id)}/leadgen_forms", data=data)
        return meta_id(result.get("id"))

    async def subscribe_leadgen(
        self, page_id: str, *, app_id: str, before_write: Callable[[], None]
    ) -> None:
        page_id, app_id = meta_id(page_id), meta_id(app_id)
        result = await self._request(
            "GET",
            f"{page_id}/subscribed_apps",
            params={"fields": "id,subscribed_fields", "limit": "100"},
        )
        rows = result.get("data")
        if not isinstance(rows, list) or result.get("paging", {}).get("next"):
            raise LeadFormUnavailable("No pudimos comprobar las suscripciones de esta Página.")
        own = [row for row in rows if isinstance(row, dict) and row.get("id") == app_id]
        if len(own) > 1:
            raise LeadFormUnavailable("No pudimos comprobar las suscripciones de esta Página.")
        fields = own[0].get("subscribed_fields") if own else []
        if not isinstance(fields, list) or not all(
            isinstance(value, str) and re.fullmatch(r"[a-z_]{1,100}", value) for value in fields
        ):
            raise LeadFormUnavailable("No pudimos comprobar las suscripciones de esta Página.")
        if "leadgen" in fields:
            return
        before_write()
        result = await self._request(
            "POST",
            f"{page_id}/subscribed_apps",
            data={"subscribed_fields": ",".join(sorted(set(fields) | {"leadgen"}))},
        )
        if result.get("success") is not True:
            raise LeadFormUnavailable("No pudimos confirmar la recepción de datos de esta Página.")

    async def leads(self, form_id: str, *, since: int, after: str | None = None) -> LeadPage:
        if type(since) is not int or since < 0:
            raise LeadFormUnavailable("Revisa la fecha de consulta.")
        params = {
            "fields": "id,form_id,ad_id,created_time,field_data",
            "limit": "100",
            "filtering": json.dumps(
                [{"field": "time_created", "operator": "GREATER_THAN", "value": since}]
            ),
        }
        if after is not None:
            if not isinstance(after, str) or not re.fullmatch(r"[A-Za-z0-9_=-]{1,2048}", after):
                raise LeadFormUnavailable("Meta devolvió una página de resultados no válida.")
            params["after"] = after
        result = await self._request("GET", f"{meta_id(form_id)}/leads", params=params)
        rows = result.get("data")
        if (
            not isinstance(rows, list)
            or len(rows) > 100
            or not all(isinstance(row, dict) for row in rows)
        ):
            raise LeadFormUnavailable("No pudimos comprobar los datos del formulario en Meta.")
        paging = result.get("paging", {})
        cursor = paging.get("cursors", {}).get("after") if isinstance(paging, dict) else None
        # `next` is only a presence marker, never fetched or persisted.
        next_cursor = cursor if isinstance(paging, dict) and paging.get("next") else None
        if next_cursor is not None and (
            not isinstance(next_cursor, str)
            or not re.fullmatch(r"[A-Za-z0-9_=-]{1,2048}", next_cursor)
        ):
            raise LeadFormUnavailable("Meta devolvió una página de resultados no válida.")
        if isinstance(paging, dict) and paging.get("next") and next_cursor is None:
            raise LeadFormUnavailable("Meta no devolvió el cursor de la página siguiente.")
        return LeadPage(tuple(rows), next_cursor)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            response = await getattr(self.client, method.lower())(f"{self.root}/{path}", **kwargs)
            body = response.json()
        except Exception:
            raise LeadFormUnavailable(
                "No pudimos confirmar la respuesta de Meta. Comprueba el estado."
            ) from None
        if response.status_code != 200 or not isinstance(body, dict) or "error" in body:
            raise LeadFormUnavailable(
                "Meta no permitió comprobar esta operación. Revisa el acceso."
            )
        return body

    async def aclose(self) -> None:
        await self.client.aclose()
        if self.ad_client is not None:
            await self.ad_client.aclose()
