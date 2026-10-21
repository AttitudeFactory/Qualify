"""Brand substrate: deterministic prompt render (MC-08) + layer-1 fidelity gate (MC-11).

Everything in this package is pure — no clock, no network, no model call — so both the
prompt-cache economics of `render_prompt` and the hard rules of `check_hard_rules` are
provable in unit tests rather than observable in production.
"""

from qualify_creative.brand.fidelity import check_hard_rules, check_route_allowed
from qualify_creative.brand.render import printed_limits, render_prompt

__all__ = ["check_hard_rules", "check_route_allowed", "printed_limits", "render_prompt"]
