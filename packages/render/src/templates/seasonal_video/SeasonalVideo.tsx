// Seasonal short video for WhatsApp (recipe D, m-25016848; founder 2026-11-12: the FFmpeg
// slideshow of recipe B looked plain). One `seasonal-video-v1--clip` composition, four
// motions — one per recipe-B slot, so the library's slot names stay the same:
//
// | motion     | slot      | photos | what moves                                               |
// |------------|-----------|--------|----------------------------------------------------------|
// | `acercar`  | `b-zoom`  | 1      | eased push-in drifting toward the upper third            |
// | `recorrer` | `b-pan`   | 1      | eased pan across a 1.22× photo with a slow zoom          |
// | `fundido`  | `b-xfade` | 2–3    | each photo its own Ken Burns; brand-colour wipe between   |
// | `logo`     | `b-logo`  | 0–1    | brand gradient (or the photo, then a circle reveal) and   |
// |            |           |        | the logo card springing in, a ring pulse and a shine      |
//
// The photo motions close with a small sign-off: the logo on a card of the contrast colour
// (`texts.card`, decided in Python by `qualify_creative.seasonal.backing`) — when the
// brand has a logo. 720 px wide, `texts.height` tall (720–1280, from the first photo's
// aspect, the same rule as recipe B), 24 fps, 4 s (5 s for a 3-photo `fundido`), silent.
// Python re-encodes the MP4 to WhatsApp's profile (H.264 Main, no B-frames) and checks it.
// No network, no randomness: same props → same frames.
import React, {useEffect, useMemo, useState} from 'react';
import {
  AbsoluteFill,
  Easing,
  Img,
  continueRender,
  delayRender,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  type CalculateMetadataFunction,
} from 'remotion';
import manifest from '../../../templates/seasonal_video/manifest.json';
import {normalizeProps, textOf, type PropsInput} from '../../props';
import {contrastOf, luminance, parseHex} from '../sticker/look';

export const FPS = 24;
export const WIDTH = manifest.outputs.clip.width;
export const MAX_HEIGHT = manifest.outputs.clip.height;
const MIN_HEIGHT = 720;

export type Motion = 'acercar' | 'recorrer' | 'fundido' | 'logo';
const MOTIONS: readonly Motion[] = ['acercar', 'recorrer', 'fundido', 'logo'];
const isMotion = (s: string): s is Motion => (MOTIONS as readonly string[]).includes(s);

/** 4 s, or 5 s for a three-photo cross-over (B's two-photo cross-fade was 3.5 s; every
 * length stays inside WhatsApp's 3–5 s check). */
export const secondsOf = (motion: Motion, photos: number): number => (motion === 'fundido' && photos >= 3 ? 5 : 4);

export const heightOf = (raw: unknown): number => {
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n)) return MAX_HEIGHT;
  return Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, Math.round(n / 2) * 2));
};

// ------------------------------------------------------------------ props

export type SeasonalVideoProps = PropsInput;

type RGB = [number, number, number];

type Colors = {
  primary: string;
  secondary: string;
  /** the logo card's fill: white, or dark behind a light logo */
  card: string;
  /** rings and the thin rule under the sign-off: a brand colour that reads on the card */
  ring: string;
  /** the wipe's leading band and trailing band */
  band: string;
  bandTrail: string;
};

const NEAR_BLACK: RGB = [20, 23, 26];
const HOUSE: RGB = [15, 118, 110];
const WHITE: RGB = [255, 255, 255];

const toHex = ([r, g, b]: RGB): string =>
  `#${[r, g, b].map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, '0')).join('')}`;
const mix = (a: RGB, b: RGB, k: number): RGB => [0, 1, 2].map((i) => a[i]! + (b[i]! - a[i]!) * k) as RGB;

const colorsOf = (palette: string[], cardHex: string): Colors => {
  const parsed = palette.map(parseHex).filter((c): c is RGB => c !== null);
  const primary = parsed[0] ?? HOUSE;
  const secondary = parsed[1] ?? mix(primary, WHITE, 0.45);
  const card = parseHex(cardHex) ?? WHITE;
  const ring =
    parsed.find((c) => contrastOf(c, card) >= 3) ?? (luminance(card) < 0.5 ? WHITE : NEAR_BLACK);
  // the trailing band: the secondary unless it is the primary's twin
  const trail = contrastOf(primary, secondary) >= 1.4 ? secondary : mix(primary, WHITE, 0.5);
  return {
    primary: toHex(primary),
    secondary: toHex(secondary),
    card: toHex(card),
    ring: toHex(ring),
    band: toHex(primary),
    bandTrail: toHex(trail),
  };
};

type Resolved = {
  motion: Motion;
  photos: string[];
  logo: string | null;
  colors: Colors;
  seconds: number;
};

const resolve = (raw: SeasonalVideoProps): Resolved => {
  const props = normalizeProps(raw);
  const motion = textOf(props, 'motion');
  if (!isMotion(motion)) throw new Error(`seasonal_video: unknown motion '${motion}'`);
  const photos = props.photos.filter((p) => typeof p === 'string' && p.length > 0).slice(0, 3);
  const logo = typeof props.brand.logo === 'string' && props.brand.logo.length > 0 ? props.brand.logo : null;
  if (motion === 'fundido' && photos.length < 2) throw new Error("seasonal_video: 'fundido' needs 2–3 photos");
  if ((motion === 'acercar' || motion === 'recorrer') && photos.length < 1) {
    throw new Error(`seasonal_video: '${motion}' needs a photo`);
  }
  if (motion === 'logo' && !logo) throw new Error("seasonal_video: 'logo' needs the brand's logo");
  return {
    motion,
    photos,
    logo,
    colors: colorsOf(props.brand.palette, textOf(props, 'card')),
    seconds: secondsOf(motion, photos.length),
  };
};

export const seasonalVideoMetadata: CalculateMetadataFunction<SeasonalVideoProps> = ({props}) => {
  const r = resolve(props);
  const normalized = normalizeProps(props);
  return {
    durationInFrames: Math.round(r.seconds * FPS),
    fps: FPS,
    width: WIDTH,
    height: heightOf(normalized.texts.height),
  };
};

// ------------------------------------------------------------------ helpers

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
/** Slow at both ends, steady in the middle: a camera move, not a slide. */
const camera = Easing.bezier(0.45, 0.05, 0.55, 0.95);
const wipeEase = Easing.bezier(0.7, 0, 0.3, 1);

type Size = {w: number; h: number};

/** Natural size of an image; blocks the render until known. */
const useImageSize = (url: string | null): Size | null => {
  const [size, setSize] = useState<Size | null>(null);
  const [handle] = useState(() => (url ? delayRender(`seasonal video logo: ${url.slice(-24)}`) : null));
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

type Pose = {s: number; x: number; y: number};

/**
 * A photo filling the frame (object-fit cover) at scale `s`, moved by (x, y) percent of
 * the frame. The move is clamped to the headroom the scale leaves, so an edge never shows.
 */
const Photo: React.FC<{src: string; pose: Pose}> = ({src, pose}) => {
  const room = ((pose.s - 1) / 2) * 100;
  const x = Math.max(-room, Math.min(room, pose.x));
  const y = Math.max(-room, Math.min(room, pose.y));
  return (
    <Img
      src={src}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        objectFit: 'cover',
        transform: `translate(${x.toFixed(3)}%, ${y.toFixed(3)}%) scale(${pose.s.toFixed(4)})`,
        transformOrigin: '50% 50%',
      }}
    />
  );
};

const lerpPose = (a: Pose, b: Pose, k: number): Pose => ({
  s: a.s + (b.s - a.s) * k,
  x: a.x + (b.x - a.x) * k,
  y: a.y + (b.y - a.y) * k,
});

/** Darkened corners and a soft floor, so the sign-off and the brand bands sit on the photo. */
const Vignette: React.FC<{floor: number}> = ({floor}) => (
  <AbsoluteFill
    style={{
      background: [
        'radial-gradient(ellipse 85% 75% at 50% 45%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.28) 100%)',
        `linear-gradient(180deg, rgba(0,0,0,0) 62%, rgba(0,0,0,${floor.toFixed(3)}) 100%)`,
      ].join(', '),
    }}
  />
);

// ------------------------------------------------------------------ the logo card

const LogoCard: React.FC<{
  logo: string;
  natural: Size;
  colors: Colors;
  width: number;
  maxHeight: number;
  /** frames since the card started entering (negative: not yet) */
  local: number;
  shineAt: number;
  ringPulse: boolean;
  /** shown at rest from its first frame (the logo-only video: frame 0 is WhatsApp's
   * thumbnail, so it must already show the brand) and only settles from 92 % */
  visibleFromStart?: boolean;
}> = ({logo, natural, colors, width, maxHeight, local, shineAt, ringPulse, visibleFromStart = false}) => {
  const {fps} = useVideoConfig();
  if (local < 0) return null;
  const enter = spring({frame: local, fps, config: {damping: 13, stiffness: 150, mass: 0.9}});
  const opacity = visibleFromStart ? 1 : interpolate(local, [0, 7], [0, 1], {extrapolateRight: 'clamp'});
  const breathe = 1 + 0.012 * Math.sin((local / fps) * Math.PI * 1.1) * clamp01((local - 18) / 12);
  const from = visibleFromStart ? 0.92 : 0.72;
  const scale = (from + (1 - from) * enter) * breathe;
  const rotate = visibleFromStart ? 0 : (1 - enter) * -5;
  const pad = Math.round(width * 0.09);
  const inner = width - 2 * pad;
  const aspect = natural.h / Math.max(1, natural.w);
  const logoH = Math.min(inner * aspect, maxHeight - 2 * pad);
  const logoW = logoH / aspect;
  const height = Math.round(logoH + 2 * pad);
  const radius = Math.round(Math.min(width, height) * 0.16);
  const shine = interpolate(local, [shineAt, shineAt + 16], [-0.6, 1.6], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.cubic),
  });
  const ring = ringPulse ? clamp01((local - 8) / 22) : 1;
  return (
    <div style={{position: 'relative', width, height, transform: `scale(${scale.toFixed(4)}) rotate(${rotate.toFixed(2)}deg)`, opacity}}>
      {ringPulse && ring < 1 ? (
        <div
          style={{
            position: 'absolute',
            inset: -(10 + 70 * ring),
            borderRadius: radius + 10 + 70 * ring,
            border: `${(6 * (1 - ring) + 1).toFixed(1)}px solid ${colors.ring}`,
            opacity: 1 - ring,
          }}
        />
      ) : null}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: radius,
          background: colors.card,
          boxShadow: '0 22px 50px rgba(0,0,0,0.30), 0 4px 12px rgba(0,0,0,0.18)',
          overflow: 'hidden',
        }}
      >
        <Img
          src={logo}
          style={{
            position: 'absolute',
            left: (width - logoW) / 2,
            top: pad,
            width: logoW,
            height: logoH,
            objectFit: 'contain',
          }}
        />
        {shine > -0.6 && shine < 1.6 ? (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background: `linear-gradient(115deg, rgba(255,255,255,0) ${((shine - 0.25) * 100).toFixed(1)}%, rgba(255,255,255,0.38) ${(shine * 100).toFixed(1)}%, rgba(255,255,255,0) ${((shine + 0.25) * 100).toFixed(1)}%)`,
            }}
          />
        ) : null}
      </div>
    </div>
  );
};

/** The photo videos' close: the logo card, small, low and centred, with a rule under it. */
const SignOff: React.FC<{r: Resolved; natural: Size | null; startFrame: number}> = ({r, natural, startFrame}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  if (!r.logo || !natural) return null;
  const local = frame - startFrame;
  if (local < 0) return null;
  const rise = spring({frame: local, fps, config: {damping: 200, stiffness: 110}});
  const rule = interpolate(local, [6, 20], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const cardW = Math.round(width * 0.54);
  // above WhatsApp's own bottom strip (duration, time, ticks: ~10–12 % of the bubble)
  const bottom = Math.round(Math.max(96, height * 0.11));
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'flex-end', paddingBottom: bottom}}>
      <div style={{transform: `translateY(${((1 - rise) * 36).toFixed(2)}px)`, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14}}>
        <LogoCard
          logo={r.logo}
          natural={natural}
          colors={r.colors}
          width={cardW}
          maxHeight={Math.round(height * 0.2)}
          local={local}
          shineAt={14}
          ringPulse={false}
        />
        <div style={{width: cardW * 0.5 * rule, height: 5, borderRadius: 3, background: r.colors.band, boxShadow: '0 2px 8px rgba(0,0,0,0.25)'}} />
      </div>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ motions

/** When the sign-off starts: 1.5 s before the end. */
const signOffStart = (seconds: number) => Math.round((seconds - 1.5) * FPS);

const Acercar: React.FC<{r: Resolved; natural: Size | null}> = ({r, natural}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const k = camera(clamp01(frame / (durationInFrames - 1)));
  const pose = lerpPose({s: 1.02, x: 0, y: 0}, {s: 1.17, x: -1.2, y: 2.4}, k);
  const start = signOffStart(r.seconds);
  const floor = 0.18 + 0.27 * clamp01((frame - start + 6) / 14);
  return (
    <AbsoluteFill style={{background: '#000', overflow: 'hidden'}}>
      <Photo src={r.photos[0]!} pose={pose} />
      <Vignette floor={floor} />
      <SignOff r={r} natural={natural} startFrame={start} />
    </AbsoluteFill>
  );
};

const Recorrer: React.FC<{r: Resolved; natural: Size | null}> = ({r, natural}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const k = camera(clamp01(frame / (durationInFrames - 1)));
  const pose = lerpPose({s: 1.22, x: 9.5, y: 1.2}, {s: 1.26, x: -9.5, y: -1.2}, k);
  const start = signOffStart(r.seconds);
  const floor = 0.18 + 0.27 * clamp01((frame - start + 6) / 14);
  return (
    <AbsoluteFill style={{background: '#000', overflow: 'hidden'}}>
      <Photo src={r.photos[0]!} pose={pose} />
      <Vignette floor={floor} />
      <SignOff r={r} natural={natural} startFrame={start} />
    </AbsoluteFill>
  );
};

/** How long one wipe between photos lasts. */
const WIPE_SECONDS = 0.6;

const Fundido: React.FC<{r: Resolved; natural: Size | null}> = ({r, natural}) => {
  const frame = useCurrentFrame();
  const {width} = useVideoConfig();
  const n = r.photos.length;
  const wipe = Math.round(WIPE_SECONDS * FPS);
  const total = Math.round(r.seconds * FPS);
  const segment = Math.round((total + (n - 1) * wipe) / n);
  const startOf = (i: number) => i * (segment - wipe);
  const start = signOffStart(r.seconds);
  const floor = 0.18 + 0.27 * clamp01((frame - start + 6) / 14);
  const bandW = Math.round(width * 0.05);
  const trailW = Math.round(width * 0.035);
  return (
    <AbsoluteFill style={{background: '#000', overflow: 'hidden'}}>
      {r.photos.map((src, i) => {
        const from = startOf(i);
        const until = i === n - 1 ? total : from + segment;
        if (frame < from || frame >= until + 1) return null;
        const k = camera(clamp01((frame - from) / Math.max(1, until - from)));
        // alternate in and out, left and right, so consecutive photos never move alike
        const a: Pose = i % 2 === 0 ? {s: 1.05, x: 2, y: 1} : {s: 1.16, x: -2.5, y: -1.5};
        const b: Pose = i % 2 === 0 ? {s: 1.16, x: -2, y: -1.5} : {s: 1.05, x: 2, y: 1};
        let pose = lerpPose(a, b, k);
        // the outgoing photo is pushed left while the next one comes in
        const next = startOf(i + 1);
        if (i < n - 1 && frame >= next) {
          const out = wipeEase(clamp01((frame - next) / wipe));
          pose = {...pose, s: pose.s + 0.04 * out, x: pose.x - 5 * out};
        }
        const reveal = i === 0 ? 1 : wipeEase(clamp01((frame - from) / wipe));
        const edge = (1 - reveal) * width;
        return (
          <React.Fragment key={i}>
            <AbsoluteFill style={{clipPath: reveal < 1 ? `inset(0 0 0 ${edge.toFixed(2)}px)` : undefined, overflow: 'hidden'}}>
              <Photo src={src} pose={pose} />
            </AbsoluteFill>
            {reveal > 0 && reveal < 1 ? (
              <>
                <div style={{position: 'absolute', top: 0, bottom: 0, left: edge - bandW, width: bandW, background: r.colors.band, boxShadow: '0 0 24px rgba(0,0,0,0.25)'}} />
                <div style={{position: 'absolute', top: 0, bottom: 0, left: edge - bandW - trailW * 1.6, width: trailW, background: r.colors.bandTrail, opacity: 0.8}} />
              </>
            ) : null}
          </React.Fragment>
        );
      })}
      <Vignette floor={floor} />
      <SignOff r={r} natural={natural} startFrame={start} />
    </AbsoluteFill>
  );
};

/** Two soft light/shade circles drifting over the brand gradient (deterministic). */
const BrandBackdrop: React.FC<{colors: Colors}> = ({colors}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const t = frame / FPS;
  const d = Math.max(width, height);
  const c1 = {x: width * (0.18 + 0.06 * Math.sin(t * 0.9)), y: height * (0.2 + 0.04 * Math.cos(t * 0.7))};
  const c2 = {x: width * (0.85 - 0.05 * Math.sin(t * 0.8)), y: height * (0.82 + 0.03 * Math.sin(t * 1.1))};
  return (
    <AbsoluteFill style={{background: `linear-gradient(160deg, ${colors.primary} 0%, ${colors.secondary} 100%)`}}>
      <div style={{position: 'absolute', left: c1.x - d * 0.4, top: c1.y - d * 0.4, width: d * 0.8, height: d * 0.8, borderRadius: '50%', background: 'radial-gradient(circle, rgba(255,255,255,0.22) 0%, rgba(255,255,255,0) 68%)'}} />
      <div style={{position: 'absolute', left: c2.x - d * 0.45, top: c2.y - d * 0.45, width: d * 0.9, height: d * 0.9, borderRadius: '50%', background: 'radial-gradient(circle, rgba(0,0,0,0.20) 0%, rgba(0,0,0,0) 66%)'}} />
    </AbsoluteFill>
  );
};

const Logo: React.FC<{r: Resolved; natural: Size | null}> = ({r, natural}) => {
  const frame = useCurrentFrame();
  const {width, height, durationInFrames} = useVideoConfig();
  const photo = r.photos[0];
  // with a photo: 2 s of photo, then the brand backdrop opens from the centre
  const openAt = photo ? Math.round(1.7 * FPS) : 0;
  const open = photo ? wipeEase(clamp01((frame - openAt) / Math.round(0.6 * FPS))) : 1;
  const cardAt = photo ? openAt + Math.round(0.3 * FPS) : 0;
  const k = camera(clamp01(frame / (durationInFrames - 1)));
  const radius = Math.hypot(width, height) / 2;
  return (
    <AbsoluteFill style={{background: '#000', overflow: 'hidden'}}>
      {photo && open < 1 ? (
        <>
          <Photo src={photo} pose={lerpPose({s: 1.04, x: 0, y: 0}, {s: 1.15, x: 1, y: 1.5}, k)} />
          <Vignette floor={0.2} />
        </>
      ) : null}
      {open > 0 ? (
        <AbsoluteFill style={{clipPath: open < 1 ? `circle(${(radius * open).toFixed(1)}px at 50% 50%)` : undefined}}>
          <BrandBackdrop colors={r.colors} />
        </AbsoluteFill>
      ) : null}
      {natural && r.logo ? (
        // above the centre: WhatsApp draws its play button in the middle of the thumbnail
        <AbsoluteFill style={{alignItems: 'center', justifyContent: 'flex-start', paddingTop: Math.round(height * 0.14)}}>
          <LogoCard
            logo={r.logo}
            natural={natural}
            colors={r.colors}
            width={Math.round(width * 0.62)}
            maxHeight={Math.round(height * 0.5)}
            local={frame - cardAt}
            shineAt={26}
            ringPulse
            visibleFromStart={!photo}
          />
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ composition

export const SeasonalVideo: React.FC<SeasonalVideoProps> = (raw) => {
  const r = useMemo(() => resolve(raw), [raw]);
  const natural = useImageSize(r.logo);
  switch (r.motion) {
    case 'acercar':
      return <Acercar r={r} natural={natural} />;
    case 'recorrer':
      return <Recorrer r={r} natural={natural} />;
    case 'fundido':
      return <Fundido r={r} natural={natural} />;
    case 'logo':
      return <Logo r={r} natural={natural} />;
  }
};
