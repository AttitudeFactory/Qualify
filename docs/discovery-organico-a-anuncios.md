# Discovery — detectar publicaciones orgánicas con potencial para anuncio

`[DISCOVERY 2026-11-16 · m-24841227 · sin código de producto · recomendación: ESPERAR]`

**Pregunta.** ¿Vale la pena construir «Qualify te avisa qué publicación promocionar», y cómo?
**Respuesta corta.** Se puede hacer **sin pedir permisos nuevos** para una primera versión, pero
hoy **no hay ni un dato propio** que pruebe H1–H3 y el camino de salida (promocionar, ADS-06)
**todavía no se ha probado con Meta real** (m-24828971 sin correr). Recomendación: **esperar**,
con una evaluación retrospectiva de solo lectura como primer paso (§6, §8).

Reglas de evidencia: `[V]` comprobado en código, en la documentación oficial (ruta o URL con
fecha) o en un dato propio; `[H]` hipótesis; **«por confirmar»** = depende de la prueba en vivo
m-24828971 o de una lectura en producción que este discovery no hizo (no tuvo acceso a
producción y no ejecutó ninguna llamada a Meta).

---

## 0. Qué cambió desde el ticket (2026-10-22 → 2026-11-16)

| El ticket decía | Hoy (medido en `main` 9a1ca81b) |
|---|---|
| «Cero llamadas a `/insights`» | Sigue cierto para **publicaciones orgánicas**. La única llamada a `/insights` es la de resultados de **anuncios** (`ads/client.py:559`, ADS-09 m-24828979) `[V]` |
| `instagram_manage_insights` no se pide | Sigue sin pedirse: no está en `QUALIFY_META_SCOPES` del `.env` local ni en `ads_requested_scopes` (`config.py:58-63`). La matriz C-05 ya lo conoce (`Capability.READ_INSIGHTS`, `permission_capability.py:349`) y la UI ya tiene la etiqueta «Ver tus resultados» (`Qualify/capabilities.py:65`) `[V]` |
| No hay cuentas publicitarias ni consentimiento | **Ya existen**: cuentas publicitarias, «Promocionar» una publicación (ADS-06), público, objetivo chat, historia, pieza sin publicar, resultados y pausa (`packages/api/src/qualify_api/ads/`, `Qualify/promotion_*`). Todo se crea en `PAUSED` y la activación exige confirmación (`ads/promotions.py`, `wizard_workflow.py`) `[V]` |
| ADS-06 asume que el cliente elige a mano | Sigue así: el botón «Promocionar» está en la tarjeta de la pieza (`Qualify/post_card.py`), en el panel del Planificador (`planner_drawer.py`) y en Crear pieza (`creative_pages.py`) `[V]` |
| Elegibilidad con `boost_eligibility_info` | **No se lee en ningún sitio** (grep `boost_eligibility`, `boost_ads_list` = 0 en código). La comprobación previa real verifica dueño + `media_type ∈ {IMAGE, VIDEO}` + no historia (`ads/live_wizard.py:176-191`) y luego una validación `validate_only` exacta `[V]` |
| Reutilizar m-24789474 | m-24789474 quedó **absorbido por m-24946127** (`docs/epica-creadores.md` §7): fórmula `cm-1` con «destacado = vistas ≥ 2 × mediana propia», madurez 3 días, mínimo 3 reels (`creators/metrics.py`, `referentes/reels.py:356 LIFT_HIGHLIGHT = 2.0`) `[V]` |
| Reutilizar m-24820834 | m-24820834 quedó **reemplazado** por VE-04c + VE-02 (`docs/diseno-video-por-planos.md:250`, `docs/epica-video-por-partes.md:157`); no hay análisis de calidad creativa en marcha `[V]` |
| m-24789540 / m-24789470 (métricas de medios propios) | **Sin rastro** en código, docs ni commits de `main` → no construidos `[V]` |

> **Deriva detectada (no corregida aquí):** `docs/epica-anuncios-meta.md` §3 todavía dice
> «`ads_management`… ❌ no pedidos», pero el código ya los pide en el flujo de anuncios
> (`ads_requested_scopes`, `connections/meta_oauth.py:212-214`). Corregirlo en el próximo PR de
> la épica.

---

## 1. Detección — qué es «con potencial»

**Señales posibles y si sirven hoy:**

| Señal | ¿Sirve? | Por qué |
|---|---|---|
| (a) Rendimiento relativo a la propia cuenta | **Sí, es la base** | Se calcula con contadores por publicación (§2) contra la mediana de la propia cuenta, igual que `cm-1` |
| (b) Calidad creativa (m-24820834 / hooks de `packages/models`) | **No en la v0** | m-24820834 se reemplazó; los hooks son un spike sin datos (`NOTES_hook_pattern_spike.md`). Añadir calidad sin medir rendimiento sería opinión, no dato |
| (c) Ventana temporal | **Sí** | Meta retrasa datos hasta 48 h (`…/instagram-media/insights.md`, «Limitations»); `cm-1` y `growth/organic.py` ya usan 72 h / 3 días como madurez |

### Definición propuesta (medible) — `po-0` `[H]`, a calibrar con §6

Una publicación propia, **publicada desde Qualify** (`publish_attempts.status='published'`), es
**«con potencial»** si cumple todo:

| # | Regla | Valor v0 | Origen del número |
|---|---|---|---|
| 1 | Madurez: lectura entre **72 h y 7 días** desde la publicación | 72 h – 7 d | 72 h = `MATURITY_DAYS=3` de `cm-1` + retraso de 48 h de Meta; 7 d = sigue siendo «actual» para anunciarla |
| 2 | Línea base: mediana de la misma cuenta y **mismo tipo** (reel con reel, foto con foto) sobre sus **últimas 12** publicaciones maduras de ≤ 90 días | 12, 90 d | `COMPARE_REELS = 12` de `cm-1` |
| 3 | **Mínimo de publicaciones** para afirmar algo | **≥ 8** maduras del mismo tipo; si no, «sin datos suficientes», nunca un cero (ruling R10) | `[H]`: más exigente que `MIN_SAMPLE = 3` de `cm-1` porque aquí la consecuencia es gastar dinero |
| 4 | **Alcance relativo** ≥ **2 ×** la mediana | 2,0 | `LIFT_HIGHLIGHT = 2.0`, el mismo umbral de «destacado» de m-24946127 |
| 5 | **Interacción relativa** ≥ mediana de la cuenta ((me gusta + comentarios + guardados + compartidos) ÷ vistas) | ≥ 1,0 × | Descarta lo que tuvo vistas pero no gustó (patrón «empujado» de `growth/organic.py`) |
| 6 | **Nunca promocionada**: ninguna promoción en Qualify con ese `source_media_id`, **en cualquier estado** (también pausada o terminada), y `boost_ads_list` vacío | — | `total_views_count` y `total_like_count` incluyen lo pagado (§2): sin este filtro un anuncio parecería «orgánico con potencial». **Límite:** `boost_ads_list` solo lista anuncios `ACTIVE`, así que una promoción hecha **fuera de Qualify** y ya terminada no se detecta y puede inflar la cifra |
| 7 | **Elegible**: la comprobación de ADS-06 pasaría (dueño, `IMAGE`/`VIDEO`, no historia) **y** `boost_eligibility_info` no la descarta | — | `live_wizard.py:176-191`; `boost_eligibility_info` por confirmar (§4) |
| 8 | Ritmo: como mucho **1 aviso por marca por semana**; el rechazo silencia esa publicación | 1/sem | `[H]`, para no convertir el aviso en ruido |

Métrica de alcance: **v0** = `total_views_count` (reels y videos; el único campo de vistas para medios propios — `view_count` es solo de Business Discovery, §2) o `like_count + comments_count` (fotos, solo orgánicos);
**v1** = `reach` de `/insights` (necesita `instagram_manage_insights`, §2). Cambiar un umbral o
una ventana = nueva versión (`po-1`…), como `CREATOR_METRICS_VERSION`.

**Qué depende de otros tickets:** la fórmula y sus constantes vienen de **m-24946127** (antes
m-24789474); la señal de calidad creativa (m-24820834 → VE-04c/VE-02) **no entra** hasta que
exista y se mida; la regla «sin métricas no hay afirmación basada en datos» (m-24789540) se
cumple con la regla 3.

---

## 2. Datos y permisos

**Qué pide la app hoy** (`[V]`, código):
- Flujo normal: los scopes salen de `QUALIFY_META_SCOPES` (env, nunca en código —
  `config.py:49-51`; `.env.example` lo deja vacío). En el `.env` **sin versionar** de la máquina
  de desarrollo (leído el 2026-11-16): `instagram_basic`,
  `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`,
  `instagram_manage_comments`, `instagram_manage_messages`, `pages_messaging`.
  **No incluye `instagram_manage_insights`.**
- Flujo de anuncios: añade `ads_management`, `ads_read`, `pages_manage_ads`,
  `business_management` (`config.py:58-63`, `meta_oauth.py:212-214`).
- Si producción usa `QUALIFY_META_CONFIG_ID`, **la configuración de Facebook Login for Business
  decide qué se pide**, no el parámetro `scope` (`meta_oauth.py:217-219`). El valor de producción no está en el repo →
  **por confirmar** con `GET /me/permissions` de una conexión de producción.

**Métricas por publicación** (documentación oficial; `[V]` doc = corpus
`reference/meta-instagram-platform/documentation/instagram-platform/reference/instagram-media.md`
y `…/instagram-media/insights.md`, cosechados el 2026-07-24; campos y permisos del nodo
re-leídos en https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/
el 2026-11-16):

| Métrica | Dónde | Tipo | Permiso que exige (Facebook Login) | ¿La app lo puede pedir hoy? |
|---|---|---|---|---|
| `like_count` | campo del nodo media | foto, reel | `instagram_basic` + `pages_read_engagement` (+ `ads_read` o `ads_management` si el rol viene por Business Manager) | **Sí**, ya pedidos (dev). Prod por confirmar |
| `comments_count` | campo | foto, reel | igual | **Sí** |
| `total_views_count` | campo | **solo video** (reel) | igual — **incluye vistas pagadas y repeticiones**; no hay campo de vistas solo orgánicas en el nodo | **Sí** según la doc; por confirmar en vivo |
| `total_like_count`, `total_comments_count` | campo | foto, reel | igual — incluyen lo pagado | **Sí** según la doc; por confirmar en vivo |
| `view_count` | campo | reel | **«Available for Business Discovery API only»**: sirve para cuentas ajenas, **no** para los medios propios | No aplica |
| `saved_count` | campo («solo el dueño o colaborador») | foto, reel | igual | **Sí** según la doc; **por confirmar en vivo** (ADR 25) |
| `shares_count`, `reposts_count` | campo | foto, reel | igual | **Sí** según la doc; por confirmar en vivo |
| `boost_eligibility_info`, `boost_ads_list` | campo | foto, reel | igual (no lista permiso propio) | **Sí** según la doc; forma de la respuesta **por confirmar** (m-24828971) |
| `copyright_check_information` | campo | video | igual | **Sí** según la doc; útil para H3 |
| `reach` | `/insights` | foto, reel, historia | `instagram_basic` + **`instagram_manage_insights`** + `pages_read_engagement` (+ `ads_*` si rol por BM) | **No**: no se pide hoy |
| `views`, `saved`, `shares`, `total_interactions`, `likes`, `comments` (solo orgánico) | `/insights` | foto, reel | igual que `reach` | **No** |
| `ig_reels_avg_watch_time`, `reels_skip_rate` | `/insights` | reel | igual | **No** |
| `profile_visits`, `follows`, `profile_activity` | `/insights` | foto, historia | igual | **No** |

Límites documentados que cambian el diseño: datos con hasta **48 h** de retraso; se guardan
**2 años**; **ningún dato para hijos de carrusel**; métricas de historia solo **24 h**; un dato
inexistente vuelve **vacío, no 0** (`…/instagram-media/insights.md`, «Limitations»).

**Qué hace falta para la v1 (`reach`):** añadir `instagram_manage_insights` a la configuración
de Facebook Login y a `QUALIFY_META_SCOPES`, que cada cliente **vuelva a conectar**, y App
Review de ese permiso para clientes sin rol en la app (con ADR 29 los negocios que administra el
fundador funcionan con acceso estándar). Es decisión del fundador; **este ticket no cambia
scopes**.

**Coste** `[H]` calculado: 2 lecturas por publicación (72 h y 7 d), ~30 publicaciones/mes por
marca → ~60 GET/marca/mes, **USD 0** (Graph API sin coste por llamada) y ~720 filas/año/marca
— despreciable para ADR 31. Va en un worker, no en la petición.

---

## 3. Recomendación al cliente

**Dónde** (nombres reales del menú: «Por aprobar», «Tu semana», «Anuncios»):

| Boceto | Lugar | Veredicto |
|---|---|---|
| **A** | **Una tarjeta arriba de «Tu semana»** que enlaza a la publicación | **Principal**: es lo que el dueño abre; con el aviso solo en la tarjeta de la publicación, la ventana de 72 h–7 días vencería sin que lo vea |
| A′ | Etiqueta en la tarjeta de la publicación (`post_card.py`) y en su panel de «Tu semana» (`planner_drawer.py`) | **Secundario**. En esa tarjeta el botón del aviso **reemplaza** a «Promocionar»: una sola acción principal |
| B | «Anuncios», una sola vez, solo para «sin datos suficientes» | Complemento |
| C | Interacciones | **Descartado**: esa pantalla es para responder a personas; mezclar dinero confunde |

```
Tu semana
┌──────────────────────────────────────────────┐
│ [miniatura]  Tu publicación del martes      › │
│ ★ Le está yendo muy bien                      │
│ En 4 días se vio el triple de lo que suele    │
│ ver una publicación tuya.                     │
│ Si la promocionas, la verán más personas de   │
│ tu zona. Tú decides cuánto gastar.            │
│ Nada se gasta hasta que tú lo confirmes.      │
│ [ Ver cómo promocionarla ]   [ No, gracias ]  │
└──────────────────────────────────────────────┘
  lunes · martes · miércoles … (la semana de hoy)
```

**Textos exactos** (revisados con `qualify-copy-es`: español llano, «publicación», «anuncio»,
sin anglicismos, cifras propias en palabras, sin decimales):

| Momento | Texto |
|---|---|
| Etiqueta | «Le está yendo muy bien» |
| Aviso (reel) | «En {días} días se vio {el doble \| el triple \| {n} veces} de lo que suele ver una publicación tuya.» |
| Aviso (foto) | «En {días} días recibió {el doble \| el triple \| {n} veces} los me gusta y comentarios que suele recibir una publicación tuya.» |
| Beneficio, sin promesas | «Si la promocionas, la verán más personas. Tú decides cuánto gastar.» (+ «desde {mínimo}» cuando ADS-00 confirme el mínimo en COP) |
| Garantía (siempre visible) | «Nada se gasta hasta que tú lo confirmes.» |
| Aceptar (botón) | «Ver cómo promocionarla» |
| Rechazar (botón) | «No, gracias» |
| Tras rechazar | «Listo, no te la volveremos a sugerir. Si cambias de idea, tócala y elige Promocionar.» Tras rechazar, la tarjeta vuelve a mostrar «Promocionar». |
| Sin datos suficientes (una vez, en «Anuncios») | «Cuando tengas {faltan} publicaciones más, te diremos cuál le está yendo mejor para promocionarla.» |

`{días}` = días reales desde la publicación (3 a 7). `{n}` se redondea hacia abajo a entero:
2 → «el doble», 3 → «el triple», 4 o más → «{n} veces».

**Qué pasa al aceptar:** abre el asistente que ya existe (`/drafts/{id}/promote`, ADS-06), con
«‹ Tu semana» para volver (`?desde=semana` en el enlace, vía `promotion_link` de `Qualify/promotion_entry.py`; lo fija `Qualify/promotion_state.py:1742-1743`, y sin ese parámetro vuelve a «Por aprobar»). Se
prepara **en pausa**; el cliente revisa presupuesto, fechas y público; **solo su confirmación
explícita** pide la activación. El aviso **no** prepara nada por su cuenta.

> **Regla, sin excepción:** toda acción publicitaria exige **consentimiento explícito del
> cliente** y **confirmación explícita antes de activar** (ADR 38 «Consecuencias», `docs/adr-38-anuncios-meta.md:39`, y ADS-16; condición de las
> Self-Serve Ad Terms de Meta). **Este discovery no aprueba ninguna automatización**: ni crear,
> ni preparar, ni activar «con un clic» sin la revisión del asistente.

---

## 4. Viabilidad con Meta (anuncios)

| Pregunta | Estado | Evidencia |
|---|---|---|
| ¿Existe un campo de elegibilidad por publicación? | **Sí, documentado** | `boost_eligibility_info` (`instagram-media.md:80`; re-leído en la URL oficial el 2026-11-16) |
| ¿Qué subcampos y motivos devuelve? | **Por confirmar** | La doc no los lista; ADS-00 m-24828971 debe leerlo en una publicación normal y en una con música con derechos |
| ¿Se sabe si ya está promocionada? | **Sí, documentado** | `boost_ads_list` (solo anuncios `ACTIVE`, `instagram-media.md:79`); más las promociones propias en BD |
| ¿Qué tipos acepta Qualify hoy? | **Foto y video publicados; no historia; no carrusel** | `live_wizard.py:187-190` |
| ¿Una publicación hecha por Qualify se puede promocionar (error 1885183)? | **Por confirmar** | App en Live desde 2026-10-21 (`epica-anuncios-meta.md` §3); ADS-00 sin correr (`docs/anuncios-mvp-validacion.md`: «No se han realizado las operaciones reales») |
| ¿Qué objetivos aceptan `LEARN_MORE` sobre una publicación existente? | **Por confirmar** | ADS-00 |
| Presupuesto mínimo en COP | **Por confirmar** | ADS-00 (`act_<id>/minimum_budgets`) |
| ¿Acceso para clientes que no administra el fundador? | **Bloqueado** | Acceso avanzado a `ads_management` + App Review (ADS-15; tablero de Meta del 2026-11-08: Marketing API 0/500 llamadas) |

---

## 5. Validación y medida

| Qué mide | Cómo | Umbral para seguir `[H]` |
|---|---|---|
| H1 — concentración | Retrospectiva §6 | En ≥ 2 cuentas con ≥ 20 publicaciones maduras: el 10 % superior concentra ≥ 40 % de las vistas, y ≥ 1 candidata `po-0` por mes por cuenta |
| H2 — aceptación (señal, no prueba) | % de avisos con «Ver cómo promocionarla» → % que confirman la activación, guardando **quién** tocó (dueño o equipo operador) | ≥ 20 % abren, ≥ 5 % activan, en 8 semanas con ≥ 5 marcas — es una señal para OA-7, **no confirma H2** (abajo) |
| H3 — elegibilidad | % de candidatas `po-0` descartadas por `boost_eligibility_info` o por tipo | Si > 50 %, la regla 7 va primero (no avisar de lo que no se puede promocionar) |
| Acierto | Resultados del anuncio (ADS-09, m-24828979: coste por resultado) de recomendadas vs promocionadas a mano | Coste por resultado de las recomendadas ≤ el de las elegidas a mano |

**H2 completa:** *el dueño de un negocio pequeño acepta promocionar una publicación con más
frecuencia cuando el aviso le muestra una comparación con sus propias publicaciones («se vio el
triple de lo que suele ver una publicación tuya») que cuando le da una recomendación genérica
(«esta publicación podría funcionar como anuncio»).* La medición de arriba **no puede
confirmarla**: no tiene grupo de control (todos ven la versión con cifras), la muestra es mínima
(≥ 5 marcas) y hoy quien toca suele ser el **equipo operador**, no el dueño.

**Prueba de concepto cualitativa** (barata, antes de construir OA-4): dentro de las entrevistas
de `docs/perfil-cliente-pyme.md` §5, mostrar las dos versiones del aviso en papel o captura,
anotar sus palabras textuales y cuál elegiría. Preguntas propuestas para esa §5 (no se edita el
perfil en este ticket):
- «¿Vuelve a mirar sus publicaciones después de publicarlas? ¿Dónde?»
- «Si Qualify te dice "esta publicación se vio el triple de lo normal", ¿la promocionarías? ¿Qué
  más necesitas saber?»

Cada aviso guarda procedencia: id de la publicación, versión de la fórmula (`po-0`), valores
usados y fecha de lectura; y una clave de idempotencia por (marca, publicación, versión).

---

## 6. Evaluación retrospectiva — **no se pudo hacer** y qué falta

**Por qué no:** Qualify **no guarda ninguna métrica** de sus publicaciones (no hay lectura de
contadores ni de `/insights` para orgánico, §0); este discovery **no tuvo acceso a producción** y
no ejecutó llamadas a Meta. Tampoco se corrió ScrapeCreators: la CLI no está instalada en esta
máquina y leer cuentas de clientes requiere el visto bueno del fundador.

**Qué falta:** (1) la lista de publicaciones hechas por Qualify en producción; (2) una lectura
de sus contadores con una credencial de producción; (3) el visto bueno del fundador para leer
las cuentas de Qualify.co y de los negocios que administra.

**Cómo correrla después (solo lectura, sin gastar, sin tokens en el doc):**

1. Publicaciones — **una marca a la vez**, bajo `tenant_session` con el `tenant_id` de esa marca (RLS hace el resto; el `WHERE` lo deja explícito). No se usa `admin_session` para esto: es de aprovisionamiento.
   ```sql
   SELECT pa.tenant_id, pa.connection_id, pa.published_media_id,
          pa.media_product_type, pa.settled_at
   FROM publish_attempts pa
   WHERE pa.tenant_id = :tenant_id
     AND pa.status = 'published' AND pa.published_media_id IS NOT NULL
     AND pa.settled_at > now() - interval '180 days'
   ORDER BY pa.tenant_id, pa.settled_at;
   ```
2. Por cada `published_media_id`, con el token de la conexión (vía `credential_session`, nunca
   impreso), un GET con scopes ya concedidos:
   `GET /{media-id}?fields=media_type,media_product_type,timestamp,like_count,comments_count,total_views_count,total_like_count,saved_count,shares_count,boost_ads_list,boost_eligibility_info`
   — guardar la respuesta cruda (sin token) en el scratchpad.
3. Calcular por cuenta y tipo, **excluyendo las publicaciones promocionadas alguna vez** (regla 6): distribución de `total_views_count` (o me gusta + comentarios) ÷ mediana,
   % de vistas del 10 % superior, número de candidatas `po-0`, y motivos de
   `boost_eligibility_info` (H3).
4. Alternativa sin credencial de Meta: `just sc instagram user-posts --handle <cuenta> --cache-max-age 7d`
   sobre las cuentas propias (vistas, me gusta y comentarios públicos; 1 crédito por página;
   `just sc balance` antes y después). Sirve para H1, no para H3.

**Veredictos:**

| Hipótesis | Veredicto | Por qué |
|---|---|---|
| **H1** concentración del alcance | **Sin evidencia propia — por confirmar** | Plausible (`cm-1` ya separa «destacados» en creadores), pero no hay un solo dato de cuentas propias |
| **H2** acepta más una cifra propia | **Sin evidencia — por confirmar** | Hoy no hay ningún aviso; primero la prueba cualitativa de §5, luego la señal cuantitativa de OA-7 |
| **H3** la elegibilidad descarta candidatas | **Parcialmente cierto por diseño, magnitud por confirmar** | Qualify ya descarta historias y carruseles (`live_wizard.py`); el campo de Meta existe pero sus motivos dependen de m-24828971 |

---

## 7. Historias candidatas (no creadas)

| # | Historia | Depende de | Tamaño |
|---|---|---|---|
| OA-1 | Retrospectiva de solo lectura §6 sobre Qualify.co y los negocios del fundador; publicar el resultado aquí | Visto bueno del fundador; credencial de producción (o CLI de ScrapeCreators) | S |
| OA-2 | Leer y guardar contadores por publicación (72 h y 7 d) con los scopes actuales, en un worker idempotente con procedencia | OA-1 confirma H1; tabla nueva con RLS (`qualify-migration`) | M |
| OA-3 | Regla `po-0` versionada (pura, con tests), reutilizando las constantes de `cm-1` | OA-2 | S |
| OA-4 | Aviso arriba de «Tu semana» y etiqueta en la tarjeta de la publicación (bocetos A y A′) con los textos de §3, que abre el asistente de ADS-06 | OA-3; prueba cualitativa de H2 (§5); m-24828971 y m-24828976 probados en vivo; ADS-16 | M |
| OA-5 | Leer `boost_eligibility_info` / `boost_ads_list` en la comprobación de ADS-06 y en la regla 7 | m-24828971 (forma real del campo) | S |
| OA-6 | v1 con `reach` y `/insights`: pedir `instagram_manage_insights`, reconectar, App Review | Decisión del fundador; ADS-15 / épica de App Review | M |
| OA-7 | Medición de H2 y del acierto con ADS-09 | OA-4 en uso ≥ 8 semanas | S |

---

## 8. Recomendación final: **ESPERAR**

**Por qué:** recomendar qué publicación promocionar antes de haber promocionado **una sola**
con Meta real (m-24828971 y m-24828976 sin correr) es construir la puerta antes que la casa, y
H1–H3 no tienen un solo dato propio. Lo barato y sin riesgo es **OA-1** (solo lectura, sin gasto,
sin código de producto).

**Pasa a «seguir» cuando:** (1) m-24828971 responde `boost_eligibility_info` y el 1885183, y
(2) hay al menos una promoción real confirmada (m-24828976), y (3) OA-1 cumple el umbral de H1
de §5. **Pasa a «parar»** si OA-1 muestra que en las cuentas propias el 10 % superior no
concentra ni el 25 % de las vistas, o que < 1 candidata por cuenta y mes pasa la regla 7.

**Estado:** `[PROPUESTO]` — decide el fundador.
