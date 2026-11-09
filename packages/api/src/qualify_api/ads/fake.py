"""Stateful in-memory MarketingAPI double, without credentials or network."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from qualify_api.ads.client import MarketingClient, Payload, _encode, _id
from qualify_api.ads.errors import MarketingError


class FakeMarketingClient(MarketingClient):
    """Objects support create/list/update/status; other reads use explicit fixtures.

    Seed `responses[(method, path)]`; queue `failures` to simulate safe errors.
    This double does not validate Meta policy or model ad delivery.
    """

    def __init__(self, *, account_id: str = "1") -> None:
        self._account = "act_" + _id(account_id.removeprefix("act_"))
        self.objects: dict[str, dict[str, Any]] = {}
        self.responses: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.failures: list[MarketingError] = []

    async def _request(
        self,
        method: str,
        path: str,
        params: Payload,
        *,
        before_write: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        _encode(params)
        if before_write is not None:
            checked = before_write()
            if inspect.isawaitable(checked):
                await checked
        self.calls.append((method, path, deepcopy(dict(params))))
        if self.failures:
            raise self.failures.pop(0)
        if (method, path) in self.responses:
            return deepcopy(self.responses[method, path])
        if path.startswith(self._account + "/") and path.split("/")[-1] in {
            "campaigns",
            "adsets",
            "adcreatives",
            "ads",
        }:
            resource = path.split("/")[-1]
            if method == "POST":
                identifier = str(len(self.objects) + 1)
                self.objects[identifier] = {
                    **deepcopy(dict(params)),
                    "id": identifier,
                    "_resource": resource,
                }
                return {"id": identifier}
            return {
                "data": [
                    {k: deepcopy(v) for k, v in item.items() if k != "_resource"}
                    for item in self.objects.values()
                    if item["_resource"] == resource
                ]
            }
        if path in self.objects:
            if method == "POST":
                self.objects[path].update(deepcopy(dict(params)))
                return {"success": True}
            return {k: deepcopy(v) for k, v in self.objects[path].items() if k != "_resource"}
        raise AssertionError("seed the fake response for this operation")
