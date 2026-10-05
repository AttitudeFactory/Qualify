// Scene timing for promo_producto. Pure and deterministic: the same props always yield
// the same script, which is what lets calculateMetadata (duration) and the component
// (what to draw at frame N) agree. Durations are clamped to the manifest's
// duration.min_sec/max_sec (CONTRACT §3).
import type {Props} from '../../props';

export const FPS = 30;
export const HOOK_SEC = 2.0;
export const PHOTO_SEC = 2.5;
export const CTA_SEC = 2.5;
export const CROSSFADE_FRAMES = 12;

export type Scene =
  | {kind: 'hook'; from: number; durationInFrames: number; photo: string}
  | {kind: 'photo'; from: number; durationInFrames: number; photo: string; index: number}
  | {kind: 'cta'; from: number; durationInFrames: number};

export type Script = {scenes: Scene[]; durationInFrames: number; durationSec: number};

export type DurationBounds = {minSec: number; maxSec: number};

const toFrames = (sec: number): number => Math.max(1, Math.round(sec * FPS));

export const buildScript = (props: Props, bounds: DurationBounds): Script => {
  const photos = props.photos.length > 0 ? props.photos : [''];
  const natural = HOOK_SEC + PHOTO_SEC * photos.length + CTA_SEC;

  // Over max: shrink the photo scenes proportionally. Under min: stretch the CTA.
  let photoSec = PHOTO_SEC;
  let ctaSec = CTA_SEC;
  if (natural > bounds.maxSec) {
    const room = Math.max(0.6 * photos.length, bounds.maxSec - HOOK_SEC - CTA_SEC);
    photoSec = room / photos.length;
  } else if (natural < bounds.minSec) {
    ctaSec = CTA_SEC + (bounds.minSec - natural);
  }

  const scenes: Scene[] = [];
  let cursor = 0;
  const hookFrames = toFrames(HOOK_SEC);
  scenes.push({kind: 'hook', from: cursor, durationInFrames: hookFrames, photo: photos[0] ?? ''});
  cursor += hookFrames;
  photos.forEach((photo, index) => {
    const d = toFrames(photoSec);
    scenes.push({kind: 'photo', from: cursor, durationInFrames: d, photo, index});
    cursor += d;
  });
  const ctaFrames = toFrames(ctaSec);
  scenes.push({kind: 'cta', from: cursor, durationInFrames: ctaFrames});
  cursor += ctaFrames;

  return {scenes, durationInFrames: cursor, durationSec: cursor / FPS};
};
