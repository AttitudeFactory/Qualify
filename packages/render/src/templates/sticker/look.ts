// The brand as a sticker draws it (creative rule 7: the Brand Kit's palette and heading
// face in every sticker). Pure colour helpers + the font hook.
import {useEffect, useState} from 'react';
import {continueRender, delayRender} from 'remotion';
import {FALLBACK_HEADING, loadFamily} from '../../fonts';
import type {BrandKit} from '../../props';

type RGB = [number, number, number];

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

export const parseHex = (s: unknown): RGB | null => {
  if (typeof s !== 'string' || !HEX.test(s.trim())) return null;
  let h = s.trim().slice(1);
  if (h.length === 3) h = h.replace(/./g, (c) => c + c);
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB;
};

const toHex = ([r, g, b]: RGB): string =>
  `#${[r, g, b].map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, '0')).join('')}`;

/** WCAG relative luminance, 0 (black) .. 1 (white). */
export const luminance = ([r, g, b]: RGB): number => {
  const ch = (c: number) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b);
};

const mix = (a: RGB, b: RGB, k: number): RGB => [0, 1, 2].map((i) => a[i]! + (b[i]! - a[i]!) * k) as RGB;

const NEAR_BLACK: RGB = [17, 24, 39];
const HOUSE: RGB = [15, 118, 110];

export type StickerColors = {
  /** text fill: the first brand colour dark enough to read inside a white outline */
  ink: string;
  /** a darker shade of the ink, for the text's 3D step */
  inkDeep: string;
  /** the coin's back and a sparkle: the brand's first colour that is not near-white */
  accent: string;
  /** rings and sparkles: the brand's next usable colour, so they stand out from the art */
  pop: string;
};

export const stickerColors = (brand: BrandKit): StickerColors => {
  const palette = brand.palette.map(parseHex).filter((c): c is RGB => c !== null);
  const ink = palette.find((c) => luminance(c) < 0.6) ?? NEAR_BLACK;
  const usable = palette.filter((c) => luminance(c) < 0.85);
  const accent = usable[0] ?? HOUSE;
  const pop = usable[1] ?? accent;
  return {ink: toHex(ink), inkDeep: toHex(mix(ink, [0, 0, 0], 0.45)), accent: toHex(accent), pop: toHex(pop)};
};

const GENERIC = 'sans-serif';
const FONT_TIMEOUT_MS = 12_000;
const FILE_FACE = 'QualifyStickerFace';

/** The brand's own uploaded face (an asset URL) when there is one, else its Google
 * family, else Noto Sans. Blocks the render until the face is usable (or timed out). */
export const useStickerFont = (fileUrl: string | undefined, family: string | undefined): {family: string; ready: boolean} => {
  const [state, setState] = useState<{family: string; ready: boolean}>({family: `${FALLBACK_HEADING}, ${GENERIC}`, ready: false});
  const [handle] = useState(() => delayRender(`sticker font: ${fileUrl ? 'file' : (family ?? '-')}`, {timeoutInMilliseconds: FONT_TIMEOUT_MS + 10_000}));

  useEffect(() => {
    let cancelled = false;
    const fromFile = async (): Promise<string> => {
      if (!fileUrl) throw new Error('no file');
      const face = new FontFace(FILE_FACE, `url(${fileUrl})`);
      await face.load();
      document.fonts.add(face);
      return FILE_FACE;
    };
    const pick = fromFile().catch(() => loadFamily(family, FALLBACK_HEADING));
    const timeout = new Promise<string>((resolve) => setTimeout(() => resolve(FALLBACK_HEADING), FONT_TIMEOUT_MS));
    Promise.race([pick, timeout]).then((name) => {
      if (!cancelled) setState({family: `${name}, ${FALLBACK_HEADING}, ${GENERIC}`, ready: true});
    });
    return () => {
      cancelled = true;
    };
  }, [fileUrl, family]);

  // Continue only once React has committed the face: the text is then measured and drawn
  // with it, not with the fallback.
  useEffect(() => {
    if (state.ready) continueRender(handle);
  }, [state.ready, handle]);

  return state;
};
