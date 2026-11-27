// `brand_still` v0 (spike m-25042530): draws ONE recipe of a BrandVisualSystem (data) with the
// owner's slot data. The component library below is parametric: colours are roles (or literal
// hex), faces come from the system's typography, geometry from the recipe's blocks (canvas
// fractions). A new brand is a new JSON document, never new React.
//
// The component proportions (paddings in em, clip-paths, shadow offsets) were ported 1:1 from
// the Bianki generator (`gen.py` / `stories.py`, HTML → Chrome), so a transcription of Bianki's
// system reproduces those flyers; other brands vary them through tokens and variants.
//
// Rules kept from the rest of packages/render: no network beyond fonts, no randomness (the
// confetti uses a PRNG seeded by the system id), every text line is fitted by measurement.
import React, {useLayoutEffect, useRef, useState} from 'react';
import {AbsoluteFill, Img, continueRender, delayRender, staticFile} from 'remotion';
import {caseOf, fitSize, loadFace, measure, type LoadedFace} from './fit';
import type {Background, Block, BrandStillProps, BrandVisualSystem, ColorRef, Components, Content, FlagShape, StackItem} from './types';

export const W = 1080;
export const FORMATS = {'4:5': {width: 1080, height: 1350}, '1:1': {width: 1080, height: 1080}, '9:16': {width: 1080, height: 1920}} as const;

// ------------------------------------------------------------------ helpers
type Faces = {display: LoadedFace; body: LoadedFace; label: LoadedFace};
type Ctx = {sys: BrandVisualSystem; comp: Components; faces: Faces; H: number; content: Content; warnings: string[]};

export const asset = (src: string): string => (/^(https?:|data:|blob:)/.test(src) ? src : staticFile(src.replace(/^\//, '')));

const color = (ctx: Ctx, ref: ColorRef | undefined, fallback: ColorRef = 'ink'): string => {
  const r = ref ?? fallback;
  if (r.startsWith('#')) return r;
  const v = (ctx.sys.colors as Record<string, string | null | undefined>)[r];
  return v ?? '#000000';
};
/** #RRGGBB + alpha (0–1) → #RRGGBBAA */
const alpha = (hex: string, a: number): string => `${hex.slice(0, 7)}${Math.round(a * 255).toString(16).padStart(2, '0')}`;
const deep = (ctx: Ctx): string => ctx.sys.colors.shadow_deep ?? ctx.sys.colors.shadow;

const get = (content: Content, path: string | null | undefined): unknown => {
  if (!path) return undefined;
  return path.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined), content);
};
const str = (v: unknown): string => (typeof v === 'string' ? v : typeof v === 'number' ? String(v) : '');

const tilt = (ctx: Ctx): number => ctx.sys.shapes?.tilt_deg ?? -3;
const hardShadow = (ctx: Ctx, dx: number, dy: number): string => {
  const kind = ctx.sys.shapes?.shadow ?? 'hard';
  if (kind === 'none') return 'none';
  if (kind === 'soft') return `0 ${dy}px ${dy * 2.4}px ${alpha(deep(ctx), 0.45)}`;
  return `${dx}px ${dy}px 0 ${ctx.sys.colors.shadow}`;
};
const dropShadow = (ctx: Ctx, dx: number, dy: number): string => {
  const kind = ctx.sys.shapes?.shadow ?? 'hard';
  if (kind === 'none') return 'none';
  if (kind === 'soft') return `drop-shadow(0 ${dy}px ${dy * 2}px ${alpha(deep(ctx), 0.45)})`;
  return `drop-shadow(${dx}px ${dy}px 0 ${ctx.sys.colors.shadow})`;
};
const fontOf = (f: LoadedFace, size: number, weight?: number): React.CSSProperties => ({
  fontFamily: f.css,
  fontWeight: weight ?? f.weight,
  fontSize: size,
  letterSpacing: `${f.letter_spacing_em ?? 0}em`,
});

// Seeded PRNG (mulberry32) so decorations are deterministic.
const prng = (seedText: string) => {
  let a = 0;
  for (let i = 0; i < seedText.length; i++) a = (Math.imul(31, a) + seedText.charCodeAt(i)) | 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

// ------------------------------------------------------------------ background
const BackgroundLayers: React.FC<{ctx: Ctx; bg: Background}> = ({ctx, bg}) => {
  const c = ctx.sys.colors;
  const base = bg.base ?? 'radial';
  const baseCss =
    base === 'solid'
      ? c.background
      : base === 'linear'
        ? `linear-gradient(180deg, ${c.background_alt} 0, ${c.background} 60%, ${c.background_edge ?? c.background} 100%)`
        : `radial-gradient(ellipse at 50% 42%, ${c.background_alt} 0, ${c.background} 45%, ${c.background_edge ?? c.background} 100%)`;
  return (
    <>
      <AbsoluteFill style={{background: baseCss}} />
      {(bg.layers ?? []).map((l, i) => {
        const col = color(ctx, l.color, 'pop');
        const op = l.opacity ?? 0.3;
        const s = l.scale ?? 1;
        const [cx, cy] = l.center ?? [0.5, 0.42];
        const key = `bg-${i}`;
        switch (l.kind) {
          case 'rays':
            return (
              <div
                key={key}
                style={{
                  position: 'absolute',
                  left: `${cx * 100}%`,
                  top: `${cy * 100}%`,
                  width: 3200,
                  height: 3200,
                  margin: '-1600px 0 0 -1600px',
                  background: `repeating-conic-gradient(from ${l.angle_deg ?? 3}deg, ${col} 0deg ${9 * s}deg, transparent ${9 * s}deg ${18 * s}deg)`,
                  opacity: op,
                }}
              />
            );
          case 'rings':
            return (
              <div
                key={key}
                style={{
                  position: 'absolute',
                  inset: '-20%',
                  opacity: op,
                  background: `repeating-radial-gradient(circle at ${cx * 100}% ${cy * 100}%, transparent 0 ${34 * s}px, ${col} ${35 * s}px ${38 * s}px, transparent ${39 * s}px ${72 * s}px)`,
                }}
              />
            );
          case 'dots':
            return (
              <AbsoluteFill
                key={key}
                style={{opacity: op, backgroundImage: `radial-gradient(${col} ${7 * s}px, transparent ${7.5 * s}px)`, backgroundSize: `${44 * s}px ${44 * s}px`, transform: `rotate(${l.angle_deg ?? 0}deg) scale(1.5)`}}
              />
            );
          case 'stripes':
            return (
              <AbsoluteFill
                key={key}
                style={{opacity: op, background: `repeating-linear-gradient(${l.angle_deg ?? 45}deg, ${col} 0 ${22 * s}px, transparent ${22 * s}px ${44 * s}px)`}}
              />
            );
          case 'grid':
            return (
              <AbsoluteFill
                key={key}
                style={{
                  opacity: op,
                  backgroundImage: `linear-gradient(${col} 2px, transparent 2px), linear-gradient(90deg, ${col} 2px, transparent 2px)`,
                  backgroundSize: `${60 * s}px ${60 * s}px`,
                }}
              />
            );
          case 'waves': {
            const w = 160 * s;
            const h = 48 * s;
            const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='${w}' height='${h}'><path d='M0 ${h / 2} Q ${w / 4} 0 ${w / 2} ${h / 2} T ${w} ${h / 2}' fill='none' stroke='${col}' stroke-width='${5 * s}' stroke-linecap='round'/></svg>`;
            return (
              <AbsoluteFill
                key={key}
                style={{opacity: op, backgroundImage: `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`, backgroundSize: `${w}px ${h}px`, transform: `rotate(${l.angle_deg ?? 0}deg) scale(1.6)`}}
              />
            );
          }
          case 'pattern_image':
            return l.image ? (
              <AbsoluteFill key={key} style={{opacity: op, backgroundImage: `url("${asset(l.image)}")`, backgroundSize: `${520 * s}px auto`, transform: `rotate(${l.angle_deg ?? 0}deg) scale(1.4)`}} />
            ) : null;
          case 'blobs': {
            const r = prng(`${ctx.sys.id}-blobs-${i}`);
            return (
              <AbsoluteFill key={key} style={{opacity: op}}>
                {[0, 1, 2].map((k) => {
                  const d = (420 + r() * 380) * s;
                  return (
                    <div
                      key={k}
                      style={{position: 'absolute', width: d, height: d, borderRadius: '42% 58% 63% 37% / 41% 44% 56% 59%', background: col, left: `${r() * 100}%`, top: `${r() * 100}%`, transform: `translate(-50%,-50%) rotate(${r() * 360}deg)`}}
                    />
                  );
                })}
              </AbsoluteFill>
            );
          }
          case 'confetti': {
            const r = prng(`${ctx.sys.id}-confetti-${i}`);
            return (
              <AbsoluteFill key={key} style={{opacity: op}}>
                {Array.from({length: 46}, (_, k) => {
                  const sz = (10 + r() * 22) * s;
                  const round = r() > 0.5;
                  return (
                    <div
                      key={k}
                      style={{position: 'absolute', left: `${r() * 100}%`, top: `${r() * 100}%`, width: sz, height: round ? sz : sz * 0.4, borderRadius: round ? '50%' : 4, background: col, transform: `rotate(${r() * 180}deg)`}}
                    />
                  );
                })}
              </AbsoluteFill>
            );
          }
          case 'grain':
            return (
              <AbsoluteFill key={key} style={{opacity: op, mixBlendMode: 'multiply'}}>
                <svg width="100%" height="100%">
                  <filter id={`grain-${i}`}>
                    <feTurbulence type="fractalNoise" baseFrequency={0.9 / s} numOctaves={2} seed={3} />
                    <feColorMatrix type="saturate" values="0" />
                  </filter>
                  <rect width="100%" height="100%" filter={`url(#grain-${i})`} />
                </svg>
              </AbsoluteFill>
            );
          default:
            return null;
        }
      })}
    </>
  );
};

// ------------------------------------------------------------------ inline markup of body text
// `[[300 g]]` → chip · `**Av. Los Agustinos**` → strong (accent, caps) · `__«La Machiri»__` → bold,
// no wrap · `\n` → line break. Data stays plain text; the markers are the only markup.
const Rich: React.FC<{ctx: Ctx; text: string}> = ({ctx, text}) => {
  const b = ctx.comp.body ?? {};
  const out: React.ReactNode[] = [];
  const re = /\[\[(.+?)\]\]|\*\*(.+?)\*\*|__(.+?)__|\n/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] !== undefined)
      out.push(
        <strong key={k++} style={{display: 'inline-block', background: color(ctx, b.chip_fill, 'surface'), color: color(ctx, b.chip_ink, 'background'), padding: '0 .3em', borderRadius: '.2em', textShadow: 'none', fontWeight: 900}}>
          {m[1]}
        </strong>,
      );
    else if (m[2] !== undefined)
      out.push(
        <b key={k++} style={{color: color(ctx, b.strong_color, 'accent'), textTransform: b.strong_uppercase === false ? 'none' : 'uppercase', letterSpacing: '.04em'}}>
          {m[2]}
        </b>,
      );
    else if (m[3] !== undefined)
      out.push(
        <b key={k++} style={{whiteSpace: 'nowrap'}}>
          {m[3]}
        </b>,
      );
    else out.push(<br key={k++} />);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
};

// ------------------------------------------------------------------ text items
const Tag: React.FC<{ctx: Ctx; text: string; size: number; maxW: number}> = ({ctx, text, size, maxW}) => {
  const t = ctx.comp.tag ?? {};
  const f = ctx.faces.label;
  const v = t.variant ?? 'tilted_block';
  // padding .8em each side → the text gets maxW - 1.6em (+ shadow)
  const s = fitSize(f, text, maxW / 1.0 - 1.9 * size, size, size * 0.5, 900) ?? size * 0.5;
  const fill = color(ctx, t.fill, 'accent');
  const ink = color(ctx, t.ink, 'on_accent');
  const base: React.CSSProperties = {...fontOf(f, s, 900), display: 'inline-block', whiteSpace: 'nowrap', lineHeight: 'normal'};
  if (v === 'pill') return <span style={{...base, background: fill, color: ink, padding: '.45em .9em', borderRadius: 999, boxShadow: hardShadow(ctx, 0, 6)}}>{caseOf(f, text)}</span>;
  if (v === 'outline') return <span style={{...base, color: fill, padding: '.4em .8em', border: `${Math.max(3, s * 0.1)}px solid ${fill}`, borderRadius: ctx.sys.shapes?.radius_px ?? 0}}>{caseOf(f, text)}</span>;
  if (v === 'underline') return <span style={{...base, color: fill, paddingBottom: '.2em', borderBottom: `${Math.max(4, s * 0.14)}px solid ${fill}`}}>{caseOf(f, text)}</span>;
  if (v === 'plain') return <span style={{...base, color: fill}}>{caseOf(f, text)}</span>;
  return (
    <span style={{...base, background: fill, color: ink, transform: `rotate(${tilt(ctx)}deg)`, padding: '.45em .8em', boxShadow: (ctx.sys.shapes?.shadow ?? 'hard') === 'none' ? 'none' : `.22em .22em 0 ${ctx.sys.colors.shadow}`}}>
      {caseOf(f, text)}
    </span>
  );
};

const splitTitle = (text: string, how: 'first_word' | 'last_word' | 'none'): [string, string] => {
  const words = text.trim().split(/\s+/);
  if (how === 'none' || words.length < 2) return [text.trim(), ''];
  if (how === 'last_word') return [words.slice(0, -1).join(' '), words[words.length - 1] ?? ''];
  return [words[0] ?? '', words.slice(1).join(' ')];
};

const Headline: React.FC<{ctx: Ctx; text: string; size: number; maxW: number}> = ({ctx, text, size, maxW}) => {
  const h = ctx.comp.headline ?? {};
  const f = ctx.faces.display;
  const explicit = text.split('|');
  const [l1, l2] = explicit.length === 2 ? [explicit[0]!.trim(), explicit[1]!.trim()] : splitTitle(text, h.split ?? 'first_word');
  const lines = [l1, l2].filter(Boolean);
  const sizes = lines.map((l) => fitSize(f, l, maxW, size, size * 0.4) ?? size * 0.4);
  const s = Math.min(...sizes);
  const first = color(ctx, h.first_color, 'ink');
  const second = color(ctx, h.second_color, 'accent');
  const shadow = h.shadow === false || (ctx.sys.shapes?.shadow ?? 'hard') === 'none' ? 'none' : `0 7px 0 ${ctx.sys.colors.shadow}, 0 14px 30px ${alpha(deep(ctx), 0.5)}`;
  const variant = h.variant ?? 'two_tone_stacked';
  const lineStyle = (i: number): React.CSSProperties => {
    if (i === 0) return {color: first};
    if (variant === 'single_color') return {color: first};
    if (variant === 'outline_second') return {color: 'transparent', WebkitTextStroke: `${Math.max(2, s * 0.035)}px ${second}`, textShadow: 'none'};
    if (variant === 'highlight_second')
      return {color: color(ctx, ctx.comp.tag?.ink, 'on_accent'), background: second, display: 'inline-block', padding: '0 .12em', textShadow: 'none', transform: `rotate(${tilt(ctx) / 2}deg)`};
    return {color: second};
  };
  return (
    <div style={{...fontOf(f, s), lineHeight: f.line_height ?? 0.98, textShadow: shadow, whiteSpace: 'nowrap'}}>
      {lines.map((l, i) => (
        <div key={i}>
          <span style={lineStyle(i)}>{caseOf(f, l)}</span>
        </div>
      ))}
    </div>
  );
};

type Price = {amount: string; symbol?: string; code?: string; secondary?: string};

const FLAG_CLIP: Record<FlagShape, string> = {
  pennant: 'polygon(0 0,100% 0,93% 50%,100% 100%,0 100%)',
  double: 'polygon(4% 0,96% 0,100% 50%,96% 100%,4% 100%,0 50%)',
  arrow: 'polygon(0 0,96% 0,100% 50%,96% 100%,0 100%)',
  rect: 'none',
};
const FLAG_PAD: Record<FlagShape, [number, number, number, number]> = {
  pennant: [0.16, 0.8, 0.2, 0.35],
  double: [0.18, 0.9, 0.22, 0.9],
  arrow: [0.18, 0.9, 0.22, 0.4],
  rect: [0.16, 0.5, 0.2, 0.5],
};

/** The banner shared by price and flag: pieces = [text, isSmall][] */
const Banner: React.FC<{ctx: Ctx; shape: FlagShape; size: number; pieces: Array<[string, 'big' | 'small' | 'code']>; smallEm: number; fill: string; ink: string; tiltDeg: number}> = ({
  ctx,
  shape,
  size,
  pieces,
  smallEm,
  fill,
  ink,
  tiltDeg,
}) => {
  const [pt, pr, pb, pl] = FLAG_PAD[shape];
  const d = ctx.faces.display;
  const b = ctx.faces.body;
  const kind = ctx.sys.shapes?.shadow ?? 'hard';
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'baseline',
        gap: '.1em',
        background: fill,
        color: ink,
        padding: `${pt}em ${pr}em ${pb}em ${pl}em`,
        clipPath: FLAG_CLIP[shape],
        borderRadius: shape === 'rect' ? (ctx.sys.shapes?.radius_px ?? 0) * 0.6 : 0,
        fontFamily: d.css,
        fontWeight: d.weight,
        fontSize: size,
        whiteSpace: 'nowrap',
        transform: `rotate(${tiltDeg}deg)`,
        letterSpacing: '-.04em',
        lineHeight: 'normal',
        filter: kind === 'none' ? 'none' : kind === 'soft' ? `drop-shadow(0 10px 18px ${alpha(deep(ctx), 0.4)})` : `drop-shadow(8px 8px 0 ${ctx.sys.colors.shadow})`,
      }}
    >
      {pieces.map(([t, k], i) =>
        k === 'big' ? (
          <React.Fragment key={i}>{caseOf(d, t)}</React.Fragment>
        ) : k === 'code' ? (
          <span key={i} style={{fontFamily: b.css, fontWeight: 900, fontSize: '.26em', letterSpacing: '.08em', marginLeft: '.35em', alignSelf: 'center'}}>
            {t}
          </span>
        ) : (
          <small key={i} style={{fontFamily: b.css, fontWeight: 900, fontSize: `${smallEm}em`, letterSpacing: 0, margin: i > 0 ? '0 .25em' : 0}}>
            {t}
          </small>
        ),
      )}
    </div>
  );
};

/** width of a banner at size s (approximation of the drawn box, measured with the real faces) */
const bannerWidth = (ctx: Ctx, shape: FlagShape, pieces: Array<[string, 'big' | 'small' | 'code']>, s: number, smallEm: number): number => {
  const [, pr, , pl] = FLAG_PAD[shape];
  let w = (pr + pl) * s;
  pieces.forEach(([t, k], i) => {
    if (k === 'big') w += measure({...ctx.faces.display, letter_spacing_em: -0.04}, caseOf(ctx.faces.display, t), s);
    else if (k === 'code') w += measure({...ctx.faces.body, letter_spacing_em: 0.08}, t, s * 0.26, 900) + 0.35 * s;
    else w += measure({...ctx.faces.body, letter_spacing_em: 0}, t, s * smallEm, 900) + (i > 0 ? 0.5 * smallEm * s : 0);
    if (i > 0) w += 0.1 * s;
  });
  // the pointed tips carry no text and may bleed past the box (gen.py's banners do)
  const tips: Record<FlagShape, number> = {pennant: 0.04, double: 0.08, arrow: 0.04, rect: 0};
  return (w + 12) * (1 - tips[shape]);
};

const piecesOf = (text: string): Array<[string, 'big' | 'small' | 'code']> => {
  // `4:00 PM <<a>> 11:00 PM` → small «a»
  const out: Array<[string, 'big' | 'small' | 'code']> = [];
  text.split(/(<<.+?>>)/).forEach((p) => {
    if (!p) return;
    if (p.startsWith('<<')) out.push([p.slice(2, -2), 'small']);
    else out.push([p.trim(), 'big']);
  });
  return out.filter(([t]) => t.length > 0);
};

const PriceItem: React.FC<{ctx: Ctx; price: Price; size: number; maxW: number; shape?: FlagShape | null; align: string}> = ({ctx, price, size, maxW, shape, align}) => {
  const p = ctx.comp.price ?? {};
  const variant = p.variant ?? 'flag';
  const fill = color(ctx, p.fill, 'accent');
  const ink = color(ctx, p.ink, 'on_accent');
  const pieces: Array<[string, 'big' | 'small' | 'code']> = [];
  if (price.symbol) pieces.push([price.symbol, 'small']);
  pieces.push([price.amount, 'big']);
  if (price.code && p.show_code !== false) pieces.push([price.code, 'code']);
  const refFace = {...ctx.faces.display, letter_spacing_em: -0.02};
  const refW = price.secondary ? measure(refFace, price.secondary, 30) + 36 + 30 + 8 : 0;
  const sh: FlagShape = shape ?? (variant === 'flag' ? 'pennant' : 'rect');
  const at = (s: number) => bannerWidth(ctx, sh, pieces, s, 0.45) + refW;
  let s = size;
  for (let i = 0; i < 5 && at(s) > maxW; i++) s = Math.floor((s * maxW) / at(s)) - 1;
  if (at(s) > maxW || s < size * 0.45) {
    // never a cut price: drop it whole and say so
    ctx.warnings.push(`price '${price.amount}' does not fit ${Math.round(maxW)} px: dropped`);
    return null;
  }
  const ref = price.secondary ? (
    <span
      style={{display: 'inline-block', whiteSpace: 'nowrap', background: color(ctx, 'surface'), color: color(ctx, 'background'), fontFamily: refFace.css, fontWeight: refFace.weight, fontSize: 30, letterSpacing: '-.02em', padding: '.3em .6em', borderRadius: '.3em', transform: `rotate(${tilt(ctx)}deg)`, boxShadow: hardShadow(ctx, 6, 6), lineHeight: 'normal'}}
    >
      {price.secondary}
    </span>
  ) : null;
  if (variant === 'circle') {
    const d = Math.min(maxW, s * 3.2);
    return (
      <div style={{display: 'flex', justifyContent: align === 'center' ? 'center' : align === 'right' ? 'flex-end' : 'flex-start'}}>
        <div style={{width: d, height: d, borderRadius: '50%', background: fill, color: ink, display: 'grid', placeContent: 'center', textAlign: 'center', transform: `rotate(${tilt(ctx) * 2}deg)`, boxShadow: hardShadow(ctx, 10, 12), fontFamily: ctx.faces.display.css, fontWeight: ctx.faces.display.weight, lineHeight: 1}}>
          <span style={{fontSize: (fitSize(ctx.faces.display, price.amount, d * 0.78, s, 10) ?? s)}}>
            {price.symbol ? <small style={{fontSize: '.45em'}}>{price.symbol}</small> : null}
            {price.amount}
          </span>
          {price.code && p.show_code !== false ? <span style={{fontFamily: ctx.faces.label.css, fontWeight: 900, fontSize: s * 0.24, letterSpacing: '.1em'}}>{price.code}</span> : null}
        </div>
      </div>
    );
  }
  if (variant === 'plain') {
    return (
      <div style={{display: 'flex', alignItems: 'center', gap: 30, justifyContent: align === 'center' ? 'center' : 'flex-start'}}>
        <span style={{fontFamily: ctx.faces.display.css, fontWeight: ctx.faces.display.weight, fontSize: s, color: fill, whiteSpace: 'nowrap', letterSpacing: '-.03em', lineHeight: 1, textShadow: hardShadow(ctx, 0, 5)}}>
          {price.symbol ? <small style={{fontSize: '.5em'}}>{price.symbol}</small> : null}
          {price.amount}
          {price.code && p.show_code !== false ? <small style={{fontSize: '.26em', marginLeft: '.3em', letterSpacing: '.08em'}}>{price.code}</small> : null}
        </span>
        {ref}
      </div>
    );
  }
  const bannerShape: FlagShape = variant === 'flag' ? sh : 'rect';
  const ticket = variant === 'ticket';
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 30, justifyContent: align === 'center' ? 'center' : align === 'right' ? 'flex-end' : 'flex-start'}}>
      <div style={ticket ? {outline: `4px dashed ${ink}`, outlineOffset: -14, display: 'inline-flex', borderRadius: (ctx.sys.shapes?.radius_px ?? 0) * 0.6} : {display: 'inline-flex'}}>
        <Banner ctx={ctx} shape={bannerShape} size={s} pieces={pieces} smallEm={0.45} fill={fill} ink={ink} tiltDeg={variant === 'badge' ? 0 : tilt(ctx)} />
      </div>
      {ref}
    </div>
  );
};

const Chips: React.FC<{ctx: Ctx; items: string[]; size: number}> = ({ctx, items, size}) => {
  const c = ctx.comp.info_card ?? {};
  return (
    <div style={{display: 'flex', flexWrap: 'wrap', gap: '22px 18px'}}>
      {items.map((t, i) => (
        <span key={i} style={{background: color(ctx, c.fill, 'surface'), color: color(ctx, c.ink, 'on_surface'), borderRadius: (ctx.sys.shapes?.radius_px ?? 34) * 0.65, padding: '22px 30px', fontFamily: ctx.faces.body.css, fontWeight: 900, fontSize: size, boxShadow: hardShadow(ctx, 0, 8), lineHeight: 'normal'}}>
          {t}
        </span>
      ))}
    </div>
  );
};

const DEFAULT_SIZE: Record<StackItem['type'], number> = {tag: 30, headline: 112, body: 38, price: 96, flag: 84, note: 30, chips: 46};
const DEFAULT_GAP: Record<StackItem['type'], number> = {tag: 0, headline: 24, body: 20, price: 40, flag: 40, note: 30, chips: 30};

const TextStack: React.FC<{ctx: Ctx; block: Block; boxPx: {w: number; h: number}}> = ({ctx, block, boxPx}) => {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [handle] = useState(() => delayRender('brand_still text stack fit'));
  const align = block.align ?? 'left';
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && scale === 1 && el.scrollHeight > boxPx.h + 1) {
      ctx.warnings.push(`text_stack scaled to ${(boxPx.h / el.scrollHeight).toFixed(2)} to fit its box`);
      setScale(boxPx.h / el.scrollHeight);
      return;
    }
    continueRender(handle);
  }, [scale, boxPx.h, handle, ctx.warnings]);
  const maxW = boxPx.w;
  const nodes = (block.items ?? []).map((it, i) => {
    const raw = it.slot ? get(ctx.content, it.slot) : it.text;
    if (raw === undefined || raw === null || raw === '') return null;
    const size = it.size && it.size > 0 ? it.size : DEFAULT_SIZE[it.type];
    const gap = i === 0 ? 0 : it.space_before !== undefined && it.space_before >= 0 ? it.space_before : DEFAULT_GAP[it.type];
    let node: React.ReactNode = null;
    if (it.type === 'tag') node = <Tag ctx={ctx} text={str(raw)} size={size} maxW={maxW} />;
    else if (it.type === 'headline') node = <Headline ctx={ctx} text={str(raw)} size={size} maxW={maxW} />;
    else if (it.type === 'body' || it.type === 'note') {
      const f = it.type === 'note' ? ctx.faces.label : ctx.faces.body;
      node = (
        <p style={{...fontOf(f, size, it.type === 'note' ? 900 : undefined), lineHeight: it.line_height ?? (it.type === 'note' ? 1.5 : (f.line_height ?? 1.38)), color: color(ctx, 'ink'), textShadow: (ctx.sys.shapes?.shadow ?? 'hard') === 'none' ? 'none' : it.type === 'note' ? `0 2px 6px ${deep(ctx)}` : `0 3px 8px ${deep(ctx)}`, margin: 0, textTransform: it.type === 'note' && f.uppercase ? 'uppercase' : 'none', ...(it.type === 'note' ? {letterSpacing: '.16em'} : {})}}>
          <Rich ctx={ctx} text={str(raw)} />
        </p>
      );
    } else if (it.type === 'price') {
      const pr = typeof raw === 'object' ? (raw as Price) : {amount: str(raw)};
      node = <PriceItem ctx={ctx} price={pr} size={size} maxW={maxW} shape={it.shape} align={align} />;
    } else if (it.type === 'flag') {
      const pieces = piecesOf(str(raw));
      const sh = it.shape ?? 'double';
      const smallEm = it.small_em ?? 0.45;
      let s = size;
      for (let k = 0; k < 5 && bannerWidth(ctx, sh, pieces, s, smallEm) > maxW; k++) s = Math.floor((s * maxW) / bannerWidth(ctx, sh, pieces, s, smallEm)) - 1;
      node = <Banner ctx={ctx} shape={sh} size={s} pieces={pieces} smallEm={smallEm} fill={color(ctx, ctx.comp.price?.fill, 'accent')} ink={color(ctx, ctx.comp.price?.ink, 'on_accent')} tiltDeg={tilt(ctx)} />;
    } else if (it.type === 'chips') {
      node = <Chips ctx={ctx} items={Array.isArray(raw) ? raw.map(str) : str(raw).split('·').map((x) => x.trim())} size={size} />;
    }
    return node ? (
      <div key={i} style={{marginTop: gap}}>
        {node}
      </div>
    ) : null;
  });
  const origin = `${align === 'center' ? 'center' : align === 'right' ? 'right' : 'left'} ${block.valign === 'bottom' ? 'bottom' : block.valign === 'center' ? 'center' : 'top'}`;
  return (
    <div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', justifyContent: block.valign === 'bottom' ? 'flex-end' : block.valign === 'center' ? 'center' : 'flex-start'}}>
      <div ref={ref} style={{textAlign: align, transform: scale === 1 ? undefined : `scale(${scale})`, transformOrigin: origin}}>
        {nodes}
      </div>
    </div>
  );
};

// ------------------------------------------------------------------ icons (ported from gen.py)
const ClockIcon: React.FC<{ctx: Ctx}> = ({ctx}) => (
  <svg viewBox="0 0 1000 1000" width="100%" height="100%">
    <circle cx="500" cy="500" r="330" fill={color(ctx, 'surface')} />
    <circle cx="500" cy="500" r="330" fill="none" stroke={color(ctx, 'accent')} strokeWidth="34" />
    <g stroke={color(ctx, 'background')} strokeWidth="22" strokeLinecap="round">
      <line x1="500" y1="225" x2="500" y2="265" />
      <line x1="500" y1="735" x2="500" y2="775" />
      <line x1="225" y1="500" x2="265" y2="500" />
      <line x1="735" y1="500" x2="775" y2="500" />
    </g>
    <g stroke={color(ctx, 'shadow')} strokeWidth="40" strokeLinecap="round">
      <line x1="500" y1="500" x2="500" y2="320" />
      <line x1="500" y1="500" x2="630" y2="575" />
    </g>
    <circle cx="500" cy="500" r="34" fill={color(ctx, 'background')} />
  </svg>
);
const SimpleIcon: React.FC<{ctx: Ctx; name: string}> = ({ctx, name}) => {
  const s = color(ctx, 'surface');
  const a = color(ctx, 'background');
  const paths: Record<string, React.ReactNode> = {
    pin: (
      <>
        <path d="M500 150c-150 0-255 112-255 250 0 185 255 455 255 455s255-270 255-455c0-138-105-250-255-250z" fill={s} />
        <circle cx="500" cy="400" r="120" fill={a} />
      </>
    ),
    card: (
      <>
        <rect x="190" y="290" width="620" height="420" rx="46" fill={s} transform="rotate(-8 500 500)" />
        <rect x="190" y="380" width="620" height="80" fill={a} transform="rotate(-8 500 500)" />
      </>
    ),
    chat: <path d="M500 175c-190 0-345 135-345 305 0 75 30 145 82 198l-42 150 160-62c44 16 94 24 145 24 190 0 345-135 345-310S690 175 500 175z" fill={s} />,
    bag: (
      <>
        <rect x="240" y="330" width="520" height="480" rx="40" fill={s} />
        <path d="M380 340v-60a120 120 0 0 1 240 0v60" fill="none" stroke={s} strokeWidth="40" />
      </>
    ),
    star: <path d="M500 150l100 220 240 25-180 160 52 235-212-122-212 122 52-235-180-160 240-25z" fill={s} />,
    heart: <path d="M500 830S180 620 180 400c0-110 85-190 185-190 65 0 110 35 135 80 25-45 70-80 135-80 100 0 185 80 185 190 0 220-320 430-320 430z" fill={s} />,
  };
  return (
    <svg viewBox="0 0 1000 1000" width="100%" height="100%">
      {paths[name] ?? null}
    </svg>
  );
};

// ------------------------------------------------------------------ blocks
type Photo = {photo?: string; cutout?: boolean};

const ProductBlock: React.FC<{ctx: Ctx; block: Block; boxPx: {w: number; h: number}}> = ({ctx, block, boxPx}) => {
  const raw = get(ctx.content, block.slot ?? 'product');
  const prod: Photo = typeof raw === 'string' ? {photo: raw} : ((raw as Photo) ?? {});
  if (!prod.photo) return null;
  const pf = ctx.comp.product_frame ?? {};
  let v = pf.variant ?? 'cutout_glow';
  if (!prod.cutout && (v === 'cutout_glow' || v === 'cutout_sun')) v = 'disc';
  const src = asset(prod.photo);
  const mirror = block.mirror ? 'scaleX(-1)' : undefined;
  if (prod.cutout && (v === 'cutout_glow' || v === 'cutout_sun')) {
    // Exactly gen.py's `.prod`: width of the box, natural height, soft drop shadow.
    return <Img src={src} style={{position: 'absolute', left: 0, top: 0, width: '100%', height: 'auto', transform: mirror, filter: `drop-shadow(0 40px 40px ${alpha(deep(ctx), 0.63)})`}} />;
  }
  const d = Math.min(boxPx.w, boxPx.h);
  const ring = color(ctx, pf.ring, 'surface');
  const shapeCss: React.CSSProperties =
    v === 'arch'
      ? {width: boxPx.w, height: boxPx.h, borderRadius: `${boxPx.w / 2}px ${boxPx.w / 2}px ${(ctx.sys.shapes?.radius_px ?? 24)}px ${(ctx.sys.shapes?.radius_px ?? 24)}px`}
      : v === 'rounded'
        ? {width: boxPx.w, height: boxPx.h, borderRadius: (ctx.sys.shapes?.radius_px ?? 24) * 1.4, transform: `rotate(${tilt(ctx)}deg)`}
        : v === 'blob'
          ? {width: d, height: d, borderRadius: '42% 58% 63% 37% / 41% 44% 56% 59%'}
          : {width: d, height: d, borderRadius: '50%'};
  return (
    <div style={{position: 'absolute', inset: 0, display: 'grid', placeItems: 'center'}}>
      <div
        style={{
          ...shapeCss,
          border: `${Math.round(d * 0.028)}px solid ${ring}`,
          boxShadow: hardShadow(ctx, 0, Math.round(d * 0.034)),
          backgroundImage: `url("${src}")`,
          backgroundSize: 'cover',
          backgroundPosition: `${(block.focus?.[0] ?? 0.5) * 100}% ${(block.focus?.[1] ?? 0.5) * 100}%`,
          transform: [shapeCss.transform, mirror].filter(Boolean).join(' ') || undefined,
        }}
      />
    </div>
  );
};

const StampBlock: React.FC<{ctx: Ctx; block: Block; boxPx: {w: number; h: number}}> = ({ctx, block, boxPx}) => {
  const st = ctx.comp.stamp ?? {};
  const v = st.variant ?? 'circle_ring';
  const raw = get(ctx.content, block.slot ?? 'product.stamp');
  if (v === 'none' || !raw || typeof raw !== 'object') return null;
  const {big, small} = raw as {big?: string; small?: string};
  const d = Math.min(boxPx.w, boxPx.h);
  const f = ctx.faces.display;
  const fill = color(ctx, st.fill, 'surface');
  const ink = color(ctx, st.ink, 'background');
  const ring = color(ctx, st.ring, 'accent');
  const bigSize = fitSize({...f, letter_spacing_em: -0.06}, str(big), d * 0.82, Math.round(d * 0.31), 10) ?? d * 0.2;
  const smallSize = fitSize(f, str(small), d * 0.78, Math.round(d * 0.16), 8) ?? d * 0.1;
  const clip =
    v === 'starburst'
      ? `polygon(${Array.from({length: 32}, (_, i) => {
          const a = (i / 32) * Math.PI * 2;
          const r = i % 2 ? 42 : 50;
          return `${50 + r * Math.cos(a)}% ${50 + r * Math.sin(a)}%`;
        }).join(',')})`
      : v === 'scallop'
        ? `polygon(${Array.from({length: 72}, (_, i) => {
            const a = (i / 72) * Math.PI * 2;
            const r = 47 + 3 * Math.cos(a * 12);
            return `${50 + r * Math.cos(a)}% ${50 + r * Math.sin(a)}%`;
          }).join(',')})`
        : undefined;
  const inner = (
    <div style={{width: d, aspectRatio: '1', display: 'grid', placeContent: 'center', textAlign: 'center', borderRadius: '50%', background: fill, color: ink, fontFamily: f.css, fontWeight: f.weight, lineHeight: 0.9, clipPath: clip, boxShadow: clip ? undefined : `0 0 0 ${d * 0.052}px ${ring}, ${d * 0.043}px ${d * 0.061}px 0 ${d * 0.052}px ${ctx.sys.colors.shadow}`}}>
      <b style={{display: 'block', letterSpacing: '-.06em', fontSize: bigSize, textTransform: f.uppercase ? 'uppercase' : 'none'}}>{big}</b>
      <span style={{fontSize: smallSize}}>{small}</span>
    </div>
  );
  return (
    <div style={{position: 'absolute', left: 0, top: 0, transform: `rotate(${block.rotate_deg ?? -8}deg)`, filter: clip ? dropShadow(ctx, d * 0.04, d * 0.05) : undefined}}>
      {clip ? <div style={{background: ring, padding: d * 0.045, clipPath: clip, margin: -d * 0.045}}>{inner}</div> : inner}
    </div>
  );
};

const Ticker: React.FC<{ctx: Ctx; block: Block}> = ({ctx, block}) => {
  const tk = ctx.comp.ticker ?? {};
  const raw = get(ctx.content, block.slot ?? 'ticker');
  if (tk.enabled === false || !Array.isArray(raw) || raw.length === 0) return null;
  const sep = tk.separator ?? '✦';
  const t = (raw as unknown[]).map(str).join(`   ${sep}   `);
  const f = ctx.faces.label;
  return (
    <div style={{position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', whiteSpace: 'nowrap', overflow: 'hidden', color: color(ctx, tk.ink, 'background'), background: color(ctx, tk.fill, 'accent'), fontFamily: f.css, fontSize: 30, fontWeight: 900, textTransform: 'uppercase', letterSpacing: '.02em'}}>
      <div style={{marginLeft: -120}}>{`✳   ${t}   ✳   ${t}`}</div>
    </div>
  );
};

type Group = {title?: string; items: Array<{label: string; logo?: string; sub?: string; value?: string}>};
const InfoList: React.FC<{ctx: Ctx; block: Block}> = ({ctx, block}) => {
  const raw = get(ctx.content, block.slot ?? 'payments');
  if (!Array.isArray(raw)) return null;
  const groups = raw as Group[];
  const c = ctx.comp.info_card ?? {};
  const v = c.variant ?? 'chip';
  const fill = color(ctx, c.fill, 'surface');
  const ink = color(ctx, c.ink, 'on_surface');
  const r = (ctx.sys.shapes?.radius_px ?? 34) * 0.65;
  const d = ctx.faces.display;
  const chipStyle: React.CSSProperties =
    v === 'outline'
      ? {border: `4px solid ${fill}`, color: fill}
      : v === 'plain'
        ? {color: color(ctx, 'ink')}
        : {background: fill, color: ink, boxShadow: hardShadow(ctx, 0, 9)};
  return (
    <div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', gap: 34}}>
      {groups.map((g, i) => (
        <div key={i}>
          {g.title ? (
            <h2 style={{fontFamily: d.css, fontWeight: d.weight, fontSize: 34, textTransform: 'uppercase', letterSpacing: '-.03em', color: color(ctx, 'accent'), margin: '0 0 16px 6px', textShadow: (ctx.sys.shapes?.shadow ?? 'hard') === 'none' ? 'none' : `0 4px 0 ${ctx.sys.colors.shadow}`}}>{g.title}</h2>
          ) : null}
          <div style={{display: 'flex', flexWrap: 'wrap', gap: 16, flexDirection: g.items.some((it) => it.value) ? 'column' : 'row'}}>
            {g.items.map((it, k) => (
              <div key={k} style={{display: 'flex', alignItems: 'center', gap: 16, borderRadius: r, padding: '18px 26px', fontFamily: ctx.faces.body.css, fontSize: 38, fontWeight: 900, minHeight: 96, ...chipStyle}}>
                {it.logo ? <Img src={asset(it.logo)} style={{height: 52, width: 'auto', maxWidth: 150}} /> : null}
                <span style={{flex: it.value ? 1 : undefined}}>
                  {it.label}
                  {it.sub ? <small style={{display: 'block', fontSize: 22, fontWeight: 700, opacity: 0.75, marginTop: 2}}>{it.sub}</small> : null}
                </span>
                {it.value ? <b style={{fontFamily: d.css, fontWeight: d.weight, letterSpacing: '-.03em'}}>{it.value}</b> : null}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

const BlockView: React.FC<{ctx: Ctx; block: Block; index: number}> = ({ctx, block, index}) => {
  const [x, y, w, h] = block.box;
  const boxPx = {w: w * W, h: h * ctx.H};
  const style: React.CSSProperties = {position: 'absolute', left: x * W, top: y * ctx.H, width: boxPx.w, height: boxPx.h, zIndex: block.z ?? index};
  const rot = block.rotate_deg && block.type !== 'stamp' ? {transform: `rotate(${block.rotate_deg}deg)`} : {};
  switch (block.type) {
    case 'photo': {
      const src = str(get(ctx.content, block.slot ?? 'photo'));
      if (!src) return null;
      const veil = block.veil ?? [];
      const framed = block.framed;
      return (
        <>
          <div
            style={{
              ...style,
              ...rot,
              backgroundImage: `url("${asset(src)}")`,
              backgroundRepeat: 'no-repeat',
              backgroundSize: block.zoom ? `auto ${block.zoom * 100}%` : 'cover',
              backgroundPosition: `${(block.focus?.[0] ?? 0.5) * 100}% ${(block.focus?.[1] ?? 0.5) * 100}%`,
              filter: block.saturate || block.contrast ? `saturate(${block.saturate ?? 1}) contrast(${block.contrast ?? 1})` : undefined,
              ...(framed ? {borderRadius: ctx.sys.shapes?.radius_px ?? 34, border: `14px solid ${color(ctx, 'surface')}`, boxShadow: hardShadow(ctx, 0, 18)} : {}),
            }}
          />
          {veil.length ? (
            <div style={{position: 'absolute', inset: 0, zIndex: (block.z ?? index) , background: `linear-gradient(180deg, ${veil.map((s) => `${alpha(color(ctx, s.color), s.alpha)} ${s.at}%`).join(', ')})`}} />
          ) : null}
          {block.fade === 'bottom' && !veil.length ? (
            <div style={{...style, background: `linear-gradient(180deg, transparent 40%, ${ctx.sys.colors.background} 100%)`}} />
          ) : null}
        </>
      );
    }
    case 'logo': {
      const src = str(get(ctx.content, block.slot ?? 'brand.logo'));
      if (!src) return null;
      const lg = ctx.comp.logo ?? {};
      const img = <Img src={asset(src)} style={{width: '100%', height: 'auto', display: 'block', filter: lg.variant === 'on_badge' ? undefined : `drop-shadow(0 6px 10px ${alpha(deep(ctx), 0.5)})`}} />;
      return (
        <div style={{...style, height: undefined, ...rot}}>
          {lg.variant === 'on_badge' ? <div style={{background: color(ctx, lg.badge, 'surface'), borderRadius: '50%', padding: boxPx.w * 0.14, boxShadow: hardShadow(ctx, 0, 10), aspectRatio: '1', display: 'grid', placeItems: 'center'}}>{img}</div> : img}
        </div>
      );
    }
    case 'product': {
      // A cutout's placement depends on the cutout's own framing: the slot may carry its box.
      const pb = (get(ctx.content, block.slot ?? 'product') as {box?: [number, number, number, number]} | undefined)?.box;
      const st = pb ? {...style, left: pb[0] * W, top: pb[1] * ctx.H, width: pb[2] * W, height: pb[3] * ctx.H} : style;
      return (
        <div style={{...st, ...rot}}>
          <ProductBlock ctx={ctx} block={block} boxPx={pb ? {w: pb[2] * W, h: pb[3] * ctx.H} : boxPx} />
        </div>
      );
    }
    case 'glow': {
      const g = color(ctx, block.colors?.[0] ?? ctx.comp.product_frame?.glow, 'accent');
      return <div style={{...style, borderRadius: '50%', background: `radial-gradient(closest-side, ${alpha(g, 0.6)}, ${alpha(g, 0)})`}} />;
    }
    case 'sun': {
      const a = color(ctx, block.colors?.[0], 'accent');
      const b = color(ctx, block.colors?.[1], 'pop');
      const glow = block.colors?.[2] ? color(ctx, block.colors[2]) : alpha(b, 0.5);
      return <div style={{...style, borderRadius: '50%', background: `repeating-conic-gradient(${a} 0deg 10deg, ${b} 10deg 20deg)`, boxShadow: `0 0 90px ${glow}`}} />;
    }
    case 'sparkle': {
      const sp = ctx.comp.sparkle ?? {};
      if (sp.enabled === false) return null;
      return (
        <span style={{position: 'absolute', left: x * W, top: y * ctx.H, zIndex: block.z ?? index, fontSize: h * ctx.H, lineHeight: 1, color: color(ctx, block.colors?.[0] ?? sp.color, 'surface'), textShadow: `0 0 14px #fff, 0 0 36px ${block.colors?.[1] ? color(ctx, block.colors[1]) : alpha(color(ctx, 'accent'), 0.5)}`}}>
          {sp.glyph ?? '✦'}
        </span>
      );
    }
    case 'stamp':
      return (
        <div style={style}>
          <StampBlock ctx={ctx} block={block} boxPx={boxPx} />
        </div>
      );
    case 'text_stack':
      return (
        <div style={{...style, ...rot}}>
          <TextStack ctx={ctx} block={block} boxPx={boxPx} />
        </div>
      );
    case 'ticker':
      return (
        <div style={style}>
          <Ticker ctx={ctx} block={block} />
        </div>
      );
    case 'info_list':
      return (
        <div style={style}>
          <InfoList ctx={ctx} block={block} />
        </div>
      );
    case 'icon_feature':
      return (
        <div style={{...style, ...rot, filter: dropShadow(ctx, 0, 16)}}>
          {block.icon === 'clock' || !block.icon ? <ClockIcon ctx={ctx} /> : <SimpleIcon ctx={ctx} name={block.icon} />}
        </div>
      );
    default:
      return null;
  }
};

// ------------------------------------------------------------------ the still
export const BrandStill: React.FC<BrandStillProps> = ({system, recipe, content}) => {
  const rec = system.recipes[recipe];
  if (!rec) throw new Error(`invalid_parameters: recipe '${recipe}' not in system '${system.id}' v${system.version}`);
  const H = FORMATS[rec.format].height;
  const [faces, setFaces] = useState<Faces | null>(null);
  const [handle] = useState(() => delayRender(`brand_still fonts ${system.id} v${system.version}`, {timeoutInMilliseconds: 40_000}));
  useLayoutEffect(() => {
    const t = system.typography;
    Promise.all([loadFace(t.display, [], asset), loadFace(t.body, [700, 800, 900], asset), loadFace(t.label, [900], asset)])
      .then(([display, body, label]) => {
        const missing = [display, body, label].filter((f) => !f.found).map((f) => f.family);
        if (missing.length) console.warn(`brand_still: font(s) not in Google Fonts: ${missing.join(', ')}`);
        setFaces({display, body, label});
        continueRender(handle);
      })
      .catch((e: unknown) => {
        throw e;
      });
  }, [system.typography, handle]);
  if (!faces) return <AbsoluteFill style={{background: system.colors.background}} />;
  // Every warning (dropped price, scaled text block) also goes to the browser console, where the
  // batch script / server collect it as the piece's report (SISVIS-002 discards on these).
  const warnings: string[] = [];
  const push = warnings.push.bind(warnings);
  warnings.push = (...m: string[]) => {
    m.forEach((x) => console.warn(`BRANDSTILL_WARN ${x}`));
    return push(...m);
  };
  const ctx: Ctx = {sys: system, comp: system.components ?? {}, faces, H, content, warnings};
  const bg = rec.background ?? system.background;
  return (
    <AbsoluteFill style={{overflow: 'hidden', background: system.colors.background, color: system.colors.ink, fontFamily: faces.body.css, fontWeight: faces.body.weight}}>
      <BackgroundLayers ctx={ctx} bg={bg} />
      {rec.blocks.map((b, i) => (
        <BlockView key={i} ctx={ctx} block={b} index={i + 1} />
      ))}
    </AbsoluteFill>
  );
};
