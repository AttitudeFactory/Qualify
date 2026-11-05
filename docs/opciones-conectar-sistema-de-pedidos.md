# Opciones: conectar Qualify con el sistema de pedidos del cliente y cobrar desde WhatsApp

**Ticket:** m-24955641 · **Fecha:** 2026-11-05 · **Autor:** principal-architect · **Estado:** `[PROPUESTO]`, pendiente de firma del fundador.
**Pedido del fundador (2026-11-05):** (1) que el pedido que el cliente de Bianki arma por WhatsApp se genere en su propio sistema (Pedidos, `~/dev/pedidos`); (2) que al terminar de agregar productos el cliente elija la forma de pago y reciba el QR o el enlace de pago con el enlace al pedido ya creado; (3) si WhatsApp acepta imágenes animadas (Lottie, GIF, SVG) en lugar de videos pesados.

Etiquetas de evidencia: **[V]** leído en código, datos o documentación oficial con fecha · **[S]** fuente de terceros · **[H]** estimación nuestra.

---

## 1. Qué existe hoy de cada lado

### 1.1 Pedidos (Bianki · Polette)

Leído en `origin/main` de `~/dev/pedidos` (`f6f9e86`, 2026-11-04). La copia local de `main` está 45 commits atrás: no sirve como referencia.

| Tema | Lo que hay | Dónde |
|---|---|---|
| Dónde corre de verdad | La idea original era la Mac de la tienda sin internet, con una copia en la nube sincronizada (`solicitud_pedido`, `bandeja_salida`, `sync_cursor`). **La sincronización nunca se construyó.** El backend en producción es `https://pedidos.attitudefactory.co`, en el mismo VPS que Qualify y detrás del mismo proxy de entrada, y la caja entra por ahí (`/puesto?tienda=bianki`, con la clave de la tienda) [V] | `docs/fase-0-arquitectura.md` §10, `docs/despliegue-vps.md`, `deploy/edge/` de este repo |
| Pedido | Tabla `pedido`: `canal` (enum `mostrador, web, whatsapp, instagram`), `entrega`, `estado` (`borrador → pago_pendiente → pagado → en_preparacion → listo → entregado/despachado`, o `cancelado`), `numero_dia` por tienda y día, `tasa_bcv` congelada al confirmar, totales en USD y Bs, `forma_pago_elegida`, `referencia_pago_declarada` [V] | `docs/esquema.sql`, `backend/migraciones/0005…0028` |
| El canal WhatsApp | Existe en el enum, pero hoy solo lo usa la caja a mano («pedido por mensaje»: la cajera lo arma mirando el chat). La API web solo acepta `canal` = `web` o `mostrador` [V] | `backend/app/web.py` (`PedidoWeb.canal`) |
| API pública | `GET /api/web/{slug}/carta` (carta, formas de pago visibles, tasas del día, entregas); `POST /api/web/{slug}/pedidos` (crea y confirma en una transacción, responde con `id` UUID v7, `numero_dia`, `a_cobrar`, `forma_pago` con su `qr`, `seguimiento`); `GET /api/web/pedidos/{id}`; `POST …/{id}/referencia` (el cliente **declara** la referencia; no confirma) [V] | `docs/api-web.md`, `backend/app/web.py` |
| Autenticación | `/api/web/*` va **sin clave**, con CORS para `bianki.com.ve` y un límite de **10 pedidos por IP y hora en memoria**. Todo lo demás exige `PEDIDOS_CLAVE_TIENDA` (cookie o `Authorization: Bearer`) [V] | `backend/app/acceso.py`, `web.py` (`LimitePorIp`, `_ip`) |
| Idempotencia | **No hay.** El POST no recibe una clave de petición: un reintento crea un segundo pedido con otro número del día [V] | `web.py` `crear_pedido` |
| Reglas que rechazan pedidos | Fuera de horario (16:00–00:00 Caracas) → 409; sin tasa VES de hoy → 409; producto inactivo → 422; **agregado obligatorio faltante** (el bowl exige proteína y aderezo) → 422 [V] | `web.py`, `docs/api-web.md` |
| Formas de pago | `pago_movil`, `tarjeta`, `efectivo_bs`, `efectivo_usd`, `efectivo_cop`, `usdt`, `bancolombia` (hoy «Bre-B · Bancolombia»), `wompi`, `wompi_qr`, `binance`; cada una con moneda, `visible_web`, `instrucciones_web`, `cuenta_de_la_empresa` [V] | `docs/esquema.sql`, migraciones `0014`, `0019`, `0022` |
| QR de pago | Imágenes fijas en `backend/app/recursos/`: `pago-movil.png` (336 KB), `bre-b-bancolombia.png` (783 KB), `binance.jpeg` (262 KB). Se sirven públicas en `/api/web/pagos/…` con versión por huella. Los datos de pago móvil (banco, RIF, teléfono) están **en el código**, no en la base. Wompi genera además un **QR por transacción** [V] | `backend/app/pagos_qr.py`, `qr_dinamico.py`, `config.py` |
| Quién confirma el pago | La cajera, para pago móvil, efectivo, tarjeta y Bre-B. **Ya no es «nunca solo»:** Wompi confirma por evento firmado (`wompi.procesar_evento`) y Binance Pay por el número de orden contra el historial firmado (`binance.py`, `docs/binance-pay.md`). Hay ramas abiertas de conciliación de pago móvil y botón BDV [V] | `wompi.py`, `binance.py`, ramas `feat/conciliacion-pago-movil`, `feat/boton-pago-bdv` |
| Monedas y tasa | VES, USD, COP, USDT; precio en USD; tasa BCV (VES) y TRM (COP) cargadas solas cada 30 min; USDT a la par; pago mixto y vuelto en otra moneda en caja [V] | `README.md`, `tasas_oficiales.py` |
| Enlace del pedido | `https://bianki.com.ve/seguimiento?id=<uuid>` (`seguimiento.enlace`), con QR en SVG y avisos push del navegador [V] | `backend/app/seguimiento.py` |

### 1.2 Qualify al cerrar el pedido por WhatsApp

- El menú (`whatsapp/menus/engine.py`) recorre `products → (agregado) → order_summary → collect (dirección) → handoff`. Al confirmar, `orders.record_confirmed_order` guarda en `whatsapp_thread_state.context["_order"]`: ítems (`product_id`, `name`, `qty`, `unit_price`, `currency`), `total`, `currency`, `confirmed_at`, `collected` (p. ej. `direccion`), y procedencia (`source_message_id` = el `wamid` que confirmó, `engine_version`). Es **idempotente por `wamid`** [V].
- El teléfono del cliente sale del hilo de WhatsApp; el nombre, del perfil de WhatsApp (no se pide) [V].
- `product_id` es el id de `brand_products` de **Qualify**, no el UUID de la carta de Pedidos. **El menú no maneja agregados** (proteína, aderezo): un bowl pedido por WhatsApp hoy sería rechazado por Pedidos con 422 [V].
- «Formas de pago» es un texto fijo con un hueco (`menus/starter.py`, `PAYMENT_TEXT`) [V].
- El envío de imágenes desde el chat existe (`attachments.py`, `client.upload_media`; 2026-11-04). El cliente soporta texto, botones (máx. 3), listas (máx. 10 filas), plantillas e imagen/video/documento/audio; **no tiene `sticker`** (`client.MediaKind`) [V].
- No existe en Qualify ningún conector saliente hacia sistemas de clientes ni webhooks firmados de salida [V].

---

## 2. Opciones para conectar

Común a todas: el pedido sigue **asistido**. Crear el pedido en Pedidos lo deja en `pago_pendiente`; cocina no lo ve hasta que la caja confirma el pago (o Wompi/Binance lo confirman), igual que un pedido web. No se cobra nada solo.

| | 0. No hacer nada | A. Qualify llama a la API de Pedidos | B. Webhook firmado `order.confirmed` | C. Enlace al checkout con el carrito | D. Interfaz «conector de pedidos», Pedidos primer adaptador |
|---|---|---|---|---|---|
| **Qué es** | El traspaso queda como hoy: la cajera ve la tarjeta del pedido en Conversaciones y lo vuelve a tipear en `/puesto` | Al confirmar, un worker de Qualify hace `POST /api/web/bianki/pedidos` con canal `whatsapp` y guarda el `id`, `numero_dia` y enlace | Qualify publica un evento firmado (HMAC) a una URL que el cliente registra; el sistema del cliente crea el pedido y responde | Qualify manda un enlace a `bianki.com.ve/pedir?carrito=…` y el cliente termina el pedido en la web | Un puerto `OrderSink` en Qualify con adaptadores: `pedidos_api` (A), `webhook` (B), `manual` (0) |
| **Dueño** | Doble tipeo; errores de transcripción | El pedido aparece solo en «Pedidos por cobrar» con chip WhatsApp | Igual que A, si su sistema sabe recibir | Igual que un pedido web | Igual que A para Bianki; elige el adaptador en Ajustes |
| **Cliente final** | Espera a que la cajera lo pase | Recibe número del día, total en su moneda, QR/enlace de pago y enlace de seguimiento en el chat | Igual que A, más lento si el sistema responde tarde | Sale de WhatsApp a una web: más pasos, se pierde parte | Igual que A |
| **Esfuerzo** | 0 | Qualify ~4–6 días; Pedidos ~2 días (canal, clave de servicio, idempotencia, mapeo) [H] | Qualify ~4 días; **el cliente** tiene que programar el receptor | ~2 días en Pedidos (leer el carrito de la URL); poco en Qualify [H] | A + ~2 días para el puerto y el adaptador webhook genérico [H] |
| **Aislamiento** | n/a | Credencial por negocio (`brand_id`), cifrada como `oauth_credentials`, leída solo por `credential_session` | Secreto HMAC por negocio, mismo resguardo | No hay credencial; el carrito viaja en la URL | El conector es una fila por negocio con RLS |
| **Idempotencia** | n/a | Hoy **no existe** en Pedidos: hace falta `Idempotency-Key` = id de la fila de salida (o `source_message_id`) y `unique` en Pedidos | Firmado con `event_id`; el receptor tiene que deduplicar (no lo controlamos) | El cliente puede abrir el enlace dos veces → dos pedidos | Lo exige el contrato del puerto |
| **Si Pedidos está caído** | n/a | Bandeja de salida con reintentos (como `whatsapp_outbox`); al tercer fallo vuelve al traspaso manual y avisa al dueño. Sin conciliación: Pedidos ya no corre sin internet | Igual, del lado del cliente | El cliente ve error en la web | Igual que A |
| **Qué deja al segundo cliente** | Todo manual | Nada, salvo que tenga Pedidos | Sirve a cualquiera que programe un receptor (raro en una pyme) | Solo a quien tenga una web con carrito | El puerto; cada sistema nuevo es un adaptador |
| **Riesgo principal** | Se queda la queja | Acoplar Qualify a un contrato que cambia sin aviso (`api-web.md` lo protege para el landing, no para nosotros) | Ningún cliente pyme tiene dónde recibirlo | Contradice el valor: cerrar el pedido dentro del chat | Diseñar la abstracción con un solo caso real |

**Datos a tener en cuenta para A/D [V]:** todo Qualify llama desde la misma IP del VPS, así que el límite de 10 pedidos por IP y hora cortaría el día 11; hace falta una ruta de servicio con clave (`Authorization: Bearer`), no la pública. Pedidos tiene que aceptar `canal = "whatsapp"` (el enum ya lo tiene). Y Qualify tiene que mandar los UUID de la carta de Pedidos y los agregados obligatorios.

**Mapeo del catálogo:** la opción más barata es que Qualify **lea la carta de Pedidos** (`GET /carta`, público) y guarde el UUID externo en cada producto (`brand_products.external_ref`), en vez de mantener dos cartas a mano. Los agregados obligatorios piden un nodo nuevo en el menú («elige proteína»). Mientras no esté, los productos con `minimo > 0` quedan fuera del pedido por WhatsApp o pasan por la persona.

Costos [V/H]: llamar a Pedidos cuesta US$ 0 (mismo VPS). Los mensajes de servicio de WhatsApp dentro de las 24 horas no se cobran por mensaje [S, tarifario de Meta; se verifica con la factura]. Filas nuevas: ~1 por pedido de WhatsApp. Con 30 pedidos por día y negocio, ~11 mil al año: no cambia nada en Postgres.

---

## 3. El paso de pago, de punta a punta (Bianki)

```
order_summary «Confirmar» → collect dirección (si delivery)
→ NUEVO nodo payment_method: lista con las formas visibles por WhatsApp (máx. 10 filas)
→ Qualify crea el pedido en Pedidos con forma_pago elegida (opción A)
→ responde Pedidos: numero_dia, a_cobrar (monto en la moneda de la forma, tasa del día), forma_pago.qr, seguimiento
→ Qualify envía UN mensaje: imagen del QR como cabecera + «Pedido N.º 12 · Bs 2.555,00 a tasa BCV 182,5 · Paga con Pago móvil…» + botón «Ver mi pedido» (enlace de seguimiento)
→ el cliente paga y responde con la referencia (o la foto del comprobante)
→ Qualify la pasa a Pedidos (POST …/referencia) → la cajera confirma en /puesto → cocina
→ (luego) Qualify avisa «tu pedido está listo» leyendo el estado del pedido
```

- **Cómo se muestra.** Lista interactiva para elegir (las formas de Bianki por web hoy son ≤ 10) y luego un mensaje con botón de enlace (`interactive` tipo `cta_url`): admite **cabecera de imagen por enlace público** y texto de botón de hasta 20 caracteres [V, https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-cta-url-messages, leído 2026-11-05]. Los QR de Pedidos ya son públicos y pesan menos de 5 MB (límite de imagen) [V]. `cta_url` todavía no está en `client.py`: se agrega como un tipo más.
- **Dónde viven las formas de pago y los QR.** Para Bianki, **el dueño es Pedidos**: Qualify las lee de `GET /carta` (`formas_pago[].qr.imagen`, `instrucciones`) y no copia nada. Copiar los QR a Qualify dejaría dos lugares para cambiar cuando Bianki cambie de cuenta, y uno siempre queda viejo. **Para el producto** (un negocio sin sistema propio) hace falta la misma idea en Qualify: «Datos de pago» por negocio (`brand_id`), con nombre, moneda, instrucciones y una imagen de QR en R2. Es lo que encaja con el ticket m-24945889 (atajos). Con ese conector en «manual», el nodo de pago muestra esos datos y la confirmación queda en la persona que atiende el chat.
- **Quién confirma.** Asistido: la cajera, como hoy. Wompi y Binance siguen confirmando solos dentro de Pedidos, no en Qualify. Qualify **nunca** marca un pago como hecho; a lo sumo lleva la referencia que escribió el cliente.
- **Monedas y tasa.** El precio base es USD; el monto a cobrar y la tasa los calcula Pedidos al confirmar (BCV/TRM del día). Qualify muestra el `a_cobrar` que recibe y nunca convierte por su cuenta. Para un negocio sin sistema, el total sale en la moneda de su catálogo y la conversión queda fuera de alcance (se dice «te confirmamos el monto»).
- **Pagos parciales y mixtos.** Por WhatsApp se elige **una** forma. Lo mixto (parte en dólares, parte en pago móvil, vuelto en pesos) sigue en caja, donde ya funciona. Si el cliente paga de menos, la cajera lo ve al buscar la referencia y escribe por el chat.
- **Qué es de Bianki y qué es producto.** De Bianki: el adaptador de Pedidos, sus formas (pago móvil, Bre-B, Binance, Wompi), BCV/TRM, la regla de horario y de tasa del día. Producto: el nodo «elige cómo pagar», el mensaje con QR y enlace, la recepción de la referencia, «Datos de pago» por negocio y el puerto de conector.

---

## 4. Imágenes animadas en WhatsApp

Verificado contra la documentación de Meta el **2026-11-05**: https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media, …/messages/sticker-messages y …/messages/video-messages.

| Formato | ¿Lo acepta la Cloud API? | Límite |
|---|---|---|
| Imagen JPEG / PNG / WebP fijo | Sí [V] | 5 MB, 8 bits RGB/RGBA, ≤ 4.096 px por lado; el WebP fijo se convierte a JPEG; **un WebP animado como imagen se rechaza** [V] |
| Sticker WebP animado | Sí [V] | **500 KB**; fijo 100 KB; solo WebP; **sin texto al pie** [V]. Medida 512×512 y límites de cuadros: la página no lo dice [no verificado] |
| Video MP4 / 3GPP | Sí [V] | 16 MB; H.264 Main/Baseline sin cuadros B, AAC o sin audio, `faststart` [V]. **No se reproduce solo**: muestra una miniatura y se abre al tocar [V] |
| GIF | **No figura** en la lista de tipos [V por ausencia]. No hay bandera de «reproducir como GIF» en el objeto `video` [V]. Las APIs no oficiales que «mandan GIF» mandan un MP4 [S] |
| SVG | No figura [V por ausencia] |
| Lottie | No figura [V por ausencia] |

**Para «el producto humeando»:** la opción realista es un **sticker WebP animado** de 2–3 s, 512×512, ~12–15 cuadros por segundo, **≤ 500 KB** (para que se mueva solo, sin tocar). Un MP4 sin audio de 3–5 s a 480–720 px pesa unos **200–600 KB** [H] y se ve mejor, pero el cliente tiene que tocarlo. Recomendación: sticker para el saludo o el «ya va tu pedido»; MP4 corto cuando importa que se vea bien el producto. Agregar `sticker` a `client.py` es pequeño (mismo envío por `id` subido). Generar el WebP desde un clip del catálogo con `ffmpeg` es una prueba barata que se mide antes de prometer el tamaño (`qualify-measure`).

---

## 5. Recomendación

**Opción D en su versión mínima: el puerto de conector con dos adaptadores, `manual` (lo de hoy, con «Datos de pago» de Qualify) y `pedidos_api` (A) para Bianki.** Descartar B y C por ahora.

- **Por qué.** A es lo único que cumple el pedido (el pedido nace en el sistema de Bianki desde el chat y el cliente recibe el pago y el enlace sin salir de WhatsApp). Ponerlo detrás de un puerto cuesta ~2 días y evita que el segundo cliente obligue a reescribir. B no tiene quién lo reciba en una pyme. C saca al cliente del chat.
- **Criterios.** (1) Cero pedidos duplicados por reintentos. (2) El pago lo confirma una persona o el proveedor de pagos dentro de Pedidos, nunca Qualify. (3) Si Pedidos falla, el pedido vuelve al traspaso manual sin perderse. (4) Un solo dueño para cada dato (formas y QR en Pedidos para Bianki).
- **La reabrimos si:** antes del 2026-12-31 aparece un segundo negocio con un sistema propio que no sea Pedidos (entonces se diseña el adaptador `webhook` con ese caso real); o si en el primer mes más del 10 % de los pedidos por WhatsApp de Bianki vuelven al traspaso manual por errores de la API (entonces el acoplamiento cuesta más de lo que ahorra); o si WA-23 (catálogo nativo con carrito) se vuelve prioridad.
- **Lo que pide a Pedidos (otro repositorio, otro dueño):** una ruta de servicio autenticada (`POST /api/servicio/{slug}/pedidos` o la misma con `Bearer`) que acepte `canal = whatsapp`, un `Idempotency-Key` con `unique`, sin límite por IP para esa clave, y `GET` del estado para el aviso de «listo». Nada de eso se toca desde este repo.

### Borrador de ADR (fila de §6)

| 47 | **[PROPUESTO — m-24955641, 2026-11-05]** **Los pedidos que cierra el menú de WhatsApp salen por un puerto «conector de pedidos» (`OrderSink`) con adaptadores por negocio: `manual` (traspaso a una persona, con «Datos de pago» de Qualify) y `pedidos_api` (crea el pedido en el sistema del cliente por su API de servicio). Una bandeja de salida idempotente (clave = fila de salida) con reintentos y vuelta al traspaso manual. Qualify muestra el pago que el sistema del cliente calcula y nunca lo confirma.** Credencial por `brand_id`, cifrada y leída solo por `credential_session`; RLS en las tablas nuevas; procedencia `source_message_id` + versión del adaptador. Detalle en `docs/opciones-conectar-sistema-de-pedidos.md` | (B) Webhook firmado `order.confirmed`; (C) enlace al checkout web con el carrito; (0) seguir manual | (B) Ninguna pyme tiene dónde recibirlo. (C) Saca al cliente del chat. (0) Doble tipeo en caja. El puerto cuesta ~2 días y deja lugar al segundo sistema sin reescribir | Un segundo negocio con sistema propio distinto de Pedidos; > 10 % de traspasos manuales por fallas de la API en el primer mes; WA-23 priorizado |

### Historias propuestas (para el product owner)

1. **Carta de Pedidos en Qualify** — `brand_products` guarda el UUID de la carta de Pedidos; un botón «Traer carta» la sincroniza. *Acepta:* los productos de Bianki en Qualify tienen su UUID externo y precio en USD igual a `GET /carta`.
2. **Agregados obligatorios en el menú** — nodo «elige tu proteína/aderezo» según `grupos.minimo`. *Acepta:* un bowl pedido por WhatsApp lleva sus agregados y Pedidos no responde 422.
3. **Ruta de servicio en Pedidos** (repo Pedidos) — `Bearer` por tienda, `canal=whatsapp`, `Idempotency-Key` único, sin límite por IP. *Acepta:* el mismo POST repetido devuelve el mismo pedido.
4. **Conector de pedidos y bandeja de salida** — puerto `OrderSink`, adaptadores `manual` y `pedidos_api`, reintentos y vuelta al traspaso. *Acepta:* con Pedidos apagado el pedido llega al traspaso manual y el dueño lo ve; nunca hay dos pedidos para una confirmación.
5. **«Elige cómo pagar» en el chat** — nodo de lista con las formas del negocio; mensaje `cta_url` con QR de cabecera, número del pedido, monto y «Ver mi pedido». *Acepta:* el cliente recibe QR y enlace en un solo mensaje después de elegir.
6. **Referencia de pago desde el chat** — el texto que manda el cliente después del pago va a `…/referencia`; la cajera la ve en `/puesto`. *Acepta:* la referencia aparece en el puesto sin tipearla.
7. **«Datos de pago» por negocio** (para quien no tiene sistema; une con m-24945889) — nombre, moneda, instrucciones e imagen QR en R2. *Acepta:* un negocio sin conector muestra sus datos al elegir la forma de pago.

Aparte, y pequeño: **sticker animado** — `sticker` en `client.py` y prueba medida de WebP ≤ 500 KB desde un clip del catálogo.

### Preguntas para el fundador

1. ¿La caja de Bianki trabaja siempre contra `pedidos.attitudefactory.co` (VPS) y no contra la Mac sin internet? Esta propuesta lo da por hecho.
2. ¿Qué formas de pago se ofrecen por WhatsApp? (¿las mismas que en la web: pago móvil, Bre-B, Binance, Wompi?)
3. ¿Aceptas que formas de pago y QR de Bianki sigan viviendo en Pedidos y que Qualify los lea, en vez de cargarlos dos veces?
4. ¿Prioridad: primero «elige cómo pagar» con los datos de Pedidos (historias 1, 3, 5) y después la creación automática del pedido, o todo junto?
