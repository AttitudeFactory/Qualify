# Claude Opus 5.5: el copy del generador (piezas, clips y videos por partes)

| Campo | Valor |
|---|---|
| Proveedor | Anthropic (Messages API), clave `QUALIFY_ANTHROPIC_API_KEY` |
| Modelo | `claude-opus-5-5`, esfuerzo `medium`, razonamiento adaptativo, salida con esquema JSON (`CopyPayload`), `max_tokens` 16.000. Lo fijan `DEFAULT_MODEL_ID` y `DEFAULT_EFFORT` en `packages/creative/src/qualify_creative/adapters/anthropic_copy.py` |
| Respaldo | Si el modelo rechaza la petición, la beta `server-side-fallback-2026-07-01` (`fallbacks: "default"`) la repite en `claude-opus-5` o `claude-opus-4-8`; se cobra el modelo que respondió (`_served_model`) |
| Precio | US$4 de entrada / US$20 de salida por millón; escritura de caché (5 min) US$5, lectura US$0,20. Tablas versionadas `v8` (la que usa `composition.PRICING_VERSION`) y `v9`, con las mismas cifras. Coincide con `claude_tools.PRICES` y con la página de precios leída el 2026-11-13. El respaldo `claude-opus-4-8` cuesta US$5 / US$25 |
| Uso en Qualify | `AnthropicCopyAdapter()` en `qualify_api.creative.composition` (proveedor `anthropic`): gancho, texto, CTA, etiquetas y, en los videos, el guion o las tomas de cada pieza. Prompt `brand.render.render_prompt`: un prefijo estable en caché (kit, voz, ventajas del negocio) y un sufijo con el encargo (nivel de consciencia incluido) |
| Datos | El kit de marca, la voz, las ventajas que escribió el dueño y el brief de la pieza. Cada pieza la aprueba el dueño antes de publicarla |

## Uso COPY-EVAL (2026-10-13 y 2026-11-04): por qué Opus 5.5 @ medium

Detalle en `packages/api/evals/copy_ai/README.md` (`just eval-copy`, 27 briefs de tres marcas ficticias).

- 2026-10-13: puertas 1,000 frente a 0,979 de Opus 5.5 @ low y 0,958 de Sonnet 5.5 @ medium. US$0,0632 por pieza.
- Con los largos asegurados por código, Sonnet 5.5 queda como candidato más barato.
- 2026-11-04 (VE-06): sin regresión, puertas 1,000. US$0,047–0,049 por pieza.

## Uso NIVELES-001…006: niveles de consciencia y ventajas del negocio (m-25026482, m-25026509, m-25027151), 2026-11-13/14

El copy de estas pasadas lo escribió siempre este modelo, con los ajustes de producción: 1 variante por caso, juez Haiku 5.5. Detalle en la bitácora.

- **[NIVELES-001](pruebas.md#niveles-001)** (piezas, 7 ángulos × 3 corridas, n 21 por brazo):
  - puertas 21/21 en los dos brazos;
  - el precio en unaware pasa de 6/6 a 0/6, pero unaware cumple 0/6 porque se cuelan ventajas de fricción;
  - US$0,0135 → US$0,0152 por pieza.
- **[NIVELES-002](pruebas.md#niveles-002):** unaware de comida pasa de 0/3 a 4/5; ofertas inventadas de 5/21 a 0/17. El unaware de inmobiliaria quedó sin medir (un `APITimeoutError`).
- **[NIVELES-003](pruebas.md#niveles-003)** (n 35):
  - unaware 6/6, sin horarios;
  - solution_aware 9/9, product_aware 9/9;
  - most_aware 3/8 por largo;
  - ofertas 3/35, por «separación» en inmobiliaria.
- **[NIVELES-004](pruebas.md#niveles-004)** (copy de clip con «¿A quién le habla este video?», n 48):
  - el precio en unaware queda en 0/6 aunque el brief lo traía, y 0/6 en los casos con el precio en la frase del dueño;
  - most_aware 0/12, product_aware 12/12;
  - tomas filmables 144/144, puertas 48/48;
  - US$0,024 por clip.
- **[NIVELES-005](pruebas.md#niveles-005)** (medidas de most_aware):
  - clip most_aware 3/11 con la medida cumplida 12/12;
  - pieza most_aware 5/8;
  - clip solution_aware 7/7, product_aware 13/15, unaware 6/9;
  - ninguna copia rechazada por corta.
- **[NIVELES-006](pruebas.md#niveles-006)** (texto de most_aware: producto, precio y cómo comprar, con cuándo y dónde):
  - **clips 20/21 y piezas 20/20**, cumple la barra de 0,80;
  - casos con «Debe mencionar» y la forma de pedir como ventaja: 11/12;
  - puertas 41/41, ninguna rechazada por corta.
- **Gasto en Claude de las seis pasadas:** US$8,85 (1,83 + 1,03 + 1,60 + 1,65 + 1,33 + 1,41), con copy, ángulos, partes y juez juntos; el desglose está en cada entrada.
