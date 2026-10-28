"""Media-only ASGI app for a local development tunnel; no workers or business routes.

Run: uv run uvicorn qualify_api.http.media_server:app --host 127.0.0.1 --port 8016 --env-file .env
Keep both this process and its HTTPS tunnel alive while generating reference-based video.
"""

from fastapi import FastAPI

from qualify_api.http import public_media_routes
from qualify_api.http.app import (
    build_production_media_token_store,
    build_production_public_media_gate,
)

app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
app.include_router(public_media_routes.router)
app.dependency_overrides[public_media_routes.get_media_token_store] = (
    build_production_media_token_store
)
app.dependency_overrides[public_media_routes.get_public_media_gate] = (
    build_production_public_media_gate
)
