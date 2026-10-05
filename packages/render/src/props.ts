// Props contract (CONTRACT.md §2). Every composition receives this shape and reads only
// the ports its manifest declares. Runtime validation with zod so a malformed payload
// fails loudly instead of rendering garbage.
import {z} from 'zod';

export const BrandKitSchema = z
  .object({
    name: z.string().default(''),
    palette: z.array(z.string()).default([]),
    fonts: z
      .object({
        heading: z.string().optional(),
        body: z.string().optional(),
      })
      .default({}),
    logo: z.string().nullable().optional(),
    tone: z.string().optional(),
  })
  .loose();

export const ProductSchema = z
  .object({
    name: z.string(),
    price: z.string().optional(),
    photo: z.string().nullable().optional(),
  })
  .loose();

export const MetaSchema = z
  .object({
    templateId: z.string(),
    version: z.number().int(),
    port: z.string(),
    tenantId: z.string().optional(),
    draftId: z.string().optional(),
    locale: z.string().optional(),
  })
  .loose();

export const TextValue = z.union([z.string(), z.number(), z.boolean(), z.null()]);

export const PropsSchema = z
  .object({
    meta: MetaSchema.optional(),
    brand: BrandKitSchema.prefault({}),
    texts: z.record(z.string(), TextValue).default({}),
    photos: z.array(z.string()).default([]),
    video: z.string().nullable().default(null),
    products: z.array(ProductSchema).default([]),
  })
  .loose();

export type BrandKit = z.infer<typeof BrandKitSchema>;
export type Props = z.infer<typeof PropsSchema>;
/** What the caller may pass before defaults are applied (Remotion's generic parameter). */
export type PropsInput = z.input<typeof PropsSchema>;

export const normalizeProps = (raw: unknown): Props => PropsSchema.parse(raw);

export const textOf = (props: Props, key: string): string => {
  const v = props.texts[key];
  if (v === undefined || v === null) return '';
  return String(v);
};

// Palette convention (CONTRACT §2 + task brief): palette[0] = background accent,
// palette[1] = text on accent surfaces, palette[2] = optional light surface.
export const DEFAULT_ACCENT = '#0F766E';
export const DEFAULT_TEXT = '#FFFFFF';
export const DEFAULT_SURFACE = '#F8FAFC';

export type Palette = {accent: string; text: string; surface: string};

const isColor = (s: unknown): s is string =>
  typeof s === 'string' && /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(s.trim());

export const paletteOf = (brand: BrandKit): Palette => {
  const [a, t, s] = brand.palette;
  return {
    accent: isColor(a) ? a.trim() : DEFAULT_ACCENT,
    text: isColor(t) ? t.trim() : DEFAULT_TEXT,
    surface: isColor(s) ? s.trim() : DEFAULT_SURFACE,
  };
};
