"""Payload-shape contracts for connected social platforms.

Strictly contract: parsing and validation only. **No DB, no HTTP, no business
logic** — the moment a module here imports a session or a client it stops being
shareable, which is the whole reason these types live in `qualify_shared` rather
than in a consumer package.
"""
