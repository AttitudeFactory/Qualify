# Claude Haiku 4.5 — hashtags de un texto, «Sugerir con IA» (m-25032581)

| Campo | Valor |
|---|---|
| Proveedor | Anthropic (Messages API), llave `QUALIFY_ANTHROPIC_API_KEY` |
| Modelo | `claude-haiku-4-5` (revisión vista: `claude-haiku-4-5-20251001`), sin esfuerzo (Haiku 4.5 no lo acepta), herramienta forzada `sugerir_hashtags`, `max_tokens` 2048 |
| Precio | US$1 / US$5 por millón de tokens de entrada / salida (`claude_tools.PRICES`, tabla `v7`) |
| Uso en Qualify | `qualify_api/hashtags/caption.py` → `suggest_for_caption`: hasta 12 hashtags para el texto de una publicación; el editor marca los 5 primeros como «Mejor». Función del registro de consumo `hashtags-pie`. Versiones del prompt: `caption-hashtags/1` (sin etiquetas vigiladas) y `caption-hashtags/2` (con ellas) |
| Otros usos | Clasificación de hashtags del catálogo (`hashtags.ai`, eval `packages/api/evals/hashtag_ai/`) |
| Datos | El texto de la publicación, los hashtags del catálogo del negocio y, con `/2`, etiquetas públicas de TikTok. Siempre con revisión humana antes de publicar |

## Prueba HASHTAGS-PIE-001 — 2026-11-15/17 · `/2` activado; pasa con la regla de «Mejor», no en el top 5 sin filtrar

- **Quién:** Claude Code (data scientist), a pedido del líder, con la barra acordada antes de correr.
- **Eval:** `packages/api/evals/hashtag_caption/` (README con reglas, adjudicaciones y todos los números).
- **Material:** 34 textos reales del negocio piloto, anonimizados; dev 18 / test 16.
- **Lista vigilada:** armada con el código del producto desde una foto de 25 videos del 2026-11-15.
- **Variantes de `seen`:** catálogo vacío (`none`) y las etiquetas propias del texto (`own`). El catálogo real no se reprodujo. Langfuse no se usó.
- **Detalle completo:** [pruebas.md#hashtags-pie-001](pruebas.md#hashtags-pie-001).

| Top 5 | test `/1` `none` | test `/2` `watched` | test `/1` `own` | test `/2` `own+watched` |
|---|---|---|---|---|
| Otro negocio | 0.004 | 0 | 0 | 0 |
| Vigilada que no encaja | 0.021 | 0.044 (0.037–0.050) | 0.004 | 0.037 (0.025–0.050) |
| Encaja | 0.800 | 0.887 | 0.975 | 0.944 |
| Mal escrita | 0.138 | 0.044 | 0.017 | 0.019 |
| Toma de vigiladas que encajan | 0.013 | 0.408 | 0 | 0.275 |
| USD por llamada | 0.0034 | 0.0041 | 0.0033 | 0.0041 |

**Resultado:**
- `/2` toma 30 veces más etiquetas vigiladas que encajan (pollo, carne, ensalada, árabe).
- Ya no elige nombres de otros negocios. El primer `/2` sí lo hacía: `yaalashawarma` en el top 5 40 de 108 veces en dev.
- Pero en test pone vigiladas de comida en textos que no las nombran: +2,3 y +3,3 puntos sobre la base, contra una barra de +2. Con catálogo, «encaja» baja 3,1 puntos. **No se activa.**

**Hallazgo del prompt de hoy:** sin catálogo, entre las cinco «Mejor» van etiquetas mal escritas: 10–14 % (`sancrystobal`, `enalada`). Además cambian casi por completo de una pulsación a otra (Jaccard ≈0,2). El catálogo es lo que más lo arregla.

**Costo:**
- US$0.0034 por llamada con `/1` y US$0.0041 con `/2`.
- Por negocio y mes (supuesto: 60–160 pulsaciones al mes, `[H]`): US$0.20–0.66.
- Gasto de la prueba: US$1.536 registrados, más ≤ US$0.44 de dos corridas detenidas sin registro.

### Re-medición 2026-11-16/17 (PR #728)

- **Cambios medidos:**
  - una línea más en `WATCHED_ADDENDUM` para que el motivo nombre la palabra del texto;
  - `foodtok` sale de la lista (al modelo llegan 19);
  - la regla de «Mejor»: una vigilada lleva la marca solo si el texto la nombra.
- **Corridas:** 3 repeticiones en dev y test (test ya usado: es una comprobación de regresión).
- **Top 5 sin filtrar: no pasa.** «Vigilada que no encaja» +3,7 a +5,4 puntos; un `manosalsazon` en el top 5 de dev.
- **Cinco «Mejor»: pasa** en dev y test, en las dos variantes:
  - 0 otros negocios y 0 vigiladas que no encajan;
  - «encaja» test 0.892 / 0.967 frente a base 0.800 / 0.975;
  - mal escritas 0.075 / 0.029 frente a base 0.138 / 0.017;
  - toma de vigiladas 0.208 / 0.125 frente a base 0.013 / 0.
- **Motivos que hablan de TikTok, vistas, audiencia o el rubro:** bajan de 8–20 % a 0,6–2,1 %; con inglés, de ≤2,2 % a ≤0,5 %.
- **Queda:** nombres de otros negocios entre las propuestas sin marca (1,5–1,7 % en `own+watched`).
- **Gasto:** US$0.836 en esta re-medición; total registrado US$2.372. Detalle: [pruebas.md#hashtags-pie-001](pruebas.md#hashtags-pie-001).
