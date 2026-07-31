# Oportunidades de mercado — sector inmobiliario

> **Autor:** `market-opportunity-analyst` (analista externo, consultoría). **Fecha:** 2026-07-29.
> **Postura:** de fuera hacia dentro. Primero qué se mueve en el mercado, después —y solo después— si Qualify está cerca.
> **Tiering de evidencia:** `[P]` primaria (URL + fecha de acceso) · `[S]` secundaria · `[H]` hipótesis.
> **Regla dura:** ningún número de mercado, presupuesto o adopción inventado. Lo desconocido se queda vacío, emparejado con el experimento que lo resolvería.

## Hallazgo cero: la asimetría del portafolio de research

Qualify tiene cuatro nichos en el radar (creadores, podcasters, e-commerce/social-commerce, inmobiliario).
Los tres primeros tienen corpus de research. **El inmobiliario no tiene ninguno — y es el único con un cliente que paga ("cliente uno").**

Eso no es un hueco de agenda: es un hallazgo. Significa que la única evidencia de disposición a pagar
que existe en el proyecto proviene del segmento sobre el que menos se sabe, y que las decisiones de producto
tomadas hasta hoy se han informado con research de segmentos que **no** han puesto dinero. Cualquier lectura de
"validación de mercado" en este proyecto debe ajustarse por ese sesgo antes de usarse.

**Cómo aplicarlo:** al ponderar prioridades de roadmap, tratar el research de creadores/podcasters/e-commerce como
*exploratorio* y el input del cliente uno como *evidencia de campo con n=1* — ninguno de los dos es demanda de mercado probada.
Ver [[user_role]] y el resto de este documento.

---

## Índice de secciones

1. [Due diligence: capacidad real de Qualify contra el filesystem](#1-due-diligence-capacidad-real-de-qualify-contra-el-filesystem)
2. [Cambios de plataforma, política y formato](#2-cambios-de-plataforma-política-y-formato)
3. [Dónde quema presupuesto de marketing una inmobiliaria hoy](#3-dónde-quema-presupuesto-de-marketing-una-inmobiliaria-hoy)
4. [Capacidades de IA recién abaratadas y qué commoditizan](#4-capacidades-de-ia-recién-abaratadas-y-qué-commoditizan)
5. [Señales de innovación](#5-señales-de-innovación)
6. [Tesis de oportunidad](#6-tesis-de-oportunidad)

---

## 1. Due diligence: capacidad real de Qualify contra el filesystem

> **Método:** todo lo de esta sección se verificó ejecutando `ls`/`find`/`grep`/`pytest --collect-only` sobre
> `/Users/herwin/Desktop/Qualify` el **2026-07-29**. No se tomó nada de `CLAUDE.md` ni `README.md`, que describen
> *arquitectura objetivo*. Evidencia tier `[P]` — el disco es la fuente primaria sobre sí mismo.
> Toda puntuación de adyacencia en la §6 se apoya exclusivamente en esta tabla.

### 1.1 Lo que EXISTE y funciona

| Activo | Estado verificado en disco | Nota que cambia la lectura |
|---|---|---|
| **Cascada multimodal** (`packages/models/`) | Real. `cascade.py` orquesta `filter → vision → transcription → sentiment` con `PIPELINE_VERSION` y `source_id` propagados (provenance de verdad, no aspiracional). | El orden documentado en `arquitectura.md` §3.4 (F1 filtrando antes que F2, descartando ~60%) **no está implementado**: falta un clasificador "has signal". Hoy transcribe todo. Eso es coste real por ítem. |
| **Filtro zero-shot** | `google/siglip2-base-patch16-224`, hardcodeado en `filter.py:15`. Corre local vía `transformers`. | El único componente de la cascada que no depende de un proveedor externo. |
| **Visión (VLM)** | `Qwen/Qwen3-VL-4B-Instruct` en las DOS rutas (local `transformers` y hosted). La hosted usa `InferenceClient(provider="featherless-ai")` — **proveedor único hardcodeado** (`providers.py:128`). | `moondream` sigue en el código como `vikhyatk/moondream2` (`providers.py:50`), que **no es** el `moondream/moondream3-preview` BSL de los docs. El doc y el código divergen en el checkpoint, no solo en la licencia. |
| **Transcripción** | `openai/whisper-large-v3-turbo` vía `InferenceClient(provider="auto")` (`providers.py:180`). | `provider="auto"` = sin control de a quién se le paga ni de latencia. Comprado, no construido. |
| **Sentimiento** | `pysentimiento/robertuito-sentiment-analysis`, local. | 3 clases de polaridad. Ver §4 y §6 — es el eslabón más débil para inmobiliario. |
| **Scraper** (`packages/scraper/`) | Cliente Zyte + parsers TikTok/Instagram + envelope `payload_schema_version = 2`. | Existe como librería. **No hay nada que lo llame periódicamente** — no hay scheduler. |
| **Conexiones / OAuth Meta** (`packages/api/connections/`) | El módulo más maduro del repo: 18 archivos, incluye `meta_oauth`, `state_token`, `crypto`, `credential_reader`, `fsm`, `locks`, `resolver`, `verifier` y **`revoke.py` (que `CLAUDE.md` declara inexistente — ya está en disco)**. | Ingesta first-party por cuenta conectada: es el activo más real que tiene Qualify hoy. |
| **Plano transaccional** | Postgres + Alembic con **4 revisiones** aplicables: `0001_tenancy`, `0002_connections`, **`0003_publishing`** (`publish_attempts` write-ahead + `scheduled_posts`), **`0004_inbox`** (`threads` + `messages`). RLS por `tenant_id`. | `0003`/`0004` son nuevas y **no** están en `CLAUDE.md`. Publicación programada y bandeja de entrada tienen esquema en disco. |
| **UI Reflex** (`Qualify/`) | Dos mitades. `connections_*` (≈1.050 líneas) está **cableada al backend real** vía `tenant_session`. | La otra mitad (dashboard de menciones: `components.py`, `state.py`) sigue sobre **SQLite local con datos semilla** (`db.py`: `create_engine("sqlite:///reflex.db")`). No está conectada a ningún pipeline. |
| **Suite de tests** | **298 tests** recolectables offline (`pytest -m "not integration"`, verificado 2026-07-29). | Sube desde los 147 que documenta `CLAUDE.md`. El repo avanzó mucho más rápido que sus docs. |

### 1.2 Lo que NO existe (verificado por ausencia)

| Ausente | Evidencia |
|---|---|
| **ClickHouse** | Cero servicio en `docker-compose.yml` (solo `postgres`, `redis`). Cero cliente. Las 6 coincidencias de "clickhouse" en el código son **comentarios y docstrings**, ninguna es una importación. `migrations/clickhouse/` no existe. |
| **Celery / workers** | `grep -ril "celery"` sobre `packages/`, `Qualify/`, `pyproject.toml` → **cero coincidencias**. No hay colas, no hay `scrape_jobs`, no hay scheduler. |
| **`scripts/`, `infra/`, `packages/pipeline/`, `packages/gpu-service/`** | No existen como directorios. |

### 1.3 Los tres matices que más fácil se malinterpretan

Estos tres son la razón por la que esta sección es la tarea de mayor prioridad de la sesión. Cada uno convierte
un "Qualify ya casi lo tiene" en un "Qualify no lo tiene".

**(a) El cliente R2 existe como código pero nunca ha hablado con R2.**
`CLAUDE.md` dice que no hay cliente R2; el disco dice que sí (`packages/shared/src/qualify_shared/objects/`:
`s3.py`, `gate.py`, `keys.py`, `config.py`). Pero `boto3` **no está declarado como dependencia** en ningún
`pyproject.toml` (verificado por grep) y se importa de forma diferida dentro de la factory. El propio docstring
de `s3.py` lo dice: los tests corren "contra un doble en memoria". Traducción para adyacencia: **el plano de
objetos está diseñado y testeado contra un simulacro, no ejercitado**. Cuenta como *media*, jamás como *alta*.

**(b) La publicación en Meta nunca se ha ejecutado contra Meta.**
Cita literal de `packages/api/src/qualify_api/publishing/client.py`:

> *"Nobody in this repo has run this flow against Meta yet, so every response shape is a reading of the corpus
> rather than an observation."*

El esquema (`0003_publishing`) y el cliente existen; el flujo real no se ha observado nunca. Además el propio
archivo documenta que el corpus de Meta **se contradice a sí mismo** sobre el esquema de `Authorization`
(`Bearer` vs `OAuth` según la página), por lo que el esquema vive como dato configurable y no como literal.
Eso es buena ingeniería y, a la vez, la confesión de que esto es una lectura de documentación, no una integración probada.

**(c) Toda la cascada multimodal está marcada `integration` — es decir, no corre en CI.**
Los 8 archivos de test de `packages/models/tests/` que ejercitan filter/vision/transcription/sentiment/cascade
llevan el marcador `integration`, que por configuración del repo **nunca se ejecuta en CI**. Los 298 tests verdes
offline **no incluyen ni una sola pasada real de la cascada**. La cascada funciona (se ha corrido a mano contra
fixtures), pero no hay red de seguridad automática sobre el activo diferenciado. Cualquier tesis que asuma
"la cascada es sólida y sólo hay que apuntarla a otro nicho" debe descontar esto.

### 1.4 Rúbrica de adyacencia (explícita y auditable)

No hay skill instalada de scoring de oportunidades (hueco COMPASS conocido), así que el criterio va escrito
para que sea auditable y destilable:

| Nivel | Definición operativa |
|---|---|
| **alta** | Reutiliza activos de §1.1 **tal como están hoy**. No requiere ClickHouse, ni Celery, ni R2 ejercitado, ni una llamada a Meta nunca probada. |
| **media** | Reutiliza activos de §1.1 + trabajo nuevo **acotado y ya especificado** (p. ej. declarar `boto3` y ejercitar R2; escribir el scheduler que hoy no existe). |
| **baja** | Exige fundaciones ausentes de §1.2 (ClickHouse, Celery) o abandonar el orden de fases. |
| **nula** | Exige renunciar a la tesis de fuente primaria ("leer el contenido, no el perfil"). Eso no es una oportunidad adyacente: es otra empresa. |

**Peso decisivo:** la ausencia de Celery/scheduler es más limitante que la de ClickHouse. Sin ClickHouse se puede
analizar poco volumen en Postgres; **sin orquestación asíncrona no hay ningún producto de monitoreo continuo**,
solo un script que alguien ejecuta a mano.

---

## 2. Cambios de plataforma, política y formato

> ### ⚠ CORRECCIÓN GEOGRÁFICA (2026-07-30) — leer antes que el resto de la sección
>
> **La primera redacción de esta sección estaba equivocada en lo que más importa: el comprador.**
> Se escribió asumiendo implícitamente un comprador estadounidense. `gtm` verificó contra el disco que el cliente
> que paga es una **inmobiliaria en URUGUAY** (`tenant country='UY'`), con un tenant hermano en **Cúcuta, Colombia**.
>
> Verificado contra fuente primaria el 2026-07-30, la restricción **no se transfiere**. La doc de Meta dice
> literalmente que las restricciones de audiencia obligan a quien está *"based in the United States or running ads
> reaching the United States, Canada, or Europe"*, y que:
>
> > *"Businesses outside the U.S. and reaching audiences outside the U.S., Canada, and Europe... **must also pass the
> > Special Ad Category field, but can choose to opt-in or opt-out of audience restrictions**."*
> > — https://developers.facebook.com/docs/marketing-api/special-ad-category/, consultado 2026-07-30
>
> **Para una inmobiliaria uruguaya anunciando en Uruguay: debe *declarar* la categoría, pero puede *optar por salir*
> de las restricciones de segmentación.** Es una casilla administrativa, no una confiscación de la palanca.
> Y la **Fair Housing Act / 24 CFR §100.75 es derecho estadounidense**: no vincula a una inmobiliaria uruguaya.
>
> **Consecuencia honesta: la tesis T-1 tal como se formuló el 2026-07-29 no aplica al cliente que paga.** Se conserva
> abajo el análisis de EE. UU. porque sigue siendo correcto *para EE. UU.* y porque un mercado futuro puede
> justificarlo — pero **deja de ser el hallazgo estructural de este nicho** y baja de rango en la §6.
> **Importar una restricción regulatoria estadounidense a un comprador latinoamericano habría sido exactamente el
> error que esta sección advertía en otros: adyacencia inflada sobre una base que no existe.**
>
> **Lo que sí hay es una inversión**, y resulta más interesante que el hallazgo original: para este comprador la
> presión regulatoria **no está en la salida (segmentación publicitaria, relajada) sino en la entrada (protección de
> datos, endurecida a nivel europeo)**. Ver la nueva **§2.5**, que es ahora el hallazgo estructural real de la sección.

**Veredicto para EE. UU./Canadá/Europa: sí, vivienda es categoría especial restringida y allí es el cambio
estructural del nicho. Para Uruguay y Colombia: no vinculante, opt-out disponible.**

### 2.1 Meta: `HOUSING` es una Special Ad Category con restricciones duras y verificables

Fuente primaria: documentación de la Marketing API de Meta `[P]`
(https://developers.facebook.com/docs/marketing-api/special-ad-category/, consultado 2026-07-29).
Los valores del enum son `HOUSING`, `EMPLOYMENT`, `FINANCIAL_PRODUCTS_SERVICES`, `ISSUES_ELECTIONS_POLITICS`, `NONE`.

Lo que la API **impone** cuando la categoría es `HOUSING` (citas de la propia doc):

| Palanca | Restricción impuesta |
|---|---|
| Edad | *"Options are generally fixed to include ages 18 through 65+"* — el anunciante no elige edad. |
| Género | *"Specific gender cannot be chosen."* `genders` cae a todos los géneros. |
| Radio geográfico | *"Location selection must include all areas equal or larger than 15 mile or 25 kilometer radius for the US and Canada, and 15 kilometer radius for Europe."* |
| Exclusión geográfica | *"Location exclusion is not supported."* |
| Tipos de ubicación prohibidos | `subcity`, `neighborhood`, `metro_area`, `small_geo_area`, `subneighborhood`, `electoral_district`, **`zips`**. |
| Segmentación detallada | *"Behavior and Demographic targeting, Interest exclusion, Detailed targeting exclusion"* no permitidos. |
| Lookalikes | *"Lookalike audiences are unavailable for housing, employment, and financial products and services ads."* |

**Y no hay puerta trasera:** las *Special Ad Audiences*, que durante un tiempo fueron el sustituto de los lookalikes,
**fueron eliminadas por completo** como parte del acuerdo con el DOJ `[S]` — Meta confirma haber
*"discontinued the use of Special Ad Audiences"* (https://about.fb.com/news/2023/01/an-update-on-our-ads-fairness-efforts/,
consultado 2026-07-29). Hoy un anunciante inmobiliario no tiene ningún mecanismo de audiencia similar.

Encima corre el **Variance Reduction System (VRS)** `[P/S]`: desplegado en EE. UU. para vivienda en **enero de 2023**
y extendido a empleo y crédito en **octubre de 2023**, derivado del acuerdo con DOJ/HUD de **junio de 2022**. El VRS
mide la distribución demográfica agregada de quien *efectivamente vio* el anuncio y la compara con la audiencia elegible,
reajustando la entrega. Es decir: **incluso la entrega, no solo la segmentación, está fuera del control del anunciante.**

Nota de enforcement `[S]`: múltiples fuentes del sector coinciden en que Meta **clasifica anuncios de vivienda
automáticamente** y aplica la categoría aunque el anunciante no la haya seleccionado, con rechazo o acción sobre la
cuenta como consecuencia. No lo pude confirmar contra doc primaria de Meta, así que queda `[S]` — pero la dirección
del enforcement no está en disputa.

### 2.2 Google: la misma restricción, misma dirección, desde antes

`[S]` Desde **octubre de 2020** Google prohíbe segmentar anuncios de vivienda, empleo y crédito por **género, edad,
estado parental, estado civil y código postal**; aplica a anunciantes que apuntan a EE. UU. y Canadá, en Google Ads,
SA360 y DV360, y en **todos los formatos y canales** (búsqueda, display, vídeo)
(https://support.google.com/adspolicy/answer/9997418, https://blog.google/technology/ads/upcoming-update-housing-employment-and-credit-advertising-policies/).

**Lo relevante no es cada plataforma por separado, sino que las dos grandes se movieron en la misma dirección.**
No hay canal de pago mainstream donde una inmobiliaria conserve segmentación fina. No es un problema de vendor: es el piso del nicho.

### 2.3 La consecuencia estratégica (aquí está la oportunidad, no en el compliance)

La cadena es corta y dura:

1. Se confiscó la precisión de **segmentación**. Nadie puede apuntar mejor que su competidor: todos están limitados al mismo mínimo de 15 millas, sin ZIP, sin edad, sin lookalikes.
2. Cuando la segmentación se iguala por decreto, **la única palanca de rendimiento que queda es el creativo**. La relevancia tiene que viajar dentro del contenido, porque ya no puede viajar en el targeting.
3. Eso desplaza valor y presupuesto desde *comprar audiencia* hacia *producir y entender contenido* — y hacia el orgánico, donde la distribución la decide la señal de interés del contenido y no una declaración del anunciante.

**Advertencia de honestidad intelectual:** el paso 3 suena a que valida la tesis de Qualify ("leer el contenido"), y por eso
hay que decir en voz alta lo que *no* implica. Que el creativo sea la palanca dominante favorece, en primer lugar, a quien
**produce y testea** creativos — no a quien los *escucha*. Qualify escucha. Ese es un hueco, no una confirmación.
Se recoge explícitamente en la tesis T-4 de la §6, que argumenta en contra del rumbo actual.

### 2.4 El giro que sí es de fuente primaria y casi nadie modela: la FHA alcanza el contenido orgánico

Aquí está el hallazgo con más filo de esta sección, y es `[P]`.

**24 CFR § 100.75** (https://www.law.cornell.edu/cfr/text/24/100.75, consultado 2026-07-29) declara ilegal
*"make, print or publish, or cause to be made, printed or published, any notice, statement or advertisement"*
que indique preferencia o discriminación. Y su alcance es explícitamente amplio:

- Cubre *"all written or oral notices or statements"* — **no solo publicidad pagada**.
- Prohíbe usar *"words, phrases, **photographs, illustrations, symbols** or forms"* que sugieran que una vivienda está disponible o no disponible para determinados grupos.
- Incluye *"flyers, brochures, ... signs, banners, posters, billboards or any documents"*.

Léase eso contra el formato dominante hoy: **un Reel de un agente inmobiliario es, jurídicamente, un anuncio** — y su
banda sonora hablada, su texto en pantalla y sus imágenes están todos dentro del alcance del reglamento. La frase
improvisada a cámara ("ideal para familias", "zona muy tranquila, gente como uno") no pasa por ningún filtro:
no hay revisión de plataforma para el orgánico, porque las Special Ad Categories son política **de anuncios**.

Y el riesgo es accionable por terceros `[S]`: pueden demandar tanto organizaciones de fair housing como los propios
lectores del anuncio discriminatorio. Además, la NAR extendió el **2020-11-13** el Artículo 10 de su Código de Ética
a discurso y conducta discriminatorios **fuera** de la práctica inmobiliaria del miembro
(https://www.nar.realtor/fair-housing-act) — el perímetro de responsabilidad se amplió, no se estrechó.

**Por qué esto importaría para una tesis de oportunidad —en EE. UU.:** existe una superficie de riesgo que (a) crece con
el formato que más crece (vídeo corto hablado), (b) vive en **audio, imagen y texto** — los tres modos que lee la cascada,
(c) **no** está cubierta por el enforcement de plataforma, y (d) el sustituto actual es la memoria del agente sobre una
lista de palabras prohibidas.
**Pero el comprador que paga está en Uruguay, y nada de este párrafo le vincula.** Ver §2.5 y la degradación de T-1 en la §6.

### 2.5 La inversión: para este comprador la presión no está en la salida publicitaria, sino en la ENTRADA de datos

Éste es ahora el hallazgo estructural real de la sección, y es más consecuente que el original — porque no toca lo que
el cliente *anuncia*, sino lo que Qualify *ingiere*.

`[S]` **Uruguay tiene un régimen de protección de datos de grado europeo** (fuentes concordantes consultadas 2026-07-30:
https://www.gub.uy/agencia-gobierno-electronico-sociedad-informacion-conocimiento/comunicacion/noticias/complete-sus-datos-ley-18331-valorada-por-union-europea,
https://www.recordinglaw.com/world-laws/world-data-privacy-laws/uruguay-data-privacy-laws/):

- **Ley 18.331** de Protección de Datos Personales y acción de *habeas data* (2008-08-11), con autoridad de control propia, la **URCDP** (dentro de AGESIC, Presidencia).
- **Decisión de adecuación de la UE 2012/484/UE (2012-08-21), reafirmada el 2024-01-15** tras la primera revisión periódica de la era GDPR. Uruguay fue además el primer Estado no europeo en adherirse al **Convenio 108** del Consejo de Europa y el primero de América en ratificar el **Convenio 108+**.
- Reformas relevantes: **Decreto 64/020** (responsabilidad proactiva, **DPO**, notificación de brechas), **Ley 19.924** (datos **biométricos** y **evaluaciones de impacto**), **Ley 20.075**.
- Obligación de **registrar las bases de datos** ante la URCDP.

**Por qué esto es exactamente el problema de Qualify y no un detalle jurídico ajeno.** El producto consiste en **leer
contenido primario de terceros**: vídeo, audio y comentarios de personas que **no son clientes del tenant y no han
consentido nada**. En EE. UU. eso vive en una zona gris cómoda. Bajo un régimen con adecuación europea, no: hay
base de licitud que justificar, derechos de acceso y supresión que atender, registro, y —si en algún momento se
analizan rostros o voz de forma identificante— la capa **biométrica** de la Ley 19.924, con evaluación de impacto.

Se dice con el nivel de certeza que corresponde: **esto es una lectura jurídica que yo no estoy cualificado para
cerrar, y va tier `[S]`.** No afirmo que el producto sea ilícito en Uruguay. Afirmo algo más acotado y más útil:
**el eje regulatorio que decide la viabilidad de este producto para este comprador es la protección de datos en la
ingesta, no la política publicitaria en la salida** — y ese eje no aparece en ningún documento del proyecto.

**Dos consecuencias, una mala y una buena, y las dos son reales:**

- **Mala (riesgo):** la tesis central de Qualify —"leer el contenido, no el perfil"— es *más* pesada legalmente en la
  jurisdicción del cliente que paga que en la que se diseñó implícitamente. Es un riesgo de producto, no de compliance
  administrativo. Se formula como tesis **T-6** en la §6, con su falsador.
- **Buena (ventaja, y honestamente derivada):** los activos que la §4.3 identificó como no-commoditizables —procedencia
  (`source_id` + `pipeline_version`), aislamiento por `tenant_id` con RLS, custodia de credenciales en un rol separado—
  son **precisamente** lo que un régimen de este tipo exige poder demostrar. No es una racionalización a posteriori:
  un régimen con derecho de supresión necesita saber de qué fuente derivó cada señal para poder borrarla, y eso es
  literalmente lo que ya está implementado y verificado en la §1.1.

---

## 3. Dónde quema presupuesto de marketing una inmobiliaria hoy

> **Encuadre obligatorio:** todo lo de esta sección es **ahorro del comprador**, no ahorro nuestro. Es la métrica que
> el propio agente ya mide (o puede medir en un extracto de tarjeta), y por eso su disposición a pagar es legible.
> **Advertencia de calidad de fuente:** gran parte del dato público de costes en este nicho vive en blogs de
> proveedores que venden la alternativa. Va etiquetado `[S]` y con esa reserva explícita. **No he inventado ningún número
> y no he promovido ninguno a `[P]` por conveniencia.**
>
> ### ⚠ ADVERTENCIA DE GEOGRAFÍA Y DE IDIOMA DE BÚSQUEDA (2026-07-30)
> **Toda esta sección se investigó en inglés y describe el mercado estadounidense. El comprador que paga está en
> Uruguay.** Zillow, Realtor.com y NAR **no operan en Uruguay ni en Colombia**, y `gtm` verificó que **no existe MLS
> en ninguno de los dos países**: el hueco lo ocupan portales privados (**InfoCasas, Gallito, Fincaraíz,
> Metrocuadrado, MercadoLibre**) que **venden exposición, no datos cooperativos de listing**.
>
> Lo declaro en lugar de extrapolarlo en silencio. **Qué sobrevive y qué no:**
> - **NO transfiere:** las cifras de coste por lead de Zillow, los datos de NAR sobre cómo se elige agente, y los rangos de precio de producción/agencia. Son de otro mercado.
> - **Sí transfiere, como hipótesis a verificar y no como hecho:** la *mecánica* de un portal que vende el mismo lead a varios agentes, que es una propiedad del modelo de negocio "vender exposición" y no de la geografía. **`[H]` — no verificada para InfoCasas/Gallito/Fincaraíz.**
> - **Experimento más barato:** preguntar al cliente uno qué paga a InfoCasas/Gallito, si el lead le llega en exclusiva, y cuántos agentes compiten por él. Una conversación, y produce dato `[P]` del mercado que importa.

### 3.1 Portales de leads: el agujero grande, y su mecánica

`[S]` El rango reportado con más consistencia para Zillow Premier Agent es **~$20–$100 por lead**, con mercados
calientes (SF, NYC) reportando **$450–$500 por lead**; gasto mensual desde ~$1.000 hasta cinco cifras
(https://theclose.com/zillow-premier-agent-worth-cost/, https://www.housingwire.com/articles/zillow-premier-agent-cost/, consultados 2026-07-29).

Pero el precio por lead **no es el gasto que duele**. Los dos mecanismos que lo son:

1. **El mismo lead se vende a varios agentes.** El modelo es de cuota de voz por código postal: comprar un 25% de
   share significa que ~1 de cada 4 consultas se enruta al comprador y las otras 3 van a competidores **que también
   están pagando por ellas** `[S]`. Es decir, el portal cobra varias veces por el mismo comprador de vivienda, y
   el coste efectivo por *cita conseguida* se dispara muy por encima del coste por lead nominal.
2. **La conversión es de un solo dígito bajo** `[S]`, con reportes de agentes de alto gasto por debajo del 2%.

**El sesgo de este dato es importante y lo declaro:** las quejas más ruidosas vienen de agentes individuales; los
equipos grandes con personal dedicado a llamar en caliente sí hacen funcionar el volumen `[S]`. O sea: **el portal no
vende leads, vende el derecho a competir por una llamada rápida.** Quien tiene músculo de seguimiento gana; quien no,
subsidia a quien sí. Esa es la asimetría real, no "los leads son malos".

### 3.2 La reformulación que cambia dónde está el dinero mal puesto

Aquí es donde el gasto en portales se ve como lo que es. Datos de NAR, *2025 Profile of Home Buyers and Sellers*
(periodo julio 2024–junio 2025):

- `[P]` **88% de los compradores** compraron a través de un agente o bróker; **91% de los vendedores** usaron agente
  — el porcentaje de vendedores más alto registrado, con el FSBO en un mínimo histórico del **5%**
  (https://www.nar.realtor/blogs/economists-outlook/top-10-takeaways-from-nars-2025-profile-of-home-buyers-and-sellers, consultado 2026-07-29).
- `[S]` De cómo **eligen** a ese agente: **43% por referido** y **18% un agente con el que ya habían trabajado**;
  en vendedores, **66%** por referido o agente repetido (reportado sobre el mismo informe NAR; no pude confirmar el
  desglose exacto contra la página de NAR, así que se queda en `[S]`).

Puestos juntos: **la búsqueda de vivienda es digital, pero la elección de agente es social.** El portal monetiza el
momento en que alguien mira casas —donde hay volumen y ninguna decisión— mientras que la mayoría de la selección de
agente ocurre en un canal de confianza que el portal no toca. Comprar leads de portal es **comprar atención en el
momento equivocado del embudo**, y hacerlo en subasta contra tres competidores.

El corolario, que es el que interesa: **el activo que decide el negocio es la reputación y la red, y hoy nadie la
instrumenta.** Un agente no tiene forma de saber quién habla de él, quién lo recomendó, o qué contenido suyo generó
la conversación que acabó en referido. Sabe exactamente lo que gastó en Zillow y no sabe nada de lo que le trajo el 61%.

### 3.3 Producción de contenido y agencia

`[S]` Rangos reportados (blogs de proveedores del sector, consultados 2026-07-29):
vídeo de listing estándar **~$300–$1.000** por propiedad, subiendo por encima de $1.000 en pieza cinematográfica
(https://homejab.com/how-much-do-real-estate-videos-cost/); retainer de agencia de social media
**~$500–$3.000/mes**, y **$1.500–$4.000+/mes** en servicio completo
(https://www.dmrmedia.org/blog/real-estate-marketing-agency-pricing).
Como referencia de tamaño de bolsillo, el benchmark que repite el sector es **5–10% del ingreso bruto por comisiones**,
subiendo a 15–20% en agentes que compiten fuerte `[S]` (https://www.tomferry.com/blog/real-estate-marketing-budget/).

**Lo que estos números no dicen, y es lo que importa:** el gasto en producción es *por pieza* y no está atado a ningún
resultado observado. El agente paga por que exista el vídeo. Nadie le dice si el vídeo funcionó, qué parte funcionó,
ni si la frase que improvisó a cámara le acaba de crear el pasivo legal de la §2.4. **El desperdicio aquí no es el
precio de la pieza: es que la pieza se produce a ciegas y se evalúa a ojo.**

### 3.4 Herramientas redundantes

`[H]` Hipótesis, no verificada aún: el stack típico de una inmobiliaria pequeña acumula CRM + portal(es) +
programador de publicaciones + herramienta de email + herramienta de vídeo/tour, con solapamiento entre ellas y sin
ninguna que cruce "qué publiqué" con "qué conversación generó" con "qué lead entró". No tengo evidencia de campo
para afirmarlo como hecho.
**Experimento más barato que lo resuelve:** pedirle al cliente uno la lista literal de suscripciones de software de
marketing con su importe mensual. Es una pregunta, no un estudio, y produce un dato `[P]` de un caso real.
Coordinar con `sales-consultant`, que ya está hablando con la demanda.

---

## 4. Capacidades de IA recién abaratadas y qué commoditizan

> El encargo pedía explícitamente que si algo de la ventaja de Qualify se volvió gratis o trivial en otro lado, ese
> es el hallazgo del día y no debo suavizarlo. **Lo es. Y no lo suavizo.**

### 4.1 El hecho: la comprensión nativa de vídeo (audio + imagen en una sola llamada) ya es commodity

`[P]` La Gemini API acepta un vídeo directamente y lo procesa entero
(https://ai.google.dev/gemini-api/docs/video-understanding, consultado 2026-07-29):

- Entrada por File API (**hasta 20 GB** en pago, 2 GB gratis), inline (<100 MB) o **URL de YouTube**.
- *"the model processes both streams together"* — **muestrea a 1 FPS y procesa el audio simultáneamente**, extrayendo *"both audio and visual details"*.
- Sabe *"describe, segment, and extract information from videos, answer questions about video content, and refer to specific timestamps"*, con marcas de tiempo `MM:SS`.
- Coste en tokens: **~300 tokens por segundo** de vídeo a resolución por defecto, **~100 tokens/segundo** en baja. Hasta 1 hora (3 h en baja).

`[P]` Precio (https://ai.google.dev/gemini-api/docs/pricing, consultado 2026-07-29): Gemini 2.5 Flash-Lite cobra
**$0,10 / 1M tokens** de entrada de texto/imagen/**vídeo** y $0,40 de salida. Hay tier gratuito.

**Aritmética directa sobre esas tarifas publicadas** (es un cálculo mío a partir de fuentes `[P]`, no un dato de mercado):
un Reel de 30 segundos ≈ 9.000 tokens a resolución normal ⇒ **≈ $0,001 por Reel, en UNA llamada**, incluyendo
descripción visual, transcripción, marcas de tiempo y cualquier clasificación que quepa en el prompt.

### 4.2 Qué commoditiza esto, exactamente, de Qualify

Comparación contra lo verificado en §1, no contra los docs. La cascada de Qualify hoy es:

`ffmpeg (keyframes+audio)` → `siglip2 filter` → `Qwen3-VL por frame` (proveedor único `featherless-ai`) → `whisper-large-v3-turbo` (`provider="auto"`) → `robertuito sentiment`

Cinco etapas, cuatro modelos, dos proveedores externos sin control, un plano de artefactos en R2 (que aún no se ha
ejercitado) y una dependencia de GPU en el horizonte. **Todo eso lo hace una sola llamada de Gemini, más barata y con
mejor cobertura temporal.**

> **Corrección de mecanismo (2026-07-30).** La primera redacción decía que la cascada "hoy transcribe todo" por no
> implementar el gate F1. **Es incorrecto y el error real es peor.** Verificado contra
> `packages/models/src/qualify_models/filter_decision.py` y `NOTES_qua23_filter_decision_rule.md` (datasci, 2026-07-29):
> la regla por defecto `UNCALIBRATED_LEGACY_RULE` usa `threshold = 0.22`, un número elegido con intuición **softmax**
> para un modelo que **no tiene cabeza softmax** (SigLIP puntúa cada etiqueta con `sigmoid` y este checkpoint trae un
> `logit_bias ≈ -16.77`). Cita del propio docstring: *"The filter therefore **discards 100% of candidates and makes the
> vision stage unreachable**."*
> Y la regla **no está elegida a propósito**: QUA-23 queda **abierta, "honestly blocked, not abandoned"**, porque el
> golden set contiene **un solo ítem, positivo, con cero negativos** — no hay datos etiquetados para fijar un umbral.
> **Formulación correcta: no hay ningún gate cableado en ninguna de las dos direcciones; la etapa que debe decidir está
> sin resolver.** No debilita el argumento —sigue siendo frágil, sin calibrar y sin ejecución fuera de tests
> `integration`— pero el mecanismo importa y estaba mal descrito.

Dato interno que agrava la comparación: el propio modelo de coste de Qualify
(`packages/models/src/qualify_models/eval/fase0_cost.py:44`) asume **`VIDEO_TOKENS_PER_FRAME = 1600`**.
**Atribución precisa (corregida 2026-07-30):** esa constante está modelada sobre el coste de imagen a resolución
estándar de **la API de Anthropic** (`NOTES_fase0_agentive_layer.md:249`); **no** es una constante de Gemini. La
comparación *por frame vs. por segundo con audio incluido* se sostiene igual, pero debe citarse como **modelo de coste
basado en Anthropic**, no como cifra propia de Gemini. Con esa salvedad: **1.600 tokens por frame** frente a
**300 tokens por segundo** que ya incluyen el audio. La arquitectura frame-a-frame no solo tiene más piezas: es más
cara por unidad de información.

**Conclusión sin adornos:** *"la cascada multimodal"* aparece en `CLAUDE.md` como parte del **núcleo diferenciado**
(«build»). Contra el mercado de 2026-07-29 **ya no lo es**. Es infraestructura commodity, y el propio principio
estratégico del proyecto —"comprar lo commodity, construir lo diferenciado"— ahora apunta en la dirección contraria a
la que apunta el código. Esto es un cambio de clasificación, no un ajuste de vendor.

### 4.3 Qué NO commoditiza (y aquí sí queda ventaja real)

Ser honesto en la mala noticia obliga a serlo también en la buena. Gemini **no** resuelve:

1. **La adquisición del contenido.** Acepta URLs de YouTube, no de TikTok ni de Instagram. Alguien tiene que conseguir
   los bytes legítimamente. Ahí viven los dos activos más reales de Qualify según §1.1: el módulo `connections`/OAuth
   (18 archivos, el más maduro del repo) y el scraper con envelope versionado.
2. **La procedencia y el versionado.** `source_id` + `pipeline_version` propagados por toda la cascada, RLS por
   `tenant_id`, custodia de credenciales en un rol de Postgres separado. Un modelo te da una respuesta; no te da una
   cadena de custodia sobre esa respuesta. Para un caso de uso con exposición legal (§2.4) esa distinción **es** el producto.
3. **El corpus longitudinal.** Una llamada es un evento. El valor está en la serie temporal sobre la misma cuenta y sus
   competidores. Eso es esquema y disciplina de ingesta, no inteligencia de modelo.
4. **El acto**, no la observación. Publicar, responder, enrutar. `0003_publishing`/`0004_inbox` existen en disco.

**Lectura estratégica:** la ventaja se movió **de la interpretación hacia la adquisición y la procedencia**. Eso
*refuerza* la tesis de fuente primaria ("leer el contenido, no el perfil") y a la vez **invalida la idea de que
construir el intérprete sea una ventaja**. Las dos cosas a la vez. Ver tesis **T-4**.

### 4.4 Riesgo que este cambio no reduce sino que agrava

- **Proveedor único hardcodeado** (`providers.py:128`, `provider="featherless-ai"`) para el VLM, y `provider="auto"`
  para ASR. Se sostiene una dependencia frágil para hacer, más caro, algo que un proveedor de primera línea hace por $0,001.
- **Cero cobertura en CI** de la cascada (§1.3c). Se mantiene un activo sin red de seguridad cuyo valor diferencial acaba de caer.
- `[H]` **El sentimiento de 3 clases de `robertuito` es el eslabón más débil para inmobiliario.** La señal que importa
  no es polaridad, es intención (¿quiere vender?, ¿se muda?, ¿está comparando agentes?) y riesgo (§2.4). Ya está
  documentado internamente que el modelo de polaridad no carga señales de intención
  (`packages/models/NOTES_pain_signal_feasibility.md`). Un LLM barato con un prompt hace esto hoy, sin checkpoint nuevo.
  **Validación más barata:** 100 comentarios etiquetados a mano, robertuito vs. un prompt de Flash-Lite, medir en el
  arnés de evaluación que **ya existe** (`packages/models/src/qualify_models/eval/harness.py`).

---

## 5. Señales de innovación

> ### ⚠ SESGO DE IDIOMA DE BÚSQUEDA (declarado 2026-07-30)
> Todo lo de esta sección se buscó **en inglés** y por tanto describe el ecosistema **EE. UU./Europa**. El comprador
> está en Uruguay. **No he encontrado —ni busqué adecuadamente— señales de innovación del proptech hispanohablante**
> (InfoCasas, Properati, La Haus, Habi, Tokko Broker, Wasi). Es un hueco de cobertura, no una ausencia de mercado, y
> **la diferencia entre esas dos cosas es exactamente lo que no se debe suponer.**
> **Validación más barata:** repetir esta sección con búsquedas en español sobre changelogs y rondas de InfoCasas,
> Tokko Broker, Wasi, La Haus y Habi. Horas de trabajo, y es lo que decide si Luxury Presence/Lofty son siquiera el
> conjunto competitivo correcto para este comprador.

### 5.0 Corrección: "agentive AI sobre social para inmobiliario" NO es campo vacío

`[S]` Hallazgo de `sales` (`docs/demanda-ventas-inmobiliario.md` §3.1, fuentes rismedia.com 2026-07-28 y
lofty.com 2026-07-29): **Lofty lanzó hace un día** una suite agentiva —*Social Agent*, *Social Studio*, *Blast*,
*Cowork*— para inmobiliario. **Ninguna tesis de este documento puede afirmar que "nadie está haciendo nada aquí".**

Dos matices que hacen el hueco **más estrecho y más específico**, no inexistente:

1. Según lo que `sales` pudo leer, la suite de Lofty opera sobre **contenido de primera parte**: listings propios,
   contactos propios, marca propia. **No hay indicio de lectura de contenido primario de terceros** — el vídeo, el
   audio o los comentarios de alguien que no eres tú. Si eso se sostiene, **el whitespace real no es "IA para social
   inmobiliario" sino específicamente *escuchar contenido primario que no te pertenece***, que es literalmente la
   tesis declarada de Qualify. **Debe verificarse contra los materiales de Lofty antes de apoyarse en ello.**
2. `[S]` Lofty vende su *"What Needs You Now"* como **human-in-the-loop**, y lo presenta como argumento de venta, no
   como disculpa. Es decir: **la postura "asistido, no autónomo" de la ADR 21 es consenso de categoría**, no una
   limitación que haya que justificar ante un comprador.

### 5.0-bis El pipeline en dirección contraria: listing-to-video **no es un competidor**

`[S]` `gtm` verificó que la categoría estadounidense de *listing-to-video* / sindicación / IDX (Reel-E, Stager AI
exportan **hacia** el MLS; BetterSpace ingiere enlaces de Zillow/Rightmove) **queda fuera de juego en LATAM por la
ausencia de MLS**. Pero el punto importante es estructural, no geográfico: **esa categoría corre la tubería en la
dirección opuesta** — *produce* vídeo a partir de datos estructurados de listing, mientras que Qualify *lee* vídeo
para extraer datos. **No es un competidor; solo lo parece.** Conviene decirlo explícitamente porque un mapa de
competidores que los incluya sobreestima la saturación del espacio.

### 5.1 La señal que más debería preocupar: Luxury Presence, enero 2026

`[S]` (múltiples fuentes concordantes, consultadas 2026-07-29: https://www.inman.com/2026/01/08/does-luxury-presences-37m-series-c-forecast-a-big-year-for-proptech-investment/,
https://news.crunchbase.com/real-estate-property-tech/luxury-presence-real-agent-platform-funding-jade-mills/,
https://www.builtinaustin.com/articles/luxury-presence-37m-series-c-20260114)

- **$37M en enero de 2026**: $22M de equity liderados por **Bessemer** (inversor repetido) + $15M de deuda de **J.P. Morgan**.
- **Distribución ya instalada: >17.000 negocios inmobiliarios y >87.000 agentes**, incluyendo ~30% de los top agents del ranking WSJ RealTrends.
- El uso declarado de los fondos: lanzar **Presence CRM**, *"AI-powered"*, con despliegue **desde febrero de 2026** — automatiza el trabajo manual del CRM: **identificar el mejor momento para contactar y redactar mensajes personalizados a través de varios canales**.

**Por qué es la señal del apartado y no una nota al pie.** Esa descripción —CRM agentivo que decide a quién contactar y
redacta la acción— **es la misma forma de producto que describe el README de Qualify**, en el mismo nicho, con
87.000 agentes de distribución ya adquirida y capital fresco. Una ronda dirigida por un inversor repetido más deuda de
un banco no es una apuesta exploratoria: es escalar algo que ya funciona.

**Y por qué no es una sentencia.** Lo que Presence CRM orquesta, según su propia descripción, es **la base de datos del
agente**: relaciones, datos y experiencias de cliente que ya están dentro del CRM. **No hay indicio de que lea contenido
primario externo** (vídeo, audio, comentarios de terceros). Es decir: se está cerrando el plano de la *acción sobre lo que
ya sabes*, no el de *enterarte de lo que no sabes*. El hueco sigue en la observación de fuente primaria; **la capa de
acción y de CRM, que Qualify también aspira a ocupar, está siendo tomada por alguien con distribución.**
Consecuencia directa para el scoring: **construir CRM/acción genérica para inmobiliario es competir de frente contra
$37M y 87.000 agentes.** Eso debe empujar hacia abajo cualquier tesis cuyo núcleo sea "CRM para inmobiliarias".

### 5.2 Contexto de financiación del sector

`[S]` El capital proptech en 2026 se está concentrando en IA aplicada, con rondas concretas reportadas en el año:
Cambio ($18M Serie A, enero 2026, gestión de activos con IA), Xpanner ($18M Serie B, mayo 2026), Rebar ($14M, marzo 2026),
Smart Bricks ($5M pre-seed liderado por a16z). No cito totales agregados de mercado: los datasets públicos que los
reportan no son consistentes entre sí y **prefiero un vacío a un número que no puedo sostener**.

### 5.3 Formato: el vídeo corto es el centro, pero el dato de adopción está mal soportado

`[S]` La prensa del sector converge en que el vídeo corto es el formato dominante del marketing inmobiliario en 2026
(p. ej. Inman, 2026-06-09, https://www.inman.com/2026/06/09/short-form-videos-that-engage-clients-in-30-seconds-or-less/).
Circula una cifra de **"63% de los agentes ya usa vídeo"** en blogs del sector; **no la pude rastrear hasta una fuente
primaria y por tanto no la uso como base de ninguna tesis.**
**Experimento más barato que lo resuelve:** contar, sobre una muestra aleatoria de N=100 perfiles públicos de agentes en
un mercado concreto, cuántos publicaron ≥1 Reel en los últimos 30 días. Es medición directa, no encuesta, y **Qualify ya
tiene el scraper que lo hace** (`packages/scraper/`, verificado en §1.1). Coste: horas, no dinero.

### 5.4 Ofertas de empleo: hueco declarado, no rellenado con humo

El encargo pedía explícitamente ofertas de empleo como indicador adelantado, y tiene razón en que lo son: una lista de
responsabilidades es una lista de requisitos que alguien ya está dispuesto a pagar. **No conseguí acceso a un corpus de
ofertas reales** (los buscadores devolvieron blogs de tendencias en lugar de puestos). **No voy a inferir el contenido de
ofertas que no he leído.** Queda como hueco declarado.
**Validación más barata:** 20 ofertas de "social media manager" / "marketing coordinator" en brokerages, extraídas de
LinkedIn o Indeed, y contar cuántas piden explícitamente (a) producir vídeo corto, (b) monitorizar/reportar
conversación o reputación, (c) revisar compliance de fair housing. La proporción (b) y (c) frente a (a) es una medida
directa de si el mercado ya paga por escuchar o solo por producir — que es justo la pregunta que decide T-1 y T-4.

---

## 6. Tesis de oportunidad

> Siete tesis. **Una recomienda declinar (T-2), una argumenta que el rumbo actual está mal clasificado (T-4), una se
> entrega con la defensa explícitamente débil (T-3) y una describe un riesgo que podría invalidar el producto (T-6).**
> Se dice por delante porque el encargo advertía —con razón— que si todas endosaran el roadmap, eso sería señal de un
> brief dirigido. No es el caso. La adyacencia se puntúa contra la **§1 (disco)**, nunca contra `CLAUDE.md`.
>
> ### ⚠ REVISIÓN 2026-07-30 — el comprador es uruguayo, y eso reordena la lista
>
> La primera versión (2026-07-29) se escribió sobre un comprador estadounidense implícito. Corregido:
>
> | Tesis | Estado tras la corrección |
> |---|---|
> | **T-1** fair housing | **DEGRADADA de 1.ª a marginal.** Su base jurídica (FHA / 24 CFR §100.75) es derecho de EE. UU. y **no vincula al cliente que paga**. Se conserva como oportunidad *de otro mercado*, no de éste. |
> | **T-2** referidos | Sin cambio en la recomendación (declinar); su sustento cuantitativo era de NAR y **tampoco transfiere**, lo que la debilita aún más. |
> | **T-3** Reel medido | **Sube**, por eliminación y porque no depende de ninguna regulación. Sigue sin foso. |
> | **T-4** commoditización | **Sin cambio y sigue siendo la más importante.** Es independiente de la geografía. Falsador (a) corregido: hoy **no se puede correr**. |
> | **T-5** brokerage | **Sube a primera**, reforzada por la estructura económica real del comprador. |
> | **T-6** protección de datos | **NUEVA. Riesgo, no oportunidad.** Sale de la §2.5 y es el eje regulatorio que de verdad decide la viabilidad aquí. |
> | **T-7** sesgo geográfico del research | **NUEVA.** Hallazgo sobre el proceso del propio proyecto. |
>
> **Lección de método, y va al ledger:** la tesis mejor puntuada de la primera ronda descansaba sobre un régimen
> regulatorio del país equivocado. No fue un fallo de investigación —las fuentes de EE. UU. eran primarias y
> correctas— sino de **no verificar la geografía del comprador antes de puntuar adyacencia**, exactamente el mismo
> tipo de error que la §1 existe para prevenir en el eje técnico. **Verificar quién paga es parte de la due
> diligence, no un dato de contexto.**

---

### T-1 — Revisión de riesgo fair-housing sobre contenido orgánico multimodal *(DEGRADADA: solo mercado EE. UU. — no aplica al cliente que paga)*

> **Degradación (2026-07-30).** Todo lo de esta tabla sigue siendo correcto **para EE. UU.** y se conserva por eso.
> Pero su base jurídica es la Fair Housing Act, **derecho estadounidense que no vincula a una inmobiliaria uruguaya**,
> y la restricción de segmentación de Meta admite **opt-out** fuera de EE. UU./Canadá/Europa (§2, corrección).
>
> ### Verificación de jurisdicción solicitada por `gtm` — HECHA, y el resultado cierra la tesis
>
> `gtm` pidió (ADV3, §2.5 de su doc) comprobar si Uruguay o Colombia tienen un régimen equivalente de
> discriminación-en-publicidad-de-vivienda, advirtiendo con razón que dejarlo "sin verificar" haría que T-1 se leyera
> como validada para un comprador que no la tiene. **Comprobado el 2026-07-30. No lo tienen — no en la forma que
> T-1 necesita.** `[S]`
>
> | | EE. UU. (lo que T-1 requiere) | Uruguay | Colombia |
> |---|---|---|---|
> | Norma | FHA / **24 CFR §100.75** | **Ley 17.817** (2004) | **Ley 1482** (2011) |
> | Qué prohíbe | *"any notice, statement or **advertisement**"* que **indique una preferencia** | Declara de interés nacional la lucha contra la discriminación; crea una **Comisión Honoraria** que **propone políticas** | **Derecho penal**: quien *"arbitrariamente impida, obstruya o restrinja"* el ejercicio de derechos (prisión 12-36 meses + multa) |
> | Umbral | **Muy bajo** — basta con que el anuncio *sugiera* preferencia | n/a — no es régimen sancionatorio sobre anuncios | **Muy alto** — exige impedir/obstruir arbitrariamente, no insinuar |
> | Alcance sobre publicidad | **Explícito**, incluye *"photographs, illustrations, symbols"* | **No hallado** | **No hallado** como previsión publicitaria específica |
> | Quién acciona | Organizaciones de fair housing y **cualquier lector** del anuncio | Comisión honoraria (rol propositivo) | Fiscalía (vía penal) |
> | Industria de *testers* | Sí, establecida | No hallada | No hallada |
>
> **Conclusión.** Lo que hace comercializable a T-1 en EE. UU. no es que la discriminación sea ilegal —lo es en los
> tres países— sino la combinación de **umbral bajo + alcance explícito sobre el anuncio + legitimación activa amplia**,
> que convierte una frase descuidada en riesgo litigioso cotidiano. **Esa combinación no existe en Uruguay ni en
> Colombia.** Una vía penal por obstrucción arbitraria no genera demanda de revisión preventiva de Reels.
> Fuentes: https://www.law.cornell.edu/cfr/text/24/100.75, https://uruguay.justia.com/nacionales/leyes/ley-17817-sep-6-2004/gdoc,
> https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=44932 (consultadas 2026-07-30).
>
> **T-1 queda CERRADA para el cliente que paga — verificada, no meramente "sin confirmar".** Sobrevive solo como
> opción de expansión a EE. UU., donde el falsador que manda ya no es el de la tabla sino *¿tiene Qualify algún camino
> a un comprador estadounidense?* Hoy no lo tiene. **No gastar validación aquí.**
>
> **Y el experimento de tasa base que proponía queda retirado tal como estaba redactado** — ver §6.2, punto 3: se
> habría ejecutado sobre datos públicos estadounidenses y aplicado a un cliente uruguayo, que es exactamente la
> conflación que esta sesión existe para corregir.

| Campo | Contenido |
|---|---|
| **El cambio** | `[P]` **24 CFR § 100.75** prohíbe cualquier *"notice, statement or advertisement"* con preferencia discriminatoria y cubre expresamente *"words, phrases, **photographs, illustrations, symbols** or forms"*, aplicándose a *"all written or oral notices or statements"* — **no solo a publicidad pagada** (https://www.law.cornell.edu/cfr/text/24/100.75, consultado 2026-07-29). En paralelo, el formato dominante pasó a ser el vídeo corto **hablado y espontáneo** (§5.3), y las Special Ad Categories de Meta son política **de anuncios**: el orgánico **no pasa por ninguna revisión de plataforma** (§2). `[S]` NAR extendió el **2020-11-13** el Artículo 10 a conducta discriminatoria fuera de la práctica inmobiliaria (https://www.nar.realtor/fair-housing-act). |
| **El dolor** | El **designated broker** de una agencia con N agentes: cada agente publica bajo la marca, a cámara, sin guion y sin revisión previa. El riesgo es accionable por terceros —organizaciones de fair housing y los propios lectores del anuncio— `[S]`. El broker no tiene ni el inventario de lo publicado ni forma de revisarlo. **Verbalización: pendiente.** No he encontrado a brokers articulando este dolor en fuentes crudas; es el hueco de evidencia de esta tesis y por eso el falsador de abajo es el primero que hay que correr. |
| **Sustitutos actuales** | (a) **Nada** — el caso mayoritario. (b) La memoria del agente sobre una lista de "palabras prohibidas" (`exclusive`, `restricted`, `ideal para familias`...) `[S]`. (c) Formación anual de fair housing. (d) Seguro E&O, que paga *después*. **Por qué fallan:** una lista de palabras es un filtro léxico sobre texto escrito, y el riesgo hoy vive en **habla improvisada, texto en pantalla e imagen** — tres modos que ningún sustituto inspecciona. La formación anual no está presente en el momento de grabar. |
| **Señal de urgencia/tamaño** | *(vacío — no tengo cifra sostenible de incidencia ni de coste de litigio en este supuesto concreto, y no la invento.)* **Experimento que lo resolvería:** medir la **tasa base** ejecutando la cascada sobre ~200 Reels públicos de agentes reales y contando cuántos contienen lenguaje o imaginería potencialmente problemática. Si la tasa base es ≈0%, no hay problema que resolver y la tesis muere sin gastar una sola conversación. |
| **Adyacencia a Qualify** | **MEDIA.** *Reutiliza tal cual (verificado §1.1):* la cascada multimodal completa (transcripción + visión + texto son exactamente los tres modos del riesgo); la **procedencia** (`source_id` + `pipeline_version` propagados) — que en un caso con exposición legal deja de ser higiene y **pasa a ser el producto**: un dictamen sin cadena de custodia no sirve; `connections`/OAuth para ingerir el contenido del propio brokerage como first-party; el modelo multi-tenant con RLS. *No requiere:* ClickHouse (el volumen de N agentes × M posts/mes cabe holgadamente en Postgres) ni Celery, si se dispara por evento o bajo demanda en lugar de por monitoreo continuo. **Por qué NO es `alta`:** (i) el clasificador de riesgo FHA no existe — es un prompt, no un checkpoint nuevo, pero hay que construirlo y evaluarlo; (ii) el plano de objetos R2 está escrito pero **nunca ejercitado** y `boto3` ni siquiera está declarado (§1.3a); (iii) la cascada **no tiene cobertura en CI** (§1.3c), lo que es difícil de sostener bajo un caso de uso con consecuencia legal. |
| **Fase** | Vecina de **Parte 4-B** (cuentas conectadas, plano Postgres). Es la tesis **más adelantable de las cinco** porque puede vivir sin el camino crítico de Parte 3. Coste de adelantarlo: declarar `boto3` y ejercitar R2 contra un bucket real; construir + evaluar el clasificador; **quitar el marcador `integration` de la cascada** o crear un subconjunto que sí corra en CI. |
| **Qué la falsifica** | Cualquiera de estas dos, y basta con una: **(a)** la tasa base del experimento anterior sale ≈0% — el contenido real no contiene el riesgo que la teoría predice; **(b)** en 10 conversaciones con designated brokers / compliance officers, ninguno puede nombrar un incidente ni tiene proceso de revisión **y ninguno lo quiere** — entonces el dolor es un miedo de consultor, no del mercado. *(Ojo con el matiz: "no tienen proceso" es ambiguo; solo falsifica si además **no lo quieren**.)* |
| **Validación más barata** | El experimento de tasa base, **en este orden y antes de hablar con nadie**: 200 Reels públicos ya scrapeables con `packages/scraper/`, una pasada de la cascada, conteo manual de positivos sobre una muestra. Días, no semanas, y **cero dependencia de fundaciones ausentes**. |

---

### T-2 — Instrumentar el canal de referido *(recomendación: DECLINAR — se entrega documentada)*

| Campo | Contenido |
|---|---|
| **El cambio** | `[P]` NAR 2025 (periodo jul-2024/jun-2025): **88% de compradores y 91% de vendedores** operaron con agente, con el FSBO en mínimo histórico del 5%. `[S]` Del **cómo eligen**: 43% por referido + 18% agente repetido; 66% en vendedores. Simultáneamente (§2), la segmentación de pago quedó inutilizada por regulación. **Doble presión hacia el canal social/reputacional.** |
| **El dolor** | Real y nítido: el agente conoce al céntimo su gasto en portales (§3.1) y **no sabe absolutamente nada sobre el canal que le trae la mayoría de su negocio**. Está optimizando lo que puede medir en lugar de lo que le da de comer. |
| **Sustitutos actuales** | Campo "fuente del lead" en el CRM, rellenado a mano y mal; la pregunta "¿cómo nos conociste?"; y la memoria personal del agente. **Por qué fallan:** capturan el último toque y pierden la cadena; y en volúmenes bajos la memoria personal **funciona razonablemente bien** — lo cual es precisamente el problema de la tesis. |
| **Señal de urgencia/tamaño** | *(vacío.)* |
| **Adyacencia a Qualify** | **BAJA.** Esto es atribución y grafo de relaciones, no lectura de contenido primario. No reutiliza la cascada, que es el activo. Requiere un grafo cross-canal que la §1.2 confirma inexistente. **Y compite de frente con la §5.1:** Presence CRM despliega desde febrero de 2026 exactamente sobre este terreno, con $37M y 87.000 agentes de distribución instalada. |
| **Fase** | Fase 4/6 en el mapa actual. No hay forma barata de adelantarlo. |
| **Qué la falsifica** | Que en 10 entrevistas los agentes reconstruyan de memoria el origen de sus últimos 10 negocios sin esfuerzo. Si la memoria basta, no hay producto. **Predicción explícita: creo que es lo que pasará** en el rango de volumen del cliente uno. |
| **Validación más barata** | Esas 10 preguntas. Pero **la recomendación es no gastarlas aquí**: aunque la tesis se confirmara, la adyacencia sigue siendo baja y el competidor sigue teniendo 87.000 agentes. **Una oportunidad bien documentada que debemos declinar es un entregable válido, y esta lo es.** |

---

### T-3 — El Reel como unidad medida: "qué parte de mi vídeo funcionó" *(defensa débil, se dice por delante)*

| Campo | Contenido |
|---|---|
| **El cambio** | §2.3: confiscada la precisión de segmentación, **el creativo es la única palanca de rendimiento que queda** — y esto por decreto regulatorio, no por moda. §3.3: la producción se paga por pieza (`[S]` ~$300–$1.000/listing) **sin atarse a ningún resultado observado**. |
| **El dolor** | El agente paga por que el vídeo exista y no sabe si funcionó, ni **qué parte** funcionó. Las métricas nativas dicen *qué post* rindió, nunca *qué del post*: ni el gancho, ni la estructura, ni el encuadre, ni la duración del plano. |
| **Sustitutos actuales** | Analíticas nativas de Instagram/TikTok (gratis, y suficientes para el "qué"); la intuición del agente; el criterio de la agencia contratada, que es **juez y parte** — cobra por producir, no por acertar. |
| **Señal de urgencia/tamaño** | *(vacío. El "63% de agentes usa vídeo" que circula en blogs del sector no se pudo rastrear a fuente primaria; ver §5.3 y su experimento de conteo directo.)* |
| **Adyacencia a Qualify** | **MEDIA.** Reutiliza cascada + scraper + connections. Un agente individual con ~100 posts históricos cabe en Postgres, así que no bloquea contra la ausencia de ClickHouse; a escala de brokerage sí empieza a pedirlo. |
| **Fase** | Fase 2 (insights) traída hacia delante sobre el plano transaccional. |
| **Qué la falsifica** | Se muestra el análisis a 5 agentes y **ninguno cambia el siguiente vídeo**. Si no altera la conducta, es un informe bonito, no una herramienta. |
| **Validación más barata** | Hacerlo a mano para 3 agentes: 20 de sus Reels, análisis con una sola llamada de vídeo nativo (§4.1, ≈$0,001 cada uno), entregarlo en PDF, **y volver a los 30 días a comprobar si cambiaron algo**. El PDF es el producto falsable; no hace falta escribir producto. |
| **Por qué la defensa es débil, dicho sin adornos** | Es exactamente el *feature* que añade encima cualquier herramienta de producción de contenido que ya tenga la relación con el agente, y §4.1 dice que el análisis en sí cuesta ~$0,001. **Sin el activo de adquisición y la serie longitudinal, aquí no hay foso.** Se entrega porque el dolor es real, no porque la posición sea buena. |

---

### T-4 — *(TESIS INCÓMODA)* La ventaja se movió de **interpretar** a **adquirir y acreditar**: la clasificación actual del núcleo diferenciado es errónea

> Ésta argumenta que el rumbo actual está mal en un punto concreto. Va destacada y sin suavizar, como corresponde.

| Campo | Contenido |
|---|---|
| **El cambio** | `[P]` §4.1: la comprensión nativa de vídeo —imagen y audio **en la misma pasada**, con marcas de tiempo— es hoy una llamada de API a **~$0,001 por Reel de 30 s** (Gemini API docs + pricing, consultados 2026-07-29). `[S]` §5.1: la capa de CRM/acción del nicho acaba de recibir $37M y despliega desde febrero de 2026 sobre 87.000 agentes ya instalados. |
| **El dolor** | El de Qualify, y se nombra como tal. `CLAUDE.md` clasifica la cascada multimodal dentro del **núcleo diferenciado** ("build"). Contra el mercado del 2026-07-29 **ya no lo es**: es infraestructura commodity, y el propio invariante del proyecto —comprar lo commodity, construir lo diferenciado— **apunta en dirección contraria a la que apunta el código**. Peor: el modelo de coste interno asume `VIDEO_TOKENS_PER_FRAME = 1600` (`eval/fase0_cost.py:44`) frente a **300 tokens/segundo con audio incluido** del sustituto. Se sostienen cinco etapas, cuatro modelos, un proveedor **único hardcodeado** (`providers.py:128`, `featherless-ai`), un `provider="auto"` sin control en ASR y **cero cobertura en CI** (§1.3c) para hacer, más caro y más frágil, algo que un proveedor de primera línea hace por una milésima de dólar. |
| **Sustitutos actuales** | Una sola llamada a un modelo frontera. Ése es el sustituto, y hoy **no falla**: es más barato, más simple y con mejor cobertura temporal que la cascada propia. |
| **Señal de urgencia/tamaño** | *(vacío en términos de mercado. La señal es de coste de oportunidad de ingeniería, no de demanda.)* |
| **Adyacencia a Qualify** | **N/A — no es una oportunidad de mercado, es una reclasificación.** Lo que sí es adyacente es su consecuencia positiva: los activos que **no** se commoditizan (§4.3) son la **adquisición** (`connections`/OAuth, el módulo más maduro del repo con 18 archivos; el scraper con envelope versionado), la **procedencia y custodia** (RLS por `tenant_id`, rol `qualify_credential`, `pipeline_version`) y el **corpus longitudinal**. Nótese la ironía útil: **esto refuerza la tesis de fuente primaria ("leer el contenido, no el perfil") y a la vez invalida que construir el intérprete sea una ventaja.** Las dos cosas son ciertas simultáneamente. |
| **Fase** | Afecta transversalmente a Fase 1. |
| **Qué la falsifica** | Tres observaciones, cualquiera basta: **(a)** el arnés muestra que la cascada propia supera **materialmente** a una sola llamada nativa en contenido en español de este nicho; **(b)** a volumen real el coste se invierte a favor del self-hosting (la API escala lineal, la GPU se amortiza) — aritmética, no opinión, y depende de un volumen que hoy no existe; **(c)** una restricción contractual o de política de datos del proveedor frontera impide procesar contenido de terceros para este fin, en cuyo caso la cascada propia es necesaria **por razones legales, no de calidad**, y sigue siendo correcta construirla. **(c) es la más importante y sigue sin verificar**; además se cruza con T-6, porque bajo la Ley 18.331 la cuestión no es solo qué permite el proveedor sino qué transferencia internacional de datos personales está justificada. |
| **⚠ Corrección al falsador (a), 2026-07-30** | **Hoy ese experimento NO se puede correr, y eso es en sí mismo un hallazgo.** El golden set contiene **un solo ítem, positivo, con cero negativos** (`NOTES_qua23_filter_decision_rule.md` §3, verificado en disco). No se puede medir calidad comparada contra n=1. **La secuencia correcta invierte el orden: primero construir un golden set etiquetado, que es además el mismo bloqueo que mantiene QUA-23 abierta.** Un golden set desbloquea simultáneamente la calibración del filtro y este benchmark — es la pieza de trabajo con mayor apalancamiento de todo el paquete técnico, y no aparece priorizada en ningún sitio. |
| **Validación más barata** | Por orden real: **(1)** leer los términos de uso del proveedor frontera — minutos, y el falsador (c) puede cerrar la cuestión entera; **(2)** construir un golden set mínimo etiquetado (~100 ítems con positivos y negativos); **(3)** solo entonces, los dos brazos en `packages/models/src/qualify_models/eval/harness.py`, que **ya existe** y es lo único de esta cadena que no hay que construir. |
| **Implicación fuera de mi alcance** | Si la reclasificación se acepta, toca a `docs/arquitectura.md` y `CLAUDE.md`, que **no son míos**. Se enruta al arquitecto vía el lead; aquí solo queda registrada. |

---

### T-5 — El **brokerage**, no el agente, como unidad de instalación

| Campo | Contenido |
|---|---|
| **El cambio** | Convergen tres cosas de este mismo documento: `[P]` el riesgo de la §2.4 **se agrega en el broker**, no en el agente (`[S]` NAR extendió el Art. 10 el 2020-11-13); `[P]` las restricciones de Meta se aplican por cuenta publicitaria y **no se pueden esquivar con más agentes**; y `[S]` la §5.1 muestra que el capital está entrando por la puerta del brokerage (17.000 negocios / 87.000 agentes), no del agente suelto. |
| **El dolor** | Un broker con N agentes tiene N superficies de publicación bajo su marca y **cero visibilidad agregada**: no sabe qué se publica, ni con qué mensaje, ni con qué riesgo, ni qué funciona. Es el mismo dolor de T-1 y T-3, pero **con presupuesto y autoridad detrás** — que es lo que los convierte en comprables. |
| **Sustitutos actuales** | Una política escrita que nadie verifica; pedir capturas a los agentes; seguir manualmente las cuentas; **nada**. Fallan todos por la misma razón: no escalan a N y dependen de la colaboración voluntaria del agente. |
| **Señal de urgencia/tamaño** | *(vacío. `[S]` El único orden de magnitud disponible es la distribución del competidor: >17.000 negocios y >87.000 agentes — ~5 agentes por negocio de media.)* |
| **Adyacencia a Qualify** | **MEDIA.** El modelo multi-tenant ya construido y verificado (§1.1: `tenants` / `tenant_members` / `brands`, RLS por `tenant_id`, tres roles, migración `0001` aplicada) mapea sobre "un brokerage = un tenant, N agentes = N miembros, N cuentas conectadas", y `connections` ya soporta múltiples cuentas por tenant con FSM y custodia. Es la tesis que **más reutiliza lo existente sin pedir nada de la §1.2**. |
| **⚠ Aviso sobre ese encaje (2026-07-30)** | **El encaje del esquema NO es evidencia de product-market fit y no debe inflar el score.** El aviso viene del lead y es correcto: el modelo de asientos se construyó **para la forma de este tenant concreto** (1 propietario + N agentes). Que encaje es una tautología, no una validación — **encaja porque se construyó para él.** Un n=1 que confirma el esquema diseñado para ese mismo n=1 no aporta información sobre el mercado. Por eso se queda en `media` y no sube. |
| **Estructura económica real del comprador (refuerzo, `[S]`)** | `gtm` verificó que la franquicia **no paga de forma centralizada**: *"el franquiciado asume los costos"* — cada oficina es económicamente independiente bajo el paraguas RE/MAX AR&UY (fuente: Forbes Uruguay). **Refuerza la tesis en lo comercial**: el que decide y el que paga son la misma persona dentro de una sola oficina, sin comité de compras corporativo. Y a la vez **cierra la puerta al atajo**: no hay una venta única a la franquicia que despliegue a N oficinas. Se vende oficina por oficina. |
| **Fase** | Parte 4-A/4-B tal como están definidas. No exige adelantar nada. |
| **Qué la falsifica** | **El agente inmobiliario suele ser contratista independiente, no empleado.** Si el broker no tiene ni autoridad ni voluntad para exigirle conectar sus cuentas —y muy plausiblemente no la tiene, porque la cuenta es del agente y se la lleva cuando cambia de brokerage— **el producto no se puede instalar**, por muy bien que encaje el modelo de datos. Éste es el riesgo dominante de la tesis y no lo he resuelto. |
| **Validación más barata** | Una sola pregunta al **cliente uno**, que ya existe y ya paga: *"¿puedes hacer que tus agentes conecten sus cuentas de Instagram, y lo harías?"*. Si la respuesta es no, T-5 cae y **arrastra la vía de instalación de T-1 y T-3 con ella**, que pasarían a depender de la venta agente-por-agente. Es la pregunta de mayor valor informativo por unidad de esfuerzo de toda la sesión. Coordinar con `sales-consultant`. |

---

### T-6 — *(NUEVA — RIESGO, no oportunidad)* La ingesta de contenido de terceros bajo un régimen de datos con adecuación europea

> Es la tesis que puede invalidar el producto para el comprador que paga. Va con el nivel de certeza que le corresponde
> y **no** disfrazada de oportunidad.

| Campo | Contenido |
|---|---|
| **El cambio** | No es un cambio reciente: es un **contexto jurídico que el proyecto nunca ha modelado** y que solo se vuelve visible al saber que el comprador es uruguayo. `[S]` Uruguay tiene **Ley 18.331** de protección de datos con autoridad propia (**URCDP**/AGESIC), **decisión de adecuación de la UE 2012/484/UE (2012-08-21) reafirmada el 2024-01-15**, adhesión al **Convenio 108** y ratificación del **108+**; reformada por **Decreto 64/020** (DPO, notificación de brechas), **Ley 19.924** (datos **biométricos**, evaluaciones de impacto) y **Ley 20.075**; con **registro de bases de datos** ante la URCDP. Detalle y fuentes en §2.5. |
| **El dolor** | **Es de Qualify, no del cliente** — y por eso es riesgo y no mercado. El producto lee vídeo, audio y comentarios de **personas que no son clientes del tenant y no han consentido nada**. Bajo un régimen de grado europeo hay base de licitud que sostener, derechos de acceso y supresión que atender, registro que cumplir y, si en algún momento se identifican rostros o voces, la capa **biométrica** con evaluación de impacto. |
| **Sustitutos actuales** | Dentro del proyecto: **ninguno**. No hay ADR, ni sección en `arquitectura.md`, ni nota sobre base de licitud o retención. **El sustituto vigente es no habérselo planteado**, que es la peor variante de "nada" porque **se parece a estar bien**. |
| **Señal de urgencia/tamaño** | *(vacío — y aquí el vacío es la parte importante: no sé si esto es un trámite de un día o un obstáculo estructural, y **nadie en el proyecto lo sabe tampoco**.)* |
| **Adyacencia a Qualify** | **N/A — es una condición de viabilidad, no una oportunidad.** Con una consecuencia técnica que sí es adyacente y honestamente derivada (§2.5): procedencia, RLS por `tenant_id` y custodia de credenciales son **exactamente** lo que un régimen así exige demostrar. Un derecho de supresión requiere saber de qué fuente derivó cada señal para poder borrarla — y eso ya está implementado y verificado (§1.1). **Esto sube el valor del activo de procedencia justo cuando la §4 bajó el del activo de interpretación.** |
| **Fase** | Transversal y **anterior** a cualquier fase: condiciona qué se puede ingerir. |
| **Qué la falsifica** | **(a)** Un dictamen legal uruguayo competente que confirme que el tratamiento de contenido público de terceros con fin de análisis de mercado tiene base de licitud clara (p. ej. interés legítimo) sin cargas desproporcionadas. **(b)** Que el producto se reduzca a contenido de **cuentas conectadas del propio tenant**, donde la relación de tratamiento es mucho más simple — nótese que eso es precisamente Parte 4-A/4-B, es decir, **el camino ya elegido esquiva gran parte del problema**, y solo la ingesta de terceros (scraping de competidores) lo reintroduce. |
| **Validación más barata** | Una consulta acotada a un abogado uruguayo de protección de datos, con una pregunta concreta: *"¿puede una empresa tratar contenido público de redes de terceros para análisis de mercado bajo la Ley 18.331, y qué exige?"*. Horas de abogado, no un proyecto. **Es barato en relación con lo que decide, y hoy no está hecho.** |
| **Fuera de mi competencia, dicho claro** | No soy abogado y esto es `[S]`. **No afirmo que el producto sea ilícito en Uruguay.** Afirmo que el eje regulatorio que decide su viabilidad para este comprador es la protección de datos en la ingesta, que **no aparece en ningún documento del proyecto**, y que resolverlo es barato comparado con su consecuencia. |

---

### T-7 — *(NUEVA — hallazgo sobre el proceso del propio proyecto)* Todo el research previo asumió un comprador que no es el que paga

| Campo | Contenido |
|---|---|
| **El cambio** | No hay cambio de mercado: hay un **desajuste descubierto**. Los tres segmentos con corpus de research (creadores, podcasters, e-commerce/social-commerce) se investigaron con encuadre **implícitamente estadounidense**. El único segmento con cliente que paga es inmobiliario **en Uruguay y Colombia**, y no tenía research hasta esta sesión. |
| **El dolor** | Es del proyecto y se manifestó **dentro de esta misma sesión, de forma medible**: mi tesis mejor puntuada de la primera ronda (T-1) descansaba sobre la Fair Housing Act, derecho de un país donde Qualify no tiene comprador. **Si el sesgo produjo un error de primer orden en un documento escrito por alguien contratado precisamente para no cometerlo, es razonable esperar que esté presente en el research anterior, que nunca fue auditado con esta pregunta.** |
| **Sustitutos actuales** | Ninguno. No hay en el proyecto ningún registro de en qué geografía es válido cada hallazgo de mercado. |
| **Señal de urgencia/tamaño** | *(vacío.)* Pero el coste de comprobarlo es de horas y el de no comprobarlo se compone silenciosamente en cada decisión que se apoye en esos documentos. |
| **Adyacencia a Qualify** | **N/A — es deuda de método, no oportunidad de mercado.** |
| **Fase** | Ninguna. Es higiene de research. |
| **Qué la falsifica** | Una relectura de `docs/dolores-creadores-podcasters.md` y `docs/fase0-zernio-mercado.md` que muestre que sus hallazgos **son geográficamente neutros o ya declaran su ámbito**. Es una comprobación de una hora y puede matar la tesis limpiamente. |
| **Validación más barata** | Exactamente esa relectura, con una única pregunta por hallazgo: *¿esto sería cierto para una PYME uruguaya?* **No propongo rehacer el research** — propongo anotarle el ámbito, que es barato y hace visible el sesgo en lugar de eliminarlo. |
| **Nota** | Va aquí porque el encargo lo pidió como posible tesis propia. **No es propiedad mía arreglarlo**: `docs/dolores-creadores-podcasters.md` y el corpus de `gtm-specialist` no son mis archivos. Queda registrado y se enruta. |

---

### 6.0 Resultado de la ronda adversarial (2026-07-30)

Se registra aquí porque cambia conclusiones, no solo matices.

#### 1. ADV1 vs `gtm` — resuelto, y `gtm` concedió más de lo que yo pedía

Mi posición era acotada: *la ausencia de oferta no es evidencia de demanda*. `gtm` revisó su propio material y aportó
cuatro puntos que **inclinan en contra del whitespace**, incluida la retirada de un argumento propio. Lo acepto entero.
El más fuerte, y lo digo con sus palabras porque es mejor que las mías: **el techo de software del comprador LATAM
($50-185/mes para toda la empresa) está por debajo de un solo asiento de cualquier herramienta de listening comparable
($249-950/mes)** — eso es una **explicación suficiente** de la ausencia, y cuando existe una explicación suficiente,
inferir whitespace es injustificado.

**Adopto la reformulación de `gtm`, que es mejor pregunta que la mía.** No es *"¿este nicho quiere escuchar?"*
—régimen A ya responde que sí: BizAI, Pipeline ROI, Birdeye y Sked venden listening por palabra clave a agentes
inmobiliarios hoy—. Es: **"¿pagaría este comprador un *delta* por listening de grado-contenido sobre el listening de
grado-palabra-clave que ya compra?"** Testable, con ancla de precio, y **desplaza la pregunta de la existencia a la
prima**. Es la formulación que debe sobrevivir a esta sesión.

Registro también, porque es lo relevante para nosotros: **Lofty —incumbente bien financiado y con conocimiento de
dominio— reconstruyó desde cero en 2026 y eligió NO leer contenido de terceros.** Es juicio de producto revelado en
contra. No es dispositivo, pero es la clase de evidencia que no se puede descartar por conveniencia.

#### 2. ADV2 vs `sales` — separo dos argumentos que llegaron juntos, y respondo distinto a cada uno

`sales` sostiene, a la vez, que el hueco existe **y** que **nadie en su corpus lo pidió**. Mi respuesta se parte en dos,
porque son pruebas de fuerza muy distinta y tratarlas igual sería un error en cualquiera de las dos direcciones.

**(a) "Nadie lo pidió" es un test débil aquí, y no concedo sobre esa base.**
Los compradores nombran **sustitutos, no categorías**. Nadie pide por su nombre una categoría para la que no tiene
referente; pide "que el CRM sea más fácil" porque el CRM es lo que conoce. Y el instrumento importa: un corpus de
reseñas de CRM mide insatisfacción con CRMs, **no demanda latente de una categoría inexistente** — cosa que `gtm`
concedió explícitamente sobre sus propios 16 verbatims. Un corpus que no puede registrar la señal no es evidencia de
su ausencia. **Este argumento, solo, no degrada ninguna tesis.**

**(b) El techo de precio sí es un argumento fuerte, y sobre ése SÍ concedo.**
No dice "nadie lo pidió"; dice **"existe una explicación suficiente y estructural de por qué no existe"**. Es
categóricamente mejor evidencia, y **degrada T-3 y T-5** — no porque falte demanda verbalizada, sino porque el
presupuesto disponible puede estar por debajo del coste de servir.

**(c) Y añado algo que ninguno de los dos planteó, que empeora el cuadro para nosotros.**
Los dos hallazgos —"nadie lo pide" y "no cabe en el presupuesto"— **se están tratando como convergentes e
independientes, y probablemente no son independientes.** Pueden ser dos síntomas de lo mismo: que **este comprador no
está en el mercado de productos de información a ningún grado ni precio**, y compra herramientas de
ejecución (publicar, contactar, cerrar). Si eso es cierto, la reformulación de `gtm` en el punto 1 no solo se
responde "no", sino que **estaba mal planteada**: no habría delta que pagar porque no hay categoría base. **No lo
afirmo — lo dejo como la hipótesis nula que ninguna de las tres líneas de trabajo ha intentado matar.**

**(d) Sobre la analogía del cinturón de seguridad, y aquí está la concesión que más me cuesta.**
El razonamiento *"algunas oportunidades genuinas nunca se piden por su nombre"* **es válido, pero solo para
oportunidades con forma regulatoria o de compliance** — nadie pide un registro de auditoría antes de que llegue el
auditor. **El problema es que mi único caso realmente con esa forma era T-1, y T-1 acaba de morir por jurisdicción,
por una razón completamente independiente.** T-3 y T-5 **no** tienen forma de compliance: son productos de
información discrecional, y para ésos "nadie lo pide" **sí** cuenta como evidencia en contra.
Es decir: **mi mejor argumento contra el test de `sales` se evaporó por un motivo que no tiene nada que ver con
`sales`.** Queda vivo únicamente para **T-6**, que es riesgo y no oportunidad, y donde la ausencia de demanda
verbalizada es exactamente lo esperado.

#### 2-bis. Convergencia independiente con `sales` — y el descuento que hay que aplicarle

`sales` llegó en paralelo, sin haber visto mi respuesta, a la misma conclusión, y **corroboró el techo de precio desde
un ángulo genuinamente distinto**: el precio publicado de Tokko (~$100-110/mes), que cae dentro del rango $50-185
que `gtm` había obtenido por otra vía. Su frase de cierre —*"si R6 se construye, su justificación tiene que venir de
otro segmento o comprador; presentarlo como el camino al cliente uno sería el error caro de esta sesión"*— es la
conclusión de mi T-4/T-6 formulada por otro y desde otros datos.

**Eso es evidencia fuerte y así debe pesarse. Pero hay que aplicarle un descuento explícito, o dentro de dos semanas
se citará como "los tres agentes coincidieron" y valdrá más de lo que vale.**

- **Lo que sí es independiente y cuenta:** el techo de precio tiene ahora **dos fuentes con métodos distintos**
  (rango sectorial de `gtm`; pricing publicado de un vendor concreto por `sales`). Eso es corroboración real.
- **Lo que NO es independiente:** los tres agentes compartimos **un mismo brief, un mismo lead que retransmitió los
  hallazgos entre nosotros durante la sesión, y una misma corrección geográfica a mitad de camino**. Nuestras
  conclusiones **no son tres observaciones independientes del mercado**; son tres análisis con inputs parcialmente
  comunes y comunicación cruzada en tiempo real. La convergencia bajo esas condiciones está **inflada por
  construcción**, y parte de ella puede ser simple contagio.
- **Regla al citar esto:** apóyese en las **dos fuentes de precio**, que sí son independientes, y **no** en "tres
  agentes coincidieron", que no lo es. **El acuerdo entre analistas que se hablan entre sí no es replicación.**

---

#### 3. Corrección al diseño del experimento de tasa base (advertencia de `gtm`, aceptada)

`gtm` advirtió que mi experimento de T-1 —vendido como *"sin hablar con nadie"*— **habría corrido sobre datos públicos
estadounidenses** y se habría aplicado al cliente uruguayo, **porque no existe corpus público de reseñas del comprador
LATAM** (Tokko tiene 2 reseñas en total). Es correcto y es grave: habría reintroducido la conflación EE. UU./LATAM
que provocó el error de T-1 en primer lugar, **y esta vez disfrazada de medición objetiva**.

**El experimento queda retirado tal como estaba.** La lección general, que vale más que el experimento: **"no requiere
hablar con nadie" es atractivo precisamente porque es barato, y ese atractivo es lo que hace que no se examine de qué
población sale el dato.** Para régimen B (el comprador que paga) **no hay atajo de datos públicos**: hay que
preguntarle a él. Cualquier experimento futuro de este documento debe declarar **sobre qué población corre** antes de
declarar qué mide.

---

### 6.0-bis Cierre: `sales` falsó mi hipótesis nula por evidencia positiva, y el resultado corrige mi formulación

Registrado el 2026-07-30, tras el cierre formal de la ronda. `sales` volvió a atacar mi hipótesis nula (§6.0-2c) con
**evidencia positiva en lugar de otro argumento desde la ausencia** — que es la forma correcta de hacerlo. Revisaron
los **10 "ojalá hiciera X" verbatim** de toda su cosecha (4 herramientas, 3 países, más una oferta de empleo)
(`docs/demanda-ventas-inmobiliario.md` §6.5).

**Mi formulación era direccionalmente correcta pero demasiado amplia, y la corrijo.** Dije "este comprador no compra
productos de información a ningún grado". El dato dice algo **más fino y más útil**: la frontera no está entre
*información* y *ejecución*. Está entre:

| | Pedido | Evidencia |
|---|---|---|
| **Información sobre la propia actividad** (reporting, atribución) | **Sí** | 2 de 10 verbatims |
| **Información sobre el mundo exterior** (competidores, conversación de mercado, contenido de terceros) | **No** | **0 en cualquier fuente** |
| Ejecución (batch texting, WhatsApp, captura de leads, recordatorios, control de publicación) | Sí | El resto |

**Dos consecuencias, y van en direcciones opuestas.**

**(a) La hipótesis nula pasa de "no falsada" a "positivamente sostenida" — para R6.** Leer contenido primario de
terceros no aparece en **ninguna** lista de deseos, de ninguna herramienta, de ningún país. Ya no es un argumento
desde la ausencia de oferta: es ausencia de petición **medida sobre el corpus en el que sí aparecen otras peticiones**.
Ése es un instrumento capaz de registrar la señal, y no la registró.

**(b) Y sin embargo rescata T-3, que era la única tesis mía de información con demanda observable.** "¿Qué Reel mío
funcionó?" es **información sobre la propia actividad** — el lado pedido de la frontera. Es la **única mejora de
puntuación de toda la sesión**, y llega de la línea de trabajo que más presión adversarial me puso.

**El cuadro que resulta es incómodo y conviene decirlo entero, porque es la posición estratégica real de Qualify:**

> **La tesis con demanda observada (T-3) es la que yo mismo declaré sin foso. La tesis con foso defendible
> —leer contenido primario de terceros— es la que tiene cero demanda observada.** No es un empate ni un menú:
> es un desajuste entre dónde está la ventaja y dónde está el tirón, y ninguna de las dos mitades se arregla
> construyendo más de la otra.

**Concesión adicional aceptada:** `sales` concedió mi punto sobre no-independencia y extrajo la consecuencia correcta,
que yo había dejado a medias — si la nula se sostiene, la pregunta reformulada de `gtm` (*"¿pagarían un delta por
listening de grado-contenido?"*) **no se responde "no": está mal planteada**, porque no hay categoría base de la que
tomar un delta.

**El test que decide, y es el más afilado que produjo cualquiera de los tres ejes:** enseñarle al cliente uno un
análisis real **de su propio vídeo** y ver si pregunta el precio. Separa "no cabe en el presupuesto" de "no está en
el mercado de información a ningún precio" — y, por (b), **es simultáneamente el test de venta de T-3**. Debe
ejecutarse antes que cualquier decisión de construcción.

---

### 6.1 Lectura conjunta

*(Revisada 2026-07-30 tras la corrección geográfica.)*

- **La dependencia oculta sigue en pie, y ahora carga más peso:** T-3 y T-5 comparten el supuesto de instalación (que se puedan conectar las cuentas de los agentes). **El falsador de T-5 es el falsador compartido de las dos tesis vivas para este comprador.** Se resuelve con una pregunta a un cliente que ya paga.
- **Orden recomendado de gasto, reordenado:**
  1. **La pregunta de T-5 al cliente uno** — *"¿puedes hacer que tus agentes conecten sus cuentas, y lo harías?"*. Máxima información por unidad de esfuerzo; si es "no", T-3 y T-5 caen juntas.
  2. **Los términos de uso del proveedor frontera** (falsador c de T-4). Minutos, y puede cerrar la cuestión.
  3. **La consulta legal de T-6.** Horas de abogado; decide qué se puede ingerir, que es anterior a todo lo demás.
  4. **El golden set etiquetado** — desbloquea a la vez QUA-23 y el benchmark de T-4. La pieza técnica de mayor apalancamiento y hoy no está priorizada en ningún sitio.
  5. **Repetir la §5 en español** (proptech hispanohablante). Decide si el conjunto competitivo que estamos mirando es siquiera el correcto.
  - **Nótese que 1, 2, 3 y 5 no requieren escribir una sola línea de código.**
  - **Añadido tras ADV1/ADV2 y ahora por delante de todo lo demás:** la pregunta reformulada por `gtm` —**"¿pagaría este comprador un delta por listening de grado-contenido sobre el de grado-palabra-clave que ya compra?"**— con la variante que exige mi §6.0-2c: **antes de preguntar por el delta, verificar que compra la categoría base.** Si el cliente uno no paga hoy por ninguna herramienta de información, la pregunta del delta no tiene sujeto. **Se responde en la misma conversación que el punto 1**, y es la más barata de todas.
- **Advertencia de método que aplica a todo lo anterior:** cada experimento debe declarar **sobre qué población corre** (régimen A estadounidense vs. régimen B, el cliente que paga) **antes** de declarar qué mide. Los experimentos "sin hablar con nadie" son atractivos por baratos, y ese atractivo es justo lo que impide preguntarse de qué población sale el dato. **Para régimen B no hay atajo de datos públicos.**
- **Sobre el whitespace, tras la ronda adversarial y sin adornos:** el hueco de capacidad está confirmado (nadie lee contenido primario de terceros en este nicho); **el whitespace NO lo está.** Hay ahora **tres explicaciones suficientes de la ausencia que no hemos descartado**, y basta con que una sea cierta para que no haya oportunidad: (i) **el techo de precio** LATAM está por debajo del coste de servir (`gtm`, ADV1 — la más fuerte); (ii) **el coste jurídico** de tratar contenido de terceros bajo un régimen con adecuación europea (T-6, mía); (iii) **este comprador no compra productos de información a ningún grado**, sino de ejecución (§6.0-2c, mía — la hipótesis nula que nadie ha atacado). Añádase que **Lofty eligió no construirlo** teniendo medios y dominio. **Cuatro razones para no hacerlo y ninguna prueba de demanda no es un empate: es una recomendación de no construir hasta que una de las cuatro caiga.**
- **Anti-adulación, explícito:** de siete tesis, **una recomienda declinar (T-2), una dice que la clasificación del núcleo es errónea (T-4), una se entrega sin foso (T-3), una es un riesgo que puede invalidar el producto (T-6) y una señala un sesgo en el research previo del propio proyecto (T-7).** Y **la mejor tesis de mi primera ronda resultó estar construida sobre el país equivocado.** El brief no era dirigido; el análisis inicial sí estaba sesgado, y el sesgo era mío.
- **Fuera de mi alcance, una línea y al fundador** (decisión del fundador, 2026-07-29): T-5 implica vender al brokerage y no al agente, lo que cambia precio y canal. **No opino** — no es mi función.
- **Enrutado a otros propietarios:** la reclasificación de T-4 toca `docs/arquitectura.md`/`CLAUDE.md` (arquitecto, en sesión posterior — no hay arquitecto en esta sesión); T-7 toca el corpus de research de `gtm-specialist` y `docs/dolores-creadores-podcasters.md`. **No he editado ninguno.**
- **Hueco de método:** no existe skill instalada de scanning de tendencias ni de scoring de oportunidades. La rúbrica está en la **§1.4** para que sea auditable (candidata COMPASS). **A esa rúbrica hay que añadirle un paso cero que hoy no tenía: *verificar la jurisdicción del comprador antes de puntuar nada*.** Esta sesión pagó el precio de que faltara.

