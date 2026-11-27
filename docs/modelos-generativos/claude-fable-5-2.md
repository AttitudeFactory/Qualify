# Claude Fable 5.2: propuestas de sistema visual de marca (spike)

| Campo | Valor |
|---|---|
| Proveedor | Anthropic (Messages API, beta), clave `QUALIFY_ANTHROPIC_API_KEY` (no hay llave de evaluación de Anthropic en el `.env`) |
| Modelo | `claude-fable-5-2`, esfuerzo `high`, razonamiento siempre activo (no se envía `thinking`), streaming, `max_tokens` 64.000, respaldo `server-side-fallback-2026-07-01` con `fallbacks: "default"` |
| Por qué este | Tarea de diseño: el brief pedía el modelo más capaz que permita la llave |
| Precio | US$8 de entrada / US$40 de salida por millón (tabla de la skill `claude-api`, 2026-11-03). **No está en las tablas versionadas** `qualify_creative/pricing_data/` (v7–v9): usarlo en producción pide una tabla nueva con su guardia de precio |
| Uso en Qualify | Ninguno en producción. Solo el spike m-25042530: `packages/api/evals/sistema_visual/propose.py`, prompt `sistema-visual-propose-v1` |
| Datos | Datos de marca de Polette que el dueño ya publica (nombre, rubro, logo, colores y tipografías del brandboard, 3 productos con precio, horario, dirección, medios de pago) y 3 imágenes (logo y dos fotos del brandboard). Ningún dato personal |

## Uso SISVIS-001 (2026-11-17)

Detalle en la bitácora: [SISVIS-001](pruebas.md#sisvis-001).

- 1 corrida, 17.051 tokens de entrada y 40.588 de salida, **US$1,76**, 423 s, `stop_reason` `end_turn`, sin respaldo.
- 3 de 3 propuestas cumplen el esquema `BrandVisualSystem` v0 a la primera.
- Se dibujaron sin tocar el JSON. Juicio y defectos en `docs/spike-sistema-visual-marca.md` §4.

## Uso SISVIS-002 (2026-11-26): propuestas restringidas (esquema v1) para 2 negocios reales con pocos datos

Detalle en la bitácora: [SISVIS-002](pruebas.md#sisvis-002).

- 2 llamadas, prompt `sistema-visual-propose-v1c`, esfuerzo `high`, `max_tokens` 24.000.
- Negocio 1: 5.290 + 13.016 tokens, US$0,563, 136 s. Negocio 2: 4.054 + 10.625 tokens, US$0,457, 103 s.
- 6 de 6 propuestas válidas a la primera.
- Frente a SISVIS-001 (US$1,76, 423 s), cada ronda cuesta un 68–74 % menos y tarda un 68–76 % menos: el modelo ya no escribe geometría.
