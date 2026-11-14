// Types of spec.mjs (the shared boundary check of `layer_still`).
export declare const SLOTS: readonly ['title', 'subtitle', 'call_phrase'];
export declare const ROLES: readonly ['cover', 'body', 'closing'];
export declare const CONTAINER_COLORS: readonly ['surface', 'accent'];
export declare const IGNORED_KEYS: readonly string[];
export declare const LAYER_KEYS: readonly string[];
export declare const charCount: (s: string) => number;
export declare const wordsOf: (s: unknown) => string[];
export declare const layerProblems: (
  catalog: unknown,
  layer: unknown,
  ctx: {formats: string[]; hasPhoto: boolean; slide?: unknown},
) => string[];
export declare const slideProblems: (slide: unknown, formats: string[]) => string[];
