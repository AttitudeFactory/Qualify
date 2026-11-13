# Épica — Etiquetas (hashtags) que se están viendo

`[PROPUESTO 2026-11-13]` · Épica en Meegle: **pendiente de crear** (el fundador confirma el
borrador de §5). En la app el dueño lee «etiquetas» (m-24849133); aquí «etiqueta» y «hashtag» son
lo mismo.

## Decisión del fundador (2026-11-13)

**D1 — Opción C: ajustar a cinco y elegir mejor, más una lectura semanal en TikTok.** Herwin la
eligió en chat el 2026-11-13 `[F]`. La recomendación del análisis era la opción B (lo mismo sin la
lectura en TikTok); C la incluye entera y suma la lectura. Manda esta decisión sobre el análisis.

- **Por qué:** con cinco etiquetas por publicación importa cuáles son; la lectura semanal trae las
  que acompañan hoy a los videos más vistos del rubro.
- **Costo:** unos 22 créditos de ScrapeCreators por negocio al mes ≈ USD 0,04 (calculado: 5
  etiquetas × 1 lectura × 4,3 semanas × USD 0,00188), el 4 % del tope de 600 créditos (ADR 42).
- **Riesgo que se asume:** que una etiqueta fuerte en TikTok no sirva en Instagram, que es donde
  publican los clientes `[H]`. Se mide en la entrega 4.
- **Descartado:** dejar como está (A); etiquetas de las tendencias generales (D), porque lo medido
  no tiene relación con ningún rubro.
- **Se reabre si** al 2026-12-15 la prueba con un negocio no muestra más alcance con las etiquetas
  de TikTok, o si la lectura semanal pasa de 60 créditos al mes por negocio.
- **Puerta de dos vías:** todo se apaga con un interruptor; no sale ningún dato de clientes.

## 1. Objetivo

Que las pocas etiquetas que lleva una publicación sean las que la gente del rubro está viendo, sin
que el dueño tenga que investigarlas y sin subir el costo. Qualify sugiere; el dueño aprueba.

## 2. Lo que ya existe en el disco (2026-11-13, `main` en `a4debe59`)

- Al crear la pieza, Claude escribe las etiquetas con las de la marca y su política
  (`packages/creative/src/qualify_creative/brand/render.py`).
- En el editor: sugerencias al instante del catálogo y del texto (`Qualify/creative_vm.py`,
  `caption_hashtag_suggestions`) y «Sugerir con IA» (`qualify_api/hashtags/caption.py`, Claude
  Haiku, hasta 12 en popular / nicho / marca).
- El catálogo compartido (`hashtags`, `hashtag_terms`, migración 0023) aprende de las búsquedas de
  referentes: guarda cuántas veces vimos cada etiqueta, no cuántas vistas tuvo ni cuándo.
- Topes: 30 por publicación en el editor (`HASHTAG_LIMIT`), máximo 10 por defecto en la política
  de marca (`HashtagPolicy`).
- No existe: vistas ni fecha por etiqueta, lectura por etiqueta en TikTok, ni tope de cinco.

## 3. Evidencia

| Dato | Nivel | Fuente |
|---|---|---|
| La API de Meta acepta hasta 30 etiquetas por publicación | `[V]` | Referencia de `IG User Media`, parámetro `caption`: «Maximum 2200 characters, 30 hashtags, and 20 @ tags» (leído 2026-11-13) |
| La app de Instagram limita a 5 desde el 2025-12-18 y su director dice que sirven para búsqueda, no para alcance | `[S]` | Prensa y blogs; no se encontró el anuncio original |
| `tiktok search-hashtag` da 20 videos por lectura con vistas, país, idioma y fecha; con `shawarma` y región CO: 14 de 20 en español, fechas de 2023 a 2026 | `[V]` | `just sc tiktok search-hashtag --hashtag shawarma --region CO --trim` (2026-11-13) |
| `instagram search-hashtag` da 10 publicaciones, mediana de 755 vistas, etiquetas en inglés, sin filtro de país | `[V]` | `just sc instagram search-hashtag --hashtag shawarma --date-posted last-month --media-type reels` |
| Las tendencias generales no tienen relación con un rubro (vallenato, NFL, Nvidia) | `[V]` | `just sc tiktok get-trending-feed --region CO --trim` · `just sc instagram reels-trending` |
| Cada lectura cobra 1 crédito; no hay ruta de «etiquetas en tendencia» | `[V]` | `credits_charged: 1` en las cuatro respuestas; `just sc tiktok --help` |
| Un crédito cuesta USD 0,00188 | `[V]` | `docs/adr-42-ideas-reels-costo.md` |

Las cuatro lecturas costaron 8 créditos (4 se repitieron por un error al guardar la salida).
`--cache-max-age` no existe en estas rutas.

## 4. Las cuatro entregas

| # | Entrega | Qué gana el dueño | Depende de |
|---|---|---|---|
| 1 | **Cinco, bien elegidas** | Una publicación con las cinco etiquetas que más le sirven, no doce | — |
| 2 | **El catálogo sabe qué se ve** | «Popular» significa vistas recientes en su rubro, no «lo vimos muchas veces» | — |
| 3 | **Lectura semanal en TikTok** | Etiquetas que acompañan esta semana a los videos más vistos de su rubro | 2 |
| 4 | **Medir si sirve** | Saber si el cambio trajo más alcance, con un negocio real | 1, 3 |

## 5. Borrador de los tickets

**1 · Generador: cinco etiquetas bien elegidas para Instagram** (Improvement, UI, P2)

- [ ] El generador escribe como máximo 5 etiquetas cuando la política de la marca no dice otra cosa.
- [ ] «Sugerir con IA» marca las 5 mejores y «Agregar todas» agrega solo esas.
- [ ] Con más de 5 el editor avisa en una línea y deja publicar: la API acepta hasta 30.
- [ ] Una marca que ya fijó su máximo lo conserva.

**2 · Etiquetas: el catálogo guarda vistas y fecha de lo que ya leemos** (Improvement, P2)

- [ ] Cada etiqueta vista en una búsqueda de referentes o una lectura de reels guarda las vistas y
      la fecha de la publicación, con la fuente (procedencia) y sin gastar créditos nuevos.
- [ ] «Popular» en «Sugerir con IA» se respalda con vistas de los últimos 90 días.
- [ ] Migración reversible, con RLS si la tabla lleva `tenant_id`.

**3 · Etiquetas: lectura semanal por etiqueta del rubro en TikTok** (Feature, P2)

- [ ] Una vez por semana y por negocio se leen hasta 5 etiquetas de su rubro, por la puerta medida
      (`metered_get`), cargadas a su tope (ADR 42), con una función nueva en `vendor_usage_events`.
- [ ] Una etiqueta leída en los últimos 7 días por cualquier negocio no se vuelve a leer.
- [ ] Solo cuentan videos en español de los últimos 90 días; se guarda la respuesta cruda.
- [ ] Repetir la corrida no duplica filas ni cobra dos veces; el worker corre con `--tenant`.
- [ ] Se apaga con un interruptor; prueba: `just sc tiktok search-hashtag --hashtag <rubro> --region CO --trim`.

**4 · Etiquetas: medir el alcance con un negocio** (Testing, P3)

- [ ] Cuatro semanas con un negocio: alcance de las publicaciones con etiquetas de la entrega 3
      frente a las cuatro semanas anteriores, escrito en este documento.
- [ ] Con el resultado se confirma o se reabre D1 antes del 2026-12-15.

## 6. Fuera de alcance

- Etiquetas de tendencias generales (opción D, descartada).
- Publicar o cambiar etiquetas sin que el dueño apruebe.
- Lecturas por etiqueta en Instagram: lo medido no alcanza.
