# Libro de consumo de Claude (m-24955649)

## Qué pasaba

Desde la migración 0105 (m-24823681) existe `consumption_ledger`, pero en producción no tenía
ni una fila (medido el 2026-11-05). La captura de Claude (`_record_anthropic_consumption`)
solo escribía dentro de un `consumption_scope` y **ningún llamador abría uno**: sin negocio
conocido, la grabación no hacía nada y nadie se enteraba. Los topes por llamada en dólares
(`DollarMeter`) sí funcionaban, pero solo en memoria.

## Cómo queda (decisión del fundador, 2026-11-05)

Un único interceptor, en el único punto por donde pasa toda llamada pagada a Claude de
`qualify_api`: `claude_tools.messages_create` (y `create_turn`, que pasa por él).

- `Attribution(tenant_id, feature, brand_id=None, prompt_version=None)` es un argumento
  **obligatorio y sin valor por omisión** de `create_turn` y `messages_create`. Ningún
  llamador puede olvidarlo: sin él la llamada ni se ejecuta, y
  `packages/api/tests/test_claude_attribution.py` recorre todo el repositorio y falla si una
  llamada no lo pasa.
- Después de cada respuesta (también una negativa del modelo: se cobra igual), el
  interceptor escribe **una fila** en `consumption_ledger` por la puerta `tenant_session`
  del negocio (RLS): modelo, revisión y versión de prompt en `metadata`, tokens por tipo,
  `cost_usd` con la tabla de precios `v7` (`pricing_table_version`), `operation` = la
  función, `idempotency_key` = `anthropic:<id de la respuesta>` (una escritura repetida se
  descarta). La escritura es síncrona a propósito y nunca rompe la acción del dueño.
- **«Sin negocio»** (`Attribution.no_business`): solo donde es una decisión — el análisis
  compartido de reels (ADR 44), las evaluaciones y las pantallas que se usan sin sesión de
  negocio (revisión de referentes, rubro, tipografía, etiquetas del texto, menú de
  WhatsApp). El constructor rechaza un `tenant_id` vacío: `no_business` es la única vía. La
  tabla exige `tenant_id`, así que esas llamadas quedan en el log como `WARNING` con todos
  sus campos (`claude consumption sin negocio: feature=… cost_usd=…`). Un test limita
  dónde se puede usar.
- Si la fila no se puede escribir, la acción del dueño sigue: se registra un `ERROR`
  (`claude consumption NOT booked`) con la traza.

### Funciones que se registran (`operation`)

| `operation` | Qué es |
|---|---|
| `wa-suggest` | Sugerir texto del menú de WhatsApp |
| `wa-import` | Leer el menú desde foto, PDF o página |
| `potenciar-contexto` | «Potenciar con IA» en Crear pieza |
| `angulos` | Proponer ángulos visuales |
| `alta-prefill` | Prellenado del Kit de marca en un Alta (rubro + etiquetas) |
| `brand-kit-rubro` | Rubro y etiquetas en el asistente del Kit de marca |
| `brand-kit-documento` | Leer un brief o documento de marca |
| `brand-kit-tipografia` | Detectar la tipografía del logo |
| `brand-kit-tono` | Sugerir el tono a partir de una grabación |
| `hashtags-catalogo` | Elegir etiquetas del catálogo |
| `hashtags-clasificar` | Clasificar etiquetas pendientes del catálogo |
| `hashtags-pie` | Etiquetas para el texto de una publicación |
| `referentes-revision` | Revisar cuentas referentes |
| `reels-revision` | Revisar reels para Descubrir reels |
| `intencion-comentarios` | Intención comercial de comentarios |
| `triaje-comentarios` | Triaje de comentarios para responder |
| `respuesta-comentario` | Borrador de respuesta a un comentario (ruta de sentimiento) |
| `respuesta-publica` | Borrador de respuesta pública con hechos validados |
| `respuesta-cualquier-comentario` | Borrador para cualquier comentario |
| `respuesta-dm` | Borrador de respuesta en Instagram Direct |
| `seguimiento` | Borrador de seguimiento |

## Consulta: total mensual por negocio y por función

Se corre con la puerta de administración (BYPASSRLS), nunca desde la app:

```sql
WITH consumo AS (
    SELECT
        date_trunc('month', created_at AT TIME ZONE 'America/Bogota')::date AS mes,
        tenant_id,
        operation,
        input_tokens + cache_read_tokens + cache_creation_tokens AS tokens_entrada,
        output_tokens AS tokens_salida,
        cost_usd
    FROM consumption_ledger
    WHERE provider = 'anthropic'
)
SELECT
    c.mes,
    t.name AS negocio,
    c.tenant_id,
    CASE WHEN GROUPING(c.operation) = 1 THEN '(total negocio)' ELSE c.operation END AS funcion,
    count(*) AS llamadas,
    sum(c.tokens_entrada) AS tokens_entrada,
    sum(c.tokens_salida) AS tokens_salida,
    round(sum(c.cost_usd), 4) AS usd
FROM consumo c
JOIN tenants t ON t.id = c.tenant_id
GROUP BY GROUPING SETS ((c.mes, t.name, c.tenant_id, c.operation), (c.mes, t.name, c.tenant_id))
ORDER BY c.mes DESC, negocio, usd DESC;
```

Las filas con `funcion = '(total negocio)'` son el total del mes de cada negocio. Lo que no
es de ningún negocio se suma desde el log:
`grep "claude consumption sin negocio" <log de la app> | grep -o "cost_usd=[0-9.]*"`.

## Lo que no se hace

- **Sin relleno desde Langfuse.** Langfuse tiene las trazas de antes, pero sin negocio ni
  marca en cada generación (el `tenant_id` nunca se envió) y con muestras incompletas en
  local: un relleno inventaría la atribución. El libro empieza el día del despliegue.
- `qualify_creative.adapters.anthropic_copy` (`AnthropicCopyAdapter`: el texto, las escenas y
  la selección de recursos de las piezas del generador) llama a Anthropic por su cuenta,
  fuera de `claude_tools`: **no pasa por el interceptor** y no escribe en este libro. Su
  costo sí queda en la procedencia de cada pieza (`cost_usd`). Pendiente: un ticket aparte
  (m-24976796, área del generador) para enrutarlo por el interceptor.
