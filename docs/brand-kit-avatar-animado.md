# Brand Kit — «Tu avatar animado» (esquematizado)

`[ESQUEMATIZADO 2026-10-19 · detrás de un interruptor apagado · nunca ejecutado contra BytePlus]`

> Pedido del fundador (2026-10-19): «quiero que cuando termine la creación del brandkit con
> Seedream te haga un avatar animado y que este también se pueda ver al momento de editar
> el brandkit, pero esto déjalo esquematizado porque aún no están las API key para hacerlo».

## 1. Qué es

Una **mascota de la marca**: un personaje ilustrado en estilo de película animada (3D),
de cuerpo entero, centrado y sobre un fondo liso, que representa el negocio. Es una
**imagen fija** que genera **Seedream** (BytePlus ModelArk), no un video. Sale de lo que el
Brand Kit ya sabe:

| Entrada | De dónde sale | Cómo entra al prompt |
|---|---|---|
| Nombre de la marca | `brands.name` (`DbBrandNames`) | entre comillas |
| Rubro, categoría, ubicación | `brand_kit_details.connect` / `profile` (`BrandContext`) | entre comillas, una línea cada uno |
| Posicionamiento y audiencia | `brand_kits` (`BrandKit`) | entre comillas, máximo 180 caracteres |
| Paleta | `BrandKit.palette_rgb` | solo hex válidos, sin repetir, máximo 5: «colores principales del personaje» |
| Tono | los 4 ejes (`ToneAxes`) | coloquial ≥ 60 → actitud relajada; formal ≤ 40 → postura profesional; entusiasta ≥ 60 → sonrisa enérgica; sobrio ≤ 40 → expresión serena; técnico ≤ 40 → un detalle del oficio. «Breve/elaborado» no cambia la imagen |
| Brief del logo | `logo_brief.feeling` / `style` | entre comillas |
| Logo | `brand_kits.logo_asset_key` (R2) | **imagen de referencia** de Seedream: «toma sus formas y colores, no dibujes el logo» |

El prompt siempre termina con «sin texto, sin letras, sin logos, sin marca de agua».
Las instrucciones van en inglés (Seedream las sigue mejor); las palabras de la marca van tal
cual, en español. El constructor es código puro y probado:
`qualify_api.creative.brand_avatar.avatar_inputs` + `build_avatar_prompt`
(`PROMPT_VERSION = "brand-avatar-v0"`).

## 2. Cuándo se genera

- **Al terminar el Brand Kit** (cualquiera de los dos asistentes, `/brand/manual` o
  `/brand/connect`): `brand_finish.save_brand_kit(state, flow)` termina con éxito →
  `brand_avatar_panel.start_brand_avatar(tenant, brand)`.
- **En segundo plano, nunca bloquea el asistente**: se lanza en un hilo
  (`asyncio.to_thread`) como tarea suelta; el operador ya está en Resultados cuando acaba.
  Un fallo nunca hace que terminar el kit parezca fallido (`maybe_generate_after_kit`
  no lanza excepciones).
- **No** se genera al guardar una sección del editor (eso no es «terminar»); para eso está
  «Regenerar».
- Con el interruptor apagado, el gancho no hace nada: no crea tareas, no construye el
  cliente, no lee la base de datos.

## 3. Dónde se guarda

- **La imagen** → R2, dentro del prefijo de la marca:
  `t/<tenant>/brand/<brand>/avatar/<uuid>.jpg` (`image/jpeg`). Clave nueva en cada
  generación: regenerar nunca pisa lo que una página aún esté mostrando.
- **El registro** → `brand_kit_details.logo_brief["brand_avatar"]` (JSONB), con
  `BrandKitStore.save_avatar` / `load_avatar`. **Sin migración.** Va dentro de
  `logo_brief` porque es la imagen de la marca, junto al logo del que sale.
  - Trampa resuelta: los asistentes reescriben `logo_brief` entero en cada guardado; por
    eso `save_details` ahora conserva las claves reservadas (`RESERVED_DETAIL_KEYS`,
    `carry_reserved`) que el llamador no envía.
  - Por qué no `brand_kit_assets`: su `kind` tiene un CHECK (pediría migración) y
    `replace_assets` borra lo que el asistente no conoce en cada guardado.
  - Por qué no `image_assets`: exige un `draft_id`; el avatar no es una pieza.
- **Procedencia** (regla dura del proyecto), en el propio registro: `status`
  (`pending` / `ready` / `failed`), `provider`, `model_id`, `model_revision` (lo que
  ModelArk devuelve, p. ej. `seedream-5-0-260128`), `prompt`, `prompt_version`,
  `cost_usd`, `created_at` y `error` (en palabras del operador).

## 4. Cómo se ve en el editor

En `/brand/kit` → «Editar Brand Kit», la primera tarjeta es **«Tu avatar animado»**
(`Qualify/brand_avatar_panel.py`, `brand_avatar_card`), encima de las secciones. No tiene
«Editar»: es generada.

| Estado | Qué muestra |
|---|---|
| Apagado, sin avatar | texto tenue: «Se creará cuando conectemos la generación de imágenes…». Sin botón |
| Encendido, sin avatar | «Aún no tienes avatar. Pulsa «Regenerar» para crearlo.» + «Regenerar» |
| `pending` | `progress_panel` «Creando tu avatar» (en el Brand Kit las esperas son barra, nunca spinner) |
| `ready` | la imagen (`media_thumb`, 10 rem, enlace `/r2media` de una hora) + «Regenerar» |
| `failed` | `callout` de error + «Regenerar» |

Leer el avatar guardado funciona aunque el interruptor esté apagado (uno dibujado cuando
estaba encendido se sigue viendo). «Regenerar» solo existe con el interruptor encendido.

## 5. Costo

Seedream 5.0 lite: **USD 0,035 por imagen** (tabla de precios v5,
`seedream-5-0-lite-260128`; las imágenes de referencia son gratis y una imagen moderada no
se cobra). Una por Brand Kit terminado + cada «Regenerar». El tope de pre-vuelo por avatar
es `AVATAR_BUDGET_USD = 0,10`: solo bloquea un modelo mal configurado, nunca una corrida
normal. Pasa por el `CreativeRouter` (resolución de llave + estimación antes de llamar).

## 6. Interruptor

- `QUALIFY_BRAND_AVATAR` — **apagado por defecto**. Encendido con `1`/`true`/`yes`/`on`.
- Además necesita `QUALIFY_BYTEPLUS_ARK_API_KEY` (la misma de Seedream y Seedance);
  modelo y URL base reutilizan `QUALIFY_SEEDREAM_MODEL` y `QUALIFY_BYTEPLUS_ARK_BASE_URL`.
- `avatar_unavailable_reason()` dice qué falta (`switch_off` / `missing_key`);
  `generate_brand_avatar` lanza `BrandAvatarUnavailable` **antes** de tocar red, base de
  datos o R2. Las pruebas lo verifican con dependencias que fallan si se tocan.

## 7. Vínculo futuro (no construido)

El avatar podría alimentar el tipo **«Avatar animado»** de `/create`: la mascota como foto
del presentador que **OmniHuman** hace hablar con la voz de la marca (Seed Speech), o como
primer fotograma de un clip de **Seedance**. Queda anotado como posibilidad; no se tocó
`/create`.

## 8. Preguntas para el fundador

1. **«Animado»**: ¿estilo caricatura/película animada (imagen fija, lo esquematizado) o
   que **se mueva** (un clip corto con Seedance/OmniHuman a partir de la imagen)? Lo
   segundo cuesta más por kit (el video se cobra por segundo) y tarda minutos.
2. **3D o 2D**: el prompt pide 3D tipo película animada. ¿Otro estilo (plano, ilustración,
   anime)? ¿Que el operador lo elija?
3. **¿Varias opciones?** Seedream puede generar varias imágenes en una llamada (cada una a
   USD 0,035) para que el operador escoja.
4. **¿Se usa en las piezas?** ¿Debe entrar como elemento del brandboard (y llegar a los
   flyers/videos) o solo verse en el Brand Kit?
5. **¿Regenerar sin límite?** Hoy no hay cupo por tenant; cada clic cuesta USD 0,035.
6. **¿Editar con indicaciones?** Un campo «cámbiale…» que reutilice la imagen actual como
   referencia.

## 9. Checklist cuando lleguen las llaves

- [ ] Poner `QUALIFY_BYTEPLUS_ARK_API_KEY` en el entorno (local y VPS).
- [ ] Una corrida en vivo con un kit real (`generate_brand_avatar` con
      `QUALIFY_BRAND_AVATAR=on`), y fijar en este documento qué devuelve Seedream para un
      prompt de mascota (calidad, si respeta la paleta, si dibuja texto pese a pedirlo).
- [ ] Afinar `build_avatar_prompt` con 5–10 kits reales y subir `PROMPT_VERSION`.
- [ ] Registrar el gasto en el libro de uso (`observed` / `billing.usage_events` cuando
      exista): hoy el costo solo queda en el registro del avatar.
- [ ] Trazar la llamada en Langfuse (`observed.traced_providers`), como las escenas.
- [ ] Traducir errores y moderación de ModelArk a palabras del operador
      (`media.ark_failure_text`).
- [ ] Un `pending` huérfano (el proceso murió a mitad): tratarlo como `failed` pasado un
      plazo (p. ej. 10 min) para que «Regenerar» no quede colgado.
- [ ] Cuando exista el worker (Celery), mover el gancho de tarea suelta en el proceso web a
      una cola.
- [ ] Encender `QUALIFY_BRAND_AVATAR` primero en staging, luego en producción.

## 10. Archivos

- `packages/api/src/qualify_api/creative/brand_avatar.py` — interruptor, prompt, registro,
  orquestación y cableado de producción (`production_deps`, marcado `TODO(keys)`).
- `packages/api/src/qualify_api/creative/brand_kit_store.py` — `save_avatar` /
  `load_avatar` y la conservación de claves reservadas en `save_details`.
- `Qualify/brand_avatar_panel.py` — `start_brand_avatar` (el gancho),
  `BrandAvatarState` y la tarjeta.
- `Qualify/brand_finish.py` — llama al gancho al terminar el kit.
- `Qualify/brand_kit_editor.py` — la tarjeta encima de las secciones.
- Pruebas: `packages/api/tests/test_brand_avatar.py`,
  `Qualify/test_brand_avatar_panel.py`.
