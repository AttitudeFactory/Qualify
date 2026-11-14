// The boundary check of the `layer_still` template (m-25017285): a `LayerSpec` (the layer
// Claude writes, ADR 49 §2 and docs/catalogo-disenos-imagen-carrusel.md §1.5/§1.6/§2) plus
// the carousel slide, validated against the catalog block of the manifest. One
// implementation shared by the HTTP server (422 invalid_parameters before a job exists) and
// the composition (calculateMetadata refuses the same props), so the two never disagree.
//
// Plain JavaScript on purpose: the server runs it on Node without a TypeScript step, the
// bundle imports it through webpack; `spec.d.mts` gives the composition its types.
// No imports: the catalog is passed in.

export const SLOTS = ['title', 'subtitle', 'call_phrase'];
export const ROLES = ['cover', 'body', 'closing'];
export const CONTAINER_COLORS = ['surface', 'accent'];
/** Keys a layer may carry that the compositor does not read (provenance and reports). */
export const IGNORED_KEYS = ['layer_id', 'base_has_invented_text', 'fallbacks', 'spec_sha256', 'notes'];
export const LAYER_KEYS = [
  'layout_id',
  'layout_version',
  ...SLOTS,
  'info_blocks',
  'price_ref',
  'anchor',
  'container_color',
  'accent_word',
  'highlight_content',
  'subject_box',
  'logo_in_photo',
  ...IGNORED_KEYS,
];

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isBlank = (v) => v === undefined || v === null || v === '';
/** Characters as a person counts them (code points, not UTF-16 units). */
export const charCount = (s) => [...s].length;
export const wordsOf = (s) => (typeof s === 'string' ? s.trim().split(/\s+/).filter(Boolean) : []);

/**
 * @param {object} catalog  manifest.layer_catalog
 * @param {unknown} layer   props.layer
 * @param {{formats: string[], hasPhoto: boolean, slide?: unknown}} ctx
 * @returns {string[]} problems, empty when valid
 */
export const layerProblems = (catalog, layer, {formats, hasPhoto, slide}) => {
  const problems = [];
  if (!isObj(layer)) return ['layer: expected an object (LayerSpec)'];

  for (const key of Object.keys(layer)) {
    if (!LAYER_KEYS.includes(key)) problems.push(`layer.${key}: unknown field`);
  }
  const layoutId = layer.layout_id;
  const layout = typeof layoutId === 'string' ? catalog.layouts[layoutId] : undefined;
  if (!layout) {
    problems.push(`layer.layout_id: unknown layout '${String(layoutId)}' (one of ${Object.keys(catalog.layouts).join(', ')})`);
    return problems;
  }
  if (layer.layout_version !== catalog.layout_version) {
    problems.push(`layer.layout_version: expected ${catalog.layout_version}, got ${String(layer.layout_version)}`);
  }
  for (const f of formats) {
    if (!layout.formats.includes(f)) problems.push(`layer.layout_id: '${layoutId}' does not exist in ${f}`);
  }

  // text slots: type, presence per format, character limit per format
  for (const slot of SLOTS) {
    const v = layer[slot];
    if (isBlank(v)) continue;
    if (typeof v !== 'string') {
      problems.push(`layer.${slot}: expected a string`);
      continue;
    }
    for (const f of formats) {
      const lim = layout.slots[slot]?.[f];
      if (!lim) {
        problems.push(`layer.${slot}: '${layoutId}' has no ${slot} in ${f}`);
        continue;
      }
      const n = charCount(v.trim());
      if (n > lim[0]) problems.push(`layer.${slot}: ${n} chars exceeds ${lim[0]} for '${layoutId}' in ${f}`);
    }
  }
  if (layoutId === 'brand_fill' && isBlank(layer.title)) problems.push("layer.title: required in 'brand_fill'");

  // parameters
  if (!isBlank(layer.anchor)) {
    if (!layout.anchors.includes(layer.anchor)) {
      problems.push(`layer.anchor: '${String(layer.anchor)}' is not an anchor of '${layoutId}' (${layout.anchors.join(', ') || 'none'})`);
    }
  }
  if (!isBlank(layer.container_color)) {
    if (!layout.container_color) problems.push(`layer.container_color: '${layoutId}' takes none`);
    else if (!CONTAINER_COLORS.includes(layer.container_color)) {
      problems.push(`layer.container_color: must be one of ${CONTAINER_COLORS.join(', ')}`);
    }
  }
  if (layer.accent_word !== undefined && layer.accent_word !== null) {
    const words = wordsOf(layer.title);
    if (!layout.accent_word) problems.push(`layer.accent_word: '${layoutId}' takes none`);
    else if (!Number.isInteger(layer.accent_word) || layer.accent_word < 0 || layer.accent_word >= words.length) {
      problems.push(`layer.accent_word: must be the index of a word of the title (0..${words.length - 1})`);
    }
  }
  if (!isBlank(layer.price_ref)) {
    if (typeof layer.price_ref !== 'string') problems.push('layer.price_ref: expected a product id string');
    else if (!layout.price) problems.push(`layer.price_ref: no price in '${layoutId}'`);
  }

  // information blocks: values come from the business's saved data (Python fills them)
  const blocks = layer.info_blocks;
  if (blocks !== undefined && blocks !== null) {
    if (!Array.isArray(blocks)) problems.push('layer.info_blocks: expected an array');
    else if (!layout.blocks) {
      if (blocks.length > 0) problems.push(`layer.info_blocks: '${layoutId}' takes none`);
    } else {
      const seen = new Set();
      blocks.forEach((b, i) => {
        if (!isObj(b)) return problems.push(`layer.info_blocks[${i}]: expected {kind, value}`);
        for (const k of Object.keys(b)) {
          if (!['kind', 'value', 'label'].includes(k)) problems.push(`layer.info_blocks[${i}].${k}: unknown field`);
        }
        if (!layout.kinds.includes(b.kind)) {
          problems.push(`layer.info_blocks[${i}].kind: '${String(b.kind)}' not allowed in '${layoutId}' (${layout.kinds.join(', ')})`);
        }
        if (seen.has(b.kind)) problems.push(`layer.info_blocks[${i}].kind: '${b.kind}' repeated`);
        seen.add(b.kind);
        if (typeof b.value !== 'string' || b.value.trim() === '') {
          problems.push(`layer.info_blocks[${i}].value: the saved value is required (never written by the model)`);
        } else {
          for (const f of formats) {
            const lim = layout.value?.[f];
            if (lim && charCount(b.value.trim()) > lim[0]) {
              problems.push(`layer.info_blocks[${i}].value: ${charCount(b.value.trim())} chars exceeds ${lim[0]} in ${f}`);
            }
          }
        }
      });
      for (const f of formats) {
        const range = layout.blocks[f];
        if (!range) continue;
        const max = hasPhoto && layoutId === 'info_card' ? range[2] : range[1];
        if (blocks.length < range[0] || blocks.length > max) {
          problems.push(`layer.info_blocks: ${blocks.length} blocks, '${layoutId}' in ${f} takes ${range[0]}–${max}${hasPhoto && layoutId === 'info_card' ? ' with a photo strip' : ''}`);
        }
      }
    }
  } else if (layout.blocks) {
    for (const f of formats) {
      const range = layout.blocks[f];
      if (range && range[0] > 0) problems.push(`layer.info_blocks: '${layoutId}' needs at least ${range[0]} in ${f}`);
    }
  }

  // highlight circle
  const hc = layer.highlight_content;
  if (layoutId === 'highlight_circle') {
    if (!isObj(hc)) problems.push("layer.highlight_content: required in 'highlight_circle' ({type: icon|word|photo})");
    else if (hc.type === 'icon') {
      if (!catalog.highlight_icons.includes(hc.icon_id)) {
        problems.push(`layer.highlight_content.icon_id: '${String(hc.icon_id)}' not in the closed icon set`);
      }
    } else if (hc.type === 'word') {
      const w = typeof hc.word === 'string' ? hc.word.trim() : '';
      if (w === '' || /\s/.test(w)) problems.push('layer.highlight_content.word: one word required');
      else if (charCount(w) > layout.word_max) problems.push(`layer.highlight_content.word: ${charCount(w)} chars exceeds ${layout.word_max}`);
    } else if (hc.type === 'photo') {
      if (!hasPhoto) problems.push("layer.highlight_content: type 'photo' needs photos[0]");
    } else problems.push("layer.highlight_content.type: must be 'icon', 'word' or 'photo'");
  } else if (!isBlank(hc)) problems.push(`layer.highlight_content: only in 'highlight_circle'`);

  // what Claude reports about the photo
  const box = layer.subject_box;
  if (box !== undefined && box !== null) {
    const ok =
      Array.isArray(box) &&
      box.length === 4 &&
      box.every((n) => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1) &&
      box[0] < box[2] &&
      box[1] < box[3];
    if (!ok) problems.push('layer.subject_box: expected [x0, y0, x1, y1], fractions 0–1, x0 < x1, y0 < y1');
  }
  if (layer.logo_in_photo !== undefined && layer.logo_in_photo !== null && typeof layer.logo_in_photo !== 'boolean') {
    problems.push('layer.logo_in_photo: expected a boolean');
  }

  const needsPhoto = ['photo_only', 'plate', 'scrim', 'band'].includes(layoutId);
  if (needsPhoto && !hasPhoto) problems.push(`photos: '${layoutId}' needs the base photo in photos[0]`);

  if (slide !== undefined && slide !== null) problems.push(...slideProblems(slide, formats));
  return problems;
};

/** The carousel slide: 1-based index, 2–10 slides, a role; carousels have no 9:16 (§8.1). */
export const slideProblems = (slide, formats) => {
  const problems = [];
  if (!isObj(slide)) return ['slide: expected {index, total, role}'];
  const {index, total, role} = slide;
  if (!Number.isInteger(total) || total < 2 || total > 10) problems.push('slide.total: integer 2–10');
  if (!Number.isInteger(index) || index < 1 || (Number.isInteger(total) && index > total)) {
    problems.push('slide.index: integer 1..total (1-based)');
  }
  if (!ROLES.includes(role)) problems.push(`slide.role: one of ${ROLES.join(', ')}`);
  if (formats.includes('9:16')) problems.push('slide: a carousel has no 9:16 slide (catalog §8.1)');
  return problems;
};
