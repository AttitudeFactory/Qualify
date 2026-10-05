// Google Fonts by family name (CONTRACT §2): the brand kit says "Poppins", we look the
// family up in @remotion/google-fonts' catalogue and load it. Unknown family, or a load
// that does not finish in time, falls back to the template default. The *warning* for
// an unknown family is produced server-side (server/fonts.mjs) from the same catalogue,
// so what the job reports and what the composition draws always agree.
import {useEffect, useState} from 'react';
import {getAvailableFonts} from '@remotion/google-fonts';
import {continueRender, delayRender} from 'remotion';

export const FALLBACK_HEADING = 'Noto Sans';
export const FALLBACK_BODY = 'Noto Sans';
const GENERIC = 'sans-serif';
const FONT_TIMEOUT_MS = 12_000;

type Catalogue = ReturnType<typeof getAvailableFonts>;
let catalogue: Catalogue | null = null;
const getCatalogue = (): Catalogue => {
  if (catalogue === null) catalogue = getAvailableFonts();
  return catalogue;
};

export const findGoogleFont = (family: string | undefined) => {
  if (!family) return null;
  const wanted = family.trim().toLowerCase();
  return getCatalogue().find((f) => f.fontFamily.toLowerCase() === wanted) ?? null;
};

type FontModule = {
  loadFont: (
    style?: string,
    options?: {weights?: string[]; subsets?: string[]},
  ) => {fontFamily: string; waitUntilDone: () => Promise<void>};
  getInfo: () => {
    fontFamily: string;
    fonts: Record<string, Record<string, Record<string, string>>>;
  };
};

const loaded = new Map<string, Promise<string>>();

/** Resolves to the CSS font-family to use; never rejects. */
export const loadFamily = (family: string | undefined, fallback: string): Promise<string> => {
  const entry = findGoogleFont(family);
  if (!entry) return Promise.resolve(fallback);
  const cached = loaded.get(entry.fontFamily);
  if (cached) return cached;

  const p = (async () => {
    const mod = (await entry.load()) as unknown as FontModule;
    const info = mod.getInfo();
    const normal = info.fonts.normal ?? Object.values(info.fonts)[0] ?? {};
    const available = Object.keys(normal);
    const weights = ['400', '700'].filter((w) => available.includes(w));
    const pick = weights.length > 0 ? weights : available.slice(0, 1);
    const firstWeight = pick[0] ? normal[pick[0]] : undefined;
    const subsets = Object.keys(firstWeight ?? {}).filter((s) => s === 'latin' || s === 'latin-ext');
    const {fontFamily, waitUntilDone} = mod.loadFont('normal', {
      weights: pick,
      subsets: subsets.length > 0 ? subsets : undefined,
    });
    await waitUntilDone();
    return fontFamily;
  })().catch(() => fallback);

  loaded.set(entry.fontFamily, p);
  return p;
};

export type Fonts = {heading: string; body: string};

const withTimeout = <T,>(p: Promise<T>, fallback: T): Promise<T> =>
  new Promise<T>((resolve) => {
    const t = setTimeout(() => resolve(fallback), FONT_TIMEOUT_MS);
    p.then(
      (v) => {
        clearTimeout(t);
        resolve(v);
      },
      () => {
        clearTimeout(t);
        resolve(fallback);
      },
    );
  });

/**
 * Loads the brand's heading/body families and blocks the render (delayRender) until
 * they are ready or the timeout fires. Always continues the render.
 */
export const useBrandFonts = (
  headingFamily: string | undefined,
  bodyFamily: string | undefined,
): Fonts => {
  const [fonts, setFonts] = useState<Fonts>({
    heading: `${FALLBACK_HEADING}, ${GENERIC}`,
    body: `${FALLBACK_BODY}, ${GENERIC}`,
  });
  const [handle] = useState(() =>
    delayRender(`brand fonts: ${headingFamily ?? '-'} / ${bodyFamily ?? '-'}`, {
      timeoutInMilliseconds: FONT_TIMEOUT_MS + 10_000,
    }),
  );

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      withTimeout(loadFamily(headingFamily, FALLBACK_HEADING), FALLBACK_HEADING),
      withTimeout(loadFamily(bodyFamily, FALLBACK_BODY), FALLBACK_BODY),
    ]).then(([heading, body]) => {
      if (!cancelled) {
        setFonts({heading: `${heading}, ${GENERIC}`, body: `${body}, ${GENERIC}`});
      }
      continueRender(handle);
    });
    return () => {
      cancelled = true;
    };
  }, [headingFamily, bodyFamily, handle]);

  return fonts;
};
