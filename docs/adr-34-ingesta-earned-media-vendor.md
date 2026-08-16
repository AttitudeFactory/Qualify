# ADR 34 — La ingesta de earned media se **compra con payload crudo**; ADR 17 se reabre solo para esa superficie

**Estado:** `[PROPUESTO]` — pendiente de firma del fundador.
**Fecha:** 2026-08-13 · **Fase:** 1, Partes 2 y 3 · **Reabre:** ADR 17 (solo la superficie *earned media* de IG/TikTok).
**Documentos hermanos:** `docs/adr-32-motor-angulos-creativo.md` (el consumidor de estos datos), `docs/alternativas-fase1.md` (evidencia de vendors), `packages/models/NOTES_hook_pattern_spike.md` (el contrato de entrada que hay que alimentar).

---

## Contexto

El fundador priorizó el **Motor de Ángulos (ADR 32) sobre Instagram**. El contrato de entrada del spike de ganchos es duro y no negociable: `extract_hook_features(video_path: Path, ...)` consume **un mp4 en disco**, del que produce él mismo los fotogramas y el WAV de 16 kHz. Un vendor que entregue thumbnails, keyframes o transcript **no satisface el contrato**.

Tres hechos, todos medidos, delimitan el problema:

1. **Instagram no sirve nada al visitante deslogueado.** La página de perfil anónima es un shell `PolarisLoggedOut` con cero ocurrencias de `username`, `video_versions` o el timeline. No es una limitación de nuestro cliente: no hay contenido que parsear.
2. **El camino gratuito murió el 2026-08-08.** `yt-dlp` falla desde esta máquina en los dos niveles (perfil y vídeo), con estable y nightly, incluso con impersonación — soft-block por IP tras el 429 del 06-08.
3. **La superficie oficial no alcanza, y en TikTok es cero.** En Instagram, `media_url` es campo público y descargable, pero Meta lo **omite si el media contiene material con copyright, citando explícitamente el audio de Reels** — se cae en silencio justo en los reels con audio de tendencia, que son los que más importan para ganchos. En TikTok **ningún producto expone el fichero de vídeo por ninguna vía, ni con OAuth del creador**; y la única API que haría el trabajo (Research API) excluye por escrito a los usuarios comerciales.

ADR 17 decidió **construir** la ingesta sobre Zyte, y registró su propia condición de reapertura: *«si algún día apareciera un vendor que sí vendiese earned media de TikTok/IG **con media crudo**, eso reabriría ADR 17»*. Esta ADR documenta que esa condición **se cumplió y se verificó empíricamente**.

## La medición

Ejecutada 2026-08-13 contra **ScrapeCreators**, dos cohortes, **665 reels**, 59 créditos de un plan gratuito de 100. Todo lo de abajo es **MEDIDO**, no documentación de vendor.

### Economía y consistencia

| Métrica | Resultado |
|---|---|
| Reels por crédito | **12,0 exactos en las 36 páginas** — cero varianza |
| 10.000 reels (metadata + URL) | **833 créditos ≈ $1,57** (tarifa $47/25K) |
| Corpus del hook spike (217 vídeos) | **≈ 18 créditos ≈ $0,03** |
| Cobro por handle inexistente | **0 créditos** (404) — la verificación de candidatos es gratis |
| Cobro por error 500 del vendor | **0 créditos** |

### Entrega de media — la pregunta que decidía la compra

| Métrica | Resultado |
|---|---|
| URLs de vídeo sondeadas desde nuestra IP | **72/72 vivas (HTTP 206). Cero 403** |
| Hosts CDN distintos atravesados | **17** |
| TTL declarado (`oe` decodificado) | **31,9 – 36,0 h**, mediana **34,2 h** |
| ¿mp4 con faststart? | **Sí** — `moov` en offset 36, `mdat` en 19439 |
| ¿Basta un `Range` de 1,5 MB? | **Sí** — 9 fotogramas + 96 KB de WAV 16 kHz de la ventana de 3 s |

El aviso público de Apify sobre *«IP blocks on large runs»* **no se materializó** en 72 descargas contra 17 CDNs.

### Payload

| Métrica | Resultado |
|---|---|
| Campos por objeto media | **125** — el shape **nativo** de Instagram (Apify normaliza a 33; Data365 a 15) |
| Completitud de `play_count`, `like_count`, `comment_count`, `video_duration`, `video_versions`, `has_audio`, `caption`, `clips_metadata` | **100 %** |
| Identidad de audio (`clips_metadata.original_sound_info.audio_asset_id`) | **99–100 %** |
| Métrica de resultado | `play_count` / `ig_play_count` — **no** se llama `view_count` |
| Profundidad histórica medida | hasta **2,5 años** (`@haddad_inmobiliaria`, 2023-11 → 2026-07); `more_available` seguía en `true` en la página 17 — **no se encontró techo** |

### Tamaño real del contenido

Mediana de duración **83 s**, p90 **157 s**; solo el **16 %** baja de 30 s. Eso son **~11,4 MB por reel** completo → 111 GB por 10.000 reels. Con `Range` de 1,5 MB (suficiente para la ventana de gancho) son **15 GB**, un **−87 %**.

### Fiabilidad

**36 páginas correctas de 37 intentos sobre cuentas vivas ≈ 97 %.** Un `HTTP 500` cortó una cosecha a mitad de paginación. Un handle de nuestros propios docs (`@inmobiliariatonchala`) devolvió 404.

### El hallazgo que no buscábamos: contaminación por alcance pagado

`is_paid_partnership` salió **0 de 665**. La etiqueta declarada casi no se usa en estas cohortes y **no es el contaminante relevante**.

El contaminante real es el **alcance pagado (boosting)**, que Meta admite y no separa: `view_count` *«incluye métricas de pago y orgánicas»*, sin campo que las distinga. Existe una **firma proxy**: el alcance comprado llega a público no interesado → suben las vistas, baja el engagement.

| Cuenta | ER mediana | ER top-decil | Ratio | Lectura |
|---|---|---|---|---|
| `@platzi` | 1,10 % | 0,38 % | **0,35** | ⚠ alcance pagado probable |
| `@inmobiliariamarelsa` | 1,19 % | 0,58 % | **0,49** | ⚠ alcance pagado probable |
| `@haddad_inmobiliaria` | 0,33 % | 0,24 % | 0,73 | mixto |
| `@inmobiliarialafontana` | 0,89 % | 1,26 % | 1,41 | orgánico limpio |
| `@edteamlat` | 2,68 % | 4,11 % | 1,54 | orgánico limpio |
| `@codigofacilito` | 1,72 % | 2,06 % | 1,20 | orgánico limpio |

**En dos de seis cuentas, los reels con más vistas tienen menos engagement que los normales.** Entrenar el Motor de Ángulos con esos reels enseñaría *lo que compró un media buyer*, no *lo que ganó un gancho*.

### La brecha de nicho

Mediana de vistas: inmobiliaria **~750** · `@edteamlat` **20.232** · `@platzi` **79.596**. Son **~100×**. Un filtro global por vistas absolutas habría seleccionado **cero** reels inmobiliarios — la cohorte del cliente 1 desaparecería del análisis.

## Decisión

1. **Se reabre ADR 17 exclusivamente para la superficie *earned media* de IG/TikTok.** El acceso a esa superficie se **compra**; el parseo, el aterrizaje, la cascada multimodal y la capa de señales se siguen **construyendo**. ADR 17 permanece intacto para todo lo demás, y Zyte sigue siendo el vendor de proxy/anti-bloqueo (`CLAUDE.md`, Bloque 1). **Las dos razones principales de ADR 17 para construir —el techo del esquema normalizado y la necesidad de media cruda— quedan satisfechas por el vendor, no violadas.**

2. **Vendor primario: ScrapeCreators, detrás del `VideoFetcher` Protocol** (`packages/scraper/.../research/harvest.py`), que se promueve al camino de producción. **Obligatorio un segundo proveedor** tras la misma costura (HikerAPI o Bright Data) antes de depender de esto en producción: el primario es un **fundador único** bajo `Web Scraping Guy LLC`, sin SLA y con reembolsos discrecionales.

3. **Nunca se depende del espejo del vendor.** Se pide la ruta de listado (1 crédito/página, payload crudo + URL de CDN) y **bajamos los bytes nosotros a R2**. El «mirror permanente» de un tercero no puede ser nuestra capa de almacenamiento; así el vendor es sustituible en una tarde.

4. **El payload crudo se persiste íntegro en R2** bajo `payload_schema_version = 2` y `raw_payload_key()`. Es el shape nativo de Instagram, así que **ADR 18/22 se cumple de verdad**: se puede re-parsear sin re-pagar. Esto es lo que Apify y Data365 **no** permiten.

5. **Del vídeo se persiste solo la cabecera** (`Range` de ~1,5 MB), suficiente para la ventana de gancho. Justificación: la URL caduca en ~34 h **pero el reel no**, y re-pedir el listado cuesta **$0,00016**, así que re-adquirir una URL fresca siempre es posible. Guardar cabeceras no es una apuesta irreversible.

6. **Reintentos obligatorios en el pipeline.** 97 % de éxito por página está medido; sin reintento con backoff, una cosecha se corta a mitad y produce un corpus sesgado por truncamiento.

7. **El selector que alimenta la cascada cara es estratificado**, con cuatro reglas:
   - **Normalizar dentro de cada cuenta** (`score = vistas / mediana_orgánica_de_la_cuenta`). La brecha de 100× entre nichos hace que cualquier umbral global sea inservible.
   - **Ajustar por edad** — un reel de 2 días no ha acumulado vistas. *La curva actual es una heurística sin calibrar; ver gate G-EDAD.*
   - **Estratificar: decil superior Y decil inferior.** Seleccionar solo ganadores es **seleccionar sobre la variable dependiente**: sin clase negativa, todo gancho observado parece ganador y el modelo no puede aprender nada.
   - **Excluir los sospechosos de alcance pagado del entrenamiento**, no del dashboard. El usuario debe verlos marcados; el modelo no debe aprender de ellos.

   Medido sobre 649 reels: **126 seleccionados (19 %)**, −81 % en la etapa cara, 189 MB frente a 7,2 GB.

8. **Dos indicadores de cuenta son de primera clase en el producto**, ortogonales entre sí:
   - **Pureza orgánica** = ER(top-decil) / ER(mediana). Por debajo de ~0,6, sospecha de distribución comprada.
   - **Dispersión** = max/mediana. `@inmobiliarialafontana` da **1,8×** frente a **57×** de `@platzi`: **una cuenta sin varianza no enseña nada** sobre ganchos. Es criterio de selección de cohorte, no adorno.

9. **Instagram y TikTok tienen posturas distintas y deben documentarse así:** en IG el vendor cubre los huecos de la API oficial (búsqueda por keyword, comentarios ajenos, reels con audio licenciado, histórico). En **TikTok el vendor es la única fuente física posible** de fotogramas y audio — no es una decisión de coste.

## Alternativas rechazadas

- **Data365.** Esquema normalizado de 15 campos **sin `views_count`** → no puede alimentar el Motor de Ángulos, cuyo outcome primario son las vistas. Además **no existe búsqueda por keyword en Instagram** (medido: `/instagram/search/...` → 404 mientras el de Twitter → 403), piso de **€300/mes** para una sola red, onboarding con llamada obligatoria, sin SLA, sin status page, **sin DPA**. Su propio blog declara *«Data365 isn't a downloader»*.
- **Apify.** Funciona y documenta el espejado, pero cobra el vídeo a **$0,015/MB = $15,36/GB**, que es **1,9× su propio precio de proxy residencial**. Con la duración real medida (11,4 MB/reel) son **~$1.710 por 10.000 reels**, frente a **$1,57**. Payload normalizado a 33 campos → viola la regla de re-parseo. Y sus actors de Instagram son **código cerrado** (0 repos públicos, `gitRepoUrl: null`), de modo que la vía «auto-hospedarlo» **no existe**.
- **Construir sobre Zyte.** Zyte rota IPs y resuelve retos anti-bot; **no rota el `doc_id` de la GraphQL de Instagram (que cambia cada 2–4 semanas) ni mantiene sesiones autenticadas**. Un scraper propio de IG no es un coste de construcción sino **mantenimiento perpetuo**. La decisión de proxies ya tomada no cubre este bloque.
- **Solo API oficial.** Cubre el plano propio con holgura, pero deja fuera búsqueda por keyword, comentarios ajenos, histórico garantizado y —decisivo— **el fichero de vídeo justo en los reels con audio de tendencia**.
- **Cuenta propia de Instagram con `yt-dlp` autenticado.** Rechazada por radio de explosión, no por dificultad: la cuenta candidata (`@qualifymkt.co`) es **la misma cuya credencial de Página está en custodia y publicó el primer reel**. Usar la identidad de publicación del producto como identidad de scraping pone en riesgo el único camino vivo. Regla que queda escrita: **nunca usar como identidad de scraping la credencial que es la identidad de publicación.**

## Consecuencias

- **Positiva:** el bloqueo del hook spike (*«Fase D diseñada pero sin datos»*) se levanta por **$0,03** de adquisición. Deja de ser un problema de presupuesto y pasa a ser una tarde de trabajo.
- **Positiva:** `ingestion.raw_payloads` recupera su propósito — con este vendor sí hay payload crudo que guardar, que es la premisa de ADR 18/22.
- **Negativa:** dependencia de un proveedor unipersonal. Mitigada por (2) y (3), no eliminada.
- **Negativa, y no se elimina comprando:** los ToS de TikTok para el EEE prohíben la extracción automatizada *«operada por un tercero o de otro modo»* — interponer un vendor traslada el trabajo técnico, **no el incumplimiento contractual**. Y el precedente que cita el sector (*Meta v. Bright Data*, N.D. Cal. 2024) ampara el scraping **deslogueado** de datos públicos, mientras hemos medido que Instagram sirve página vacía al deslogueado: si los bytes exigen sesión, la sentencia no cubre esa conducta. **Riesgo residual real, limitado al plano de media ajena.** Los tres ToS revisados lo devuelven al cliente por escrito.
- **Operativa:** los datos comprados son la **vista deslogueada**, que subestima sistemáticamente las métricas frente a lo que el creador ve en su propio Insights. Ninguna promesa de reporting debe prometer reconciliación con el panel del creador.

## Gates abiertos

- **G-VOL — volumen sostenido, SIN MEDIR.** Lo ejecutado fue una ráfaga de ~8 minutos. Antes de producción hay que medir un día completo de cosecha programada: rate limits, tasa de 500 y aparición de 403 bajo carga sostenida.
- **G-PAGO — el detector de alcance pagado es un proxy, no un veredicto.** La inversión de ER también la produce la **viralidad orgánica** (un reel que se dispara alcanza público fuera del núcleo y baja su ER). Hace falta un segundo indicador para separar comprado de viral, porque el primero contamina el entrenamiento y el segundo es exactamente lo que queremos aprender. **Hasta cerrarlo, la etiqueta del dashboard debe decir «sospecha», nunca «pagado».**
- **G-EDAD — la curva de madurez está sin calibrar.** El ajuste actual (`madurez = edad/14`, con suelo 0,25) es una heurística inventada y está empujando reels de 0–3 días al decil superior. Debe calibrarse contra curvas reales de acumulación de vistas antes de que el selector alimente decisiones de producto.
- **G-DPA — sin revisión legal.** Antes de que el primer cliente B2B firme, un abogado debe leer las cláusulas de redistribución e indemnización del vendor elegido y confirmar la posición RGPD para datos personales de creadores.

## Lo que esta ADR **no** decide

- **No toca el plano propio** (cuentas conectadas por OAuth). Ese plano se sirve de la API oficial, no tiene riesgo de ToS y no necesita vendor. La separación de planos de ADR 24(c) sigue mandando: `tenant_id` para primera parte, `brand_id` para media ajena.
- **No elige el segundo proveedor.** Solo lo hace obligatorio antes de producción.
- **No abre la Instagram Creator Marketplace API**, que sigue bajo ADR 33 como superficie de credenciales.
- **No reabre ADR 17 para el resto de la ingesta**, ni desplaza a Zyte de su rol de proxy.

---

## Apéndice — reproducibilidad

Scripts del experimento en el scratchpad de la sesión (`sc_experiment.py`, `sc_volume.py`, `sc_faro.py`). Cohortes usadas:

- **Faro (inmobiliaria):** `@haddad_inmobiliaria` (96 reels), `@inmobiliarialafontana` (96), `@zonainmobiliariacolombia` (14), `@rentahousecolombia` (12), `@inmobiliaria.colombia` (12, sin métricas). Muertas y gratuitas: `@inmobiliariatonchala`, `@inmolafontana`, `@inmobiliariahabitar`.
- **Attitude (software/edu):** `@edteamlat` (216), `@platzi` (84), `@codigofacilito` (84).

**Higiene de datos detectada:** `@inmobiliariatonchala` está citada en `packages/models/NOTES_hook_pattern_spike.md` y **ya no existe**. Los handles en los docs caducan; cualquier corpus debe re-verificarse antes de usarse (cuesta 0 créditos).
