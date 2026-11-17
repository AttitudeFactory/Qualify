// Font loading with explicit weights + canvas text measurement for brand_still (spike m-25042530).
// The shared fonts.ts loads only 400/700; a brand system names its own weights (Unbounded 800,
// Archivo 900), so this loader asks for the nearest weights the family really has.
import {getAvailableFonts} from '@remotion/google-fonts';
import type {TypeFace} from './types';

type FontModule = {
  loadFont: (
    style?: string,
    options?: {weights?: string[]; subsets?: string[]},
  ) => {fontFamily: string; waitUntilDone: () => Promise<void>};
  getInfo: () => {fontFamily: string; fonts: Record<string, Record<string, Record<string, string>>>};
};

export type LoadedFace = TypeFace & {css: string; weight: number; found: boolean};

const nearest = (available: number[], wanted: number): number =>
  available.reduce((best, w) => (Math.abs(w - wanted) < Math.abs(best - wanted) ? w : best), available[0] ?? 400);

/** Loads one family with the weights the system needs; unknown family → generic sans, reported. */
export const loadFace = async (
  face: TypeFace,
  extraWeights: number[] = [],
  resolve: (src: string) => string = (s) => s,
): Promise<LoadedFace> => {
  if (face.src) {
    // A brand font file (variable or static): registered under its own family name so it never
    // collides with a Google family of the same name.
    const family = `brand-${face.family.replace(/[^A-Za-z0-9]/g, '')}-${face.src.length}`;
    const already = Array.from(document.fonts).some((f) => f.family === family);
    if (!already) {
      const ff = new FontFace(family, `url("${resolve(face.src)}")`, {weight: '100 900'});
      await ff.load();
      document.fonts.add(ff);
    }
    return {...face, css: `"${family}", sans-serif`, found: true};
  }
  const entry = getAvailableFonts().find((f) => f.fontFamily.toLowerCase() === face.family.trim().toLowerCase());
  if (!entry) return {...face, css: 'sans-serif', found: false};
  const mod = (await entry.load()) as unknown as FontModule;
  const info = mod.getInfo();
  const normal = info.fonts.normal ?? Object.values(info.fonts)[0] ?? {};
  const available = Object.keys(normal).map(Number).filter((n) => !Number.isNaN(n));
  const weight = nearest(available, face.weight);
  const weights = Array.from(new Set([weight, ...extraWeights.map((w) => nearest(available, w))])).map(String);
  const first = normal[String(weight)] ?? {};
  const subsets = Object.keys(first).filter((s) => s === 'latin' || s === 'latin-ext');
  const {fontFamily, waitUntilDone} = mod.loadFont('normal', {weights, subsets: subsets.length ? subsets : undefined});
  await waitUntilDone();
  return {...face, weight, css: `"${fontFamily}", sans-serif`, found: true};
};

let ctx: CanvasRenderingContext2D | null = null;
const context = (): CanvasRenderingContext2D => {
  if (!ctx) {
    const c = document.createElement('canvas');
    const got = c.getContext('2d');
    if (!got) throw new Error('canvas 2d unavailable');
    ctx = got;
  }
  return ctx;
};

export const caseOf = (face: TypeFace, text: string): string => (face.uppercase ? text.toLocaleUpperCase('es') : text);

/** Advance width of one line, in px, as it will be drawn (case + letter spacing applied). */
export const measure = (face: LoadedFace, text: string, size: number, weight?: number): number => {
  const c = context();
  c.font = `${weight ?? face.weight} ${size}px ${face.css}`;
  const ls = (face.letter_spacing_em ?? 0) * size;
  (c as unknown as {letterSpacing: string}).letterSpacing = `${ls}px`;
  return c.measureText(caseOf(face, text)).width;
};

/**
 * Largest size ≤ max at which `text` fits `width` on ONE line; null when it would need less
 * than `min` (the caller then drops the element whole — a price is never cut).
 */
export const fitSize = (face: LoadedFace, text: string, width: number, max: number, min: number, weight?: number): number | null => {
  let size = max;
  for (let i = 0; i < 6; i++) {
    const w = measure(face, text, size, weight);
    if (w <= width) return Math.floor(size);
    size = Math.floor((size * width) / w) - 1;
    if (size < min) return null;
  }
  return size >= min ? size : null;
};
