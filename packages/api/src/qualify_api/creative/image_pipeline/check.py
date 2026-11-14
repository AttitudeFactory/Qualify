"""Stage `check` of the image and carousel pipeline (ADR 49 §2 item 4, §2.3) — not built
yet.

In: the composed stills of stage `compose`. Out: approved, or one corrected layer (a child
row in `piece_layers`, `source='model'`) that is composed once more without calling
Seedream again. Active from the start by the founder's choice (§8.3).

m-25017287 builds it. Until then a composed still goes to the owner's review as before.
"""
