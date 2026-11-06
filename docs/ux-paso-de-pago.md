# Al terminar el pedido, tu cliente elige cómo pagarte (m-24955648)

Especificación de experiencia (ux-designer, 2026-11-05). Base firmada: `docs/opciones-conectar-sistema-de-pedidos.md`
D2–D4, D7, §3, §3.1 e historias 1, 3 y 4. Hoy «Formas de pago» es un texto que nadie usa y el pedido
termina en «Pedido confirmado» (traspaso). Sin componentes ni colores nuevos: `card`, `choice_card`,
`media_thumb`, `chat_bubble`, `dropzone`, `sort_handle`, `drawer`, `step_progress`, `callout`,
`signal_pill`, `tone_badge`, `empty_state`, `rx.switch`. **No se revisó en la app corriendo:** es propuesta.

## 1. Decisiones

1. **Dónde vive: WhatsApp → «Tu número» → «Formas de pago»** (subpestaña nueva, con su dirección propia,
   entre Perfil y Códigos QR). El dueño piensa «lo que mi cliente ve de mi negocio en WhatsApp»: ahí ya
   están Perfil y los QR, y `ux-whatsapp-enviar-imagen.md` §2.4 ya ubicaba ahí «Tus datos de pago»
   (este diseño lo reemplaza). Son **del negocio, no del número**: con dos números se ve la misma lista
   y la línea «Son las mismas para todos tus números». (El §3.1 decía «Ajustes»: pregunta 1.)
2. **Una forma = una tarjeta**, la misma en el menú automático, en el selector del chat y en la vista
   previa: foto del QR (si hay) con pie = instrucciones + total + qué hacer ahora.
3. **Nombre ≤ 20 caracteres** (cabe en un botón de WhatsApp). **Instrucciones ≤ 900**: Qualify agrega
   al pie el total y el cierre (~120); el pie completo nunca pasa de 1024. El motor lo valida al enviar.
4. **Campo nuevo pequeño: «¿Cuándo te paga?»** (`pay_on_delivery`, antes / al recibir). Sin él, al
   efectivo le pediríamos un comprobante que no existe. Va en el PR 1 con la tabla.
5. **Nada se da por pagado solo.** Qualify marca el chat; una persona toca «Pago recibido» y revisa el
   mensaje antes de que salga (N13).
6. **Botones si hay ≤ 3 activas, lista si hay 4 a 10.** Máximo 10 activas (lo que cabe en la lista).

## 2. Formas de pago (el dueño)

**Lista.** Título «Formas de pago»; ayuda «Tu cliente las elige al terminar su pedido y le llegan tus
datos al instante. Tú solo confirmas que el pago llegó.» Fila: asa `sort_handle` + «⋯» (Editar · Primero
· Subir uno · Bajar uno · Último · Borrar), miniatura del QR (`media_thumb`, `alt` «QR de Pago móvil»;
sin QR, icono `banknote` y píldora «Sin QR»), nombre, moneda en palabras («En bolívares»), «Actualizado
el 5 nov.» y el interruptor con etiqueta visible **«La ofreces»** (no solo color). Bajo la lista: «Con
hasta 3, tu cliente las ve como botones; con más, en una lista.» Se guarda al soltar, aviso 6 s
«Listo: «Pago móvil» va primero.» [Deshacer] (igual que `ux-orden-de-productos.md`). Botón **«Agregar
forma de pago»**.
- Activar sin instrucciones ni QR: «Para ofrecerla, escribe cómo te pagan o sube tu QR.» [Editar].
- La 11.ª: «Ya ofreces 10, lo máximo que muestra WhatsApp. Apaga una para ofrecer esta.»
- Borrar: «¿Borrar «Binance»? Tus clientes dejan de verla. Los chats donde ya la enviaste no cambian.»
  [Borrar] [Dejarla].
- **Vacío** (`empty_state`): «Cobra por WhatsApp sin dictar tus datos» · «Carga tu pago móvil, tu llave
  o tu QR una vez. Cuando alguien termine su pedido, le llegan tus datos y tú solo confirmas el pago.»
  [Agregar forma de pago].

**Agregar o editar: 4 pasos** (`drawer` a pantalla completa en el celular, «Paso N de 4», «‹ Atrás» sin
perder nada; al editar, se abre en el paso 4 con «Cambiar» en cada bloque).
1. **«¿Cómo se llama esta forma de pago?»** Atajos (`choice_card`): Pago móvil · Transferencia · Bre-B ·
   Nequi · Binance · Efectivo al recibir · «Otra». Campo «Nombre que ve tu cliente» (pre-lleno, 20/20).
   «¿En qué moneda?» (pre-llena la moneda del negocio; Binance → USDT). «¿Cuándo te paga?»: «Antes de
   recibir (te manda el comprobante)» / «Al recibir el pedido» (Efectivo lo pre-elige).
2. **«¿Qué tiene que saber tu cliente para pagarte?»** Ayuda: «Escribe solo lo que le dirías por
   WhatsApp. Qualify no pide ni muestra más datos que estos.» Área de texto con etiqueta visible y
   contador «0/900», pre-llena con un ejemplo según el atajo (lo de `[ ]` es para reemplazar):
   - Pago móvil: «Banco [nombre] ([código]) · Cédula o RIF: [número] · Teléfono: [número]»
   - Bre-B / Transferencia: «Llave Bre-B: [tu llave] · A nombre de: [titular]» / «Banco [nombre],
     cuenta [número], a nombre de [titular]» (sirve en CO, VE y UY)
   - Nequi: «Nequi al [número], a nombre de [titular]» · Binance: «Binance Pay ID: [número] · Solo USDT»
   - Efectivo: «Pagas en efectivo cuando te llega. Si necesitas vuelto, dinos con cuánto pagas.»
   Con `[` o `]` sin cambiar no deja seguir: «Cambia lo que está entre [ ] por tus datos.»
3. **«¿Tienes un QR para esta forma de pago?»** (opcional) `dropzone` «Sube la foto o captura de tu QR»
   (JPEG/PNG ≤ 5 MB, como las fotos del chat). Botones «Siguiente» y «Sin QR». Si pesa más: «Esa foto
   pesa más de 5 MB. Toma una captura de pantalla del QR y súbela.»
4. **«Así le llega a tu cliente»** `chat_bubble` de salida con la tarjeta de §3 y un total de ejemplo
   («Total: $18 (ejemplo)»). Interruptor «Ofrecerla desde ya» (encendido). **[Guardar]**. Aviso: «Listo:
   tus clientes ya pueden elegir «Pago móvil».» (apagado: «Guardada. Enciéndela cuando quieras.»)

## 3. Lo que ve el cliente en WhatsApp

Va después de la dirección (o después de «Confirmar» si el menú no la pide), solo si hay ≥ 1 activa.
- **Pregunta.** Cuerpo: «¿Cómo quieres pagar? Total: $18». ≤ 3 → botones con los nombres; si hay 1 o 2,
  el último botón es «Otra forma». 4 a 10 → lista, botón «Elegir», filas: título = nombre, descripción =
  moneda en palabras («En bolívares», «En pesos», «En dólares», «En USDT»); si hay ≤ 9, última fila «Otra
  forma de pago» · «Te escribe una persona del equipo».
- **Un solo mensaje** (imagen del QR con pie; sin QR, el mismo texto solo):
  > {instrucciones}
  > Total: $18
  > *(moneda distinta a la del catálogo:)* Te confirmamos el monto en bolívares.
  > Cuando pagues, envíanos el comprobante o el número de referencia por aquí. Una persona del equipo
  > lo revisa y te confirma.
  Al recibir: el cierre es «Pagas al recibir tu pedido. Una persona del equipo te confirma en un momento.»
- Después el chat pasa a «Respondes tú» (como hoy con «Pedido confirmado»). No hay acuse automático:
  el comprobante llega como un mensaje más. El total usa el mismo formato que el resumen del pedido.
- **Escribe otra cosa:** se repite una vez («Elige una de las opciones para seguir.»); a la segunda,
  traspaso con «Forma de pago: no eligió». **«Otra forma»:** traspaso, «Forma de pago: quiere otra».
  **Calla:** nada automático ni recordatorios; queda «Esperando el pago». Forma apagada a mitad: se
  pregunta de nuevo con las que siguen ofrecidas; si no queda ninguna, traspaso.

## 4. Lo que ve el dueño en Chats

- **Estados** (`signal_pill`, texto + tono, en la fila de la lista y en la cabecera junto a «Respondes
  tú»): «Esperando el pago» (neutral) tras la tarjeta · **«Pago por revisar»** (warn) en cuanto el
  cliente manda algo (foto o texto) · «Paga al recibir» (neutral) · «Pago recibido» (ok, ese día).
  Filtro nuevo «Pago por revisar» junto a Abiertos · Cerrados · Sin leer.
- **Tarjeta del pedido** (la de hoy, `_order_card`): fila «Paga con: Pago móvil (en bolívares)» y el
  botón principal **«Pago recibido»** (antes de «Pedido listo»). Al tocarlo, hoja pequeña:
  «¿Ya te llegó el pago de {nombre}?» · «Busca la referencia en tu banco antes de confirmar.» · texto
  editable ya escrito: **«¡Pago recibido, gracias! Ya estamos preparando tu pedido.»** (hipótesis
  para rubros que no son de comida, perfil §5 pregunta 4) · [Enviar y marcar pagado] [Todavía no].
- Secundario **«No lo encuentro»**: no envía; escribe en el cuadro «Todavía no nos aparece tu pago.
  ¿Nos mandas la foto del comprobante o el número de referencia?» y el dueño toca «Enviar».
- **Cómo se limpia:** solo con «Enviar y marcar pagado». La tarjeta dice «Pago recibido · lo confirmó
  Ana a las 3:42 p. m.» No hay deshacer (el mensaje ya salió): por eso la hoja.
- Fuera de las 24 h la hoja no envía: «Ya pasaron 24 horas. Márcalo pagado y avísale con un mensaje
  aprobado.» [Marcar pagado sin avisar].

## 5. «Formas de pago» en el selector del chat (Orbit, m-24955785)

Opción «Formas de pago» · «Tus datos para que te pague, con tu QR.» Pasos: ① qué mandar → ② «¿Cuál
forma de pago?» (`choice_card`: miniatura, nombre, moneda, «Actualizado el …») → ③ «Revisa y envía»:
la misma tarjeta; si el chat tiene pedido, con su «Total»; si no, sin esa línea. El pie **no se edita
aquí** (evita cambiar una cuenta por error): enlace «Cambiar estos datos» → Formas de pago, vuelve con
«‹ Volver al chat». Desde el Orbit abre en ② («Paso 1 de 2»); con una sola activa, directo a ③.
Enviarla en un chat con pedido lo marca «Esperando el pago». Sin formas: «Aún no cargas tus formas de
pago» [Agregar forma de pago].

## 6. Negocio sin formas de pago

El recorrido queda como hoy. Avisos: (a) Respuesta automática, paso del pedido: `callout` info «Tus
clientes pueden elegir cómo pagarte al terminar su pedido.» [Agregar formas de pago]; (b) la respuesta
«Formas de pago» del menú de inicio se arma sola con las activas: «Aceptamos Pago móvil (en bolívares),
Bre-B Bancolombia (en pesos) y efectivo al recibir. Te pasamos los datos al terminar tu pedido.»; sin
ninguna, se queda el texto del dueño; (c) el vacío del selector (§5).

## 7. Maquetas (375 px)

```
① Formas de pago                    ② Paso 4 de 4
┌───────────────────────────────┐   ┌───────────────────────────────┐
│ Estado Perfil [Pagos] QR Act. │   │ ‹ Atrás           Paso 4 de 4 │
│ Formas de pago                │   │ Así le llega a tu cliente     │
│ Tu cliente las elige al termi-│   │        ┌────────────────────┐ │
│ nar su pedido...              │   │        │ [  QR  ]           │ │
│ ⠿ [QR] Pago móvil         ⋯   │   │        │ Banco de Venezuela │ │
│        En bolívares           │   │        │ (0102) · RIF ...   │ │
│        5 nov.   (●) La ofreces│   │        │ Total: $18 (ejem.) │ │
│ ⠿ [QR] Bre-B Bancolombia  ⋯   │   │        │ Te confirmamos el  │ │
│ ⠿ [$]  Efectivo  Sin QR   ⋯   │   │        │ monto en bolívares.│ │
│ Con hasta 3, botones; con más,│   │        │ Cuando pagues, ... │ │
│ una lista.                    │   │        └────────────────────┘ │
│ [ + Agregar forma de pago ]   │   │ (●) Ofrecerla desde ya        │
└───────────────────────────────┘   │ [           Guardar         ] │
                                    └───────────────────────────────┘
③ WhatsApp del cliente              ④ Chat del dueño
┌───────────────────────────────┐   ┌───────────────────────────────┐
│ Bianki: ¿Retiras o te lo...?  │   │ ‹ Chats   María G.            │
│ Tú: Envío · Calle 5 #12       │   │ [Respondes tú][Pago por revisar]│
│ Bianki: ¿Cómo quieres pagar?  │   │ ┌ Pedido confirmado  3 prod. ┐│
│ Total: $18                    │   │ │ 2 Shawarma pollo     $10   ││
│ [Pago móvil][Bre-B][Efectivo] │   │ │ Total               $18    ││
│ Tú: Pago móvil                │   │ │ Paga con: Pago móvil (Bs)  ││
│ Bianki: [QR] Banco de Vzla... │   │ │ [Pago recibido] No lo encuentro│
│ Total: $18 · Te confirmamos...│   │ └────────────────────────────┘│
│ Cuando pagues, envíanos...    │   │ María: [foto] Ref 00987654    │
│ Tú: [foto] Ref 00987654       │   │ Escribe una respuesta…  [Env.]│
└───────────────────────────────┘   └───────────────────────────────┘
```

## 8. Entregas para `reflex-ui-engineer` / `backend-engineer`

- **PR 1 — las formas de pago:** tabla `brand_payment_methods` (§3.1 + `pay_on_delivery`, nombre ≤ 20,
  instrucciones ≤ 900, máx. 10 activas) y la subpestaña «Formas de pago» con lista, orden, interruptor,
  borrar y los 4 pasos con vista previa. No cambia nada de lo que ve el cliente.
- **PR 2 — el cobro:** nodo `payment_method`, tarjeta QR + pie, estados y filtro, «Pago recibido»,
  «No lo encuentro», opción del selector (y del Orbit con m-24955785), avisos de §6.

## 9. Preguntas para el fundador

1. ¿Las formas de pago van en WhatsApp → Tu número (recomendado) o en Configuración, como decía §3.1?
2. Si el cliente elige «Retiro en el local», ¿igual le preguntamos cómo pagar o paga en caja?
   (hipótesis: en Bianki muchos pagan al retirar).
3. Con «te confirmamos el monto en bolívares», la cajera escribe el monto a mano. ¿Sirve así en esta
   versión, o la tasa del día de la carta de Pedidos entra ya?
