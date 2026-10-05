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
  for (const role of ['heading', 'body']) {
    const family = fonts[role];
    if (typeof family !== 'string' || family.trim() === '') continue;
    if (!known().has(family.trim().toLowerCase())) {
      warnings.push(`font '${family}' unavailable, used '${FALLBACK}' for ${role}`);
    }
  }
  return warnings;
};
