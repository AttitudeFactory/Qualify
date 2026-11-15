// A synthetic «food photo» for the local preview of `layer_still` (scripts/layer-preview.mjs):
// no client photo ever goes to git. Deliberately hard for text: a bright, near-white top
// (worst case for the scrim), a busy table and a plate as the subject. Not a template port.
import React from 'react';
import {AbsoluteFill} from 'remotion';

export const FIXTURE_PHOTO = {width: 1200, height: 1500};
/** Where the plate is, as Claude would report it (fractions, rounded to 0.05). */
export const FIXTURE_SUBJECT: [number, number, number, number] = [0.25, 0.4, 0.75, 0.8];

export const FixturePhoto: React.FC = () => (
  <AbsoluteFill style={{background: 'linear-gradient(180deg, #FBF7F0 0%, #F3E3C8 38%, #8A5A35 62%, #5C3A22 100%)'}}>
    {/* window light */}
    <div style={{position: 'absolute', left: 80, top: 60, width: 420, height: 380, background: '#FFFFFF', borderRadius: 24}} />
    <div style={{position: 'absolute', left: 760, top: 120, width: 300, height: 260, background: '#FFFDF8', borderRadius: 24}} />
    {/* table texture */}
    {Array.from({length: 9}).map((_, i) => (
      <div key={i} style={{position: 'absolute', left: 0, right: 0, top: 930 + i * 64, height: 6, background: 'rgba(40,20,8,0.35)'}} />
    ))}
    {/* the plate (subject): x 300–900, y 600–1200 */}
    <div style={{position: 'absolute', left: 300, top: 600, width: 600, height: 600, borderRadius: '50%', background: '#FAFAFA'}} />
    <div style={{position: 'absolute', left: 390, top: 690, width: 420, height: 420, borderRadius: '50%', background: '#D9822B'}} />
    <div style={{position: 'absolute', left: 470, top: 760, width: 140, height: 120, borderRadius: '50%', background: '#4E7A2E'}} />
    <div style={{position: 'absolute', left: 620, top: 880, width: 120, height: 110, borderRadius: '50%', background: '#B3261E'}} />
    {/* a glass on the side */}
    <div style={{position: 'absolute', left: 960, top: 820, width: 140, height: 300, borderRadius: 20, background: 'rgba(255,255,255,0.7)'}} />
  </AbsoluteFill>
);
