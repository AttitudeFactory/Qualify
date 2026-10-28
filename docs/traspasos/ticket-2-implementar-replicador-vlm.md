# Ticket 2 — Generador: replicar reel con persona vía VLM (video → descripción → clip)

**Tipo:** Issue (Default Issue)
**Label:** Feature
**Priority:** P2 (bloqueado por ticket 1 — decisión)
**Área:** Generador

## Título

Generador: replicar reel con persona vía VLM (video → descripción → clip)

## Descripción

**Contexto**
BytePlus/Seedance rechaza reels con persona real (`InputVideoSensitiveContentDetected.PrivacyInformation`) y no hay bypass. Para no bloquear la funcionalidad, se implementa un camino alternativo: un VLM lee el reel, extrae su contexto visual en texto y ese texto alimenta la generación del clip en modo `reference/auto` (sin mandar el reel como video). Bloqueado por la decisión del ticket 1 (enfoque, modelo VLM, criterio de frames, muestreo).

**Qué se quiere**
Como operador quiero poder replicar un reel que muestra a una persona, sin que BytePlus lo rechace, aceptando una fidelidad menor (recreación inspirada) cuando el reel tiene persona.

**Propuesta**
- Pre-procesar el reel con shot-boundary detection (un frame por plano) — gratis, local.
- Mandar esos frames al VLM (modelo según ticket 1) con prompt de extracción de estructura visual: planos ordenados con duración, escena, colores, acciones, composición, ritmo.
- Inyectar la descripción en el prompt del modo `reference/auto` (no `edit`), sin mandar el reel como `reference_video`.
- Si el enfoque es híbrido (B): intentar `edit` primero; si BytePlus devuelve `PrivacyInformation`, fallback automático a VLM→texto.
- Mejorar el mensaje al operador para el caso de reel con persona (hoy dice "fotos").

**Criterios de aceptación**
- [ ] Un reel con persona se replica sin error de BytePlus (no se manda el video como input).
- [ ] La descripción generada por el VLM se inyecta en el prompt de generación del clip.
- [ ] El modo `edit` sigue funcionando para reels sin persona (fidelidad alta).
- [ ] El costo por replicación queda dentro del rango estimado (Sonnet 5.5: ~$0.02–0.10 por reel).
- [ ] El mensaje al operador es claro cuando el reel tiene persona (español, beneficio).
- [ ] Tests unitarios para la extracción de frames y el prompt del VLM.

**Fuera de alcance**
- Cambiar el modo `edit` para reels sin persona.
- Reutilizar un video generado por la propia cuenta (flujo de asset autorizado de BytePlus).

**Referencias**
- Ticket 1 (decisión).
- `packages/creative/src/qualify_creative/media.py`
- `packages/creative/src/qualify_creative/reel_reference.py`
- `docs/traspasos/decision-replicador-vlm-a-texto.md`
