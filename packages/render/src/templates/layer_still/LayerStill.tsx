// `layer_still` v1 (m-25017285, ADR 49 §2 «Remotion compone»): one still from a base photo,
// the LayerSpec Claude wrote, the brand kit and the format — the seven layouts of
// docs/catalogo-disenos-imagen-carrusel.md.
//
// Where the checks run: in `calculateMetadata`, inside Chromium, before the frame is drawn.
// That is the only place with the brand's real fonts and a real text measurer, so «does it
// fit at the minimum size» is measured, not estimated. It validates the props (spec.mjs, the
// same check the server answers 422 with), measures the photo, runs the deterministic engine
// (engine.ts: sizes, line breaks, contrast, subject box, safe zones, fallback chain) and
// returns the props with `resolved` added. The server reads `resolved.report` from
// selectComposition and puts it on the job output, so Python records the layout actually
// rendered and every fallback. The component only draws `resolved`: every line is placed
// explicitly with `white-space: nowrap`, so what is drawn is what was measured.
//
// Legibility never comes from glyph outlines or text shadows (catalog §1.3): only opaque
// plates/bands/fills, or the scrim (≥ 60 % black under every line).
import React from 'react';
import {AbsoluteFill, Img, type CalculateMetadataFunction} from 'remotion';
import manifest from '../../../templates/layer_still/manifest.json';
import {loadFamily, useBrandFonts, FALLBACK_BODY, FALLBACK_HEADING} from '../../fonts';
import {normalizeProps, paletteOf, type PropsInput} from '../../props';
import {resolveLayer, type Catalog, type Format, type LayerSpec, type Resolved} from './engine';
import {Icon} from './icons';
import {layerProblems} from './spec.mjs';

export const CATALOG = manifest.layer_catalog as unknown as Catalog;
type PortSpec = {kind: string; width: number; height: number; composition: string; format: Format};
export const PORTS = manifest.outputs as unknown as Record<string, PortSpec>;

export type LayerStillProps = PropsInput & {
  /** the LayerSpec of m-25017283 (carousel place, photo reading and price ref inside it) */
  layer: LayerSpec;
  resolved?: Resolved | null;
};

const formatOf = (port: string | undefined): Format => {
  const spec = port ? PORTS[port] : undefined;
  if (!spec) throw new Error(`invalid_parameters: unknown port '${String(port)}' for layer_still`);
  return spec.format;
};

const quoted = (family: string): string => `"${family.replace(/"/g, '')}", sans-serif`;

const naturalSize = async (src: string): Promise<{width: number; height: number}> => {
  const img = new Image();
  img.src = src;
  try {
    await img.decode();
  } catch {
    throw new Error(`Could not load image ${src.slice(0, 80)} (layer_still base photo)`);
  }
  return {width: img.naturalWidth, height: img.naturalHeight};
};

export const layerStillMetadata: CalculateMetadataFunction<LayerStillProps> = async ({props}) => {
  const base = normalizeProps(props);
  const format = formatOf(base.meta?.port);
  const photoSrc = base.photos[0] ?? '';
  const problems = layerProblems(CATALOG, props.layer, {formats: [format], hasPhoto: !!photoSrc});
  if (problems.length > 0) throw new Error(`invalid_parameters: ${problems.join('; ')}`);

  const headingFamily = await loadFamily(base.brand.fonts.heading, FALLBACK_HEADING);
  const bodyFamily = await loadFamily(base.brand.fonts.body, FALLBACK_BODY);
  await document.fonts.ready;
  const canvas = document.createElement('canvas');
  const g = canvas.getContext('2d');
  if (!g) throw new Error('layer_still: no 2D canvas to measure text');
  const measure = (text: string, f: {role: 'heading' | 'body'; size: number; weight: number}): number => {
    g.font = `${f.weight} ${f.size}px ${quoted(f.role === 'heading' ? headingFamily : bodyFamily)}`;
    return g.measureText(text).width;
  };
  const photo = photoSrc ? await naturalSize(photoSrc) : null;
  const texts = base.texts;
  const resolved = resolveLayer({
    catalog: CATALOG,
    format,
    layer: props.layer,
    photo,
    priceText: typeof texts.price_text === 'string' ? texts.price_text : '',
    isFood: texts.is_food === true,
    palette: paletteOf(base.brand),
    headingFamily: base.brand.fonts.heading ?? '',
    hasLogo: !!base.brand.logo,
    measure,
  });
  return {props: {...props, resolved}};
};

const Photo: React.FC<{src: string; placement: NonNullable<Resolved['photo']>}> = ({src, placement}) => {
  const {window: win, box, fit, circle} = placement;
  return (
    <div
      style={{
        position: 'absolute',
        left: win.x,
        top: win.y,
        width: win.w,
        height: win.h,
        overflow: 'hidden',
        borderRadius: circle ? '50%' : 0,
        background: '#111827',
      }}
    >
      {fit === 'contain' ? (
        <Img
          src={src}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            transform: 'scale(1.25)',
            filter: 'blur(40px) brightness(0.7)',
          }}
        />
      ) : null}
      <Img
        src={src}
        style={{position: 'absolute', left: box.x - win.x, top: box.y - win.y, width: box.w, height: box.h}}
      />
    </div>
  );
};

const Scrim: React.FC<{scrim: NonNullable<Resolved['scrim']>}> = ({scrim}) => {
  const top = Math.min(scrim.start, scrim.end);
  const height = Math.abs(scrim.end - scrim.start);
  // gradient runs from the transparent start towards the edge
  const solidPct = (Math.abs(scrim.solid - scrim.start) / height) * 100;
  const dir = scrim.edge === 'bottom' ? '180deg' : '0deg';
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        top,
        height,
        background: `linear-gradient(${dir}, rgba(0,0,0,0) 0%, rgba(0,0,0,${scrim.textAlpha}) ${solidPct.toFixed(2)}%, rgba(0,0,0,${scrim.maxAlpha}) 100%)`,
      }}
    />
  );
};

export const LayerStill: React.FC<LayerStillProps> = (raw) => {
  const props = normalizeProps(raw);
  const fonts = useBrandFonts(props.brand.fonts.heading, props.brand.fonts.body);
  const resolved = raw.resolved;
  if (!resolved) {
    // calculateMetadata always sets it; without it nothing was checked, so draw nothing
    return <AbsoluteFill style={{background: '#000'}} />;
  }
  const photo = props.photos[0] ?? '';
  const logo = props.brand.logo ?? null;
  return (
    <AbsoluteFill style={{background: resolved.background}}>
      {resolved.photo && photo ? <Photo src={photo} placement={resolved.photo} /> : null}
      {resolved.scrim ? <Scrim scrim={resolved.scrim} /> : null}
      {resolved.containers.map((c, i) => (
        <div
          key={`c${i}`}
          style={{position: 'absolute', left: c.rect.x, top: c.rect.y, width: c.rect.w, height: c.rect.h, background: c.color, borderRadius: c.radius}}
        />
      ))}
      {resolved.icons.map((ic, i) => (
        <Icon key={`i${i}`} {...ic} />
      ))}
      {resolved.texts.flatMap((t) =>
        t.lines.map((l, li) => (
          <div
            key={`${t.slot}-${li}`}
            style={{
              position: 'absolute',
              left: l.x,
              top: l.y,
              fontFamily: t.role === 'heading' ? fonts.heading : fonts.body,
              fontWeight: t.weight,
              fontSize: t.size,
              lineHeight: `${t.size * t.lineHeight}px`,
              whiteSpace: 'nowrap',
              letterSpacing: 0,
            }}
          >
            {l.spans.map((s, si) => (
              <span key={si} style={{color: s.color}}>
                {s.text}
              </span>
            ))}
          </div>
        )),
      )}
      {resolved.logo && logo ? (
        <div
          style={{
            position: 'absolute',
            left: resolved.logo.rect.x,
            top: resolved.logo.rect.y,
            width: resolved.logo.rect.w,
            height: resolved.logo.rect.h,
            borderRadius: resolved.logo.radius,
            background: resolved.logo.tile,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden',
          }}
        >
          <Img src={logo} style={{width: '82%', height: '82%', objectFit: 'contain'}} />
        </div>
      ) : null}
      {resolved.counter ? (
        <div
          style={{
            position: 'absolute',
            left: resolved.counter.rect.x,
            top: resolved.counter.rect.y,
            width: resolved.counter.rect.w,
            height: resolved.counter.rect.h,
            background: resolved.counter.background ?? 'transparent',
            borderRadius: 16,
            color: resolved.counter.color,
            fontFamily: fonts.body,
            fontWeight: 600,
            fontSize: resolved.counter.size,
            lineHeight: `${resolved.counter.rect.h}px`,
            textAlign: 'center',
            whiteSpace: 'nowrap',
          }}
        >
          {resolved.counter.text}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
