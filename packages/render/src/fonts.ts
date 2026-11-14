// Google Fonts by family name (CONTRACT §2): the brand kit says "Poppins", we look the
// family up in @remotion/google-fonts' catalogue and load it. Unknown family, or a load
// that does not finish in time, falls back to the template default. The *warning* for
// an unknown family is produced server-side (server/fonts.mjs) from the same catalogue,
// so what the job reports and what the composition draws always agree.
import {useEffect, useState} from 'react';
import {getAvailableFonts} from '@remotion/google-fonts';
import {cancelRender, continueRender, delayRender} from 'remotion';

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
  // the cache keeps the raw load (which may reject) so each caller applies its OWN fallback
  return loadEntry(entry).catch(() => fallback);
};

const loadEntry = (entry: NonNullable<ReturnType<typeof findGoogleFont>>): Promise<string> => {
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
  })();
  // a failed load is not cached: the next caller retries it
  p.catch(() => loaded.delete(entry.fontFamily));
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

/**
 * The families a `layer_still` is measured with (review m-25017285, round 2 #4). Strict:
 * - a family the Google Fonts catalogue does not know → the fallback, always (deterministic:
 *   the same props measure and draw the same face every time; the server warns about it);
 * - a known family that fails or does not load within FONT_TIMEOUT_MS → THROWS (`timeout` /
 *   `dependency_failed`), never a silent fallback. Otherwise a transient network hiccup would
 *   store a still in the fallback face under the same job id and object key as the brand-face
 *   still. Plain family names, recorded in the report.
 */
export const resolveBrandFamilies = async (
  headingFamily: string | undefined,
  bodyFamily: string | undefined,
): Promise<{heading: string; body: string}> => {
  const strict = async (family: string | undefined, fallback: string): Promise<string> => {
    const entry = findGoogleFont(family);
    if (!entry) return fallback;
    type Got = {family: string} | {error: string} | {timedOut: true};
    const got = await withTimeout<Got>(
      loadEntry(entry).then(
        (f) => ({family: f}),
        (e: unknown) => ({error: String(e)}),
      ),
      {timedOut: true},
    );
    if ('timedOut' in got) throw new Error(`font '${entry.fontFamily}' did not load within ${FONT_TIMEOUT_MS / 1000} s (timeout)`);
    if ('error' in got) throw new Error(`font '${entry.fontFamily}' failed to load: ${got.error}`);
    return got.family;
  };
  const [heading, body] = await Promise.all([strict(headingFamily, FALLBACK_HEADING), strict(bodyFamily, FALLBACK_BODY)]);
  return {heading, body};
};

const NOT_LOADED = '\u0000font-not-loaded';

/**
 * Draws with EXACTLY the families the layout was measured with. A family that measured fine
 * but then fails to load here fails the render (dependency_failed) instead of silently drawing
 * a different face than the one the boxes were sized for.
 */
export const useExactFamilies = (families: {heading: string; body: string} | null | undefined): Fonts => {
  const heading = families?.heading ?? FALLBACK_HEADING;
  const body = families?.body ?? FALLBACK_BODY;
  const [handle] = useState(() =>
    delayRender(`measured fonts: ${heading} / ${body}`, {timeoutInMilliseconds: FONT_TIMEOUT_MS + 10_000}),
  );
  useEffect(() => {
    const need = (f: string, fallback: string) => (f === fallback ? Promise.resolve(f) : loadFamily(f, NOT_LOADED));
    Promise.all([need(heading, FALLBACK_HEADING), need(body, FALLBACK_BODY)]).then((got) => {
      if (got.includes(NOT_LOADED)) {
        cancelRender(new Error(`font '${got[0] === NOT_LOADED ? heading : body}' measured but failed to load for drawing`));
        return;
      }
      continueRender(handle);
    });
  }, [heading, body, handle]);
  return {heading: `"${heading}", ${GENERIC}`, body: `"${body}", ${GENERIC}`};
};
