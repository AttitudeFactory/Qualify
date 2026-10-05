// Small, typed building blocks shared by the templates. No network, no randomness.
import React from 'react';
import {AbsoluteFill, Img, interpolate} from 'remotion';
import type {Palette} from './props';

/**
 * A photo that fills the frame: the photo itself with object-fit contain (never
 * cropped), over a blurred, darkened cover copy of the same photo that fills whatever
 * the aspect ratio leaves empty. When the aspect matches, contain == cover.
 */
export const CoverPhoto: React.FC<{src: string; scale?: number; dim?: number}> = ({
  src,
  scale = 1,
  dim = 0.25,
}) => {
  if (!src) {
    return <AbsoluteFill style={{background: '#111827'}} />;
  }
  return (
    <AbsoluteFill style={{overflow: 'hidden', background: '#000'}}>
      <Img
        src={src}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          transform: 'scale(1.25)',
          filter: 'blur(40px) brightness(0.7)',
        }}
      />
      <Img
        src={src}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'contain',
          transform: `scale(${scale})`,
        }}
      />
      <AbsoluteFill
        style={{
          background: `linear-gradient(180deg, rgba(0,0,0,${dim}) 0%, rgba(0,0,0,0) 35%, rgba(0,0,0,0) 60%, rgba(0,0,0,${dim + 0.25}) 100%)`,
        }}
      />
    </AbsoluteFill>
  );
};

export const PricePill: React.FC<{
  text: string;
  palette: Palette;
  font: string;
  size?: number;
}> = ({text, palette, font, size = 56}) => {
  if (!text) return null;
  return (
    <div
      style={{
        display: 'inline-block',
        background: palette.accent,
        color: palette.text,
        fontFamily: font,
        fontWeight: 700,
        fontSize: size,
        lineHeight: 1,
        padding: `${size * 0.45}px ${size * 0.9}px`,
        borderRadius: 999,
        boxShadow: '0 12px 40px rgba(0,0,0,0.35)',
        whiteSpace: 'nowrap',
      }}
    >
      {text}
    </div>
  );
};

/** Heading text over a photo: white with a soft shadow so any palette stays legible. */
export const Headline: React.FC<{
  text: string;
  font: string;
  size: number;
  color?: string;
  align?: 'left' | 'center';
  style?: React.CSSProperties;
}> = ({text, font, size, color = '#FFFFFF', align = 'left', style}) => (
  <div
    style={{
      fontFamily: font,
      fontWeight: 700,
      fontSize: size,
      lineHeight: 1.08,
      letterSpacing: -size * 0.02,
      color,
      textAlign: align,
      textShadow: '0 4px 24px rgba(0,0,0,0.45)',
      overflowWrap: 'break-word',
      ...style,
    }}
  >
    {text}
  </div>
);

export const Logo: React.FC<{src: string | null | undefined; size: number}> = ({src, size}) => {
  if (!src) return null;
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.22,
        background: 'rgba(255,255,255,0.92)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        boxShadow: '0 12px 40px rgba(0,0,0,0.25)',
      }}
    >
      <Img src={src} style={{width: '82%', height: '82%', objectFit: 'contain'}} />
    </div>
  );
};

/** 0→1 over `frames`, clamped. */
export const fadeIn = (frame: number, frames: number, delay = 0): number =>
  interpolate(frame - delay, [0, frames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

export const fadeOut = (frame: number, total: number, frames: number): number =>
  interpolate(frame, [total - frames, total], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
