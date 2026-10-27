# Ticket 1 — Generador: decisión de replicador de reels (video → descripción → clip)

**Tipo:** Issue (Default Issue)
**Label:** Documentación
**Priority:** P2
**Área:** Generador

## Título

Generador: decisión de replicador de reels (video → descripción → clip)

## Descripción

**Contexto**
El replicador de reels falla cuando el reel de referencia muestra una persona real: BytePlus/Seedance rechaza el video con `InputVideoSensitiveContentDetected.PrivacyInformation` ("may contain real person"). El filtro no se puede desactivar (doc de Seedance 2.5: "does not support directly uploading reference images or videos containing real human faces"). Hoy el error se muestra al operador de forma confusa ("No podemos usar fotos de personas reales como referencia").

Se propone una vía alternativa: un VLM lee el reel de referencia, extrae su contexto visual (planos, escena, colores, acciones, ritmo, composición) y lo convierte en texto; ese texto alimenta la generación del clip en modo `reference/auto` (sin mandar el reel como video), evitando el filtro.

Detalle completo en `docs/traspasos/decision-replicador-vlm-a-texto.md`.

**Qué se quiere**
Como fundador quiero decidir, antes de implementar, cuál es el enfoque, el modelo VLM y el criterio de selección de frames para el replicador de reels, con los costos y trade-offs claros.

**Propuesta**
Decisión A — Enfoque:
- (A) Siempre VLM→texto (un solo camino; pierde fidelidad del modo `edit` hasta para reels sin persona).
- (B) Híbrido: intentar `edit` primero; si BytePlus bloquea por persona, fallback automático a VLM→texto. (Más trabajo, mejor producto.) ← recomendado.

Decisión B — Modelo VLM:
- Opus 5.5 (~$0.10 / reel 15s, ~$0.20 / 30s): mejor descripción, overkill.
- Sonnet 5.5 (~$0.05 / 15s, ~$0.10 / 30s): punto dulce, recomendado.
- Haiku 5.5 (~$0.0025 / 15s, ~$0.005 / 30s): 20× más barato, descripción más superficial.

Decisión C — Criterio de selección de frames:
- (1) Shot-boundary detection (un frame por plano detectado): ~3–8 frames por reel, recomendado. Más barato y más fiel que 1 fps.
- (2) Diversidad visual por clustering.
- (3) Anclas fijas (primero/medio/último).
- (4) Muestreo uniforme 1 fps.
- (5) Peak (nitidez/acción).

Decisión D — Muestreo: 1 fps vs 0.5 fps (mitad de frames, ~50% menos costo).

**Criterios de aceptación**
- [ ] Queda documentada la decisión (enfoque, modelo, criterio, muestreo) en un ADR o en `docs/arquitectura.md`.
- [ ] Se actualiza el mensaje al operador para el caso de reel con persona (hoy dice "fotos", debería decir "reel").
- [ ] Se abre el ticket de implementación (ver ticket 2).

**Fuera de alcance**
- Implementación del VLM→texto (ticket 2).
- Cambios a BytePlus/Seedance (no hay opción de bypass).

**Referencias**
- `docs/traspasos/decision-replicador-vlm-a-texto.md`
- `packages/creative/src/qualify_creative/media.py` (líneas ~760, ~2519–2523, ~4413)
- `packages/creative/src/qualify_creative/reel_reference.py` (línea 84, redimensionado a 1280px)
- Doc Seedance 2.5: "does not support directly uploading reference images or videos containing real human faces"
