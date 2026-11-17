// BrandVisualSystem v0 — TypeScript mirror of
// packages/creative/src/qualify_creative/brand_system/model.py (the single source; spike m-25042530).
// The renderer trusts Python to have validated the document; it only guards what would throw.

export type ColorRole =
  | 'background'
  | 'background_alt'
  | 'surface'
  | 'on_surface'
  | 'ink'
  | 'accent'
  | 'on_accent'
  | 'shadow'
  | 'pop';

export type Format = '4:5' | '1:1' | '9:16';
/** A role of the system, or a literal #RRGGBB / #RRGGBBAA. */
export type ColorRef = ColorRole | string;

export type TypeFace = {
  family: string;
  weight: number;
  letter_spacing_em?: number;
  line_height?: number;
  uppercase?: boolean;
  src?: string | null;
};

export type BackgroundLayer = {
  kind: 'rays' | 'rings' | 'dots' | 'stripes' | 'grid' | 'waves' | 'pattern_image' | 'blobs' | 'grain' | 'confetti';
  color?: ColorRef;
  opacity?: number;
  scale?: number;
  angle_deg?: number;
  center?: [number, number];
  image?: string | null;
};

export type Background = {base?: 'solid' | 'radial' | 'linear'; layers?: BackgroundLayer[]};

export type FlagShape = 'pennant' | 'double' | 'arrow' | 'rect';

export type StackItem = {
  type: 'tag' | 'headline' | 'body' | 'price' | 'flag' | 'note' | 'chips';
  slot?: string | null;
  text?: string | null;
  size?: number;
  space_before?: number;
  shape?: FlagShape | null;
  small_em?: number;
  line_height?: number | null;
};

export type VeilStop = {color: ColorRef; alpha: number; at: number};

export type Block = {
  type:
    | 'photo'
    | 'logo'
    | 'product'
    | 'stamp'
    | 'text_stack'
    | 'ticker'
    | 'info_list'
    | 'icon_feature'
    | 'sparkle'
    | 'glow'
    | 'sun';
  box: [number, number, number, number];
  align?: 'left' | 'center' | 'right';
  valign?: 'top' | 'center' | 'bottom';
  rotate_deg?: number;
  z?: number;
  slot?: string | null;
  text?: string | null;
  items?: StackItem[];
  icon?: 'clock' | 'pin' | 'card' | 'chat' | 'bag' | 'star' | 'heart' | null;
  fade?: 'none' | 'bottom' | 'full';
  mirror?: boolean;
  focus?: [number, number];
  zoom?: number | null;
  veil?: VeilStop[];
  saturate?: number;
  contrast?: number;
  framed?: boolean;
  colors?: ColorRef[];
};

export type Recipe = {format: Format; background?: Background | null; blocks: Block[]};

type Fill = {fill?: ColorRef; ink?: ColorRef};

export type Components = {
  body?: {strong_color?: ColorRef; strong_uppercase?: boolean; chip_fill?: ColorRef; chip_ink?: ColorRef};
  tag?: Fill & {variant?: 'tilted_block' | 'pill' | 'outline' | 'underline' | 'plain'};
  headline?: {
    variant?: 'two_tone_stacked' | 'single_color' | 'outline_second' | 'highlight_second';
    split?: 'first_word' | 'last_word' | 'none';
    first_color?: ColorRef;
    second_color?: ColorRef;
    shadow?: boolean;
  };
  price?: Fill & {variant?: 'flag' | 'badge' | 'circle' | 'ticket' | 'plain'; show_code?: boolean};
  stamp?: Fill & {variant?: 'circle_ring' | 'starburst' | 'scallop' | 'none'; ring?: ColorRef};
  ticker?: Fill & {enabled?: boolean; separator?: string};
  product_frame?: {variant?: 'cutout_glow' | 'cutout_sun' | 'disc' | 'arch' | 'rounded' | 'blob'; ring?: ColorRef; glow?: ColorRef};
  info_card?: Fill & {variant?: 'card' | 'chip' | 'outline' | 'plain'};
  logo?: {variant?: 'plain' | 'on_badge'; badge?: ColorRef};
  sparkle?: {enabled?: boolean; glyph?: string; color?: ColorRef};
};

export type BrandVisualSystem = {
  schema_version: 0;
  id: string;
  version: number;
  parent_version?: number | null;
  brand: string;
  name: string;
  style_family: string;
  rationale: string;
  provenance: {source: string; model?: string | null; prompt_version?: string | null; created_at: string};
  colors: Record<ColorRole, string> & {background_edge?: string | null; shadow_deep?: string | null};
  typography: {display: TypeFace; body: TypeFace; label: TypeFace};
  background: Background;
  shapes?: {radius_px?: number; tilt_deg?: number; shadow?: 'hard' | 'soft' | 'none'; shadow_offset_px?: number; stroke_px?: number};
  components?: Components;
  tone: {voice: string; exclamations?: boolean};
  recipes: Record<string, Recipe>;
};

/** Slot data: the owner's own content. Free-form; recipes point into it with dotted paths. */
export type Content = Record<string, unknown>;

export type BrandStillProps = {
  meta?: {templateId?: string; version?: number; port?: string};
  system: BrandVisualSystem;
  recipe: string;
  content: Content;
};
