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
    </>
  );
};
