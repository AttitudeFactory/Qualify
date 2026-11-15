#!/usr/bin/env node
// Timing of one `layer_still` still, split so font network time is visible (m-25017285 review 2 #6).
//
//   node scripts/layer-timing.mjs [repeats=6]
//
// Mode «service»: exactly what server/jobs.mjs does today — selectComposition then renderStill,
// each opening its own Chrome (no shared browser, so no font cache between renders).
// Mode «shared»: one Chrome for the whole run (`openBrowser` + `puppeteerInstance`); its first
// render is cold (fonts fetched), the rest warm (fonts in that browser's cache).
// Per render: select (calculateMetadata: font load + measuring) and render (drawing) in ms.
// Output to stdout as JSON lines + a summary. Needs network for Google Fonts.
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {openBrowser, renderStill, selectComposition} from '@remotion/renderer';
import fs from 'node:fs/promises';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const OUT = path.join(root, 'out', 'layer-timing');
const repeats = Number(process.argv[2] ?? 6);
await fs.mkdir(OUT, {recursive: true});
const serveUrl = await bundle({entryPoint: path.join(root, 'src', 'index.ts'), outDir: path.join(OUT, '.bundle')});
const chromiumOptions = {enableMultiProcessOnLinux: true};
const photo = `data:image/jpeg;base64,${(await fs.readFile(path.join(root, 'public', 'sample', 'photo-1.jpg'))).toString('base64')}`;

const BRANDS = {
  poppins: {name: 'Panadería La Espiga', palette: ['#B5532A', '#FFFFFF', '#FFF4E6'], fonts: {heading: 'Poppins', body: 'Inter'}, logo: null},
  pacifico: {name: 'Heladería Nube', palette: ['#F4C2C2', '#5A2A27', '#FFFFFF'], fonts: {heading: 'Pacifico', body: 'Nunito'}, logo: null},
};
const layer = {
  spec_version: 1,
  layout_id: 'band',
  layout_version: 1,
  format: '4:5',
  photo: {subject_box: [0.25, 0.4, 0.75, 0.8], logo_in_photo: false, base_has_invented_text: false},
  anchor: 'bottom',
  container_color: 'accent',
  title: 'Empanadas recién horneadas',
  subtitle: 'Masa crujiente y la salsa de la casa',
};
const propsFor = (brand) => ({meta: {templateId: 'layer_still', version: 1, port: 'feed'}, brand, texts: {}, photos: [photo], layer});

const once = async (brand, puppeteerInstance) => {
  const inputProps = propsFor(brand);
  const t0 = Date.now();
  const composition = await selectComposition({serveUrl, id: 'layer-still-v1--feed', inputProps, chromiumOptions, logLevel: 'error', puppeteerInstance});
  const t1 = Date.now();
  await renderStill({composition, serveUrl, output: path.join(OUT, 'still.png'), inputProps, chromiumOptions, logLevel: 'error', puppeteerInstance});
  const t2 = Date.now();
  return {select: t1 - t0, render: t2 - t1, total: t2 - t0};
};

const stats = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return {n: s.length, median: s[Math.floor(s.length / 2)], max: s[s.length - 1], min: s[0]};
};
const summary = {};
for (const [name, brand] of Object.entries(BRANDS)) {
  const service = [];
  for (let i = 0; i < repeats; i++) {
    const r = await once(brand, undefined);
    service.push(r);
    console.log(JSON.stringify({mode: 'service', brand: name, i, ...r}));
  }
  const browser = await openBrowser('chrome', {chromiumOptions});
  const shared = [];
  for (let i = 0; i < repeats; i++) {
    const r = await once(brand, browser);
    shared.push(r);
    console.log(JSON.stringify({mode: 'shared', brand: name, i, cold: i === 0, ...r}));
  }
  await browser.close({silent: true});
  summary[name] = {
    service_total: stats(service.map((r) => r.total)),
    service_select: stats(service.map((r) => r.select)),
    service_render: stats(service.map((r) => r.render)),
    shared_cold_total: shared[0]?.total,
    shared_cold_select: shared[0]?.select,
    shared_warm_total: stats(shared.slice(1).map((r) => r.total)),
    shared_warm_select: stats(shared.slice(1).map((r) => r.select)),
  };
}
console.log(JSON.stringify({summary}, null, 2));
