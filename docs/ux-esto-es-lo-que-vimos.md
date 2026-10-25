# Propuesta de experiencia — «Ya saben de mi marca» en el primer ingreso

`[BORRADOR v2 · ux-designer · 2026-10-25 · épica m-24852192 (PB-5)]` · Pedido del fundador (Herwin, 2026-10-25):
«que viera lo que ya obtuvimos de su perfil para generar esa sensación de asombro al ver que ya me
investigaron y analizaron mi red social y saben cosas de mi marca que solo yo podría saber, eso engancha».

> **Decisiones del fundador (2026-10-25):** opción B1 con confirmación por borrador; frecuencia y «la que más gustó» solo con publicaciones en los últimos 30 días; WhatsApp enmascarado; aviso de TikTok aplazado; flujo largo después de «Aprobar» (la alternativa corta queda descartada). Historias: [épica, §7](epica-prellenado-brand-kit-alta.md#7-ola-2--esto-es-lo-que-vimos-en-tu-instagram).

- Maqueta: [`maquetas/esto-es-lo-que-vimos.html`](maquetas/esto-es-lo-que-vimos.html), 360 px, colores del sistema de diseño.
- Fuente de datos: [`scrapecreators-canales-perfil.md`](scrapecreators-canales-perfil.md) (medido con la CLI el 2026-10-24) +
  código de `main` 12fc775d.
- **v2 (2026-10-25):** se añaden la cuadrícula de publicaciones, los enlaces de la bio, la
  publicación que más gustó, de qué publica y cada cuánto; un caso de cuenta sin publicaciones; y
  una variante de TikTok. Cada dato dice qué cambio de backend necesita (§1).

> Todos los textos nuevos de este documento son **BORRADORES** para que el fundador los apruebe.
> Los cinco textos ya aprobados (§3 PB-5 de la épica) se mantienen **literales**.

---

## 1. Qué podemos mostrar con honestidad

Regla: solo lo que de verdad leemos. El asombro sale de **reconocerse** (sus fotos, sus palabras,
su botón de WhatsApp, sus colores), no de adivinar cosas privadas: Qualify solo ve lo público.

Leyenda del costo — **0** = ya está en la propuesta · **G** = el proveedor ya lo entrega (pagado)
pero hoy lo descartamos: el backend tiene que guardarlo · **R2** = la imagen vence (IG ~4 días,
TikTok ~1–2 días) y hay que copiarla a R2 en el mismo trabajo del Alta (0 créditos) ·
**IA** = una llamada más de Claude · **+1** = un crédito más de ScrapeCreators.

| Dato en pantalla | Instagram | TikTok | Costo | Si no hay datos |
|---|---|---|---|---|
| Foto de perfil | sí | sí | 0 + **R2** (hoy sale vacía) | ícono de la red |
| @usuario, nombre, seguidores | sí | sí | 0 | — |
| Total de publicaciones / videos | sí | sí | **G** (`postsCount` está en la instantánea, no en la propuesta) | se oculta si es 0 |
| Me gusta recibidos en total | no | sí | **G** | se oculta |
| Categoría | en inglés («Bakery»), a veces vacía | no existe | 0, **traducir**; si no hay traducción, no mostrar | se oculta |
| **Así te presentas** (bio citada) | sí | sí | 0 | se oculta |
| **Tus enlaces** («Pedir por WhatsApp», tu web) | `bio_links` | un enlace (`bioLink`) | **G** (hoy solo se guarda `external_url`, vacío en Bianki) | se oculta |
| A qué te dedicas (frase de Claude) | sí | sí | 0 (llamada que ya existe) | pregunta en el paso siguiente |
| Dónde estás | bio + **lugar etiquetado** en publicaciones | bio + lugar etiquetado + región | 0 bio · **G** lugares | solo el país del registro |
| Tu logo = tu foto de perfil · Tus colores | sí | sí | 0 | «Sube tu logo» |
| **Tus últimas publicaciones** (cuadrícula de 6) | 12 ya vienen con el perfil | 10 portadas por página | **G + R2** | no se muestra (ver caso 0) |
| **La que más gustó** | ordenar las 12 por me gusta + comentarios («de tus últimas 12») | `popular`: los 10 más vistos de siempre | IG **G** · TikTok **G + 1 crédito** | se muestra solo con ≥ 3 publicaciones |
| **De qué publicas** (las etiquetas que más usas) | sí | sí | **G** (`topHashtags` está en la instantánea, no en la propuesta) | se oculta |
| **Cada cuánto publicas** | de las 12 fechas | de las 10 fechas | **G** (hoy solo hay una ventana de 7 días que da «0» a casi todos) | se oculta (ver §4 R6) |
| Etiquetas que te sugerimos (+ motivo) | sí | sí | 0 | se ocultan |
| Tono de voz sugerido | de los textos | de los textos | **IA** +1 llamada, solo con ≥ 3 textos | pregunta normal |
| Qué te hace distinto, quién te compra | no está en los datos | no | **IA** (B1, ver abajo) o se pregunta | pregunta normal |

**No se muestra (no disponible o no fiable):** correo, teléfono y dirección de empresa de Meta
(vacíos sin sesión, 4 de 4 cuentas), historias destacadas (0 incluso en una marca de 1 M),
historial de seguidores (el proveedor no lo da: no hay «creciste N»), cuentas parecidas
(vacío 4 de 4; además se siente vigilancia).

**Llamadas de IA y costo** (el tope por Alta sigue pendiente, PB-6; precios sin verificar):

| Opción | Qué da | Costo extra por Alta |
|---|---|---|
| **B1 (recomendada)** — ampliar la llamada de rubro que ya existe para que además redacte «qué te hace distinto», «quién te compra» y una frase de ejemplo, **solo con lo que el negocio escribe** | borradores de las 3 preguntas | misma llamada, +~150 tokens: < US$0,005 estimado |
| **Tono** — una llamada nueva sobre los textos (solo si hay ≥ 3) | los deslizadores de tono ya ajustados | +1 llamada (sube `CallCaps.claude_calls` de 3 a 4); se puede fusionar con B1 y quedar en 0 llamadas extra |
| A — sin IA nueva | el dueño escribe; ejemplos por rubro | 0 |

**Créditos:** Instagram puede bajar a **1 crédito** por Alta (las 12 publicaciones ya vienen en
el perfil). TikTok sube a ~3 si se quiere «tus videos más vistos» de verdad. Las copias a R2 son
~13 descargas al CDN, sin créditos.

**Datos personales (enlaces y teléfonos):** el enlace de WhatsApp se muestra **con el número
enmascarado** («Pedir por WhatsApp · +58 ••• ••12»), se guarda solo en el documento del negocio
(RLS) y nunca en registros ni procedencia; si la cuenta parece personal, no se muestra.

---

## 2. Flujo propuesto (celular, una decisión por paso)

Hoy: tarjeta → «Aprobar» → cae en «Paso 2 de 5 · Tu negocio y rubro» con «Listo. Guardamos tu
identidad de marca.» encima de dos campos vacíos. Se lee como «¿no estaba hecho?». Al aprobar
quedan completos Tus redes, Tu logo y Tus colores; faltan «¿Qué te hace distinto?», «¿Quién te
compra?» y la frase de «Cómo hablas».

### Pantalla 1 — «Esto es lo que vimos en tu {red}» (asombro)
Igual para Instagram y TikTok; cambian las palabras («publicaciones» / «videos») y se ocultan
los bloques sin datos. Orden de arriba abajo:
1. Aviso literal (Instagram). **Para TikTok el aviso aprobado no sirve tal cual** (dice
   «Instagram»): ver la pregunta 4.
2. Cuenta: foto, nombre, seguidores, total de publicaciones (o «me gusta recibidos» en TikTok).
3. **Tus últimas publicaciones**: cuadrícula de 6 miniaturas (3 × 2), con la que más gustó
   marcada con texto («La que más gustó»), no solo con color.
4. Así te presentas (bio citada) · Tus enlaces.
5. Filas con fuente y «Corregir»: A qué te dedicas · Dónde estás · Tu logo · Tus colores.
6. De qué publicas (sus etiquetas) · Cada cuánto publicas · Etiquetas que te sugerimos.
7. Botones literales: **«Aprobar»**, «Cambiar», «Empezar de cero». Nota: «Solo miramos lo que ya
   es público en tu perfil.»

«Corregir» abre el cajón (`drawer`) con un solo campo lleno; cambia la propuesta, no aprueba.

### Pantalla 1, cuenta sin publicaciones (Bianki y la cuenta de Qualify hoy)
Sin cuadrícula, sin «la que más gustó», sin frecuencia, sin «0». Queda lo que sí hay (foto,
bio, enlaces, rubro, lugar, colores) y una línea positiva: «Tu cuenta está empezando. Tus
primeras publicaciones las armamos juntos.» Ninguna cifra en cero.

### Pantalla 2 — después de «Aprobar»: «Te faltan 3 cosas que solo tú sabes»
Arriba literal: «Listo. Guardamos tu identidad de marca.» Lista de lo hecho y lo que falta;
contador **«1 de 3»**, nunca «Paso 2 de 5». Botones: «Responder ahora» / «Lo hago después».

### Pantallas 3, 4, 5 — una pregunta cada una
«¿Qué te hace distinto?» · «¿Quién te compra?» · «¿Cómo le dirías a un cliente que llegó algo
nuevo?». Con B1 llegan con el borrador («Lo escribimos leyendo tus publicaciones. Cámbialo si no
es así.»; en una cuenta sin publicaciones: «Lo escribimos con lo que dice tu perfil.»). Con A,
vacías con un ejemplo según el rubro. Siempre se puede volver atrás.

### Pantalla 6 — «Tu marca está lista»
Resumen corto y el siguiente paso: **«Crear mi primera publicación»** (secundario: «Ver mi
identidad de marca»).

**Alternativa corta:** con B1, las 3 respuestas van como filas más en la Pantalla 1 y «Aprobar»
lo termina todo (de la 1 a la 6 directo).

---

## 3. Textos nuevos (BORRADORES para aprobar)

| Dónde | Instagram | TikTok |
|---|---|---|
| Título P1 | Esto es lo que vimos en tu Instagram | Esto es lo que vimos en tu TikTok |
| Aviso P1 | (literal aprobado) | Preparamos una propuesta de tu identidad de marca a partir de tu cuenta de TikTok @{usuario}. Revísala y apruébala para empezar a crear publicaciones. |
| Cifras | {n} seguidores · {n} publicaciones | {n} seguidores · {n} me gusta recibidos |
| Cuadrícula | Tus últimas publicaciones | Tus últimos videos |
| Fuente cuadrícula | De tu perfil, hoy. | De tu perfil, hoy. |
| Marca en miniatura | La que más gustó | El más visto |
| Fuente «más gustó» | {n} me gusta. De tus últimas 12. | {n} reproducciones. De todos tus videos. |
| Bio | Así te presentas | Así te presentas |
| Enlaces | Tus enlaces | Tu enlace |
| WhatsApp | Pedir por WhatsApp · {número enmascarado} | ídem |
| Fuente rubro | Lo leímos en tu descripción y tus publicaciones. | Lo leímos en tu descripción y tus videos. |
| Fuente lugar (bio) | Lo leímos en tu descripción. | ídem |
| Fuente lugar (etiqueta) | Lo marcaste en {n} publicaciones. | Lo marcaste en {n} videos. |
| Logo | Tu logo: tu foto de perfil | ídem |
| Fuente logo/colores | Salen de tu foto de perfil. | ídem |
| De qué publicas | De qué publicas · Las etiquetas que más usas. | ídem |
| Frecuencia | Publicas unas {n} veces por semana. | Subes unos {n} videos por semana. |
| Sugeridas | Etiquetas que te sugerimos | ídem |
| Enlace por fila | Corregir | ídem |
| Cajón | Corrige este dato · Guardar · Cancelar | ídem |
| Cuenta nueva | Tu cuenta está empezando. Tus primeras publicaciones las armamos juntos. | ídem |
| Privacidad | Solo miramos lo que ya es público en tu perfil. (existe en `PUBLIC_READ_NOTE`) | ídem |
| P2 | Te faltan 3 cosas que solo tú sabes · {n} de 3 · Responder ahora · Lo hago después | ídem |
| P2 lista | Tu cuenta · A qué te dedicas · Tu logo y tus colores · Tus etiquetas · Qué te hace distinto · Quién te compra · Cómo le hablas a tus clientes | ídem |
| Borrador B1 | Lo escribimos leyendo tus publicaciones. Cámbialo si no es así. / Sí, así es / Corregir | …leyendo tus videos… |
| Borrador B1 sin publicaciones | Lo escribimos con lo que dice tu perfil. Cámbialo si no es así. | ídem |
| P5 | Ajustar el tono (opcional) | ídem |
| P6 | Tu marca está lista · Cada publicación que crees va a salir con tu logo, tus colores y tu forma de hablar. Nada se publica sin que lo apruebes. · Crear mi primera publicación · Ver mi identidad de marca | ídem |

Literales que se conservan: el aviso de propuesta (Instagram), «Aprobar», «Cambiar», «Empezar
de cero», «Listo. Guardamos tu identidad de marca.» (y los dos de cuenta ilegible/privada).
«Reproducciones» y «me gusta» son palabras de la app de la red; no son anglicismos.

---

## 4. Riesgos y cómo se corrige en un toque

| # | Riesgo | Mitigación |
|---|---|---|
| R1 | Rubro equivocado | «Corregir» en la fila |
| R2 | Ciudad equivocada (detectada por texto) | Preferir el lugar etiquetado cuando coincide; decir la fuente; «Corregir»; si no hay certeza, solo el país del registro `[H]` |
| R3 | Cuenta equivocada (error en el Alta) | Las miniaturas lo delatan al instante; «Empezar de cero» lleva a Tus redes |
| R4 | Se siente vigilancia | Fuente en cada dato; nota de lo público; sin cuentas parecidas ni competencia; número de WhatsApp enmascarado `[H]` (§5 pregunta 8 del perfil) |
| R5 | Imágenes vacías (URL vencida) | Copiar foto y miniaturas a R2 en el trabajo del Alta; si falla, ocultar la miniatura, nunca un recuadro roto |
| R6 | Cifras que avergüenzan («0 publicaciones», «última hace 4 años», la panadería medida) | Nunca mostrar ceros; frecuencia solo si hubo publicaciones en los últimos 30 días; si no, se omite sin comentario `[H]` |
| R7 | Borradores B1 que inventan | Solo frases del propio texto; vacío si no hay base; eval antes de encender |
| R8 | No sabe que su foto pasa a ser su logo | Fila «Tu logo: tu foto de perfil» con «Corregir» |
| R9 | Categoría en inglés («Bakery») | Traducir con una tabla fija; si no está en la tabla, no mostrarla |
| R10 | Publicación ajena en la cuadrícula (colaboraciones) | Mostrar solo las del dueño de la cuenta (`coauthor` aparte) |

## 5. Qué necesita cada área

- **Backend / creative (`brand_prefill`, `scrapecreators_client`):** guardar en la propuesta,
  sin depender de la red: `pic_r2_key`, `links[]`, `recent_media[]` (con `thumb_r2_key`,
  fecha, me gusta, comentarios, reproducciones, lugar), `top_media_ids` + base («últimas 12» /
  «de siempre»), `top_hashtags`, `posts_count`, `total_likes`, `place_hint{source}`; subir
  `SNAPSHOT_SCHEMA`; IG: leer las 12 del perfil (1 crédito); una función `edit_prefill_field`
  bajo el mismo bloqueo que `approve_prefill`.
- **UI (`brand_proposal.py`, `brand_proposal_vm.py`, `brand_minimal.py`):** con primitivas que
  ya existen: `card`, `callout`, `media_thumb` (cuadrícula y avatar), `tag`, `drawer`, `kv`.
  Cada bloque se oculta sin datos. Tras aprobar, una vista «faltan N» con su propio contador.
- **datasci (PB-6):** medir B1 y tono, y el costo con R2 y TikTok `popular`.

## 6. Preguntas para el fundador

1. ¿B1 (borradores de las 3 respuestas y del tono, en la llamada que ya existe) o que el dueño
   las escriba? Si B1, ¿flujo corto («Aprobar» lo termina todo)?
2. ¿Mostramos «cada cuánto publicas» y «la que más gustó», con las reglas de R6, o solo la
   cuadrícula?
3. ¿El enlace de WhatsApp se muestra (enmascarado) o mejor no?
4. TikTok: ¿aprueba la variante del aviso con «TikTok» en vez de «Instagram»?
