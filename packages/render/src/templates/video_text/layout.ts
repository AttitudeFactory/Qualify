// `video_text` v1 (EF-05, m-25026573): where the owner's text over a video goes, decided by the
// SAME engine that draws an ADR 49 image (`layer_still`'s engine.ts, `resolveLayer`), on the
// SAME catalog (layer_still's `layer_catalog`, format 9:16, layout `scrim`). Nothing here
// measures, wraps or sizes text on its own: the line breaks (by word, never inside one), the
// font sizes (112 → 76 px), the line height from the measured ink, the left alignment inside
// the safe zone (x 64–1016, y 270–1536) and the scrim (≥ 60 % black under every line) all come
// from `resolveLayer`. So a text that fits the image's scrim is drawn by the video exactly as
// in a 9:16 image of the same brand: same sizes, same breaks, same boxes.
//
// What the video adds, on a copy of the catalog (the image's own is never changed):
// - the owner's text may run longer than an image title (up to 120 characters, the editor's
//   limit): the title may take `title_lines` lines instead of 2, and when the text is too tall
//   for the scrim's 45 % the scrim grows by `cover_steps` (the text still sits over ≥ 60 %);
// - the place is the owner's: the image's fallback chain (the other anchor, then `band`) is a
//   failure here — a video text never moves by itself;
// - «middle», which the scrim does not have: the lines `resolveLayer` laid out at the top are
//   moved to the canvas' centre and the scrim is mirrored around them (the same gradient on
//   both sides: 75 % at the centre, 60 % at the text's edge plus its padding, transparent at
//   least 10 % of the height further out) — the adaptation the editor's preview already shows.
//
// No React, no runtime imports (only `import type`): the composition passes `resolveLayer` in,
// the Node tests (`server/video-text.test.mjs`) load this file with Node's type stripping.
import type {Catalog, Ink, Input, Measure, Palette, Resolved, TextBlock} from '../layer_still/engine';

export type Place = 'top' | 'middle' | 'bottom';
export const PLACES: readonly Place[] = ['top', 'middle', 'bottom'];
/** The editor's limit (`VIDEO_TEXT_MAX`): the manifest's `text` port says the same. */
export const TEXT_MAX = 120;

export type VideoTextConfig = {
  overlay_revision: number;
  format: '9:16';
  layouts: string[];
  title_lines: number;
  cover_steps: number[];
  middle_center_y: number;
};

export type ScrimBand = {edge: 'top' | 'bottom'; start: number; solid: number; end: number; textAlpha: number; maxAlpha: number};
type Box = {x: number; y: number; w: number; h: number};

export type VideoTextReport = {
  template: 'video_text';
  layout_requested: string;
  layout_rendered: 'scrim';
  layout_version: number;
  place: Place;
  format: '9:16';
  /** the scrim's height as a fraction of the canvas (0.45 = the catalog's own) */
  cover: number;
  /** the title size drawn, px */
  size: number;
  lines: string[];
  /** the text's ink box (every line box), px of the 1080×1920 canvas */
  text_box: Box;
  /** the catalog's 9:16 safe zone the text stays inside [x0, y0, x1, y1] */
  safe: [number, number, number, number];
  fallbacks: string[];
  contrast: Record<string, number>;
  fonts: {heading: string; body: string} | null;
  title_metrics: {line_height: number; gap_after: number} | null;
  /** layer_still's `layer_catalog.engine_revision`: the engine that decided every box */
  engine_revision: number;
  /** this template's own `video_text.overlay_revision` */
  overlay_revision: number;
  /** the image report `resolveLayer` returned, for the record */
  image_report: Resolved['report'];
};

export type VideoTextResolved = {
  width: number;
  height: number;
  scrims: ScrimBand[];
  texts: TextBlock[];
  report: VideoTextReport;
};

export type VideoTextInput = {
  catalog: Catalog;
  config: VideoTextConfig;
  text: string;
  place: string;
  layoutId: string;
  layoutVersion: number;
  headingFamily: string;
  palette: Palette;
  measure: Measure;
  ink?: Ink;
  fonts?: {heading: string; body: string};
  /** layer_still's `resolveLayer` (passed in: this module has no runtime imports) */
  resolve: (input: Input) => Resolved;
};

/** tryScrim's soft part before the gradient reaches 60 %: 10 % of the height (engine.ts). */
const MIN_FADE = 0.1;

const REFUSAL_MARK = 'layer_unrenderable ';

const refuse = (reason: string, detail: string, attempts: string[]): Error =>
  // the same message shape as engine.ts' LayerRefusal, so the server reports it as a refusal
  new Error(
    `invalid_parameters: ${REFUSAL_MARK}${JSON.stringify({
      code: 'layer_unrenderable',
      slot: 'text',
      reason,
      detail,
      format: '9:16',
      layout_requested: 'scrim',
      attempts,
    })}`,
  );

/** Problems with the props (the server answers 422 with them before any render). */
export const videoTextProblems = (catalog: Catalog, config: VideoTextConfig, p: {text: unknown; place: unknown; layoutId: unknown; layoutVersion: unknown}): string[] => {
  const problems: string[] = [];
  const text = typeof p.text === 'string' ? p.text.trim() : '';
  if (!text) problems.push('texts.text: required');
  else if ([...text].length > TEXT_MAX) problems.push(`texts.text: ${[...text].length} chars exceeds max ${TEXT_MAX}`);
  if (!PLACES.includes(p.place as Place)) problems.push(`texts.place: must be one of ${PLACES.join(', ')}`);
  if (typeof p.layoutId !== 'string' || !config.layouts.includes(p.layoutId)) {
    problems.push(`texts.layout_id: must be one of ${config.layouts.join(', ')}`);
  }
  if (p.layoutVersion !== catalog.layout_version) {
    problems.push(`texts.layout_version: the catalog is at ${catalog.layout_version}, got ${String(p.layoutVersion)}`);
  }
  return problems;
};

const blockBox = (texts: TextBlock[]): Box => {
  const rects = texts.flatMap((t) => t.lines.map((l) => ({x: l.x, y: l.y, w: l.width, h: t.size * t.lineHeight})));
  const x0 = Math.min(...rects.map((r) => r.x));
  const y0 = Math.min(...rects.map((r) => r.y));
  const x1 = Math.max(...rects.map((r) => r.x + r.w));
  const y1 = Math.max(...rects.map((r) => r.y + r.h));
  return {x: x0, y: y0, w: x1 - x0, h: y1 - y0};
};

const insideSafe = (b: Box, safe: [number, number, number, number]): boolean =>
  b.x >= safe[0] - 0.5 && b.y >= safe[1] - 0.5 && b.x + b.w <= safe[2] + 0.5 && b.y + b.h <= safe[3] + 0.5;

export const resolveVideoText = (input: VideoTextInput): VideoTextResolved => {
  const {catalog, config} = input;
  const problems = videoTextProblems(catalog, config, {
    text: input.text,
    place: input.place,
    layoutId: input.layoutId,
    layoutVersion: input.layoutVersion,
  });
  if (problems.length > 0) throw new Error(`invalid_parameters: ${problems.join('; ')}`);
  const place = input.place as Place;
  const text = input.text.trim().replace(/\s+/g, ' ');
  const fmt = catalog.formats[config.format];
  const scrimDef = catalog.layouts.scrim;
  // middle is laid out at the top (the lines and sizes are the same) and moved afterwards
  const anchor: 'top' | 'bottom' = place === 'bottom' ? 'bottom' : 'top';
  const attempts: string[] = [];
  let lastReason = 'title_does_not_fit';
  let lastDetail = '';
  for (const cover of config.cover_steps) {
    const derived: Catalog = {
      ...catalog,
      layouts: {
        ...catalog.layouts,
        scrim: {
          ...scrimDef,
          anchors: [anchor],
          default_anchor: anchor,
          cover,
          slots: {title: {[config.format]: [TEXT_MAX, config.title_lines]}},
        },
      },
    };
    let r: Resolved;
    try {
      r = input.resolve({
        catalog: derived,
        format: config.format,
        layer: {
          spec_version: 1,
          layout_id: 'scrim',
          layout_version: input.layoutVersion,
          format: config.format,
          title: text,
          anchor,
        } as Input['layer'],
        photo: null,
        priceText: '',
        isFood: false,
        palette: input.palette,
        headingFamily: input.headingFamily,
        hasLogo: false,
        measure: input.measure,
        ink: input.ink,
        fonts: input.fonts,
      });
    } catch (err) {
      const refusal = (err as {refusal?: {reason?: string; detail?: string}}).refusal;
      if (!refusal) throw err;
      lastReason = refusal.reason ?? lastReason;
      lastDetail = refusal.detail ?? '';
      attempts.push(`scrim/${anchor} cover ${cover}: ${lastReason}`);
      continue;
    }
    if (r.report.layout_rendered !== 'scrim' || r.report.anchor !== anchor || !r.scrim) {
      // the image's chain moved it (other anchor, band): never for a video text
      attempts.push(`scrim/${anchor} cover ${cover}: fell back to ${r.report.layout_rendered}/${String(r.report.anchor)}`);
      lastReason = 'title_does_not_fit';
      continue;
    }
    let texts = r.texts;
    let scrims: ScrimBand[] = [r.scrim];
    let box = blockBox(texts);
    if (place === 'middle') {
      // the scrim's padding between the text and the solid point, as tryScrim drew it
      const pad = r.scrim.solid - (box.y + box.h);
      const centre = config.middle_center_y;
      const dy = centre - (box.y + box.h / 2);
      texts = texts.map((t) => ({...t, lines: t.lines.map((l) => ({...l, y: l.y + dy}))}));
      box = blockBox(texts);
      // same total height as the top/bottom scrim at this cover, never less than the text,
      // its padding and the minimum fade on each side
      const half = Math.max((cover * fmt.height) / 2, box.h / 2 + pad + MIN_FADE * fmt.height);
      const {textAlpha, maxAlpha} = r.scrim;
      scrims = [
        {edge: 'bottom', start: centre - half, solid: box.y - pad, end: centre, textAlpha, maxAlpha},
        {edge: 'top', start: centre + half, solid: box.y + box.h + pad, end: centre, textAlpha, maxAlpha},
      ];
    }
    if (!insideSafe(box, fmt.safe)) {
      attempts.push(`scrim/${place} cover ${cover}: outside_safe_zone`);
      lastReason = 'outside_safe_zone';
      lastDetail = `text at y ${Math.round(box.y)}–${Math.round(box.y + box.h)}, safe zone y ${fmt.safe[1]}–${fmt.safe[3]}`;
      continue;
    }
    const title = texts.find((t) => t.slot === 'title');
    return {
      width: fmt.width,
      height: fmt.height,
      scrims,
      texts,
      report: {
        template: 'video_text',
        layout_requested: input.layoutId,
        layout_rendered: 'scrim',
        layout_version: input.layoutVersion,
        place,
        format: config.format,
        cover,
        size: title?.size ?? 0,
        lines: (title?.lines ?? []).map((l) => l.spans.map((s) => s.text).join('')),
        text_box: {x: Math.round(box.x * 100) / 100, y: Math.round(box.y * 100) / 100, w: Math.round(box.w * 100) / 100, h: Math.round(box.h * 100) / 100},
        safe: fmt.safe,
        fallbacks: attempts,
        contrast: r.report.contrast,
        fonts: r.report.fonts,
        title_metrics: r.report.title_metrics,
        engine_revision: catalog.engine_revision,
        overlay_revision: config.overlay_revision,
        image_report: r.report,
      },
    };
  }
  throw refuse(lastReason, lastDetail, attempts);
};
