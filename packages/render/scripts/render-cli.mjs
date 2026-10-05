// Render one composition from the command line, without the HTTP server:
//   node scripts/render-cli.mjs <compositionId> <props.json> <out.mp4|out.png>
// Bundles on every call (slow); meant for debugging a template, not for production.
import fs from 'node:fs';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const [id, propsFile, out] = process.argv.slice(2);
if (!id || !propsFile || !out) {
  console.error('usage: node scripts/render-cli.mjs <compositionId> <props.json> <out.mp4|out.png>');
  process.exit(2);
}
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const inputProps = JSON.parse(fs.readFileSync(propsFile, 'utf8'));
const serveUrl = await bundle({entryPoint: path.join(root, 'src/index.ts'), publicDir: path.join(root, 'public')});
const composition = await selectComposition({serveUrl, id, inputProps});
if (out.endsWith('.png')) {
  await renderStill({composition, serveUrl, output: out, inputProps, imageFormat: 'png'});
} else {
  await renderMedia({composition, serveUrl, codec: 'h264', outputLocation: out, inputProps,
    onProgress: ({progress}) => process.stdout.write(`\r${Math.round(progress * 100)}%`)});
  process.stdout.write('\n');
}
console.log(`wrote ${out} (${composition.width}x${composition.height}, ${composition.durationInFrames} frames)`);
