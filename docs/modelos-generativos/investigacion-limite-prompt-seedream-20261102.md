# Límite de longitud del prompt en Seedream (BytePlus ModelArk) — 2026-11-02

Leyenda: [V] verificado con cita de la doc oficial; [S] inferido. Las citas vienen de WebFetch sobre las páginas `.md` (resumidas por un modelo pequeño: las citas son fieles en lo esencial pero conviene releer el texto exacto antes de citarlo en un ADR).

Base: `https://ai.byteplus.com/ark/region:ap-southeast-1/docs/` + `image-generation-api.md`, `image-generation-tutorial.md`, `seedream-5-0-pro.md`, `seedream-4-0-5-0-prompt-guide.md`, `model-list.md`, `error-codes.md`.

## 1. Longitud del `prompt` en la API de imagen

- [V] `image-generation-api.md`, parámetro `prompt`, viñeta titulada "Prompt length recommendation": "Use no more than 300 Chinese characters or 600 English words." y "Excessively long prompts may scatter information, causing the model to overlook details" (el modelo se centra en lo principal y omite detalles). La página lo etiqueta como recomendación; no describe error, truncado ni corte.
- [V] `image-generation-tutorial.md`: "Keep text prompts under 600 English words." / "Very long prompts may scatter the information, causing the model to overlook details".
- [V] No existe una cifra distinta por modelo: la nota aplica al parámetro `prompt` en general. `seedream-5-0-pro.md` (5.0 pro/flash) no dice nada sobre longitud; `model-list.md` no lista límites de contexto/prompt para ningún Seedream.
- [S] Por tanto: no es un límite duro documentado, es una recomendación de calidad (igual que Seedance 2.x), pero a diferencia de Seedance no es "sin límite": la doc da un número y el motivo (pérdida de detalles). Que no esté documentado un tope duro no prueba que no exista uno en el servidor (p. ej. por tokens, ver sección 4).

## 2. Guía de prompts y referencias

- [V] Guía 4.0-4.5 (`seedream-4-0-5-0-prompt-guide.md`): "using concise and precise prompts is usually better than repeatedly stacking ornate and complex vocabulary"; para imágenes complejas: "describe elements thoroughly to control the output precisely"; estructura: "Use coherent natural language to describe the subject + action + environment". No dice qué se ignora ni da números de longitud ni de referencias.
- [V] Referencias (`image-generation-api.md` y tutorial):
  - Seedream 5.0 pro y 5.0 flash: "support up to 10 reference images".
  - Seedream 5.0 lite, 4.5 y 4.0: "support up to 14 reference images"; en modo batch "Number of input reference images + number of generated images ≤ 15".
- [S] Nuestro `MAX_REFERENCE_IMAGES = 14` es correcto para lite/4.5/4.0 pero excedería el máximo si migramos a 5.0 pro/flash (10).

## 3. Modelos y versiones más nuevas

- [V] Model list / tutorial: `seedream-5-0-260128` (alias también aceptado: `seedream-5-0-lite-260128`, nuestro id), `seedream-4-5-251128`, `seedream-4-0-250828`.
- [V] Más nuevos que 5.0 lite, ya disponibles: `dola-seedream-5-0-pro-260628` ("higher image quality", mejor calidad) y `dola-seedream-5-0-flash-260915` ("generates images faster and costs less"). Ambos con prefijo `dola-`.
- [V] Diferencias de 5.0 pro/flash: máx. 10 referencias; soportan descomposición en capas, edición interactiva y `background` transparente; "Sequential image generation, web search, and streaming output are not currently supported"; tamaños 1K/1.5K/2K (lite: 2K/3K/4K); en la API la mención de recomendación de longitud no cambia.
- [V] Max IPM 500 en todos los Seedream.
- [S] No hay un 5.x posterior anunciado en las páginas leídas (llms.txt lista sólo pro/flash como "5.0 pro / flash").
- [S] Los sufijos de fecha sugieren pro = 2026-06-28 y flash = 2026-09-15; la doc no lo explica.

## 4. Código de error por prompt largo

- [V] `error-codes.md`: no hay código específico para longitud de texto. Lo más cercano: `OutofContextError` (HTTP 400): "Total tokens of image and text exceed max message tokens."; genéricos `InvalidParameter` / `InvalidParameter.{Parameter}` (HTTP 400).
- [S] Esa fila habla de modelos de chat con imagen; no está probado que aplique a Seedream. Un prompt gigante probablemente fallaría con `InvalidParameter.prompt` o se degradaría en calidad, sin confirmación en doc.

## 5. Recomendación

- [S] La doc NO respalda la premisa "Seedream no tiene restricción de longitud": hay una recomendación explícita de ≤300 caracteres chinos / ≤600 palabras inglesas, con degradación de calidad documentada, igual para todos los modelos. No hay tope duro documentado ni error asociado.
- [S] Nuestro tope de 3000 caracteres (~500 palabras en español/inglés) ya queda alineado con las 600 palabras recomendadas; quitarlo sólo se justificaría como "sin rechazo en cliente", no como "la doc lo permite sin coste". Opción prudente: sustituir el recorte duro por un aviso/log al superar ~600 palabras (y dejar que el servidor decida), y validar empíricamente con un prompt largo real (una llamada pagada, requiere aprobación) si el founder quiere eliminar el cap.
- [S] Aparte: si se adopta 5.0 pro/flash, bajar `MAX_REFERENCE_IMAGES` a 10 para esos modelos.
