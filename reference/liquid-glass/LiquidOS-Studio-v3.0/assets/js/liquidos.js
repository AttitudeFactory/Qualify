(() => {
  const iconPaths = {
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    external: '<path d="M14 5h5v5M10 14 19 5M19 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
    sparkles: '<path d="m12 3 1.15 3.1L16 7.5l-2.85 1.4L12 12l-1.15-3.1L8 7.5l2.85-1.4L12 3ZM5.5 13l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9.9-2.1ZM18.5 13l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8Z"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>',
    code: '<path d="m8 9-4 3 4 3M16 9l4 3-4 3M14 5l-4 14"/>',
    grid: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
    play: '<path d="m9 7 8 5-8 5V7Z"/>',
    pause: '<path d="M9 7v10M15 7v10"/>',
    moon: '<path d="M20 15.2A8.5 8.5 0 0 1 8.8 4 8.5 8.5 0 1 0 20 15.2Z"/>',
    sun: '<circle cx="12" cy="12" r="3.5"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42"/>',
    copy: '<rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m16 16 4 4"/>',
    sliders: '<path d="M4 6h8M16 6h4M4 12h3M11 12h9M4 18h10M18 18h2"/><circle cx="14" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="16" cy="18" r="2"/>',
    home: '<path d="m3 11 9-8 9 8v9a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1v-9Z"/>',
    components: '<rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="5" rx="2"/><rect x="13" y="10" width="8" height="11" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/>',
    flask: '<path d="M9 3h6M10 3v6l-5.5 9.2A1.8 1.8 0 0 0 6.05 21h11.9a1.8 1.8 0 0 0 1.55-2.8L14 9V3"/><path d="M7.5 15h9"/>',
    book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11a2 2 0 0 1 2 2v16a2 2 0 0 0-2-2H6.5A2.5 2.5 0 0 0 4 21.5v-16ZM20 5.5A2.5 2.5 0 0 0 17.5 3H15a2 2 0 0 0-2 2v16a2 2 0 0 1 2-2h2.5a2.5 2.5 0 0 1 2.5 2.5v-16Z"/>',
    download: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    monitor: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
    smartphone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    shield: '<path d="M12 3 20 6v5c0 5-3.3 8.2-8 10-4.7-1.8-8-5-8-10V6l8-3Z"/><path d="m9 12 2 2 4-5"/>',
    terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
    gamepad: '<path d="M8 8h8a5 5 0 0 1 4.7 6.7l-1 2.7a2.4 2.4 0 0 1-4.1.7L14 16h-4l-1.6 2.1a2.4 2.4 0 0 1-4.1-.7l-1-2.7A5 5 0 0 1 8 8Z"/><path d="M7 12v4M5 14h4M16 12h.01M18 15h.01"/>',
    wallet: '<path d="M4 6a2 2 0 0 1 2-2h12v4H6a2 2 0 0 0 0 4h14v7a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V6Z"/><path d="M20 9v6h-5a3 3 0 0 1 0-6h5Z"/>',
    thermostat: '<path d="M10 14.7V5a2 2 0 0 1 4 0v9.7a4 4 0 1 1-4 0Z"/><path d="M12 8v8"/>',
    power: '<path d="M12 3v9M7.1 5.8a8 8 0 1 0 9.8 0"/>',
    upload: '<path d="M12 21V9M7 14l5-5 5 5M5 3h14"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
    phone: '<path d="M7.2 3h3l1.3 4-2 1.4a14 14 0 0 0 6.1 6.1l1.4-2 4 1.3v3a4 4 0 0 1-4 4C9.4 20.8 3.2 14.6 3.2 7a4 4 0 0 1 4-4Z"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m4 7 8 6 8-6"/>',
    eye: '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/>',
    calculator: '<rect x="5" y="2" width="14" height="20" rx="2"/><rect x="8" y="5" width="8" height="4" rx="1"/><path d="M8 13h.01M12 13h.01M16 13h.01M8 17h.01M12 17h.01M16 17h.01"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    delete: '<path d="m6 6 12 12M18 6 6 18"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
    bell: '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/>',
    cloud: '<path d="M6 19a4 4 0 0 1-.4-8A6.5 6.5 0 0 1 18 9.5 4.8 4.8 0 0 1 18.5 19H6Z"/>',
    folder: '<path d="M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6Z"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m3 16 5-5 4 4 2-2 7 7"/>',
    video: '<rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3v-4Z"/>',
    music: '<path d="M9 18V5l10-2v13M9 18a3 3 0 1 1-3-3h3M19 16a3 3 0 1 1-3-3h3"/>',
    paint: '<path d="M12 3a9 9 0 0 0 0 18h1.5a2 2 0 0 0 0-4H12a1.5 1.5 0 0 1 0-3h2.5A6.5 6.5 0 0 0 21 7.5C21 5 17 3 12 3Z"/><path d="M7.5 8h.01M11 6h.01M15 7h.01M6 12h.01"/>',
    cursor: '<path d="m5 3 14 9-6 2-3 6-5-17Z"/>',
    zoom: '<circle cx="11" cy="11" r="7"/><path d="m16 16 4 4M8 11h6M11 8v6"/>',
    undo: '<path d="m9 7-5 5 5 5M5 12h8a6 6 0 0 1 6 6"/>',
    redo: '<path d="m15 7 5 5-5 5M19 12h-8a6 6 0 0 0-6 6"/>',
    star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z"/>',
    message: '<path d="M21 12a8 8 0 0 1-8 8H5l-3 2 1-5a8 8 0 1 1 18-5Z"/>',
    send: '<path d="m3 3 18 9-18 9 4-9-4-9Z"/><path d="M7 12h14"/>',
    heart: '<path d="M20.8 5.8a5.5 5.5 0 0 0-7.8 0L12 6.9l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.4a5.5 5.5 0 0 0 0-7.8Z"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/>',
    volume: '<path d="M5 9v6h4l5 4V5L9 9H5ZM17 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12"/>',
    compass: '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5 5-2Z"/>',
    rocket: '<path d="M14 5c3-3 6-2 6-2s1 3-2 6l-5 5-4-4 5-5ZM9 10l-4 1-2 3 6 1M13 14l-1 5-3 2-1-6"/><circle cx="15" cy="8" r="1.5"/>',
    cpu: '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    wifi: '<path d="M5 11a10 10 0 0 1 14 0M8 14a6 6 0 0 1 8 0M11 17a2 2 0 0 1 2 0M12 20h.01"/>',
    battery: '<rect x="3" y="7" width="17" height="10" rx="2"/><path d="M22 10v4M6 10v4M10 10v4M14 10v4"/>',
    map: '<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6ZM9 3v15M15 6v15"/>',
    database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/>',
    activity: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    trade: '<path d="M7 7h11l-3-3M17 17H6l3 3"/>',
    drone: '<path d="M8 8h8v8H8zM4 4l4 4M20 4l-4 4M4 20l4-4M20 20l-4-4"/><circle cx="4" cy="4" r="2"/><circle cx="20" cy="4" r="2"/><circle cx="4" cy="20" r="2"/><circle cx="20" cy="20" r="2"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5M6.1 9a7 7 0 0 1 11.7-2L20 12M4 12l2.2 5a7 7 0 0 0 11.7-2"/>',
    filter: '<path d="M3 5h18l-7 8v6l-4 2v-8L3 5Z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    file: '<path d="M6 3h8l4 4v14H6V3Z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    edit: '<path d="m4 20 4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10L4 20ZM14 7l3 3"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    more: '<circle cx="5" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none"/>'
  };

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function icon(name, className = 'lq-icon') {
    const paths = iconPaths[name] || iconPaths.sparkles;
    return `<svg class="${className}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paths}</svg>`;
  }

  function hydrateIcons(root = document) {
    root.querySelectorAll('[data-icon]').forEach((node) => {
      if (node.dataset.iconHydrated) return;
      node.innerHTML = icon(node.dataset.icon, node.dataset.iconClass || 'lq-icon');
      node.dataset.iconHydrated = 'true';
    });
  }

  function toast(title, message = '', options = {}) {
    let region = document.querySelector('.lq-toast-region');
    if (!region) {
      region = document.createElement('div');
      region.className = 'lq-toast-region';
      region.setAttribute('aria-live', 'polite');
      region.setAttribute('aria-atomic', 'true');
      document.body.appendChild(region);
    }
    const item = document.createElement('div');
    item.className = 'lq-toast';
    item.setAttribute('role', 'status');
    item.innerHTML = `
      <span class="lq-toast__icon">${icon(options.icon || 'check')}</span>
      <span><strong>${escapeHtml(title)}</strong>${message ? `<small>${escapeHtml(message)}</small>` : ''}</span>
      <button type="button" aria-label="Dismiss notification">${icon('close')}</button>
    `;
    region.appendChild(item);
    const remove = () => {
      if (item.classList.contains('is-leaving')) return;
      item.classList.add('is-leaving');
      window.setTimeout(() => item.remove(), 310);
    };
    item.querySelector('button').addEventListener('click', remove);
    window.setTimeout(remove, options.duration || 3800);
    return item;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[char]);
  }

  async function copyText(text, label = 'Copied') {
    try {
      await navigator.clipboard.writeText(text);
    } catch (error) {
      const field = document.createElement('textarea');
      field.value = text;
      field.setAttribute('readonly', '');
      field.style.position = 'fixed';
      field.style.opacity = '0';
      document.body.appendChild(field);
      field.select();
      document.execCommand('copy');
      field.remove();
    }
    toast(label, 'Ready to paste anywhere.');
  }

  function initRipples(root = document) {
    root.addEventListener('pointerdown', (event) => {
      const button = event.target.closest('.lq-button, [data-ripple]');
      if (!button || button.disabled) return;
      const rect = button.getBoundingClientRect();
      const ripple = document.createElement('span');
      ripple.className = 'lq-ripple';
      ripple.style.left = `${event.clientX - rect.left}px`;
      ripple.style.top = `${event.clientY - rect.top}px`;
      button.appendChild(ripple);
      window.setTimeout(() => ripple.remove(), 650);
    });
  }

  function initLiquidPointers(root = document) {
    if (reducedMotion) return;
    root.addEventListener('pointermove', (event) => {
      const glass = event.target.closest('.lq-glass--liquid');
      if (!glass) return;
      const rect = glass.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * 100;
      const y = ((event.clientY - rect.top) / rect.height) * 100;
      glass.style.setProperty('--lq-pointer-x', `${x}%`);
      glass.style.setProperty('--lq-pointer-y', `${y}%`);
      glass.style.setProperty('--lq-shift-x', `${(x - 50) * 0.08}px`);
      glass.style.setProperty('--lq-shift-y', `${(y - 50) * 0.08}px`);
    });
  }

  function initTilts(root = document) {
    if (reducedMotion || matchMedia('(pointer: coarse)').matches) return;
    root.querySelectorAll('.lq-tilt').forEach((card) => {
      card.addEventListener('pointermove', (event) => {
        const rect = card.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width - 0.5;
        const y = (event.clientY - rect.top) / rect.height - 0.5;
        card.style.setProperty('--lq-tilt-x', `${y * -7}deg`);
        card.style.setProperty('--lq-tilt-y', `${x * 9}deg`);
      });
      card.addEventListener('pointerleave', () => {
        card.style.setProperty('--lq-tilt-x', '0deg');
        card.style.setProperty('--lq-tilt-y', '0deg');
      });
    });
  }

  function initReveals(root = document) {
    const elements = [...root.querySelectorAll('.lq-reveal')];
    if (!elements.length) return;
    if (reducedMotion || !('IntersectionObserver' in window)) {
      elements.forEach((element) => element.classList.add('is-visible'));
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -4% 0px' });
    elements.forEach((element) => observer.observe(element));
  }

  function initTabs(root = document) {
    root.querySelectorAll('[data-tabs]').forEach((tabs) => {
      const buttons = [...tabs.querySelectorAll('[role="tab"]')];
      buttons.forEach((button) => {
        button.addEventListener('click', () => {
          buttons.forEach((item) => {
            const selected = item === button;
            item.setAttribute('aria-selected', String(selected));
            item.classList.toggle('is-active', selected);
            const panel = document.getElementById(item.getAttribute('aria-controls'));
            if (panel) panel.hidden = !selected;
          });
        });
      });
    });
  }

  function initDialogs(root = document) {
    root.addEventListener('click', (event) => {
      const opener = event.target.closest('[data-dialog-open]');
      const closer = event.target.closest('[data-dialog-close]');
      if (opener) {
        const dialog = document.getElementById(opener.dataset.dialogOpen);
        if (dialog && typeof dialog.showModal === 'function') dialog.showModal();
      }
      if (closer) {
        const dialog = closer.closest('dialog');
        if (dialog) dialog.close();
      }
    });
    root.querySelectorAll('dialog').forEach((dialog) => {
      dialog.addEventListener('click', (event) => {
        if (event.target === dialog) dialog.close();
      });
    });
  }

  function initCopyButtons(root = document) {
    root.addEventListener('click', (event) => {
      const button = event.target.closest('[data-copy]');
      if (!button) return;
      const selector = button.dataset.copy;
      const target = selector ? document.querySelector(selector) : null;
      const text = button.dataset.copyText || target?.textContent || '';
      copyText(text, button.dataset.copyLabel || 'Copied');
    });
  }

  function initAmbientCanvas(canvas) {
    if (!canvas) return;
    const context = canvas.getContext('2d', { alpha: true });
    if (!context) return;
    let width = 0;
    let height = 0;
    let dpr = 1;
    let animationFrame = 0;
    const pointer = { x: 0.5, y: 0.35, active: false };
    const particles = Array.from({ length: 34 }, (_, index) => ({
      x: Math.random(),
      y: Math.random(),
      radius: 0.5 + Math.random() * 1.8,
      speed: 0.00004 + Math.random() * 0.00011,
      phase: Math.random() * Math.PI * 2,
      color: index % 3
    }));

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      dpr = Math.min(2, window.devicePixelRatio || 1);
      width = Math.max(1, Math.floor(rect.width));
      height = Math.max(1, Math.floor(rect.height));
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = (time = 0) => {
      context.clearRect(0, 0, width, height);
      const colors = ['124, 109, 255', '81, 215, 255', '255, 111, 187'];
      particles.forEach((particle) => {
        const drift = time * particle.speed;
        const x = (particle.x * width + Math.sin(drift + particle.phase) * 42 + width) % width;
        const y = (particle.y * height + Math.cos(drift * 0.8 + particle.phase) * 34 + height) % height;
        const distance = Math.hypot(x / width - pointer.x, y / height - pointer.y);
        const near = pointer.active ? Math.max(0, 0.3 - distance) : 0;
        const radius = particle.radius + near * 7;
        const gradient = context.createRadialGradient(x, y, 0, x, y, radius * 7);
        gradient.addColorStop(0, `rgba(${colors[particle.color]}, ${0.22 + near})`);
        gradient.addColorStop(1, `rgba(${colors[particle.color]}, 0)`);
        context.fillStyle = gradient;
        context.beginPath();
        context.arc(x, y, radius * 7, 0, Math.PI * 2);
        context.fill();
      });
      if (!reducedMotion) animationFrame = requestAnimationFrame(draw);
    };

    window.addEventListener('resize', resize, { passive: true });
    window.addEventListener('pointermove', (event) => {
      pointer.x = event.clientX / Math.max(window.innerWidth, 1);
      pointer.y = event.clientY / Math.max(window.innerHeight, 1);
      pointer.active = true;
    }, { passive: true });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) cancelAnimationFrame(animationFrame);
      else if (!reducedMotion) animationFrame = requestAnimationFrame(draw);
    });
    resize();
    draw(0);
  }

  function init(root = document) {
    hydrateIcons(root);
    initRipples(root);
    initLiquidPointers(root);
    initTilts(root);
    initReveals(root);
    initTabs(root);
    initDialogs(root);
    initCopyButtons(root);
  }

  window.LiquidOS = {
    icon,
    icons: iconPaths,
    hydrateIcons,
    toast,
    copyText,
    escapeHtml,
    init,
    initTilts,
    initReveals,
    initTabs,
    initDialogs,
    initAmbientCanvas,
    reducedMotion
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init(document), { once: true });
  } else {
    init(document);
  }
})();
