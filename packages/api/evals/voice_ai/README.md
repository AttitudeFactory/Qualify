# Experimento — transcripción de voz («Tu voz» del Brand Kit)

Compara los Whisper locales que puede correr «Tu voz»: faster-whisper en CPU, sin clave y
a $0. Los candidatos solo se diferencian en precisión y en tiempo. Las métricas viven en
`qualify_api.evals.voice_transcription` y tienen tests offline.

| Configuración | Modelo |
|---|---|
| `large-v3-turbo` (producción) | `deepdml/faster-whisper-large-v3-turbo-ct2` |
| `small` | `small` |

Necesita el grupo `ml` (faster-whisper) y el servidor de Langfuse. Los modelos cargan de la
caché local:

```bash
just langfuse-up
just eval-voz
```

## Métricas

- **WER** (tasa de error por palabra) contra la transcripción de referencia. Se ignoran
  acentos, mayúsculas y puntuación. 0 es perfecto.
- **RTF** (factor de tiempo real): segundos de proceso ÷ segundos de audio. Menos de 1 es
  más rápido que la grabación.

Un caso sin transcripción humana (`reference: null`) se compara contra la transcripción de
`large-v3-turbo`, y su puntuación lo marca (`referencia = modelo`). Eso mide acuerdo entre
modelos, no precisión.

## Grabaciones

Las grabaciones están en `audio/`, que está en `.gitignore`: una voz es un dato personal y
estos WAV pesan unos 31 MB. Las transcripciones sí están en `cases.json`.

Las seis actuales salen del corpus de español colombiano de Google (OpenSLR 72, licencia
CC BY-SA 4.0). Son tres mujeres y tres hombres. Cada grabación une diez frases leídas por la
misma persona, con medio segundo de silencio entre frases, y dura de 46 a 70 segundos. La
referencia es la transcripción humana de esas frases, en el mismo orden.

Para bajarlas en otra máquina:

```bash
just eval-voz-audio
```

Para agregar grabaciones propias:

1. Copia el audio a `audio/`.
2. Agrega el caso a `cases.json` con su transcripción **humana** en `reference`.

Un caso borrado de `cases.json` queda archivado en Langfuse y ya no entra en las corridas.

**Límite de este dataset:** son frases leídas, no habla espontánea como la de «Tu voz».
Sirve para comparar modelos con el acento colombiano. Unas grabaciones reales de la marca
hablando libre lo completarían.

## Resultado — 2026-10-14 (`results/20261014-104357.json`) — ACTUAL

Seis grabaciones con transcripción humana, en CPU.

| Configuración | WER medio | RTF medio |
|---|---|---|
| **`large-v3-turbo` (producción)** | **1,5 %** | 0,50 |
| `small` | 7,7 % | **0,18** |

- **Producción se queda en `large-v3-turbo`.** Comete cinco veces menos errores y aun así
  transcribe en la mitad del tiempo del audio.
- Los errores de `small` cambian el sentido. Ejemplo: «Los hamster comen zanahorias» quedó
  como «Los hamsters comenzan a orias».
- `small` solo tendría sentido en un servidor sin capacidad para turbo. Es casi tres veces
  más rápido.
- Una parte pequeña del WER de `small` no es error real: escribe «70» donde se dijo
  «setenta», y la métrica lo cuenta como palabra distinta. No cambia la conclusión.

## Primera corrida — 2026-10-14 (`results/20261014-070346.json`): sin datos válidos

Solo había una grabación: la muestra de TikTok de los tests de `packages/models`, con
música y en inglés, sin transcripción humana. `large-v3-turbo` alucinó «¡Suscríbete al
canal!» tres veces. Esa muestra ya no forma parte del dataset.
