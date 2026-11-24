// Server-side mirror of src/fonts.ts: is this Google Fonts family known? Used to emit
// the `warnings` of /estimate and the job (CONTRACT §2) without opening Chromium.
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {getAvailableFonts} = require('@remotion/google-fonts');

const FALLBACK = 'Noto Sans';
let families = null;
const known = () => {
  if (!families) families = new Set(getAvailableFonts().map((f) => f.fontFamily.toLowerCase()));
  return families;
};

/** @returns {string[]} warnings for the brand kit's fonts */
export const fontWarnings = (brand) => {
  const warnings = [];
  const fonts = brand?.fonts ?? {};
  const files = brand?.fontFiles ?? {};
  for (const role of ['heading', 'body']) {
    const family = fonts[role];
    if (typeof family !== 'string' || family.trim() === '') continue;
    // ED-13: the brand's own font file draws this role — its family name is only a label
    if (typeof files?.[role] === 'string' && files[role] !== '') continue;
    if (!known().has(family.trim().toLowerCase())) {
      warnings.push(`font '${family}' unavailable, used '${FALLBACK}' for ${role}`);
    }
  }
  return warnings;
};
