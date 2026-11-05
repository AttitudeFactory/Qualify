# Chats de WhatsApp: «Foto o menú», en vez de pegar un enlace

> Propuesta de experiencia (ux-designer, 2026-11-04). Pedido del fundador mientras atiende a los
> clientes de Bianki desde `/whatsapp` → Chats: en lugar de pegar un enlace a mano, elegir una foto
> de sus productos o de sus piezas, o mandar el menú completo. Hoy existe solo el modo «Imagen por
> enlace» (`Qualify/whatsapp_tab_chats.py` `_compose_fields`, `COMPOSE_MODES` en
> `Qualify/whatsapp_chats_vm.py`). Reglas: `qualify-ux`, `qualify-copy-es`, `docs/ux-guia-navegacion.md`.
> Sin componentes ni colores nuevos: `drawer`, `stepper`, `choice_card`, `media_thumb`,
> `chat_bubble`, `callout`, `signal_pill`, `empty_state`, `skeleton_card`, `dropzone` y el
> `segmented_control` que la pantalla ya usa.
> **No se revisó en la app corriendo:** es una propuesta de flujo, no una revisión.

## 1. Decisiones

1. **Un botón, no un modo.** «Imagen por enlace» sale del selector (queda «Texto · Botones»). Debajo
   del cuadro de texto aparece **«Foto o menú»** (icono `image-plus`). Se llama así porque una de
   las opciones, el menú, no es una foto: el nombre no promete algo que no pasa.
2. **Se abre en un `drawer`** (pantalla completa en el celular), con el chat detrás. Tres pasos
   como máximo: ① qué mandar → ② cuál → ③ revisa y envía. Un paso, una decisión.
3. **Siempre termina en «Enviar»** tocado por el dueño, con la vista previa del mensaje tal como lo
   verá el cliente (`chat_bubble` de salida). Nada se manda al elegir.
4. **El pie de foto llega escrito y se puede cambiar.** Contador «120/1024» siempre visible.
5. **Las fotos van por WhatsApp, no por enlace.** Qualify sube la foto (`upload_media`) al tocar
   «Enviar»; el dueño nunca ve ni pega una dirección de internet.
6. **Productos sin foto se muestran, al final y marcados «Sin foto».** Esconderlos haría pensar
   que el producto se borró. Al tocarlo se envía **como texto** (nombre, precio, descripción) y se
   ofrece «Agregar una foto» en Tus productos.
7. **Las piezas sin aprobar se pueden enviar, con un aviso que informa y no frena** (§2.2).
8. **Los `#` se quitan del pie de foto de una pieza**: en un chat no sirven y ensucian el mensaje.
9. **Fuera de las 24 horas el botón no aparece**: el chat ya muestra el aviso y «Enviar un mensaje
   aprobado» (`_expired_composer`). Mismo texto, sin palabras nuevas.

## 2. El recorrido del dueño

Cabecera del drawer en todos los pasos: «‹ Atrás» (paso 1: «‹ Volver al chat»), «Paso N de M» y
el título. Si al chat le queda menos de una hora, la píldora que ya existe va bajo el título
(«Puedes escribirle hasta las 5:00 p. m.»). Atrás del celular = paso anterior; en el paso 1 cierra
el drawer y queda en el chat (N5).

**Paso 1 — «¿Qué le quieres mandar a {nombre}?»**
- Ayuda: «Elige y revisa antes de enviar. Nada sale sin que toques «Enviar».»
- Decisión: una fuente (`choice_card`, una por fila, icono + título + una línea):
  - **Tus productos** — «Una foto con su precio, para que te lo pida.»
  - **Tus piezas** — «Lo que ya preparaste para tus redes.»
  - **Tu menú** — «La lista de tus productos para que elija y te pida.»
  - Grupo **Atajos** (aparece cuando hay al menos uno listo; PR 2): **Promoción de la semana**,
    **Cómo llegar**, **Datos de pago**.

### 2.1 Tus productos (3 pasos)

**Paso 2 de 3 — «¿Cuál producto?»** Ayuda: «Toca uno para ver cómo le llega.» Grilla de 2
columnas: foto (`media_thumb`, `alt` = nombre), nombre, precio con `price_label`. Buscador
«Buscar en tus productos» solo si hay más de 8. Los «Sin foto» van al final con `signal_pill`.

**Paso 3 de 3 — «Revisa y envía»**. Vista previa (burbuja con la foto) y debajo el campo
**«Texto que acompaña la foto»** (etiqueta visible), ya escrito:
- Negocio de comida: `«{nombre} — {precio}. ¿Te lo preparo?»` (ej. «Shawarma mixto — $5. ¿Te lo preparo?»).
- Otros rubros: `«{nombre} — {precio}. ¿Te interesa?»` — hipótesis, pregunta 4 del perfil §5.
- Sin precio: se omite «— {precio}». Con descripción: va en una segunda línea si cabe.
- Botón principal **«Enviar»**; mientras sale: «Enviando…»; al terminar el drawer se cierra y la
  burbuja aparece en el chat (el mismo camino que un texto).
- Producto sin foto: la burbuja es de texto y arriba `callout` info: «Este producto no tiene foto:
  le llegará solo el texto.» Enlace secundario «Agregar una foto» (abre Tus productos en el producto).

### 2.2 Tus piezas (3 pasos)

**Paso 2 de 3 — «¿Cuál pieza?»** Selector arriba: **«Aprobadas» · «Sin aprobar»** (por defecto
Aprobadas: aprobadas y publicadas, la más reciente primero, con «Publicada el 2 nov.» o
«Aprobada»). En «Sin aprobar», cada tarjeta lleva la píldora `warn` **«Sin aprobar»** (texto, no
solo color). Solo piezas de foto en el PR 1; un carrusel muestra su primera foto con «1 de 4 fotos».

**Paso 3 de 3 — «Revisa y envía»**. Texto ya escrito = el texto de la pieza, sin `#`, cortado en la
última frase completa que entre en 1024 caracteres; si se cortó: «Acortamos el texto para que
quepa en WhatsApp.» Si la pieza no está aprobada, encima del botón, `callout` **warn**:
> «Todavía no aprobaste esta pieza. Revísala bien: al tocar «Enviar», tú la apruebas para este chat.»

El botón sigue siendo «Enviar» (sin diálogo extra: el aviso informa, no bloquea).

### 2.3 Tu menú (2 pasos)

**Paso 2 de 2 — «Así le llega tu menú»**. Ayuda: «Es la misma lista que reciben cuando tocan «Ver
menú y pedir». No es una foto: tu cliente toca el botón y elige.» Vista previa: burbuja con el
texto de la lista y el botón de la lista; debajo «{N} productos de Tus productos». Botón **«Enviar
el menú»**. Si hay más productos de los que caben en la lista de WhatsApp, se avisa igual que en
Respuesta automática (mismo texto, lo calcula el motor).

### 2.4 Atajos (PR 2)

- **Promoción de la semana.** La marca vive en la pieza: en el paso 3 de Tus piezas (pieza
  aprobada) hay un enlace secundario «Usar como promoción de la semana». Una sola por negocio; la
  pieza lleva la píldora «Promoción de la semana». El atajo salta directo al paso 3 («Paso 2 de 2»).
- **Cómo llegar.** Usa la dirección de Tu número → Perfil. Una ubicación de WhatsApp necesita el
  punto exacto en el mapa (latitud y longitud), que el perfil no guarda: se agrega una vez en
  Perfil con «Marca tu local en el mapa» (pegar el enlace de Google Maps). Sin punto, se envía la
  dirección como texto con un enlace al mapa. Requiere una llamada nueva del cliente de WhatsApp
  (`send_location`). Vista previa + «Enviar».
- **Datos de pago.** Una foto que el dueño sube una vez en Tu número → Perfil («Tus datos de pago»,
  `dropzone`) y reutiliza. Texto ya escrito: «Estos son nuestros datos de pago. Cuando pagues,
  envíanos la captura y te confirmamos.»

## 3. Pantallas (375 px)

```
① Chat con el botón nuevo
┌─────────────────────────────────┐
│ ‹ Chats  María G.  [Hasta 5 pm] │
│ ┌ ¿tienen shawarma mixto? ┐     │
│ └─────────────────────────┘     │
│ ( Texto | Botones )             │
│ ┌─────────────────────────────┐ │
│ │ Escribe una respuesta…      │ │
│ └─────────────────────────────┘ │
│ [⊕ Foto o menú]      [ Enviar ] │
└─────────────────────────────────┘
② Paso 1 — qué mandar
┌─────────────────────────────────┐
│ ‹ Volver al chat     Paso 1 de 3│
│ ¿Qué le quieres mandar a María? │
│ Elige y revisa antes de enviar. │
│ ┌─────────────────────────────┐ │
│ │ ▣ Tus productos             │ │
│ │ Una foto con su precio...   │ │
│ ├─────────────────────────────┤ │
│ │ ▣ Tus piezas                │ │
│ │ Lo que ya preparaste...     │ │
│ ├─────────────────────────────┤ │
│ │ ☰ Tu menú                   │ │
│ │ La lista de tus productos...│ │
│ └─────────────────────────────┘ │
│ Atajos (PR 2)                   │
│ [Promoción] [Cómo llegar] [Pago]│
└─────────────────────────────────┘
③ Productos (paso 2)                 ④ Revisa y envía (paso 3)
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│ ‹ Atrás               Paso 2 de 3│  │ ‹ Atrás               Paso 3 de 3│
│ ¿Cuál producto?                  │  │ Revisa y envía                   │
│ ┌──────────────┐┌──────────────┐ │  │        ┌──────────────────────┐ │
│ │   [foto]     ││   [foto]     │ │  │        │ [foto shawarma]      │ │
│ │Shawarma mixto││Ensalada César│ │  │        │ Shawarma mixto — $5. │ │
│ │ $5           ││ $4           │ │  │        │ ¿Te lo preparo?      │ │
│ └──────────────┘└──────────────┘ │  │        └──────────────────────┘ │
│ ┌──────────────┐┌──────────────┐ │  │ Texto que acompaña la foto       │
│ │   [▣]        ││   [▣]        │ │  │ ┌─────────────────────────────┐ │
│ │Limonada      ││Combo Vecino  │ │  │ │Shawarma mixto — $5. ¿Te lo..│ │
│ │$1 [Sin foto] ││$7 [Sin foto] │ │  │ └─────────────────────── 34/1024┘
│ └──────────────┘└──────────────┘ │  │ [            Enviar           ] │
└─────────────────────────────────┘  └─────────────────────────────────┘
⑤ Piezas sin aprobar (paso 2 y 3)    ⑥ Tu menú (paso 2 de 2)
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│ ‹ Atrás               Paso 2 de 3│  │ ‹ Atrás               Paso 2 de 2│
│ ¿Cuál pieza?                     │  │ Así le llega tu menú             │
│ ( Aprobadas | Sin aprobar )      │  │ Es la misma lista de «Ver menú y │
│ ┌──────────────┐┌──────────────┐ │  │ pedir». No es una foto: toca el  │
│ │ [foto]       ││ [foto]       │ │  │ botón y elige.                   │
│ │ [Sin aprobar]││ [Sin aprobar]│ │  │        ┌──────────────────────┐ │
│ │ Martes 2x1   ││ Nuevo combo  │ │  │        │ ¡Hola! Este es el    │ │
│ └──────────────┘└──────────────┘ │  │        │ menú de Bianki.      │ │
│ ── paso 3, encima del botón ──   │  │        │ [ ☰ Ver productos ]  │ │
│ ⚠ Todavía no aprobaste esta      │  │        └──────────────────────┘ │
│ pieza. Revísala bien: al tocar   │  │ 12 productos de Tus productos    │
│ «Enviar», tú la apruebas para    │  │                                  │
│ este chat.                       │  │ [        Enviar el menú       ] │
│ [            Enviar           ] │  └─────────────────────────────────┘
└─────────────────────────────────┘
⑦ Fuera de las 24 horas (ya existe, no cambia)
┌─────────────────────────────────┐
│ ‹ Chats  María G.               │
│          [Solo con mensaje aprob.]
│ ⚠ Pasaron más de 24 horas desde │
│ su último mensaje. WhatsApp solo│
│ deja escribirle con un mensaje  │
│ aprobado.                       │
│ [  Enviar un mensaje aprobado  ]│
│ (no aparece «Foto o menú»)      │
└─────────────────────────────────┘
```

## 4. Vacíos y errores

| Caso | Qué se ve (texto exacto) | Acción |
|---|---|---|
| Ningún producto | `empty_state` «Todavía no tienes productos.» / «Agrégalos una vez y los mandas en un toque.» | «Agregar un producto» (Tus productos) |
| Productos, ninguno con foto | Grilla normal, todos «Sin foto»; arriba `callout` info «Tus productos no tienen foto: se enviarán como texto.» | «Agregar fotos» |
| Ninguna pieza aprobada | En «Aprobadas»: «Todavía no tienes piezas aprobadas.» / «Revisa las que tienes por aprobar o crea una.» | «Ver sin aprobar» · «Crear una pieza» |
| Ninguna pieza | «Todavía no tienes piezas.» / «Crea una con la foto de tu producto en un minuto.» | «Crear una pieza» |
| Menú sin productos | «Tu menú está vacío: agrega productos para poder enviarlo.» | «Agregar un producto» |
| Sin dirección (Cómo llegar) | «Falta la dirección de tu local.» / «Escríbela una vez en Tu número y la mandas cuando te pregunten.» | «Agregar la dirección» → Tu número › Perfil |
| Sin foto de pago | «Todavía no subiste tus datos de pago.» / «Súbela una vez y la reenvías en un toque.» | «Subir mis datos de pago» → Perfil |
| Cargando | `skeleton_card` con la forma de la grilla, nunca un spinner | — |
| Falló la subida o el envío | `callout` error encima del botón: «No pudimos enviar la foto. Revisa tu conexión y vuelve a intentarlo.» El texto escrito se conserva. | «Reintentar» |
| Se cerraron las 24 h mientras elegía | Igual al chat: «No se entregó: pasaron más de 24 horas desde su último mensaje.» + `WINDOW_CLOSED_NOTICE` | «Enviar un mensaje aprobado» (cierra el drawer y abre esa lista) |
| Pie demasiado largo | «El texto admite hasta 1024 caracteres.» (reemplaza «pie de foto», que el dueño no dice) | «Enviar» queda apagado con el motivo al lado |

Accesibilidad: cada tarjeta es un `choice_card` (botón real, `aria-checked`), ≥ 44 px; foto con
`alt` = nombre del producto o título de la pieza; el drawer atrapa el foco y Esc cierra; «Sin
aprobar» y «Sin foto» son texto, no solo color; el contador se lee junto al campo.

## 5. Qué va en cada PR

**PR 1 — Productos, piezas y menú.** El botón «Foto o menú», el drawer con el paso 1 (sin Atajos),
los recorridos 2.1, 2.2 y 2.3, los vacíos y errores de §4 que les tocan, y el retiro de «Imagen por
enlace». Backend: leer productos/piezas del negocio, subir la foto privada de R2 con
`upload_media` y enviar con `send_media(kind="image", media_id=…)`; el menú reutiliza el mensaje
del nodo «productos» del motor de menús. Solo piezas de foto.

**PR 2 — Atajos.** Marca «Promoción de la semana» en la pieza, «Cómo llegar» (punto en el mapa en
Perfil + `send_location` nuevo, con la salida de texto), «Datos de pago» (subida en Perfil). Piezas
de video (límite de WhatsApp de 16 MB) cuando haga falta.

Para `reflex-ui-engineer`: los textos de §2 y §4 van como constantes en `whatsapp_chats_vm.py`
junto a las que ya existen (`WINDOW_CLOSED_NOTICE`, `MAX_CAPTION_CHARS`); el pie se arma con una
función pura (nombre, precio, rubro → texto) con prueba unitaria; los pasos usan `stepper` dentro
de `drawer`, igual que el Planificador.

## 6. Preguntas para el fundador

1. **Enviar una pieza sin aprobar, ¿la aprueba también para tus redes?** Esta propuesta dice que
   no: vale para ese chat y la pieza sigue en Por aprobar. Si debe quedar aprobada, el aviso cambia
   a «…al tocar «Enviar», también queda aprobada para tus redes».
2. **¿Agregamos «Una foto de tu celular» como cuarta opción del PR 1?** Es lo que cualquiera espera
   de WhatsApp, sale barato (`dropzone` + `upload_media`) y reemplaza mejor al enlace que hoy usa el
   equipo. Sin ella, el enlace se pierde del todo.
3. **¿La promoción de la semana vence sola a los 7 días?** Propuesta: sí, con aviso en el chat
   «Tu promoción de la semana venció: elige otra» para no mandar un 2x1 que ya terminó.
