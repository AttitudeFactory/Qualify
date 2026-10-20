# Plan: observabilidad de pruebas de modelos con Langfuse

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

**Estado:** aprobado en lo esencial, 2026-10-13. Nada de Langfuse existe en código todavía.

**Decisiones del fundador (2026-10-13):**

1. **Langfuse autoalojado**, no Cloud.
2. **Fuera de las pruebas: HeyGen y Remotion.** No se instrumentan ni entran en experimentos.
3. **Las métricas las fija este plan** (sección 6).
4. **Antes de empezar, el copy pasa a `claude-opus-5-5`.** Hecho el mismo día: ver sección 2.

**Alcance:** las llamadas a modelos del **generador de contenido** (/create), del **Brand Kit**, del **inbox** y del **harness de evaluación** de `packages/models`. No cubre logs de infraestructura, métricas HTTP ni la ingesta social de Fase 1 Parte 3.

---

## 1. Qué queremos conseguir

1. **Ver cada llamada a un modelo**: qué entró, qué salió, cuánto tardó y cuánto costó, agrupado por pieza o por lectura del Brand Kit.
2. **Comparar modelos con datos**: el mismo conjunto de casos contra dos modelos, dos prompts o dos niveles de `effort`, con calidad, costo y latencia lado a lado.
3. **Recoger el juicio humano**: aprobar, rechazar o editar un borrador queda como puntuación sobre la traza que lo produjo.

---

## 2. Punto de partida

### Modelos en el alcance

| Dónde | Modelo | Qué hace |
|---|---|---|
| Generador: copy | `claude-opus-5-5`, `effort: medium`, con respaldo automático ante rechazos | Gancho, CTA, guion, texto del post |
| Generador: imagen | Seedream `seedream-5-0-lite-260128` | Escena de la imagen publicitaria, diapositivas, primer fotograma de video |
| Generador: video | Seedance `seedance-1-0-pro-250528` | Avatar y diapositivas animadas |
| Brand Kit | `claude-sonnet-5` | Lectura de brief y brandboard, tipografía, tono de voz, rubro desde la cuenta, referentes, selección de hashtags |
| Brand Kit | `claude-haiku-4-5` | Clasificación de hashtags, hashtags del caption |
| Brand Kit | Whisper `large-v3-turbo` local | Transcripción de la grabación de voz |
| Inbox | `claude-haiku-5-5` | Borrador de respuesta |
| Cascada multimodal | SigLIP2, Qwen3-VL, Whisper, robertuito | Filtro, visión, transcripción, sentimiento |

**Fuera del alcance:** HeyGen (decisión del fundador) y Remotion (es un render determinista, no un modelo).

### Migración a Opus 5.5 (hecha el 2026-10-13)

`claude-opus-5` solo se usaba en el copy del generador. El cambio, siguiendo la guía oficial de migración:

- **Modelo** `claude-opus-5-5`: 20 % más barato ($4 / $20 por millón de tokens), mismo tokenizador y contexto.
- **`effort` explícito en `medium`.** Opus 5.5 trae `medium` por defecto donde Opus 5 traía `high`. Según Anthropic, su `medium` ya supera al `high` de Opus 5. Fijarlo evita que un cambio de modelo cambie cuánto piensa sin querer.
- **Respaldo ante rechazos** (`fallbacks: "default"`). Si los clasificadores de seguridad rechazan un brief benigno, la misma llamada se reintenta en el modelo que Anthropic recomienda para esa categoría: Opus 5 u Opus 4.8. Se registra y se cobra el modelo que respondió de verdad.
- **Tabla de precios v4**, con Opus 5.5 y los dos modelos de respaldo. Las versiones publicadas no se editan.
- **Sin cambios necesarios en** thinking (ya era adaptativo), `tool_choice` (el copy usa salida estructurada) y parámetros de muestreo (nunca se enviaron).

**Verificado el 2026-10-13 con la clave del `.env` local:** la API reconoce `claude-opus-5-5` para esta cuenta y el conteo de tokens responde. Falta una generación real de copy, que sí cuesta.

### Lo que ya existe y se reutiliza

| Pieza | Dónde | Papel con Langfuse |
|---|---|---|
| Traza en consola del generador | `qualify_api/creative/trace.py` | Sigue igual; Langfuse no la sustituye |
| Costo por llamada | `creative_usage_events` + `pricing_data/v4.json` | Sigue siendo la fuente de verdad del gasto. Langfuse recibe esas cifras, no las calcula |
| Estadísticas de Claude del Brand Kit | `claude_tools.CallStats` | Hoy se descartan; pasan a Langfuse |
| Harness de evaluación con métricas | `qualify_models/eval/` | Sus métricas se vuelven evaluadores de Langfuse |
| Reglas duras de marca | `qualify_creative/brand` (`check_hard_rules`) | Evaluador determinista del copy |

**Puntos únicos de paso** que cubren todo con poca instrumentación:

- `CreativeRouter.run`: toda llamada del generador a un proveedor. Se instrumenta con una lista de proveedores permitidos: `anthropic`, `seedream`, `seedance`. HeyGen y Remotion pasan sin registrarse.
- `claude_tools.create_turn`: todas las funciones de Claude del Brand Kit.
- Sueltas: `replies/claude_drafts.py` y Whisper en `Qualify/voice_lab.py`.

---

## 3. Despliegue autoalojado

Langfuse v4 necesita dos contenedores propios (web y worker) más Postgres, **ClickHouse**, Redis y un almacenamiento compatible con S3. Ese ClickHouse es interno de Langfuse: no es nuestro plano analítico y no contradice ADR 31.

**No cabe en el servidor de la app.** El servidor de producción es un CX23 (2 vCPU, 4 GB). Langfuse recomienda 4 núcleos y 16 GiB.

### Etapa A: en esta máquina (desde ya)

Esta máquina tiene 8 núcleos y 32 GB de RAM: alcanza de sobra para pruebas.

- **Un compose propio** en `infra/langfuse/docker-compose.yml`, basado en el oficial, con nombre de proyecto `qualify-langfuse`. Va separado del `docker-compose.yml` de la app para que `just down` nunca borre las trazas.
- **Puertos.** Solo se publica la web, en el **3100**: el 3000 es el frontend de Reflex. Postgres, ClickHouse, Redis y MinIO quedan sin puertos al host, porque el 5432 y el 6379 ya los usa la app.
- **Base de datos propia.** Langfuse no comparte el Postgres de la app, por aislamiento y para que sus migraciones no toquen las nuestras.
- **Arranque sin interfaz** con las variables oficiales `LANGFUSE_INIT_ORG_ID`, `LANGFUSE_INIT_PROJECT_ID`, `LANGFUSE_INIT_PROJECT_PUBLIC_KEY`, `LANGFUSE_INIT_PROJECT_SECRET_KEY`, `LANGFUSE_INIT_USER_EMAIL` y `LANGFUSE_INIT_USER_PASSWORD`. El proyecto y las claves existen desde el primer arranque.
- **Secretos** (`NEXTAUTH_SECRET`, `SALT`, `ENCRYPTION_KEY` de 64 caracteres hex, contraseñas) en `infra/langfuse/.env`, fuera de git, con un `.env.example` al lado.
- **Recetas nuevas:** `just langfuse-up`, `just langfuse-down` (sin `-v`), `just langfuse-logs`.
- **Rotación de logs de Docker** (`max-size`, `max-file`), que la guía oficial pide para no llenar el disco.

**Hecho y verificado el 2026-10-13** (`just langfuse-up`, imagen `4.58.0`):

- Los seis servicios arrancan sanos. Solo hay dos puertos publicados, ambos en `127.0.0.1`: la web en el 3100 y MinIO en el 9190.
- El arranque sin interfaz crea la organización y el proyecto «Qualify» con sus claves. El usuario y la contraseña están en `infra/langfuse/.env`.
- Una generación de prueba enviada por OTLP se lee de vuelta al momento con su entrada, salida, uso y costo intactos.

Tres cosas aprendidas al levantarlo, ya resueltas en el compose:

1. **La v4 solo acepta trazas por OpenTelemetry.** El servidor corre en modo `events_only`: el endpoint clásico `/api/public/ingestion` solo acepta puntuaciones, y las trazas se leen por `/api/public/v2/observations`. El SDK v4 de Python ya usa OTLP, así que el plan no cambia.
2. **Carrera de arranque.** El worker arrancaba junto a la web, antes de las migraciones, y fallaba al crear los paneles por defecto. Ahora espera a que la web esté sana.
3. **La imagen web no trae healthcheck**, y el servidor escucha en el nombre del contenedor, no en `localhost`. Se añadió uno que consulta `/api/public/health` por ese nombre.

**Un solo proyecto.** Desarrollo y experimentos se separan por el atributo `environment`, no por proyectos distintos.

### Etapa B: servidor propio (cuando haya que compartirlo)

Cuando otra persona del equipo necesite verlo, o cuando la app de producción envíe trazas:

- **Un servidor aparte en Hetzner**, CX43 (8 vCPU, 16 GB), con su propio Caddy y TLS en un subdominio como `langfuse.<dominio>`. Confirmar precio y disponibilidad al crearlo: Hetzner cambió precios el 2026-06-15.
- **Registro cerrado** después del primer usuario.
- **Copias de seguridad** del Postgres y del volumen de ClickHouse. El Compose oficial no las trae, y Langfuse no lo recomienda para producción por eso.
- **La app envía las trazas por HTTPS.** No hace falta red privada entre servidores.

---

## 4. Cómo se ve una pieza en Langfuse

- **Una traza por generación de borrador.** El `draft_id` es la sesión, así que las regeneraciones del mismo borrador quedan juntas.
- **Una observación por llamada del enrutador:** `copy` (Claude), `escena` (Seedream), `video` (Seedance).
- **Atributos propagados** a todas las observaciones:
  - `tags`: tipo de contenido y formato, por ejemplo `static_flyer` y `reels_9_16`.
  - `metadata`: `tenant_id`, `brand_id`, `pricing_version`, `voice_version`, `effort`.
  - `user_id`: un hash del usuario que actúa, nunca su correo.
- **Entorno** (`LANGFUSE_TRACING_ENVIRONMENT`): `development` en cada máquina, `eval` en los experimentos, `production` cuando llegue.
- **Versión** (`LANGFUSE_RELEASE`): el SHA de git.

**Costos ingeridos, no inferidos.** Cada observación lleva `usage_details` y `cost_details` calculados con `pricing_data/v4.json`:

| Proveedor | `usage_details` | Costo |
|---|---|---|
| Claude | `input`, `output`, `cache_read`, `cache_creation` | por token |
| Seedream | `images` | $0.035 por imagen |
| Seedance | `video_tokens` | por millón de tokens |
| Whisper local | `audio_seconds` | $0 |

---

## 5. Dónde se instrumenta

Un módulo nuevo, `qualify_shared/observability.py`, envuelve el SDK v4 de Python. Tres reglas:

1. **Sin claves no hace nada.** Los tests offline y la CI siguen igual.
2. **Nunca rompe una generación.** Es la misma regla que `trace.py`.
3. **Es el único sitio que importa `langfuse`.** Un test estático lo hace cumplir, igual que con las sesiones de base de datos y con R2.

| Punto | Qué se registra |
|---|---|
| `ContentService` al generar | La traza raíz con sus atributos |
| `CreativeRouter.run` | Una observación por llamada, solo para `anthropic`, `seedream` y `seedance` |
| `claude_tools.create_turn` | Un turno de Claude con el nombre de la función (`brief_ai`, `font_ai`…) |
| `replies/claude_drafts.py` | El borrador de respuesta |
| Whisper en `voice_lab.py` | Duración del audio y tiempo de transcripción |
| `qualify_models/eval/harness.py` | Una observación por etapa de la cascada |

**Instrumentación manual, no `opentelemetry-instrumentation-anthropic`.** El automático solo ve Claude y no conoce nuestra tabla de precios ni la caché.

**Hilos.** Las generaciones corren en hilos de `InlineDispatcher`. No hizo falta propagar contexto: la traza raíz se abre dentro del hilo, en `ContentService._generate`, y el productor de medios no abre hilos propios. Los CLI de evaluación llaman a `flush()` antes de salir.

**Cómo quedó (fase 2, 2026-10-13):**

- **El enrutador no se tocó.** Los proveedores se envuelven al montar la app (`traced_providers` en `composition.py`), así `qualify_creative` sigue sin saber que Langfuse existe.
- **El enmascarado corre antes del SDK, no solo en su gancho.** El SDK extrae las URL `data:` de una entrada y las sube como archivos a Langfuse antes de aplicar su propio `mask`. Sin enmascarar primero, la foto de un cliente acabaría en el almacenamiento de Langfuse. Un test lo vigila.
- **Verificado con una llamada real** a `claude-opus-5-5` con `effort: medium` y respaldo activo: la traza llegó con la generación `copy`, 308 tokens de entrada, 257 de salida y $0.0064.
- **El `.env` de la app ya tiene las claves**, así que cada pieza generada desde /create se registra en el entorno `development`.

**Cómo quedó (fase 3, 2026-10-13):**

- **Una traza por función con IA**, con un decorador `observability.traced` en las nueve: leer documento, identificar tipografía, sugerir tono, analizar voz, clasificar hashtags, elegir hashtags, hashtags del caption, rubro desde la cuenta y revisar referentes. Si una corre dentro de otra («analizar voz» llama a «sugerir tono»), queda como tramo hijo y la traza conserva el nombre de la de fuera.
- **Cada turno de Claude es una generación**, desde una sola función, `claude_tools.messages_create`, que comparten el Brand Kit y el inbox. Los PDF e imágenes de los mensajes se sustituyen por un marcador: viajan en base64 sin prefijo `data:`, y el enmascarado genérico no los reconocería.
- **Whisper** queda como generación de costo cero con el modelo, el idioma y los segundos de audio. Nunca se envía el audio ni el nombre del archivo, que puede llevar el nombre de una persona.
- **`observability.capture_spans()`** permite probar todo en memoria, sin que ningún test importe el SDK.
- **Verificado con una llamada real** a Haiku 5.5 desde el inbox: traza «respuesta inbox» con su generación anidada, $0.00007.

---

## 6. Métricas

### 6.1 Comunes a todas las llamadas (automáticas, desde las trazas)

| Métrica | Definición |
|---|---|
| `costo_usd` | Costo de la llamada, y suma por pieza |
| `latencia_s` | p50 y p95 por modelo y por función |
| `tasa_error` | Llamadas que terminan en excepción o timeout |
| `tasa_rechazo` | Claude: respuestas con `stop_reason: refusal` |
| `tasa_respaldo` | Claude Opus 5.5: respuestas servidas por el modelo de respaldo |
| `cache_hit` | Claude: `cache_read / (input + cache_read + cache_creation)`. El copy debería estar por encima de 0,5 desde la segunda pieza de una marca |

### 6.2 Por tarea

**Copy del generador** (Opus 5.5)

| Métrica | Tipo | Definición |
|---|---|---|
| `reglas_ok` | Puerta, 0/1 | `check_hard_rules` sin fallos: palabras prohibidas y afirmaciones vetadas |
| `esquema_ok` | Puerta, 0/1 | La salida valida contra `CopyPayload` |
| `largos_ok` | Puerta, 0/1 | El gancho y el CTA caben en los límites impresos de la plantilla |
| `restricciones_ok` | Puerta, 0/1 | Aparece todo lo de «Debe mencionar» y nada de «Debe evitar» |
| `diversidad` | 0–1 | 1 menos la similitud media de trigramas entre los ganchos de las variantes de un borrador |
| `aprobado` | Humano, 0/1 | El borrador se aprobó en Borradores |
| `edicion` | Humano, 0–1 | Distancia de edición normalizada entre el copy generado y el aprobado |

**Lectura de documentos del Brand Kit** (`brief_ai`)

| Métrica | Definición |
|---|---|
| `citas_verificadas` | Propuestas cuya cita aparece literal en el documento. El código ya lo comprueba |
| `precision_campos` / `recall_campos` | Campos propuestos correctos frente a los esperados, con comparación normalizada |

**Tipografía** (`font_ai`): `top1` y `top3`, si la familia correcta está en la primera o entre las tres primeras propuestas.

**Tono de voz** (`voice_analysis`): `mae_ejes`, el error absoluto medio en los cuatro ejes frente a la etiqueta, y `dentro_de_1`, el porcentaje de ejes a una posición o menos.

**Hashtags**

| Función | Métrica |
|---|---|
| Clasificación (Haiku) | `exactitud` y `f1_macro` por tipo de hashtag |
| Selección (Sonnet) | `precision_k`: de los elegidos, cuántos están en el conjunto relevante etiquetado |

**Referentes** (`referentes/ai.py`): `exactitud` del veredicto de encaje y `precision_encaja`, de los que dijo que encajan, cuántos encajan de verdad.

**Respuestas del inbox** (Haiku 5.5): `reglas_ok` determinista, `aprobado` y `edicion` humanos.

**Imagen** (Seedream). No hay métrica automática fiable de fidelidad visual: el filtro SigLIP del repo tiene un defecto verificado y no se usa como juez.

| Métrica | Tipo |
|---|---|
| `dimensiones_ok` | Automática, 0/1: tamaño y proporción del formato pedido |
| `fidelidad_producto` | Humana, 1–5, solo si se subió foto del producto |
| `fidelidad_fondo` | Humana, 1–5, solo si se subió foto del fondo |
| `coherencia_escena` | Humana, 1–5: la imagen muestra lo que pide la descripción |
| `texto_legible` | Humana, 0/1: el titular y el botón se leen |
| `zona_segura_ok` | Humana, 0/1, solo Reel y Story: nada importante bajo los botones de Instagram |
| `artefactos` | Humana, 0/1: manos deformes, objetos fundidos, texto inventado en la escena |

**Video** (Seedance)

| Métrica | Tipo |
|---|---|
| `duracion_ok` | Automática, 0/1: dura lo pedido |
| `segundos_por_dolar` | Automática |
| `movimiento_natural` | Humana, 1–5 |
| `fidelidad_primer_fotograma` | Humana, 1–5 |
| `artefactos` | Humana, 0/1 |

**Whisper local**: `wer` frente a la transcripción de referencia, con la función que ya existe en `qualify_models/eval/metrics.py`, y `rtf`, tiempo de proceso dividido entre la duración del audio.

**Cascada multimodal**: las métricas que ya calcula el harness (precisión y exhaustividad del filtro, WER, exactitud de sentimiento). Bloqueada hasta etiquetar el golden set, que hoy tiene un ítem.

### 6.3 Regla para declarar ganador

Un candidato reemplaza al modelo actual en una tarea si cumple todo esto, sobre al menos 30 casos:

1. **Puertas:** la tasa de casos que pasan todas las puertas no baja más de 2 puntos.
2. **Calidad:** la métrica principal de la tarea no baja. Si hay juicio humano, `aprobado` no baja.
3. **Ventaja:** cuesta menos con la misma calidad, o da más calidad por un costo aceptado de antemano.
4. **Operación:** la latencia p95 no sube más de un 50 % y la tasa de error no sube.

Cada experimento se repite dos veces antes de decidir. Los modelos con thinking no dan siempre la misma salida.

### 6.4 Juez con LLM

Queda **fuera de la primera versión**. Un evaluador «¿suena a la marca?» con Claude cuesta otra llamada por caso, y su propio sesgo habría que medirlo. Entra solo cuando las puertas y el juicio humano ya no distingan entre dos candidatos.

---

## 7. Datasets y primeros experimentos

| Dataset | Casos | Primer experimento | Pregunta que responde |
|---|---|---|---|
| **Briefs del generador** | ~30: tipo × formato × marca de prueba | Opus 5.5 `medium` contra Opus 5.5 `low` | ¿Se puede pensar menos sin perder calidad? |
| | | Opus 5.5 contra `claude-sonnet-5-5` | ¿Vale la pena Opus para el copy? Sonnet cuesta la mitad |
| **Documentos del Brand Kit** | 15–20 briefs y brandboards anonimizados | `claude-sonnet-5` contra `claude-sonnet-5-5` | Mismo precio: ¿el nuevo lee mejor? |
| **Hashtags** | ~200 etiquetas con su tipo correcto | `claude-haiku-4-5` contra `claude-haiku-5-5` | Haiku 5.5 cuesta 10 veces menos |
| **Escenas de imagen** | ~20 briefs con y sin fotos | Seedream 5.0 lite: con fotos frente a solo descripción | ¿Cuánto aportan las fotos opcionales? |
| **Grabaciones de voz** | 10–15 audios con transcripción | Whisper `large-v3-turbo` contra `small` | ¿Se puede transcribir más rápido en el servidor sin GPU? |

### 7.1 Resultados de la primera corrida (2026-10-13)

Una corrida por configuración; la regla de §6.3 pide repetir antes de cambiar un modelo por defecto. Detalle en `packages/api/evals/copy_ai/README.md` y `packages/api/evals/hashtag_ai/README.md`.

**Copy del generador** (24 briefs × 2 variantes):

| Configuración | Puertas | $/pieza | p95 | Diversidad |
|---|---|---|---|---|
| Opus 5.5 `medium` (producción) | 100 % | 0.063 | 17,7 s | 0,89 |
| Opus 5.5 `low` | 97,9 % | 0.041 | 10,9 s | 0,78 |
| Sonnet 5.5 `medium` | 95,8 % | 0.020 | 8,3 s | 0,85 |

- **Producción se queda en Opus 5.5 `medium`.** Los dos candidatos bajan más de 2 puntos en puertas.
- **Todos los fallos son de largo**, ninguno de reglas de marca. La salida estructurada no puede imponer `maxLength`: el modelo solo recibe el límite como texto. Un gancho de 61 caracteres de Sonnet haría fallar la validación en producción. Hacer cumplir los largos en código y repetir es el siguiente paso; si la brecha se cierra, Sonnet 5.5 escribe por un tercio del costo.

**Repetida con los largos ya aplicados en código** (los dos candidatos): Opus 5.5 `low` y Sonnet 5.5 `medium` pasan el 100 % de puertas, a $0.043 y $0.020 por pieza. **Sonnet 5.5 `medium` queda como candidato a reemplazar a Opus 5.5 `medium`**: un tercio del costo y la mitad de la latencia. Falta lo que las puertas no miden, que suene a la marca: una segunda corrida y una semana de aprobaciones comparadas por modelo en Langfuse antes de cambiarlo.

**Hashtags:**

| Tarea | Actual | Candidato | Resultado |
|---|---|---|---|
| Clasificar (95 etiquetas) | Haiku 4.5: 96,8 %, $0.022 | Haiku 5.5 `low`: 96,8 %, $0.0033 | Igual de preciso, casi 7 veces más barato |
| Elegir (15 marcas) | Sonnet 5: precisión 0,917, recall 0,869, 1 trampa | Sonnet 5.5: 0,976, 0,905, 0 trampas, más barato y rápido | Mejor en todo |

Haiku 5.5 eligiendo: precisión 0,917, recall 0,798, $0.0006 por marca. Barato, pero encuentra menos.

**Gasto total del día:** unos $4,40 entre el piloto, las corridas completas y la repetición.

**Lo aprendido al montarlo:**

- **Los ids de los casos son únicos en todo el proyecto**, no por dataset, y borrar un caso no libera su id. `sync_dataset` compone siempre `dataset:caso`.
- **El SDK etiqueta los experimentos con el entorno `sdk-experiment`**, por encima del `eval` que pedía el plan. Para filtrarlos en Langfuse, usar ese.
- **Un corte de red de tres minutos** tumbó 9 llamadas de una configuración. Los evaluadores lo cuentan como error, así que una corrida con errores se repite antes de compararla.

### 7.2 Resultados de la fase 6 (2026-10-14)

Una corrida por configuración. Detalle en el README de cada carpeta de `packages/api/evals/`: `referentes_ai`, `brief_ai`, `scenes_ai` y `voice_ai`.

**Referentes** (4 marcas, 164 cuentas reales etiquetadas, receta `just eval-referentes`):

| Configuración | Precisión | Recall | Trampas | $ total |
|---|---|---|---|---|
| Sonnet 5 `low` (producción) | 1,000 | 0,758 | 0 | 0.142 |
| Sonnet 5.5 `low` | 1,000 | 0,735 | 0 | 0.130 |
| Haiku 5.5 `low` | 1,000 | 0,799 | 0 | 0.013 |

- **Haiku 5.5 es candidato fuerte**: cero trampas, el mejor recall y 11 veces más barato. Falta la segunda corrida de §6.3.
- **El recall bajó para los tres frente a septiembre (0,926).** No es el harness: `run_eval.py` sin Langfuse dio 0,78 el mismo día. Casi todo viene de la tienda de celulares, donde los modelos descartan creadores tech que publican en inglés por «público internacional». Se arregla en el prompt, que es un cambio de producción pendiente.

**Documentos del Brand Kit** (8 documentos de marcas ficticias, `just eval-documentos`):

| Configuración | Cobertura | Recall | Precisión | Inventados | $/doc | p50 |
|---|---|---|---|---|---|---|
| Sonnet 5 `medium` (producción) | 0,982 | 0,979 | 0,984 | 0 | 0.0086 | 6,8 s |
| Sonnet 5.5 `medium` | 0,961 | 0,958 | 0,954 | 1 | 0.0087 | 5,6 s |

**Producción se queda en Sonnet 5.** Mismo precio, y Sonnet 5.5 inventó un campo en el manual que lleva el lema de un competidor como trampa. El plan pedía 15–20 documentos reales anonimizados; se empezó con 8 ficticios para no subir documentos de tenants.

**Escenas de imagen** (10 escenas sin fotos en feed 1:1, feed 4:5, story y reel, `just eval-escenas`): Seedream 5.0 lite entregó las 10 al tamaño exacto, sin errores, por $0.35 en total y 38 s de mediana. **El veredicto es humano y está pendiente**: las diez esperan puntuación en la cola «Revisión de imagen y video». La comparación con fotos frente a sin fotos queda para cuando haya fotos de producto de prueba.

**Grabaciones de voz** (6 grabaciones del corpus de español colombiano de Google, OpenSLR 72, CC BY-SA 4.0; `just eval-voz-audio` las baja y `just eval-voz` corre el experimento):

| Modelo | WER | RTF |
|---|---|---|
| `large-v3-turbo` (producción) | 1,5 % | 0,50 |
| `small` | 7,7 % | 0,18 |

**Producción se queda en `large-v3-turbo`**: cinco veces menos errores y aun así más rápido que el audio. Los errores de `small` cambian el sentido («comen zanahorias» → «comenzan a orias»). Son frases leídas; grabaciones reales de una marca hablando libre completarían el dataset. La primera corrida, con la muestra de TikTok de los tests, no servía: música, inglés y una alucinación de turbo.

**Lo visto en las imágenes** (bajadas con `just eval-escenas-imagenes` a `packages/api/evals/scenes_ai/imagenes/`): en dos formatos cortos la escena deja espacio vacío literal para el texto, y las personas de marcas colombianas salen con rasgos asiáticos. Son hipótesis sobre `ad_scene_prompt` para confirmar en la revisión humana.

**Gasto de la fase 6:** unos $0,95, incluida la repetición de control de referentes. La voz corre en local y no cuesta.

**Lo aprendido:**

- **Para revisar una pieza hay que poder abrirla.** Cada traza del generador lleva ahora en `metadata.borrador` el enlace al borrador en Qualify (`review.draft_url`), así quien revisa en la cola llega a la pieza con un clic.
- **Las imágenes de los experimentos sí se adjuntan a la traza**, como excepción a §9: son marcas ficticias. `observability.media` lo hace explícito y opcional; en producción no se usa.
- **Un caso borrado del archivo local seguía corriendo en Langfuse**, porque un id no se puede liberar. `sync_dataset` ahora archiva los casos que ya no están y `run_experiment` solo corre los activos.
- **En el modo `events_only` de Langfuse v4 la API de puntuaciones no se puede leer.** Para revisar casos concretos, los comentarios de cada puntuación se ven en la interfaz, o se repite el script local sin Langfuse.

### 7.3 Reglas de los experimentos

- **Nunca en la CI.** Cuestan dinero real. Van marcados `integration`.
- **Se lanzan a mano** con recetas como `just eval-copy`.
- **Marcas de prueba** en los datasets. Los documentos reales del Brand Kit entran anonimizados.
- **El harness de `packages/models` no se reescribe.** Sus métricas pasan a ser evaluadores de Langfuse.

---

## 8. Juicio humano

- **Desde Borradores:** aprobar registra `aprobado = 1` y rechazar `aprobado = 0`. Al aprobar con edición, se registra `edicion`. Se engancha en `ContentService.approve` y `reject`, buscando la traza por `draft_id`.
- **Colas de anotación de Langfuse** para las métricas humanas de imagen y video (sección 6.2), con las escalas ya definidas como configuraciones de puntuación.

**Cómo quedó (fase 5, 2026-10-13):**

- **La traza de cada generación tiene un id fijo**, derivado del borrador y su revisión (`review.trace_seed`). Aprobar o rechazar la encuentra sin guardar nada nuevo en la base de datos.
- **Aprobar** registra `aprobado = 1`, `edicion` (0 si no se tocó, hasta 1 si se reescribió, comparando el post tal como se pegaría) y `variante_elegida`. **Rechazar** registra `aprobado = 0` con el motivo, sobre la generación rechazada y antes de que la regeneración cree otra.
- **Cada imagen o video de Seedream o Seedance entra solo en la cola «Revisión de imagen y video»**, con las 8 escalas humanas de §6.2. HeyGen y Remotion no entran.
- **`just langfuse-setup`** crea las 10 escalas y la cola. Se corre una vez por servidor y es idempotente.
- **Verificado contra el servidor local:** una traza con id fijo quedó en la cola como pendiente y con sus tres puntuaciones guardadas.
- **La suite ya no puede enviar trazas a tu Langfuse.** Un `conftest.py` en la raíz apaga el trazado en cada test: algunos módulos cargan el `.env`, que ahora trae las claves.

**Requisito previo resuelto en la misma fase: los largos del copy se hacen cumplir.** Un gancho de más de 60 caracteres hacía fallar la validación, y el borrador entero quedaba como «error del proveedor». Ahora el adaptador pide una sola corrección de los campos pasados y, si aún sobran caracteres, recorta por palabras. El servicio le pasa también los límites impresos (gancho 50, CTA 32) en flyers, plantillas y carruseles.

---

## 9. Privacidad y tenants

- **Un proyecto por entorno, no por tenant.** El tenant va en `metadata`. La separación real sigue siendo RLS en Postgres.
- **Enmascarado en el cliente** con la función `mask` del SDK: correos, teléfonos y tokens.
- **Imágenes y videos: solo la clave de R2**, nunca los bytes. La excepción son los experimentos con marcas ficticias (§7.2), que adjuntan la imagen para poder revisarla.
- **Al autoalojar, los datos no salen de nuestros equipos.** Es la principal ventaja frente a Cloud.

---

## 10. Fases

| Fase | Entregable | Estimación | Depende de |
|---|---|---|---|
| **0. Migración a Opus 5.5** | Hecha | — | — |
| **1. Langfuse local** | **Hecha el 2026-10-13.** `infra/langfuse/`, recetas `just langfuse-*`, proyecto y claves por arranque sin interfaz | — | — |
| **2. Trazas del generador** | **Hecha el 2026-10-13.** `qualify_shared/observability.py`, `qualify_api/creative/observed.py`, traza por borrador, observaciones de Claude, Seedream y Seedance con uso y costo, tests | — | — |
| **3. Trazas del Brand Kit e inbox** | **Hecha el 2026-10-13.** Nueve funciones con `observability.traced`, cada turno de Claude como generación (`claude_tools.messages_create`), respuestas del inbox, Whisper | — | — |
| **4. Primeros experimentos** | **Hecha el 2026-10-13.** Datasets `copy-generador`, `hashtags-clasificar` y `hashtags-elegir`; evaluadores de §6.2; `just eval-copy`, `just eval-hashtags`; resultados en §7.1 | — | — |
| **5. Juicio humano** | **Hecha el 2026-10-13.** Puntuaciones desde aprobar y rechazar; 10 escalas y la cola «Revisión de imagen y video» (`just langfuse-setup`); antes, los largos del copy se hacen cumplir en código | — | — |
| **6. Resto de datasets** | **Hecha el 2026-10-14.** Datasets `referentes-revisar`, `brand-kit-documentos`, `escenas-imagen` y `voz-transcripcion`; recetas `just eval-referentes`, `eval-documentos`, `eval-escenas` y `eval-voz`; resultados en §7.2. Pendiente: la revisión humana de las escenas | — | — |
| **7. Servidor propio** | CX43 en Hetzner con TLS y copias de seguridad | 1 día | Cuando haga falta compartirlo |
| **8. Cascada multimodal** | El harness como experimento | 1 día de código | Golden set etiquetado |

Las fases 1 a 5 suman **6,5 a 9 días**. La fase 4 responde la primera pregunta de negocio: cuánto se puede ahorrar en el copy sin perder calidad.

---

## 11. Riesgos

| Riesgo | Mitigación |
|---|---|
| El SDK v4 de Python (marzo 2026) cambió la API: `start_observation` sustituye a `start_span`/`start_generation`, y `dataset.run_experiment()` a `item.run()` | Escribir contra v4 y fijar la versión en `uv.lock` |
| El SDK v4 exige servidor v4 | Desplegar la imagen v4 en ambas etapas |
| El servidor v4 rechaza trazas por el endpoint clásico de lotes | Usar solo el SDK v4 u OTLP; el endpoint de lotes queda para puntuaciones |
| Choque de puertos con la app | Solo se publica la web en el 3100; el resto queda interno |
| `just down` borra volúmenes | Langfuse vive en su propio compose y su propio proyecto |
| Observaciones sueltas por los hilos del dispatcher | Copiar el contexto al crear el hilo; un test lo comprueba |
| Langfuse caído o lento | El SDK exporta en lote y en segundo plano; el envoltorio traga los errores |
| Pérdida de trazas en la etapa A | Aceptable para pruebas. La etapa B trae copias de seguridad |
| El respaldo de Opus 5.5 subcuenta un intento rechazado a mitad de respuesta | Solo se cobra la respuesta servida. Si `tasa_respaldo` sube, leer `usage.iterations` completo |

---

## Fuentes

Documentación de Langfuse consultada el 2026-10-13:

- [Autoalojamiento con Docker Compose](https://langfuse.com/self-hosting/deployment/docker-compose) y [requisitos](https://langfuse.com/self-hosting)
- [Configuración del autoalojamiento](https://langfuse.com/self-hosting/configuration)
- [Arranque sin interfaz](https://langfuse.com/self-hosting/administration/headless-initialization)
- [Migración del SDK de Python de v3 a v4](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4)
- [Experimentos desde el SDK](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk)
- [Seguimiento de tokens y costos](https://langfuse.com/docs/observability/features/token-and-cost-tracking)
