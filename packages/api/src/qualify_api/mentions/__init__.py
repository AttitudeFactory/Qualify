"""The Instagram `mentions` webhook receiver + persistence + read API (QUA-49).

Verify the webhook (GET challenge, POST signature), parse the `mentions`-field
payload into typed events (`qualify_shared.social.ig_shapes.parse_mentions_notification`),
resolve which tenant/connection each event belongs to (`resolve.py`, never guessing
across an ambiguous match), enrich a `RESOLVED` event via `mentioned_media`/
`mentioned_comment` (`meta_client.py`), and persist it (`models.py`/`repository.py`) —
orchestrated by `composition.py`. `sentiment.py` adds versioned sentiment analysis over a
mention's text, as its own entity (`mention_sentiment_results`), reusing the same
underlying model call `qualify_api.sentiment` already uses for comments without
conflating a mention with a conversational message. Still out of scope: any UI-facing
`Capability`, and everything Meta's own production access still gates (Business
Verification, Advanced Access/App Review, Page Subscriptions) — external prerequisites,
not code.
"""
