# Chats de WhatsApp: el botón «+» abre las opciones de envío (menú Orbit) (m-24955785)

Especificación de experiencia (ux-designer, 2026-11-06), **propuesta no revisada en la app corriendo**.
Fundador (D7, `docs/opciones-conectar-sistema-de-pedidos.md`): en vez de renombrar «Foto o menú», el
**menú Orbit** del kit; cada opción abre el panel directo en su paso y desaparece «¿Qué le quieres
mandar?». Base: `docs/ux-whatsapp-enviar-imagen.md`, `docs/ux-paso-de-pago.md` §5,
`Qualify/whatsapp_tab_chats.py`, `Qualify/whatsapp_chats_vm.py` (`PICK_*`). Fuera de alcance: los
efectos de pulsado del resto del sistema (m-24955828). Del Orbit del kit (`demos/demo.css`
`.orbit-menu`: «+» que gira 45° y cuatro círculos **solo icono** en cruz) se toma el gesto; la cruz
y los iconos sin texto no (no caben cinco a 375 px y el dueño no adivina iconos). Se **redibuja**
sobre nuestras piezas; `liquidos.css` no se carga (`docs/plan-migracion-liquid-glass.md` D2).

## 1. El botón

- **Dónde:** primera fila del cuadro de respuesta, a la izquierda de «Texto · Botones». Esa fila
  responde a «qué tipo de mensaje mando», y desde ahí las opciones suben sobre los mensajes sin
  tapar el cuadro. La fila de abajo queda solo con «Enviar», a la derecha.
- **Forma:** redondo, 44 × 44 px, material de control, icono `plus`, **sin texto visible**: el «+»
  junto al cuadro es el gesto que el dueño conoce de WhatsApp (hipótesis, perfil §5 pregunta 6).
  Nombre accesible **«Enviar algo al cliente»**, con `aria-haspopup="menu"`, `aria-expanded`, `aria-controls`.
- **Estados:** cerrado «+»; abierto, el icono gira 45° y queda «×» con tono de acento suave;
  deshabilitado mientras sale un mensaje, igual que hoy; fuera de las 24 horas no existe (§6).

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
- **Geometría:** una **columna**, no un arco. Cada opción es una píldora (círculo de icono de
  44 px + texto, tamaño 2, peso medio), alto de toque 44 px, separación 8 px, alineada a la
  izquierda del botón. La columna se apoya en el borde superior del cuadro y sube: cinco ocupan
  5 × 44 + 4 × 8 = **252 px**; a 375 × 667 quedan unos 320 px sobre el cuadro, así que caben.
- **Seis o siete opciones (más adelante):** a lo sumo **6 filas** (304 px, cabe a 667). Stickers
  y Videos cortos (m-24955647) aparecen solo cuando la función exista y haya algo listo. Si hay de
  los dos, van en **una** fila «Stickers y videos» (icono `sticker`) que abre el panel en «¿Qué le
  mandas?» con las dos tarjetas; si hay de uno solo, va con su nombre. Nunca 7 filas ni dos
  columnas (no entran a 375 px), y los cinco de hoy no se agrupan. «Stickers» es la palabra del
  WhatsApp en español: se acepta.

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

Capturas del componente real en una página de prueba (no en el chat con datos; 2026-11-06):
[375 × 667](img/whatsapp-menu-orbit/375x667-open.png) ·
[375 × 568](img/whatsapp-menu-orbit/375x568-open.png) ·
[escritorio](img/whatsapp-menu-orbit/1280x800-open.png). A 375 × 667: «+» de 447 a 491 px,
columna de 181 a 439 px, caja de texto de 500 a 570 px.

## 3. Una opción sin nada que mandar

**Se muestra igual, y el panel abre en el estado vacío de hoy**, con su acción («Todavía no tienes
productos.», «Aún no cargas tus formas de pago» [Agregar forma de pago], «Tu menú está vacío:
agrega productos para poder enviarlo.»).

Por qué: el panel ya resuelve esos vacíos y enseña dónde se carga cada cosa. Esconder una opción
haría pensar que se perdió, y obligaría a leer cinco listas cada vez que se toca «+», con
opciones que aparecen y desaparecen. La única excepción son Stickers y Videos cortos (§2), que son
módulos nuevos y por pedido del ticket solo aparecen cuando hay algo listo.

## 4. Atrás y cerrar dentro del panel

- Pasos sin el 1: Tus productos, Tus piezas y Foto del celular, 2 (elegir → «Revisa y envía»);
  Formas de pago, 2 (o 1 con una sola forma); Tu menú, 1. Con un solo paso **no se muestra «Paso
  1 de 1»**, solo el título (N6: M real).
- Primer paso: **«‹ Volver al chat»** cierra el panel y no reabre el Orbit (para cambiar de
  opción, «+» otra vez: dos toques). Segundo paso: «‹ Atrás» sin perder lo elegido. Atrás del
  celular: un paso atrás; en el primero cierra (N5).
- Dirección: `?flujo=enviar&que={productos|menu|pagos|piezas|foto}&paso=N`. Título del panel = el
  del paso; su icono, el de la opción.
- Al cerrar el panel (Volver, ✕, Esc o fondo) el **foco vuelve al botón «+»**, ya cerrado.

## 5. Abrir, cerrar, teclado y movimiento

- **Cierran el Orbit:** tocar fuera, Esc, «×» o elegir (que abre el panel en el mismo toque). No es
  un paso: no escribe la dirección; el atrás del celular con el Orbit abierto solo lo cierra.
- **Teclado** (botón de menú; sale gratis de Radix `DropdownMenu`, el mismo del «⋯»): Tab llega
  al «+»; Enter, Espacio o ↓ abren con el foco en la primera opción (↑, en la última); ↑/↓
  recorren y dan la vuelta, Inicio/Fin; Enter elige; Esc cierra y devuelve el foco al «+»; Tab
  cierra y sigue.
- **Lector de pantalla:** «Enviar algo al cliente, menú contraído/expandido»; cada opción es
  `menuitem` con su texto como nombre; iconos `aria-hidden`.
- **Movimiento:** el «+» gira 45° con `T.SPRING` en `--q-dur`. Las píldoras suben 12 px desde el
  botón con aparición, una tras otra cada 30 ms. Con `prefers-reduced-motion`: el icono cambia a
  «×» sin girar y las píldoras aparecen en su sitio, sin desplazarse ni escalonarse.
- **Pulsado de este botón:** `scale(0.92)`, como el `.orbit-main` del kit (los rectangulares, 0,975,
  §5.5); con `prefers-reduced-motion`, solo el cambio de tono. Las píldoras: el pulsado de §5.5.
  **Sin velo oscuro:** cada píldora lleva el material flotante (`--q-overlay-*`) y su sombra.

## 6. Fuera de las 24 horas

No cambia nada. El cuadro de respuesta entero, con el «+», se reemplaza por lo de hoy
(`_expired_composer`): el aviso «Pasaron más de 24 horas desde su último mensaje. WhatsApp solo
deja escribirle con un mensaje aprobado.» y el botón «Enviar un mensaje aprobado».

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
- **Reglas de uso:** (1) **solo en el cuadro de respuesta de Chats de WhatsApp**; otra pantalla
  necesita el visto bueno del fundador; (2) entre 2 y 6 opciones; (3) icono **y** texto de 16
  caracteres como máximo, nunca solo icono; (4) una opción **abre un flujo, nunca envía ni
  publica** (N13); (5) fuera de sus condiciones (ventana cerrada) no se dibuja, en vez de
  deshabilitarse.

## 8. Qué cambia en textos y pruebas

- **Desaparecen:** `PICK_BUTTON_LABEL` «Foto o menú» y `PICK_BUTTON_ARIA`; `pick_heading`
  («¿Qué le quieres mandar a {nombre}?»); `PICK_HELP_SOURCE`; las líneas de `PICK_SOURCE_CARDS`
  («Una foto con su precio, para que te lo pida.», etc.), que queda como (clave, icono, texto).
- **Textos nuevos:** «Enviar algo al cliente», «Foto del celular», «Stickers y videos» (más adelante).
- **«Nada sale sin que toques «Enviar».»** pasa a la ayuda del paso «Revisa y envía» de las
  opciones que no la tienen, para no perder esa garantía.
- **Pruebas:** `test_whatsapp_chats_picker.py:570-582` deja de esperar «Foto o menú» y «Una foto
  de tu celular» y espera «Enviar algo al cliente», los cinco textos y «Volver al chat».
  `open_picker` pasa a `open_pick(source)`, que abre en el primer paso de esa opción
  (`pick_step == 1`, `pick_total` 2, o 1 en Tu menú) y reemplaza las aserciones `pick_step == 2`
  (`:329`, `:497`, `:553`; `test_whatsapp_chats_payments.py:345`); `pick_back()` en el primer paso
  cierra el panel (`:554-556`). Nuevas: orden y textos del Orbit; Esc o elegir cierran; fuera de
  la ventana no se dibuja; una sola forma de pago abre en «Revisa y envía»; a 375 px la columna no
  se cruza con `.q-wa-composer` ni sale de la pantalla.
