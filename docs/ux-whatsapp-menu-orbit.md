# Chats de WhatsApp: el botón «+» abre las opciones de envío (menú Orbit) (m-24955785)

Especificación de experiencia (ux-designer, 2026-11-06). Decisión del fundador (D7 de
`docs/opciones-conectar-sistema-de-pedidos.md`): en vez de renombrar «Foto o menú», usar el **menú
Orbit** del kit líquido. Un botón en el chat muestra las opciones y cada una abre el panel lateral
directo en su paso. Desaparece el paso «¿Qué le quieres mandar?». Base: `docs/ux-whatsapp-enviar-imagen.md`,
`docs/ux-paso-de-pago.md` §5, `Qualify/whatsapp_tab_chats.py` (`_live_composer`, `_pick_button`,
el `drawer` del selector) y `Qualify/whatsapp_chats_vm.py` (`PICK_*`). Fuera de alcance: los efectos
de pulsado del resto del sistema (épica m-24955828). **Es una propuesta: no se revisó en la app corriendo.**

El Orbit del kit (`reference/liquid-glass/LiquidOS-Studio-v3.0/demos/demo.css` `.orbit-menu`) es un
botón redondo «+» que gira 45° y abre cuatro círculos **solo con icono** en cruz, a 72 px. Se toma
el gesto (el «+» que gira, opciones que brotan del botón, curva `--lq-ease-spring`). La cruz y los
iconos sin texto no se toman: no caben cinco opciones a 375 px y el dueño no debe adivinar un icono.
Se **redibuja** sobre nuestras piezas. `liquidos.css` no se carga (`docs/plan-migracion-liquid-glass.md` D2).

## 1. El botón

- **Dónde:** primera fila del cuadro de respuesta, a la izquierda de «Texto · Botones». Esa fila
  responde a «qué tipo de mensaje mando», y desde ahí las opciones suben sobre los mensajes sin
  tapar el cuadro. La fila de abajo queda solo con «Enviar», a la derecha.
- **Forma:** botón redondo de 44 × 44 px con el material de control. Icono `plus`.
  **Sin texto visible**: el «+» junto al cuadro de escribir es el gesto que el dueño ya conoce de
  WhatsApp (hipótesis, perfil §5 pregunta 6). Las opciones sí llevan siempre texto.
- **Nombre accesible:** «Enviar algo al cliente». Atributos: `aria-haspopup="menu"`,
  `aria-expanded` y `aria-controls`.
- **Estados:**
  - Cerrado: «+».
  - Abierto: el icono gira 45° y queda «×», con tono de acento suave.
  - Deshabilitado (mientras sale un mensaje): igual que hoy.
  - Fuera de las 24 horas el botón no existe (§6).

## 2. Las opciones

Se ven de arriba abajo en este orden, que sigue el de una venta: mostrar, pedir, pagar.

| # | Icono | Texto | Abre el panel en |
|---|---|---|---|
| 1 | `package` | Tus productos | «¿Cuál producto?» |
| 2 | `list` | Tu menú | «Así le llega tu menú» |
| 3 | `wallet` | Formas de pago | «¿Cuál forma de pago?» (con una sola forma, directo a «Revisa y envía») |
| 4 | `images` | Tus piezas | «¿Cuál pieza?» |
| 5 | `smartphone` | Foto del celular | «¿Qué foto?» |

- «Una foto de tu celular» pasa a **«Foto del celular»**: regla de 16 caracteres como máximo por
  texto. El orden es hipótesis (perfil §5 pregunta 6). Se revisa con lo que más mande Bianki.
- **Geometría:** una **columna**, no un arco.
  - Cada opción es una píldora: círculo de icono de 44 px más el texto (tamaño 2, peso medio).
  - Alto de toque de 44 px y separación de 8 px. Alineadas a la izquierda del botón.
  - La columna se apoya sobre el borde superior del cuadro de respuesta y sube.
  - Cinco opciones ocupan 5 × 44 + 4 × 8 = **252 px**.
  - En un celular de 375 × 667 quedan unos 320 px sobre el cuadro, así que caben enteras.
- **Seis o siete opciones (más adelante):** a lo sumo **6 filas** (304 px, cabe a 667).
  - Stickers y Videos cortos (m-24955647) aparecen solo cuando la función exista y el negocio tenga
    algo listo.
  - Si hay de los dos, van en **una** fila: «Stickers y videos» (icono `sticker`). Esa fila abre el
    panel en un paso «¿Qué le mandas?» con las dos tarjetas.
  - Si hay de uno solo, va con su nombre («Stickers» o «Videos cortos»).
  - Así nunca son 7 filas, no hay dos columnas que no entran a 375 px, y los cinco de hoy no se
    agrupan.
  - «Stickers» es la palabra que usa el WhatsApp en español. Se acepta.

```
375 px, abierto                         escritorio, abierto (columna derecha del chat)
┌─────────────────────────────────┐     ┌──────────────────────────────────────────────┐
│ ‹ Chats  María G. [Hasta 5 pm]  │     │ María G.  [Hasta 5 pm] [Respondes tú]        │
│ ┌ ¿tienen shawarma mixto? ┐     │     │ ┌ ¿tienen shawarma mixto? ┐                  │
│ (📦) Tus productos              │     │ (📦) Tus productos                           │
│ (☰) Tu menú                     │     │ (☰) Tu menú                                  │
│ (▣) Formas de pago              │     │ (▣) Formas de pago                           │
│ (▤) Tus piezas                  │     │ (▤) Tus piezas                               │
│ (▯) Foto del celular            │     │ (▯) Foto del celular                         │
│ (×) ( Texto | Botones )         │     │ (×) ( Texto | Botones )                      │
│ ┌─────────────────────────────┐ │     │ ┌──────────────────────────────────────────┐ │
│ │ Escribe una respuesta…      │ │     │ │ Escribe una respuesta…                   │ │
│ └─────────────────────────────┘ │     │ └──────────────────────────────────────────┘ │
│ Al responder, la respuesta...   │     │ Al responder, la respuesta automática...     │
│                       [Enviar]  │     │                                    [Enviar]  │
└─────────────────────────────────┘     └──────────────────────────────────────────────┘
6 filas (más adelante): … (▯) Foto del celular / (✦) Stickers y videos — 304 px
```

## 3. Una opción sin nada que mandar

**Se muestra igual, y el panel abre en el estado vacío de hoy**, con su acción. Ejemplos:
- «Todavía no tienes productos.» con el botón para agregarlos.
- «Aún no cargas tus formas de pago» con [Agregar forma de pago].
- «Tu menú está vacío: agrega productos para poder enviarlo.»

Por qué: el panel ya resuelve esos vacíos y enseña dónde se carga cada cosa. Esconder una opción
haría pensar que se perdió, y obligaría a leer cinco listas cada vez que se toca «+», con
opciones que aparecen y desaparecen. La única excepción son Stickers y Videos cortos (§2), que son
módulos nuevos y por pedido del ticket solo aparecen cuando hay algo listo.

## 4. Atrás y cerrar dentro del panel

Los pasos se renumeran sin el paso 1:

| Opción | Pasos |
|---|---|
| Tus productos, Tus piezas, Foto del celular | 2: elegir → «Revisa y envía» |
| Formas de pago | 2, o 1 si hay una sola forma |
| Tu menú | 1 |

- Con un solo paso **no se muestra «Paso 1 de 1»**, solo el título (N6: M real).
- En el primer paso, el botón de arriba es **«‹ Volver al chat»** y cierra el panel. No reabre el
  Orbit: para cambiar de opción, el dueño toca «+» de nuevo (dos toques).
- En el segundo paso es «‹ Atrás» y vuelve al primero sin perder lo elegido.
- Atrás del celular: un paso atrás; en el primero cierra el panel (N5).
- La dirección pasa a ser `?flujo=enviar&que={productos|menu|pagos|piezas|foto}&paso=N`.
- Al cerrar el panel (Volver, ✕, Esc o fondo) el **foco vuelve al botón «+»**, ya cerrado.
- El título del panel es el del paso («¿Cuál producto?»). Su icono es el de la opción elegida.

## 5. Abrir, cerrar, teclado y movimiento

- **Cierran el Orbit:** tocar fuera, Esc, tocar «×» o elegir una opción. Elegir cierra el Orbit
  y abre el panel en el mismo toque.
- El Orbit **no es un paso**: no escribe la dirección. Si el atrás del celular llega con el Orbit
  abierto, solo lo cierra.
- **Teclado** (patrón de botón de menú; sale gratis de Radix `DropdownMenu`, el mismo del «⋯»):
  - Tab llega al «+».
  - Enter, Espacio o ↓ abren y llevan el foco a la primera opción; ↑ abre y lo lleva a la última.
  - ↑ y ↓ recorren las opciones (dan la vuelta); Inicio y Fin van a la primera y a la última.
  - Enter elige.
  - Esc cierra y devuelve el foco al «+».
  - Tab cierra y sigue.
- **Lector de pantalla:** el botón se anuncia «Enviar algo al cliente, menú contraído o
  expandido». Cada opción es `menuitem` con su texto como nombre; los iconos llevan
  `aria-hidden`.
- **Movimiento:** el «+» gira 45° con `T.SPRING` en `--q-dur`. Las píldoras suben 12 px desde el
  botón con aparición, una tras otra cada 30 ms. Con `prefers-reduced-motion`: el icono cambia a
  «×» sin girar y las píldoras aparecen en su sitio, sin desplazarse ni escalonarse.
- **Pulsado de este botón:** `scale(0.92)` mientras se presiona, como el `.orbit-main` del kit
  (los botones rectangulares usan 0,975, §5.5). Con `prefers-reduced-motion`, sin escala, solo el
  cambio de tono. Las píldoras usan el pulsado de §5.5. El resto lo decide m-24955828.
- **Sin velo oscuro.** Cada píldora lleva el material de capa flotante (`--q-overlay-*`) y su sombra.

## 6. Fuera de las 24 horas

No cambia nada. El cuadro de respuesta entero, con el «+», se reemplaza por lo de hoy
(`_expired_composer`):
- el aviso «Pasaron más de 24 horas desde su último mensaje. WhatsApp solo deja escribirle con
  un mensaje aprobado.»;
- el botón «Enviar un mensaje aprobado».

No hay «+» deshabilitado ni Orbit vacío. Si la ventana se cierra con el Orbit abierto, el Orbit
desaparece con el cuadro.

## 7. Primitiva nueva del sistema de diseño: `orbit_menu`

Aprobada por el fundador al pedir el Orbit por nombre. Va en `Qualify/ui/primitives.py` y se
documenta en `docs/design-system.md` §5.9.

- **Firma:**
  `orbit_menu(label: str, items: Sequence[OrbitItem], *, disabled=False, icon="plus") -> rx.Component`,
  con `OrbitItem(key: str, icon: str, text: str, on_select: EventHandler)`.
- `label` es el nombre accesible del botón. `key` sirve para las pruebas y para `data-orbit-key`.
- Construida sobre `rx.menu` (Radix DropdownMenu): `side="top"`, `align="start"`, sin dar vuelta
  hacia abajo, para que nunca tape lo que está debajo del botón.
- **Reglas de uso:**
  1. **Solo en el cuadro de respuesta de Chats de WhatsApp.** Otra pantalla necesita el visto
     bueno del fundador.
  2. Entre 2 y 6 opciones.
  3. Cada opción lleva icono **y** texto de 16 caracteres como máximo. Nunca solo icono.
  4. Una opción **abre un flujo; nunca envía ni publica** (N13).
  5. Fuera de las condiciones de uso (por ejemplo, ventana cerrada) no se dibuja, en vez de
     deshabilitarse.

## 8. Qué cambia en textos y pruebas

- **Textos que desaparecen:**
  - `PICK_BUTTON_LABEL` «Foto o menú» y `PICK_BUTTON_ARIA`.
  - `pick_heading` («¿Qué le quieres mandar a {nombre}?»).
  - `PICK_HELP_SOURCE` «Elige y revisa antes de enviar. Nada sale sin que toques «Enviar».»
  - Las líneas de `PICK_SOURCE_CARDS` («Una foto con su precio, para que te lo pida.», etc.).
  - `PICK_SOURCE_CARDS` queda como lista de (clave, icono, texto) del Orbit.
- **Textos nuevos:** «Enviar algo al cliente», «Foto del celular», «Stickers y videos» (más adelante).
- **«Nada sale sin que toques «Enviar».»** pasa a la ayuda del paso «Revisa y envía» de las
  opciones que no la tienen, para no perder esa garantía.
- **Pruebas:**
  - `test_whatsapp_chats_picker.py:570-582` deja de esperar «Foto o menú» y «Una foto de tu
    celular». Espera «Enviar algo al cliente», los cinco textos del Orbit y «Volver al chat».
  - `open_picker` se reemplaza por `open_pick(source)`, que abre en el primer paso de esa
    opción: `pick_step == 1` y `pick_total` igual a 2, o 1 para Tu menú. Esto reemplaza las
    aserciones `pick_step == 2` (`:329`, `:497`, `:553`; `test_whatsapp_chats_payments.py:345`).
  - `pick_back()` en el primer paso cierra el panel (`:554-556`).
  - Nuevas: el orden y los textos del Orbit; Esc o elegir cierran; fuera de la ventana no se
    dibuja; con una sola forma de pago abre directo en «Revisa y envía».
  - La prueba a 375 px comprueba que la columna no se cruza con `.q-wa-composer` ni sale de la
    pantalla.
