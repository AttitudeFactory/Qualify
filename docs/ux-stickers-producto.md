# Stickers de tu producto: tu shawarma con su mensaje, listo para tus chats

Especificación de experiencia (ux-designer, 2026-11-12). **Propuesta: no se revisó en la app
corriendo** (es un flujo nuevo; la pestaña donde vive sí existe). Base: decisión del fundador del
2026-11-12 (dibujo tierno —estilo *kawaii*— de un producto del dueño, con mensaje, quieto o con
movimiento, pagado por sticker, unos US$0,045, pasa por el presupuesto del mes y por «Por
aprobar», «Pedir otro» con tope). Se apoya en `docs/ux-stickers-videos.md` (tanda de temporada) y
`docs/ux-aprobados-y-menus.md` §2–§4. Sin componentes nuevos: `drawer`, `step_progress`,
`choice_card`, `media_thumb`, `text_field`, `callout`, `tone_badge`, `signal_pill`, `empty_state`,
`skeleton_card`.

> **Actualización del 2026-11-12 (decisiones del fundador, m-25017372).** El costo se muestra
> en **creaciones, nunca en dólares**: «Usa 1 de tus creaciones del mes. Te quedan 12.» y el
> botón «Crear dibujo · 1 creación». En todo este documento, cada precio en dólares se cambia
> por eso (D1 = B). «Pedir otro» **guarda todos los dibujos** para que el dueño elija uno
> (D3 = B), sin tope de cantidad (D2 = C). En el chat y en la biblioteca van **primero los de
> temporada** (D4 = B). Lo que ya está construido y el contrato para la pantalla están en
> [stickers-producto-backend.md](stickers-producto-backend.md).

## 0. La idea en una frase (para el dueño)

**«Tu producto convertido en un sticker tierno que dice "¡Gracias por tu pedido!", para mandarlo
en tus chats.»** El beneficio es que cada pedido se siente atendido con la marca, sin diseñador.

## 1. Dónde vive y cómo convive con la tanda de temporada

WhatsApp › Chats › **Stickers y videos** (`/whatsapp?tab=chats&sub=stickers`). Arriba de la
biblioteca, **dos tarjetas de inicio** (`choice_card` de acción, una debajo de la otra a 375 px),
cada una con su beneficio y su precio a la vista; nunca un solo «Crear» que pregunte después:

| Tarjeta | Línea | Botón | Abre |
|---|---|---|---|
| **Para esta temporada · gratis** | «Stickers y videos con tu logo para saludar en Navidad.» | **Crear para esta temporada** | el `drawer` de hoy (sin cambios) |
| **Tu producto en sticker · unos US$0,05** | «Dibujamos tu producto con un mensaje: "Gracias por tu pedido", "En camino"…» | **Crear sticker de producto** | el `drawer` nuevo (§2) |

- La gratuita va primero (el dueño cuida cada peso); la de pago dice el precio en el título.
- URL propia para cada flujo (N5): `…&sub=stickers&crear=temporada` (hoy) y
  `…&sub=stickers&crear=producto` (nuevo). Atrás del celular cierra el panel, no sale del módulo.
- **Biblioteca:** los stickers de producto forman su propio grupo **«De tus productos»**, sin
  fecha, **arriba de las temporadas** (son para el día a día de los pedidos). Se archivan igual.
- **Por aprobar** (`/drafts?ver=stickers`): grupo **«De tus productos · 2 por aprobar»** junto a
  los grupos de temporada, con la misma tarjeta (§3).
- **En el chat** («+» › Fotos y videos › Stickers de tu marca › «¿Qué le mandas?»): primero
  «De tus productos», luego la temporada actual, luego «De otras temporadas». *Hipótesis* (perfil
  §5, preguntas 5 y 6): que el dueño los mande más en pedidos que en fechas; si en la prueba con
  Bianki no es así, la temporada vuelve arriba.

```
375 px · WhatsApp › Chats › Stickers y videos
┌───────────────────────────────────┐
│ WhatsApp                          │
│ ( Chats | Stickers y videos )     │
│ ┌───────────────────────────────┐ │
│ │ Para esta temporada · gratis  │ │
│ │ Stickers y videos con tu logo │ │
│ │ para saludar en Navidad.      │ │
│ │ [ Crear para esta temporada ] │ │
│ └───────────────────────────────┘ │
│ ┌───────────────────────────────┐ │
│ │ Tu producto en sticker ·      │ │
│ │ unos US$0,05                  │ │
│ │ Dibujamos tu producto con un  │ │
│ │ mensaje: "Gracias por tu      │ │
│ │ pedido", "En camino"…         │ │
│ │ [ Crear sticker de producto ] │ │
│ └───────────────────────────────┘ │
│ De tus productos · 3 stickers   ▾ │
│ Navidad 2026 · 6 stickers, 4 vid ▸│
└───────────────────────────────────┘
```

## 2. El flujo: 4 pasos, una decisión por paso

`drawer` con `step_progress` «Paso N de 4» arriba, **«‹ Atrás»** que no borra nada y el botón
principal abajo, siempre a la vista. Todo viene **ya elegido** para que una segunda vez sea
«Siguiente, Siguiente, Siguiente, Crear».

### Paso 1 de 4 — «¿Qué producto dibujamos?»

- Ayuda: «Elige uno de tus productos. Lo dibujamos tierno, con tus colores.»
- Grilla de 3 columnas de `media_thumb` con nombre debajo (≥ 44 px, una sola elección, `radiogroup`).
  Salen **solo productos con foto** (de Tus productos o una foto aprobada del producto).
- **Ya elegido:** el último producto usado para un sticker; si es la primera vez, el primero del
  orden de Tus productos (el dueño ya lo puso primero por algo).
- Más de 9 productos: campo «Buscar producto» arriba de la grilla, no paginación.
- Botón: **[Siguiente]**.

### Paso 2 de 4 — «¿Qué dice el sticker?»

- Lista de `choice_card` (una sola elección):
  1. **«¡Gracias por tu pedido!»** ← ya elegido la primera vez; después, el último usado.
  2. «Bienvenido»
  3. «En camino»
  4. «Entregado»
  5. «Listo para recoger»
  6. **«Escribir el mío»** → al elegirla aparece `text_field` con etiqueta **«Tu mensaje»**,
     ejemplo **«Por ejemplo: ¡Feliz finde!»**, contador **«0/25»** y tope de 25 caracteres.
- Debajo, una línea fija: «El mensaje sale escrito tal cual, con la letra de tu marca.»
  (*supuesto técnico para creative-engineer*: el texto se pone encima del dibujo con la fuente de
  la marca, no lo escribe la IA; si la IA lo escribe, esta línea se quita porque no se puede
  prometer la ortografía).
- Botón: **[Siguiente]**.

### Paso 3 de 4 — «¿Quieto o con movimiento?»

- Dos `choice_card`:
  - **«Con movimiento»** ← ya elegido — «Se mueve en el chat, como los stickers animados.»
  - **«Quieto»** — «Más liviano: llega rápido aunque la señal sea mala.»
- Si los dos cuestan lo mismo, el precio no se repite aquí. Si un día cuestan distinto, cada
  tarjeta lleva el suyo en el título («Con movimiento · unos US$0,08»).
- Botón: **[Siguiente]**.

### Paso 4 de 4 — «Revisa y crea»

- Resumen en palabras, con la miniatura del producto:
  **«Vamos a dibujar tu Shawarma mixto con el mensaje "¡Gracias por tu pedido!", con
  movimiento.»**
- Bloque de costo (`callout` neutro), siempre antes del botón:
  - **«Cuesta unos US$0,05.»**
  - «Se descuenta de lo que tu plan trae este mes. Te quedan unos US$1,30.» (la segunda frase
    solo si el saldo se conoce; nunca un número inventado).
- Línea de confianza: **«Llega a Por aprobar en unos minutos. Nada se manda sin que lo apruebes.»**
- Botón con el precio: **[Crear sticker · unos US$0,05]**. Mientras se revisa el precio:
  «Revisando el precio…» y el botón quieto. **Sin precio no hay botón**: nunca se crea sin
  mostrar el costo.
- Al crear: se cierra el panel y sale el aviso «Listo: estamos dibujando tu sticker. Llega a Por
  aprobar.» [Ver Por aprobar].

```
Paso 1 de 4                           Paso 2 de 4
┌───────────────────────────────────┐ ┌───────────────────────────────────┐
│ ‹ Atrás                Paso 1 de 4│ │ ‹ Atrás                Paso 2 de 4│
│ ■■■□□□□□□□□□                      │ │ ■■■■■■□□□□□□                      │
│ ¿Qué producto dibujamos?          │ │ ¿Qué dice el sticker?             │
│ Elige uno de tus productos. Lo    │ │ (•) ¡Gracias por tu pedido!       │
│ dibujamos tierno, con tus colores.│ │ ( ) Bienvenido                    │
│ ┌───────┐ ┌───────┐ ┌───────┐     │ │ ( ) En camino                     │
│ │ [img] │ │ [img] │ │ [img] │     │ │ ( ) Entregado                     │
│ │   ✓   │ │       │ │       │     │ │ ( ) Listo para recoger            │
│ └───────┘ └───────┘ └───────┘     │ │ ( ) Escribir el mío               │
│ Shawarma  Ensalada  Falafel       │ │                                   │
│ mixto     griega                  │ │ El mensaje sale escrito tal cual, │
│                                   │ │ con la letra de tu marca.         │
│ [          Siguiente            ] │ │ [          Siguiente            ] │
└───────────────────────────────────┘ └───────────────────────────────────┘

Paso 2 · «Escribir el mío»            Paso 4 de 4
┌───────────────────────────────────┐ ┌───────────────────────────────────┐
│ (•) Escribir el mío               │ │ ‹ Atrás                Paso 4 de 4│
│ Tu mensaje                        │ │ ■■■■■■■■■■■■                      │
│ ┌───────────────────────────────┐ │ │ Revisa y crea                     │
│ │ ¡Feliz finde!                 │ │ │ [img] Vamos a dibujar tu Shawarma │
│ └───────────────────────────────┘ │ │ mixto con el mensaje "¡Gracias    │
│ Por ejemplo: ¡Feliz finde! 13/25  │ │ por tu pedido!", con movimiento.  │
│                                   │ │ ┌───────────────────────────────┐ │
│                                   │ │ │ Cuesta unos US$0,05.          │ │
│                                   │ │ │ Se descuenta de lo que tu plan│ │
│                                   │ │ │ trae este mes. Te quedan unos │ │
│                                   │ │ │ US$1,30.                      │ │
│                                   │ │ └───────────────────────────────┘ │
│                                   │ │ Llega a Por aprobar en unos       │
│                                   │ │ minutos. Nada se manda sin que lo │
│                                   │ │ apruebes.                         │
│ [          Siguiente            ] │ │ [ Crear sticker · unos US$0,05  ] │
└───────────────────────────────────┘ └───────────────────────────────────┘
```

## 3. En «Por aprobar»: aprobar o pedir otro

- Grupo **«De tus productos»**; mientras se dibuja, `skeleton_card` «Dibujando…».
- Tarjeta: vista previa cuadrada (con movimiento se anima a la vista; con
  `prefers-reduced-motion`, al tocar), `tone_badge` **«Sticker»**, y debajo
  **«Shawarma mixto · ¡Gracias por tu pedido!»**.
- Botones **[Aprobar]** y **[Pedir otro]**, más la línea **«Puedes pedir 2 más.»**
- «Pedir otro» confirma siempre el costo: «Pedir otro cuesta unos US$0,05. ¿Lo creamos?»
  [Sí, crear otro] [Cancelar] (el texto de hoy, `another_ai_question`). El nuevo **reemplaza**
  al anterior en la tarjeta; mismo producto, mensaje y tipo.
- **Tope:** 3 dibujos por sticker (el primero + 2 «Pedir otro»; *número a confirmar por el
  fundador*, D2). Agotado: el botón desaparece y queda «Ya pediste 3. Aprueba este o crea uno
  nuevo con otro mensaje.» [Crear otro sticker] (abre el flujo con producto y mensaje ya elegidos).
- Aprobar: aviso de hoy, «Listo: ya lo puedes mandar en tus chats.» [Ver aprobados]. Lo no
  aprobado **nunca** aparece en el chat.

```
375 px · Por aprobar › Stickers
┌───────────────────────────────────┐
│ De tus productos · 1 por aprobar  │
│ ┌───────────────────────────────┐ │
│ │        [ dibujo animado ]     │ │
│ │ Sticker                       │ │
│ │ Shawarma mixto ·              │ │
│ │ ¡Gracias por tu pedido!       │ │
│ │ [  Aprobar  ] [ Pedir otro ]  │ │
│ │ Puedes pedir 2 más.           │ │
│ └───────────────────────────────┘ │
└───────────────────────────────────┘
```

## 4. Vacíos y errores (cada uno dice qué hacer)

| Caso | Dónde se dice | Texto | Acción |
|---|---|---|---|
| **Ningún producto con foto** | Paso 1, `empty_state` (no un error al final) | «Para dibujar tu producto necesitamos una foto de él.» · «Sube la foto en Tus productos y vuelve aquí.» | [Ir a Tus productos] (`/catalog`) |
| Algunos productos sin foto | Paso 1, al pie de la grilla | «3 productos no salen porque no tienen foto.» | enlace «Agregar fotos» (`/catalog`) |
| **Presupuesto del mes agotado** | En la tarjeta de inicio (§1) **antes** de abrir el flujo, y en el paso 4 si se agota mientras tanto | «Este mes ya usaste lo que tu plan trae para crear con IA. Vuelve a tener el 1 de diciembre.» | [Crear para esta temporada · gratis] y enlace «Escríbenos y lo revisamos contigo» |
| Alcanza para menos de uno | Paso 4 | «Te quedan unos US$0,02: no alcanza para este sticker.» | igual que la fila anterior |
| **El dibujo no salió** | En la tarjeta de Por aprobar | `signal_pill` warn «No salió» + «Este no salió y no se te cobró. Pide otro.» | [Pedir otro] (no gasta intento ni dinero; *requiere que el backend no cobre ni cuente la falla*) |
| Salió muy pesado para WhatsApp | En la tarjeta | «Muy pesado» + «Salió muy pesado para WhatsApp. Pídelo quieto, que pesa menos.» | [Pedir quieto] |
| No pudimos empezar | `callout` en el paso 4 | «No pudimos empezar a dibujar. No se te cobró. Vuelve a intentarlo en un momento.» | [Intentar de nuevo] |
| No hay precio | Paso 4 | «Ahora no podemos calcular el costo. Vuelve a intentarlo en un rato.» | sin botón de crear |
| **Mensaje muy largo** | Paso 2, bajo el campo | El campo no deja pasar de 25; si se pega algo más largo: «Máximo 25 letras. Prueba algo más corto, como "¡Gracias!".» y el contador «31/25» en aviso (texto, no solo color) | [Siguiente] inactivo hasta corregir |
| Mensaje vacío | Paso 2 | «Escribe el mensaje del sticker.» | — |

## 5. Cómo se muestra el costo (reglas)

1. **Siempre antes de gastar**, en tres lugares: el título de la tarjeta de inicio, el bloque del
   paso 4 y el botón «Crear sticker · unos US$0,05»; y en la confirmación de «Pedir otro».
2. **«unos»** delante: es estimado. Formato de hoy (`usd_label`): «US$0,05», coma decimal, dos
   decimales; el número sale de la tabla de precios vigente, nunca escrito a mano. US$0,045 se
   redondea a «unos US$0,05».
3. **Una sola moneda** (dólares), la misma de la tanda con IA de temporada.
4. Las fallas y lo que no empezó **no se cobran** y se dice («no se te cobró»).

> **Tensión a resolver (D1).** La decisión 8 (2026-10-23, `docs/modelo-cobro-generacion.md` D1)
> dice «el dueño ve creaciones, nunca dinero», y Crear pieza la cumple («tu negocio llegó a su
> límite»). La tanda con IA de temporada y este pedido del 2026-11-12 muestran dólares. Esta
> propuesta sigue el pedido más reciente; la alternativa es «Usa 1 de tus creaciones del mes ·
> te quedan 12» en los mismos tres lugares.

## 6. Textos (todos, para copiar)

- Inicio: «Para esta temporada · gratis», «Stickers y videos con tu logo para saludar en
  {temporada}.», «Tu producto en sticker · unos {costo}», «Dibujamos tu producto con un mensaje:
  "Gracias por tu pedido", "En camino"…», «Crear sticker de producto», «De tus productos».
- Paso 1: «¿Qué producto dibujamos?», «Elige uno de tus productos. Lo dibujamos tierno, con tus
  colores.», «Buscar producto».
- Paso 2: «¿Qué dice el sticker?», «¡Gracias por tu pedido!», «Bienvenido», «En camino»,
  «Entregado», «Listo para recoger», «Escribir el mío», «Tu mensaje», «Por ejemplo: ¡Feliz
  finde!», «{n}/25», «El mensaje sale escrito tal cual, con la letra de tu marca.»
- Paso 3: «¿Quieto o con movimiento?», «Con movimiento», «Se mueve en el chat, como los stickers
  animados.», «Quieto», «Más liviano: llega rápido aunque la señal sea mala.»
- Paso 4: «Revisa y crea», «Vamos a dibujar tu {producto} con el mensaje "{mensaje}", {con
  movimiento | quieto}.», «Cuesta unos {costo}.», «Se descuenta de lo que tu plan trae este mes.
  Te quedan unos {saldo}.», «Llega a Por aprobar en unos minutos. Nada se manda sin que lo
  apruebes.», «Crear sticker · unos {costo}», «Revisando el precio…», «Listo: estamos dibujando tu
  sticker. Llega a Por aprobar.», «Ver Por aprobar».
- Por aprobar: «Dibujando…», «Puedes pedir {n} más.» / «Puedes pedir 1 más.», «Ya pediste 3.
  Aprueba este o crea uno nuevo con otro mensaje.», «Crear otro sticker», «Pedir quieto».
- Errores: tabla del §4.
- **Nunca:** «kawaii» (en pantalla se dice «tierno»), «prompt», «generar», «IA mágica»,
  «automático», «se envía solo». «Sticker» se acepta (así lo dice WhatsApp en español).

## 7. Accesibilidad y celular

- Una columna a 375 px; nada depende de pasar el mouse; objetivos ≥ 44 px.
- Grilla de productos y mensajes: `radiogroup` con nombre accesible «Shawarma mixto» / el mensaje.
- La vista previa lleva `alt` «Sticker de Shawarma mixto que dice ¡Gracias por tu pedido!».
- El contador del mensaje se anuncia (`aria-live="polite"`) solo al pasar de 20.
- Con `prefers-reduced-motion`, nada se mueve hasta tocar.
- Al cambiar de paso, el foco va al título del paso (como el flujo de temporada).

## 8. Qué necesita `reflex-ui-engineer` (y el backend)

1. **UI:** `seasonal_ui.py`/`seasonal_vm.py` — dos tarjetas de inicio en `brand_section()`; un
   `product_sticker_drawer()` de 4 pasos reutilizando `_flow_footer`, `choice_card` y la grilla de
   `_ai_photo`; `?crear=producto` en la URL; grupo «De tus productos» en Por aprobar, Aprobados y
   en «¿Qué le mandas?» (`whatsapp_chats_vm.py`), primero.
2. **Estado:** producto, mensaje (preset o propio, `len ≤ 25` validado en el estado y en el
   backend), quieto/movimiento, último usado (por negocio) para pre-elegir.
3. **Backend / creative-engineer:** precio desde la tabla vigente y saldo del mes antes del paso 4;
   guarda de presupuesto (ADR 41) que frena **antes** de cobrar; falla = sin cobro y sin gastar
   intento; contador de intentos por sticker; procedencia (producto, foto, mensaje, modelo y
   versión del pedido a la IA) en la fila; el texto sobre el dibujo con la fuente de la marca.
4. **Pruebas:** nunca se crea sin precio visible; el botón lleva el costo; «Pedir otro» confirma
   y respeta el tope; una falla no descuenta intento; productos sin foto no salen en el paso 1;
   26 caracteres no pasan; nada sin aprobar llega al chat; `?crear=producto` abre el paso 1.

## 9. Decisiones para el fundador

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| D1 | ¿Dinero o creaciones? | **A** dólares («unos US$0,05») · **B** «1 de tus creaciones del mes» (decisión 8) | **A** por coherencia con la tanda con IA ya en producción y con el pedido del 2026-11-12; si se elige B, cambiar también la tanda. |
| D2 | Tope de «Pedir otro» | **A** 3 dibujos por sticker · **B** 2 · **C** sin tope, solo el presupuesto | **A**: deja comparar sin gastar de más (máximo unos US$0,15 por sticker). |
| D3 | «Pedir otro» ¿reemplaza o guarda los anteriores para elegir? | **A** reemplaza · **B** muestra los 3 y se aprueba uno | **A** para la primera versión (sin patrón nuevo); **B** si en la prueba el dueño extraña el anterior. |
| D4 | Orden en el chat | **A** «De tus productos» primero · **B** la temporada primero | **A**, *hipótesis* a validar con Bianki (perfil §5, preguntas 5 y 6). |
