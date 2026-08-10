# Corpus de candidatos — vertical viajes: Cúcuta (CO) / Santa Marta / frontera Táchira (VE)

**Owner:** gtm-specialist · **Fecha de investigación:** 2026-08-08 · **Estado:** COMPLETO (sourcing cerrado; R2/R3 pendientes de verificación por máquina — ver §Método y H4)
**Encargo:** sourcing de cuentas TikTok para el corpus de análisis de hooks (`qualify_models.hooks` — primeros 3 s: hablado/mostrado/texto en pantalla) del vertical **agencias de viajes**. Gemelo metodológico de `docs/corpus-candidatos-inmobiliario-tachira-cucuta.md`. No es un teardown de competencia.
**Autorización:** sólo investigación. **No se ha scrapeado, descargado ni gastado nada** — la verificación de handles usa `yt-dlp` en modo enumeración (metadatos, $0, sin descarga de vídeo).

## Contexto funcional

El corpus alimenta un banco mensual de ideas de contenido (8–12 reels/mes) para una agencia de viajes en lanzamiento en Cúcuta: destino insignia Santa Marta / Caribe colombiano, tiquetes aéreos, público binacional Cúcuta–Táchira/San Cristóbal. Cuatro categorías de cuenta buscadas:

1. **Competidoras directas:** agencias de viajes en Cúcuta / Norte de Santander activas en vídeo.
2. **Benchmark de formato que vende:** agencias colombianas de paquetes a Santa Marta / Caribe (Cartagena, San Andrés) con precio visible, salidas grupales, "todo incluido" — aunque no sean de Cúcuta.
3. **Contenido de destino:** creadores de Santa Marta (hoteles, tours, playas) con buen desempeño en views.
4. **Frontera:** agencias venezolanas (San Cristóbal/Táchira) que venden viajes saliendo desde Cúcuta.

## Criterios de selección (heredados del doc inmobiliario, adaptados)

| # | Requisito | Por qué mata a un candidato |
|---|---|---|
| R1 | Agencia pequeña/mediana o creador individual | Las OTAs/portales (Despegar, Expedia) publican inventario con plantilla corporativa, no ganchos comparables |
| R2 | ~30+ vídeos cortos publicados | Bajo eso la cuenta no llena su celda del diseño |
| R3 | **Variedad de aperturas entre sus vídeos** | El diseño compara tipos de hook **dentro de cada cuenta**; una cuenta que siempre abre igual aporta cero |
| R4 | Métricas visibles (views/likes/fecha) | Sin fecha no se quita la tendencia de crecimiento de la cuenta |
| R5 | Relevancia geográfica o de formato | Cat. 1 y 4: región Cúcuta–Táchira. Cat. 2 y 3: el destino/formato es lo relevante, no la ciudad |

**R3 sigue siendo el criterio escaso**, pero la hipótesis de partida difiere del vertical inmobiliario: el nicho de viajes vive de vender deseo (playa, precio-ancla, "por menos de X te llevo a Y"), no fichas de inventario — se espera **más** variedad de aperturas. El corpus debe confirmarlo o refutarlo, no asumirlo.

## Barra de honestidad aplicada a este documento

- Ninguna cifra de vídeos o seguidores aparece sin fuente nombrada y fecha.
- `[V]` verificado contra la cuenta/página real hoy · `[S]` fuente secundaria (buscador, directorio) · `[H]` hipótesis con evidencia parcial explícita.
- Un handle que no resuelve se marca **NO CONFIRMADO** o se elimina; no se deja pasar como si existiera.

## Método de verificación (2026-08-08) — y un hallazgo operativo que cambia el plan de harvest

El plan era replicar la corrección final del doc inmobiliario: **`yt-dlp` enumera cualquier handle gratis** con recuento exacto de vídeos. **Hoy ese camino está cerrado desde esta máquina.** Medido 2026-08-08:

- `yt-dlp` **2026.07.04** (estable) y **2026.08.04** (nightly), ambos con impersonación `curl_cffi` instalada, fallan sobre TikTok en **los dos niveles**: página de usuario (`Unable to extract secondary user ID`) y página de vídeo individual (`Unable to extract universal data for rehydration`) — incluso sobre vídeos cuya existencia está confirmada por el índice de búsqueda.
- El HTML crudo del perfil (curl con UA de navegador, HTTP 200, 390 KB) contiene el tag `__UNIVERSAL_DATA_FOR_REHYDRATION__` **vacío de datos de usuario** (`secUid`: 0 ocurrencias, nombre de la cuenta: 0) y el título genérico `TikTok - Make Your Day`: TikTok sirve el *shell* sin hidratar.
- Hipótesis más probable, no confirmable desde aquí: **soft-block a nivel de IP/cliente**, plausiblemente secuela del HTTP 429 que el harvest de corpus provocó desde esta misma máquina el 2026-08-06 (documentado en `.claude/sprint-state-2026-08-06-corpus-acquisition.md`). Alternativa no descartada: cambio del lado de TikTok posterior al nightly del 08-04. Distinguirlas requiere probar desde otra IP.

**Consecuencias para este documento y para el harvest:**
1. Ninguna cifra de vídeos/seguidores de TikTok aparece aquí verificada por máquina. `[V]` se reserva para handles confirmados por **fuente primaria propia** (la web/linktree de la agencia enlazando su TikTok) o por **URLs de vídeo del handle resolviendo en el índice de búsqueda**; las métricas quedan `[S]`/no verificado.
2. Antes de lanzar el harvest de este corpus (o de re-lanzar el inmobiliario), hay que **re-probar el camino yt-dlp**: desde otra IP, o tras días de enfriamiento, y con espaciado mucho más agresivo que el actual (`sleep_between=2.0` en `YtDlpFetcher` fue suficiente para provocar el 429). Si el bloqueo persiste, la alternativa es enrutar yt-dlp por proxy (Zyte ya es vendor aprobado) — deja de ser $0, pero sigue siendo barato frente a APIs de datos sociales.

---

## Tabla de candidatos

Leyenda de confianza: `[V]` handle verificado contra fuente primaria (web propia de la agencia o URLs de vídeo del handle resolviendo en el índice de búsqueda, con contenido verbatim) · `[S]` fuente secundaria (resumen de buscador, directorio) · `[H]` hipótesis con evidencia parcial.
`R2 (30+ vídeos)` y `R3 (variedad de aperturas)` quedan **sin verificar en todas las filas** — ver §Método: la vía de verificación por máquina está cerrada hoy.

### Categoría 1 — Competidoras directas: Cúcuta / Norte de Santander

| # | Cuenta TikTok | Confianza | Quién es | Evidencia (2026-08-08) | Por qué es candidata |
|---|---|---|---|---|---|
| C1 | [@luxury_travel22](https://www.tiktok.com/@luxury_travel22) | **[V]** | Luxury Travel Prime S.A.S., Cúcuta (Caobos, RNT 124521, NIT 901595075-3) | Su propia web [agencialuxury.com](https://agencialuxury.com/) enlaza el handle en el footer | Agencia registrada de Cúcuta con web, check-in online y presencia TikTok declarada por ella misma |
| C2 | [@melincue.viajes](https://www.tiktok.com/@melincue.viajes) | **[V]** | Melincue Viajes, Cúcuta (Caobos, Cll 17A #1E-12 ofc 202, RNT 124521) | URL de perfil resuelve en el índice de búsqueda; dirección y RNT en resúmenes de buscador | Vende tours con concierto+vuelo+hotel y financiación — formato de oferta empaquetada. **Ver H1: comparte RNT y dirección con C1** |
| C3 | [@cucutapaseos_](https://www.tiktok.com/@cucutapaseos_) | **[V]** | Cúcuta Paseos — operador de excursiones locales (Chinácota, Tolú/Coveñas, playa) | URL de perfil con nombre "Cúcutapaseos" indexada en buscador | Excursiones terrestres económicas con transporte+comidas+seguro: el formato "salida grupal desde Cúcuta" que el cliente necesita estudiar |
| C4 | [@travelluxury_c](https://www.instagram.com/travelluxury_c/) (IG; TikTok **NO CONFIRMADO**) | **[H]** | Travel Luxury — Viajes-Cruceros-Tours, Cúcuta (Av 2 #14-92, barrio La Playa) | IG con ~28K seguidores según resumen de buscador; búsquedas de su TikTok no devolvieron handle | La agencia de Cúcuta con más audiencia encontrada; si su TikTok existe, es candidata fuerte. Entra sólo como hipótesis: **el handle TikTok no se pudo confirmar** |
| C5 | [@atreveteavolar.co](https://www.tiktok.com/@atreveteavolar.co) | **[S]** | "Agencia de Viajes - online" | Perfil indexado en buscador con ~562 seguidores y 2.558 likes | Agencia online pequeña que aparece en búsquedas de "agencia viajes Cúcuta"; **ubicación no confirmada** — verificar que es de Cúcuta antes del harvest |

### Categoría 2 — Benchmark del formato que vende: paquetes Santa Marta / Caribe (Colombia)

| # | Cuenta TikTok | Confianza | Quién es | Evidencia (2026-08-08) | Por qué es candidata |
|---|---|---|---|---|---|
| B1 | [@agenciadelapetravel](https://www.tiktok.com/@agenciadelapetravel) | **[V]** | Agencia de viajes De la Peña (Colombia, multi-destino) | Perfil indexado + **2 vídeos indexados con caption verbatim**: "2x1 Santa Marta 4 días 3 noches incluye **tiquetes aéreos**… 1.540.000 PAREJA" y "San Andrés desde 1.290.000 5 días todo incluido… paga a cuotas" | **El arquetipo exacto del formato objetivo**: precio-ancla visible, todo incluido, tiquetes aéreos, CTA "escríbenos/cotiza". Prioritaria |
| B2 | [@goza.viajando](https://www.tiktok.com/@goza.viajando) | **[V]** | Agencia colombiana multi-destino | Vídeo indexado verbatim: "Viaja a San Andrés en 2025 al mejor precio ✅ Tiquetes ida y regreso ✅ Hospedaje ✅ Desayunos ✅ Traslados ✅ 2 tours" | Formato checklist-de-inclusiones + precio por temporada — segunda variante del formato que vende |
| B3 | [@agenciamundorutas](https://www.tiktok.com/@agenciamundorutas) | **[V]** | Mundo Rutas (Colombia) | Vídeo indexado verbatim: "Descubre cuánto cuesta nuestro plan todo incluido para San Andrés… déjanos tus datos en el enlace de nuestro perfil" | Variante de hook "cuánto cuesta" (curiosity gap sobre el precio) + captura de lead en perfil — mecánica distinta a B1/B2, útil para variedad R3 del corpus |
| B4 | Camargo Tour — TikTok **NO CONFIRMADO** · [web](https://www.agenciadeviajescamargotour.com/) · [IG @camargotour2025](https://www.instagram.com/camargotour2025/) | **[H]** | Agencia de Bucaramanga y Santander; salidas grupales a Santa Marta, Cartagena, San Andrés | Su web verificada hoy lista IG/YouTube/Facebook pero **no TikTok** | Geográficamente la más análoga al cliente (ciudad andina no-costera vendiendo Caribe), pero sin TikTok confirmado no puede entrar al harvest |
| B5 | Lili Tours / "Me lo Contaron" (Bucaramanga) — handles **NO CONFIRMADOS** | **[H]** | Operadores de salidas grupales Bucaramanga→Santa Marta (~350.000 COP con transporte terrestre, hospedaje, tours) | Sólo resúmenes de buscador sobre páginas `/discover`; ningún handle resolvió | Mismo racional que B4. Pendiente de confirmación de handle antes de contar como candidatas |

### Categoría 4 — Frontera: agencias venezolanas vendiendo desde Cúcuta / San Cristóbal

| # | Cuenta TikTok | Confianza | Quién es | Evidencia (2026-08-08) | Por qué es candidata |
|---|---|---|---|---|---|
| F1 | [@gochi_travels1](https://www.tiktok.com/@gochi_travels1) | **[V]** | Gochi Travels (San Cristóbal, fundada 2020; RIF J503158280) — transporte puerta a puerta Cúcuta↔Venezuela, encomiendas, mascotas | **3 URLs de vídeo del handle indexadas** con captions verbatim sobre el servicio Cúcuta→Venezuela; web propia [gochitravels.com](https://gochitravels.com/); [IG @gochi_travelss](https://www.instagram.com/gochi_travelss/) ~38K seg. según buscador | La cuenta de frontera con más evidencia de actividad encontrada. **Matiz:** vende transporte terrestre, no tiquetes aéreos ni paquetes — su valor para el corpus es el *hook* al público binacional, no el producto |
| F2 | Aly Tours Táchira — handle **NO CONFIRMADO** | **[H]** | Agencia de San Cristóbal; paquetes 4D/3N a Chichiriviche desde $150, rutas Táchira/Mérida | Resúmenes de buscador sobre páginas `/discover` (tels. 0414-7322592 / 0424-7180994); ningún handle resolvió | Único operador venezolano de *paquetes turísticos* (no transporte) encontrado en Táchira — si su handle se confirma, es la mejor candidata de la categoría |
| F3 | Ocean Travel (San Cristóbal/Cúcuta) — handle **NO CONFIRMADO** | **[H]** | "Viajes y Turismo"; aparece en buscador asesorando compra de boletos aéreos | Sólo resúmenes de buscador; aparece tanto en búsquedas de Cúcuta como de San Cristóbal — ni la ciudad ni el handle están confirmados | Si vende boletos aéreos al público binacional es exactamente el competidor del brief; sin handle no entra al harvest |

### Categoría 3 — Contenido de destino: Santa Marta (creadores, hoteles, tours)

| # | Cuenta TikTok | Confianza | Quién es | Evidencia (2026-08-08) | Por qué es candidata |
|---|---|---|---|---|---|
| D1 | [@elviajepacuando](https://www.tiktok.com/@elviajepacuando) | **[V]** | Creador colombiano de itinerarios de viaje | **2 vídeos indexados** verbatim: "Itinerario para visitar Santa Marta" y "Hotel Todo Incluido cerca a Santa Marta con @On Vacation Oficial" | Hace itinerarios y colaboraciones con hoteles — el formato "contenido de destino que convierte" que el cliente debe replicar |
| D2 | [@saraxelmundo](https://www.tiktok.com/@saraxelmundo) | **[V]** | Sara Bonilla, viajera/creadora | Vídeo indexado verbatim: "5 PLANES SANTA MARTA" — listicle con **precios exactos por plan** (Tayrona 28-33K nacionales, tubing 40K…) y CTA de compartir | Hook tipo listicle con precio: tercera mecánica de apertura distinta observada en el vertical |
| D3 | [@eldecolombiaentusojos](https://www.tiktok.com/@eldecolombiaentusojos) | **[V]** | Creador "Colombia en tus ojos" | Vídeo indexado verbatim: "Estos son los costos aproximados para tu viaje a Santa Marta… hotel 90.000 por pareja… lancha 25.000" | Hook de *cost breakdown* ("cuánto cuesta X de verdad") — formato de alta retención típico del nicho, con respuesta a comentarios |
| D4 | [@cantamarbh](https://www.tiktok.com/@cantamarbh) | **[V]** | Cantamar Beach Hostel (Santa Marta) | Vídeo indexado verbatim: "Un pasadía Santa Marta en Cantamar Beach Hostel" | Cuenta de alojamiento publicando pasadías — la voz "oferta de destino" (vs. la voz "agencia emisora" de cat. 2) |
| D5 | [@360_viajesyturismo](https://www.tiktok.com/@360_viajesyturismo) | **[V]** | Viajes y Turismo 360 (Pasto, por hashtags) | Vídeo indexado verbatim: reseña del hotel @hotelesrodadero en El Rodadero con CTA "reserva todo tu plan con @viajesyturismo_360" | Híbrido cat. 2/3: agencia de ciudad andina haciendo *contenido de destino* en Santa Marta como vehículo de venta — estructuralmente lo que el cliente de Cúcuta necesita hacer |

### Descartados, con motivo

| Cuenta | Motivo |
|---|---|
| [@visit360ecuador](https://www.tiktok.com/@visit360ecuador) | **Geografía**: vende San Andrés saliendo desde Quito, público ecuatoriano. El formato es benchmark válido (2 vídeos indexados con precio-ancla en USD), pero mezclar mercado/moneda contamina el corpus |
| [@comiendocontriana](https://www.tiktok.com/@comiendocontriana) | Creador de comida/viajes que *cotiza con* una agencia (@hoturis_viajes) — no es agencia ni contenido de destino sistemático |
| [@carlosnomada](https://www.tiktok.com/@carlosnomada) | Creador de vuelos nacionales (Medellín–Cartagena); tangencial al brief, sin foco Santa Marta ni Cúcuta |
| [@viajesconclau](https://www.tiktok.com/@viajesconclau) | Creadora venezolana con contenido de destino sobre San Cristóbal — dirección inversa a la del brief (mostrar Táchira, no vender Caribe al tachirense) |
| Poporo Tours, Wiwa Tour (Santa Marta) | Operadores receptivos reales con web verificada hoy, pero **sin TikTok enlazado en sus webs** — no hay handle que harvestear |
| OTAs / mayoristas (Despegar, On Vacation corporativo, Éxito Viajes) | **R1**: inventario con plantilla corporativa, no ganchos comparables con una agencia local |

## Hallazgos

### H1 — "Dos competidores" de Cúcuta son la misma empresa: Melincue Viajes y Luxury Travel Prime comparten RNT (124521) y dirección (Cll 17A #1E-12 ofc 202, Caobos)

Verificado cruzando la web propia de Luxury Travel Prime ([agencialuxury.com](https://agencialuxury.com/), que declara RNT 124521 y esa dirección) con los datos de Melincue en resúmenes de buscador (misma dirección, mismo RNT, teléfono distinto). Una entidad legal, dos marcas/cuentas TikTok (C1 y C2).

Dos consecuencias para el corpus: (a) el mapa competitivo real de Cúcuta tiene **menos actores que cuentas** — quien lea este doc como censo de competidores contaría de más; (b) si C1 y C2 comparten equipo de contenido, sus aperturas pueden compartir plantilla, y el diseño del análisis (que compara variedad *dentro* de cada cuenta) debería tratarlas como potencialmente correlacionadas, no independientes.

### H2 — A diferencia del vertical inmobiliario, aquí los captions ya muestran variedad de mecánicas de apertura

El hallazgo H1 del doc inmobiliario fue que el nicho publica una única plantilla (`[operación]+[m²]+[ubicación]+[precio]`). En viajes, sólo con los captions verbatim indexados hoy, se observan al menos **cinco mecánicas distintas**:

1. **Precio-ancla + paquete** ("2x1 Santa Marta… 1.540.000 PAREJA" — B1)
2. **Checklist de inclusiones** ("✅ Tiquetes ✅ Hospedaje ✅ Desayunos…" — B2)
3. **Curiosity gap sobre el precio** ("Descubre cuánto cuesta nuestro plan…" — B3)
4. **Cost breakdown de creador** ("Estos son los costos aproximados…" — D3)
5. **Listicle con precios** ("5 PLANES SANTA MARTA" — D2)

**La salvedad metodológica del doc inmobiliario aplica idéntica**: el hook definido por el spike son los 3 primeros segundos del *vídeo*, no el caption. Pero la dirección de la evidencia es la opuesta a la del inmobiliario: allí los captions sugerían plantilla única; aquí sugieren variedad real. El riesgo R3 en este vertical parece **bajo**, lo que convierte a viajes en mejor primer corpus que inmobiliario si hubiera que elegir.

### H3 — El producto exacto del cliente (tiquetes aéreos + Caribe desde Cúcuta, público binacional) casi no tiene incumbente TikTok encontrado

Estado observado, con las búsquedas de hoy: las cuentas de frontera con actividad real venden **transporte terrestre** (Gochi Travels: puerta a puerta Cúcuta↔Venezuela); las agencias de Cúcuta encontradas venden excursiones terrestres locales (Cúcuta Paseos) o portafolio generalista (Luxury/Melincue); y las vendedoras agresivas de paquetes Caribe con tiquete aéreo encontradas emiten desde Bogotá/Bucaramanga/otras ciudades, no desde Cúcuta. No apareció ninguna cuenta TikTok activa que venda específicamente "Santa Marta/Caribe en avión saliendo de Cúcuta al público binacional". Se registra el estado del campo; la lectura de oportunidad corresponde a otro eje.

### H4 — Operativo: el camino de harvest $0 está roto desde esta máquina hoy

Detallado en §Método. Afecta a este corpus **y** al inmobiliario (re-harvest). Nada debe presupuestarse asumiendo yt-dlp funcional hasta re-probarlo desde otra IP o tras enfriamiento.

## Recomendación

**Prioritarias para el primer harvest (en orden), cuando el camino yt-dlp se re-abra:**

1. **B1 [@agenciadelapetravel](https://www.tiktok.com/@agenciadelapetravel)** — el arquetipo del formato que vende (precio-ancla, todo incluido, tiquetes); 2 vídeos verbatim ya observados con mecánicas distintas entre sí.
2. **C1 [@luxury_travel22](https://www.tiktok.com/@luxury_travel22)** — competidor directo en Cúcuta, handle verificado por fuente primaria propia.
3. **D1 [@elviajepacuando](https://www.tiktok.com/@elviajepacuando)** — contenido de destino con colaboración hotelera; la voz que el cliente debe aprender.
4. **F1 [@gochi_travels1](https://www.tiktok.com/@gochi_travels1)** — la única cuenta de frontera con actividad verificada; aporta el registro del público binacional.
5. **D3 [@eldecolombiaentusojos](https://www.tiktok.com/@eldecolombiaentusojos)** — la mecánica *cost breakdown*, ausente en las cuentas de agencia.

**Precondiciones antes de gastar en adquisición** (heredadas del doc inmobiliario, siguen vigentes):
- Re-probar el camino yt-dlp (H4). Con él re-abierto, verificar R2 (30+ vídeos) por máquina para las cinco prioritarias — hoy **ninguna fila tiene R2 verificado**.
- Chequeo de mediana de likes de los últimos ~10 vídeos por cuenta (el H2 del doc inmobiliario): si una cuenta vive en 0-5 likes/vídeo, no puede sostener correlación alguna.
- Los handles `[H]` (Travel Luxury TikTok, Camargo, Lili Tours, Aly Tours, Ocean Travel) **no entran al harvest** hasta confirmarse; están listados porque son los nombres correctos que buscar con variantes cuando haya navegador humano — la lección del doc inmobiliario de que los handles no son estables entre plataformas aplica aquí.
