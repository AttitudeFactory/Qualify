// The sticker motions as pure functions of time (seconds into the 2 s loop). No React,
// no randomness: the sheet composition samples them at `frames` instants and Python
// encodes the samples into the animated WebP, so the same props give the same bytes.
//
// Every motion STARTS AND ENDS AT REST (WhatsApp shows the first frame as the sticker's
// still preview, and the loop must not jump): the movement happens in the first ~1.5 s
// and the art is still for the rest of the loop.

export const MOTIONS = ['latido', 'rebote', 'giro', 'brillo', 'texto'] as const;
export type Motion = (typeof MOTIONS)[number];
export const IMAGE_MOTIONS: readonly Motion[] = ['latido', 'rebote', 'giro', 'brillo'];

export const isMotion = (v: unknown): v is Motion =>
  typeof v === 'string' && (MOTIONS as readonly string[]).includes(v);

/** What the art does at one instant. Scales are about the transform origin. */
export type Pose = {
  scaleX: number;
  scaleY: number;
  /** px, negative = up */
  translateY: number;
  /** deg, in plane */
  rotate: number;
  /** deg, about the vertical axis (coin flip) */
  rotateY: number;
  /** 'center' or 'bottom' — squash and stretch happen on the ground */
  origin: 'center' | 'bottom';
  /** shine band position across the art, 0..1, null = no shine */
  shine: number | null;
  /** heartbeat rings: each ring's progress 0..1 (null = not shown) */
  rings: (number | null)[];
  /** sparkles: each one's scale 0..1 */
  sparkles: number[];
  /** ground shadow under a hopping art: 1 = on the ground, smaller = higher */
  ground: number | null;
  /** per-word lift (texto), px, negative = up */
  wordLift: number[];
};

const REST: Pose = {
  scaleX: 1,
  scaleY: 1,
  translateY: 0,
  rotate: 0,
  rotateY: 0,
  origin: 'center',
  shine: null,
  rings: [],
  sparkles: [],
  ground: null,
  wordLift: [],
};

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** Smooth 0→1 between a and b (cubic ease in-out). */
const ease = (t: number, a: number, b: number): number => {
  const x = clamp01((t - a) / (b - a));
  return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2;
};

/**
 * A spring's answer to a kick at time 0: rises fast, overshoots below zero once and
 * settles. Normalised so the first peak is ≈ 1. `freq` in Hz, `decay` per second.
 */
export const impulse = (tau: number, freq = 2.4, decay = 6.5): number => {
  if (tau <= 0) return 0;
  const w = 2 * Math.PI * freq;
  const peakT = Math.atan(w / decay) / w;
  const peak = Math.exp(-decay * peakT) * Math.sin(w * peakT);
  return (Math.exp(-decay * tau) * Math.sin(w * tau)) / peak;
};

/**
 * A spring released from 0 towards 1 at time 0 (under-damped: overshoots, then settles
 * at 1). `freq` in Hz, `damping` ratio.
 */
export const springTo = (tau: number, freq = 2.2, damping = 0.45): number => {
  if (tau <= 0) return 0;
  const w0 = 2 * Math.PI * freq;
  const wd = w0 * Math.sqrt(1 - damping * damping);
  const env = Math.exp(-damping * w0 * tau);
  return 1 - env * (Math.cos(wd * tau) + ((damping * w0) / wd) * Math.sin(wd * tau));
};

// --- latido: two heartbeats with rings ---------------------------------------------

const latido = (t: number): Pose => {
  const beat1 = impulse(t - 0.12, 3.0, 9);
  const beat2 = impulse(t - 0.5, 3.0, 9);
  const s = 1 + 0.12 * beat1 + 0.08 * beat2;
  const ring = (start: number) => {
    const p = (t - start) / 0.75;
    return p >= 0 && p <= 1 ? p : null;
  };
  return {...REST, scaleX: s, scaleY: s, rings: [ring(0.14), ring(0.52)]};
};

// --- rebote: anticipation, hop with stretch, landing squash, settle ----------------

const HOP_PX = 74;

const rebote = (t: number): Pose => {
  const crouchStart = 0.12;
  const takeOff = 0.3;
  const land = 0.86;
  let sx = 1;
  let sy = 1;
  let y = 0;
  if (t >= crouchStart && t < takeOff) {
    const c = ease(t, crouchStart, takeOff);
    sy = 1 - 0.14 * c;
    sx = 1 + 0.1 * c;
  } else if (t >= takeOff && t < land) {
    const p = (t - takeOff) / (land - takeOff);
    y = -HOP_PX * 4 * p * (1 - p);
    // stretched while fast, round at the top
    const speed = Math.abs(1 - 2 * p);
    sy = 1 + 0.1 * speed;
    sx = 1 - 0.07 * speed;
  } else if (t >= land) {
    const k = impulse(t - land, 2.6, 7.5);
    sy = 1 - 0.13 * k;
    sx = 1 + 0.1 * k;
  }
  const ground = 1 - (0.45 * -y) / HOP_PX;
  return {...REST, scaleX: sx, scaleY: sy, translateY: y, origin: 'bottom', ground};
};

// --- giro: a coin flip with a little hop -------------------------------------------

const giro = (t: number): Pose => {
  const start = 0.18;
  const turn = springTo(t - start, 1.15, 0.62); // one full turn, a soft overshoot
  const hop = t > start && t < start + 0.9 ? Math.sin((Math.PI * (t - start)) / 0.9) : 0;
  return {...REST, rotateY: 360 * turn, translateY: -26 * hop};
};

// --- brillo: a shine sweeps across, sparkles pop ------------------------------------

const brillo = (t: number): Pose => {
  const shineT = (t - 0.2) / 0.75;
  const shine = shineT >= 0 && shineT <= 1 ? ease(shineT, 0, 1) : null;
  const sparkle = (at: number) => {
    const tau = t - at;
    if (tau <= 0 || tau > 0.9) return 0;
    // pops in with a spring, fades away at the end of its life
    return Math.max(0, springTo(tau, 2.6, 0.4)) * (1 - ease(tau, 0.55, 0.9));
  };
  const s = 1 + 0.04 * impulse(t - 0.2, 1.6, 4.5);
  return {...REST, scaleX: s, scaleY: s, shine, sparkles: [sparkle(0.35), sparkle(0.55), sparkle(0.75)]};
};

// --- texto: the words hop one after the other, a wave ------------------------------
// Only the words move (no tilt or scale of the whole block): a block that turns changes
// every pixel of every frame, and a long greeting then weighs past WhatsApp's 500 KB.

const texto = (t: number, words: number): Pose => {
  const gap = Math.min(0.09, 0.7 / Math.max(1, words));
  const wordLift = Array.from({length: words}, (_, i) => -26 * impulse(t - 0.15 - gap * i, 2.2, 6));
  return {...REST, wordLift};
};

export const poseAt = (motion: Motion, t: number, words = 0): Pose => {
  switch (motion) {
    case 'latido':
      return latido(t);
    case 'rebote':
      return rebote(t);
    case 'giro':
      return giro(t);
    case 'brillo':
      return brillo(t);
    case 'texto':
      return texto(t, words);
  }
};
