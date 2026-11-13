# Chats de WhatsApp e Instagram: una sola bandeja, ajustes aparte (m-24789459)

`[PROPUESTA UX 2026-11-12 · m-24789459 · sin implementar]`

> Propuesta de experiencia (ux-designer, 2026-11-12). D1–D4 y la mayor parte de D5 esperan la
> decisión del fundador; ya decidido: «Enviar» en los dos canales (m-25017173, PR #606).
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
   con texto blanco (`assets/qualify-inbox.css` ~337). El tramo naranja con texto blanco queda por
   debajo de 4,5:1 (texto de 15 px). Es lo que el fundador vio como «mejor color», pero no pasa AA
   tal como está. *(Estimación con los valores de Radix; medir en el navegador antes de decidir.)*
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
└ Ajustes de chats                   ← solo preparar (nombre: decisión D1)
   ├ Para todos tus chats: Mensajes guardados · Formas de pago · Cómo llegar
   ├ WhatsApp: Respuesta automática · Preguntas iniciales
   └ Instagram: Preguntas iniciales
Tus redes (Tu negocio)               ← ¿está conectado? (absorbe «Tu número»)
Promociones por WhatsApp             ← decisión D3
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

## 3. Decisiones para el fundador

Cada una con mi recomendación y la razón desde el perfil del cliente. «[H]» = hipótesis, se valida
con la pregunta del perfil §5 que se indica.

### D1 · Dónde vive la configuración y cómo se llama

| Opción | Qué ve el dueño |
|---|---|
| A. «Canales» en Atiende (la dirección propuesta) | Por responder · Canales |
| **B. «Ajustes de chats» en Atiende** + «Tu número» pasa a «Tus redes» | Por responder · Ajustes de chats |
| C. Todo dentro de «Tus redes» | Atiende queda solo con Por responder |

**Recomiendo B.** «Canales» es una palabra de marketing: el dueño dice «mi WhatsApp», «mi
Instagram» [H, §5 pregunta 4]; «Ajustes de chats» dice qué hay adentro. B deja una sola pantalla
para saber si algo está conectado (Tus redes, con los estados de §7.3) y una sola para preparar
cómo se atiende. C esconde la respuesta automática lejos de los chats, que es justo lo que el dueño
quiere corregir cuando ve que el menú contestó mal; por eso, además, el «⋯» de cada chat lleva a
«Ajustes de este canal».

### D2 · El color del canal y la burbuja enviada

| Opción | Burbuja enviada | Color del canal |
|---|---|---|
| **A. Tinte suave del canal** | relleno `{canal}-a4` (pink / green / purple), texto gray-12 | glifo + lavado `{canal}-a3` en la cabecera del chat |
| B. Degradado del canal, oscurecido | `{canal}-10 → {canal}-11`, texto blanco | igual que A |
| C. Una sola burbuja de acento (teal) para todos | `accent-a4`, texto gray-12 | solo glifo |

**Recomiendo A.** Conserva lo que al fundador le gustó (se nota el color de Instagram, y WhatsApp
gana el suyo) sin colores a mano, con escalas Radix que ya existen (`T.PLATFORM_SCALE`: instagram
pink, whatsapp green, tiktok purple) y con texto legible al sol en el celular (pasos 11-12 sobre
alfa, `docs/design-system.md` §8). B es más vistosa pero hay que medir contraste en claro y en
oscuro. C es la más sobria pero borra justo lo que gustó.

### D3 · Promociones

**Recomiendo sacarla de la configuración** y dejarla como entrada propia «Promociones por
WhatsApp» junto a «Anuncios» (zona Publica): las dos sirven para llegar a gente que hoy no te está
escribiendo, y el dueño las piensa como «mandar algo para vender», no como «ajustar el WhatsApp»
[H, §5 pregunta 5]. Si el fundador prefiere no sumar una entrada al menú: dentro de «Ajustes de
chats › WhatsApp», pero como primera tarjeta con su beneficio («Manda tu promoción a los clientes
que aceptaron recibirla»), nunca abajo de la lista.

### D4 · Qué se vuelve igual en los dos canales (trabajo de backend)

Para que el cuadro de respuesta sea de verdad el mismo, hacen falta tres cosas que hoy existen solo
en un canal:

| Pieza | Hoy | Recomiendo | Por qué (perfil) |
|---|---|---|---|
| Sugerir respuesta | Instagram | Llevarla a WhatsApp **primero** | Bianki recibe pedidos por WhatsApp: ahí es donde ahorra más tiempo «entre clientes» [E, §1 y §2] |
| Mensajes guardados (hoy «Plantillas» de Instagram) | Instagram | Una sola biblioteca para todos los canales | El dueño escribe una vez «Abrimos de 11 a 9» y le sirve en todos lados |
| Cerrar / Reabrir chat | WhatsApp | También en Instagram | Sin esto el filtro «Cerrados» no puede ser igual en los dos |
| Formas de pago y Cómo llegar | WhatsApp › Tu número | Datos del negocio, en «Para todos tus chats» | El «+» de Instagram los necesita |

Mientras no estén, el botón no se dibuja en el canal que no lo soporta (la maqueta marca cuáles).

### D5 · Un solo nombre por cosa

Las cuatro primeras filas siguen abiertas; la última (el botón de mandar) **ya está decidida**.

| Hoy | Propuesta | Razón |
|---|---|---|
| «Atajos» (WhatsApp) / «Preguntas iniciales» (Instagram) | **Preguntas iniciales** en los dos, con la línea «Lo que tu cliente puede tocar al abrir el chat» | «Atajos» no dice qué es; «Preguntas iniciales» sí |
| «Respuestas rápidas» (Instagram) / «Texto · Botones» (WhatsApp) | **Botones** en los dos | Es lo que el cliente ve y toca |
| «Plantillas» (Instagram) | **Mensajes guardados** | Libera «plantilla» y evita confundirlo con el mensaje aprobado de WhatsApp |
| «Mensaje aprobado» (WhatsApp, chat cerrado) | se queda | Ya dice por qué es distinto |
| «Responder» (Instagram) / «Enviar» (WhatsApp) | **Enviar** en los dos (**decidido**) | Decidido por el fundador en m-25017173 (2026-11-12): ya es la palabra de WhatsApp y evita dos verbos en la misma barra («Enviar sin botones», «Enviar mensaje aprobado») |

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
   respuesta, y cambia de nombre a «Responder yo» [H, §5 pregunta 6: probar si se entiende].
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
  pasa a usarse también en Instagram (§5.9 del design system dice «otra pantalla, visto bueno del
  fundador»: esta propuesta es ese pedido).
- «⋯» = `rx.menu` (Radix DropdownMenu), sin componente nuevo.
- Franja del pedido = `card` plegable (`rx.accordion` o `rx.collapsible`, ya en uso), la tarjeta de
  `_order_card()` adentro sin cambios.
- Colores: borrar el degradado a mano de `assets/qualify-inbox.css` (~323-377) y el lavado verde
  (~475-563); un solo juego de reglas que lea la escala del canal (`T.platform_scale`).
- Rutas (N3): `/responder?tab=mensajes&canal=whatsapp&chat=<id>`; `/whatsapp` redirige a
  `/responder?tab=mensajes&canal=whatsapp`; los ajustes, `/chats/ajustes/whatsapp` y
  `/chats/ajustes/instagram` (nombres a decidir). Menú: «Por responder» encendido en la lista y en
  cada chat; su contador suma lo que hoy es el contador de «WhatsApp».
- «Stickers y videos» no es pestaña (la subpestaña ya salió de Chats de WhatsApp): se mandan por
  Foto o video › «¿De dónde?»; se gestionan en Tu marca / Por aprobar / Aprobados.

## 6. Preguntas abiertas

1. ¿Bianki y Polette contestan desde el celular, con una mano, mientras despachan? Todo el diseño
   lo supone [H, §5 pregunta 3]. Si contesta un empleado en una computadora del local, la vista de
   escritorio pasa a ser la principal.
2. ¿«Responder yo» se entiende mejor que «Tomar el control»? Probarlo con el dueño de Bianki
   mostrándole la maqueta [§5 pregunta 6].
3. ¿El dueño quiere ver todos los canales mezclados, o prefiere entrar «a WhatsApp»? Si en la
   prueba siempre toca el filtro de un canal, el filtro de canal debería recordarse.
4. ¿Hace falta «Asignar» para un negocio de 1 a 3 personas? Hoy está en WhatsApp; la propuesta lo
   esconde en «⋯» y solo si el negocio tiene más de una persona con acceso.
5. ¿TikTok permite recibir y contestar mensajes de negocio con su API para los clientes de la
   región? Esto lo responde `principal-architect`, no esta propuesta; la pantalla solo deja el lugar.
6. Contraste real del degradado de Instagram (hallazgo 7): medir en el navegador en claro y oscuro
   antes de decidir D2.
