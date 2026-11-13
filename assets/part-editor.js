/* UI-4: the drawer is one history entry inside the existing step frame. */
(() => {
  if (window.__qPartEditor) return;
  window.__qPartEditor = {
    open(n) {
      const u = new URL(location.href);
      u.searchParams.set('paso', '2'); u.searchParams.set('parte', String(n));
      if (u.href !== location.href) history.pushState({...history.state, qPartEntry: true}, '', u);
    },
    focus() { document.getElementById('q-part-editor-question')?.focus({preventScroll:true}); },
    // Invoked only by Radix's close-autofocus lifecycle, after content unmount.
    // The state consumes the captured stable target once; this never retains focus.
    restoreAfterClose(id) { document.getElementById(id)?.focus({preventScroll:true}); },
    close(id, navigate = true) {
      const u = new URL(location.href);
      if (navigate && u.searchParams.has('parte')) {
        u.searchParams.delete('parte');
        if (history.state?.qPartEntry) history.back();
        else history.replaceState({...history.state, qPartEntry: false}, '', u);
      }
    },
    clear() {
      const u = new URL(location.href); u.searchParams.delete('parte');
      history.replaceState({...history.state, qPartEntry: false}, '', u);
    },
  };
  document.addEventListener('keydown', event => {
    const group = event.target.closest?.('#q-part-editor-question');
    if (!group || !['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    const choices = [...group.querySelectorAll('[role="radio"]:not([aria-disabled="true"])')];
    if (!choices.length) return;
    const at = choices.indexOf(document.activeElement);
    const step = ['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : -1;
    const next = choices[at < 0 ? (step > 0 ? 0 : choices.length - 1)
      : (at + step + choices.length) % choices.length];
    next.focus(); next.click();
    event.preventDefault();
  });
})();
