# Chats de WhatsApp e Instagram: una sola bandeja, ajustes aparte (m-24789459)

`[PROPUESTA UX DECIDIDA por el fundador 2026-11-13 · m-24789459 · sin implementar]`

> Propuesta de experiencia (ux-designer, 2026-11-12). El fundador aceptó las cinco
> recomendaciones (D1–D5) el 2026-11-13; «Enviar» en los dos canales ya estaba decidido y en
> producción (m-25017173, PR #606). Lo que sigue abierto está en el §6.
> **No se revisó en la app corriendo**: es una propuesta de flujo
> hecha sobre el código de hoy (`Qualify/whatsapp_tab_chats.py`, `whatsapp_chats_vm.py`,
> `conversations_page.py`, `responder_page.py`, `ui/layout.py`, `assets/qualify-inbox.css`), no una
> revisión de pantalla.
>
> **Maqueta:** `docs/mockups/chats-unificados.html` (celular primero, luego escritorio).
> Reglas: `qualify-ux`, `qualify-copy-es`, `docs/ux-guia-navegacion.md`, `docs/design-system.md`
> (sin componentes ni colores nuevos). Persona: `docs/perfil-cliente-pyme.md` §2.

## 0. Pedido

El fundador (2026-11-12) probó WhatsApp e Instagram Direct con Bianki (shawarma, toma pedidos por
chat): la pantalla de chats de WhatsApp tiene mala experiencia; la de Instagram tiene mejor color y
mejor ubicación de botones. Quiere que los dos se vean y funcionen igual, la configuración separada
de los mensajes, menos pestañas y submenús, y la misma base para recibir más adelante pedidos por
mensajes de TikTok.

## 1. Lo que se encontró en el código (y que cambia la dirección propuesta)

1. **«Respuestas rápidas» de Instagram no son respuestas guardadas: son botones.** Son hasta 13
   opciones que el cliente toca debajo del mensaje (`conversations_page.py:36`). Es lo mismo que
   «Texto · Botones» de WhatsApp (hasta 3). Hoy la misma cosa tiene dos nombres y dos lugares.
2. **«Plantillas» de Instagram son mensajes guardados del negocio** (con `{nombre}` y `[precio]`).
   En WhatsApp no existe esa biblioteca; lo que WhatsApp llama «Mensaje aprobado» es otra cosa: el
   único mensaje que se puede mandar cuando pasaron 24 horas. Si las dos se llaman «plantilla», el
   dueño las va a confundir.
3. **«Sugerir respuesta» solo existe en Instagram.** Llevarlo a WhatsApp es trabajo de backend, no
   de pantalla.
4. **«Formas de pago» vive dentro de WhatsApp › Tu número.** Si el «+» de Instagram también manda
   formas de pago, ese dato es del negocio, no del número de WhatsApp.
5. **«Promociones» no es configuración: es vender.** Manda mensajes a clientes que aceptaron
   recibirlos (Enviadas · Mensajes aprobados · Clientes que aceptaron). Esconderlo en «Canales»
   lo aleja justo de quien lo tiene que usar.
6. **«Tu número» es estado de conexión.** Ya existe «Tus redes» (`/connections`) para eso, con los
   estados de `docs/design-system.md` §7.3 (Conectada · Desconectada · Sin acceso).
7. **Contraste:** la burbuja enviada de Instagram es un degradado `purple-9 → pink-9 → orange-9`
   con texto blanco (`assets/qualify-inbox.css`, regla `.q-conv-msg.q-wa-msg--out .q-bubble--out`;
   el mismo degradado pinta el glifo del canal, `.q-conv-channel`). El tramo naranja con texto blanco queda por
   debajo de 4,5:1 (texto de 15 px). Es lo que el fundador vio como «mejor color», pero no pasa AA
   tal como está. *(Estimación con los valores de Radix; se mide en el navegador antes de construir,
   condición de D2.)*
8. **Hoy una fila de WhatsApp puede llevar hasta 5 píldoras** (pago, ventana, quién responde,
   «Cerrado», iniciales). A 360 px eso son dos renglones de etiquetas por cliente.

## 2. La propuesta en una mirada

```
Atiende
├ Por responder                      ← solo conversar
│  ├ Quién te espera (como hoy, sin la tarjeta aparte de WhatsApp)
│  └ Mensajes  [Todos] [WhatsApp] [Instagram]      (solo si hay 2 o más conectados)
│              [Por responder] [Todos] [Cerrados] (+ «Pago por revisar · N» si hay)
│              una fila, un chat, un cuadro de respuesta
└ Ajustes de chats                   ← solo preparar (D1)
   ├ Para todos tus chats: Mensajes guardados · Formas de pago · Cómo llegar
   ├ WhatsApp: Respuesta automática · Preguntas iniciales
   └ Instagram: Preguntas iniciales
Tus redes (Tu negocio)               ← ¿está conectado? (absorbe «Tu número»)
Promociones por WhatsApp (Publica)   ← junto a «Anuncios» (D3)
```

- **Una fila** (la de Instagram): foto o inicial, glifo del canal en la esquina, punto que respira
  cuando el cliente espera, nombre, hora, vista previa con «Tú: », **una sola** píldora de atención
  (la más urgente: Pago por revisar › Responde en N min › Quiere comprar) y, si hay equipo, las
  iniciales de quien atiende. «Cerrado» no hace falta en la fila: ya lo dice el filtro.
- **Un chat**: arriba, volver con destino («‹ Por responder», N7), nombre, canal y hasta cuándo se
  le puede escribir; a la derecha, «⋯» con lo que se usa poco (Asignar, Cerrar chat, Ajustes de este
  canal). Si hay pedido, una franja «Pedido · 3 productos · $ 45.000 · Pago por revisar» que se
  abre con un toque y muestra el resumen, «Pago recibido» y «Pedido listo».
- **Quién responde** (solo WhatsApp con respuesta automática): una franja justo encima del cuadro de
  respuesta, «Está respondiendo tu menú automático · Responder yo», o «Estás respondiendo tú ·
  Devolver al menú». Está pegada a donde el dueño escribe porque es lo que cambia al escribir.
- **Un cuadro de respuesta**, el mismo en los dos canales, en tres renglones:
  1. el texto;
  2. herramientas de todos los días, con icono **y** nombre corto: Foto o video · Botones ·
     Mensajes guardados · (Instagram: Archivo, Nota de voz, ❤);
  3. «+» (cosas del negocio) · «Sugerir respuesta» · **«Enviar»** (el único botón sólido).
  Lo que un canal no puede mandar **no se dibuja** (regla del `orbit_menu`: fuera de sus
  condiciones no se dibuja, no se deshabilita).
- **El «+»** queda con 5 filas iguales en los dos canales: Tus productos · Tu oferta · Tu menú ·
  Formas de pago · Cómo llegar. «Fotos y videos» sale del «+» y pasa al renglón de todos los días
  (abre el mismo paso «¿De dónde?»: Tus piezas · De tu celular · stickers y videos de marca).
  Los stickers se crean y se aprueban en Tu marca / Por aprobar / Aprobados; desde el chat solo se
  mandan. Chats de WhatsApp ya no tiene la subpestaña «Stickers y videos» (decidido y en
  producción). Si no hay ninguno de la temporada, «Crear para esta temporada» lleva a Tu marca, con
  «Volver a tus chats» para regresar al mismo chat.
  Lo que cambia por canal es **cómo le llega**, y eso ya lo muestra el paso «Así le llega».

## 3. Decisiones (fundador, 2026-11-13)

El fundador aceptó las cinco recomendaciones. Cada una deja la opción elegida, las descartadas en
corto (para que el porqué se pueda seguir) y, si la hay, la condición antes de construir. «[H]» =
hipótesis del perfil, que se valida en el §6.

### D1 · Dónde vive la configuración — **Decidido por el fundador (2026-11-13)**

**Elegida: «Ajustes de chats» en Atiende, y «Tu número» pasa a «Tus redes».** Atiende queda con
Por responder · Ajustes de chats; «¿está conectado?» de todas las cuentas vive solo en Tus redes
(estados de `docs/design-system.md` §7.3). El «⋯» de cada chat lleva a «Ajustes de este canal».

Descartadas: «Canales» en Atiende (palabra de marketing; el dueño dice «mi WhatsApp» [H, §5
pregunta 4]); todo dentro de «Tus redes» (aleja la respuesta automática de los chats, que es lo
que el dueño quiere corregir cuando el menú contestó mal).

### D2 · El color del canal y la burbuja enviada — **Decidido por el fundador (2026-11-13)**

**Elegida: tinte suave del canal con texto oscuro.** Burbuja enviada con relleno `{canal}-a4`
(instagram pink, whatsapp green, tiktok purple, de `T.PLATFORM_SCALE`) y texto gray-12; glifo +
lavado `{canal}-a3` en la cabecera del chat. Es lo que WhatsApp ya hace hoy
(`.q-wa-msg--glass.q-wa-msg--out .q-bubble--out`) y conserva el color que gustó en Instagram.

**Condición antes de construir (no es una decisión abierta):** medir el contraste en el navegador,
en claro y en oscuro (hallazgo 7). Si el tinte no llega a 4,5:1, se corrige dentro de la misma
opción (otro paso de alfa) antes de pasar a otra.

Descartadas: degradado del canal oscurecido con texto blanco (más vistoso, contraste sin medir);
una sola burbuja de acento teal (borra el color que gustó).

### D3 · Promociones — **Decidido por el fundador (2026-11-13)**

**Elegida: entrada propia «Promociones por WhatsApp» junto a «Anuncios» (zona Publica).** Las dos
sirven para llegar a gente que hoy no te está escribiendo [H, sin fuente; ninguna pregunta del §5
la cubre todavía]. **Costo aceptado:** suma una entrada al menú lateral aunque el pedido fue tener
menos; Atiende pierde «WhatsApp» y Publica gana «Promociones por WhatsApp», así que el total queda
igual.

Descartada: dentro de «Ajustes de chats › WhatsApp» como primera tarjeta (no suma entrada, pero
esconde algo que vende entre ajustes).

### D4 · Qué se vuelve igual en los dos canales — **Decidido por el fundador (2026-11-13)**

**Elegido: «Sugerir respuesta» llega a WhatsApp primero**, porque Bianki recibe pedidos por
WhatsApp ([F] perfil §1; el ahorro «entre clientes» es [H], §2). Es también una decisión de costo:
**cada toque de «Sugerir respuesta» es una llamada a la IA (Claude) que se paga.** Con eso, el
resto del trabajo de backend para un mismo cuadro de respuesta:

| Pieza | Hoy | Decidido |
|---|---|---|
| Sugerir respuesta | Instagram | También en WhatsApp, primero |
| Mensajes guardados (hoy «Plantillas» de Instagram) | Instagram | Una sola biblioteca para todos los canales |
| Cerrar / Reabrir chat | WhatsApp | También en Instagram |
| Formas de pago y Cómo llegar | WhatsApp › Tu número | Datos del negocio, en «Para todos tus chats» |

Mientras no estén, el botón no se dibuja en el canal que no lo soporta (la maqueta marca cuáles).

### D5 · Un solo nombre por cosa — **Decidido por el fundador (2026-11-13)**

**Elegidos: «Preguntas iniciales», «Botones», «Mensajes guardados» y «Enviar»** (este último ya
decidido el 2026-11-12, m-25017173, PR #606).

| Hoy | Decidido | Razón |
|---|---|---|
| «Atajos» (WhatsApp) / «Preguntas iniciales» (Instagram) | **Preguntas iniciales** en los dos, con la línea «Lo que tu cliente puede tocar al abrir el chat» | «Atajos» no dice qué es |
| «Respuestas rápidas» (Instagram) / «Texto · Botones» (WhatsApp) | **Botones** en los dos | Es lo que el cliente ve y toca |
| «Plantillas» (Instagram) | **Mensajes guardados** | Evita confundirlo con el mensaje aprobado de WhatsApp |
| «Mensaje aprobado» (WhatsApp, chat cerrado) | se queda | Ya dice por qué es distinto |
| «Responder» (Instagram) / «Enviar» (WhatsApp) | **Enviar** en los dos | Ya es la palabra de WhatsApp; un solo verbo en la barra |

## 4. Qué cambié respecto de la dirección propuesta, y por qué

1. **«Canales» → «Ajustes de chats»**, y «Tu número» a «Tus redes» (D1).
2. **«Promociones» fuera de la configuración** (D3, hallazgo 5).
3. **«Quick replies» inline no era una sola cosa:** se separa en «Botones» (lo que el cliente toca)
   y «Mensajes guardados» (lo que tú reutilizas). Hallazgos 1 y 2.
4. **«Fotos y videos» sale del «+»** al renglón de todos los días (lo pedía la dirección) y el «+»
   queda en 5 filas iguales para los dos canales; así el «+» no cambia de forma según el chat.
5. **El filtro de canal solo aparece con 2 canales o más.** Bianki hoy tiene un número de WhatsApp;
   si solo tiene uno, la fila de canales es ruido.
6. **TikTok no se dibuja hasta que exista.** Nada de «TikTok (pronto)» en el filtro: sería un
   botón que no lleva a nada (N8). La base ya lo admite: glifo `purple`, su fila de capacidades en
   la tabla de la maqueta, sus ajustes en «Ajustes de chats».
7. **Una sola píldora por fila** en vez de cinco (hallazgo 8).
8. **«Tomar el control» se mudó** de la cabecera a la franja «quién responde» encima del cuadro de
   respuesta, y cambia de nombre a «Responder yo» (el nombre se prueba antes de construir: §6, 2).
   Asignar y Cerrar van al «⋯».
9. **La tarjeta del pedido se pliega** en una franja con el total y el estado del pago; abierta,
   es la tarjeta de hoy sin cambios.

## 5. Lo que necesita `reflex-ui-engineer` (cuando haya ticket)

- Fila: generalizar la fila de `conversations_page.py:333-430` para los dos canales; WhatsApp deja
  la suya (`whatsapp_tab_chats.py:236-306`). Una píldora: prioridad en el VM, no en la vista.
- Cuadro de respuesta: uno solo, con una tabla de capacidades por canal en el VM
  (`can_photo`, `can_file`, `can_voice`, `can_heart`, `can_buttons`, `max_buttons`,
  `can_saved`, `can_suggest`, `can_close`, `has_menu_handoff`, `has_payments`). La vista solo
  pregunta «¿se dibuja?».
- El «+» = `orbit_menu` con las 5 filas de `PICK_SOURCE_CARDS` sin `PICK_MEDIA`; el `orbit_menu`
  pasa a usarse también en Instagram (§5.9 del design system pide el visto bueno del fundador para
  otra pantalla: ver §6, 3).
- «⋯» = `rx.menu` (Radix DropdownMenu), sin componente nuevo.
- Franja del pedido = `card` plegable (`rx.accordion` o `rx.collapsible`, ya en uso), la tarjeta de
  `_order_card()` adentro sin cambios.
- Colores: en `assets/qualify-inbox.css`, quitar el degradado a mano de Instagram
  (`.q-conv-channel` y `.q-conv-msg.q-wa-msg--out .q-bubble--out`, con sus variantes de sticker) y
  el juego verde aparte de WhatsApp (`.q-wa-card`, `.q-wa-msg--glass…`); dejar un solo juego de
  reglas que lea la escala del canal (`T.platform_scale`).
- Rutas (N3): `/responder?tab=mensajes&canal=whatsapp&chat=<id>`; `/whatsapp` redirige a
  `/responder?tab=mensajes&canal=whatsapp`; los ajustes, `/chats/ajustes/whatsapp` y
  `/chats/ajustes/instagram` (nombres a decidir). Menú: «Por responder» encendido en la lista y en
  cada chat; su contador suma lo que hoy es el contador de «WhatsApp».
- «Stickers y videos» no es pestaña (la subpestaña ya salió de Chats de WhatsApp): se mandan por
  Foto o video › «¿De dónde?»; se gestionan en Tu marca / Por aprobar / Aprobados.

## 6. Preguntas abiertas

D1–D5 están decididas (§3). Lo que sigue abierto:

1. **Hipótesis del perfil por validar con clientes** (`docs/perfil-cliente-pyme.md` §5):
   - ¿Bianki y Polette contestan desde el celular, con una mano, mientras despachan? Todo el
     diseño lo supone [H, §5 pregunta 3]. Si contesta un empleado en una computadora del local, la
     vista de escritorio pasa a ser la principal.
   - ¿El dueño dice «mi WhatsApp» y no «canal»? Sostiene el nombre de D1 [H, §5 pregunta 4].
   - ¿El dueño piensa «Promociones» como vender y no como ajuste? Sostiene D3 [H, sin pregunta en
     el §5 todavía: conviene agregarla].
   - ¿El dueño quiere ver todos los canales mezclados, o prefiere entrar «a WhatsApp»? Si en la
     prueba siempre toca el filtro de un canal, el filtro de canal debería recordarse.
   - ¿Hace falta «Asignar» para un negocio de 1 a 3 personas? La propuesta lo esconde en «⋯» y
     solo si el negocio tiene más de una persona con acceso.
2. **«Responder yo» o «Tomar el control».** Probarlo con el dueño de Bianki mostrándole la maqueta
   [§5 pregunta 6] antes de construir la franja «quién responde».
3. **«Fotos y videos» (y el «+») en Instagram antes de la unificación.** ¿Se adelanta a la pantalla
   de Instagram de hoy, o espera al cuadro de respuesta único? Necesita el visto bueno del fundador
   para usar el `orbit_menu` fuera de WhatsApp (`docs/design-system.md` §5.9).
4. ¿TikTok permite recibir y contestar mensajes de negocio con su API para los clientes de la
   región? Lo responde `principal-architect`; la pantalla solo deja el lugar.
5. Condición de D2 (no es decisión abierta): medir en el navegador, en claro y oscuro, el contraste
   del tinte elegido (y del degradado de hoy, hallazgo 7) antes de construir.
