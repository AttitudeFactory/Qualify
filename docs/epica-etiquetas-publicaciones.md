# Épica — Etiquetas (hashtags) que se están viendo

`[FIRMADO 2026-11-13]` · Épica en Meegle: **m-25026375** «Épica — Etiquetas que se están
viendo», con cuatro tickets (§4). En la app el dueño lee «etiquetas» (m-24849133); aquí «etiqueta»
y «hashtag» son lo mismo.

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

**D2 —** Los negocios ya guardados conservan el máximo de 10 etiquetas; no se migra a 5. El máximo de 5 aplica a los
negocios que se guarden desde el PR #642. Mientras no exista una pantalla para elegirlo, cambiar
un negocio actual es un cambio a mano en su política. Decidido por Herwin en chat el 2026-11-13
`[F]`.

## 1. Objetivo

Que las pocas etiquetas que lleva una publicación sean las que la gente del rubro está viendo, sin
que el dueño tenga que investigarlas y sin subir el costo. Qualify sugiere; el dueño aprueba.

## 2. Lo que ya existe en el disco (2026-11-13, `main` en `9a027a46`)

- Al crear la pieza, Claude escribe las etiquetas con las de la marca y su política
  (`packages/creative/src/qualify_creative/brand/render.py`). Desde el PR #642 la política trae
  un máximo de 5 por defecto (`HashtagPolicy.maximum`); una marca que ya guardó su máximo lo
  conserva (D2).
- En el editor: sugerencias al instante del catálogo y del texto (`Qualify/creative_vm.py`,
  `caption_hashtag_suggestions`) y «Sugerir con IA» (`qualify_api/hashtags/caption.py`, Claude
  Haiku, hasta 12 en popular / nicho / marca); «Sugerir con IA» marca las 5 mejores y con más de
  5 el editor avisa en una línea y deja publicar (PR #642). El editor acepta hasta 30
  (`HASHTAG_LIMIT`, lo que admite la API de Meta), también al guardar en el servidor.
- El catálogo compartido (`hashtags`, `hashtag_terms`, migración 0023) aprende de las búsquedas de
  referentes y cuenta cuántas veces vimos cada etiqueta.
- Desde el PR #644, la migración 0162 (`hashtag_post_sightings`) guarda por etiqueta las vistas y
  la fecha de cada publicación pública en que la vimos (búsquedas de referentes y lecturas de
  reels, sin gastar créditos nuevos), con su procedencia y sin ningún dato del negocio.
  `resolve_popular` ordena por vistas de los últimos 90 días sin que una coincidencia más lejana
  pase por delante de una más cercana. Las etiquetas que solo vimos en reels no entran a la cola
  de clasificación pagada.
- Desde el PR #647, el editor usa `resolve_popular`: las sugerencias del catálogo y la lista que
  recibe «Sugerir con IA» van primero con las etiquetas más vistas en los últimos 90 días.
- Entrega 3 (este PR, m-25026378): la lectura semanal en TikTok (`qualify_api/hashtags/weekly.py`,
  migración 0167), apagada hasta encender `QUALIFY_HASHTAG_WEEKLY_READ`. Una etiqueta con una
  respuesta guardada en los últimos 7 días no se vuelve a leer; un negocio se intenta como mucho
  una vez al día; se detiene en el primer error; deja margen al dueño (no lee si el negocio ya
  gastó más de dos tercios de su tope del día o cinco sextos del mes). Tope fijo: un negocio
  nunca gasta más de 5 créditos de esta lectura en 7 días seguidos, cuente lecturas buenas o
  fallidas y aunque cambie sus etiquetas cada día; como mucho 25 en un mes. Si dos negocios
  leen la misma etiqueta a la vez, solo uno paga.
- **Límite conocido, a decidir por el fundador antes de encenderla:** en producción solo se leen
  los negocios que el trabajador de reels considera activos, y eso significa exactamente «una
  marca del negocio abrió la pantalla «Ideas para tus reels» en los últimos 14 días». No
  significa «cliente activo»: un negocio que publica a diario pero nunca abre esa pantalla no se
  lee, y uno que la abrió una vez y se fue se sigue leyendo dos semanas más.
- **Reparto desigual del costo:** cuando dos negocios comparten etiquetas, paga el que se procesa
  primero y el otro no paga nada por esas etiquetas esa semana. Lo que gasta cada negocio en
  esta lectura no refleja cuánto la aprovecha.
- La respuesta cruda se guarda en `vendor_payloads`, que guarda una fila por ruta y parámetros:
  cada semana reemplaza a la anterior de la misma etiqueta y país, y comparte esa fila con la
  memoria de las búsquedas de referentes. Por eso las vistas y fechas solo se pueden reconstruir
  desde la lectura más reciente; las de semanas anteriores quedan en `hashtag_post_sightings`
  pero no se pueden volver a leer.

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

| # | Entrega | Ticket | Qué gana el dueño | Depende de | Estado |
|---|---|---|---|---|---|
| 1 | **Cinco, bien elegidas** | m-25026376 | Una publicación con las cinco etiquetas que más le sirven, no doce | — | Hecha: PR #642 (2026-11-13) |
| 2 | **El catálogo sabe qué se ve** | m-25026377 | «Popular» significa vistas recientes en su rubro, no «lo vimos muchas veces» | — | Hecha: PR #644 (migración 0162) y PR #647 (el editor usa `resolve_popular`), 2026-11-13 |
| 3 | **Lectura semanal en TikTok** | m-25026378 | Etiquetas que acompañan esta semana a los videos más vistos de su rubro | 2 | En revisión: migración 0167, apagada por defecto |
| 4 | **Medir si sirve** | m-25026379 | Saber si el cambio trajo más alcance, con un negocio real | 1, 3 | Pendiente |

## 5. Criterios de aceptación (los que valen son los de cada ticket)

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
