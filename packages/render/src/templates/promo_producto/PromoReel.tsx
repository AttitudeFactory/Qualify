import React from 'react';
import {
  AbsoluteFill,
  Easing,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {CoverPhoto, Headline, Logo, PricePill, fadeIn, fadeOut} from '../../components';
import {useBrandFonts} from '../../fonts';
import {normalizeProps, paletteOf, textOf, type PropsInput} from '../../props';
import {CROSSFADE_FRAMES, type DurationBounds, type Scene, buildScript} from './script';

type HookSceneProps = {
  photo: string;
  hook: string;
  brandName: string;
  fonts: {heading: string; body: string};
  durationInFrames: number;
};

/** Room kept free at the bottom for Instagram's own interface. A 9:16 video sits under
 * the Reels caption and buttons; a 4:5 or 1:1 one is shown in the feed with nothing on
 * top of it. The 9:16 values are v1's, so a Reel renders exactly as it always did. */
const safeBottom = (height: number, vertical: number, feed: number): number =>
  height >= 1800 ? vertical : feed;

const HookScene: React.FC<HookSceneProps> = ({photo, hook, brandName, fonts, durationInFrames}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 200, stiffness: 120}});
  const y = interpolate(enter, [0, 1], [80, 0]);
  const opacity = fadeIn(frame, 10) * fadeOut(frame, durationInFrames, CROSSFADE_FRAMES);
  return (
    <AbsoluteFill style={{opacity}}>
      <CoverPhoto src={photo} dim={0.45} />
      <AbsoluteFill
        style={{justifyContent: 'flex-end', padding: `0 88px ${safeBottom(height, 300, 120)}px 88px`}}
      >
        <div style={{transform: `translateY(${y}px)`, opacity: enter}}>
          {brandName ? (
            <div
              style={{
                fontFamily: fonts.body,
                fontSize: 38,
                color: 'rgba(255,255,255,0.85)',
                letterSpacing: 6,
                textTransform: 'uppercase',
                marginBottom: 28,
              }}
            >
              {brandName}
            </div>
          ) : null}
          <Headline text={hook} font={fonts.heading} size={hook.length > 36 ? 92 : 108} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

type PhotoSceneProps = {
  photo: string;
  index: number;
  priceLine: string;
  palette: ReturnType<typeof paletteOf>;
  fonts: {heading: string; body: string};
  durationInFrames: number;
};

const PhotoScene: React.FC<PhotoSceneProps> = ({
  photo,
  index,
  priceLine,
  palette,
  fonts,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  // Gentle Ken Burns, alternating direction per photo so consecutive scenes differ.
  const zoomFrom = index % 2 === 0 ? 1.0 : 1.08;
  const zoomTo = index % 2 === 0 ? 1.08 : 1.0;
  const scale = interpolate(frame, [0, durationInFrames], [zoomFrom, zoomTo], {
    easing: Easing.inOut(Easing.quad),
    extrapolateRight: 'clamp',
  });
  const opacity = fadeIn(frame, CROSSFADE_FRAMES) * fadeOut(frame, durationInFrames, CROSSFADE_FRAMES);
  const pillIn = spring({frame: frame - 6, fps, config: {damping: 14, stiffness: 160}});
  return (
    <AbsoluteFill style={{opacity}}>
      <CoverPhoto src={photo} scale={scale} dim={0.15} />
      {priceLine ? (
        <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'flex-start', padding: 88}}>
          <div style={{transform: `scale(${pillIn}) translateY(${(1 - pillIn) * 40}px)`, marginBottom: safeBottom(height, 200, 40)}}>
            <PricePill text={priceLine} palette={palette} font={fonts.heading} size={64} />
          </div>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

type CtaSceneProps = {
  cta: string;
  brandName: string;
  logo: string | null | undefined;
  priceLine: string;
  palette: ReturnType<typeof paletteOf>;
  fonts: {heading: string; body: string};
};

const CtaScene: React.FC<CtaSceneProps> = ({cta, brandName, logo, priceLine, palette, fonts}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 200, stiffness: 100}});
  const pop = spring({frame: frame - 8, fps, config: {damping: 12, stiffness: 180}});
  return (
    <AbsoluteFill style={{background: palette.accent, opacity: fadeIn(frame, CROSSFADE_FRAMES)}}>
      <AbsoluteFill
        style={{alignItems: 'center', justifyContent: 'center', padding: 96, gap: 56, display: 'flex', flexDirection: 'column'}}
      >
        <div style={{transform: `scale(${pop})`}}>
          <Logo src={logo} size={240} />
        </div>
        {brandName ? (
          <div
            style={{
              fontFamily: fonts.body,
              fontSize: 40,
              color: palette.text,
              opacity: 0.8 * enter,
              letterSpacing: 6,
              textTransform: 'uppercase',
            }}
          >
            {brandName}
          </div>
        ) : null}
        <div style={{transform: `translateY(${(1 - enter) * 60}px)`, opacity: enter}}>
          <Headline
            text={cta}
            font={fonts.heading}
            size={cta.length > 24 ? 96 : 120}
            color={palette.text}
            align="center"
            style={{textShadow: 'none'}}
          />
        </div>
        {priceLine ? (
          <div style={{opacity: enter, marginTop: 24}}>
            <div
              style={{
                fontFamily: fonts.heading,
                fontWeight: 700,
                fontSize: 64,
                color: palette.accent,
                background: palette.text,
                padding: '28px 56px',
                borderRadius: 999,
              }}
            >
              {priceLine}
            </div>
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const PromoReel: React.FC<PropsInput & {bounds: DurationBounds}> = (raw) => {
  const {bounds, ...rest} = raw;
  const props = normalizeProps(rest);
  const palette = paletteOf(props.brand);
  const fonts = useBrandFonts(props.brand.fonts.heading, props.brand.fonts.body);
  const script = buildScript(props, bounds);
  const hook = textOf(props, 'hook');
  const priceLine = textOf(props, 'price_line');
  const cta = textOf(props, 'cta');

  const render = (scene: Scene): React.ReactNode => {
    switch (scene.kind) {
      case 'hook':
        return (
          <HookScene
            photo={scene.photo}
            hook={hook}
            brandName={props.brand.name}
            fonts={fonts}
            durationInFrames={scene.durationInFrames}
          />
        );
      case 'photo':
        return (
          <PhotoScene
            photo={scene.photo}
            index={scene.index}
            priceLine={priceLine}
            palette={palette}
            fonts={fonts}
            durationInFrames={scene.durationInFrames}
          />
        );
      case 'cta':
        return (
          <CtaScene
            cta={cta}
            brandName={props.brand.name}
            logo={props.brand.logo}
            priceLine={priceLine}
            palette={palette}
            fonts={fonts}
          />
        );
    }
  };

  return (
    <AbsoluteFill style={{background: '#000'}}>
      {script.scenes.map((scene, i) => (
        <Sequence
          key={i}
          from={scene.from}
          durationInFrames={scene.durationInFrames}
          name={scene.kind}
        >
          {render(scene)}
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
