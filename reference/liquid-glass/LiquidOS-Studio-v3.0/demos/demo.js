(() => {
  const LQ = window.LiquidOS;
  if (!LQ) return;
  const demoId = document.body.dataset.demo || 'components';
  const root = document.getElementById('demo-root');
  let uid = 0;

  const icon = (name) => `<span data-icon="${name}"></span>`;
  const chart = (points = 'M0 180C45 155 72 169 110 128s68 18 102-22 69 25 103-16 67-32 105-21 69-47 120-32', height = 220) => {
    const id = `chart-fill-${uid++}`;
    return `<svg class="demo-chart" viewBox="0 0 540 ${height}" preserveAspectRatio="none" role="img" aria-label="Trend chart"><defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--demo-accent-2)" stop-opacity=".42"/><stop offset="1" stop-color="var(--demo-accent-2)" stop-opacity="0"/></linearGradient></defs><path class="demo-chart-grid" d="M0 40H540M0 90H540M0 140H540M0 190H540"/><path class="demo-chart-area" fill="url(#${id})" d="${points}V${height}H0Z"/><path class="demo-chart-line" d="${points}"/></svg>`;
  };

  const backChrome = (label = 'Back to demos') => `<a class="demo-back" href="../index.html#demos" aria-label="${label}">${icon('arrow')}<span>${label}</span></a><span class="demo-version lq-badge">LiquidOS 3.0</span>`;

  const page = (content, options = {}) => `${backChrome()}<canvas id="demo-ambient" aria-hidden="true"></canvas><main class="demo-page ${options.className || ''}">${content}</main>`;

  const heading = (kicker, title, description, actions = '') => `<header class="demo-heading"><div class="demo-heading__copy"><span class="demo-kicker">${kicker}</span><h1>${title}</h1><p>${description}</p></div>${actions ? `<div class="demo-actions">${actions}</div>` : ''}</header>`;

  const metric = (title, value, note, iconName, className = 'span-3') => `<article class="demo-card demo-metric lq-glass ${className}"><div class="demo-metric__top"><span>${title}</span><span class="demo-metric__icon">${icon(iconName)}</span></div><div><strong>${value}</strong><small>${note}</small></div></article>`;

  function appShell(config) {
    const nav = config.nav.map((item, index) => `<button class="${index === 0 ? 'is-active' : ''}" type="button" data-app-nav="${item.label.toLowerCase().replace(/\s+/g, '-')}">${icon(item.icon)}<span>${item.label}</span></button>`).join('');
    return `<div class="app-shell" id="app-shell">
      <aside class="app-sidebar">
        <div class="app-logo"><span class="app-logo__mark">${icon(config.logoIcon || 'sparkles')}</span><span>${config.brand}</span></div>
        <nav class="app-nav">${nav}</nav>
        <div class="app-sidebar__foot"><button class="lq-button lq-button--ghost" type="button" data-app-settings>${icon('settings')}<span>Settings</span></button><div class="app-user"><span class="lq-avatar">${config.initials || 'LU'}</span><span class="app-user__copy"><strong>${config.user || 'Liquid User'}</strong><small>${config.role || 'Administrator'}</small></span>${icon('more')}</div></div>
      </aside>
      <section class="app-content">
        <header class="app-topbar"><button class="lq-button lq-icon-button app-mobile-menu" type="button" data-app-menu aria-label="Open app navigation">${icon('grid')}</button><div class="app-title"><h1>${config.title}</h1><p>${config.subtitle}</p></div><div class="demo-cluster"><div class="lq-field-wrap app-search">${icon('search')}<input class="lq-field" type="search" placeholder="Search workspace" data-app-search></div><button class="lq-button lq-icon-button lq-tooltip" type="button" data-tooltip="Notifications" data-app-notify>${icon('bell')}</button></div></header>
        <div data-app-content>${config.content}</div>
      </section>
    </div>`;
  }

  function componentLibrary() {
    return page(`${heading('Component textbook', 'Liquid Glass UI', 'The core catalog from the original release, rebuilt with native controls, cleaner hierarchy, and working interactions.', `<a class="lq-button lq-button--primary" href="index_2.html">Advanced elements ${icon('arrow')}</a>`)}
      <div class="catalog-layout">
        <nav class="catalog-sidebar lq-glass" aria-label="Component chapters">
          <button class="is-active" type="button" data-catalog-jump="core-actions">${icon('cursor')}Actions</button>
          <button type="button" data-catalog-jump="core-controls">${icon('sliders')}Controls</button>
          <button type="button" data-catalog-jump="core-content">${icon('layers')}Content</button>
          <button type="button" data-catalog-jump="core-data">${icon('chart')}Data</button>
          <button type="button" data-catalog-jump="core-feedback">${icon('bell')}Feedback</button>
        </nav>
        <div class="catalog-content">
          <section class="catalog-section lq-glass" id="core-actions"><header><div><h2>Buttons and navigation</h2><p>Pill, square, rounded, icon, and breadcrumb actions.</p></div><span class="lq-badge">Interactive</span></header><div class="sample-grid">
            <article class="sample-box"><span class="sample-label">Button shapes</span><button class="lq-button lq-button--primary lq-button--pill" type="button">Pill button</button><button class="lq-button" type="button">Rounded button</button></article>
            <article class="sample-box"><span class="sample-label">Icon actions</span><div class="demo-cluster"><button class="lq-button lq-icon-button" type="button">${icon('heart')}</button><button class="lq-button lq-icon-button" type="button">${icon('send')}</button><button class="lq-button lq-icon-button" type="button">${icon('more')}</button></div></article>
            <article class="sample-box sample-box--left"><span class="sample-label">Breadcrumb</span><div class="demo-cluster"><span class="lq-tag">Home</span>${icon('chevron')}<span class="lq-tag">Library</span>${icon('chevron')}<strong>Component</strong></div></article>
          </div></section>
          <section class="catalog-section lq-glass" id="core-controls"><header><div><h2>Controls</h2><p>Knob, progress, tracker, flip card, and keyboard.</p></div><span class="lq-badge">Physical response</span></header><div class="sample-grid">
            <article class="sample-box"><span class="sample-label">Rotary knob</span><div class="knob demo-knob" role="slider" tabindex="0" aria-valuenow="54" aria-valuemin="0" aria-valuemax="100"><span>54%</span></div></article>
            <article class="sample-box sample-box--left"><span class="sample-label">Tracker</span><strong>Project completion</strong><div class="lq-progress"><span id="core-progress" style="--lq-progress:68%"></span></div><input class="lq-range" id="core-progress-range" type="range" value="68"></article>
            <article class="sample-box"><span class="sample-label">Flip card</span><button class="flip-card demo-flip" type="button"><span class="flip-card__inner"><span class="flip-card__face"><strong>Card front</strong><small>Tap to reveal</small></span><span class="flip-card__face flip-card__face--back"><strong>Card back</strong><small>Material retained</small></span></span></button></article>
          </div><div class="sample-box sample-box--left" style="margin-top:10px"><span class="sample-label">Liquid keyboard</span><div class="keyboard-mini" data-demo-keyboard><button type="button">Q</button><button type="button">W</button><button type="button">E</button><button type="button">R</button><button type="button">T</button><button type="button">Y</button><button type="button">A</button><button type="button">S</button><button type="button">D</button><button type="button">F</button><button type="button">G</button><button type="button">H</button><button class="is-wide" type="button">Space</button><button class="is-wide" type="button">Return</button></div></div></section>
          <section class="catalog-section lq-glass" id="core-content"><header><div><h2>Content modules</h2><p>Secure login, weather, countdown, task list, and quote.</p></div><span class="lq-badge">Responsive</span></header><div class="sample-grid">
            <article class="sample-box sample-box--left"><span class="sample-label">Secure login</span><div class="lq-field-wrap">${icon('user')}<input class="lq-field" placeholder="Username"></div><div class="lq-field-wrap">${icon('lock')}<input class="lq-field" type="password" placeholder="Password"></div><button class="lq-button lq-button--primary" type="button" data-mini-login>Sign in</button></article>
            <article class="sample-box"><span class="sample-label">Weather</span><span style="font-size:3rem">24°</span><strong>Clear glass</strong><small style="color:var(--lq-text-soft)">New York · Feels like 25°</small></article>
            <article class="sample-box"><span class="sample-label">Countdown</span><strong style="font-size:2rem" id="core-countdown">04:18:32</strong><small style="color:var(--lq-text-soft)">Until the next release</small></article>
          </div><div class="sample-grid sample-grid--two" style="margin-top:10px"><article class="sample-box sample-box--left"><span class="sample-label">Task list</span><label class="lq-check"><input type="checkbox" checked>Audit tokens</label><label class="lq-check"><input type="checkbox">Polish motion</label><label class="lq-check"><input type="checkbox">Ship demo</label></article><article class="sample-box"><span class="sample-label">Featured quote</span><blockquote style="margin:0;font-size:1.15rem;letter-spacing:-.03em">“Interfaces should feel understood before they feel impressive.”</blockquote><small style="color:var(--lq-text-faint)">LiquidOS principles</small></article></div></section>
          <section class="catalog-section lq-glass" id="core-data"><header><div><h2>Data display</h2><p>Charts, metrics, tags, and responsive tables.</p></div><span class="lq-badge lq-badge--success">Live</span></header><div class="sample-grid sample-grid--two"><article class="sample-box sample-box--left"><span class="sample-label">Performance chart</span>${chart('M0 185C45 150 75 174 114 128s67 23 108-19 70 32 108-18 61-26 102-13 68-54 108-37')}</article><article class="sample-box sample-box--left"><span class="sample-label">Tag cloud</span><div class="demo-cluster"><span class="lq-tag">Liquid</span><span class="lq-tag">Optical</span><span class="lq-tag">Motion</span><span class="lq-tag">Glass</span><span class="lq-tag">Tokens</span><span class="lq-tag">Accessible</span></div></article></div><div class="lq-table-wrap" style="margin-top:10px"><table class="lq-table"><thead><tr><th>Name</th><th>Category</th><th>Status</th><th>Usage</th></tr></thead><tbody><tr><td>Liquid surface</td><td>Foundation</td><td><span class="lq-badge lq-badge--success">Ready</span></td><td>4.2K</td></tr><tr><td>Dynamic island</td><td>Navigation</td><td><span class="lq-badge lq-badge--success">Ready</span></td><td>2.8K</td></tr><tr><td>Context menu</td><td>Overlay</td><td><span class="lq-badge lq-badge--warning">Beta</span></td><td>1.4K</td></tr></tbody></table></div></section>
          <section class="catalog-section lq-glass" id="core-feedback"><header><div><h2>Feedback</h2><p>Modal, toast notification, loading, and etched icon states.</p></div><button class="lq-button lq-button--primary" type="button" data-core-toast>${icon('bell')}Show toast</button></header><div class="sample-grid"><article class="sample-box"><span class="sample-label">Modal</span><button class="lq-button" type="button" data-dialog-open="core-modal">Open modal</button></article><article class="sample-box"><span class="sample-label">Spinner</span><span class="lq-spinner"></span><small>Loading material</small></article><article class="sample-box"><span class="sample-label">Etched icons</span><div class="demo-cluster" style="font-size:1.5rem;color:#b6ecff">${icon('shield')}${icon('cloud')}${icon('sparkles')}${icon('activity')}</div></article></div></section>
        </div>
      </div>
      <dialog class="lq-dialog" id="core-modal"><div class="lq-dialog__header"><strong>Welcome to LiquidOS</strong><button class="lq-button lq-icon-button lq-button--ghost" type="button" data-dialog-close>${icon('close')}</button></div><div class="lq-dialog__body"><p style="color:var(--lq-text-soft)">This uses the browser’s native dialog layer with LiquidOS material and focus behavior.</p></div><div class="lq-dialog__footer"><button class="lq-button lq-button--primary" type="button" data-dialog-close>Continue</button></div></dialog>`);
  }

  function advancedLibrary() {
    return page(`${heading('Extended component lab', 'New Liquid Glass Elements', 'The advanced release rebuilt with clearer states, native accessibility, and no external chart or icon dependencies.', `<a class="lq-button" href="index.html">${icon('arrow')} Core library</a><button class="lq-button lq-button--primary" type="button" data-advanced-random>${icon('sparkles')}Randomize</button>`)}
      <div class="demo-grid">
        <article class="demo-card lq-glass span-6"><h3>Global theme controls</h3><p>Switch material density and surface tone across this page.</p><div class="demo-cluster"><label class="lq-switch"><input id="advanced-dark" type="checkbox" checked><span></span></label><span>Dark mode</span><label class="lq-switch"><input id="advanced-frosted" type="checkbox"><span></span></label><span>Extra frost</span></div></article>
        <article class="demo-card lq-glass span-6" data-tabs><h3>Tabs</h3><div class="lq-segmented" role="tablist"><button class="is-active" role="tab" aria-selected="true" aria-controls="advanced-tab-one">Preview</button><button role="tab" aria-selected="false" aria-controls="advanced-tab-two">Details</button><button role="tab" aria-selected="false" aria-controls="advanced-tab-three">History</button></div><div id="advanced-tab-one" role="tabpanel" style="padding-top:18px">Your live material preview is ready.</div><div id="advanced-tab-two" role="tabpanel" hidden style="padding-top:18px">24px blur · 155% saturation · liquid edge.</div><div id="advanced-tab-three" role="tabpanel" hidden style="padding-top:18px">Three local versions saved.</div></article>
        <article class="demo-card lq-glass span-4"><h3>Checkbox and radio</h3><div style="display:grid;gap:12px"><label class="lq-check"><input type="checkbox" checked>Glass highlights</label><label class="lq-radio"><input type="radio" name="advanced-density" checked>Comfortable</label><label class="lq-radio"><input type="radio" name="advanced-density">Compact</label></div></article>
        <article class="demo-card lq-glass span-4"><h3>Dropdown button</h3><div style="position:relative"><button class="lq-button" type="button" data-dropdown-button>${icon('layers')} Choose layer ${icon('chevron')}</button><div class="lq-glass" data-dropdown-menu hidden style="position:absolute;z-index:4;top:52px;left:0;display:grid;min-width:190px;padding:7px"><button class="lq-button lq-button--ghost" type="button">Surface</button><button class="lq-button lq-button--ghost" type="button">Highlight</button><button class="lq-button lq-button--ghost" type="button">Shadow</button></div></div></article>
        <article class="demo-card lq-glass span-4"><h3>Split button</h3><div class="demo-cluster" style="flex-wrap:nowrap"><button class="lq-button lq-button--primary" type="button" style="border-radius:14px 0 0 14px">Publish</button><button class="lq-button lq-button--primary lq-icon-button" type="button" style="border-radius:0 14px 14px 0">${icon('chevron')}</button></div></article>
        <article class="demo-card lq-glass span-4"><h3>Progress spinner</h3><div class="demo-cluster"><span class="lq-spinner"></span><span><strong>Rendering</strong><small style="display:block;color:var(--lq-text-faint)">Compositing layer 4 of 6</small></span></div></article>
        <article class="demo-card lq-glass span-4"><h3>Analog clock</h3><div class="analog-clock" data-advanced-clock style="margin:auto"><span class="clock-hand" data-clock-hand="hour" style="--hand-height:25px"></span><span class="clock-hand" data-clock-hand="minute" style="--hand-height:36px"></span><span class="clock-hand" data-clock-hand="second" style="--hand-height:41px;--hand-color:#ff6f91"></span></div></article>
        <article class="demo-card lq-glass span-4"><h3>Animated counter</h3><strong style="display:block;margin-top:28px;font-size:3.5rem;letter-spacing:-.07em" data-counter="2487">0</strong><small style="color:var(--lq-text-faint)">Active components</small></article>
        <article class="demo-card lq-glass span-8"><h3>Animated bar and line graph</h3>${chart('M0 175C33 161 68 172 104 125s63 9 105-14 67 29 106-25 69-25 104-9 67-42 121-34')}</article>
        <article class="demo-card lq-glass span-4"><h3>Pricing table</h3><div style="display:grid;gap:8px"><div class="lq-glass lq-panel"><span class="lq-badge">Starter</span><strong style="display:block;margin-top:12px;font-size:2rem">$29</strong><small>12 components</small></div><div class="lq-glass lq-glass--tint lq-panel"><span class="lq-badge lq-badge--success">Pro</span><strong style="display:block;margin-top:12px;font-size:2rem">$79</strong><small>Complete system</small></div></div></article>
        <article class="demo-card lq-glass span-6"><h3>Animated progress</h3><div style="display:grid;gap:17px"><div><div class="demo-cluster" style="justify-content:space-between"><span>Foundation</span><small>96%</small></div><div class="lq-progress"><span style="--lq-progress:96%"></span></div></div><div><div class="demo-cluster" style="justify-content:space-between"><span>Components</span><small>84%</small></div><div class="lq-progress"><span style="--lq-progress:84%"></span></div></div><div><div class="demo-cluster" style="justify-content:space-between"><span>Demos</span><small>100%</small></div><div class="lq-progress"><span style="--lq-progress:100%"></span></div></div></div></article>
        <article class="demo-card lq-glass span-6"><h3>Syntax highlighting</h3><pre style="overflow:auto;margin:0;padding:18px;border-radius:15px;background:rgba(0,0,0,.25);color:#d9ecff;font:500 .73rem/1.7 ui-monospace,monospace"><code><span style="color:#ff88c4">const</span> material = <span style="color:#ffe095">'liquid'</span>;
<span style="color:#86d7ff">applyGlass</span>({
  blur: <span style="color:#9ff0c4">24</span>,
  motion: <span style="color:#9ff0c4">true</span>
});</code></pre></article>
        <article class="demo-card lq-glass span-6"><h3>Etched typography</h3><div style="display:grid;gap:5px;text-shadow:0 1px 0 rgba(255,255,255,.2),0 -1px 0 rgba(0,0,0,.5)"><strong style="font-size:2.7rem;letter-spacing:-.06em">Heading 1</strong><strong style="font-size:1.8rem;letter-spacing:-.04em">Heading 2</strong><strong style="font-size:1.2rem">Heading 3</strong></div></article>
        <article class="demo-card lq-glass span-6"><h3>Glass overlay</h3><div style="position:relative;min-height:190px;overflow:hidden;border-radius:17px;background:linear-gradient(135deg,#2147bd,#9c3fc1,#ed6b7f)"><div class="lq-glass lq-glass--liquid lq-panel" style="position:absolute;inset:38px">Layered over a scene</div></div></article>
        <article class="demo-card lq-glass span-6"><h3>Context menu</h3><div class="context-zone" data-advanced-context>Right-click or long-press this zone</div></article>
        <article class="demo-card lq-glass span-6"><h3>Animated text</h3><strong style="display:block;margin-top:32px;font-size:clamp(2rem,5vw,4.5rem);letter-spacing:-.07em" data-typed-text></strong><small style="color:var(--lq-text-faint)">Replays automatically</small></article>
      </div>
      <div class="context-menu" data-advanced-context-menu role="menu"><button type="button">${icon('copy')}Copy</button><button type="button">${icon('edit')}Edit</button><button type="button">${icon('trash')}Remove</button></div>`);
  }

  function iosComponents() {
    return page(`${heading('System component library', 'LiquidOS Controls', 'The original iOS-inspired catalog preserved and reorganized into seven clear chapters with stronger interactions.', `<a class="lq-button" href="index_2.html">Advanced catalog</a><button class="lq-button lq-button--primary" type="button" data-ios-toast>${icon('bell')}Test notification</button>`)}
      <div class="catalog-layout">
        <nav class="catalog-sidebar lq-glass" aria-label="System component chapters"><button class="is-active" type="button" data-catalog-jump="ios-system">${icon('smartphone')}System UI</button><button type="button" data-catalog-jump="ios-inputs">${icon('sliders')}Inputs</button><button type="button" data-catalog-jump="ios-media">${icon('image')}Media</button><button type="button" data-catalog-jump="ios-data">${icon('database')}Data</button><button type="button" data-catalog-jump="ios-social">${icon('message')}Social</button><button type="button" data-catalog-jump="ios-nav">${icon('compass')}Navigation</button><button type="button" data-catalog-jump="ios-gems">${icon('sparkles')}Gems</button></nav>
        <div class="catalog-content">
          <section class="catalog-section lq-glass" id="ios-system"><header><div><h2>1. System UI and dynamic elements</h2><p>Dynamic island, call state, and compact notifications.</p></div><span class="lq-badge">Adaptive</span></header><div class="sample-grid sample-grid--two"><article class="sample-box"><span class="sample-label">Dynamic island</span><button class="island" type="button" data-island><span class="island-cover"></span><span class="row-copy"><strong>Prismatic Flow</strong><small>LiquidOS Studio</small></span>${icon('activity')}</button></article><article class="sample-box"><span class="sample-label">Call state</span><div class="island is-expanded"><span class="lq-avatar">M</span><span class="row-copy"><strong>Maya Chen</strong><small>Connected · 04:18</small></span><button class="lq-button lq-icon-button lq-button--danger" type="button">${icon('phone')}</button></div></article></div></section>
          <section class="catalog-section lq-glass" id="ios-inputs"><header><div><h2>2. Advanced inputs and controls</h2><p>Segmented views, passcode, accent, quantity, drop zone, and filters.</p></div><span class="lq-badge">Form ready</span></header><div class="sample-grid"><article class="sample-box"><span class="sample-label">View mode</span><div class="lq-segmented" data-ios-segmented><button class="is-active" type="button">Day</button><button type="button">Week</button><button type="button">Month</button></div></article><article class="sample-box"><span class="sample-label">Passcode</span><div class="otp-group" data-otp><input class="lq-field" inputmode="numeric" maxlength="1"><input class="lq-field" inputmode="numeric" maxlength="1"><input class="lq-field" inputmode="numeric" maxlength="1"><input class="lq-field" inputmode="numeric" maxlength="1"></div></article><article class="sample-box"><span class="sample-label">Accent color</span><div class="demo-cluster"><button class="lq-button lq-icon-button" style="background:#8b7cff" data-accent="#8b7cff" type="button"></button><button class="lq-button lq-icon-button" style="background:#51d7ff" data-accent="#51d7ff" type="button"></button><button class="lq-button lq-icon-button" style="background:#ff6f91" data-accent="#ff6f91" type="button"></button></div></article></div><div class="sample-grid sample-grid--two" style="margin-top:10px"><article class="sample-box"><span class="sample-label">Quantity</span><div class="demo-cluster"><button class="lq-button lq-icon-button" type="button" data-qty="-1">${icon('minus')}</button><strong style="font-size:1.8rem" id="ios-qty">1</strong><button class="lq-button lq-icon-button lq-button--primary" type="button" data-qty="1">${icon('plus')}</button></div></article><article class="sample-box"><span class="sample-label">Drop files</span><button class="lq-button" type="button" data-upload-demo>${icon('upload')}Drop files here</button><small id="ios-upload-status" style="color:var(--lq-text-faint)">PNG, SVG, WEBP up to 10 MB</small></article></div></section>
          <section class="catalog-section lq-glass" id="ios-media"><header><div><h2>3. Media and rich content</h2><p>Liquid gallery, audio playback, collaborators, and expandable art.</p></div><span class="lq-badge">Gesture ready</span></header><div class="gallery" data-gallery><div class="gallery-track"><div class="gallery-slide" style="--slide-bg:linear-gradient(145deg,#174f97,#7a3fc2,#ed6095)"></div><div class="gallery-slide" style="--slide-bg:linear-gradient(145deg,#083c5e,#098b8a,#77d9a0)"></div><div class="gallery-slide" style="--slide-bg:linear-gradient(145deg,#3d184d,#bf426c,#f1a04e)"></div></div><button class="gallery-control gallery-control--prev" type="button" data-gallery-prev>${icon('arrow')}</button><button class="gallery-control gallery-control--next" type="button" data-gallery-next>${icon('arrow')}</button></div><div class="sample-grid sample-grid--two" style="margin-top:10px"><article class="sample-box sample-box--left"><span class="sample-label">Liquid vibes</span><div class="demo-cluster"><button class="lq-button lq-icon-button lq-button--primary" type="button" data-audio-toggle>${icon('play')}</button><span class="row-copy"><strong>Chromatic Surface</strong><small>03:42 · LiquidOS Audio</small></span></div><div class="lq-progress"><span id="audio-progress" style="--lq-progress:22%"></span></div></article><article class="sample-box"><span class="sample-label">Collaborators</span><div class="lq-avatar-stack"><span class="lq-avatar">A</span><span class="lq-avatar" style="background:linear-gradient(135deg,#ff6f91,#ffb86c)">B</span><span class="lq-avatar" style="background:linear-gradient(135deg,#61e4a0,#51d7ff)">C</span><span class="lq-avatar">+8</span></div><button class="lq-button" type="button">Invite people</button></article></div></section>
          <section class="catalog-section lq-glass" id="ios-data"><header><div><h2>4. Data and utilities</h2><p>Storage, calendar, activity, and compact visualization.</p></div><span class="lq-badge lq-badge--success">Synced</span></header><div class="sample-grid sample-grid--two"><article class="sample-box"><span class="sample-label">Storage</span><div class="donut" style="--donut:72%"><strong>72%</strong><small>184 GB used</small></div></article><article class="sample-box sample-box--left"><span class="sample-label">Calendar</span><div class="calendar-grid" id="ios-calendar"></div></article></div><div class="lq-table-wrap" style="margin-top:10px"><table class="lq-table"><thead><tr><th>Recent activity</th><th>Owner</th><th>State</th><th>Time</th></tr></thead><tbody><tr><td>Glass tokens updated</td><td>Alex</td><td><span class="lq-badge lq-badge--success">Synced</span></td><td>Now</td></tr><tr><td>Motion preview exported</td><td>Maya</td><td><span class="lq-badge">Ready</span></td><td>8m</td></tr><tr><td>Theme audit</td><td>Devon</td><td><span class="lq-badge lq-badge--warning">Review</span></td><td>1h</td></tr></tbody></table></div></section>
          <section class="catalog-section lq-glass" id="ios-social"><header><div><h2>5. Social and messaging</h2><p>Chat, profile, follow state, and rating.</p></div><span class="lq-badge">Realtime</span></header><div class="sample-grid sample-grid--two"><article class="sample-box sample-box--left"><span class="sample-label">Messages</span><div class="chat-window" id="ios-chat"><div class="chat-message">The new glass tokens are ready.</div><div class="chat-message chat-message--out">Perfect. I’m reviewing them now.</div></div><div class="chat-compose"><input class="lq-field" id="ios-chat-input" placeholder="Message"><button class="lq-button lq-icon-button lq-button--primary" type="button" data-chat-send>${icon('send')}</button></div></article><article class="sample-box"><span class="sample-label">Profile</span><span class="lq-avatar" style="width:78px;height:78px;font-size:1.2rem">AD</span><strong>Alex Designer</strong><small style="color:var(--lq-text-faint)">Product designer · New York</small><button class="lq-button lq-button--primary" type="button" data-follow>Follow profile</button><div class="demo-cluster" data-rating><button class="lq-button lq-icon-button lq-button--ghost" type="button">${icon('star')}</button><button class="lq-button lq-icon-button lq-button--ghost" type="button">${icon('star')}</button><button class="lq-button lq-icon-button lq-button--ghost" type="button">${icon('star')}</button><button class="lq-button lq-icon-button lq-button--ghost" type="button">${icon('star')}</button><button class="lq-button lq-icon-button lq-button--ghost" type="button">${icon('star')}</button></div></article></div></section>
          <section class="catalog-section lq-glass" id="ios-nav"><header><div><h2>6. Navigation and layouts</h2><p>Bottom bar, orbit actions, pagination, and adaptable layout controls.</p></div><span class="lq-badge">Touch friendly</span></header><div class="sample-grid sample-grid--two"><article class="sample-box"><span class="sample-label">Bottom navigation</span><div class="lq-segmented" data-ios-nav><button class="is-active" type="button">${icon('home')} Home</button><button type="button">${icon('search')} Search</button><button type="button">${icon('bell')} Alerts</button><button type="button">${icon('user')} Profile</button></div></article><article class="sample-box"><span class="sample-label">Orbit menu</span><div class="orbit-menu" data-orbit><button class="orbit-main" type="button">${icon('plus')}</button><button class="orbit-action" type="button">${icon('heart')}</button><button class="orbit-action" type="button">${icon('send')}</button><button class="orbit-action" type="button">${icon('image')}</button><button class="orbit-action" type="button">${icon('file')}</button></div></article></div></section>
          <section class="catalog-section lq-glass" id="ios-gems"><header><div><h2>7. Miscellaneous gems</h2><p>Accordion, loading, QR-style marker, and status.</p></div><span class="lq-badge">Utility</span></header><div class="sample-grid"><article class="sample-box"><span class="sample-label">Loading state</span><span class="lq-spinner"></span><div class="lq-progress" style="width:100%"><span style="--lq-progress:64%"></span></div></article><article class="sample-box sample-box--left"><span class="sample-label">Accordion</span><button class="lq-button" type="button" data-accordion>How the glass works ${icon('chevron')}</button><p data-accordion-panel hidden>Backdrop blur, subtle color, edge highlights, and a pointer-reactive sheen create the material.</p></article><article class="sample-box"><span class="sample-label">QR marker</span><div style="display:grid;grid-template-columns:repeat(5,14px);gap:3px;padding:15px;border-radius:15px;background:#fff" data-qr></div><small>LiquidOS / components</small></article></div></section>
        </div>
      </div>`);
  }

  function adminDashboard() {
    const content = `<div class="demo-grid">
      ${metric('Net revenue', '$84.2K', '+12.8% from last month', 'wallet')}
      ${metric('Active customers', '2,487', '+183 this period', 'user')}
      ${metric('Conversion', '7.42%', '+0.86 percentage points', 'activity')}
      ${metric('Open orders', '148', '23 require review', 'database')}
      <article class="demo-card lq-glass span-8"><div class="demo-cluster" style="justify-content:space-between"><div><h3>Sales overview</h3><p>Revenue and order volume across the last 12 months.</p></div><div class="lq-segmented" data-admin-range><button type="button">7D</button><button class="is-active" type="button">12M</button><button type="button">All</button></div></div>${chart()}</article>
      <article class="demo-card lq-glass span-4"><h3>Traffic sources</h3><p>Qualified visits by acquisition channel.</p><div class="donut" style="--donut:68%;margin:24px auto"><strong>68%</strong><small>Organic</small></div><div class="demo-cluster" style="justify-content:center"><span class="lq-tag">Organic 68%</span><span class="lq-tag">Direct 21%</span><span class="lq-tag">Social 11%</span></div></article>
      <article class="demo-card lq-glass span-12"><div class="demo-cluster" style="justify-content:space-between;margin-bottom:16px"><div><h3>Recent orders</h3><p>Live operational queue.</p></div><button class="lq-button" type="button" data-admin-export>${icon('download')}Export</button></div><div class="lq-table-wrap"><table class="lq-table"><thead><tr><th>Order</th><th>Customer</th><th>Product</th><th>Total</th><th>Status</th></tr></thead><tbody data-admin-orders><tr><td>#LG-4208</td><td>Maya Chen</td><td>Pro UI license</td><td>$79.00</td><td><span class="lq-badge lq-badge--success">Completed</span></td></tr><tr><td>#LG-4207</td><td>Marcus Hill</td><td>Studio license</td><td>$149.00</td><td><span class="lq-badge lq-badge--warning">Review</span></td></tr><tr><td>#LG-4206</td><td>Ava Patel</td><td>Starter kit</td><td>$29.00</td><td><span class="lq-badge">Processing</span></td></tr><tr><td>#LG-4205</td><td>Noah Williams</td><td>Agency license</td><td>$249.00</td><td><span class="lq-badge lq-badge--success">Completed</span></td></tr></tbody></table></div></article>
    </div>`;
    return page(appShell({ brand: 'Liquid Admin', logoIcon: 'chart', title: 'Welcome back, Admin', subtitle: 'Friday, August 21 · Workspace synchronized', user: 'Alex Morgan', role: 'Operations admin', initials: 'AM', nav: [{ label: 'Dashboard', icon: 'grid' }, { label: 'Analytics', icon: 'chart' }, { label: 'Products', icon: 'layers' }, { label: 'Customers', icon: 'user' }, { label: 'Settings', icon: 'settings' }], content }));
  }

  function calculatorDemo() {
    return page(`<div class="calculator-wrap"><section class="calculator lq-glass lq-glass--liquid" aria-label="Liquid calculator"><div class="calculator-display"><span class="calculator-history" id="calculator-history"></span><strong class="calculator-value" id="calculator-value">0</strong></div><div class="calculator-grid" id="calculator-grid"><button class="calculator-key calculator-key--operator" type="button" data-calc-action="clear">AC</button><button class="calculator-key calculator-key--operator" type="button" data-calc-action="backspace">⌫</button><button class="calculator-key calculator-key--operator" type="button" data-calc-value="%">%</button><button class="calculator-key calculator-key--operator" type="button" data-calc-value="/">÷</button><button class="calculator-key" type="button" data-calc-value="7">7</button><button class="calculator-key" type="button" data-calc-value="8">8</button><button class="calculator-key" type="button" data-calc-value="9">9</button><button class="calculator-key calculator-key--operator" type="button" data-calc-value="*">×</button><button class="calculator-key" type="button" data-calc-value="4">4</button><button class="calculator-key" type="button" data-calc-value="5">5</button><button class="calculator-key" type="button" data-calc-value="6">6</button><button class="calculator-key calculator-key--operator" type="button" data-calc-value="-">−</button><button class="calculator-key" type="button" data-calc-value="1">1</button><button class="calculator-key" type="button" data-calc-value="2">2</button><button class="calculator-key" type="button" data-calc-value="3">3</button><button class="calculator-key calculator-key--operator" type="button" data-calc-value="+">+</button><button class="calculator-key calculator-key--wide" type="button" data-calc-value="0">0</button><button class="calculator-key" type="button" data-calc-value=".">.</button><button class="calculator-key calculator-key--equals" type="button" data-calc-action="equals">=</button></div></section></div>`);
  }

  function quoteCalculator() {
    return page(`${heading('Interactive project estimator', 'Website Quote Generator', 'Choose project scope, features, design complexity, and page count. Every choice updates the transparent estimate.', `<button class="lq-button" type="button" data-quote-reset>${icon('refresh')}Reset</button><button class="lq-button" type="button" data-quote-print>${icon('file')}Print quote</button>`)}
      <div class="quote-layout"><form class="quote-form" id="quote-form">
        <section class="quote-step lq-glass"><div class="quote-step__title"><span class="quote-step__number">1</span><strong>Project type</strong></div><div class="choice-grid"><label class="choice-card"><input type="checkbox" name="projectType" value="New website" data-cost="2000"><strong>New website</strong><small>Strategy and build · $2,000</small></label><label class="choice-card"><input type="checkbox" name="projectType" value="Redesign" data-cost="1500"><strong>Redesign</strong><small>Refresh existing site · $1,500</small></label><label class="choice-card"><input type="checkbox" name="projectType" value="E-commerce" data-cost="5000"><strong>E-commerce</strong><small>Store and checkout · $5,000</small></label><label class="choice-card"><input type="checkbox" name="projectType" value="Web application" data-cost="8000"><strong>Web application</strong><small>Custom platform · $8,000</small></label></div></section>
        <section class="quote-step lq-glass"><div class="quote-step__title"><span class="quote-step__number">2</span><strong>Add features</strong></div><div class="choice-grid"><label class="choice-card"><input type="checkbox" name="feature" value="Content management" data-cost="1200"><strong>Content management</strong><small>Editor workflows · $1,200</small></label><label class="choice-card"><input type="checkbox" name="feature" value="User accounts" data-cost="1800"><strong>User accounts</strong><small>Authentication · $1,800</small></label><label class="choice-card"><input type="checkbox" name="feature" value="API integration" data-cost="2500"><strong>API integration</strong><small>Third-party services · $2,500</small></label><label class="choice-card"><input type="checkbox" name="feature" value="Database" data-cost="2000"><strong>Database</strong><small>Structured data · $2,000</small></label></div></section>
        <section class="quote-step lq-glass"><div class="quote-step__title"><span class="quote-step__number">3</span><strong>Design complexity</strong></div><div class="choice-grid"><label class="choice-card"><input type="radio" name="design" value="Simple" data-multiplier="1" checked><strong>Simple</strong><small>Clean foundation · 1×</small></label><label class="choice-card"><input type="radio" name="design" value="Custom" data-multiplier="1.5"><strong>Custom</strong><small>Distinct visual system · 1.5×</small></label><label class="choice-card"><input type="radio" name="design" value="Immersive" data-multiplier="2.5"><strong>Immersive</strong><small>Advanced motion · 2.5×</small></label></div></section>
        <section class="quote-step lq-glass"><div class="quote-step__title"><span class="quote-step__number">4</span><strong>Number of pages</strong></div><div class="builder-control-row"><label for="quote-pages"><span>Pages</span><output id="quote-pages-output">10 pages</output></label><input class="lq-range" id="quote-pages" type="range" min="1" max="50" value="10" data-cost="150"></div></section>
      </form><aside class="quote-result lq-glass lq-glass--liquid"><span class="lq-badge lq-badge--success">Live estimate</span><div class="quote-total"><small>Estimated project</small><strong id="quote-total">$1,500</strong></div><div><strong style="font-size:.82rem">Quote breakdown</strong><ul class="quote-breakdown" id="quote-breakdown"></ul></div><button class="lq-button lq-button--primary" type="button" data-quote-generate>${icon('sparkles')}Generate proposal</button><small style="color:var(--lq-text-faint)">Illustrative estimate. Final scope may change after discovery.</small></aside></div>`);
  }

  function loginDashboard() {
    const dashboardContent = `<div class="demo-grid">${metric('Revenue', '$48.3K', '+14.2% this month', 'wallet')}${metric('Sales', '1,204', '+89 this week', 'chart')}${metric('Customers', '3,819', '96% retention', 'user')}${metric('Satisfaction', '4.92', 'From 830 reviews', 'star')}<article class="demo-card lq-glass span-8"><h3>Sales overview</h3>${chart()}</article><article class="demo-card lq-glass span-4"><h3>Traffic sources</h3><div class="donut" style="--donut:74%;margin:20px auto"><strong>74%</strong><small>Organic</small></div></article></div>`;
    return `${backChrome()}<canvas id="demo-ambient" aria-hidden="true"></canvas><section class="auth-stage"><div class="auth-visual"><div class="auth-visual__copy"><span class="demo-kicker">Secure workspace</span><h1>Liquid<br>Access.</h1><p>A full transition from authentication into the application shell, without reloading the page.</p></div></div><div class="auth-panel"><form class="auth-form lq-glass lq-panel" id="auth-form"><span class="lq-badge">LiquidOS Identity</span><h2>Welcome back</h2><p>Any valid email and a password of at least four characters will unlock the demo.</p><div class="lq-field-wrap">${icon('mail')}<input class="lq-field" id="auth-email" type="email" placeholder="Email address" required></div><div class="lq-field-wrap">${icon('lock')}<input class="lq-field" id="auth-password" type="password" placeholder="Password" minlength="4" required></div><div class="auth-error" id="auth-error" hidden></div><button class="lq-button lq-button--primary" type="submit" id="auth-submit">${icon('lock')}Sign in securely</button><div class="demo-cluster" style="justify-content:space-between"><label class="lq-check"><input type="checkbox" checked>Remember this device</label><button class="lq-button lq-button--ghost" type="button">Forgot password?</button></div></form></div></section><main class="demo-page auth-dashboard">${appShell({ brand: 'Liquid Workspace', logoIcon: 'shield', title: 'Dashboard', subtitle: 'Secure session active · Synchronized now', user: 'Demo User', role: 'Workspace admin', initials: 'DU', nav: [{ label: 'Dashboard', icon: 'grid' }, { label: 'Analytics', icon: 'chart' }, { label: 'Projects', icon: 'folder' }, { label: 'Team', icon: 'user' }], content: `${dashboardContent}<div style="margin-top:13px"><button class="lq-button lq-button--danger" type="button" data-logout>${icon('power')}Log out</button></div>` })}</main>`;
  }

  function smartHome() {
    return page(`<div class="home-layout"><nav class="home-rail"><span class="app-logo__mark">${icon('home')}</span><button class="is-active" type="button">${icon('home')}</button><button type="button">${icon('thermostat')}</button><button type="button">${icon('activity')}</button><button type="button">${icon('settings')}</button><button type="button" style="margin-top:auto" data-home-power>${icon('power')}</button></nav><main class="home-main"><div class="demo-heading"><div class="demo-heading__copy"><span class="demo-kicker">Friday, August 21</span><h1>Good evening, Dave.</h1><p>Your home is comfortable and running 12% below its energy target.</p></div><div class="demo-cluster"><span class="lq-badge lq-badge--success">Home secure</span><span class="lq-badge" id="home-time">8:42 PM</span></div></div><div class="scene-strip" data-scenes><button class="scene-card is-active" type="button" data-scene="Focus" style="--scene-bg:linear-gradient(145deg,#173e76,#7950c6)"><span>Focus</span></button><button class="scene-card" type="button" data-scene="Cinema" style="--scene-bg:linear-gradient(145deg,#2e183f,#a33a74)"><span>Cinema</span></button><button class="scene-card" type="button" data-scene="Sunset" style="--scene-bg:linear-gradient(145deg,#5e2930,#e27947,#f4c766)"><span>Sunset</span></button></div><div class="demo-grid" style="margin-top:13px"><section class="demo-card lq-glass span-7 temperature"><div><span class="demo-kicker">Living room climate</span><div class="temperature-value"><span id="home-temp">72</span><sup>°</sup></div><div class="temp-controls"><button class="lq-button lq-icon-button" type="button" data-temp="-1">${icon('minus')}</button><button class="lq-button lq-icon-button lq-button--primary" type="button" data-temp="1">${icon('plus')}</button></div></div></section><section class="demo-card lq-glass span-5"><div class="demo-cluster" style="justify-content:space-between"><div><h3>Lighting</h3><p id="home-light-count">3 of 4 on</p></div><button class="lq-button lq-button--ghost" type="button" data-all-lights>All off</button></div><div class="light-grid" data-lights><button class="light-card is-on" type="button"><span>${icon('sun')}</span><strong>Living room</strong></button><button class="light-card is-on" type="button"><span>${icon('sun')}</span><strong>Kitchen</strong></button><button class="light-card is-on" type="button"><span>${icon('sun')}</span><strong>Hallway</strong></button><button class="light-card" type="button"><span>${icon('moon')}</span><strong>Bedroom</strong></button></div></section><section class="demo-card lq-glass span-4">${metric('Energy today','18.4','kWh · 12% below target','activity','').replace('demo-card demo-metric lq-glass ', 'demo-metric ')}</section><section class="demo-card lq-glass span-4"><h3>Air quality</h3><strong style="display:block;margin-top:24px;font-size:2.6rem">Excellent</strong><div class="lq-progress" style="margin-top:18px"><span style="--lq-progress:92%"></span></div></section><section class="demo-card lq-glass span-4"><h3>Doors and locks</h3><div class="activity-list"><div class="activity-row"><span class="row-icon">${icon('lock')}</span><span class="row-copy"><strong>Front door</strong><small>Locked 22 min ago</small></span><span class="lq-badge lq-badge--success">Secure</span></div><div class="activity-row"><span class="row-icon">${icon('lock')}</span><span class="row-copy"><strong>Garage</strong><small>Closed</small></span><span class="lq-badge lq-badge--success">Secure</span></div></div></section></div></main></div>`);
  }

  function liquidVault() {
    return page(`${heading('Encrypted workspace', 'Liquid Vault', 'A secure storage interface with fluid capacity, search, file selection, preview, and realistic upload behavior.', `<button class="lq-button" type="button" data-vault-lock>${icon('lock')}Lock vault</button><button class="lq-button lq-button--primary" type="button" data-vault-upload>${icon('upload')}Upload</button>`)}<section class="vault-hero lq-glass lq-glass--liquid"><div><span class="lq-badge lq-badge--success">End-to-end encrypted</span><h1>Capacity<br>in motion.</h1><p style="max-width:540px;color:var(--lq-text-soft)">Your files stay organized inside a calm, layered workspace. Search, inspect, and manage storage without losing context.</p></div><div class="vault-capacity" style="--capacity:68%"><strong>68%</strong><small>312 GB free</small></div></section><div class="demo-grid" style="margin-top:13px"><aside class="demo-card lq-glass span-4"><div class="lq-field-wrap">${icon('search')}<input class="lq-field" id="vault-search" placeholder="Decrypting file index..."></div><nav class="app-nav" style="margin-top:15px"><button class="is-active" type="button">${icon('folder')}All files</button><button type="button">${icon('image')}Images</button><button type="button">${icon('video')}Video</button><button type="button">${icon('file')}Documents</button></nav><div class="file-list" id="vault-files" style="margin-top:18px"><button class="file-row" type="button" data-file="Project_Neon.png"><span class="row-icon">${icon('image')}</span><span class="row-copy"><strong>Project_Neon.png</strong><small>18.6 MB · Today</small></span>${icon('more')}</button><button class="file-row" type="button" data-file="Motion_Study.mp4"><span class="row-icon">${icon('video')}</span><span class="row-copy"><strong>Motion_Study.mp4</strong><small>246 MB · Yesterday</small></span>${icon('more')}</button><button class="file-row" type="button" data-file="Brand_System.pdf"><span class="row-icon">${icon('file')}</span><span class="row-copy"><strong>Brand_System.pdf</strong><small>8.2 MB · Aug 19</small></span>${icon('more')}</button><button class="file-row" type="button" data-file="Ambient_Audio.wav"><span class="row-icon">${icon('music')}</span><span class="row-copy"><strong>Ambient_Audio.wav</strong><small>74 MB · Aug 18</small></span>${icon('more')}</button></div></aside><section class="demo-card lq-glass span-8"><div class="demo-cluster" style="justify-content:space-between;margin-bottom:13px"><div><h3 id="vault-file-title">Project_Neon.png</h3><p id="vault-file-meta">18.6 MB · 3200 × 2400 · Today</p></div><div class="demo-cluster"><button class="lq-button lq-icon-button" type="button">${icon('download')}</button><button class="lq-button lq-icon-button" type="button">${icon('more')}</button></div></div><div class="file-preview"><div class="file-preview__art"></div></div><div class="demo-grid" style="margin-top:12px">${metric('Files','4,281','Across 42 folders','file','span-4')}${metric('Shared','128','With 16 collaborators','user','span-4')}${metric('Available','312 GB','32% capacity remains','database','span-4')}</div></section></div>`);
  }

  function liquidStudio() {
    return page(`<section class="studio-app"><header class="studio-menubar"><div class="app-logo"><span class="app-logo__mark">${icon('paint')}</span><span>Liquid Studio</span></div><div class="demo-actions"><button class="lq-button lq-button--ghost" type="button" data-studio-undo>${icon('undo')}Undo</button><button class="lq-button lq-button--ghost" type="button" data-studio-redo>${icon('redo')}Redo</button><button class="lq-button lq-button--primary" type="button" data-studio-export>${icon('download')}Export</button></div></header><div class="studio-workspace"><nav class="studio-tools" aria-label="Creative tools"><button class="studio-tool is-active" type="button" data-tool="Select">${icon('cursor')}</button><button class="studio-tool" type="button" data-tool="Brush">${icon('edit')}</button><button class="studio-tool" type="button" data-tool="Shape">${icon('layers')}</button><button class="studio-tool" type="button" data-tool="Text">T</button><button class="studio-tool" type="button" data-tool="Image">${icon('image')}</button><button class="studio-tool" type="button" data-tool="Zoom">${icon('zoom')}</button></nav><section class="studio-canvas-wrap"><div class="studio-canvas" id="creative-canvas" aria-label="Creative canvas preview"></div><div class="lq-glass" style="position:absolute;right:15px;bottom:15px;display:flex;align-items:center;gap:8px;padding:7px"><button class="lq-button lq-icon-button lq-button--ghost" type="button" data-zoom="-0.1">${icon('minus')}</button><output id="studio-zoom">100%</output><button class="lq-button lq-icon-button lq-button--ghost" type="button" data-zoom="0.1">${icon('plus')}</button></div></section><aside class="studio-properties"><div class="property-group"><h3>Adjustments</h3><div class="builder-control-row"><label for="studio-brightness"><span>Brightness</span><output id="studio-brightness-output">100%</output></label><input class="lq-range" id="studio-brightness" type="range" min="40" max="160" value="100"></div><div class="builder-control-row"><label for="studio-contrast"><span>Contrast</span><output id="studio-contrast-output">100%</output></label><input class="lq-range" id="studio-contrast" type="range" min="40" max="180" value="100"></div><div class="builder-control-row"><label for="studio-blur"><span>Blur</span><output id="studio-blur-output">0px</output></label><input class="lq-range" id="studio-blur" type="range" min="0" max="12" value="0"></div></div><div class="property-group"><h3>Accent</h3><input class="lq-field" id="studio-accent" type="color" value="#8b7cff"></div><div class="property-group"><h3>Layers</h3><button class="layer-row is-active" type="button">${icon('sparkles')}Liquid object</button><button class="layer-row" type="button">${icon('file')}Typography</button><button class="layer-row" type="button">${icon('image')}Gradient field</button><button class="layer-row" type="button">${icon('grid')}Background</button></div><div class="property-group"><h3>Active tool</h3><strong id="studio-active-tool">Select</strong></div></aside></div></section>`);
  }

  function tradingTerminal() {
    const assets = [['₿','BTC','98,240','+2.84%'],['Ξ','ETH','4,218','+1.12%'],['S','SOL','218.40','-0.62%'],['A','ADA','1.24','+0.18%']];
    const assetRows = assets.map((asset, index) => `<button class="asset-row ${index === 0 ? 'is-active' : ''}" type="button" data-asset="${asset[1]}" data-price="${asset[2]}"><span class="asset-symbol">${asset[0]}</span><span class="row-copy"><strong>${asset[1]} / USD</strong><small>Liquid market</small></span><span class="${asset[3].startsWith('-') ? 'demo-negative' : 'demo-positive'}" style="font-size:.62rem">${asset[3]}</span></button>`).join('');
    const bookRows = Array.from({ length: 10 }, (_, index) => `<div class="book-row ${index < 5 ? 'is-ask' : ''}" style="--book-depth:${35 + (index * 6) % 55}%"><span class="${index < 5 ? 'demo-negative' : 'demo-positive'}">${(98280 - index * 12.4).toFixed(1)}</span><span>${(0.06 + index * 0.013).toFixed(3)}</span><span>${(5.8 + index * 1.7).toFixed(2)}</span></div>`).join('');
    return page(`<section class="finance-layout"><aside class="finance-watchlist"><div class="app-logo"><span class="app-logo__mark">${icon('trade')}</span><span>LiquidFi</span></div><div class="lq-field-wrap" style="margin:18px 0">${icon('search')}<input class="lq-field" placeholder="Markets"></div><div>${assetRows}</div><div style="margin-top:24px"><h3 style="color:var(--lq-text-faint);font-size:.64rem;letter-spacing:.1em;text-transform:uppercase">Portfolio</h3><strong style="display:block;font-size:1.7rem">$128,420</strong><small class="demo-positive">+$4,219 today</small></div></aside><main class="finance-main"><header class="price-head"><div><span class="lq-badge lq-badge--success">Market open</span><strong><span id="trade-symbol">BTC</span> / USD</strong><span class="demo-positive" id="trade-change">+2.84%</span></div><div style="text-align:right"><strong id="trade-price">$98,240</strong><small style="color:var(--lq-text-faint)">24h volume $4.8B</small></div></header><div class="lq-segmented" data-trade-range><button type="button">1H</button><button class="is-active" type="button">1D</button><button type="button">1W</button><button type="button">1M</button></div><div style="margin-top:12px">${chart('M0 180C35 165 58 179 95 144s54 12 88-22 62 36 96-21 57-44 95-17 75-33 166-25')}</div><div class="demo-grid"><article class="demo-card lq-glass span-6"><h3>Order book</h3><div class="book-row" style="color:var(--lq-text-faint)"><span>Price</span><span>Amount</span><span>Total</span></div><div class="order-book">${bookRows}</div></article><article class="demo-card lq-glass span-6"><h3>Recent trades</h3><div class="activity-list">${Array.from({length:6},(_,i)=>`<div class="activity-row"><span class="row-icon">${icon('trade')}</span><span class="row-copy"><strong class="${i%3===0?'demo-negative':'demo-positive'}">$${(98232+i*3.7).toFixed(2)}</strong><small>${(0.02+i*.011).toFixed(3)} BTC</small></span><span class="row-value">${i+1}s</span></div>`).join('')}</div></article></div></main><aside class="finance-order"><div class="demo-cluster" style="justify-content:space-between"><strong>Place order</strong><span class="lq-badge">Spot</span></div><div class="order-tabs"><button class="is-active" type="button" data-side="buy">Buy</button><button type="button" data-side="sell">Sell</button></div><label class="lq-label">Order type<select class="lq-select"><option>Market</option><option>Limit</option><option>Stop</option></select></label><label class="lq-label" style="margin-top:12px">Price<input class="lq-field" id="order-price" value="98240.00" inputmode="decimal"></label><label class="lq-label" style="margin-top:12px">Amount<input class="lq-field" id="order-amount" value="0.15" inputmode="decimal"></label><input class="lq-range" id="order-percent" type="range" value="25" style="margin-top:13px"><div class="demo-cluster" style="justify-content:space-between;margin-top:10px"><small style="color:var(--lq-text-faint)">Estimated total</small><strong id="order-total">$14,736.00</strong></div><button class="lq-button lq-button--primary" id="order-submit" type="button" style="width:100%;margin-top:18px;background:linear-gradient(135deg,#23b879,#61e4a0);color:#03120b">Buy BTC</button><h3 style="margin-top:28px;color:var(--lq-text-faint);font-size:.64rem;letter-spacing:.1em;text-transform:uppercase">Market depth</h3><div class="order-book">${bookRows.slice(0,6)}</div></aside></section>`);
  }

  function gamingDashboard() {
    const games = [
      ['Apex Rivals','linear-gradient(145deg,#1e3b67,#d84d6d)'],['Neon Drift','linear-gradient(145deg,#0b3f50,#35a4aa)'],['Star Forge','linear-gradient(145deg,#30205f,#8d4cc0)'],['Elden Core','linear-gradient(145deg,#463315,#c78d32)']
    ];
    return page(`<section class="gaming-shell"><nav class="gaming-rail"><span class="app-logo__mark">${icon('gamepad')}</span><button class="studio-tool is-active" type="button">${icon('home')}</button><button class="studio-tool" type="button">${icon('grid')}</button><button class="studio-tool" type="button">${icon('user')}</button><button class="studio-tool" type="button">${icon('settings')}</button><button class="studio-tool" type="button" style="margin-top:auto">${icon('power')}</button></nav><main class="gaming-content"><div class="app-topbar"><div class="app-title"><h1>Cloud Library</h1><p id="gaming-status">4 games ready · Controller connected</p></div><div class="demo-cluster"><div class="lq-field-wrap app-search">${icon('search')}<input class="lq-field" id="game-search" placeholder="Search library"></div><span class="lq-avatar">LU</span></div></div><section class="game-hero"><span class="lq-badge">Featured campaign</span><h1>CYBER<br>ODYSSEY</h1><p>Return to Helix City. Your last checkpoint is synchronized across every device.</p><div class="demo-actions"><button class="lq-button lq-button--primary" type="button" data-game-play>${icon('play')}Continue</button><button class="lq-button" type="button">${icon('more')}Details</button></div></section><div class="demo-cluster" style="justify-content:space-between;margin:22px 0 10px"><strong>Quick resume</strong><button class="lq-button lq-button--ghost" type="button">View all</button></div><div class="game-strip" id="game-strip">${games.map((game,index)=>`<button class="game-card ${index===0?'is-active':''}" type="button" data-game="${game[0]}" style="--game-bg:${game[1]}"><strong>${game[0]}</strong></button>`).join('')}</div><div class="demo-grid" style="margin-top:13px"><article class="demo-card lq-glass span-8"><h3>Online friends</h3><div class="friends-list"><div class="friend-row"><span class="lq-avatar">M</span><span class="row-copy"><strong>MayaFlux</strong><small>Playing Neon Drift</small></span><span class="lq-badge lq-badge--success">Join</span></div><div class="friend-row"><span class="lq-avatar" style="background:linear-gradient(135deg,#ff6f91,#ffb86c)">K</span><span class="row-copy"><strong>KodaZero</strong><small>In menus</small></span><span class="lq-badge">Online</span></div><div class="friend-row"><span class="lq-avatar" style="background:linear-gradient(135deg,#61e4a0,#51d7ff)">R</span><span class="row-copy"><strong>RunePilot</strong><small>Star Forge</small></span><span class="lq-badge lq-badge--success">Join</span></div></div></article><article class="demo-card lq-glass span-4"><h3>System performance</h3><div style="display:grid;gap:15px"><div><div class="demo-cluster" style="justify-content:space-between"><span>GPU</span><small>72%</small></div><div class="lq-progress"><span style="--lq-progress:72%"></span></div></div><div><div class="demo-cluster" style="justify-content:space-between"><span>Network</span><small>18 ms</small></div><div class="lq-progress"><span style="--lq-progress:84%"></span></div></div><div><div class="demo-cluster" style="justify-content:space-between"><span>Storage</span><small>61%</small></div><div class="lq-progress"><span style="--lq-progress:61%"></span></div></div></div></article></div></main></section>`);
  }

  function droneTerminal() {
    const telemetry = [['ALTITUDE','124.8 m'],['VELOCITY','18.2 m/s'],['HEADING','047° NE'],['BATTERY','84%'],['SIGNAL','-42 dBm'],['WIND','6.4 km/h'],['GPS','12 satellites'],['MODE','AUTONOMOUS']];
    return page(`<section class="drone-shell"><header class="drone-header"><div class="app-logo"><span class="app-logo__mark" style="background:rgba(117,209,120,.12);color:#75d178">${icon('drone')}</span><span>SPECTRE _01</span></div><div class="demo-cluster"><span class="lq-badge lq-badge--success">UPLINK STABLE</span><span class="lq-badge" id="drone-time">00:00:00 UTC</span><button class="lq-button lq-button--danger" type="button" data-drone-abort>ABORT</button></div></header><div class="drone-grid"><aside class="drone-panel"><h3>Telemetry</h3><div class="telemetry-list">${telemetry.map(row=>`<div class="telemetry-row"><span>${row[0]}</span><strong>${row[1]}</strong></div>`).join('')}</div><h3 style="margin-top:24px">Flight controls</h3><div class="demo-grid" style="gap:6px"><button class="lq-button lq-icon-button span-4" type="button" data-drone-control="Ascend">${icon('plus')}</button><button class="lq-button lq-icon-button span-4" type="button" data-drone-control="Forward">↑</button><button class="lq-button lq-icon-button span-4" type="button" data-drone-control="Descend">${icon('minus')}</button><button class="lq-button lq-icon-button span-4" type="button" data-drone-control="Left">←</button><button class="lq-button lq-icon-button span-4" type="button" data-drone-control="Hover">●</button><button class="lq-button lq-icon-button span-4" type="button" data-drone-control="Right">→</button></div></aside><main class="drone-map"><span class="drone-target drone-target--one">T1</span><span class="drone-target drone-target--two">T2</span><div class="drone-core">${icon('drone')}</div><div class="lq-glass" style="position:absolute;left:14px;bottom:14px;padding:10px 12px;font-size:.65rem"><strong>HUDSON SECTOR</strong><br><span style="color:rgba(217,255,224,.48)">41.7004° N · 73.9210° W</span></div></main><aside class="drone-panel"><h3>Mission feed</h3><div class="command-feed" id="command-feed"><div class="command-line"><strong>00:00:01</strong> Uplink established</div><div class="command-line"><strong>00:00:04</strong> Waypoint grid loaded</div><div class="command-line"><strong>00:00:08</strong> Autonomous mode active</div><div class="command-line"><strong>00:00:12</strong> Tracking two targets</div></div><div class="command-input"><input class="lq-field" id="drone-command" placeholder="Enter command"><button class="lq-button lq-icon-button" type="button" data-drone-send>${icon('send')}</button></div><h3 style="margin-top:24px">System</h3><div class="telemetry-list"><div class="telemetry-row"><span>CAMERA</span><strong class="demo-positive">ONLINE</strong></div><div class="telemetry-row"><span>LIDAR</span><strong class="demo-positive">ONLINE</strong></div><div class="telemetry-row"><span>THERMAL</span><strong class="demo-positive">ONLINE</strong></div><div class="telemetry-row"><span>PAYLOAD</span><strong>2.4 KG</strong></div></div></aside></div></section>`);
  }

  function menuStudy() {
    return `${backChrome()}<main class="menu-study" id="menu-study"><div class="menu-study__intro"><span class="demo-kicker">Navigation motion study</span><h1>Liquid<br>Menu.</h1><p>Open the control to watch each layer arrive with spring timing, blur, focus trapping, and Escape-key support.</p><button class="menu-study__trigger" id="study-trigger" type="button" aria-expanded="false" aria-controls="study-overlay">${icon('plus')}</button></div><div class="study-overlay" id="study-overlay" aria-hidden="true"><nav class="study-nav"><a href="#surface"><span>Surface</span>${icon('arrow')}</a><a href="#motion"><span>Motion</span>${icon('arrow')}</a><a href="#system"><span>System</span>${icon('arrow')}</a><a href="#about"><span>About</span>${icon('arrow')}</a></nav></div></main>`;
  }

  function organicLiquid() {
    return `${backChrome()}<main class="organic-stage"><canvas id="organic-canvas" aria-label="Interactive organic liquid simulation"></canvas><div class="organic-copy"><h1>Organic<br>Liquid.</h1><p>Move to attract · press to create · double-click to burst</p></div><div class="organic-hint">Dependency-free Canvas 2D field · reduced-motion aware · touch enabled</div></main>`;
  }

  function introSequence() {
    const title = 'LIQUIDOS';
    return `${backChrome()}<main class="intro-stage" id="intro-stage"><div class="intro-orb"></div><section class="intro-panel lq-glass lq-glass--liquid"><div style="display:grid;justify-items:center;gap:25px"><span class="intro-logo">${icon('sparkles')}</span><h1 class="intro-title" aria-label="LiquidOS">${[...title].map((letter,index)=>`<span style="--letter:${index}">${letter}</span>`).join('')}</h1><p class="intro-subtitle">A clearer, faster, more expressive interface system.</p><button class="lq-button lq-button--primary lq-button--pill" id="intro-replay" type="button">${icon('play')}Replay sequence</button></div></section></main>`;
  }

  function effectsPlayground() {
    return page(`${heading('Guided material showcase', 'Effects Playground', 'A cleaner replacement for the original ease-of-use demo: compare materials, interact with working components, and copy complete recipes.', `<button class="lq-button lq-button--primary" type="button" data-effects-copy-all>${icon('copy')}Copy all recipes</button>`)}<div class="effects-grid"><article class="effect-sample lq-glass lq-glass--liquid" style="--effect-scene:linear-gradient(145deg,#214ed5,#8b38cf,#ef5b8f)"><span class="effect-sample__orb"></span><span class="lq-badge">Liquid</span><h2>Distorted glass</h2><p>Pointer-reactive sheen, concentrated edge, and restrained body color.</p><button class="lq-button" type="button" data-effect-copy="liquid">${icon('copy')}Copy liquid CSS</button></article><article class="effect-sample lq-glass lq-glass--frosted" style="--effect-scene:linear-gradient(145deg,#075376,#15a092,#8bd98b)"><span class="effect-sample__orb"></span><span class="lq-badge">Frosted</span><h2>Frosted surface</h2><p>High diffusion for panels that need readable content over busy scenes.</p><button class="lq-button" type="button" data-effect-copy="frosted">${icon('copy')}Copy frosted CSS</button></article><article class="effect-sample lq-glass lq-glass--tint" style="--effect-scene:linear-gradient(145deg,#31164d,#a43d92,#ed745f)"><span class="effect-sample__orb"></span><span class="lq-badge">Tinted</span><h2>Spectral tint</h2><p>Color depth that preserves legibility and ambient scene context.</p><button class="lq-button" type="button" data-effect-copy="tinted">${icon('copy')}Copy tinted CSS</button></article><article class="effect-sample lq-glass lq-glass--clear" style="--effect-scene:linear-gradient(145deg,#233145,#68738f,#b0bed4)"><span class="effect-sample__orb"></span><span class="lq-badge">Clear</span><h2>Clear lens</h2><p>Minimal body, crisp highlight, and subtle optical separation.</p><button class="lq-button" type="button" data-effect-copy="clear">${icon('copy')}Copy clear CSS</button></article></div><section class="catalog-section lq-glass" style="margin-top:13px"><header><div><h2>Working component samples</h2><p>Login, calculator, metrics, and search retained from the earlier guide.</p></div><span class="lq-badge lq-badge--success">Functional</span></header><div class="sample-grid"><article class="sample-box sample-box--left"><span class="sample-label">Login</span><input class="lq-field" type="email" placeholder="Email"><input class="lq-field" type="password" placeholder="Password"><button class="lq-button lq-button--primary" type="button" data-effects-login>Sign in</button></article><article class="sample-box"><span class="sample-label">Calculator</span><strong style="font-size:2.8rem" id="effects-calc-value">42</strong><div class="demo-cluster"><button class="lq-button lq-icon-button" type="button" data-effects-calc="-1">${icon('minus')}</button><button class="lq-button lq-icon-button" type="button" data-effects-calc="1">${icon('plus')}</button></div></article><article class="sample-box sample-box--left"><span class="sample-label">Search</span><div class="lq-field-wrap">${icon('search')}<input class="lq-field" placeholder="Search components"></div><div class="demo-cluster"><span class="lq-tag">Button</span><span class="lq-tag">Card</span><span class="lq-tag">Input</span></div></article></div></section>`);
  }

  const templates = {
    components: componentLibrary,
    advanced: advancedLibrary,
    ios: iosComponents,
    admin: adminDashboard,
    calculator: calculatorDemo,
    quote: quoteCalculator,
    login: loginDashboard,
    home: smartHome,
    vault: liquidVault,
    studio: liquidStudio,
    trading: tradingTerminal,
    gaming: gamingDashboard,
    drone: droneTerminal,
    menu: menuStudy,
    organic: organicLiquid,
    intro: introSequence,
    effects: effectsPlayground
  };

  function initAppShell() {
    document.querySelectorAll('[data-app-menu]').forEach((button) => button.addEventListener('click', () => document.getElementById('app-shell')?.classList.toggle('menu-open')));
    document.querySelectorAll('[data-app-nav]').forEach((button) => button.addEventListener('click', () => {
      const nav = button.closest('.app-nav');
      nav?.querySelectorAll('[data-app-nav]').forEach((item) => item.classList.toggle('is-active', item === button));
      document.getElementById('app-shell')?.classList.remove('menu-open');
      LQ.toast(button.textContent.trim(), 'Demo section selected.');
    }));
    document.querySelectorAll('[data-app-notify]').forEach((button) => button.addEventListener('click', () => LQ.toast('You’re all caught up', 'No new workspace alerts.')));
    document.querySelectorAll('[data-app-settings]').forEach((button) => button.addEventListener('click', () => LQ.toast('Settings', 'Appearance and workspace preferences are ready.')));
  }

  function initCatalog() {
    document.querySelectorAll('[data-catalog-jump]').forEach((button) => button.addEventListener('click', () => {
      const target = document.getElementById(button.dataset.catalogJump);
      button.closest('.catalog-sidebar')?.querySelectorAll('button').forEach((item) => item.classList.toggle('is-active', item === button));
      target?.scrollIntoView({ behavior: LQ.reducedMotion ? 'auto' : 'smooth', block: 'start' });
    }));
  }

  function initKnob(knob) {
    if (!knob) return;
    const setValue = (value) => {
      const normalized = Math.max(0, Math.min(100, Math.round(value)));
      knob.style.setProperty('--knob-angle', `${normalized * 2.64}deg`);
      knob.setAttribute('aria-valuenow', normalized);
      knob.querySelector('span').textContent = `${normalized}%`;
    };
    const pointerValue = (event) => {
      const rect = knob.getBoundingClientRect();
      const x = event.clientX - rect.left - rect.width / 2;
      const y = event.clientY - rect.top - rect.height / 2;
      let angle = Math.atan2(y, x) * 180 / Math.PI + 90;
      if (angle < 0) angle += 360;
      if (angle > 264) angle = angle > 312 ? 0 : 264;
      setValue(angle / 2.64);
    };
    setValue(Number(knob.getAttribute('aria-valuenow') || 50));
    knob.addEventListener('pointerdown', (event) => { knob.setPointerCapture(event.pointerId); pointerValue(event); });
    knob.addEventListener('pointermove', (event) => { if (knob.hasPointerCapture(event.pointerId)) pointerValue(event); });
    knob.addEventListener('keydown', (event) => {
      if (!['ArrowUp', 'ArrowRight', 'ArrowDown', 'ArrowLeft'].includes(event.key)) return;
      event.preventDefault();
      setValue(Number(knob.getAttribute('aria-valuenow')) + (['ArrowUp', 'ArrowRight'].includes(event.key) ? 2 : -2));
    });
  }

  function updateClocks() {
    document.querySelectorAll('[data-advanced-clock]').forEach((clock) => {
      const now = new Date();
      const angles = { hour: (now.getHours() % 12) * 30 + now.getMinutes() / 2, minute: now.getMinutes() * 6 + now.getSeconds() / 10, second: now.getSeconds() * 6 };
      Object.entries(angles).forEach(([key, value]) => clock.querySelector(`[data-clock-hand="${key}"]`)?.style.setProperty('--hand-angle', `${value}deg`));
    });
  }

  function initKeyboard(keyboard) {
    if (!keyboard) return;
    keyboard.addEventListener('click', (event) => {
      const key = event.target.closest('button');
      if (!key) return;
      key.classList.add('is-pressed');
      setTimeout(() => key.classList.remove('is-pressed'), 130);
    });
    document.addEventListener('keydown', (event) => {
      if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) return;
      const label = event.code === 'Space' ? 'Space' : event.key.toUpperCase();
      const key = [...keyboard.querySelectorAll('button')].find((item) => item.textContent === label);
      if (!key) return;
      key.classList.add('is-pressed');
      setTimeout(() => key.classList.remove('is-pressed'), 130);
    });
  }

  function initComponentsDemo() {
    initCatalog();
    document.querySelectorAll('.demo-flip').forEach((card) => card.addEventListener('click', () => card.classList.toggle('is-flipped')));
    const range = document.getElementById('core-progress-range');
    range?.addEventListener('input', () => document.getElementById('core-progress').style.setProperty('--lq-progress', `${range.value}%`));
    initKnob(document.querySelector('.demo-knob'));
    initKeyboard(document.querySelector('[data-demo-keyboard]'));
    document.querySelector('[data-mini-login]')?.addEventListener('click', () => LQ.toast('Demo sign-in complete', 'The component validated successfully.'));
    document.querySelector('[data-core-toast]')?.addEventListener('click', () => LQ.toast('Liquid notification', 'The component is fully interactive.'));
    const countdown = document.getElementById('core-countdown');
    let seconds = 4 * 3600 + 18 * 60 + 32;
    setInterval(() => {
      seconds = Math.max(0, seconds - 1);
      const h = String(Math.floor(seconds / 3600)).padStart(2, '0');
      const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
      const s = String(seconds % 60).padStart(2, '0');
      if (countdown) countdown.textContent = `${h}:${m}:${s}`;
    }, 1000);
  }

  function initAdvancedDemo() {
    const darkToggle = document.getElementById('advanced-dark');
    const frostToggle = document.getElementById('advanced-frosted');
    darkToggle?.addEventListener('change', () => document.body.classList.toggle('demo-light', !darkToggle.checked));
    frostToggle?.addEventListener('change', () => document.querySelectorAll('.demo-card').forEach((card) => card.classList.toggle('lq-glass--frosted', frostToggle.checked)));
    document.querySelector('[data-dropdown-button]')?.addEventListener('click', () => {
      const dropdown = document.querySelector('[data-dropdown-menu]');
      dropdown.hidden = !dropdown.hidden;
    });
    document.addEventListener('click', (event) => {
      if (event.target.closest('[data-dropdown-button], [data-dropdown-menu]')) return;
      const dropdown = document.querySelector('[data-dropdown-menu]');
      if (dropdown) dropdown.hidden = true;
    });
    const counter = document.querySelector('[data-counter]');
    if (counter) {
      const target = Number(counter.dataset.counter);
      const start = performance.now();
      const animate = (time) => {
        const progress = Math.min(1, (time - start) / 1300);
        counter.textContent = Math.round(target * (1 - Math.pow(1 - progress, 3))).toLocaleString();
        if (progress < 1) requestAnimationFrame(animate);
      };
      requestAnimationFrame(animate);
    }
    updateClocks();
    setInterval(updateClocks, 1000);
    const contextZone = document.querySelector('[data-advanced-context]');
    const contextMenu = document.querySelector('[data-advanced-context-menu]');
    const showContext = (x, y) => {
      contextMenu.style.left = `${Math.min(x, innerWidth - 195)}px`;
      contextMenu.style.top = `${Math.min(y, innerHeight - 150)}px`;
      contextMenu.classList.add('is-open');
    };
    contextZone?.addEventListener('contextmenu', (event) => { event.preventDefault(); showContext(event.clientX, event.clientY); });
    contextMenu?.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      LQ.toast(button.textContent.trim(), 'Context action completed.');
      contextMenu.classList.remove('is-open');
    });
    document.addEventListener('pointerdown', (event) => { if (!event.target.closest('[data-advanced-context-menu]')) contextMenu?.classList.remove('is-open'); });
    const typed = document.querySelector('[data-typed-text]');
    const phrases = ['Designed to flow.', 'Built to respond.', 'Ready to ship.'];
    let phraseIndex = 0;
    let letterIndex = 0;
    let deleting = false;
    const type = () => {
      const phrase = phrases[phraseIndex];
      letterIndex += deleting ? -1 : 1;
      typed.textContent = phrase.slice(0, Math.max(0, letterIndex));
      let delay = deleting ? 35 : 62;
      if (!deleting && letterIndex === phrase.length) { deleting = true; delay = 1250; }
      else if (deleting && letterIndex === 0) { deleting = false; phraseIndex = (phraseIndex + 1) % phrases.length; delay = 300; }
      setTimeout(type, delay);
    };
    type();
    document.querySelector('[data-advanced-random]')?.addEventListener('click', () => {
      const accents = [['#8b7cff','#51d7ff'],['#ff6f91','#ffcf70'],['#61e4a0','#51d7ff'],['#9d66f2','#f56eb3']];
      const pair = accents[Math.floor(Math.random() * accents.length)];
      document.documentElement.style.setProperty('--demo-accent', pair[0]);
      document.documentElement.style.setProperty('--demo-accent-2', pair[1]);
      LQ.toast('Theme randomized', 'Every component inherited the new tokens.', { icon: 'sparkles' });
    });
  }

  function initIosDemo() {
    initCatalog();
    document.querySelector('[data-island]')?.addEventListener('click', (event) => event.currentTarget.classList.toggle('is-expanded'));
    document.querySelectorAll('[data-ios-segmented], [data-ios-nav]').forEach((group) => group.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      group.querySelectorAll('button').forEach((item) => item.classList.toggle('is-active', item === button));
    }));
    const otp = [...document.querySelectorAll('[data-otp] input')];
    otp.forEach((field, index) => {
      field.addEventListener('input', () => { field.value = field.value.replace(/\D/g, '').slice(0, 1); if (field.value) otp[index + 1]?.focus(); });
      field.addEventListener('keydown', (event) => { if (event.key === 'Backspace' && !field.value) otp[index - 1]?.focus(); });
      field.addEventListener('paste', (event) => {
        event.preventDefault();
        [...event.clipboardData.getData('text').replace(/\D/g, '').slice(0, 4)].forEach((value, pasteIndex) => { if (otp[pasteIndex]) otp[pasteIndex].value = value; });
        otp[Math.min(3, event.clipboardData.getData('text').length - 1)]?.focus();
      });
    });
    document.querySelectorAll('[data-accent]').forEach((button) => button.addEventListener('click', () => {
      document.documentElement.style.setProperty('--demo-accent', button.dataset.accent);
      LQ.toast('Accent changed', button.dataset.accent);
    }));
    let quantity = 1;
    document.querySelectorAll('[data-qty]').forEach((button) => button.addEventListener('click', () => {
      quantity = Math.max(1, Math.min(99, quantity + Number(button.dataset.qty)));
      document.getElementById('ios-qty').textContent = quantity;
    }));
    document.querySelector('[data-upload-demo]')?.addEventListener('click', () => {
      const status = document.getElementById('ios-upload-status');
      status.textContent = 'Uploading material-preview.webp…';
      setTimeout(() => { status.textContent = 'material-preview.webp · Ready'; LQ.toast('Upload complete', 'The demo file is available.', { icon: 'upload' }); }, 850);
    });
    let slide = 0;
    const gallery = document.querySelector('[data-gallery]');
    const updateSlide = () => gallery?.querySelector('.gallery-track').style.setProperty('--slide', slide);
    document.querySelector('[data-gallery-prev]')?.addEventListener('click', () => { slide = (slide + 2) % 3; updateSlide(); });
    document.querySelector('[data-gallery-next]')?.addEventListener('click', () => { slide = (slide + 1) % 3; updateSlide(); });
    let playing = false;
    let audioProgress = 22;
    let audioTimer = 0;
    document.querySelector('[data-audio-toggle]')?.addEventListener('click', (event) => {
      playing = !playing;
      event.currentTarget.innerHTML = LQ.icon(playing ? 'pause' : 'play');
      clearInterval(audioTimer);
      if (playing) audioTimer = setInterval(() => {
        audioProgress = (audioProgress + 1) % 101;
        document.getElementById('audio-progress').style.setProperty('--lq-progress', `${audioProgress}%`);
      }, 180);
    });
    const calendar = document.getElementById('ios-calendar');
    if (calendar) {
      calendar.innerHTML = ['M','T','W','T','F','S','S'].map((day) => `<span>${day}</span>`).join('') + Array.from({ length: 35 }, (_, index) => `<button type="button" ${index === 18 ? 'class="is-selected"' : ''}>${index + 1 <= 31 ? index + 1 : ''}</button>`).join('');
      calendar.addEventListener('click', (event) => {
        const button = event.target.closest('button');
        if (!button?.textContent) return;
        calendar.querySelectorAll('button').forEach((item) => item.classList.toggle('is-selected', item === button));
      });
    }
    const chatInput = document.getElementById('ios-chat-input');
    const sendChat = () => {
      const value = chatInput.value.trim();
      if (!value) return;
      const message = document.createElement('div');
      message.className = 'chat-message chat-message--out';
      message.textContent = value;
      document.getElementById('ios-chat').appendChild(message);
      chatInput.value = '';
    };
    document.querySelector('[data-chat-send]')?.addEventListener('click', sendChat);
    chatInput?.addEventListener('keydown', (event) => { if (event.key === 'Enter') sendChat(); });
    document.querySelector('[data-follow]')?.addEventListener('click', (event) => {
      event.currentTarget.classList.toggle('lq-button--primary');
      event.currentTarget.textContent = event.currentTarget.classList.contains('lq-button--primary') ? 'Following' : 'Follow profile';
    });
    document.querySelector('[data-rating]')?.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      const buttons = [...event.currentTarget.querySelectorAll('button')];
      buttons.forEach((item, index) => item.style.color = index <= buttons.indexOf(button) ? '#ffcf70' : '');
    });
    document.querySelector('[data-orbit] .orbit-main')?.addEventListener('click', (event) => event.currentTarget.closest('[data-orbit]').classList.toggle('is-open'));
    document.querySelector('[data-accordion]')?.addEventListener('click', () => {
      const panel = document.querySelector('[data-accordion-panel]');
      panel.hidden = !panel.hidden;
    });
    const qr = document.querySelector('[data-qr]');
    if (qr) qr.innerHTML = Array.from({length:25},(_,index)=>`<i style="width:14px;height:14px;background:${[0,1,4,5,6,8,10,12,14,16,18,19,20,23,24].includes(index)?'#0a0d18':'transparent'}"></i>`).join('');
    document.querySelector('[data-ios-toast]')?.addEventListener('click', () => LQ.toast('System notification', 'Every interaction is running locally.'));
  }

  function downloadText(name, text, type = 'text/plain') {
    const blob = new Blob([text], { type });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function initAdminDemo() {
    initAppShell();
    document.querySelector('[data-admin-range]')?.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      event.currentTarget.querySelectorAll('button').forEach((item) => item.classList.toggle('is-active', item === button));
      LQ.toast(`Range: ${button.textContent}`, 'Analytics view updated.');
    });
    document.querySelector('[data-admin-export]')?.addEventListener('click', () => {
      downloadText('liquidos-orders.csv', 'Order,Customer,Product,Total,Status\nLG-4208,Maya Chen,Pro UI license,79.00,Completed\nLG-4207,Marcus Hill,Studio license,149.00,Review\nLG-4206,Ava Patel,Starter kit,29.00,Processing', 'text/csv');
      LQ.toast('Orders exported', 'The CSV download is ready.', { icon: 'download' });
    });
    const search = document.querySelector('[data-app-search]');
    search?.addEventListener('input', () => {
      const query = search.value.toLowerCase();
      document.querySelectorAll('[data-admin-orders] tr').forEach((row) => row.hidden = !row.textContent.toLowerCase().includes(query));
    });
  }

  function initCalculator() {
    const display = document.getElementById('calculator-value');
    const history = document.getElementById('calculator-history');
    const grid = document.getElementById('calculator-grid');
    let current = '0';
    let previous = null;
    let operator = null;
    let overwrite = false;

    const symbol = (value) => ({ '*': '×', '/': '÷', '-': '−', '+': '+' })[value] || value;
    const render = () => {
      display.textContent = current;
      history.textContent = previous !== null && operator ? `${previous} ${symbol(operator)}` : '';
    };
    const calculate = () => {
      if (previous === null || !operator) return;
      const a = Number(previous);
      const b = Number(current);
      let result = b;
      if (operator === '+') result = a + b;
      if (operator === '-') result = a - b;
      if (operator === '*') result = a * b;
      if (operator === '/') result = b === 0 ? NaN : a / b;
      history.textContent = `${previous} ${symbol(operator)} ${current} =`;
      current = Number.isFinite(result) ? String(Number(result.toFixed(10))) : 'Error';
      previous = null;
      operator = null;
      overwrite = true;
    };
    const inputValue = (value) => {
      if (['+', '-', '*', '/'].includes(value)) {
        if (operator && previous !== null && !overwrite) calculate();
        previous = current === 'Error' ? '0' : current;
        operator = value;
        overwrite = true;
      } else if (value === '%') {
        current = String(Number(current) / 100);
      } else if (value === '.') {
        if (overwrite || current === 'Error') { current = '0.'; overwrite = false; }
        else if (!current.includes('.')) current += '.';
      } else {
        if (overwrite || current === '0' || current === 'Error') { current = value; overwrite = false; }
        else if (current.length < 14) current += value;
      }
      render();
    };
    const handle = (value, action) => {
      if (action === 'clear') { current = '0'; previous = null; operator = null; overwrite = false; history.textContent = ''; }
      else if (action === 'backspace') current = current.length > 1 && current !== 'Error' ? current.slice(0, -1) : '0';
      else if (action === 'equals') calculate();
      else if (value) inputValue(value);
      render();
    };
    grid.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      handle(button.dataset.calcValue, button.dataset.calcAction);
    });
    document.addEventListener('keydown', (event) => {
      if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) return;
      const keyMap = { Enter: ['','equals'], '=': ['','equals'], Escape: ['','clear'], Backspace: ['','backspace'] };
      if (/^[0-9.+\-*/%]$/.test(event.key)) handle(event.key, '');
      else if (keyMap[event.key]) handle(...keyMap[event.key]);
      else return;
      event.preventDefault();
      const matching = [...grid.querySelectorAll('button')].find((button) => button.dataset.calcValue === event.key || button.dataset.calcAction === keyMap[event.key]?.[1]);
      matching?.classList.add('is-pressed');
      setTimeout(() => matching?.classList.remove('is-pressed'), 120);
    });
    render();
  }

  function initQuote() {
    const form = document.getElementById('quote-form');
    const pages = document.getElementById('quote-pages');
    const total = document.getElementById('quote-total');
    const breakdown = document.getElementById('quote-breakdown');
    const calculate = () => {
      const selected = [...form.querySelectorAll('input[type="checkbox"]:checked')];
      const design = form.querySelector('input[name="design"]:checked');
      const multiplier = Number(design.dataset.multiplier);
      const base = selected.reduce((sum, input) => sum + Number(input.dataset.cost), 0);
      const pageCost = Number(pages.value) * Number(pages.dataset.cost);
      const finalTotal = Math.round(base * multiplier + pageCost);
      document.getElementById('quote-pages-output').textContent = `${pages.value} page${pages.value === '1' ? '' : 's'}`;
      total.textContent = finalTotal.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
      const lines = selected.map((input) => `<li><span>${LQ.escapeHtml(input.value)}</span><strong>$${Number(input.dataset.cost).toLocaleString()}</strong></li>`);
      lines.push(`<li><span>${LQ.escapeHtml(design.value)} design (${multiplier}×)</span><strong>${multiplier.toFixed(1)}×</strong></li>`);
      lines.push(`<li><span>${pages.value} pages</span><strong>$${pageCost.toLocaleString()}</strong></li>`);
      breakdown.innerHTML = lines.join('');
    };
    form.addEventListener('change', calculate);
    pages.addEventListener('input', calculate);
    document.querySelector('[data-quote-reset]')?.addEventListener('click', () => { form.reset(); pages.value = 10; calculate(); LQ.toast('Estimate reset', 'The default project is restored.', { icon: 'refresh' }); });
    document.querySelector('[data-quote-print]')?.addEventListener('click', () => window.print());
    document.querySelector('[data-quote-generate]')?.addEventListener('click', () => LQ.toast('Proposal generated', `${total.textContent} estimate is ready to review.`, { icon: 'file' }));
    calculate();
  }

  function initLogin() {
    initAppShell();
    const form = document.getElementById('auth-form');
    const email = document.getElementById('auth-email');
    const password = document.getElementById('auth-password');
    const error = document.getElementById('auth-error');
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (!email.validity.valid || password.value.length < 4) {
        error.hidden = false;
        error.textContent = 'Enter a valid email and a password of at least four characters.';
        return;
      }
      error.hidden = true;
      const button = document.getElementById('auth-submit');
      button.disabled = true;
      button.innerHTML = `${LQ.icon('activity')} Verifying…`;
      setTimeout(() => { document.body.classList.add('authenticated'); window.scrollTo(0, 0); LQ.toast('Welcome back', 'Your secure workspace is ready.', { icon: 'shield' }); }, 720);
    });
    document.querySelector('[data-logout]')?.addEventListener('click', () => {
      document.body.classList.remove('authenticated');
      form.reset();
      const button = document.getElementById('auth-submit');
      button.disabled = false;
      button.innerHTML = `${LQ.icon('lock')} Sign in securely`;
      window.scrollTo(0, 0);
    });
  }

  function initHome() {
    let temperature = 72;
    const temp = document.getElementById('home-temp');
    document.querySelectorAll('[data-temp]').forEach((button) => button.addEventListener('click', () => {
      temperature = Math.max(60, Math.min(82, temperature + Number(button.dataset.temp)));
      temp.textContent = temperature;
      LQ.toast('Climate updated', `Living room set to ${temperature}°.`);
    }));
    const lights = [...document.querySelectorAll('[data-lights] .light-card')];
    const updateCount = () => {
      const count = lights.filter((light) => light.classList.contains('is-on')).length;
      document.getElementById('home-light-count').textContent = `${count} of ${lights.length} on`;
      document.querySelector('[data-all-lights]').textContent = count ? 'All off' : 'All on';
    };
    lights.forEach((light) => light.addEventListener('click', () => { light.classList.toggle('is-on'); updateCount(); }));
    document.querySelector('[data-all-lights]')?.addEventListener('click', () => {
      const anyOn = lights.some((light) => light.classList.contains('is-on'));
      lights.forEach((light) => light.classList.toggle('is-on', !anyOn));
      updateCount();
    });
    document.querySelector('[data-scenes]')?.addEventListener('click', (event) => {
      const scene = event.target.closest('[data-scene]');
      if (!scene) return;
      document.querySelectorAll('[data-scene]').forEach((item) => item.classList.toggle('is-active', item === scene));
      LQ.toast(`${scene.dataset.scene} scene`, 'Lighting and climate settings applied.', { icon: 'home' });
    });
    document.querySelector('[data-home-power]')?.addEventListener('click', () => LQ.toast('Away mode enabled', 'Lights off, doors secured, climate reduced.', { icon: 'shield' }));
    const clock = document.getElementById('home-time');
    const updateClock = () => clock.textContent = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    updateClock();
    setInterval(updateClock, 30000);
    updateCount();
  }

  function initVault() {
    const search = document.getElementById('vault-search');
    search?.addEventListener('input', () => {
      const query = search.value.toLowerCase();
      document.querySelectorAll('#vault-files [data-file]').forEach((file) => file.hidden = !file.dataset.file.toLowerCase().includes(query));
    });
    document.getElementById('vault-files')?.addEventListener('click', (event) => {
      const file = event.target.closest('[data-file]');
      if (!file) return;
      document.getElementById('vault-file-title').textContent = file.dataset.file;
      document.getElementById('vault-file-meta').textContent = file.querySelector('small').textContent;
      document.querySelector('.file-preview').style.filter = `hue-rotate(${Math.floor(Math.random() * 220)}deg)`;
    });
    document.querySelector('[data-vault-upload]')?.addEventListener('click', () => {
      LQ.toast('Encrypting upload', 'Preparing design-export.zip…', { icon: 'upload' });
      setTimeout(() => LQ.toast('Upload complete', 'design-export.zip is secured.', { icon: 'shield' }), 1000);
    });
    document.querySelector('[data-vault-lock]')?.addEventListener('click', () => LQ.toast('Vault locked', 'Biometric unlock is required to continue.', { icon: 'lock' }));
  }

  function initStudio() {
    const canvas = document.getElementById('creative-canvas');
    let zoom = 1;
    const apply = () => {
      const brightness = document.getElementById('studio-brightness').value;
      const contrast = document.getElementById('studio-contrast').value;
      const blur = document.getElementById('studio-blur').value;
      canvas.style.setProperty('--canvas-brightness', brightness / 100);
      canvas.style.setProperty('--canvas-contrast', contrast / 100);
      canvas.style.setProperty('--canvas-blur', `${blur}px`);
      canvas.style.setProperty('--canvas-zoom', zoom);
      document.getElementById('studio-brightness-output').textContent = `${brightness}%`;
      document.getElementById('studio-contrast-output').textContent = `${contrast}%`;
      document.getElementById('studio-blur-output').textContent = `${blur}px`;
      document.getElementById('studio-zoom').textContent = `${Math.round(zoom * 100)}%`;
    };
    ['brightness', 'contrast', 'blur'].forEach((name) => document.getElementById(`studio-${name}`).addEventListener('input', apply));
    document.querySelectorAll('[data-zoom]').forEach((button) => button.addEventListener('click', () => { zoom = Math.max(.5, Math.min(1.5, zoom + Number(button.dataset.zoom))); apply(); }));
    document.querySelectorAll('[data-tool]').forEach((tool) => tool.addEventListener('click', () => {
      document.querySelectorAll('[data-tool]').forEach((item) => item.classList.toggle('is-active', item === tool));
      document.getElementById('studio-active-tool').textContent = tool.dataset.tool;
    }));
    document.querySelectorAll('.layer-row').forEach((layer) => layer.addEventListener('click', () => document.querySelectorAll('.layer-row').forEach((item) => item.classList.toggle('is-active', item === layer))));
    document.getElementById('studio-accent').addEventListener('input', (event) => {
      document.documentElement.style.setProperty('--demo-accent', event.target.value);
      canvas.style.background = `linear-gradient(145deg,#123c71,${event.target.value} 48%,#e54f8d 76%,#f2aa5a)`;
    });
    document.querySelector('[data-studio-undo]')?.addEventListener('click', () => LQ.toast('Undo', 'Last adjustment reverted.', { icon: 'undo' }));
    document.querySelector('[data-studio-redo]')?.addEventListener('click', () => LQ.toast('Redo', 'Adjustment restored.', { icon: 'redo' }));
    document.querySelector('[data-studio-export]')?.addEventListener('click', () => {
      downloadText('liquidos-studio-export.svg', `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 900"><defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="#123c71"/><stop offset=".5" stop-color="#8b7cff"/><stop offset="1" stop-color="#e54f8d"/></linearGradient></defs><rect width="1200" height="900" fill="url(#g)"/><text x="650" y="760" fill="white" font-size="92" font-family="sans-serif" font-weight="700">LIQUID / 03</text></svg>`, 'image/svg+xml');
      LQ.toast('Artwork exported', 'The SVG is ready.', { icon: 'download' });
    });
    apply();
  }

  function initTrading() {
    const priceField = document.getElementById('order-price');
    const amountField = document.getElementById('order-amount');
    const total = document.getElementById('order-total');
    let side = 'buy';
    let symbol = 'BTC';
    const updateOrder = () => {
      const value = Number(String(priceField.value).replace(/,/g, '')) * Number(amountField.value || 0);
      total.textContent = Number.isFinite(value) ? value.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) : '$0.00';
      const submit = document.getElementById('order-submit');
      submit.textContent = `${side === 'buy' ? 'Buy' : 'Sell'} ${symbol}`;
      submit.style.background = side === 'buy' ? 'linear-gradient(135deg,#23b879,#61e4a0)' : 'linear-gradient(135deg,#e94c72,#ff8da6)';
      submit.style.color = side === 'buy' ? '#03120b' : '#fff';
    };
    document.querySelectorAll('.asset-row').forEach((row) => row.addEventListener('click', () => {
      document.querySelectorAll('.asset-row').forEach((item) => item.classList.toggle('is-active', item === row));
      symbol = row.dataset.asset;
      document.getElementById('trade-symbol').textContent = symbol;
      document.getElementById('trade-price').textContent = `$${row.dataset.price}`;
      priceField.value = row.dataset.price.replace(/,/g, '');
      updateOrder();
    }));
    document.querySelector('.order-tabs')?.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      side = button.dataset.side;
      event.currentTarget.querySelectorAll('button').forEach((item) => item.classList.toggle('is-active', item === button));
      updateOrder();
    });
    priceField.addEventListener('input', updateOrder);
    amountField.addEventListener('input', updateOrder);
    document.getElementById('order-percent').addEventListener('input', (event) => { amountField.value = (event.target.value / 100 * .6).toFixed(3); updateOrder(); });
    document.getElementById('order-submit').addEventListener('click', () => LQ.toast(`${side === 'buy' ? 'Buy' : 'Sell'} order staged`, `${amountField.value} ${symbol} at market.`, { icon: 'trade' }));
    document.querySelector('[data-trade-range]')?.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      event.currentTarget.querySelectorAll('button').forEach((item) => item.classList.toggle('is-active', item === button));
    });
    let livePrice = 98240;
    setInterval(() => {
      livePrice += (Math.random() - .48) * 18;
      if (symbol === 'BTC') document.getElementById('trade-price').textContent = livePrice.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
    }, 1800);
    updateOrder();
  }

  function initGaming() {
    const search = document.getElementById('game-search');
    search?.addEventListener('input', () => {
      const query = search.value.toLowerCase();
      document.querySelectorAll('[data-game]').forEach((game) => game.hidden = !game.dataset.game.toLowerCase().includes(query));
    });
    document.getElementById('game-strip')?.addEventListener('click', (event) => {
      const game = event.target.closest('[data-game]');
      if (!game) return;
      document.querySelectorAll('[data-game]').forEach((item) => item.classList.toggle('is-active', item === game));
      document.getElementById('gaming-status').textContent = `${game.dataset.game} selected · Cloud save ready`;
    });
    document.querySelector('[data-game-play]')?.addEventListener('click', (event) => {
      event.currentTarget.innerHTML = `${LQ.icon('activity')} Launching…`;
      setTimeout(() => { event.currentTarget.innerHTML = `${LQ.icon('pause')} Running`; LQ.toast('Cyber Odyssey launched', 'Cloud session connected.', { icon: 'gamepad' }); }, 800);
    });
  }

  function initDrone() {
    const clock = document.getElementById('drone-time');
    const updateClock = () => clock.textContent = `${new Date().toISOString().slice(11, 19)} UTC`;
    updateClock();
    setInterval(updateClock, 1000);
    const feed = document.getElementById('command-feed');
    const addLine = (text, warning = false) => {
      const line = document.createElement('div');
      line.className = 'command-line';
      line.innerHTML = `<strong style="${warning ? 'color:#ff7f96' : ''}">${new Date().toISOString().slice(11, 19)}</strong> ${LQ.escapeHtml(text)}`;
      feed.appendChild(line);
      feed.scrollTop = feed.scrollHeight;
    };
    document.querySelectorAll('[data-drone-control]').forEach((button) => button.addEventListener('click', () => addLine(`${button.dataset.droneControl.toUpperCase()} command acknowledged`)));
    const input = document.getElementById('drone-command');
    const send = () => {
      const value = input.value.trim();
      if (!value) return;
      addLine(`CMD > ${value}`);
      input.value = '';
    };
    document.querySelector('[data-drone-send]')?.addEventListener('click', send);
    input.addEventListener('keydown', (event) => { if (event.key === 'Enter') send(); });
    document.querySelector('[data-drone-abort]')?.addEventListener('click', () => { addLine('MISSION ABORT REQUESTED · RETURNING HOME', true); LQ.toast('Abort sequence active', 'Spectre is returning to launch point.', { icon: 'shield' }); });
  }

  function initMenuStudy() {
    const stage = document.getElementById('menu-study');
    const trigger = document.getElementById('study-trigger');
    const overlay = document.getElementById('study-overlay');
    const setOpen = (open) => {
      stage.classList.toggle('is-open', open);
      trigger.setAttribute('aria-expanded', String(open));
      overlay.setAttribute('aria-hidden', String(!open));
      document.body.style.overflow = open ? 'hidden' : '';
      if (open) setTimeout(() => overlay.querySelector('a')?.focus(), 300);
    };
    trigger.addEventListener('click', () => setOpen(!stage.classList.contains('is-open')));
    overlay.querySelectorAll('a').forEach((link) => link.addEventListener('click', (event) => { event.preventDefault(); LQ.toast(link.textContent.trim(), 'Navigation selection captured.'); setOpen(false); }));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') setOpen(false);
      if (event.key !== 'Tab' || !stage.classList.contains('is-open')) return;
      const links = [...overlay.querySelectorAll('a')];
      if (event.shiftKey && document.activeElement === links[0]) { event.preventDefault(); links.at(-1).focus(); }
      else if (!event.shiftKey && document.activeElement === links.at(-1)) { event.preventDefault(); links[0].focus(); }
    });
  }

  function initOrganic() {
    const canvas = document.getElementById('organic-canvas');
    const context = canvas.getContext('2d');
    const mask = document.createElement('canvas');
    const maskContext = mask.getContext('2d');
    let width = 0;
    let height = 0;
    let dpr = 1;
    let raf = 0;
    const pointer = { x: 0, y: 0, active: false, down: false };
    const blobs = [];
    const addBlob = (x, y, radius = 32 + Math.random() * 34) => {
      if (blobs.length >= 30) return;
      blobs.push({ x, y, radius, vx: (Math.random() - .5) * .8, vy: (Math.random() - .5) * .8, phase: Math.random() * Math.PI * 2 });
    };
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      dpr = Math.min(2, devicePixelRatio || 1);
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      canvas.width = mask.width = Math.round(width * dpr);
      canvas.height = mask.height = Math.round(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      maskContext.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (!blobs.length) for (let index = 0; index < 11; index += 1) addBlob(width * (.3 + Math.random() * .4), height * (.25 + Math.random() * .5));
    };
    const update = (time) => {
      blobs.forEach((blob, index) => {
        if (pointer.active) {
          const dx = pointer.x - blob.x;
          const dy = pointer.y - blob.y;
          const distance = Math.max(40, Math.hypot(dx, dy));
          const force = (pointer.down ? .08 : .018) / distance;
          blob.vx += dx * force;
          blob.vy += dy * force;
        }
        blob.vx += Math.sin(time * .0004 + blob.phase + index) * .003;
        blob.vy += Math.cos(time * .00035 + blob.phase) * .003;
        blob.vx *= .985;
        blob.vy *= .985;
        blob.x += blob.vx;
        blob.y += blob.vy;
        if (blob.x < -blob.radius) blob.x = width + blob.radius;
        if (blob.x > width + blob.radius) blob.x = -blob.radius;
        if (blob.y < -blob.radius) blob.y = height + blob.radius;
        if (blob.y > height + blob.radius) blob.y = -blob.radius;
      });
    };
    const draw = (time = 0) => {
      update(time);
      maskContext.clearRect(0, 0, width, height);
      maskContext.fillStyle = '#fff';
      blobs.forEach((blob) => { maskContext.beginPath(); maskContext.arc(blob.x, blob.y, blob.radius, 0, Math.PI * 2); maskContext.fill(); });
      context.clearRect(0, 0, width, height);
      context.save();
      context.filter = 'blur(14px) contrast(8)';
      context.globalAlpha = .22;
      context.drawImage(mask, 0, 0, width, height);
      context.restore();
      blobs.forEach((blob) => {
        const gradient = context.createRadialGradient(blob.x - blob.radius * .32, blob.y - blob.radius * .36, 2, blob.x, blob.y, blob.radius);
        gradient.addColorStop(0, 'rgba(255,255,255,.42)');
        gradient.addColorStop(.24, 'rgba(255,255,255,.09)');
        gradient.addColorStop(.72, 'rgba(255,255,255,.035)');
        gradient.addColorStop(1, 'rgba(255,255,255,.22)');
        context.fillStyle = gradient;
        context.strokeStyle = 'rgba(255,255,255,.33)';
        context.lineWidth = 1;
        context.beginPath();
        context.arc(blob.x, blob.y, blob.radius, 0, Math.PI * 2);
        context.fill();
        context.stroke();
      });
      if (!LQ.reducedMotion) raf = requestAnimationFrame(draw);
    };
    const pointerPosition = (event) => {
      const rect = canvas.getBoundingClientRect();
      pointer.x = event.clientX - rect.left;
      pointer.y = event.clientY - rect.top;
      pointer.active = true;
    };
    canvas.addEventListener('pointermove', pointerPosition);
    canvas.addEventListener('pointerdown', (event) => { pointerPosition(event); pointer.down = true; addBlob(pointer.x, pointer.y, 24 + Math.random() * 28); });
    canvas.addEventListener('pointerup', () => pointer.down = false);
    canvas.addEventListener('pointerleave', () => { pointer.active = false; pointer.down = false; });
    canvas.addEventListener('dblclick', (event) => { pointerPosition(event); for (let index = 0; index < 7; index += 1) addBlob(pointer.x + (Math.random() - .5) * 120, pointer.y + (Math.random() - .5) * 120, 18 + Math.random() * 26); });
    addEventListener('resize', resize);
    document.addEventListener('visibilitychange', () => { if (document.hidden) cancelAnimationFrame(raf); else if (!LQ.reducedMotion) raf = requestAnimationFrame(draw); });
    resize();
    draw(0);
  }

  function initIntro() {
    const stage = document.getElementById('intro-stage');
    const replay = document.getElementById('intro-replay');
    const play = () => {
      stage.classList.remove('is-playing');
      void stage.offsetWidth;
      stage.classList.add('is-playing');
    };
    replay.addEventListener('click', play);
    play();
  }

  function initEffects() {
    const snippets = {
      liquid: '.lq-glass--liquid { backdrop-filter: blur(18px) saturate(178%); background: linear-gradient(130deg, rgba(255,255,255,.105), rgba(255,255,255,.022)); }',
      frosted: '.lq-glass--frosted { backdrop-filter: blur(34px) saturate(135%); background: rgba(255,255,255,.12); }',
      tinted: '.lq-glass--tint { background: linear-gradient(140deg, rgba(139,124,255,.18), rgba(81,215,255,.06), rgba(255,111,145,.08)); }',
      clear: '.lq-glass--clear { backdrop-filter: blur(10px); background: rgba(255,255,255,.045); border-color: rgba(255,255,255,.25); }'
    };
    document.querySelectorAll('[data-effect-copy]').forEach((button) => button.addEventListener('click', () => LQ.copyText(snippets[button.dataset.effectCopy], `${button.dataset.effectCopy} recipe copied`)));
    document.querySelector('[data-effects-copy-all]')?.addEventListener('click', () => LQ.copyText(Object.values(snippets).join('\n\n'), 'All recipes copied'));
    document.querySelector('[data-effects-login]')?.addEventListener('click', () => LQ.toast('Signed in', 'The component demo is working.'));
    let value = 42;
    document.querySelectorAll('[data-effects-calc]').forEach((button) => button.addEventListener('click', () => { value += Number(button.dataset.effectsCalc); document.getElementById('effects-calc-value').textContent = value; }));
  }

  const initializers = {
    components: initComponentsDemo,
    advanced: initAdvancedDemo,
    ios: initIosDemo,
    admin: initAdminDemo,
    calculator: initCalculator,
    quote: initQuote,
    login: initLogin,
    home: initHome,
    vault: initVault,
    studio: initStudio,
    trading: initTrading,
    gaming: initGaming,
    drone: initDrone,
    menu: initMenuStudy,
    organic: initOrganic,
    intro: initIntro,
    effects: initEffects
  };

  const themes = {
    components: ['#8b7cff','#51d7ff','#070a12'], advanced: ['#9b6cff','#ff6fbb','#080912'], ios: ['#4f82ff','#51d7ff','#070b13'],
    admin: ['#6a73ff','#53c7ef','#080b15'], calculator: ['#8f61ee','#ff70b0','#0b0914'], quote: ['#6e66f7','#51d7ff','#080b15'],
    login: ['#7e5eff','#e960a3','#080a13'], home: ['#20a69b','#ffc06c','#071112'], vault: ['#7259ee','#40bfe0','#080a14'],
    studio: ['#8b67ef','#ff629d','#090a13'], trading: ['#2ecf91','#51d7ff','#041013'], gaming: ['#744deb','#ef4d99','#080817'],
    drone: ['#75d178','#51d7ff','#031011'], menu: ['#8b7cff','#51d7ff','#080a13'], organic: ['#8b7cff','#ff6fbb','#080a13'],
    intro: ['#8b7cff','#51d7ff','#070914'], effects: ['#765eff','#51d7ff','#070a12']
  };

  function init() {
    const template = templates[demoId] || templates.components;
    const theme = themes[demoId] || themes.components;
    document.documentElement.style.setProperty('--demo-accent', theme[0]);
    document.documentElement.style.setProperty('--demo-accent-2', theme[1]);
    document.documentElement.style.setProperty('--demo-bg', theme[2]);
    root.innerHTML = template();
    LQ.hydrateIcons(document);
    LQ.initTilts(document);
    LQ.initReveals(document);
    LQ.initTabs(document);
    const ambient = document.getElementById('demo-ambient');
    if (ambient) LQ.initAmbientCanvas(ambient);
    initializers[demoId]?.();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
