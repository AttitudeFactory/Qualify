# M6 · WhatsApp — auditoría de experiencia

Ruta `/whatsapp` (`Qualify/Qualify.py:229-235`, título «Qualify · WhatsApp»). Archivos revisados:
`whatsapp_page.py`, `whatsapp_tab_chats.py`, `whatsapp_tab_menu.py`, `whatsapp_tab_templates.py`,
`whatsapp_tab_contacts.py`, `whatsapp_tab_campaigns.py`, `whatsapp_metrics_block.py`,
`whatsapp_marketing_ui.py` y las etiquetas de sus `*_vm.py`. Solo sugerencias: no se tocó código.

## (a) El trabajo del módulo, en palabras del dueño

1. «Que mi WhatsApp conteste solo lo básico (menú, precios, pedido) con lo que yo escribí, y me pase el cliente cuando hace falta.»
2. «Contestar yo, desde el celular, a quien me escribió, sin perder ningún pedido.»
3. «Volver a escribirles a los que ya me compraron para que regresen (promo, cupón), sin pagar de más.»

## (b) Hallazgos, ordenados

| # | Sev. | Dónde | Problema, en palabras del dueño | Arreglo sugerido | Esf. |
|---|---|---|---|---|---|
| 1 | 1 | `whatsapp_tab_chats.py:785` + `whatsapp_chats_vm.py:117`, `:850-852` | «Este cliente me escribió ayer y ya no le puedo contestar. ¿Y ahora qué hago?» Con la conversación vencida, el cuadro de respuesta se apaga y el aviso dice «La ventana de 24 h está cerrada: solo plantillas», pero no hay forma de enviar una plantilla desde el chat. Es un callejón sin salida. | Aviso: «Pasaron más de 24 horas desde su último mensaje. WhatsApp solo deja escribirle con un mensaje aprobado.» + botón **«Enviar un mensaje aprobado»** que abre la lista de plantillas aprobadas (con vista previa) y la envía a esta persona tras confirmar. Mientras no exista: enlace «Ver tus mensajes aprobados» → pestaña Plantillas. | M |
| 2 | 1 | `whatsapp_tab_menu.py:921`, `:148-156`, `:589-624`, `:714` | «¿Qué es un "identificador del paso"? ¿Qué pongo en "Lleva a"?» El menú se arma como un diagrama: cada paso tiene un identificador en minúsculas (`mono`), y los botones se conectan eligiendo ese identificador de una lista. Además «Se guarda como» (placeholder `direccion`), «Identificador» de cada opción, «Comandos» con «/», «Motivo (para la bandeja)». Un dueño no termina esto en 2 minutos. | Pasos guiados para crear el menú (ver mockup abajo) desde la plantilla de comida rápida: el dueño solo cambia textos; los identificadores se generan solos y se muestran con el **título del paso** («Ver el menú», «Confirmar pedido»), nunca el id. El editor actual queda detrás de «Más opciones (avanzado)». | L |
| 3 | 1 | `whatsapp_tab_menu.py:333-340`, `:1000-1030`, `:1361-1376` | «Ya guardé, ¿por qué no responde?» Publicar son dos acciones separadas: «Guardar versión» arriba y «Publicar esta versión» en la tarjeta Versiones, al final de una página larguísima. En el celular la vista previa queda debajo de todo el editor. | En la barra del menú: un solo botón principal **«Publicar en mi WhatsApp»** (guarda y publica, con el diálogo de confirmación actual); «Guardar sin publicar» como secundario. Versiones, detrás de «Ver versiones anteriores». En el celular, un botón «Probar el menú» que lleva a la vista previa. | M |
| 4 | 2 | `whatsapp_tab_campaigns.py:352-399` | «¿Marca? ¿Origen del consentimiento? ¿Prefijos de país?» El paso Audiencia tiene 6 controles de operador. El dueño solo quiere «a todos mis clientes» o «a los que me compraron este mes». | Paso «¿A quién se lo envías?»: `(•) A todos tus clientes que aceptaron (128)` `( ) Solo a los que se sumaron desde…` [fecha]. Marca, origen y prefijos, detrás de «Más filtros». El conteo grande, arriba. | M |
| 5 | 2 | `whatsapp_tab_campaigns.py:419-444`, `whatsapp_campaigns_vm.py:36` | «¿Cuántos mensajes por minuto? No sé.» Hay que escribir un número entre 1 y 1000, y el aviso menciona «código 131049». | Quitar el paso «Ritmo» del camino principal: valor por defecto (30) explicado en la revisión: «Se envían de a poco (30 por minuto) para cuidar tu número: tarda unos 5 minutos.» Ajuste en «Más opciones». Quitar el código: «Si alguien ya recibió muchas promociones esta semana, WhatsApp no le entrega la tuya y no se le cobra.» | S |
| 6 | 2 | `whatsapp_tab_campaigns.py:143`, `:355`, `:549`, `:728`; `whatsapp_tab_contacts.py:124-151`, `:241-243`; `whatsapp_contacts_vm.py:25-29`; `whatsapp_templates_vm.py:49`, `:43-62` | Palabras en inglés o técnicas: «opt-in», «leads», «Formulario de leads», «Marketing», «Lanzar», «encola», «Revocar», «STOP», «WhatsApp Manager», «Sincronizar con Meta». | «opt-in» → «que aceptaron recibir tus mensajes»; «Formulario de leads» → «Formulario de clientes interesados»; «Marketing» → «Promociones»; «Utilidad» → «Avisos de pedidos»; «Lanzar» → «Enviar ahora»; «encola los envíos» → «empieza a enviar»; «Revocar» → «Quitar de la lista»; «Sincronizar con Meta» → «Ver si ya las aprobaron». «Quien escribe STOP, BAJA o CANCELAR…» → «Si alguien responde BAJA, deja de recibir tus promociones.» | S |
| 7 | 2 | `whatsapp_tab_templates.py:265-370`, `:284-293` | «Solo quiero mandar una promo.» Crear plantilla tiene 7+ campos de golpe: categoría, nombre en `promo_octubre` (minúsculas y guion bajo), idioma, encabezado, mensaje con `{{nombre}}`, ejemplos «que Meta exige», pie, botones. | Pasos: ① «¿Qué quieres avisar?» (Promoción / Aviso de pedido) ② «Escribe el mensaje» (con botón «Agregar el nombre del cliente» que inserta la variable; el ejemplo se rellena solo) ③ «Botones (opcional)» ④ «Así lo verá tu cliente» → «Enviar a aprobación». Nombre interno e idioma: automáticos (nombre desde el mensaje, idioma «Español»), editables en «Más opciones». | M |
| 8 | 2 | `whatsapp_tab_contacts.py:136-226`, `:177-214` | «Mis clientes de siempre ya me escriben por WhatsApp, ¿por qué tengo que agregarlos uno por uno?» La única forma de sumar contactos es importar desde el formulario o tipear número + «texto que aceptó». No hay camino desde Chats. | En la conversación: acción «Invitarlo a recibir tus promociones» que envía (tras confirmar) un mensaje con botones «Sí, quiero» / «No, gracias»; el «Sí» lo agrega a Contactos con ese texto como consentimiento. Hipótesis: el dueño entiende y acepta pedir permiso así (§5 pregunta 8). | L |
| 9 | 3 | `whatsapp_page.py:144-154`, `whatsapp_vm.py:43-52` | «¿Dónde estaba lo de las promos?» Ocho pestañas en una sola tira (Chats, Conexión, Perfil, QR, Menú, Plantillas, Contactos, Campañas); a 360 px hay que deslizar de lado y la mitad queda oculta. | Agrupar en 4 tareas (ver «Navegación»). | M |
| 10 | 3 | `whatsapp_page.py:136-141`, `:177-183`, `:245-309` | Encabezado de función y desactualizado: «Tu número de WhatsApp Business: estado de la conexión, perfil y códigos QR.» La pestaña Conexión muestra 10 datos de Meta («Estado del nombre», «Estado en Meta», «Datos de Meta al día»). Sin número conectado, la página es un callejón: no hay botón. | Encabezado: «Atiende y vende por WhatsApp: tus chats, tu menú automático y tus promociones.» Conexión: arriba una sola línea «Tu WhatsApp funciona bien ✓» (o qué hacer si no); los 10 datos, detrás de «Ver detalles». Sin número: «Conecta tu WhatsApp para atender y vender desde aquí» + qué gana (3 viñetas) + el pedido al equipo como paso siguiente. | S |
| 11 | 4 | `whatsapp_tab_campaigns.py:108-131`, `whatsapp_tab_templates.py:115-125`, `whatsapp_tab_contacts.py:93-103`, `whatsapp_metrics_block.py:188-210` | Tablas de 6 a 10 columnas (Enviados, Entregados, Leídos, Fallidos, Omitidos, Costo…) que en el celular se deslizan de lado. | En el celular: una tarjeta por fila con lo esencial: «Promo de octubre · Enviada · 120 la leyeron de 128 · ≈ $3» y «Ver». Ya existen `card` y `tone_pill`: no hace falta un componente nuevo. | M |
| 12 | 5 | `whatsapp_tab_chats.py:135-138`, `:760-766`, `whatsapp_tab_campaigns.py:163-181`, `whatsapp_metrics_block.py:39-44` | Detalles: «Imagen por enlace» pide una URL pública (nadie tiene una); los distintivos «Automático/Persona» y «Abierta hasta…» no se explican; el estado interno de la tarifa (`rate_card_status`) aparece en `mono`; «Primera respuesta humana · Mediana · p90». | «Imagen por enlace» → «Foto» usando `dropzone`, como en Perfil. Distintivos: «Responde el menú» / «Respondes tú» y «Puedes escribirle hasta las 6:40 p. m.». Quitar `rate_card_status` de la vista del dueño. «Primera respuesta humana» → «Cuánto tardas en responder (la mitad de las veces)». | S |

### Mockup — hallazgo 2/3: crear el menú automático en pasos

```
① ¿Cómo saludas?                     ② ¿Qué botones ve al escribirte?
┌────────────────────────────┐        ┌────────────────────────────┐
│ «¡Hola! Bienvenido a        │        │ [✓] Ver el menú            │
│  Bianki 🥙 ¿Qué se te       │        │ [✓] Hacer un pedido        │
│  antoja hoy?»   [editar]    │        │ [✓] Hablar con una persona │
│ Paso 1 de 4                 │        │ [ + Agregar botón ]  (máx 3)│
│          [ Siguiente ]      │        │ [ Atrás ]  [ Siguiente ]    │
└────────────────────────────┘        └────────────────────────────┘
③ Tus productos                      ④ Pruébalo y publícalo
┌────────────────────────────┐        ┌────────────────────────────┐
│ Se muestran los 12 de tu    │        │  📱 vista previa del chat   │
│ catálogo con su precio ✓    │        │  [Escribe como tu cliente…] │
│ [ Revisar catálogo ]        │        │ «Desde que publiques, tu    │
│ Al confirmar el pedido:     │        │  WhatsApp responde con este │
│ (•) Pedir dirección         │        │  menú. Tú tomas el chat     │
│ ( ) No pedir nada           │        │  cuando quieras.»           │
│ [ Atrás ]  [ Siguiente ]    │        │ [Publicar en mi WhatsApp]   │
└────────────────────────────┘        └────────────────────────────┘
                     Más opciones (avanzado) → editor actual
```

### Mockup — hallazgo 4/5: «Enviar una promoción» en 3 pasos

```
① ¿Qué mensaje envías?       ② ¿A quién?                   ③ Revisa y envía
 ( ) Promo de octubre ✓        (•) A todos los que           «Promo de octubre» a 128
     «Hola Ana, esta semana…»       aceptaron (128)          clientes, de a poco
 ( ) Cupón 2x1 · en revisión   ( ) Solo los que se sumaron   (unos 5 min).
 [ + Escribir uno nuevo ]           desde [__/__/____]       Costo aproximado: $3
 Nombre: Promo de oct. (auto)  Más filtros ▸                 [ Atrás ] [ Enviar ahora ]
```
(Las variables se piden dentro del paso ① solo si el mensaje las tiene.)

## (c) Navegación

**Hoy.** Un solo `page_header` («WhatsApp») + un `segmented_control` con 8 pestañas planas
(`whatsapp_vm.py:43-52`), por defecto «Chats». `select_tab` (`whatsapp_state.py:244-247`) cambia la
pestaña pero **no actualiza `?tab=`**: si el dueño recarga la página o toca «atrás» en el
celular, vuelve a Chats o sale del módulo. Asistentes y fichas abren en `drawer`. Callejones:
chat vencido (hallazgo 1), «Crea una en «Plantillas»» dentro del asistente de campaña (texto, sin
enlace, `whatsapp_tab_campaigns.py:291`), sin número conectado (sin botón), menú publicado sin
siguiente paso. Después de enviar una campaña no hay camino a las respuestas (llegan a Chats).
Además los chats de WhatsApp viven aquí y los de Instagram en `/conversations`: el dueño tiene dos
bandejas de mensajes.

**Propuesta** (mismo `segmented_control`, sin componentes nuevos):

```
WhatsApp — Atiende y vende por WhatsApp
[ Chats ] [ Respuesta automática ] [ Promociones ] [ Tu número ]
                                    │                 └─ Estado · Perfil · Códigos QR · Actividad
                                    └─ Enviadas · Mensajes aprobados · Clientes que aceptaron
```

- 4 pestañas principales; las secundarias con un segundo `segmented_control` pequeño dentro.
- Cada cambio de pestaña escribe `?tab=` (y `?sub=`), así «atrás» y recargar funcionan y los
  enlaces cruzados pueden llevar directo (`/whatsapp?tab=promociones&sub=aprobados`).
- **Siguiente paso al terminar:** menú publicado → «Haz que te escriban: crea tu código QR para el
  mostrador» (→ Tu número › QR). Plantilla enviada a aprobación → «Te avisamos cuando esté lista; mientras, revisa a quién se la enviarás» (→ Clientes que aceptaron). Campaña enviada → su ficha + «Ver respuestas en Chats». Chat vencido → «Enviar un mensaje aprobado».
- **Enlaces con otros módulos:** si el catálogo está vacío, el menú muestra «Agrega tus productos» (→ `/catalog`); los clientes interesados de `/leads` se pueden sumar desde allí a «Clientes que aceptaron».
  Unificar Chats de WhatsApp con `/conversations` es decisión de la guía global de navegación (sugerencia: una sola «Conversaciones» con filtro por red).
- Título de pestaña del navegador: sin cambio («Qualify · WhatsApp»).

## (d) Historias de usuario propuestas

**Atender**

1. **Como dueño, quiero responder a un cliente aunque hayan pasado más de 24 horas, para no perder una venta.**
   - Con la conversación vencida, el chat muestra «Enviar un mensaje aprobado» en lugar de un cuadro de respuesta apagado.
   - Lista solo mensajes aprobados, con vista previa y variables ya rellenadas (nombre del cliente si existe).
   - Se envía solo después de que el dueño toca «Enviar»; el mensaje aparece en la conversación con su estado.
   - Sin mensajes aprobados: enlace directo a crear uno.
2. **Como dueño, quiero entender de un vistazo quién responde cada chat y hasta cuándo puedo escribir, para no dejar a nadie sin respuesta.**
   - Distintivos «Responde el menú» / «Respondes tú» y «Puedes escribirle hasta las 6:40 p. m.».
   - «Imagen por enlace» se reemplaza por «Foto» que se sube desde el celular.

**Respuesta automática**

3. **Como dueño, quiero armar mi menú automático en 4 pasos cortos con mis textos y mi catálogo, para que WhatsApp atienda lo básico sin que yo aprenda a programar.**
   - Pasos: saludo → botones de inicio → productos y datos del pedido → probar y publicar; «Paso N de 4», «Atrás» sin perder datos.
   - Ningún identificador técnico visible en el camino principal; el editor actual queda en «Más opciones (avanzado)».
   - Un dueño de prueba termina en ≤ 5 min desde la plantilla de comida rápida (hipótesis: tiempo aceptable, §5 pregunta 3).
4. **Como dueño, quiero publicar mi menú con un solo botón y saber qué pasa, para no quedarme con cambios guardados que no responden.**
   - «Publicar en mi WhatsApp» guarda y publica tras confirmar con texto en lenguaje simple.
   - El texto deja claro que el menú envía los mensajes que escribió el dueño y que él puede tomar cualquier chat.
   - Tras publicar, sugiere crear el código QR (enlace a Tu número › QR).

**Promociones**

5. **Como dueño, quiero enviar una promoción a mis clientes en 3 pasos (mensaje, a quién, revisar), para que vuelvan sin pagar una agencia.**
   - Público por defecto «A todos los que aceptaron (N)»; marca, origen y prefijos en «Más filtros».
   - Ritmo con valor por defecto explicado en la revisión, sin campo numérico obligatorio.
   - La revisión dice en palabras: cuántos, cuánto tarda, costo aproximado; botón «Enviar ahora».
   - Ningún código de error ni nombre de herramienta de Meta en pantalla.
6. **Como dueño, quiero crear un mensaje de promoción guiado y sin nombres técnicos, para que me lo aprueben a la primera.**
   - Pasos: tipo (Promoción / Aviso de pedido) → mensaje con botón «Agregar el nombre del cliente» → botones opcionales → vista previa y «Enviar a aprobación».
   - Nombre interno e idioma automáticos; los ejemplos de las variables se rellenan solos.
   - Al enviar, se indica «Te avisamos cuando esté aprobado (puede tardar hasta 24 h)».
7. **Como dueño, quiero invitar desde el chat a un cliente a recibir mis promociones, para armar mi lista sin cargar números a mano.**
   - Acción en la conversación que envía, tras confirmar, un mensaje con «Sí, quiero» / «No, gracias».
   - El «Sí» lo agrega a «Clientes que aceptaron» con el texto aceptado y la fecha; «BAJA» lo quita.
   - Hipótesis por validar con §5 pregunta 8.

**Navegación y lenguaje**

8. **Como dueño, quiero encontrar lo que necesito en 4 pestañas con nombres de tareas y volver atrás sin perderme, para usar WhatsApp desde el celular sin buscar.**
   - Pestañas: Chats · Respuesta automática · Promociones · Tu número; secundarias dentro.
   - `?tab=`/`?sub=` se actualizan; recargar o «atrás» conserva la pestaña.
   - A 360 px las 4 pestañas se ven sin deslizar; los objetivos táctiles miden ≥ 44 px.
   - Se reemplazan opt-in, leads, Marketing, Lanzar, Revocar, Sincronizar con Meta y WhatsApp Manager (hallazgo 6); tablas como tarjetas en el celular (hallazgo 11).
