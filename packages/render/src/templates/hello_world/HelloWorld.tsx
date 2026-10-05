// Smoke-test template: proves the bundle, Chromium, fonts and the MP4 encoder work.
import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {useBrandFonts} from '../../fonts';
import {normalizeProps, paletteOf, type PropsInput} from '../../props';

export const HelloWorld: React.FC<PropsInput> = (raw) => {
  const props = normalizeProps(raw);
  const palette = paletteOf(props.brand);
  const fonts = useBrandFonts(props.brand.fonts.heading, props.brand.fonts.body);
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 14, stiffness: 120}});
  const sweep = interpolate(frame, [0, durationInFrames], [-20, 20]);
  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(${135 + sweep}deg, ${palette.accent} 0%, #111827 100%)`,
        alignItems: 'center',
        justifyContent: 'center',
        color: palette.text,
      }}
    >
      <div style={{transform: `scale(${enter})`, textAlign: 'center'}}>
        <div style={{fontFamily: fonts.heading, fontWeight: 700, fontSize: 140, lineHeight: 1}}>
          Hola, Qualify
        </div>
        <div style={{fontFamily: fonts.body, fontSize: 48, marginTop: 40, opacity: 0.85}}>
          render service · {props.brand.name || 'hello_world v1'}
        </div>
      </div>
    </AbsoluteFill>
  );
};
