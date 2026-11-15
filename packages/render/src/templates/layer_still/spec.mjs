// The boundary check of the `layer_still` template (m-25017285): a `LayerSpec` v1 — the shape
// m-25017283 defines (`qualify_creative.layer_spec`, layer_spec_v1.schema.json; field names
// are theirs) — validated against the catalog block of the manifest
// (docs/catalogo-disenos-imagen-carrusel.md §1.5/§1.6/§2/§6). One implementation shared by
// the HTTP server (422 invalid_parameters before a job exists) and the composition
// (calculateMetadata refuses the same props), so the two never disagree.
//
// Plain JavaScript on purpose: the server runs it on Node without a TypeScript step, the
// bundle imports it through webpack; `spec.d.mts` gives the composition its types.
// No imports: the catalog is passed in. The free-text rules of §1.8 (no currency, phone,
// hour, forbidden titles) are the layer stage's; the compositor checks shape and limits.

export const SLOTS = ['title', 'subtitle', 'call_phrase'];
export const ROLES = ['cover', 'body', 'closing'];
export const CONTAINER_COLORS = ['surface', 'accent'];
export const HIGHLIGHT_KINDS = ['icon', 'word', 'photo'];
/** Keys of LayerSpec v1 the compositor accepts. `fallbacks` is written by the compositor
 * (ignored on input); `layer_id` is an optional label echoed in the report. */
export const LAYER_KEYS = [
  'spec_version',
  'layout_id',
  'layout_version',
  'format',
  'photo',
  'anchor',
  'container_color',
  'accent_word',
  ...SLOTS,
  'info_blocks',
  'price_ref',
  'highlight_content',
  'photo_strip',
  'carousel',
  'fallbacks',
  'layer_id',
];

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isBlank = (v) => v === undefined || v === null || v === '';
/** Characters as a person counts them (code points, not UTF-16 units). */
export const charCount = (s) => [...s].length;
export const wordsOf = (s) => (typeof s === 'string' ? s.trim().split(/\s+/).filter(Boolean) : []);

const unknownKeys = (obj, allowed, where, problems) => {
  for (const k of Object.keys(obj)) if (!allowed.includes(k)) problems.push(`${where}.${k}: unknown field`);
};

/**
 * @param {object} catalog  manifest.layer_catalog
 * @param {unknown} layer   props.layer (LayerSpec v1)
 * @param {{formats: string[], hasPhoto: boolean}} ctx  the formats of the requested ports
 * @returns {string[]} problems, empty when valid
 */
export const layerProblems = (catalog, layer, {formats, hasPhoto}) => {
  const problems = [];
  if (!isObj(layer)) return ['layer: expected an object (LayerSpec)'];
  unknownKeys(layer, LAYER_KEYS, 'layer', problems);

  if (layer.spec_version !== undefined && layer.spec_version !== 1) {
    problems.push(`layer.spec_version: expected 1, got ${String(layer.spec_version)}`);
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
  if (!isBlank(layer.format)) {
    for (const f of formats) {
      if (layer.format !== f) problems.push(`layer.format: the spec is for ${String(layer.format)}, the port renders ${f}`);
    }
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

  // parameters (§1.6)
  if (!isBlank(layer.anchor) && !layout.anchors.includes(layer.anchor)) {
    problems.push(`layer.anchor: '${String(layer.anchor)}' is not an anchor of '${layoutId}' (${layout.anchors.join(', ') || 'none'})`);
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
    if (!isObj(layer.price_ref) || typeof layer.price_ref.product_id !== 'string' || layer.price_ref.product_id === '') {
      problems.push('layer.price_ref: expected {product_id}');
    } else {
      unknownKeys(layer.price_ref, ['product_id'], 'layer.price_ref', problems);
      if (!layout.price) problems.push(`layer.price_ref: no price in '${layoutId}'`);
    }
  }

  // what Claude reports about the photo (§1.2)
  const photo = layer.photo;
  if (photo !== undefined && photo !== null) {
    if (!isObj(photo)) problems.push('layer.photo: expected {subject_box, logo_in_photo, base_has_invented_text}');
    else {
      unknownKeys(photo, ['subject_box', 'logo_in_photo', 'base_has_invented_text'], 'layer.photo', problems);
      const box = photo.subject_box;
      const ok =
        Array.isArray(box) &&
        box.length === 4 &&
        box.every((n) => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1) &&
        box[0] < box[2] &&
        box[1] < box[3];
      if (!ok) problems.push('layer.photo.subject_box: expected [x0, y0, x1, y1], fractions 0–1, x0 < x1, y0 < y1');
      if (typeof photo.logo_in_photo !== 'boolean') problems.push('layer.photo.logo_in_photo: expected a boolean');
      if (photo.base_has_invented_text !== undefined && typeof photo.base_has_invented_text !== 'boolean') {
        problems.push('layer.photo.base_has_invented_text: expected a boolean');
      }
    }
  }

  // information blocks (§1.5): fixed label, the business's saved value
  const blocks = layer.info_blocks;
  const strip = layer.photo_strip === true;
  if (layer.photo_strip !== undefined && typeof layer.photo_strip !== 'boolean') problems.push('layer.photo_strip: expected a boolean');
  if (strip && layoutId !== 'info_card') problems.push(`layer.photo_strip: only in 'info_card'`);
  if (strip && !hasPhoto) problems.push('layer.photo_strip: needs the photo in photos[0]');
  if (blocks !== undefined && blocks !== null) {
    if (!Array.isArray(blocks)) problems.push('layer.info_blocks: expected an array');
    else if (!layout.blocks) {
      if (blocks.length > 0) problems.push(`layer.info_blocks: '${layoutId}' takes none`);
    } else {
      const seen = new Set();
      blocks.forEach((b, i) => {
        if (!isObj(b)) return problems.push(`layer.info_blocks[${i}]: expected {kind, label, value}`);
        unknownKeys(b, ['kind', 'label', 'value'], `layer.info_blocks[${i}]`, problems);
        if (!layout.kinds.includes(b.kind)) {
          problems.push(`layer.info_blocks[${i}].kind: '${String(b.kind)}' not allowed in '${layoutId}' (${layout.kinds.join(', ')})`);
        }
        const fixed = catalog.info_kinds[b.kind]?.label;
        if (b.label !== undefined && fixed && b.label !== fixed) {
          problems.push(`layer.info_blocks[${i}].label: the label of a ${b.kind} block is «${fixed}»`);
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
        const max = strip ? range[2] : range[1];
        if (blocks.length < range[0] || blocks.length > max) {
          problems.push(`layer.info_blocks: ${blocks.length} blocks, '${layoutId}' in ${f} takes ${range[0]}–${max}${strip ? ' with a photo strip' : ''}`);
        }
      }
    }
  } else if (layout.blocks) {
    for (const f of formats) {
      const range = layout.blocks[f];
      if (range && range[0] > 0) problems.push(`layer.info_blocks: '${layoutId}' needs at least ${range[0]} in ${f}`);
    }
  }

  // highlight circle (§2.7)
  const hc = layer.highlight_content;
  if (layoutId === 'highlight_circle') {
    if (!isObj(hc)) problems.push("layer.highlight_content: required in 'highlight_circle' ({kind: icon|word|photo})");
    else {
      unknownKeys(hc, ['kind', 'icon_id', 'word'], 'layer.highlight_content', problems);
      if (hc.kind === 'icon') {
        if (!catalog.highlight_icons.includes(hc.icon_id)) {
          problems.push(`layer.highlight_content.icon_id: '${String(hc.icon_id)}' not in the closed icon set`);
        }
      } else if (hc.kind === 'word') {
        const w = typeof hc.word === 'string' ? hc.word.trim() : '';
        if (w === '' || /\s/.test(w)) problems.push('layer.highlight_content.word: one word required');
        else if (charCount(w) > layout.word_max) problems.push(`layer.highlight_content.word: ${charCount(w)} chars exceeds ${layout.word_max}`);
      } else if (hc.kind === 'photo') {
        if (!hasPhoto) problems.push("layer.highlight_content: kind 'photo' needs photos[0]");
      } else problems.push(`layer.highlight_content.kind: one of ${HIGHLIGHT_KINDS.join(', ')}`);
    }
  } else if (!isBlank(hc)) problems.push(`layer.highlight_content: only in 'highlight_circle'`);

  const needsPhoto = ['photo_only', 'plate', 'scrim', 'band'].includes(layoutId);
  if (needsPhoto && !hasPhoto) problems.push(`photos: '${layoutId}' needs the base photo in photos[0]`);

  if (layer.carousel !== undefined && layer.carousel !== null) problems.push(...carouselProblems(layer.carousel, formats));
  return problems;
};

/** The carousel place (§6): 0-based index below count (2–10); the role follows the index;
 * carousels have no 9:16 (§8.1). */
export const carouselProblems = (c, formats) => {
  const problems = [];
  if (!isObj(c)) return ['layer.carousel: expected {role, index, count}'];
  unknownKeys(c, ['role', 'index', 'count'], 'layer.carousel', problems);
  const {index, count, role} = c;
  if (!Number.isInteger(count) || count < 2 || count > 10) problems.push('layer.carousel.count: integer 2–10');
  if (!Number.isInteger(index) || index < 0 || (Number.isInteger(count) && index >= count)) {
    problems.push('layer.carousel.index: integer 0..count-1 (0-based)');
  }
  if (!ROLES.includes(role)) problems.push(`layer.carousel.role: one of ${ROLES.join(', ')}`);
  else if (Number.isInteger(index) && Number.isInteger(count)) {
    const expected = index === 0 ? 'cover' : index === count - 1 ? 'closing' : 'body';
    if (role !== expected) problems.push(`layer.carousel.role: slide ${index + 1} of ${count} is the ${expected}`);
  }
  if (formats.includes('9:16')) problems.push('layer.carousel: a carousel has no 9:16 slide (catalog §8.1)');
  return problems;
};
