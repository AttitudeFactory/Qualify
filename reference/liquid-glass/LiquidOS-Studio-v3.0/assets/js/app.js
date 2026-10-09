(() => {
  const LQ = window.LiquidOS;
  if (!LQ) return;

  const demoRegistry = [
    { id: 'components', title: 'Component Library', subtitle: 'Core catalog', file: 'demos/index.html', category: 'productivity', tags: ['buttons', 'cards', 'tables', 'weather'], description: 'The original core showcase rebuilt as a searchable, interactive component textbook.', background: 'linear-gradient(145deg,#162143,#6449c7 55%,#2fb8d7)' },
    { id: 'advanced', title: 'Advanced Elements', subtitle: 'Extended catalog', file: 'demos/index_2.html', category: 'productivity', tags: ['tabs', 'clock', 'pricing', 'context'], description: 'Tabs, pricing, progress, analog clock, counter, syntax, overlays, and contextual actions.', background: 'linear-gradient(145deg,#251448,#8f3fc0 55%,#ea6ba1)' },
    { id: 'ios', title: 'System Components', subtitle: 'iOS-inspired catalog', file: 'demos/ios_components.html', category: 'productivity', tags: ['island', 'otp', 'gallery', 'chat'], description: 'Dynamic island, passcode, media, calendar, chat, navigation, QR, rating, and utility patterns.', background: 'linear-gradient(145deg,#0d1834,#166c91 55%,#56d7c9)' },
    { id: 'admin', title: 'Admin Intelligence', subtitle: 'Operations dashboard', file: 'demos/admin_dashboard_demo.html', category: 'dashboard', tags: ['analytics', 'orders', 'charts'], description: 'A responsive business dashboard with filtering, charts, metrics, activity, and mobile navigation.', background: 'linear-gradient(145deg,#0f1730,#2c4f9c 55%,#63bdf2)' },
    { id: 'calculator', title: 'Liquid Calculator', subtitle: 'Working utility', file: 'demos/calculator_demo.html', category: 'utility', tags: ['math', 'keyboard', 'history'], description: 'A polished calculator with keyboard support, expression history, percentages, and motion feedback.', background: 'linear-gradient(145deg,#161426,#7134a4 55%,#ef69a4)' },
    { id: 'quote', title: 'Project Estimator', subtitle: 'Quote calculator', file: 'demos/quote_calculator_demo.html', category: 'utility', tags: ['form', 'pricing', 'estimate'], description: 'A multi-step website estimate builder with animated totals, summary, reset, and printable output.', background: 'linear-gradient(145deg,#1a1d36,#5352c7 55%,#4bcbd0)' },
    { id: 'login', title: 'Secure Workspace', subtitle: 'Login + dashboard', file: 'demos/working_login_form_demo.html', category: 'dashboard', tags: ['login', 'auth', 'dashboard'], description: 'An animated sign-in experience that transitions into a complete responsive workspace and logout flow.', background: 'linear-gradient(145deg,#111732,#7843ce 55%,#ee6fae)' },
    { id: 'home', title: 'Liquid Home', subtitle: 'Smart home hub', file: 'demos/liquid_home.html', category: 'dashboard', tags: ['smart home', 'lights', 'climate'], description: 'Room scenes, climate controls, lights, energy status, and contextual home automation.', background: 'linear-gradient(145deg,#102b35,#258b80 55%,#e4a65b)' },
    { id: 'vault', title: 'Liquid Vault', subtitle: 'Secure storage', file: 'demos/liquid_vault.html', category: 'productivity', tags: ['files', 'storage', 'upload'], description: 'A secure file workspace with capacity visualization, search, selection, preview, and upload actions.', background: 'linear-gradient(145deg,#12152c,#5e43bd 55%,#28a8c9)' },
    { id: 'studio', title: 'Liquid Studio', subtitle: 'Creative suite', file: 'demos/liquidstudio.html', category: 'productivity', tags: ['editor', 'layers', 'filters'], description: 'A functional creative canvas with tools, zoom, adjustments, layer selection, export, and history.', background: 'linear-gradient(145deg,#14172d,#6a46c4 55%,#f0629d)' },
    { id: 'trading', title: 'LiquidFi Terminal', subtitle: 'Market workspace', file: 'demos/trading_terminal.html', category: 'dashboard', tags: ['finance', 'chart', 'order'], description: 'Market list, animated price chart, order book, trade controls, and responsive terminal layout.', background: 'linear-gradient(145deg,#081c23,#0b756a 55%,#54e09b)' },
    { id: 'gaming', title: 'Cloud Launcher', subtitle: 'Gaming dashboard', file: 'demos/gaming_dashboard.html', category: 'dashboard', tags: ['games', 'library', 'performance'], description: 'A cinematic launcher with game library, quick resume, friends, settings, and performance telemetry.', background: 'linear-gradient(145deg,#120e27,#5735b2 55%,#e4478c)' },
    { id: 'drone', title: 'Spectre Uplink', subtitle: 'Drone terminal', file: 'demos/drone_terminal.html', category: 'dashboard', tags: ['drone', 'map', 'terminal'], description: 'A tactical operations interface with telemetry, flight controls, radar, mission feed, and command input.', background: 'linear-gradient(145deg,#07161a,#0f5d5b 55%,#75d178)' },
    { id: 'menu', title: 'Liquid Menu Motion', subtitle: 'Navigation experiment', file: 'demos/glass_menu.html', category: 'experimental', tags: ['menu', 'motion', 'navigation'], description: 'A focused navigation study showing spring-open choreography, orbiting actions, and focus-safe close behavior.', background: 'linear-gradient(145deg,#12132c,#6c43d1 55%,#48c6e2)' },
    { id: 'organic', title: 'Organic Liquid Field', subtitle: 'Canvas experiment', file: 'demos/organic_liquid.html', category: 'experimental', tags: ['metaballs', 'canvas', 'physics'], description: 'A dependency-free organic liquid field that attracts, merges, splits, and responds to pointer gestures.', background: 'linear-gradient(145deg,#204ad0,#8a36d3 42%,#f04c91 70%,#efa442)' },
    { id: 'intro', title: 'LiquidOS Intro', subtitle: 'Motion opener', file: 'demos/intro_html_forvideo.html', category: 'experimental', tags: ['intro', 'type', 'animation'], description: 'A cinematic, replayable opening sequence for product videos, demos, or onboarding.', background: 'linear-gradient(145deg,#10132c,#7445c6 52%,#48bedd)' },
    { id: 'effects', title: 'Effects Playground', subtitle: 'Guided showcase', file: 'demos/ease_of_use.html', category: 'utility', tags: ['effects', 'copy', 'guide'], description: 'A clearer replacement for the original ease-of-use page with working samples and copy-ready recipes.', background: 'linear-gradient(145deg,#16254d,#4e66d4 50%,#e368b1)' }
  ];

  const routeNames = ['overview', 'builder', 'components', 'demos', 'docs'];
  const body = document.body;
  const menu = document.getElementById('liquid-menu');
  const menuTrigger = document.getElementById('menu-trigger');
  const topbar = document.getElementById('studio-topbar');
  const themeToggle = document.getElementById('theme-toggle');
  let activeRoute = 'overview';
  let lastMenuFocus = null;

  function getRoute() {
    const hash = location.hash.replace('#', '').split('/')[0];
    return routeNames.includes(hash) ? hash : 'overview';
  }

  function openMenu() {
    lastMenuFocus = document.activeElement;
    body.classList.add('menu-open');
    menu.inert = false;
    document.getElementById('studio-main').inert = true;
    menuTrigger.setAttribute('aria-expanded', 'true');
    menuTrigger.setAttribute('aria-label', 'Close navigation');
    menu.setAttribute('aria-hidden', 'false');
    window.setTimeout(() => menu.querySelector('.liquid-menu__link')?.focus(), 260);
  }

  function closeMenu(restoreFocus = false) {
    body.classList.remove('menu-open');
    menu.inert = true;
    document.getElementById('studio-main').inert = false;
    menuTrigger.setAttribute('aria-expanded', 'false');
    menuTrigger.setAttribute('aria-label', 'Open navigation');
    menu.setAttribute('aria-hidden', 'true');
    if (restoreFocus && lastMenuFocus instanceof HTMLElement) lastMenuFocus.focus();
  }

  function showRoute(route, options = {}) {
    const nextRoute = routeNames.includes(route) ? route : 'overview';
    activeRoute = nextRoute;
    document.querySelectorAll('[data-view]').forEach((view) => {
      const active = view.dataset.view === nextRoute;
      view.hidden = !active;
      view.classList.toggle('is-entering', active);
      if (active) window.setTimeout(() => view.classList.remove('is-entering'), 850);
    });
    document.querySelectorAll('[data-route-link]').forEach((link) => {
      if (link.dataset.routeLink === nextRoute) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    const labels = { overview: 'Overview', builder: 'Glass Lab', components: 'Components', demos: 'Demos', docs: 'Documentation' };
    document.title = `${labels[nextRoute]} · LiquidOS Studio 3.0`;
    closeMenu(false);
    if (!options.keepScroll) window.scrollTo({ top: 0, behavior: LQ.reducedMotion ? 'auto' : 'smooth' });
    if (location.hash !== `#${nextRoute}` && !options.fromHash) location.hash = nextRoute;
  }

  function setTheme(light, persist = true) {
    body.classList.toggle('is-light', light);
    themeToggle.innerHTML = LQ.icon(light ? 'sun' : 'moon');
    themeToggle.setAttribute('aria-label', light ? 'Use dark appearance' : 'Use light appearance');
    themeToggle.dataset.tooltip = light ? 'Use dark appearance' : 'Use light appearance';
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', light ? '#e8eef9' : '#080b14');
    if (persist) {
      try { localStorage.setItem('liquidos-theme', light ? 'light' : 'dark'); } catch (error) { void error; }
    }
  }

  function initShell() {
    LQ.initAmbientCanvas(document.getElementById('ambient-canvas'));
    menuTrigger.addEventListener('click', () => body.classList.contains('menu-open') ? closeMenu(true) : openMenu());
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && body.classList.contains('menu-open')) closeMenu(true);
      if (event.key !== 'Tab' || !body.classList.contains('menu-open')) return;
      const focusables = [...menu.querySelectorAll('a[href], button:not([disabled])'), menuTrigger];
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    document.querySelectorAll('[data-route-link]').forEach((link) => {
      link.addEventListener('click', (event) => {
        event.preventDefault();
        const route = link.dataset.routeLink;
        if (location.hash === `#${route}`) showRoute(route, { fromHash: true });
        else location.hash = route;
      });
    });
    window.addEventListener('hashchange', () => showRoute(getRoute(), { fromHash: true }));
    window.addEventListener('scroll', () => topbar.classList.toggle('is-scrolled', window.scrollY > 18), { passive: true });
    let savedTheme = 'dark';
    try { savedTheme = localStorage.getItem('liquidos-theme') || 'dark'; } catch (error) { void error; }
    setTheme(savedTheme === 'light', false);
    themeToggle.addEventListener('click', () => setTheme(!body.classList.contains('is-light')));
    showRoute(getRoute(), { fromHash: true, keepScroll: true });

    const clock = document.getElementById('hero-clock');
    const updateClock = () => {
      const now = new Date();
      if (clock) clock.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    };
    updateClock();
    window.setInterval(updateClock, 30000);
  }

  const builderDefaults = {
    mode: 'liquid', scene: 'spectrum', blur: 20, opacity: 10, saturation: 155,
    radius: 30, border: 30, refraction: 18, frequency: 24, depth: 72, tint: '#8b7cff'
  };
  let builderState = { ...builderDefaults };
  let activeCodeTab = 'css';

  function hexToRgb(hex) {
    const value = hex.replace('#', '');
    const parsed = Number.parseInt(value.length === 3 ? value.split('').map((item) => item + item).join('') : value, 16);
    return [(parsed >> 16) & 255, (parsed >> 8) & 255, parsed & 255];
  }

  function createBuilderFilter() {
    if (document.getElementById('builder-refraction-svg')) return;
    const wrap = document.createElement('div');
    wrap.hidden = true;
    wrap.innerHTML = `<svg id="builder-refraction-svg" xmlns="http://www.w3.org/2000/svg"><filter id="builder-refraction-filter" x="-40%" y="-40%" width="180%" height="180%"><feTurbulence id="builder-noise" type="fractalNoise" baseFrequency="0.024" numOctaves="2" seed="12" result="noise"/><feGaussianBlur in="noise" stdDeviation="0.55" result="softNoise"/><feDisplacementMap id="builder-displacement" in="SourceGraphic" in2="softNoise" scale="18" xChannelSelector="R" yChannelSelector="G"/></filter></svg>`;
    document.body.appendChild(wrap);
  }

  function builderCss() {
    const [r, g, b] = hexToRgb(builderState.tint);
    const modeExtra = builderState.mode === 'frosted'
      ? `background: linear-gradient(145deg, rgba(255,255,255,${((builderState.opacity + 8) / 100).toFixed(2)}), rgba(${r},${g},${b},${(builderState.opacity / 260).toFixed(3)}));`
      : builderState.mode === 'clear'
        ? `background: linear-gradient(145deg, rgba(255,255,255,${(builderState.opacity / 210).toFixed(3)}), rgba(${r},${g},${b},${(builderState.opacity / 520).toFixed(3)}));`
        : `background: radial-gradient(circle at var(--pointer-x,30%) var(--pointer-y,20%), rgba(255,255,255,.28), transparent 24%), linear-gradient(145deg, rgba(255,255,255,${((builderState.opacity + 3.5) / 100).toFixed(3)}), rgba(${r},${g},${b},${(builderState.opacity / 220).toFixed(3)}));`;
    return `.liquid-glass {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,${(builderState.border / 100).toFixed(2)});
  border-radius: ${builderState.radius}px;
  ${modeExtra}
  box-shadow: inset 0 1px 0 rgba(255,255,255,.32), 0 32px 68px rgba(15,20,64,.30);
  -webkit-backdrop-filter: blur(${builderState.blur}px) saturate(${builderState.saturation}%);
  backdrop-filter: blur(${builderState.blur}px) saturate(${builderState.saturation}%);
}

.liquid-glass::before {
  position: absolute;
  inset: -18%;
  background: conic-gradient(from 215deg, transparent 0 30%, rgba(255,255,255,.24) 37%, transparent 48% 100%);
  content: "";
  filter: url(#liquid-refraction) blur(${Math.max(1, Math.round(builderState.depth / 18))}px);
  opacity: ${(builderState.depth / 100).toFixed(2)};
  pointer-events: none;
}`;
  }

  function builderHtml() {
    return `<article class="liquid-glass">
  <span class="eyebrow">LiquidOS material</span>
  <h2>Optical depth.</h2>
  <p>Layered glass with responsive highlight and refraction.</p>
</article>

<svg width="0" height="0" aria-hidden="true">
  <filter id="liquid-refraction" x="-40%" y="-40%" width="180%" height="180%">
    <feTurbulence type="fractalNoise" baseFrequency="${(builderState.frequency / 1000).toFixed(3)}" numOctaves="2" seed="12" result="noise"/>
    <feDisplacementMap in="SourceGraphic" in2="noise" scale="${builderState.refraction}"/>
  </filter>
</svg>`;
  }

  function builderTokens() {
    return `:root {
  --liquid-mode: ${builderState.mode};
  --liquid-blur: ${builderState.blur}px;
  --liquid-opacity: ${(builderState.opacity / 100).toFixed(2)};
  --liquid-saturation: ${builderState.saturation}%;
  --liquid-radius: ${builderState.radius}px;
  --liquid-border-alpha: ${(builderState.border / 100).toFixed(2)};
  --liquid-refraction: ${builderState.refraction};
  --liquid-frequency: ${(builderState.frequency / 1000).toFixed(3)};
  --liquid-depth: ${(builderState.depth / 100).toFixed(2)};
  --liquid-tint: ${builderState.tint};
}`;
  }

  function builderCode() {
    if (activeCodeTab === 'html') return builderHtml();
    if (activeCodeTab === 'tokens') return builderTokens();
    return builderCss();
  }

  function updateBuilder(persist = true) {
    const preview = document.getElementById('builder-preview-card');
    const scene = document.getElementById('builder-scene');
    const [r, g, b] = hexToRgb(builderState.tint);
    preview.dataset.mode = builderState.mode;
    scene.dataset.scene = builderState.scene;
    preview.style.setProperty('--builder-blur', `${builderState.blur}px`);
    preview.style.setProperty('--builder-opacity', (builderState.opacity / 100).toFixed(2));
    preview.style.setProperty('--builder-saturation', `${builderState.saturation}%`);
    preview.style.setProperty('--builder-radius', `${builderState.radius}px`);
    preview.style.setProperty('--builder-border', (builderState.border / 100).toFixed(2));
    preview.style.setProperty('--builder-tint', `${r}, ${g}, ${b}`);
    preview.style.setProperty('--builder-depth', (builderState.depth / 100).toFixed(2));
    const turbulence = document.getElementById('builder-noise');
    const displacement = document.getElementById('builder-displacement');
    if (turbulence) turbulence.setAttribute('baseFrequency', (builderState.frequency / 1000).toFixed(3));
    if (displacement) displacement.setAttribute('scale', String(builderState.refraction));
    document.querySelectorAll('[data-builder-mode]').forEach((button) => button.classList.toggle('is-active', button.dataset.builderMode === builderState.mode));
    document.getElementById('builder-scene-select').value = builderState.scene;
    const output = document.getElementById('builder-code-output');
    output.textContent = builderCode();
    if (persist) {
      try { localStorage.setItem('liquidos-builder', JSON.stringify(builderState)); } catch (error) { void error; }
    }
  }

  function syncBuilderControls() {
    const formatters = {
      blur: (value) => `${value}px`, opacity: (value) => `${value}%`, saturation: (value) => `${value}%`,
      radius: (value) => `${value}px`, border: (value) => `${value}%`, refraction: (value) => `${value}`,
      frequency: (value) => `${value}`, depth: (value) => `${value}%`
    };
    Object.keys(formatters).forEach((key) => {
      const input = document.getElementById(`builder-${key}`);
      const output = document.getElementById(`builder-${key}-value`);
      input.value = builderState[key];
      output.textContent = formatters[key](builderState[key]);
    });
    document.getElementById('builder-tint').value = builderState.tint;
    document.getElementById('builder-scene-select').value = builderState.scene;
  }

  function initBuilder() {
    createBuilderFilter();
    try {
      const saved = JSON.parse(localStorage.getItem('liquidos-builder') || 'null');
      if (saved && typeof saved === 'object') builderState = { ...builderDefaults, ...saved };
    } catch (error) { void error; }
    syncBuilderControls();
    updateBuilder(false);

    document.querySelectorAll('[data-builder-mode]').forEach((button) => {
      button.addEventListener('click', () => { builderState.mode = button.dataset.builderMode; updateBuilder(); });
    });
    document.getElementById('builder-scene-select').addEventListener('change', (event) => { builderState.scene = event.target.value; updateBuilder(); });
    ['blur', 'opacity', 'saturation', 'radius', 'border', 'refraction', 'frequency', 'depth'].forEach((key) => {
      const input = document.getElementById(`builder-${key}`);
      input.addEventListener('input', () => {
        builderState[key] = Number(input.value);
        document.getElementById(`builder-${key}-value`).textContent = ({ blur: `${input.value}px`, opacity: `${input.value}%`, saturation: `${input.value}%`, radius: `${input.value}px`, border: `${input.value}%`, depth: `${input.value}%` })[key] || input.value;
        updateBuilder();
      });
    });
    document.getElementById('builder-tint').addEventListener('input', (event) => { builderState.tint = event.target.value; updateBuilder(); });
    document.querySelectorAll('[data-code-tab]').forEach((button) => {
      button.addEventListener('click', () => {
        activeCodeTab = button.dataset.codeTab;
        document.querySelectorAll('[data-code-tab]').forEach((item) => {
          const active = item === button;
          item.classList.toggle('is-active', active);
          item.setAttribute('aria-selected', String(active));
        });
        updateBuilder(false);
      });
    });
    document.getElementById('builder-copy').addEventListener('click', () => LQ.copyText(builderCode(), `${activeCodeTab.toUpperCase()} copied`));
    document.getElementById('builder-reset').addEventListener('click', () => {
      builderState = { ...builderDefaults };
      syncBuilderControls();
      updateBuilder();
      LQ.toast('Builder reset', 'The default liquid material is restored.', { icon: 'refresh' });
    });
    document.getElementById('builder-randomize').addEventListener('click', () => {
      const choices = ['liquid', 'frosted', 'clear'];
      const scenes = ['spectrum', 'ocean', 'orchid', 'noir'];
      const colors = ['#8b7cff', '#51d7ff', '#ff6fbb', '#61e4a0', '#ffb86c'];
      builderState = {
        mode: choices[Math.floor(Math.random() * choices.length)], scene: scenes[Math.floor(Math.random() * scenes.length)],
        blur: 8 + Math.floor(Math.random() * 34), opacity: 5 + Math.floor(Math.random() * 19), saturation: 100 + Math.floor(Math.random() * 23) * 5,
        radius: 10 + Math.floor(Math.random() * 45), border: 15 + Math.floor(Math.random() * 44), refraction: 6 + Math.floor(Math.random() * 37),
        frequency: 10 + Math.floor(Math.random() * 43), depth: 35 + Math.floor(Math.random() * 60), tint: colors[Math.floor(Math.random() * colors.length)]
      };
      syncBuilderControls();
      updateBuilder();
      LQ.toast('New material generated', 'Every value remains editable.', { icon: 'sparkles' });
    });
    document.getElementById('builder-download').addEventListener('click', () => {
      const content = `${builderCss()}\n\n${builderHtml()}`;
      const blob = new Blob([content], { type: 'text/css' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'liquidos-generated-material.css';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      LQ.toast('CSS downloaded', 'Your generated material is ready.', { icon: 'download' });
    });
    const preview = document.getElementById('builder-preview-card');
    preview.addEventListener('pointermove', (event) => {
      if (LQ.reducedMotion) return;
      const rect = preview.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width;
      const y = (event.clientY - rect.top) / rect.height;
      preview.style.setProperty('--builder-pointer-x', `${x * 100}%`);
      preview.style.setProperty('--builder-pointer-y', `${y * 100}%`);
      preview.style.setProperty('--builder-tilt-x', `${(y - 0.5) * -6}deg`);
      preview.style.setProperty('--builder-tilt-y', `${(x - 0.5) * 8}deg`);
    });
    preview.addEventListener('pointerleave', () => {
      preview.style.setProperty('--builder-tilt-x', '0deg');
      preview.style.setProperty('--builder-tilt-y', '0deg');
    });
  }

  function demoCardTemplate(demo) {
    return `<article class="demo-card lq-glass lq-tilt" data-demo-id="${demo.id}" data-demo-category="${demo.category}" data-demo-search="${LQ.escapeHtml([demo.title, demo.subtitle, demo.description, ...demo.tags].join(' ').toLowerCase())}" style="--demo-bg:${demo.background}">
      <div class="demo-card__preview"><div class="demo-card__window"><span class="demo-card__rail"></span><span class="demo-card__screen"><i class="demo-card__bar"></i><span class="demo-card__content"><i></i><i></i><i></i></span></span></div></div>
      <div class="demo-card__body">
        <div class="demo-card__meta"><span>${LQ.escapeHtml(demo.subtitle)}</span><span class="lq-badge">${LQ.escapeHtml(demo.category)}</span></div>
        <h3>${LQ.escapeHtml(demo.title)}</h3>
        <p>${LQ.escapeHtml(demo.description)}</p>
        <div class="demo-card__actions"><button class="lq-button lq-button--primary" type="button" data-preview-demo="${demo.id}"><span data-icon="play"></span>Preview</button><a class="lq-button" href="${demo.file}" target="_blank" rel="noopener"><span data-icon="external"></span>Open</a></div>
      </div>
    </article>`;
  }

  function initDemos() {
    const grid = document.getElementById('demo-grid');
    grid.innerHTML = demoRegistry.map(demoCardTemplate).join('');
    LQ.hydrateIcons(grid);
    LQ.initTilts(grid);
    const search = document.getElementById('demo-search');
    const filters = [...document.querySelectorAll('[data-demo-filter]')];
    let activeFilter = 'all';
    const filter = () => {
      const query = search.value.trim().toLowerCase();
      grid.querySelectorAll('.demo-card').forEach((card) => {
        const categoryMatch = activeFilter === 'all' || card.dataset.demoCategory === activeFilter;
        const queryMatch = !query || card.dataset.demoSearch.includes(query);
        card.hidden = !(categoryMatch && queryMatch);
      });
    };
    search.addEventListener('input', filter);
    filters.forEach((button) => {
      button.addEventListener('click', () => {
        activeFilter = button.dataset.demoFilter;
        filters.forEach((item) => item.classList.toggle('is-active', item === button));
        filter();
      });
    });
    grid.addEventListener('click', (event) => {
      const button = event.target.closest('[data-preview-demo]');
      if (!button) return;
      const demo = demoRegistry.find((item) => item.id === button.dataset.previewDemo);
      if (!demo) return;
      const dialog = document.getElementById('demo-preview-dialog');
      document.getElementById('demo-preview-title').textContent = demo.title;
      document.getElementById('demo-preview-subtitle').textContent = demo.description;
      document.getElementById('demo-open-new').href = demo.file;
      document.getElementById('demo-preview-frame').src = demo.file;
      dialog.showModal();
    });
    const dialog = document.getElementById('demo-preview-dialog');
    dialog.addEventListener('close', () => { document.getElementById('demo-preview-frame').src = 'about:blank'; });
  }

  function updateAnalogClock() {
    const clock = document.getElementById('sample-clock');
    if (!clock) return;
    const now = new Date();
    const values = {
      hour: (now.getHours() % 12) * 30 + now.getMinutes() * 0.5,
      minute: now.getMinutes() * 6 + now.getSeconds() * 0.1,
      second: now.getSeconds() * 6
    };
    Object.entries(values).forEach(([name, angle]) => clock.querySelector(`[data-clock-hand="${name}"]`)?.style.setProperty('--hand-angle', `${angle}deg`));
  }

  function setKnobValue(knob, value) {
    const normalized = Math.max(0, Math.min(100, Math.round(value)));
    const angle = normalized * 2.64;
    knob.style.setProperty('--knob-angle', `${angle}deg`);
    knob.setAttribute('aria-valuenow', String(normalized));
    knob.querySelector('span').textContent = `${normalized}%`;
  }

  function initComponents() {
    document.querySelectorAll('[data-component-jump]').forEach((button) => {
      button.addEventListener('click', () => {
        const target = document.getElementById(button.dataset.componentJump);
        if (!target) return;
        document.querySelectorAll('[data-component-jump]').forEach((item) => item.classList.toggle('is-active', item === button));
        target.scrollIntoView({ behavior: LQ.reducedMotion ? 'auto' : 'smooth', block: 'start' });
      });
    });
    document.querySelectorAll('[data-segmented]').forEach((group) => {
      group.addEventListener('click', (event) => {
        const button = event.target.closest('button');
        if (!button) return;
        group.querySelectorAll('button').forEach((item) => item.classList.toggle('is-active', item === button));
      });
    });
    const range = document.getElementById('sample-range');
    range.addEventListener('input', () => { document.getElementById('sample-range-output').textContent = `${range.value}%`; });
    document.querySelectorAll('[data-demo-toast]').forEach((button) => button.addEventListener('click', () => LQ.toast('Component ready', 'The toast enters, announces itself, and dismisses cleanly.')));
    document.querySelector('[data-confirm-dialog]')?.addEventListener('click', () => LQ.toast('Confirmed', 'The native dialog completed successfully.'));
    document.getElementById('sample-flip-card').addEventListener('click', (event) => event.currentTarget.classList.toggle('is-flipped'));
    updateAnalogClock();
    window.setInterval(updateAnalogClock, 1000);

    const knob = document.getElementById('sample-knob');
    setKnobValue(knob, 48);
    const updateKnobFromPointer = (event) => {
      const rect = knob.getBoundingClientRect();
      const x = event.clientX - (rect.left + rect.width / 2);
      const y = event.clientY - (rect.top + rect.height / 2);
      let degrees = Math.atan2(y, x) * 180 / Math.PI + 90;
      if (degrees < 0) degrees += 360;
      const clamped = degrees > 264 && degrees < 312 ? 264 : degrees >= 312 ? 0 : Math.min(264, degrees);
      setKnobValue(knob, clamped / 2.64);
    };
    knob.addEventListener('pointerdown', (event) => {
      knob.setPointerCapture(event.pointerId);
      updateKnobFromPointer(event);
    });
    knob.addEventListener('pointermove', (event) => { if (knob.hasPointerCapture(event.pointerId)) updateKnobFromPointer(event); });
    knob.addEventListener('keydown', (event) => {
      if (!['ArrowUp', 'ArrowRight', 'ArrowDown', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const current = Number(knob.getAttribute('aria-valuenow'));
      if (event.key === 'Home') setKnobValue(knob, 0);
      else if (event.key === 'End') setKnobValue(knob, 100);
      else setKnobValue(knob, current + (['ArrowUp', 'ArrowRight'].includes(event.key) ? 2 : -2));
    });

    const keyboard = document.getElementById('sample-keyboard');
    keyboard.addEventListener('click', (event) => {
      const key = event.target.closest('button');
      if (!key) return;
      key.classList.add('is-pressed');
      window.setTimeout(() => key.classList.remove('is-pressed'), 140);
    });
    document.addEventListener('keydown', (event) => {
      if (activeRoute !== 'components' || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) return;
      const label = event.code === 'Space' ? 'Space' : event.key.toUpperCase();
      const key = [...keyboard.querySelectorAll('button')].find((button) => button.textContent === label);
      if (key) {
        key.classList.add('is-pressed');
        window.setTimeout(() => key.classList.remove('is-pressed'), 120);
      }
    });

    const zone = document.getElementById('sample-context-zone');
    const context = document.getElementById('sample-context-menu');
    const showContext = (x, y) => {
      context.style.left = `${Math.min(x, innerWidth - 200)}px`;
      context.style.top = `${Math.min(y, innerHeight - 160)}px`;
      context.classList.add('is-open');
      context.inert = false;
      context.setAttribute('aria-hidden', 'false');
    };
    zone.addEventListener('contextmenu', (event) => { event.preventDefault(); showContext(event.clientX, event.clientY); });
    let pressTimer = 0;
    zone.addEventListener('pointerdown', (event) => { pressTimer = window.setTimeout(() => showContext(event.clientX, event.clientY), 560); });
    ['pointerup', 'pointercancel', 'pointermove'].forEach((name) => zone.addEventListener(name, () => clearTimeout(pressTimer)));
    document.addEventListener('pointerdown', (event) => {
      if (!event.target.closest('#sample-context-menu') && !event.target.closest('#sample-context-zone')) {
        context.classList.remove('is-open');
        context.inert = true;
        context.setAttribute('aria-hidden', 'true');
      }
    });
    context.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      context.classList.remove('is-open');
      context.inert = true;
      context.setAttribute('aria-hidden', 'true');
      LQ.toast(button.textContent.trim(), 'Context action completed.');
    });
  }

  function init() {
    initShell();
    initBuilder();
    initDemos();
    initComponents();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
