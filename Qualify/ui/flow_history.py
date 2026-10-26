"""Session draft addresses for non-page wizards and drawers (PASOS-3).

`flujo` identifies the form, `paso` its visible 1-based step. Optional `consulta`
and `objeto` are internal UUIDs. A route's restore handler owns validation and never
submits anything. Put one ready marker in the active form after it has restored state.
"""

from __future__ import annotations

import reflex as rx

_FLOW_SCRIPT = r"""
(() => {
 if (!window.__qFlowSync) {
  let pending = false;
  window.__qFlowSync = () => {
   if (pending) return;
   pending = true;
   window.requestAnimationFrame(() => {
    pending = false;
    const mark = document.querySelector('.q-drawer[data-state="open"] .q-flow-sync')
      || document.querySelector('main.q-panel .q-flow-sync');
    if (!mark) return;
    const flow = mark.dataset.flow;
    const n = String(Math.max(1, Number(mark.dataset.step) || 1));
    const u = new URL(window.location.href);
    const oldFlow = u.searchParams.get('flujo');
    const oldStep = u.searchParams.get('paso');
    const st = window.history.state || {};
    let same = oldFlow === flow;
    u.searchParams.set('flujo', flow); u.searchParams.set('paso', n);
    for (const key of ['consulta', 'objeto']) {
      const value = mark.dataset[key];
      const valid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
      const id = value && valid.test(value) ? value : '';
      if ((u.searchParams.get(key) || '') !== id) same = false;
      if (id) u.searchParams.set(key, id); else u.searchParams.delete(key);
    }
    const target = u.pathname + u.search + u.hash;
    const current = window.location.pathname + window.location.search + window.location.hash;
    if (target === current) return;
    if (same && Number(n) < Number(oldStep)) {
      if (st.qFlowPrevStep === n) { window.history.back(); return; }
      window.history.replaceState(st, '', target); return;
    }
    window.history.pushState({ ...st, qPrevHref: current,
      qFlowRoot: same ? (st.qFlowRoot || current) : current,
      qFlowDepth: same ? (st.qFlowDepth || 0) + 1 : 1,
      qFlowPrevStep: same ? oldStep : null }, '', target);
   });
  };
  const carriesMarker = node => node?.nodeType === 1 &&
    (node.matches('.q-flow-sync') || node.querySelector('.q-flow-sync'));
  new MutationObserver(records => {
    const changed = records.some(record => record.type === 'attributes'
      ? (record.target.matches('.q-flow-sync') ||
         (record.attributeName === 'data-state' && record.target.matches('.q-drawer')))
      : [...record.addedNodes, ...record.removedNodes].some(carriesMarker));
    if (changed) window.__qFlowSync();
  }).observe(document.body, {subtree: true, childList: true, attributes: true,
    attributeFilter: ['data-flow', 'data-step', 'data-consulta', 'data-objeto', 'data-state']});
 }
 window.__qFlowSync();
})();
"""


def flow_sync(
    flow: str | rx.Var[str],
    step: int | rx.Var[int],
    *,
    ready: bool | rx.Var[bool] = True,
    **params: str | rx.Var[str],
) -> rx.Component:
    """Write only after route restoration; dynamic values remain data, never JS source."""
    unknown = set(params) - {"consulta", "objeto"}
    if unknown:
        raise ValueError(f"Unknown flow parameters: {sorted(unknown)}")
    marker = rx.box(
        key=f"{flow}:{step}:{params.get('consulta', '')}:{params.get('objeto', '')}",
        custom_attrs={
            "data-flow": flow,
            "data-step": step,
            **{f"data-{key}": value for key, value in params.items()},
        },
        on_mount=rx.call_script(_FLOW_SCRIPT),
        class_name="q-flow-sync",
        display="none",
    )
    return rx.cond(ready, marker)
