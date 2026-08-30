"""The Instagram `mentions` webhook receiver (QUA-49).

Scope of this slice, deliberately narrow: verify the webhook (GET challenge,
POST signature), parse the `mentions`-field payload into typed events
(`qualify_shared.social.ig_shapes.parse_mentions_notification`), and resolve
which tenant/connection each event belongs to — read-only, never guessing
across an ambiguous match. Nothing here persists a mention, calls
`mentioned_media`/`mentioned_comment`, touches the UI, or adds a `Capability`.
Those are later slices, once this receptor is proven against real Meta traffic.
"""
