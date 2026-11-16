// `video_text` v1 (EF-05, m-25026573): the owner's text over a video, as ONE transparent PNG of
// 1080×1920 that Python lays over every frame (`qualify_creative.video.text_overlay`). Remotion
// never encodes the video: it draws the layer, PyAV composes.
//
// The layer is an ADR 49 `scrim` drawn by layer_still's own code: the same fonts and timeout
// rule (`resolveBrandFamilies`), the same canvas measurer (`canvasMeasurer`), the same engine
// (`resolveLayer`, through `layout.ts`), the same `Scrim` and `TextBlocks` components. The only
// differences from a 9:16 image are what `layout.ts` documents (longer texts, the owner's place
// never moved, «middle») and the canvas: no photo, no logo, nothing but the scrim and the
// letters on a transparent background.
import React from 'react';
import {AbsoluteFill, type CalculateMetadataFunction} from 'remotion';
import layerManifest from '../../../templates/layer_still/manifest.json';
import manifest from '../../../templates/video_text/manifest.json';
import {resolveBrandFamilies, useExactFamilies} from '../../fonts';
import {normalizeProps, paletteOf, textOf, type PropsInput} from '../../props';
import {resolveLayer, type Catalog} from '../layer_still/engine';
import {Scrim, TextBlocks, canvasMeasurer} from '../layer_still/LayerStill';
import {resolveVideoText, type VideoTextConfig, type VideoTextResolved} from './layout';

export const CATALOG = layerManifest.layer_catalog as unknown as Catalog;
export const CONFIG = manifest.video_text as unknown as VideoTextConfig;
export const OVERLAY = manifest.outputs.overlay;

export type VideoTextProps = PropsInput & {resolved?: VideoTextResolved | null};

export const videoTextMetadata: CalculateMetadataFunction<VideoTextProps> = async ({props}) => {
  const base = normalizeProps(props);
  if (base.meta?.port !== undefined && base.meta.port !== 'overlay') {
    throw new Error(`invalid_parameters: unknown port '${base.meta.port}' for video_text`);
  }
  const families = await resolveBrandFamilies(base.brand.fonts.heading, base.brand.fonts.body);
  await document.fonts.ready;
  const {measure, ink} = canvasMeasurer(families);
  const resolved = resolveVideoText({
    catalog: CATALOG,
    config: CONFIG,
    text: textOf(base, 'text'),
    place: textOf(base, 'place'),
    layoutId: textOf(base, 'layout_id'),
    layoutVersion: Number(base.texts.layout_version),
    headingFamily: base.brand.fonts.heading ?? '',
    palette: paletteOf(base.brand),
    measure,
    ink,
    fonts: families,
    resolve: resolveLayer,
  });
  return {props: {...props, resolved}};
};

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
