// Spike m-25042530: render many brand_still pieces with ONE bundle.
//   node scripts/brand-still-batch.mjs <jobs.json>
// jobs.json: {"publicDir": "<dir with the brand assets>", "jobs": [{"system": "<path.json>",
//   "recipe": "product_hero", "content": "<path.json>" | {...}, "out": "<file.png>"}]}
// Asset paths inside system/content are relative to publicDir (staticFile). Local only: no R2.
import fs from 'node:fs';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';

const PORT = {'4:5': 'feed', '1:1': 'square', '9:16': 'story'};
const [jobsFile] = process.argv.slice(2);
if (!jobsFile) {
  console.error('usage: node scripts/brand-still-batch.mjs <jobs.json>');
  process.exit(2);
}
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const spec = JSON.parse(fs.readFileSync(jobsFile, 'utf8'));
const read = (v) => (typeof v === 'string' ? JSON.parse(fs.readFileSync(path.resolve(path.dirname(jobsFile), v), 'utf8')) : v);
const serveUrl = await bundle({entryPoint: path.join(root, 'src/index.ts'), publicDir: path.resolve(path.dirname(jobsFile), spec.publicDir)});
let failed = 0;
for (const job of spec.jobs) {
  if (job.composition) {
    // a plain composition (the contact sheet): {composition, props, out}
    const out = path.resolve(path.dirname(jobsFile), job.out);
    fs.mkdirSync(path.dirname(out), {recursive: true});
    const inputProps = read(job.props);
    const composition = await selectComposition({serveUrl, id: job.composition, inputProps});
    await renderStill({composition, serveUrl, output: out, inputProps, ...(job.out.endsWith('.jpg') ? {imageFormat: 'jpeg', jpegQuality: 90} : {imageFormat: 'png'})});
    console.log(`ok ${job.out} (${job.composition} ${composition.width}x${composition.height})`);
    continue;
  }
  const system = read(job.system);
  const content = read(job.content);
  const recipe = system.recipes?.[job.recipe];
  const out = path.resolve(path.dirname(jobsFile), job.out);
  fs.mkdirSync(path.dirname(out), {recursive: true});
  if (!recipe) {
    console.error(`SKIP ${job.out}: recipe ${job.recipe} missing in ${system.id}`);
    failed++;
    continue;
  }
  const id = `brand-still-v0--${PORT[recipe.format]}`;
  const inputProps = {meta: {templateId: 'brand_still', version: 0, port: PORT[recipe.format]}, system, recipe: job.recipe, content};
  const t0 = Date.now();
  try {
    const composition = await selectComposition({serveUrl, id, inputProps});
    await renderStill({composition, serveUrl, output: out, inputProps, ...(job.out.endsWith('.jpg') ? {imageFormat: 'jpeg', jpegQuality: 92} : {imageFormat: 'png'}),
      onBrowserLog: (l) => { if (l.type === 'warning' || l.type === 'error') console.log(`  [browser ${l.type}] ${l.text}`); }});
    console.log(`ok ${job.out} (${id}, ${Date.now() - t0} ms)`);
  } catch (e) {
    failed++;
    console.error(`FAIL ${job.out}: ${String(e).slice(0, 400)}`);
  }
}
process.exit(failed ? 1 : 0);
