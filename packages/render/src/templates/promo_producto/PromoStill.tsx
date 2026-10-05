// A representative single frame for the feed (4:5) and story (9:16) ports: the first
// photo, the hook, the price pill and a CTA bar with the logo. Same primitives as the
// reel so the three outputs read as one piece.
import React from 'react';
import {AbsoluteFill} from 'remotion';
import {CoverPhoto, Headline, Logo, PricePill} from '../../components';
import {useBrandFonts} from '../../fonts';
import {normalizeProps, paletteOf, textOf, type PropsInput} from '../../props';

export const PromoStill: React.FC<PropsInput> = (raw) => {
  const props = normalizeProps(raw);
  const palette = paletteOf(props.brand);
  const fonts = useBrandFonts(props.brand.fonts.heading, props.brand.fonts.body);
  const hook = textOf(props, 'hook');
  const priceLine = textOf(props, 'price_line');
  const cta = textOf(props, 'cta');
  const photo = props.photos[0] ?? '';

  return (
    <AbsoluteFill style={{background: '#000'}}>
      <CoverPhoto src={photo} dim={0.4} />
      <AbsoluteFill style={{padding: 80, justifyContent: 'space-between', display: 'flex', flexDirection: 'column'}}>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
          {props.brand.name ? (
            <div
              style={{
                fontFamily: fonts.body,
                fontSize: 34,
                color: 'rgba(255,255,255,0.9)',
                letterSpacing: 6,
                textTransform: 'uppercase',
              }}
            >
              {props.brand.name}
            </div>
          ) : (
            <div />
          )}
          <Logo src={props.brand.logo} size={132} />
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 40}}>
          <Headline text={hook} font={fonts.heading} size={hook.length > 36 ? 84 : 100} />
          <div style={{display: 'flex', alignItems: 'center', gap: 32, flexWrap: 'wrap'}}>
            <PricePill text={priceLine} palette={palette} font={fonts.heading} size={52} />
            {cta ? (
              <div
                style={{
                  fontFamily: fonts.body,
                  fontWeight: 700,
                  fontSize: 44,
                  color: '#FFFFFF',
                  padding: '22px 44px',
                  borderRadius: 999,
                  border: '4px solid rgba(255,255,255,0.9)',
                  whiteSpace: 'nowrap',
                }}
              >
                {cta}
              </div>
            ) : null}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
