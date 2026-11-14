// One <Composition>/<Still> per output port; id = `<template_id>_v<version>__<port>`,
// exactly the `composition` field of templates/<id>/manifest.json (CONTRACT §3).
// Dimensions and duration bounds are read from the manifests so there is one source.
// A published version is never edited (CONTRACT §1): v1 stays registered from its kept
// manifest (`manifest.v1.json`) so a render pinned to it keeps working; v2 (2026-10-13)
// adds the 4:5 and 1:1 video and the 1:1 still, so the «Video publicitario» and «Con
// plantilla» pieces exist in every Instagram format that suits them.
import React from 'react';
import {Composition, Still, staticFile, type CalculateMetadataFunction} from 'remotion';
import helloManifest from '../templates/hello_world/manifest.json';
import promoManifest from '../templates/promo_producto/manifest.json';
import promoManifestV1 from '../templates/promo_producto/manifest.v1.json';
import {normalizeProps, type PropsInput} from './props';
import {HelloWorld} from './templates/hello_world/HelloWorld';
import {PromoReel} from './templates/promo_producto/PromoReel';
import {PromoStill} from './templates/promo_producto/PromoStill';
import {FPS, buildScript} from './templates/promo_producto/script';
import stickerManifest from '../templates/sticker/manifest.json';
import stickerManifestV1 from '../templates/sticker/manifest.v1.json';
import {CELL, SHEET, StickerPreview, StickerSheet, type StickerProps} from './templates/sticker/Sticker';
import {FIXTURE_PHOTO, FixturePhoto} from './templates/layer_still/FixturePhoto';
import {LayerStill, PORTS as LAYER_PORTS, layerStillMetadata, type LayerStillProps} from './templates/layer_still/LayerStill';
import seasonalVideoManifest from '../templates/seasonal_video/manifest.json';
import {
  FPS as SEASONAL_VIDEO_FPS,
  SeasonalVideo,
  seasonalVideoMetadata,
  type SeasonalVideoProps,
} from './templates/seasonal_video/SeasonalVideo';

// m-24987158: seasonal WhatsApp stickers. The sheet is the only output port (a PNG grid
// of every frame, transparent); the preview plays it in Studio and is not a port.
const stickerDefaults: StickerProps = {
  meta: {templateId: 'sticker', version: 1, port: 'sheet'},
  brand: {name: 'Polette', palette: ['#5A2A27', '#F4C2C2'], fonts: {heading: 'Poppins'}},
  texts: {motion: 'texto', text: '¡Feliz Navidad!'},
};
// m-25017372: v2 adds the «caption» mode (product character + message). v1 stays
// registered from its kept manifest so a render pinned to it keeps working.
const stickerV2Defaults: StickerProps = {...stickerDefaults, meta: {templateId: 'sticker', version: 2, port: 'sheet'}};

// m-25016848: seasonal short videos (recipe D). Size and length come from the props
// (calculateMetadata): 720 px wide, as tall as the first photo allows, 4–5 s.
const seasonalVideoDefaults: SeasonalVideoProps = {
  meta: {templateId: 'seasonal_video', version: 1, port: 'clip'},
  brand: {name: 'Polette', palette: ['#5A2A27', '#F4C2C2'], fonts: {heading: 'Poppins'}},
  texts: {motion: 'fundido', height: 900},
  photos: [staticFile('sample/photo-1.jpg'), staticFile('sample/photo-2.jpg')],
};

const promoBounds = {
  minSec: promoManifest.duration.min_sec,
  maxSec: promoManifest.duration.max_sec,
};

const promoDefaults: PropsInput = {
  meta: {templateId: 'promo_producto', version: 1, port: 'reel'},
  brand: {
    name: 'Polette',
    palette: ['#F4C2C2', '#5A2A27', '#FFFFFF'],
    fonts: {heading: 'Poppins', body: 'Inter'},
    logo: null,
  },
  texts: {hook: 'El yogurt que se come con cuchara', price_line: '$4', cta: 'Pide el tuyo'},
  photos: [staticFile('sample/photo-1.jpg'), staticFile('sample/photo-2.jpg')],
  video: null,
  products: [],
};

const helloDefaults: PropsInput = {
  meta: {templateId: 'hello_world', version: 1, port: 'reel'},
  brand: {name: 'Qualify', palette: ['#0F766E', '#FFFFFF'], fonts: {heading: 'Poppins', body: 'Inter'}},
  texts: {},
  photos: [],
  video: null,
  products: [],
};

const promoReelMetadata: CalculateMetadataFunction<PropsInput & {bounds: typeof promoBounds}> = ({
  props,
}) => {
  const {bounds: _ignored, ...rest} = props;
  const script = buildScript(normalizeProps(rest), promoBounds);
  return {
    durationInFrames: script.durationInFrames,
    fps: FPS,
    props: {...props, bounds: promoBounds},
  };
};

// m-25017285: `layer_still` v1 — one still per port from a LayerSpec (ADR 49). The checks
// and the fallback chain run in calculateMetadata (LayerStill.tsx).
const layerStillDefaults: LayerStillProps = {
  meta: {templateId: 'layer_still', version: 1, port: 'feed'},
  brand: {name: 'Panadería La Espiga', palette: ['#B5532A', '#FFFFFF', '#FFF4E6'], fonts: {heading: 'Poppins', body: 'Inter'}, logo: null},
  texts: {price_text: '$ 12.000', is_food: true},
  photos: [staticFile('sample/photo-1.jpg')],
  layer: {
    spec_version: 1,
    layout_id: 'plate',
    layout_version: 1,
    format: '4:5',
    photo: {subject_box: [0.2, 0.55, 0.8, 0.95], logo_in_photo: false, base_has_invented_text: false},
    title: 'Tu pan, recién horneado',
    subtitle: 'Masa madre de la casa',
    anchor: 'top_left',
    container_color: 'surface',
    accent_word: 1,
    price_ref: {product_id: '00000000-0000-4000-8000-000000000001'},
  },
};

const layerStillCompositions = (): React.ReactNode[] =>
  Object.entries(LAYER_PORTS).map(([port, spec]) => (
    <Still
      key={spec.composition}
      id={spec.composition}
      component={LayerStill}
      width={spec.width}
      height={spec.height}
      defaultProps={{...layerStillDefaults, meta: {templateId: 'layer_still', version: 1, port}, layer: {...layerStillDefaults.layer, format: spec.format}}}
      calculateMetadata={layerStillMetadata}
    />
  ));

type PromoManifest = typeof promoManifest | typeof promoManifestV1;
type PortSpec = {kind: string; width: number; height: number; composition: string};

/** One <Composition>/<Still> per output port of a promo manifest version. */
const promoCompositions = (manifest: PromoManifest): React.ReactNode[] =>
  Object.entries(manifest.outputs as Record<string, PortSpec>).map(([port, spec]) => {
    const meta = {...promoDefaults.meta!, version: manifest.version, port};
    if (spec.kind === 'video') {
      return (
        <Composition
          key={spec.composition}
          id={spec.composition}
          component={PromoReel}
          width={spec.width}
          height={spec.height}
          fps={FPS}
          durationInFrames={Math.round(promoBounds.minSec * FPS)}
          defaultProps={{...promoDefaults, meta, bounds: promoBounds}}
          calculateMetadata={promoReelMetadata}
        />
      );
    }
    return (
      <Still
        key={spec.composition}
        id={spec.composition}
        component={PromoStill}
        width={spec.width}
        height={spec.height}
        defaultProps={{...promoDefaults, meta}}
      />
    );
  });

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id={helloManifest.outputs.reel.composition}
        component={HelloWorld}
        width={helloManifest.outputs.reel.width}
        height={helloManifest.outputs.reel.height}
        fps={FPS}
        durationInFrames={Math.round(helloManifest.duration.min_sec * FPS)}
        defaultProps={helloDefaults}
      />
      {promoCompositions(promoManifestV1)}
      {promoCompositions(promoManifest)}
      <Still
        id={stickerManifestV1.outputs.sheet.composition}
        component={StickerSheet}
        width={stickerManifestV1.outputs.sheet.width}
        height={stickerManifestV1.outputs.sheet.height}
        defaultProps={stickerDefaults}
      />
      <Still
        id={stickerManifest.outputs.sheet.composition}
        component={StickerSheet}
        width={stickerManifest.outputs.sheet.width}
        height={stickerManifest.outputs.sheet.height}
        defaultProps={stickerV2Defaults}
      />
      <Composition
        id={seasonalVideoManifest.outputs.clip.composition}
        component={SeasonalVideo}
        width={seasonalVideoManifest.outputs.clip.width}
        height={seasonalVideoManifest.outputs.clip.height}
        fps={SEASONAL_VIDEO_FPS}
        durationInFrames={Math.round(seasonalVideoManifest.duration.min_sec * SEASONAL_VIDEO_FPS)}
        defaultProps={seasonalVideoDefaults}
        calculateMetadata={seasonalVideoMetadata}
      />
      {layerStillCompositions()}
      <Still
        id="layer-still-fixture-photo"
        component={FixturePhoto}
        width={FIXTURE_PHOTO.width}
        height={FIXTURE_PHOTO.height}
      />
      <Composition
        id="sticker-v1-preview"
        component={StickerPreview}
        width={CELL}
        height={CELL}
        fps={SHEET.fps}
        durationInFrames={SHEET.frames}
        defaultProps={stickerDefaults}
      />
      <Composition
        id="sticker-v2-preview"
        component={StickerPreview}
        width={CELL}
        height={CELL}
        fps={SHEET.fps}
        durationInFrames={SHEET.frames}
        defaultProps={stickerV2Defaults}
      />
    </>
  );
};
