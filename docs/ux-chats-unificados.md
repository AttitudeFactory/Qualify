# Chats de WhatsApp e Instagram: una sola bandeja, ajustes aparte (m-24789459)

`[PROPUESTA UX DECIDIDA por el fundador 2026-11-12 · m-24789459 · fila y lista única construidas (m-25017844, m-25017859), el resto sin implementar]`

> **Cambios de texto posteriores (2026-11-13), decididos por el fundador:** «Responde en N min»
> pasó a «Quedan {N} min para responder»; la lista suma el filtro «Sin responder a tiempo · N» para
> los chats de Instagram vencidos sin respuesta (solo se dibuja al abrirlo desde el aviso). Detalle y resto de textos en
> `docs/epica-bandeja-unica.md` §6 (vii).

> Propuesta de experiencia (ux-designer, 2026-11-12). El fundador aceptó las cinco
> recomendaciones (D1–D5) el 2026-11-12; «Enviar» en los dos canales ya estaba decidido y en
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
   tal como está. *(Medido en el navegador el 2026-11-14: blanco sobre `orange-9` = 2,97:1, sobre
   `pink-9` = 4,12:1; ver «D2 medido».)*
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
   ├ WhatsApp: Respuesta automática (*) · Preguntas iniciales
   └ Instagram: Preguntas iniciales
Tus redes (Tu negocio)               ← ¿está conectado? (absorbe «Tu número»)
Promociones por WhatsApp (Publica)   ← junto a «Anuncios» (D3)
```

(*) Nombre **pendiente de la decisión de nombres del fundador (condición 3 de m-24789557)**:
ningún texto puede decir ni sugerir que Qualify responde solo. Alternativa de la revisión de
experiencia independiente, no decidida: «Tu menú de bienvenida». La maqueta todavía muestra el
nombre anterior hasta que el fundador decida.

- **Una fila** (la de Instagram): foto o inicial, glifo del canal en la esquina, punto que respira
  cuando el cliente espera, nombre, hora, vista previa con «Tú: », **una sola** píldora de atención
  (la más urgente: Pago por revisar › Quedan N min para responder › Quiere comprar; texto
  cambiado por el fundador el 2026-11-13, antes «Responde en N min»; el orden construido es otro,
  ver `epica-bandeja-unica.md` §6 (vii) 9) y, si hay equipo, las
  iniciales de quien atiende. «Cerrado» no hace falta en la fila: ya lo dice el filtro.
- **Un chat**: arriba, volver con destino («‹ Por responder», N7), nombre, canal y hasta cuándo se
  le puede escribir; a la derecha, «⋯» con lo que se usa poco (Asignar, Cerrar chat, Ajustes de este
  canal). Si hay pedido, una franja «Pedido · 3 productos · $ 45.000 · Pago por revisar» que se
  abre con un toque y muestra el resumen, «Pago recibido» y «Pedido listo».
- **Quién responde** (solo WhatsApp con respuesta automática): una franja justo encima del cuadro de
  respuesta, «Está respondiendo tu menú automático · Responder yo», o «Estás respondiendo tú ·
  Devolver al menú». Está pegada a donde el dueño escribe porque es lo que cambia al escribir.
  El texto de la franja está **pendiente de la decisión de nombres del fundador (condición 3 de
  m-24789557)**; alternativa de la revisión de experiencia independiente, no decidida: «Este
  cliente está usando tu menú · Responder yo». La maqueta todavía muestra el texto anterior.
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

## 3. Decisiones (fundador, 2026-11-12)

El fundador aceptó las cinco recomendaciones. Cada una deja la opción elegida, las descartadas en
corto (para que el porqué se pueda seguir) y, si la hay, la condición antes de construir. «[H]» =
hipótesis del perfil, que se valida en el §6.

### D1 · Dónde vive la configuración — **Decidido por el fundador (2026-11-12)**

**Elegida: «Ajustes de chats» en Atiende, y «Tu número» pasa a «Tus redes».** Atiende queda con
Por responder · Ajustes de chats; «¿está conectado?» de todas las cuentas vive solo en Tus redes
(estados de `docs/design-system.md` §7.3). El «⋯» de cada chat lleva a «Ajustes de este canal».

Descartadas: «Canales» en Atiende (palabra de marketing; el dueño dice «mi WhatsApp» [H, §5
pregunta 4]); todo dentro de «Tus redes» (aleja la respuesta automática de los chats, que es lo
que el dueño quiere corregir cuando el menú contestó mal).

### D2 · El color del canal y la burbuja enviada — **Decidido por el fundador (2026-11-12) · contraste medido (2026-11-14)**

**Elegida: tinte suave del canal con texto oscuro.** Burbuja enviada con relleno `{canal}-a4`
(instagram pink, whatsapp green, tiktok purple, de `T.PLATFORM_SCALE`) y texto gray-12; glifo +
lavado `{canal}-a3` en la cabecera del chat. Es lo que WhatsApp ya hace hoy
(`.q-wa-msg--glass.q-wa-msg--out .q-bubble--out`) y conserva el color que gustó en Instagram.

**Condición antes de construir (no es una decisión abierta):** medir el contraste en el navegador,
en claro y en oscuro (hallazgo 7). Si el tinte no llega a 4,5:1, se corrige dentro de la misma
opción (otro paso de alfa) antes de pasar a otra.

Descartadas: degradado del canal oscurecido con texto blanco (más vistoso, contraste sin medir);
una sola burbuja de acento teal (borra el color que gustó).

#### D2 medido (m-25017860, 2026-11-14) — **lo aceptado pasa; D2 queda medido**

**Método.** Chrome, página de prueba local con la hoja de Radix Themes 3.3.0 de `.web` (solo los
valores sRGB; se quitó el bloque display-p3), `assets/qualify.css` y `assets/qualify-inbox.css`
reales, tema `teal`/`slate`, `.light` y `.dark`. Cada token se leyó con `getComputedStyle` sobre la
página dibujada, y las capas traslúcidas se componen sobre lo que tienen detrás; cada razón es la
**peor** combinación, WCAG 2.x. Captura: `docs/mockups/contraste-tinte-canal-2026-11-14.jpg`
(claro a la izquierda, oscuro a la derecha). La página de prueba no se guarda en el repo: se
rehace con esas tres hojas y una burbuja con las clases de `Qualify/whatsapp_tab_chats.py`.

**Lo que hay detrás de la burbuja, leído en la página dibujada (no solo en el CSS).**
`.q-wa-card` y `.q-conv-card` (`assets/qualify-inbox.css`, cargada después) ponen su propio
`background-image` y **reemplazan** el relleno de `.q-card` (`--q-card-fill`): el color calculado
de la tarjeta es transparente y su imagen es solo el lavado del canal, `{canal}-a3` en una esquina
que se desvanece al 55 %. Por eso «hoy» = panel opaco `--color-panel-solid` → lavado `{canal}-a3`
(peor punto: la esquina, a toda fuerza) → `--gray-a2` → `{canal}-a2` arriba del hilo → burbuja
`--q-control-fill` + `{canal}-a4 → a3`. La burbuja de Instagram con tinte no existe todavía: se
midió con la regla de WhatsApp (`.q-wa-msg--glass…--out`) cambiando `green` por `pink`, sobre el
lavado rosa que ya tiene `.q-conv-card`. Las columnas de Instagram aplican además la regla del
hilo de WhatsApp con rosa (capa `pink-a2` arriba), que hoy no existe: `.q-conv-scroll` es solo
`--gray-a2`. Es un caso conservador; los valores reales son un poco mejores y ningún resultado
cambia.

| Par, con el fondo de hoy (texto 12–15 px salvo indicación) | Claro WA | Claro IG | Oscuro WA | Oscuro IG | Resultado |
|---|---|---|---|---|---|
| Texto `gray-12` sobre la burbuja del negocio `{canal}-a4→a3` | 12,78 | 11,93 | 5,11 | 6,90 | **Pasa** (4,5) |
| Hora, «Enviado»: `gray-10` (`TEXT_MUTED`, lo de hoy) | 2,95 | 2,76 | 1,40 | 1,89 | Falla |
| Hora, «Enviado»: `gray-11` | 4,63 | 4,32 | 2,85 | 3,85 | Pasa solo claro WA |
| Hora, «Enviado»: `gray-12` | 12,78 | 11,93 | 5,11 | 6,90 | Pasa |
| Enlace de `rx.link` (`--accent-a11`, Radix `components.css:589`) | 3,56 | 3,32 | 3,74 | 4,65 | Falla, salvo oscuro IG |
| Enlace `--accent-12` (lo que pinta `rx.link(high_contrast=True)`) | 9,40 | 8,78 | 4,60 | 6,21 | Pasa |
| Error «No se envió» `tomato-11` | 3,89 | 3,63 | 2,82 | 3,80 | Falla |
| Error `tomato-12` | 9,28 | 8,66 | **4,32** | 5,83 | Falla en oscuro WA (pasa sin lavado: 6,11) |
| Ícono «Leído» `accent-11` (no texto, 3:1) | 3,56 | 3,32 | 3,26 | 4,39 | Pasa (3:1) |
| Borde: relleno de la burbuja vs. fondo del hilo (no texto, 3:1) | 1,01 | 1,01 | 1,63 | 1,47 | No llega · no exigible¹ |
| Borde: anillo `{canal}-a5` vs. fondo (no texto, 3:1) | 1,25 | 1,35 | 2,56 | 1,97 | No llega · no exigible¹ |
| *Cliente:* texto `gray-12` | 15,16 | 14,98 | 7,55 | 8,62 | Pasa |
| *Cliente:* hora `gray-10` / `gray-11` | 3,50 / 5,49 | 3,46 / 5,43 | 2,07 / **4,21** | 2,36 / 4,81 | `gray-10` falla; `gray-11` falla en oscuro WA |
| *Cliente:* enlace `--accent-a11` / `--accent-12` | 4,22 / 11,16 | 4,17 / 11,02 | 5,29 / 6,80 | 5,83 / 7,76 | `accent-a11` falla en claro |
| *Hoy (hallazgo 7):* blanco sobre `purple-9` / `pink-9` / `orange-9` | — | 5,18 / 4,12 / **2,97** | — | igual | Falla (hora al 85 %: 2,53) |
| *Maqueta (solo oscuro, colores a mano):* texto / hora `gray-11` | — | — | 9,80 / 5,47 | 10,82 / 6,03 | Pasa, pero no son los tokens |

¹ WCAG 1.4.11 pide 3:1 a controles y a gráficos necesarios para entender; el fondo de la burbuja
no lo es: quién habla lo dicen el lado (derecha = tú) y el texto, que sí pasa. En claro, sobre
`--gray-a2`, el anillo no llega a 3:1 hasta `{canal}-a8` (2,41–2,47 WA; 2,46–2,62 IG); desde
`{canal}-a9` sí llega (3,08–3,12 WA; 4,06–4,14 IG; `a11` 4,55–5,18; sólido `9` 3,00 / 3,92), pero
eso ya es un borde de color lleno, no un tinte suave. No se propone cambiar el borde.

**Peor caso, no el de hoy.** Si el hilo nuevo de BU-A5 se montara sobre una `ui.card` que conserve
`--q-card-fill` **y** además llevara el lavado `{canal}-a3` a toda fuerza debajo de los mensajes,
el texto principal de WhatsApp en oscuro caería a **4,39** (falla). Hoy no pasa: la tarjeta de
chat no tiene ese relleno y el lavado es una esquina que se desvanece.

**Con el fondo del hilo solo en `--gray-a2`** (propuesta 9 de abajo) hay dos casos, según lo que
BU-A5 haga con la tarjeta del chat. En claro dan lo mismo (el panel es blanco); en oscuro no:

| Par (claro WA / claro IG / oscuro WA / oscuro IG) | (a) Tarjeta transparente | (b) Vuelve `--q-card-fill` |
|---|---|---|
| Texto `gray-12` | 13,44 / 12,72 / 7,23 / 8,93 | 13,44 / 12,72 / 5,95 / 7,52 |
| Hora `gray-11` (burbuja del negocio) | 4,87 / 4,61 / 4,03 / 4,98 | 4,87 / 4,61 / 3,32 / 4,19 |
| Enlace `--accent-12` | 9,89 / 9,36 / 6,51 / 8,04 | 9,89 / 9,36 / 5,36 / 6,77 |
| Error `tomato-12` | 9,76 / 9,23 / 6,11 / 7,54 | 9,76 / 9,23 / 5,03 / 6,35 |
| Hora del cliente `gray-11` | 5,82 / 5,82 / 6,24 / 6,24 | 5,82 / 5,82 / 4,94 / 4,94 |

(a) es lo que pasa si el lavado se quita dejando en `.q-wa-card` / `.q-conv-card` una regla que
siga reemplazando el relleno de `.q-card` (por ejemplo `background-image: none`). (b) es lo que
pasa si se borra esa regla, como pide el §5: vuelve `--q-card-fill` (blanco al 7,5 % → 3 % en
oscuro) y todo queda un poco más claro detrás de la burbuja. Los dos casos pasan; (b) es el
probable y con menos margen. Los números de (b) se midieron en la misma página dibujada.

**Propuesta de UX para BU-A5.** Los mismos nombres de token en claro y en oscuro; Radix cambia el
valor solo.

| # | Pieza | Valor (WhatsApp `green` · Instagram `pink`) | Estado |
|---|---|---|---|
| 1 | Relleno de la burbuja del negocio | `--q-control-fill` + `linear-gradient(160deg, var(--{canal}-a4), var(--{canal}-a3))` | Aceptado en D2 |
| 2 | Texto del mensaje | `--gray-12` | Aceptado en D2 |
| 3 | Glifo y lavado `{canal}-a3` en la cabecera del chat | como dice D2 | Aceptado en D2 |
| 4 | Anillo de la burbuja | `inset 0 0 0 1px var(--{canal}-a5)` (lo de WhatsApp hoy) | Sin cambio; no exigible¹ |
| 5 | Hora, «Enviado», ✓ y ✓✓ sin leer, dentro de la burbuja del negocio | `--gray-12` (hoy `gray-10`) | Propuesta, falta el visto bueno del fundador |
| 6 | Enlace dentro de cualquier burbuja | `--accent-12` = `rx.link(high_contrast=True)`, con subrayado | Propuesta, falta el visto bueno del fundador |
| 7 | Error dentro de la burbuja del negocio | `--tomato-12` | Propuesta, falta el visto bueno del fundador |
| 8 | Hora en la burbuja del cliente | `--gray-11` (hoy `gray-10`); **no hay token de rol** para el paso 11 (`Qualify/ui/tokens.py` tiene `TEXT_MUTED` = 10, `TEXT_FAINT` = 8, `TEXT_STRONG` = 12, y la regla P7 pide tokens por rol): BU-A5 necesita un token nuevo o una decisión del sistema de diseño | Propuesta, falta el visto bueno del fundador |
| 9 | Fondo debajo de los mensajes | `--gray-a2` solo, sin lavado del canal debajo del hilo. Hoy los dos lo tienen: WhatsApp verde (`green-a3` en una esquina + `green-a2` arriba del hilo) e Instagram rosa y morado (`pink-a3` y `purple-a3` en dos esquinas, `assets/qualify-inbox.css:351–356`) | Propuesta, falta el visto bueno del fundador |
| — | ✓✓ «Leído» | `--accent-11` (ícono, pasa 3:1) | Sin cambio |

La 9 es una preferencia, no una obligación: con el fondo de hoy lo aceptado en D2 pasa. Sirve
para que en oscuro pasen la hora del cliente (`gray-11`: 4,21 hoy → 4,94 en el caso b, 6,24 en
el a) y el error (`tomato-12`: 4,32 → 5,03 / 6,11), y para que el color del canal se lea en un
solo lugar (la burbuja y la cabecera). Si el fundador prefiere conservar el lavado, la hora del
cliente y el texto de error pasan a `gray-12` (el error se sigue reconociendo por sus palabras y
su ícono); para no tener reglas distintas por tema, se usa `gray-12` en claro y en oscuro (en
claro también pasa).

TikTok (`purple`) no se midió: no tiene chat todavía.

**Qué no se midió.** (1) La pantalla real: el tinte de Instagram no está construido; esto es la
hoja real con la burbuja armada a mano. BU-A5 vuelve a medir en la app, en los dos temas, al
terminar. (2) Colores display-p3: un iPhone usa los valores p3 de Radix, un poco más saturados;
no se midieron. (3) Fotos, stickers y videos dentro de la burbuja. (4) Lectura al sol: el
contraste no la mide.

**Hallazgos fuera de esta historia (para el fundador o el sistema de diseño, no bloquean BU-A5).**
`TEXT_MUTED` (`gray-10`) no llega a 4,5:1 ni sobre la burbuja del cliente (3,50 en claro), y
`docs/design-system.md` §3 dice a la vez «secundario = gray-10» y «texto solo en pasos 11-12»;
conviene revisarlo en todo el sistema. Y «Entregado» y «Leído» usan el mismo ✓✓ y se distinguen
solo por el color (WCAG 1.4.1): en el chat tiene `aria-label`, pero a la vista no.

### D3 · Promociones — **Decidido por el fundador (2026-11-12)**

**Elegida: entrada propia «Promociones por WhatsApp» junto a «Anuncios» (zona Publica).** Las dos
sirven para llegar a gente que hoy no te está escribiendo [H, sin fuente; ninguna pregunta del §5
la cubre todavía]. **Costo aceptado:** suma una entrada al menú lateral aunque el pedido fue tener
menos; Atiende pierde «WhatsApp» y Publica gana «Promociones por WhatsApp», así que el total queda
igual.

Descartada: dentro de «Ajustes de chats › WhatsApp» como primera tarjeta (no suma entrada, pero
esconde algo que vende entre ajustes).

### D4 · Qué se vuelve igual en los dos canales — **Decidido por el fundador (2026-11-12)**

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

### D5 · Un solo nombre por cosa — **Decidido por el fundador (2026-11-12)**

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
5. **Nombres del menú automático** (condición 3 de m-24789557: ningún texto dice ni sugiere que
   Qualify responde solo). Decide el fundador; la tabla de textos que chocan está en
   `docs/arquitectura-bandeja-unica.md` §3.3. Afecta «Respuesta automática» (§2, árbol) y la franja
   «Está respondiendo tu menú automático» (§2); alternativas propuestas: «Tu menú de bienvenida» y
   «Este cliente está usando tu menú · Responder yo».
6. ~~Condición de D2: medir el contraste del tinte en claro y oscuro.~~ Hecho el 2026-11-14
   (m-25017860, «D2 medido»): lo aceptado en D2 (`{canal}-a4` con texto `gray-12`) pasa.
7. **Para el fundador — letra secundaria del chat (propuestas 5 a 9 de «D2 medido»).** «En los
   chats, la hora, el "Enviado" y las marcas ✓ de tus mensajes hoy salen en un gris tenue que
   cuesta leer, sobre todo con el celular en modo oscuro. Proponemos: ponerlos del mismo color que
   el texto, solo más pequeños; que los enlaces y los avisos de "No se envió" tengan más contraste,
   con el enlace subrayado; que la hora de los mensajes del cliente también tenga un poco más de
   contraste; y quitar el color suave que hoy se ve detrás de toda la conversación (verde en
   WhatsApp, rosa y morado en Instagram), dejando el color de cada red solo en tus burbujas y en
   la franja de arriba del chat. Verías los chats un poco más sobrios y todo se leería mejor. ¿Lo
   hacemos así, o prefieres conservar ese color de fondo?» Si dice que lo conserve, la 9 se cae y
   la hora del cliente y el error van en `gray-12` en los dos temas (ver la nota bajo la tabla).
