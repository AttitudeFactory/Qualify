// `video_text` (EF-05, m-25026573; v2 ED-13, m-25029108): the owner's text over a video, as
// transparent PNGs of 1080×1920 that Python lays over the frames
// (`qualify_creative.video.text_overlay`). Remotion never encodes the video: it draws the
// layer, PyAV composes.
//
// The layer is an ADR 49 `scrim` text block drawn by layer_still's own code: the same fonts and
// timeout rule (`resolveBrandFamilies`), the same canvas measurer (`canvasMeasurer`), the same
// engine (`resolveLayer`, through `layout.ts`), the same `Scrim` and `TextBlocks` components.
// The only differences from a 9:16 image are what `layout.ts` documents (longer texts, the
// owner's place never moved, «middle», v2's backgrounds) and the canvas: no photo, no logo,
// nothing but the background and the letters on a transparent background.
//
// v1 (`manifest.v1.json`, port `overlay`) is kept as it was: a render pinned to it draws the
// same pixels. v2 (`manifest.json`) adds the backgrounds `band`, `brand_fill` and `shadow`
// (clean letters, no text shadow), `band`/`brand_fill` in a colour the owner picked (`box_color`),
// the brand's own font file (`brand.fontFiles.heading`, an asset) and two more ports of the
// SAME layout for «Letra por letra»: `backdrop` (only the background) and `letters` (only the
// letters, whose report carries every character's box).
import React from 'react';
import {AbsoluteFill, type CalculateMetadataFunction} from 'remotion';
import layerManifest from '../../../templates/layer_still/manifest.json';
import manifestV2 from '../../../templates/video_text/manifest.json';
import manifestV1 from '../../../templates/video_text/manifest.v1.json';
import {resolveBrandFamilies, useExactFamilies} from '../../fonts';
import {normalizeProps, paletteOf, textOf, type PropsInput} from '../../props';
import {resolveLayer, textColorOn, type Catalog} from '../layer_still/engine';
import {Scrim, TextBlocks, canvasMeasurer} from '../layer_still/LayerStill';
import {resolveVideoText, type VideoTextConfig, type VideoTextResolved} from './layout';

export const CATALOG = layerManifest.layer_catalog as unknown as Catalog;
export const CONFIG = manifestV1.video_text as unknown as VideoTextConfig;
export const CONFIG_V2 = manifestV2.video_text as unknown as VideoTextConfig;
export const OVERLAY = manifestV1.outputs.overlay;
export const PORTS_V2 = manifestV2.outputs;

/** What a port draws: everything, only the background, only the letters. */
export type VideoTextPort = 'overlay' | 'backdrop' | 'letters';

export type VideoTextProps = PropsInput & {resolved?: VideoTextResolved | null};

type BrandWithFiles = {fontFiles?: {heading?: unknown}};

const headingFileOf = (raw: PropsInput): string | undefined => {
  const file = (raw.brand as BrandWithFiles | undefined)?.fontFiles?.heading;
  return typeof file === 'string' && file.length > 0 ? file : undefined;
};

const metadataFor =
  (config: VideoTextConfig, ports: readonly string[]): CalculateMetadataFunction<VideoTextProps> =>
  async ({props}) => {
    const base = normalizeProps(props);
    if (base.meta?.port !== undefined && !ports.includes(base.meta.port)) {
      throw new Error(`invalid_parameters: unknown port '${base.meta.port}' for video_text`);
    }
    // v1 never reads a font file: its pixels stay a function of the family names
    const file = config.box !== undefined ? headingFileOf(props) : undefined;
    const families = await resolveBrandFamilies(base.brand.fonts.heading, base.brand.fonts.body, file);
    await document.fonts.ready;
    const {measure, ink} = canvasMeasurer(families);
    const palette = paletteOf(base.brand);
    const resolved = resolveVideoText({
      catalog: CATALOG,
      config,
      text: textOf(base, 'text'),
      place: textOf(base, 'place'),
      layoutId: textOf(base, 'layout_id'),
      layoutVersion: Number(base.texts.layout_version),
      headingFamily: base.brand.fonts.heading ?? '',
      palette,
      measure,
      ink,
      fonts: families,
      resolve: resolveLayer,
      inkOn: (bg) => textColorOn(bg, palette),
      // ED-13: the colour the owner picked for «Franja» / «Recuadro de tu color» ('' = none)
      boxColor: textOf(base, 'box_color') || null,
      // ED-13 round 3: «Sin fondo»'s letters in the colour picked ('' = white, no shadow)
      textColor: textOf(base, 'text_color') || null,
      // ED-13 round 4: the letters' size ('' = «Mediana», the catalog's own)
      textSize: textOf(base, 'text_size') || null,
    });
    return {props: {...props, resolved}};
  };

export const videoTextMetadata = metadataFor(CONFIG, ['overlay']);
export const videoTextMetadataV2 = metadataFor(CONFIG_V2, Object.keys(PORTS_V2));

const Background: React.FC<{resolved: VideoTextResolved}> = ({resolved}) => (
  <>
    {resolved.scrims.map((s, i) => (
      <Scrim key={`s${i}`} scrim={s} />
    ))}
    {(resolved.containers ?? []).map((c, i) => (
      <div
        key={`c${i}`}
        style={{
          position: 'absolute',
          left: c.rect.x,
          top: c.rect.y,
          width: c.rect.w,
          height: c.rect.h,
          borderRadius: c.radius,
          background: c.color,
        }}
      />
    ))}
  </>
);

const drawer = (port: VideoTextPort): React.FC<VideoTextProps> => {
  const Drawn: React.FC<VideoTextProps> = (raw) => {
    const resolved = raw.resolved;
    const fonts = useExactFamilies(resolved?.report.fonts, headingFileOf(raw));
    // calculateMetadata always sets it; without it nothing was checked, so draw nothing
    if (!resolved) return <AbsoluteFill />;
    // «Sin fondo» draws only the letters: no text shadow, no outline (Deivid, 2026-11-23)
    return (
      <AbsoluteFill>
        {port !== 'letters' ? <Background resolved={resolved} /> : null}
        {port !== 'backdrop' ? (
          <AbsoluteFill>
            <TextBlocks texts={resolved.texts} fonts={fonts} />
          </AbsoluteFill>
        ) : null}
      </AbsoluteFill>
    );
  };
  return Drawn;
};

/** v1's component (port `overlay`). */
export const VideoText: React.FC<VideoTextProps> = (raw) => {
  const resolved = raw.resolved;
  const fonts = useExactFamilies(resolved?.report.fonts);
  // calculateMetadata always sets it; without it nothing was checked, so draw nothing
  if (!resolved) return <AbsoluteFill />;
  return (
    <AbsoluteFill>
      {resolved.scrims.map((s, i) => (
        <Scrim key={`s${i}`} scrim={s} />
      ))}
      <TextBlocks texts={resolved.texts} fonts={fonts} />
    </AbsoluteFill>
  );
};

/** v2's components, one per port. */
export const VIDEO_TEXT_V2: Record<VideoTextPort, React.FC<VideoTextProps>> = {
  overlay: drawer('overlay'),
  backdrop: drawer('backdrop'),
  letters: drawer('letters'),
};
