// Animated WhatsApp sticker (option C of docs/opciones-stickers-videos-cortos.md, founder
// 2026-11-09). One `sticker-v1--sheet` still holds every frame of the 2 s loop as a
// grid of 512×512 cells on a TRANSPARENT background (renderStill writes PNG with alpha);
// Python slices the grid and encodes the animated WebP with its own quality ladder and
// WhatsApp checks (`qualify_creative.seasonal.sticker_c`). The look:
//
// - die-cut: a thick, rounded white outline around the art's own shape plus a soft drop
//   shadow (an SVG filter on the alpha channel — the art can be any logo or cut-out);
// - Brand Kit colours for the text, rings, sparkles and the coin's back; the Brand Kit's
//   heading face for the words;
// - spring motions that start and end at rest (motion.ts).
//
// `StickerPreview` is the same art as a playing composition for Remotion Studio only
// (an MP4 cannot keep transparency, so it is not an output port).
import React, {useEffect, useMemo, useState} from 'react';
import {AbsoluteFill, Img, continueRender, delayRender, useCurrentFrame} from 'remotion';
import manifest from '../../../templates/sticker/manifest.json';
import {normalizeProps, textOf, type PropsInput} from '../../props';
import {useStickerFont, stickerColors, type StickerColors} from './look';
import {IMAGE_MOTIONS, isMotion, poseAt, type Motion, type Pose} from './motion';

export const CELL = 512;
/** WhatsApp's guideline: 16 px clear around the art. */
const MARGIN = 16;
const OUTLINE_ART = 15;
const OUTLINE_TEXT = 15;
const CENTER = CELL / 2;

export type SheetSpec = {cell: number; columns: number; frames: number; fps: number};
/** The grid layout, from the manifest (Python reads the same numbers). */
export const SHEET: SheetSpec = manifest.sheet;

// ------------------------------------------------------------------ props

type StickerInput = PropsInput & {art?: string | null};

type Resolved = {
  motion: Motion;
  text: string;
  art: string | null;
  fontFile: string | undefined;
  fontFamily: string | undefined;
  colors: StickerColors;
};

const resolve = (raw: StickerInput): Resolved => {
  const props = normalizeProps(raw);
  const motionText = textOf(props, 'motion');
  if (!isMotion(motionText)) throw new Error(`sticker: unknown motion '${motionText}'`);
  const art = typeof raw.art === 'string' && raw.art.length > 0 ? raw.art : null;
  const text = textOf(props, 'text').trim();
  if (IMAGE_MOTIONS.includes(motionText) && !art) throw new Error(`sticker: '${motionText}' needs art`);
  if (motionText === 'texto' && !text) throw new Error("sticker: 'texto' needs text");
  const brand = props.brand as typeof props.brand & {fontFiles?: {heading?: string}};
  return {
    motion: motionText,
    text,
    art,
    fontFile: typeof brand.fontFiles?.heading === 'string' ? brand.fontFiles.heading : undefined,
    fontFamily: props.brand.fonts.heading,
    colors: stickerColors(props.brand),
  };
};

// ------------------------------------------------------------------ layout

type Size = {w: number; h: number};

/** Natural size of the art; blocks the render until known. */
const useArtSize = (url: string | null): Size | null => {
  const [size, setSize] = useState<Size | null>(null);
  const [handle] = useState(() => (url ? delayRender(`sticker art: ${url.slice(-24)}`) : null));
  useEffect(() => {
    if (!url) return;
    const img = new Image();
    img.onload = () => setSize({w: img.naturalWidth || 1, h: img.naturalHeight || 1});
    img.onerror = () => setSize({w: 1, h: 1});
    img.src = url;
  }, [url]);
  useEffect(() => {
    if (size && handle !== null) continueRender(handle);
  }, [size, handle]);
  return size;
};

/** The largest box (w, h) of the art's aspect that fits the motion's room. */
const artBox = (natural: Size, motion: Motion): Size => {
  // Room for the motion inside WhatsApp's 16 px margin: latido grows 12 %, rebote hops
  // 74 px and stretches 10 %, giro hops 26 px, brillo grows 4 % (+ 15 px outline).
  const [maxW, maxH] = motion === 'rebote' ? [360, 330] : motion === 'latido' ? [350, 350] : [370, 370];
  const k = Math.min(maxW / natural.w, maxH / natural.h);
  return {w: Math.round(natural.w * k), h: Math.round(natural.h * k)};
};

/** Rebote stands on a ground line; the others are centred. */
const GROUND_Y = CELL - MARGIN - OUTLINE_ART - 26;

type TextLayout = {lines: string[][]; px: number};

const TEXT_MAX_W = 420;
const TEXT_MAX_H = 300;
const TEXT_MAX_LINES = 3;
const LINE_HEIGHT = 1.08;

/** Greedy wrap at the largest size that fits (measured with the loaded face). */
const fitText = (text: string, family: string): TextLayout => {
  const words = text.split(/\s+/).filter(Boolean);
  const ctx = document.createElement('canvas').getContext('2d');
  for (let px = 112; px >= 28; px -= 2) {
    if (!ctx) break;
    ctx.font = `700 ${px}px ${family}`;
    const space = ctx.measureText(' ').width;
    const lines: string[][] = [[]];
    let width = 0;
    let fits = true;
    for (const word of words) {
      const w = ctx.measureText(word).width;
      if (w > TEXT_MAX_W) {
        fits = false;
        break;
      }
      const line = lines[lines.length - 1]!;
      if (line.length > 0 && width + space + w > TEXT_MAX_W) {
        lines.push([word]);
        width = w;
      } else {
        width += (line.length > 0 ? space : 0) + w;
        line.push(word);
      }
    }
    if (fits && lines.length <= TEXT_MAX_LINES && lines.length * px * LINE_HEIGHT <= TEXT_MAX_H) {
      return {lines, px};
    }
  }
  return {lines: [words], px: 28};
};

// ------------------------------------------------------------------ filters

const filterId = (name: string) => `qualify-sticker-${name}`;

/**
 * The die-cut edge: dilate the alpha, blur it and threshold it again (a round outline,
 * not the square one feMorphology alone gives), fill it white; a blurred, offset copy
 * of the same shape is the drop shadow. `fill` replaces the art itself (the coin's back).
 */
const DieCut: React.FC<{name: string; radius: number; fill?: string}> = ({name, radius, fill}) => (
  <filter id={filterId(name)} x="-30%" y="-30%" width="160%" height="160%" colorInterpolationFilters="sRGB">
    <feMorphology in="SourceAlpha" operator="dilate" radius={radius * 0.6} result="grown" />
    <feGaussianBlur in="grown" stdDeviation={radius * 0.45} result="soft" />
    <feComponentTransfer in="soft" result="edge">
      <feFuncA type="linear" slope={5} intercept={-1.2} />
    </feComponentTransfer>
    <feFlood floodColor="#ffffff" result="white" />
    <feComposite in="white" in2="edge" operator="in" result="outline" />
    <feGaussianBlur in="edge" stdDeviation={3.5} result="blur" />
    <feOffset in="blur" dx={0} dy={4} result="dropped" />
    <feFlood floodColor="#000000" floodOpacity={0.35} />
    <feComposite in2="dropped" operator="in" result="shadow" />
    {fill ? (
      <>
        <feFlood floodColor={fill} />
        <feComposite in2="SourceAlpha" operator="in" result="art" />
      </>
    ) : null}
    <feMerge>
      <feMergeNode in="shadow" />
      <feMergeNode in="outline" />
      <feMergeNode in={fill ? 'art' : 'SourceGraphic'} />
    </feMerge>
  </filter>
);

const Filters: React.FC<{colors: StickerColors}> = ({colors}) => (
  <svg width={0} height={0} style={{position: 'absolute'}} aria-hidden>
    <defs>
      <DieCut name="art" radius={OUTLINE_ART} />
      <DieCut name="back" radius={OUTLINE_ART} fill={colors.accent} />
      <DieCut name="text" radius={OUTLINE_TEXT} />
      <DieCut name="spark" radius={4} />
    </defs>
  </svg>
);

// ------------------------------------------------------------------ pieces

const transformOf = (pose: Pose): string =>
  [
    `translateY(${pose.translateY.toFixed(2)}px)`,
    `rotate(${pose.rotate.toFixed(3)}deg)`,
    `scale(${pose.scaleX.toFixed(4)}, ${pose.scaleY.toFixed(4)})`,
  ].join(' ');

const Sparkle: React.FC<{x: number; y: number; size: number; scale: number; color: string}> = ({x, y, size, scale, color}) => {
  if (scale <= 0.01) return null;
  const r = size / 2;
  // a four-point star
  const d = `M ${r} 0 Q ${r * 1.12} ${r * 0.88} ${size} ${r} Q ${r * 1.12} ${r * 1.12} ${r} ${size} Q ${r * 0.88} ${r * 1.12} 0 ${r} Q ${r * 0.88} ${r * 0.88} ${r} 0 Z`;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      style={{
        position: 'absolute',
        left: x - r,
        top: y - r,
        overflow: 'visible',
        transform: `scale(${scale.toFixed(3)}) rotate(${(scale * 25).toFixed(1)}deg)`,
        filter: `url(#${filterId('spark')})`,
      }}
    >
      <path d={d} fill={color} />
    </svg>
  );
};

/**
 * A white band sweeping across the art and only the art. An SVG <mask> of the art's alpha,
 * not CSS `mask-image`: the art is served by the render service's asset route, another
 * origin than the bundle, and CSS masks need CORS where SVG masks do not.
 */
const Shine: React.FC<{art: string; box: Size; at: number; id: string}> = ({art, box, at, id}) => {
  const x = -0.6 + 2.2 * at; // the band's centre, in box widths
  const mask = `${filterId('shine-mask')}-${id}`;
  const grad = `${filterId('shine-grad')}-${id}`;
  return (
    <svg width={box.w} height={box.h} style={{position: 'absolute', inset: 0}} aria-hidden>
      <defs>
        <mask id={mask} style={{maskType: 'alpha'}} maskUnits="userSpaceOnUse" x={0} y={0} width={box.w} height={box.h}>
          <image href={art} width={box.w} height={box.h} preserveAspectRatio="xMidYMid meet" />
        </mask>
        <linearGradient id={grad} gradientUnits="objectBoundingBox" x1={0} y1={0.15} x2={1} y2={0.85}>
          <stop offset={Math.max(0, x - 0.22)} stopColor="#ffffff" stopOpacity={0} />
          <stop offset={Math.min(1, Math.max(0, x))} stopColor="#ffffff" stopOpacity={0.8} />
          <stop offset={Math.min(1, x + 0.22)} stopColor="#ffffff" stopOpacity={0} />
        </linearGradient>
      </defs>
      <rect width={box.w} height={box.h} fill={`url(#${grad})`} mask={`url(#${mask})`} />
    </svg>
  );
};

const ArtSticker: React.FC<{r: Resolved; box: Size; pose: Pose; cellId: string}> = ({r, box, pose, cellId}) => {
  const art = r.art!;
  const left = CENTER - box.w / 2;
  const top = pose.origin === 'bottom' ? GROUND_Y - box.h : CENTER - box.h / 2;
  const origin = pose.origin === 'bottom' ? '50% 100%' : '50% 50%';
  const face = (filter: string, back = false): React.CSSProperties => ({
    position: 'absolute',
    inset: 0,
    width: '100%',
    height: '100%',
    objectFit: 'contain',
    filter: `url(#${filterId(filter)})`,
    backfaceVisibility: 'hidden',
    transform: back ? 'rotateY(180deg)' : undefined,
  });
  const ringMax = CENTER - MARGIN - 4;
  const ringMin = Math.min(box.w, box.h) * 0.42;
  return (
    <>
      {pose.ground !== null ? (
        <div
          style={{
            position: 'absolute',
            left: CENTER - (box.w * 0.62 * pose.ground) / 2,
            top: GROUND_Y + OUTLINE_ART + 6,
            width: box.w * 0.62 * pose.ground,
            height: 18 * pose.ground,
            borderRadius: '50%',
            background: 'rgba(0, 0, 0, 0.22)',
            filter: 'blur(5px)',
          }}
        />
      ) : null}
      {pose.rings.map((p, i) =>
        p === null ? null : (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: CENTER,
              top: CENTER,
              width: 0,
              height: 0,
            }}
          >
            <div
              style={{
                position: 'absolute',
                left: -(ringMin + (ringMax - ringMin) * p),
                top: -(ringMin + (ringMax - ringMin) * p),
                width: 2 * (ringMin + (ringMax - ringMin) * p),
                height: 2 * (ringMin + (ringMax - ringMin) * p),
                borderRadius: '50%',
                border: `${(14 * (1 - p) + 3).toFixed(1)}px solid ${r.colors.pop}`,
                opacity: (1 - p * p).toFixed(3),
                boxSizing: 'border-box',
              }}
            />
          </div>
        ),
      )}
      <div style={{position: 'absolute', left, top, width: box.w, height: box.h, perspective: 900}}>
        <div
          style={{
            position: 'absolute',
            inset: 0,
            transformOrigin: origin,
            transform: `${transformOf(pose)} rotateY(${pose.rotateY.toFixed(2)}deg)`,
            transformStyle: 'preserve-3d',
          }}
        >
          <Img src={art} style={face('art')} alt="" />
          {pose.rotateY !== 0 ? <Img src={art} style={face('back', true)} alt="" /> : null}
          {pose.shine !== null ? <Shine art={art} box={box} at={pose.shine} id={cellId} /> : null}
        </div>
      </div>
      {pose.sparkles.map((s, i) => {
        const spots = [
          [left + box.w * 0.95, top + box.h * 0.05, 78],
          [left + box.w * 0.02, top + box.h * 0.3, 58],
          [left + box.w * 0.9, top + box.h * 0.95, 64],
        ] as const;
        const [x, y, size] = spots[i % spots.length]!;
        const clampX = Math.min(CELL - MARGIN - size / 2, Math.max(MARGIN + size / 2, x));
        const clampY = Math.min(CELL - MARGIN - size / 2, Math.max(MARGIN + size / 2, y));
        return <Sparkle key={i} x={clampX} y={clampY} size={size} scale={s} color={i === 1 ? r.colors.accent : r.colors.pop} />;
      })}
    </>
  );
};

const TextSticker: React.FC<{r: Resolved; layout: TextLayout; family: string; pose: Pose}> = ({r, layout, family, pose}) => {
  const step = Math.max(3, Math.round(layout.px / 18));
  let index = 0;
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
      <div style={{transform: transformOf(pose), transformOrigin: '50% 50%'}}>
        <div
          style={{
            filter: `url(#${filterId('text')})`,
            padding: OUTLINE_TEXT + 4,
            fontFamily: family,
            fontWeight: 700,
            fontSize: layout.px,
            lineHeight: LINE_HEIGHT,
            color: r.colors.ink,
            textAlign: 'center',
            textShadow: `0 ${step}px 0 ${r.colors.inkDeep}`,
            whiteSpace: 'nowrap',
          }}
        >
          {layout.lines.map((line, li) => (
            <div key={li}>
              {line.map((word, wi) => {
                const lift = pose.wordLift[index++] ?? 0;
                return (
                  <React.Fragment key={wi}>
                    {wi > 0 ? ' ' : null}
                    <span style={{display: 'inline-block', transform: `translateY(${lift.toFixed(2)}px)`}}>{word}</span>
                  </React.Fragment>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** One frame of the sticker at time `t` (seconds), on a transparent 512×512 cell. */
const StickerFrame: React.FC<{
  r: Resolved;
  t: number;
  box: Size | null;
  text: TextLayout | null;
  family: string;
  cellId: string;
}> = ({r, t, box, text, family, cellId}) => {
  const words = text ? text.lines.reduce((n, l) => n + l.length, 0) : 0;
  const pose = poseAt(r.motion, t, words);
  return (
    <AbsoluteFill style={{width: CELL, height: CELL, overflow: 'hidden'}}>
      {r.motion === 'texto'
        ? text && <TextSticker r={r} layout={text} family={family} pose={pose} />
        : box && <ArtSticker r={r} box={box} pose={pose} cellId={cellId} />}
    </AbsoluteFill>
  );
};

/** Hooks shared by the sheet and the preview: font, art size, text layout. */
const useSticker = (raw: StickerInput) => {
  const r = useMemo(() => resolve(raw), [raw]);
  const font = useStickerFont(r.fontFile, r.fontFamily);
  const natural = useArtSize(r.motion === 'texto' ? null : r.art);
  const box = useMemo(() => (natural ? artBox(natural, r.motion) : null), [natural, r.motion]);
  const text = useMemo(
    () => (r.motion === 'texto' && font.ready ? fitText(r.text, font.family) : null),
    [r.motion, r.text, font.ready, font.family],
  );
  return {r, font, box, text};
};

// ------------------------------------------------------------------ compositions

export type StickerProps = StickerInput;

/** Every frame of the loop in a grid, left to right, top to bottom. */
export const StickerSheet: React.FC<StickerProps> = (raw) => {
  const {r, font, box, text} = useSticker(raw);
  const {cell, columns, frames, fps} = SHEET;
  return (
    <AbsoluteFill style={{background: 'transparent'}}>
      <Filters colors={r.colors} />
      {Array.from({length: frames}, (_, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: (i % columns) * cell,
            top: Math.floor(i / columns) * cell,
            width: cell,
            height: cell,
            overflow: 'hidden',
          }}
        >
          <StickerFrame r={r} t={i / fps} box={box} text={text} family={font.family} cellId={`c${i}`} />
        </div>
      ))}
    </AbsoluteFill>
  );
};

/** Studio only: the same sticker playing. */
export const StickerPreview: React.FC<StickerProps> = (raw) => {
  const {r, font, box, text} = useSticker(raw);
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{background: 'transparent'}}>
      <Filters colors={r.colors} />
      <StickerFrame r={r} t={frame / SHEET.fps} box={box} text={text} family={font.family} cellId="p" />
    </AbsoluteFill>
  );
};
