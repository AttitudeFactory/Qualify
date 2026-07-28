"""HTTP surface of the Qualify backend (FastAPI). The connect callback lives here
because Meta redirects a browser to it; everything else the CRM needs is available as a
direct importable seam (see `qualify_api.connections.read` / `.service`)."""
