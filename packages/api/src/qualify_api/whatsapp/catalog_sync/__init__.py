"""Upload of Galería products to the business's WhatsApp (Meta Commerce) catalog — ADR 48,
m-25017356. Not to be confused with `whatsapp/catalog.py`, the chat menu's product reader.

- `mapping` — product → Meta item `data`, content hash, eligibility (pure)
- `planning` — what to send and what the screen shows (pure)
- `service` — the three actions and `catalog_sync_view` (the Galería screen's contract)
- `client` — `items_batch` / `check_batch_request_status` seam + fakes
- `worker` — `CatalogSyncTick`, run inside `whatsapp-worker`
- `media_url` — the signed, stable photo URL served by `/public/catalog-media/…`
- `connect` — the administrative CLI that registers a catalog
"""
