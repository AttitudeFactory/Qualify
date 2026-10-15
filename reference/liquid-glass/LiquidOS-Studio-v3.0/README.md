# LiquidOS Studio 3.0

LiquidOS Studio is a ground-up rebuild of the attached Liquid Glass packages. It combines the visual effect builder, component catalogs, and application demos into one coherent, dependency-free interface system.

## Open it

Open `index.html` directly in a modern browser. Everything required to run the Studio and demos is included locally.

For the most consistent local behavior, you can also serve the folder with any static server:

```bash
python -m http.server 8080
```

Then open `http://localhost:8080`.

## What changed

- Rebuilt navigation with animated full-screen menu choreography.
- New responsive Studio shell and visual hierarchy.
- New dependency-free liquid glass foundation.
- Expanded live Glass Lab with persistent controls and three export modes.
- Consolidated core, advanced, and iOS-inspired component systems.
- Seventeen redesigned, standalone, interactive demos.
- No Tailwind CDN, icon CDN, chart library, remote font, stock-image, or placeholder dependency.
- Mouse, touch, keyboard, reduced-motion, and 320px mobile support.
- Familiar legacy demo filenames retained where possible.

## Project structure

```text
LiquidOS-Studio-v3.0/
├── index.html
├── manifest.json
├── assets/
│   ├── css/liquidos.css
│   ├── css/studio.css
│   ├── js/liquidos.js
│   └── js/app.js
├── demos/
│   ├── demo.css
│   ├── demo.js
│   └── standalone HTML entry files
├── adapters/
│   └── tailwind-liquid-glass.cjs
└── docs/
    └── FEATURE-MAP.md
```

## Use the core system independently

```html
<link rel="stylesheet" href="assets/css/liquidos.css">

<article class="lq-glass lq-glass--liquid lq-panel">
  Your content
</article>

<script src="assets/js/liquidos.js"></script>
```

Available material modifiers include `lq-glass--clear`, `lq-glass--frosted`, `lq-glass--liquid`, `lq-glass--tint`, and `lq-glass--light`.

## Demos

The Studio demo browser links to all 17 experiences. See `docs/FEATURE-MAP.md` for the exact mapping from the attached packages into this rebuild.

## Optional Tailwind adapter

LiquidOS itself does not require Tailwind. The adapter is included only to preserve the earlier integration feature for projects that already use Tailwind:

```js
plugins: [require('./adapters/tailwind-liquid-glass.cjs')]
```

## Browser behavior

Modern Chromium, Firefox, and Safari receive the complete backdrop-filter treatment. Browsers without backdrop-filter still retain the layered surface, border, color, shadow, and readable content structure.
