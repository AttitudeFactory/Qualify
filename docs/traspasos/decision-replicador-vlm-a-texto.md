# Decisión pendiente: replicador de reels con VLM a texto (m-24820836)

**Fecha:** 2026-10-27
**Rama:** `feat/m-24820836-replica-fiel` (trabajo local sin commitear)
**Estado:** investigación terminada; falta la decisión del fundador antes de implementar.

---

## Contexto: por qué se necesita una decisión

El replicador de reels hoy usa el **modo `edit`** de BytePlus Seedance 2.5: manda el
reel como `reference_video` y el modelo lo edita in-place reemplazando producto y marca.
El flujo funciona, pero BytePlus empezó a **bloquear reels que muestran una persona real**
con el error:

```
ArkAPIError: HTTP 400 InputVideoSensitiveContentDetected.PrivacyInformation:
The request failed because the input video 'content[3]' may contain real person.
```

Investigación confirmada (alta confianza, doc oficial de ModelArk leída directamente):

- **No existe parámetro para desactivar ni relajar el filtro.** Es un bloqueo duro del
  proveedor. Doc textual: *"Seedance 2.5 does not support directly uploading reference
  images or videos containing real human faces."*
- **No es específico del modo `edit`.** Aunque bajemos a `reference`/`auto`, el mismo reel
  con persona sería bloqueado igual (el filtro aplica a todos los videos de referencia de
  Seedance 2.x).
- El filtro **no se disparaba antes en `edit`** → BytePlus lo empezó a enforcear sobre el
  video de entrada de la tarea edit. No es un bug nuestro ni del cambio de prompt/copy.
- Las 3 vías sancionadas por BytePlus (reels sin persona, reusar un video generado por la
  propia cuenta en 30 días, asset autorizado de persona real con consentimiento + empresa +
  plan Advanced Entry) **no resuelven el caso "replicar un reel de Instagram que tiene una
  persona"**.

Hoy cada intento fallido cuesta **~$0.064 en Opus 5.5** (copy) + el crédito de Seedance
(~$0.05–0.15 por reel de 5s) → **~$0.12–0.22 perdidos por intento**.

---

## La idea del fundador (alternativa al bloqueo)

En lugar de mandar el reel como `reference_video` (que triggerea el filtro), **un VLM de
Anthropic mira el reel, extrae su contexto visual en texto** (planos, escena, colores,
acciones, ritmo, composición) y **ese texto se manda a generar el clip** en modo
`reference`/`auto`, **sin mandar el video** a BytePlus. El VLM hace de puente:
video → texto → generación. BytePlus nunca ve el video original, así que el filtro nunca
se dispara.

**Trade-off clave (que el fundador debe aceptar):** esto **no es una réplica fiel
cuadro a cuadro**. El modo `edit` usa el reel como lienzo literal; el modo
VLM→texto genera desde cero guiado por la descripción → el clip **se parece** al reel
pero es una **recreación inspirada**, no una réplica. Cambia el producto: pasa de
"réplica fiel" a "recreación con la estructura del reel".

---

## Costo por análisis de reel (VLM de Anthropic)

Parámetros reales de un reel de Instagram promedio: **1080×1920 vertical, 30 fps**.
Frame normalizado para el VLM: ~720×1280 → **~1.548 tokens por frame**.
Output (descripción estructurada): ~350 tok (15s) / ~500 tok (30s).

### Costo con muestreo uniforme 1 fps (referencia, no recomendado)

| Modelo | 15s (15 frames) | 30s (30 frames) |
|---|---|---|
| Opus 5.5 ($4/$20) | ~$0.100 | ~$0.196 |
| Sonnet 5.5 ($2/$10) | ~$0.050 | ~$0.098 |
| Haiku 5.5 ($0.10/$0.50) | ~$0.0025 | ~$0.0049 |

### Costo con shot-boundary detection (1 frame por plano — recomendado)

Un reel de IG típico tiene **3–8 planos** (gancho → desarrollo → cierre), no 30.
Detectar los cortes es **gratis** (cómputo local con `PyAV`/`opencv` que ya están en el
repo) y entrega un frame por plano, en orden, con la duración de cada corte.

| Modelo | 15s (~4 planos, ~6.300 tok input) | 30s (~6 planos, ~9.400 tok input) |
|---|---|---|
| Opus 5.5 | ~$0.026 | ~$0.039 |
| Sonnet 5.5 | ~$0.013 | ~$0.020 |
| Haiku 5.5 | ~$0.0007 | ~$0.0010 |

**6–8× más barato que 1 fps y más fiel** (cada frame representa un plano real, no un
momento arbitrario). El cache apenas ayuda aquí porque los frames cambian por reel.

---

## Criterios para elegir los frames del reel

| # | Criterio | Captura | Costo | Fidelidad | Nota |
|---|---|---|---|---|---|
| 1 | **Shot-boundary detection** (1 frame por corte) | Planos, orden, duración | Bajo (3–8 frames) | **Alta** | **Recomendado.** Ya tenemos `PyAV`. Gratis el cómputo. |
| 2 | Clustering por similitud visual (medoide por cluster) | Agrupa parecidos | Bajo-medio | Alta | Útil si hay transiciones suaves sin cortes duros. |
| 3 | Anclas fijas (primero/medio/último = 3 frames) | Apertura y cierre | Muy bajo | Media-baja | Se pierde el desarrollo del medio. Solo reels muy simples. |
| 4 | Muestreo uniforme por tiempo (1 fps) | Distribución temporal | Alto (15–30 frames) | Media | Malgasta frames (muchos del mismo plano) y se salta planos cortos. |
| 5 | Selección por nitidez/acción (peak por plano) | Lo más nítido de cada plano | Bajo | Alta | Sobrecomplica sin aportar a "describir estructura". |

---

## Modelos VLM de Anthropic (comparativa)

| Modelo | ID | Input $/MTok | Output $/MTok | Calidad visual | Latencia | Recomendación |
|---|---|---|---|---|---|---|
| Opus 5.5 | `claude-opus-5-5` | $4.00 | $20.00 | Excelente | Lenta | Overkill para describir escenas. Solo si querés máxima calidad sin importar costo. |
| Sonnet 5.5 | `claude-sonnet-5-5` | $2.00 | $10.00 | Muy buena | Rápida | **Recomendado.** Punto dulce calidad/costo. Descripción visual prácticamente igual a Opus por la mitad. |
| Haiku 5.5 | `claude-haiku-5-5` | $0.10 | $0.50 | Buena, más superficial | Muy rápida | Si priorizás costo (20× más barato), aceptando descripción más genérica y fidelidad menor. |

---

## Opciones de implementación (A o B)

### A — Siempre VLM→texto (un solo camino)

Un solo flujo: VLM describe el reel → texto alimenta el modo `reference`. El modo `edit`
se deja de usar para replicación.

- **Pros:** simple, un solo camino, ningún reel se bloquea por persona.
- **Contras:** pierde la fidelidad del `edit` **incluso para reels sin persona**. Todos los
  reels pasan a ser "recreación inspirada".
- **Costo extra por replicación:** ~$0.013 (Sonnet, 15s) a ~$0.020 (Sonnet, 30s).

### B — Híbrido: `edit` primero, VLM→texto como fallback (recomendado)

Intentar `edit` primero (fidelidad alta). Si BytePlus lo bloquea por
`PrivacyInformation` (persona detectada), **fallback automático** a VLM→texto.

- **Pros:** reels **sin persona** siguen siendo réplica fiel (alta fidelidad); reels **con
  persona** se recrean (fidelidad menor pero funciona). Mejor producto.
- **Contras:** más trabajo de implementación (detectar el error de BytePlus, rerutear al
  VLM, regenerar el prompt en modo `reference`). Los reels con persona pagan doble llamado
  (el fallido de BytePlus cuesta el crédito + el VLM), pero hoy ya pagan eso y más.
- **Costo extra:** solo para reels con persona (~$0.013–0.020 VLM + el crédito de Seedance
  del intento fallido). Reels sin persona: $0 extra.

### Variante B′ — pre-check de persona (opcional, complemento de B)

Antes de mandar a BytePlus, un VLM barato (Haiku 5.5) clasifica "¿hay persona?".
Si sí, ir directo a VLM→texto sin intentar `edit` (evita pagar el crédito de Seedance
del intento fallido).

- Pre-check con Haiku 5.5: **~$0.0009 por reel** (5 frames, prompt corto).
- Ahorra los ~$0.05–0.15 de crédito de Seedance por cada reel con persona.

---

## Decisión que se necesita del fundador

1. **Opción de implementación:** ¿**A** (siempre VLM→texto), **B** (híbrido, recomendado)
   o **B′** (híbrido + pre-check de persona con Haiku)?
2. **Modelo VLM para extracción de contexto:** ¿**Sonnet 5.5** (recomendado), **Haiku 5.5**
   (más barato, menos fiel) o **Opus 5.5** (máxima calidad, más caro)?
3. **Criterio de muestreo de frames:** ¿**shot-boundary detection** (recomendado,
   1 frame por plano) o **1 fps uniforme** (más caro, menos fiel)?
4. **Aceptar el trade-off de producto:** ¿se acepta que los reels con persona pasen de
   "réplica fiel" a "recreación inspirada en la estructura del reel"?

---

## Trabajo ya hecho en esta rama (sin commitear)

- **`Qualify/reel_replication.py`** — `replication_topic` → `replication_context`, texto
  reformulado (reel como estructura de segundo plano, marca de primer plano).
- **`Qualify/creative_state.py`** — campo `replication_context`, merge en
  `_effective_topic`, separación del flujo «Potenciar con IA».
- **`packages/api/.../creative/media.py`** — `reel_edit_prompt` reescrito para que el
  contexto merged llegue al video como instrucción de producción.
- **`packages/creative/.../brand/render.py`** — guard en el copy prompt para que las
  instrucciones de escena no caigan en el caption (excepción solo si el operador lo pide
  textualmente).
- Tests offline pasando (141 + 155), lint limpio.

Esto **no toca** el flujo VLM→texto (la decisión pendiente). Es trabajo previo sobre el
prompt/copy que queda válido independientemente de la decisión.

---

## Servidores corriendo (al cierre de este ticket)

- **Reflex** (pane `w3:pQ` «Servidor Reflex»): `http://localhost:3000` / backend `:8000`
- **Media server** (pane `w3:pS`): `:8016` + túnel cloudflared vivo
  (`https://marketing-briefly-authorities-plenty.trycloudflare.com`)
- **Compose:** postgres, redis, render — healthy
- **Sin push, sin commit** — trabajo local en `feat/m-24820836-replica-fiel`.
