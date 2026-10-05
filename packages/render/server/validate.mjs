// Props vs manifest (CONTRACT §1/§2). Python validates first; we re-validate and answer
// 422 invalid_parameters with every problem found, not just the first.
//
// Where each port type lives in the props object:
//   string | number | boolean → props.texts[<name>]
//   image[]                    → props.<name>   (e.g. photos)
//   image                      → props.<name>   (a single asset ref)
//   video                      → props.video
//   brand_kit                  → props.brand
//   product[]                  → props.products
import {HttpError} from './http.mjs';

export const ASSET_SCHEME = 'asset://';

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

const assetRefProblems = (value, where, problems) => {
  if (typeof value !== 'string' || value.length === 0) {
    problems.push(`${where}: expected an asset reference string`);
    return;
  }
  if (!value.startsWith(ASSET_SCHEME) && !/^https?:\/\//.test(value)) {
    problems.push(`${where}: expected 'asset://<assetId>' (got '${value.slice(0, 40)}')`);
  }
};

/**
 * @returns {string[]} problems (empty = valid)
 */
export const validateProps = (manifest, props) => {
  const problems = [];
  if (!isObj(props)) return ['props must be a JSON object'];
  const texts = isObj(props.texts) ? props.texts : {};
  if (props.texts !== undefined && !isObj(props.texts)) problems.push('texts must be an object');

  for (const [name, port] of Object.entries(manifest.inputs ?? {})) {
    const optional = port.optional === true;
    switch (port.type) {
      case 'string': {
        const v = texts[name];
        if (v === undefined || v === null || v === '') {
          if (!optional) problems.push(`texts.${name}: required`);
          break;
        }
        if (typeof v !== 'string') {
          problems.push(`texts.${name}: expected string`);
          break;
        }
        if (typeof port.max === 'number' && [...v].length > port.max) {
          problems.push(`texts.${name}: ${[...v].length} chars exceeds max ${port.max}`);
        }
        if (Array.isArray(port.enum) && !port.enum.includes(v)) {
          problems.push(`texts.${name}: must be one of ${port.enum.join(', ')}`);
        }
        break;
      }
      case 'number': {
        const v = texts[name];
        if (v === undefined || v === null) {
          if (!optional) problems.push(`texts.${name}: required`);
        } else if (typeof v !== 'number' || !Number.isFinite(v)) {
          problems.push(`texts.${name}: expected number`);
        } else {
          if (typeof port.min === 'number' && v < port.min) problems.push(`texts.${name}: below min ${port.min}`);
          if (typeof port.max === 'number' && v > port.max) problems.push(`texts.${name}: above max ${port.max}`);
        }
        break;
      }
      case 'boolean': {
        const v = texts[name];
        if (v === undefined || v === null) {
          if (!optional) problems.push(`texts.${name}: required`);
        } else if (typeof v !== 'boolean') problems.push(`texts.${name}: expected boolean`);
        break;
      }
      case 'image[]': {
        const v = props[name];
        if (v === undefined || v === null) {
          if (!optional) problems.push(`${name}: required (image[])`);
          break;
        }
        if (!Array.isArray(v)) {
          problems.push(`${name}: expected an array of asset references`);
          break;
        }
        if (typeof port.min === 'number' && v.length < port.min) problems.push(`${name}: ${v.length} images, min ${port.min}`);
        if (typeof port.max === 'number' && v.length > port.max) problems.push(`${name}: ${v.length} images, max ${port.max}`);
        v.forEach((ref, i) => assetRefProblems(ref, `${name}[${i}]`, problems));
        break;
      }
      case 'image': {
        const v = props[name];
        if (v === undefined || v === null) {
          if (!optional) problems.push(`${name}: required (image)`);
        } else assetRefProblems(v, name, problems);
        break;
      }
      case 'video': {
        const v = props.video;
        if (v === undefined || v === null) {
          if (!optional) problems.push('video: required');
        } else assetRefProblems(v, 'video', problems);
        break;
      }
      case 'brand_kit': {
        const v = props.brand;
        if (v === undefined || v === null) {
          if (!optional) problems.push('brand: required (brand_kit)');
          break;
        }
        if (!isObj(v)) {
          problems.push('brand: expected an object');
          break;
        }
        if (v.palette !== undefined && !Array.isArray(v.palette)) problems.push('brand.palette: expected string[]');
        if (v.fonts !== undefined && !isObj(v.fonts)) problems.push('brand.fonts: expected object');
        if (v.logo !== undefined && v.logo !== null) assetRefProblems(v.logo, 'brand.logo', problems);
        break;
      }
      case 'product[]': {
        const v = props.products;
        if (v === undefined || v === null) {
          if (!optional) problems.push('products: required (product[])');
          break;
        }
        if (!Array.isArray(v)) {
          problems.push('products: expected an array');
          break;
        }
        v.forEach((p, i) => {
          if (!isObj(p) || typeof p.name !== 'string') problems.push(`products[${i}]: needs a string name`);
          else if (p.photo) assetRefProblems(p.photo, `products[${i}].photo`, problems);
        });
        break;
      }
      default:
        problems.push(`manifest port '${name}' has unknown type '${port.type}'`);
    }
  }
  return problems;
};

export const assertValid = (manifest, props) => {
  const problems = validateProps(manifest, props);
  if (problems.length > 0) {
    throw new HttpError(422, 'invalid_parameters', problems.join('; '), {problems});
  }
};

/** Every `asset://` reference found anywhere in props (deduplicated). */
export const collectAssetRefs = (props) => {
  const ids = new Set();
  const walk = (v) => {
    if (typeof v === 'string') {
      if (v.startsWith(ASSET_SCHEME)) ids.add(v.slice(ASSET_SCHEME.length));
    } else if (Array.isArray(v)) v.forEach(walk);
    else if (isObj(v)) Object.values(v).forEach(walk);
  };
  walk(props);
  return [...ids];
};

/** Deep copy of props with every `asset://id` replaced through `resolve(id)`. */
export const resolveAssetRefs = (props, resolve) => {
  const walk = (v) => {
    if (typeof v === 'string') return v.startsWith(ASSET_SCHEME) ? resolve(v.slice(ASSET_SCHEME.length)) : v;
    if (Array.isArray(v)) return v.map(walk);
    if (isObj(v)) return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x)]));
    return v;
  };
  return walk(props);
};
