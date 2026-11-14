#!/usr/bin/env node
// Local preview of `layer_still` v1 (m-25017285): renders every layout × format with fixture
// props (two fictional businesses, a synthetic photo drawn by Remotion itself — no client
// photo) at the catalog's maximum text lengths, into the untracked `out/layer-preview/`, and
// writes a contact sheet (index.html) with what the compositor decided for each still.
//
//   node scripts/layer-preview.mjs [--only plate,band] [--brand a|b|all]
//
// Each still is rendered the way the service does it (selectComposition + renderStill, a new
// browser each time, concurrency 1), timed, and its peak memory sampled (this process plus
// every child: Chrome Headless Shell and its renderers). Needs network for Google Fonts.
import {execFile} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';

const run = promisify(execFile);
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const OUT = path.join(root, 'out', 'layer-preview');
const manifest = JSON.parse(await fs.readFile(path.join(root, 'templates', 'layer_still', 'manifest.json'), 'utf8'));
const catalog = manifest.layer_catalog;
const args = process.argv.slice(2);
const argOf = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};
const only = argOf('--only')?.split(',');
const brandArg = argOf('--brand') ?? 'all';

// ------------------------------------------------------------------ fixtures (fictional)

const svgLogo = (bg, fg, letters) =>
  `data:image/svg+xml;base64,${Buffer.from(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><circle cx="100" cy="100" r="96" fill="${bg}"/><text x="100" y="128" font-family="Georgia, serif" font-size="88" font-weight="700" text-anchor="middle" fill="${fg}">${letters}</text></svg>`,
  ).toString('base64')}`;

const BRANDS = {
  a: {
    label: 'Panadería La Espiga (Poppins / Inter)',
    brand: {name: 'Panadería La Espiga', palette: ['#B5532A', '#FFFFFF', '#FFF4E6'], fonts: {heading: 'Poppins', body: 'Inter'}, logo: svgLogo('#B5532A', '#FFF4E6', 'LE')},
    isFood: true,
    price: '$ 12.000',
  },
  b: {
    label: 'Heladería Nube (Pacifico / Nunito, manuscrita)',
    brand: {name: 'Heladería Nube', palette: ['#F4C2C2', '#5A2A27', '#FFFFFF'], fonts: {heading: 'Pacifico', body: 'Nunito'}, logo: svgLogo('#5A2A27', '#F4C2C2', 'N')},
    isFood: true,
    price: '$ 9.500',
  },
};

/** The longest prefix of `text` that ends on a word and has at most `n` characters. */
const atMost = (text, n) => {
  if ([...text].length <= n) return text;
  const cut = [...text].slice(0, n + 1).join('');
  return cut.slice(0, cut.lastIndexOf(' ')).replace(/[,.;:]$/, '');
};
const POOL = {
  title: 'Empanadas recién horneadas con la receta de la abuela para compartir en familia',
  subtitle: 'Masa crujiente, relleno jugoso y una salsa de la casa que se prepara cada mañana con ingredientes frescos del mercado',
  call_phrase: 'Pídelo hoy por WhatsApp y recógelo caliente en el local',
};
const VALUES = {
  location: 'Calle 10 # 4-25, local 3, frente al parque principal del barrio centro',
  hours: 'Lunes a sábado de 7:00 a 20:00 y domingos de 8:00 a 13:00 sin falta',
  payment: 'Efectivo · Transferencia · Tarjeta débito · Tarjeta crédito',
  products: 'Empanada de carne · Pan de bono · Café con leche · Avena',
  contact: '+57 300 123 4567',
};
const SUBJECT = [0.25, 0.4, 0.75, 0.8];
const PORT_OF = {'4:5': 'feed', '1:1': 'square', '9:16': 'story'};

/** Every slot the layout has in this format, filled to its maximum length. */
const maxText = (layoutId, format) => {
  const def = catalog.layouts[layoutId];
  const out = {};
  for (const slot of ['title', 'subtitle', 'call_phrase']) {
    const lim = def.slots[slot]?.[format];
    if (lim) out[slot] = atMost(POOL[slot], lim[0]);
  }
  if (layoutId === 'band' && format === '1:1') delete out.call_phrase; // only without subtitle
  return out;
};

const cases = [];
const push = (c) => {
  if (only && !only.includes(c.layer.layout_id)) return;
  cases.push(c);
};
for (const [key, b] of Object.entries(BRANDS)) {
  if (brandArg !== 'all' && brandArg !== key) continue;
  for (const format of ['4:5', '1:1', '9:16']) {
    const base = {layout_version: 1, subject_box: SUBJECT, logo_in_photo: false};
    push({brand: key, format, name: 'photo_only', photo: true, layer: {...base, layout_id: 'photo_only'}});
    push({brand: key, format, name: 'plate top_left (price)', photo: true, layer: {...base, layout_id: 'plate', anchor: 'top_left', container_color: 'surface', accent_word: 1, price_ref: 'p-1', ...maxText('plate', format)}});
    push({brand: key, format, name: 'scrim bottom', photo: true, layer: {...base, layout_id: 'scrim', anchor: 'top', subject_box: [0.25, 0.5, 0.75, 0.9], ...maxText('scrim', format)}});
    push({brand: key, format, name: 'band bottom (price)', photo: true, layer: {...base, layout_id: 'band', anchor: 'bottom', container_color: 'accent', accent_word: 0, price_ref: 'p-1', ...maxText('band', format)}});
    const range = catalog.layouts.info_card.blocks[format];
    const lim = catalog.layouts.info_card.value[format][0];
    const kinds = ['location', 'hours', 'payment', 'products'].slice(0, range[1]);
    const info = {...base, subject_box: null, layout_id: 'info_card', container_color: 'surface', accent_word: 0, ...maxText('info_card', format)};
    push({brand: key, format, name: `info_card ${kinds.length} blocks`, photo: false, layer: {...info, info_blocks: kinds.map((k) => ({kind: k, value: atMost(VALUES[k], lim)}))}});
    push({brand: key, format, name: 'info_card 1 block + photo strip', photo: true, layer: {...info, subject_box: SUBJECT, info_blocks: [{kind: 'location', value: atMost(VALUES.location, lim)}]}});
    const bfMax = catalog.layouts.brand_fill.blocks[format][1];
    push({brand: key, format, name: 'brand_fill', photo: false, layer: {...base, subject_box: null, layout_id: 'brand_fill', container_color: 'accent', accent_word: 2, ...maxText('brand_fill', format), info_blocks: ['contact', 'hours'].slice(0, bfMax).map((k) => ({kind: k, value: atMost(VALUES[k], catalog.layouts.brand_fill.value[format][0])}))}});
    if (format === '9:16') {
      push({brand: key, format, name: 'highlight icon', photo: false, layer: {layout_id: 'highlight_circle', layout_version: 1, container_color: 'accent', highlight_content: {type: 'icon', icon_id: 'utensils'}}});
      push({brand: key, format, name: 'highlight word', photo: false, layer: {layout_id: 'highlight_circle', layout_version: 1, container_color: 'accent', highlight_content: {type: 'word', word: 'Domicilio'}}});
      push({brand: key, format, name: 'highlight photo', photo: true, layer: {layout_id: 'highlight_circle', layout_version: 1, container_color: 'surface', highlight_content: {type: 'photo'}, subject_box: SUBJECT}});
    }
  }
  // a 3-slide carousel (4:5): cover, body, closing — counter on all, logo on first and last
  const slides = [
    {role: 'cover', layer: {layout_id: 'plate', anchor: 'top_left', container_color: 'surface', title: 'Así nace tu pan', subtitle: 'Desliza y mira el paso a paso'}},
    {role: 'body', layer: {layout_id: 'band', anchor: 'bottom', container_color: 'surface', title: 'Amasado a mano', subtitle: 'Doce horas de reposo'}},
    {role: 'closing', layer: {layout_id: 'brand_fill', container_color: 'accent', title: 'Te esperamos hoy', call_phrase: 'Pídelo por WhatsApp', info_blocks: [{kind: 'contact', value: VALUES.contact}]}},
  ];
  slides.forEach((s, i) =>
    push({
      brand: key,
      format: '4:5',
      name: `carousel ${i + 1}/3 ${s.role}`,
      photo: s.role !== 'closing',
      slide: {index: i + 1, total: 3, role: s.role},
      layer: {layout_version: 1, subject_box: s.role === 'closing' ? null : SUBJECT, ...s.layer},
    }),
  );
}

// ------------------------------------------------------------------ memory sampling

const descendants = async () => {
  const {stdout} = await run('ps', ['-A', '-o', 'pid=,ppid=,rss=']);
  const rows = stdout
    .trim()
    .split('\n')
    .map((l) => l.trim().split(/\s+/).map(Number));
  const kids = new Map();
  for (const [pid, ppid] of rows) {
    if (!kids.has(ppid)) kids.set(ppid, []);
    kids.get(ppid).push(pid);
  }
  const rss = new Map(rows.map(([pid, , r]) => [pid, r]));
  let total = 0;
  const stack = [process.pid];
  while (stack.length) {
    const p = stack.pop();
    total += rss.get(p) ?? 0;
    stack.push(...(kids.get(p) ?? []));
  }
  return total * 1024; // bytes
};
const sampler = () => {
  let peak = 0;
  let stop = false;
  const loop = (async () => {
    while (!stop) {
      peak = Math.max(peak, await descendants().catch(() => 0));
      await new Promise((r) => setTimeout(r, 100));
    }
  })();
  return {
    done: async () => {
      stop = true;
      await loop;
      return peak;
    },
  };
};

// ------------------------------------------------------------------ render

await fs.rm(OUT, {recursive: true, force: true});
await fs.mkdir(OUT, {recursive: true});
console.log('bundling…');
const serveUrl = await bundle({entryPoint: path.join(root, 'src', 'index.ts'), outDir: path.join(OUT, '.bundle')});
const chromiumOptions = {enableMultiProcessOnLinux: true};

// the synthetic photo, drawn by Remotion (no client data)
const photoFile = path.join(OUT, 'fixture-photo.png');
{
  const composition = await selectComposition({serveUrl, id: 'layer-still-fixture-photo', inputProps: {}, chromiumOptions, logLevel: 'error'});
  await renderStill({composition, serveUrl, output: photoFile, inputProps: {}, chromiumOptions, logLevel: 'error'});
}
const photoUrl = `data:image/png;base64,${(await fs.readFile(photoFile)).toString('base64')}`;

const results = [];
let n = 0;
for (const c of cases) {
  n += 1;
  const b = BRANDS[c.brand];
  const port = PORT_OF[c.format];
  const spec = manifest.outputs[port];
  const inputProps = {
    meta: {templateId: 'layer_still', version: 1, port},
    brand: b.brand,
    texts: {price_text: b.price, is_food: b.isFood},
    photos: c.photo ? [photoUrl] : [],
    layer: c.layer,
    slide: c.slide ?? null,
  };
  const file = `${String(n).padStart(2, '0')}-${c.brand}-${c.format.replace(':', 'x')}-${c.name.replace(/[^a-z0-9]+/gi, '-')}.png`;
  const mem = sampler();
  const t0 = Date.now();
  let report = null;
  let error = null;
  try {
    const composition = await selectComposition({serveUrl, id: spec.composition, inputProps, chromiumOptions, logLevel: 'error'});
    report = composition.props?.resolved?.report ?? null;
    await renderStill({composition, serveUrl, output: path.join(OUT, file), inputProps, chromiumOptions, imageFormat: 'png', logLevel: 'error'});
  } catch (e) {
    error = String(e?.message ?? e).slice(0, 400);
  }
  const ms = Date.now() - t0;
  const peak = await mem.done();
  results.push({...c, file, ms, peakMb: Math.round(peak / 1e6), report, error, texts: c.layer});
  console.log(`${n}/${cases.length} ${file} ${ms} ms peak ${Math.round(peak / 1e6)} MB ${report ? `→ ${report.layout_rendered}` : error}`);
}

// ------------------------------------------------------------------ contact sheet

const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[ch]);
const ok = results.filter((r) => !r.error);
const times = ok.map((r) => r.ms).sort((a, b) => a - b);
const peaks = ok.map((r) => r.peakMb);
const median = times[Math.floor(times.length / 2)] ?? 0;
const summary = {
  stills: results.length,
  failed: results.length - ok.length,
  ms: {min: times[0], median, max: times[times.length - 1]},
  peakMb: {max: Math.max(...peaks), median: peaks.sort((a, b) => a - b)[Math.floor(peaks.length / 2)]},
  carousel10EstimateSec: Math.round((median * 10) / 100) / 10,
};
await fs.writeFile(path.join(OUT, 'report.json'), JSON.stringify({summary, results}, null, 2));
const card = (r) => {
  const rep = r.report;
  const fell = rep && rep.layout_rendered !== rep.layout_requested;
  const notes = rep ? [...rep.fallbacks, ...rep.overflow.map((o) => `OVERFLOW ${o}`)] : [];
  return `<figure class="${r.error ? 'err' : fell || rep?.overflow.length ? 'warn' : ''}">
  ${r.error ? `<div class="ph">error</div>` : `<a href="${esc(r.file)}"><img src="${esc(r.file)}" loading="lazy"></a>`}
  <figcaption><b>${esc(r.name)}</b> · ${esc(r.format)} · ${esc(BRANDS[r.brand].label.split(' (')[0])}<br>
  ${rep ? `${esc(rep.layout_requested)} → <b>${esc(rep.layout_rendered)}</b>${rep.anchor ? ` / ${esc(rep.anchor)}` : ''} · logo ${esc(rep.logo)}` : esc(r.error)}<br>
  ${rep ? `tamaños ${esc(Object.entries(rep.sizes).map(([k, v]) => `${k} ${v}`).join(', '))} · contraste ${esc(Object.entries(rep.contrast).map(([k, v]) => `${k} ${v}`).join(', '))}` : ''}<br>
  ${r.ms} ms · ${r.peakMb} MB
  ${notes.length ? `<ul>${notes.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}</figcaption></figure>`;
};
const html = `<!doctype html><meta charset="utf-8"><title>layer_still v1 — hoja de contactos</title>
<style>body{font:14px system-ui,sans-serif;margin:16px;background:#f4f4f5;color:#18181b}h1{font-size:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}
figure{margin:0;background:#fff;border-radius:8px;padding:8px;border:2px solid transparent}figure.warn{border-color:#f59e0b}figure.err{border-color:#dc2626}
img{width:100%;display:block;border-radius:4px;background:#ddd}figcaption{font-size:12px;line-height:1.4;margin-top:6px}ul{margin:4px 0 0;padding-left:16px;color:#92400e}
.ph{height:200px;display:flex;align-items:center;justify-content:center;background:#fee2e2}</style>
<h1>layer_still v1 · ${results.length} imágenes · fallidas ${summary.failed}</h1>
<p>Tiempo por imagen (selectComposition + renderStill, navegador nuevo, concurrencia 1): mín ${summary.ms.min} ms · mediana ${summary.ms.median} ms · máx ${summary.ms.max} ms. Memoria pico (este proceso + Chrome): máx ${summary.peakMb.max} MB, mediana ${summary.peakMb.median} MB. Carrusel de 10: ≈ ${summary.carousel10EstimateSec} s. Borde ámbar = cayó a otro diseño o desbordó; rojo = error.</p>
<div class="grid">${results.map(card).join('\n')}</div>`;
await fs.writeFile(path.join(OUT, 'index.html'), html);
console.log(JSON.stringify(summary));
console.log(`contact sheet: ${path.join(OUT, 'index.html')}`);
