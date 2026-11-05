# Opciones: conectar Qualify con el sistema de pedidos del cliente y cobrar desde WhatsApp

**Ticket:** m-24955641 · **Fecha:** 2026-11-05 · **Autor:** principal-architect · **Estado:** decisiones de producto **firmadas por el fundador el 2026-11-05** (abajo); el ADR 47 sigue `[PROPUESTO]`.
**Pedido del fundador (2026-11-05):** (1) que el pedido que el cliente de Bianki arma por WhatsApp se genere en su propio sistema (Pedidos, `~/dev/pedidos`); (2) que al terminar de agregar productos el cliente elija la forma de pago y reciba el QR o el enlace de pago con el enlace al pedido ya creado; (3) si WhatsApp acepta imágenes animadas (Lottie, GIF, SVG) en lugar de videos pesados.

Etiquetas de evidencia: **[V]** leído en código, datos o documentación oficial con fecha · **[S]** fuente de terceros · **[H]** estimación nuestra.

---

## Decisiones del fundador (2026-11-05)

Mandan sobre el análisis de abajo; donde lo contradicen, el texto de abajo ya está ajustado.

| # | Decisión | Qué cambia |
|---|---|---|
| D1 | La caja de Bianki **trabaja siempre contra el servidor** (`pedidos.attitudefactory.co`), nunca contra la Mac sin internet | No hay que encolar y conciliar con una tienda desconectada. El único caso es «el servidor de Pedidos no responde»: se mantienen la bandeja de salida idempotente y la vuelta al traspaso manual |
| D2 | **Qué formas de pago se ofrecen por WhatsApp lo decide el negocio.** Las de hoy son las de Pedidos y su web: Pago móvil, Bre-B · Bancolombia, Binance Pay, Wompi (tarjeta, Nequi o QR Bancolombia) | Cada forma tiene en Qualify su interruptor «activa» y su orden, que maneja el dueño |
| D3 | **Las formas de pago y sus QR también se cargan en Qualify.** Pasan a ser una opción más del selector del chat (hoy «Foto o menú»: Tus productos · Tus piezas · Tu menú · Una foto de tu celular). El botón se renombra, porque ya no tendrá solo fotos y el menú. Esto anula mi recomendación de no duplicar | Diseño en §3.1: dónde viven, cómo se cargan las de Bianki, una sola fuente para el menú automático y el selector manual, y cómo se vigila la duplicación |
| D4 | **Primero sale «elige cómo pagar», con confirmación manual** del dueño o la cajera. La creación automática del pedido en Pedidos viene después | Las historias de §5 están reordenadas y la 1 no depende de Pedidos |
| D5 | **Nuevo:** un módulo que genere stickers animados (WebP ≤ 500 KB) y videos cortos sin sonido de 3 a 5 s con la identidad de la marca, para WhatsApp. Se regeneran por temporada (Navidad) y son dos opciones más del mismo selector | Bosquejo de opciones en §4.1, **sin decisión** |

### Lo que ve el cliente de Bianki (versión «primero el pago»)

> **Bianki:** Tu pedido: 2 Shawarma de pollo · 1 Bowl armable. Total: $19,00. [Confirmar] [Agregar más] [Cancelar]
> **Cliente:** *toca* Confirmar
> **Bianki:** ¿Retiras en el local o te lo llevamos? → *el cliente elige y, si es envío, escribe la dirección*
> **Bianki:** ¿Cómo quieres pagar? [Elegir] → *se abre una lista:* Pago móvil (bolívares) · Bre-B Bancolombia (pesos) · Binance (USDT)
> **Cliente:** *elige* Pago móvil
> **Bianki:** *(imagen del QR de pago móvil)* Paga Bs 16.703,33 (tasa BCV de hoy: 879,12). Banco de Venezuela (0102) · RIF de la empresa · teléfono del pago móvil.
> **Bianki:** Cuando pagues, mándanos el número de referencia o una foto del comprobante.
> **Cliente:** Ref. 00987654
> **Bianki:** ¡Gracias! Te confirmamos cuando llegue el pago y ahí tu pedido pasa a cocina.
> *(La cajera busca la referencia en el banco y responde desde Qualify:)* **Bianki:** Pago recibido. Tu pedido ya está en preparación.

En esta primera versión no hay «número del día» ni enlace de seguimiento, porque el pedido todavía no existe en Pedidos: la cajera lo carga en `/puesto` como hoy. El número y el enlace «Ver mi pedido» llegan con la creación automática (historias 5 y 6). El monto en bolívares necesita la tasa del día: en la versión 1 sale de la carta pública de Pedidos (§3.1). Si un negocio no tiene esa fuente, el mensaje dice «te confirmamos el monto en bolívares».

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
| **Si Pedidos está caído** | n/a | Bandeja de salida con reintentos (como `whatsapp_outbox`); al tercer fallo vuelve al traspaso manual y avisa al dueño. Sin conciliación: la caja trabaja siempre contra el servidor (D1) | Igual, del lado del cliente | El cliente ve error en la web | Igual que A |
| **Qué deja al segundo cliente** | Todo manual | Nada, salvo que tenga Pedidos | Sirve a cualquiera que programe un receptor (raro en una pyme) | Solo a quien tenga una web con carrito | El puerto; cada sistema nuevo es un adaptador |
| **Riesgo principal** | Se queda la queja | Acoplar Qualify a un contrato que cambia sin aviso (`api-web.md` lo protege para el landing, no para nosotros) | Ningún cliente pyme tiene dónde recibirlo | Contradice el valor: cerrar el pedido dentro del chat | Diseñar la abstracción con un solo caso real |

**Datos a tener en cuenta para A/D [V]:** todo Qualify llama desde la misma IP del VPS, así que el límite de 10 pedidos por IP y hora cortaría el día 11; hace falta una ruta de servicio con clave (`Authorization: Bearer`), no la pública. Pedidos tiene que aceptar `canal = "whatsapp"` (el enum ya lo tiene). Y Qualify tiene que mandar los UUID de la carta de Pedidos y los agregados obligatorios.

**Mapeo del catálogo:** la opción más barata es que Qualify **lea la carta de Pedidos** (`GET /carta`, público) y guarde el UUID externo en cada producto (`brand_products.external_ref`), en vez de mantener dos cartas a mano. Los agregados obligatorios piden un nodo nuevo en el menú («elige proteína»). Mientras no esté, los productos con `minimo > 0` quedan fuera del pedido por WhatsApp o pasan por la persona.

Costos [V/H]: llamar a Pedidos cuesta US$ 0 (mismo VPS). Los mensajes de servicio de WhatsApp dentro de las 24 horas no se cobran por mensaje [S, tarifario de Meta; se verifica con la factura]. Filas nuevas: ~1 por pedido de WhatsApp. Con 30 pedidos por día y negocio, ~11 mil al año: no cambia nada en Postgres.

---

## 3. El paso de pago, de punta a punta (Bianki)

Este es el recorrido completo, el de la **etapa 2** (el pedido nace en Pedidos). La etapa 1 (D4) es el mismo recorrido sin crear el pedido: el QR y las instrucciones salen de Qualify (§3.1) y la confirmación es manual (ver el ejemplo arriba).

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
- **Dónde viven las formas de pago y los QR:** en Qualify, por negocio (D3). Diseño en §3.1.
- **Quién confirma.** Asistido: la cajera, como hoy. Wompi y Binance siguen confirmando solos dentro de Pedidos, no en Qualify. Qualify **nunca** marca un pago como hecho; a lo sumo lleva la referencia que escribió el cliente.
- **Monedas y tasa.** El precio base es USD; el monto a cobrar y la tasa los calcula Pedidos al confirmar (BCV/TRM del día). Qualify muestra el `a_cobrar` que recibe y nunca convierte por su cuenta. Para un negocio sin sistema, el total sale en la moneda de su catálogo y la conversión queda fuera de alcance (se dice «te confirmamos el monto»).
- **Pagos parciales y mixtos.** Por WhatsApp se elige **una** forma. Lo mixto (parte en dólares, parte en pago móvil, vuelto en pesos) sigue en caja, donde ya funciona. Si el cliente paga de menos, la cajera lo ve al buscar la referencia y escribe por el chat.
- **Qué es de Bianki y qué es producto.** De Bianki: el adaptador de Pedidos, sus formas (pago móvil, Bre-B, Binance, Wompi), BCV/TRM, la regla de horario y de tasa del día. Producto: el nodo «elige cómo pagar», el mensaje con QR y enlace, la recepción de la referencia, «Datos de pago» por negocio y el puerto de conector.

### 3.1 Formas de pago en Qualify (D3)

- **Tabla `brand_payment_methods`** (migración nueva, `tenant_id` + `brand_id` + RLS con `NULLIF`): `name` («Pago móvil»), `currency` (`VES`/`USD`/`COP`/`USDT`), `instructions` (texto que lee el cliente, ≤ 1.024 caracteres, el límite del pie de una imagen), `qr_media_key` (imagen en R2 con clave del negocio, normalizada al subirla como las fotos del chat: JPEG/PNG ≤ 5 MB), `active`, `position`, `external_code` (el `codigo` de Pedidos, `null` si no hay sistema), `updated_at` y `updated_by`, y procedencia de la carga (`source` = `manual` | `pedidos_import`, más la huella del archivo importado). `unique (brand_id, name)` para que una importación repetida no duplique.
- **Una sola fuente, dos usos.** El nodo nuevo `payment_method` del menú automático y la opción del selector del chat leen la misma función (`list_payment_methods(brand_id)`: las activas, por `position`). El selector manda la misma tarjeta que el menú (imagen del QR con las instrucciones como pie), así lo que manda una persona y lo que manda el menú nunca difieren. El texto «Formas de pago» del menú de inicio (`PAYMENT_TEXT`) se arma con esa lista y deja de ser un hueco.
- **El selector del chat** suma «Formas de pago», y más adelante «Stickers» y «Videos cortos» (D5). El nombre «Foto o menú» deja de describirlo. Propuesta a validar por `ux-designer` y `qualify-copy-es`: **«Enviar»**, o **«Adjuntar»**.
- **Carga inicial de Bianki, una sola vez y confirmada por el dueño.** Un comando de importación lee la carta pública de Pedidos (`GET /api/web/bianki/carta`: `formas_pago[]` con `nombre`, `moneda`, `instrucciones` y `qr.imagen`) y baja cada QR desde su URL pública. Así no se copian archivos de otro repositorio a mano, y los datos que hoy están en el código de Pedidos (banco, RIF, teléfono) llegan tal como los ve el cliente en la web. El resultado queda como **borrador**: el dueño lo revisa en Ajustes → Formas de pago y lo activa forma por forma. Nada sale al cliente sin esa confirmación.
- **El riesgo de tener dos lugares.** Si Bianki cambia de banco o de llave Bre-B, hay que cambiarlo en Pedidos y en Qualify. Si no, el cliente paga a una cuenta vieja: es el peor error posible de este módulo. Cómo se mantiene honesto: (1) cada forma muestra «Actualizado el …» en Ajustes y en la vista previa del chat; (2) para un negocio con `external_code`, una comprobación diaria lee la carta pública y, si el nombre, las instrucciones o la huella del QR difieren, **pausa esa forma en el chat** y avisa al dueño («Tus datos de Pago móvil cambiaron en tu sistema de pedidos: revísalos») hasta que confirme; (3) más adelante, si el fundador lo prefiere, la lectura pasa a ser directa de Pedidos (Qualify como espejo de solo lectura) y la tabla queda solo para negocios sin sistema.
- **Tasa del día (versión 1).** Para mostrar el monto en bolívares o pesos, Qualify lee `tasas[]` de la misma carta pública (BCV y TRM, con fecha). Si la tasa no es de hoy, no calcula: dice «te confirmamos el monto en bolívares». Qualify nunca escribe ni inventa una tasa.
- **Confirmación (versión 1).** La referencia o la foto del comprobante entra al chat como cualquier mensaje y se marca «Pago por revisar». El dueño o la cajera confirman con un toque («Pago recibido», respuesta rápida aprobada). Qualify no marca nada como pagado por su cuenta.

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

### 4.1 Módulo de stickers y videos cortos de marca (D5) — bosquejo, sin decisión

Objetivo: piezas de 2 a 5 s con logo, colores y producto, regenerables por temporada (Navidad, aniversario), como dos opciones más del selector. Son piezas generadas, así que llevan doble aprobación como las demás y guardan procedencia (modelo, plantilla y versión). Ninguna cifra de abajo está medida: todas son **[H] sin verificar** hasta una prueba de `qualify-measure`.

| Vía | Cómo | Qué ya existe | Qué sería nuevo | Costo por pieza [H] |
|---|---|---|---|---|
| G1. Plantilla Remotion | Plantilla de marca (foto del producto + vapor/brillo animado + logo, variante por temporada) → MP4; para el sticker, cuadros → WebP animado | Servicio de render `packages/render` (precio `remotion_selfhost` = 0); Pillow escribe WebP animado | Una plantilla nueva; sacar una secuencia de cuadros (soporte en `CONTRACT.md` sin verificar) | ~US$ 0 de proveedor; solo CPU del VPS |
| G2. Seedance imagen → video | Foto del catálogo → clip de 5 s a 480p → recodificar a H.264 Main sin cuadros B ≤ 600 KB, y a WebP ≤ 500 KB | Proveedores en `packages/creative`; tabla de precios v7: Seedance 1.0 pro fast US$ 1,0 por millón de tokens, 2.0 mini US$ 3,5 | **Recodificar en producción:** PyAV (`qualify-creative[media]`, sus ruedas traen FFmpeg) no está en la imagen `app` de producción [V: `deploy/Dockerfile` no instala FFmpeg]. Instalar el binario `ffmpeg` o el extra `media` ahí es una dependencia nueva que **decide el fundador** | 1.0 pro fast: ~48 mil tokens → ~US$ 0,05; 2.0 mini ~US$ 0,17; más reintentos |
| G3. Seedream + animación simple | Imagen fija de temporada (Seedream 5.0 lite, US$ 0,035 [V, tabla v7]) → zoom suave y partículas con Pillow → WebP animado | Seedream, Pillow | Nada nuevo para el sticker; el MP4 igual necesita un codificador (ver G2) | ~US$ 0,035–0,07 |

Lectura rápida: G1 o G3 cubren el sticker sin un proveedor nuevo. Un MP4 de Seedance hay que recodificarlo de todos modos: su perfil H.264 no está verificado, y los clientes Android de WhatsApp no aceptan el perfil High con cuadros B [V, §4]. Eso pide la decisión sobre FFmpeg en producción. El envío necesita `sticker` en `client.py` (ver §4).

---

## 5. Recomendación (ajustada a D1–D5)

**Dos etapas sobre el mismo diseño.** **Etapa 1:** «elige cómo pagar» con las formas de pago guardadas en Qualify (§3.1) y confirmación manual. Para todo negocio es el adaptador `manual`. **Etapa 2:** el puerto `OrderSink` con el adaptador `pedidos_api` (opción A) para Bianki, que suma el número del día, el monto que calcula Pedidos y «Ver mi pedido». B y C quedan descartadas por ahora.

- **Por qué en ese orden.** La etapa 1 resuelve hoy la queja de «Formas de pago» para cualquier negocio, sin tocar el repositorio de Pedidos ni esperar su ruta de servicio. La etapa 2 elimina el doble tipeo en caja de Bianki. Detrás de un puerto cuesta ~2 días más y deja lugar al segundo sistema sin reescribir.
- **Criterios.** (1) Cero pedidos duplicados por reintentos. (2) El pago lo confirma una persona, o el proveedor de pagos dentro de Pedidos; nunca Qualify. (3) Si el servidor de Pedidos no responde, el pedido vuelve al traspaso manual sin perderse (D1). (4) Ningún dato de pago viejo llega a un cliente: la duplicación decidida en D3 se vigila con la comprobación diaria contra la carta (§3.1).
- **La reabrimos si:** antes del 2026-12-31 aparece un segundo negocio con un sistema propio que no sea Pedidos (entonces se diseña el adaptador `webhook` con ese caso real); si en el primer mes de la etapa 2 más del 10 % de los pedidos por WhatsApp de Bianki vuelven al traspaso manual por errores de la API; si la comprobación diaria encuentra datos de pago distintos más de una vez al mes (entonces Qualify pasa a leer directo de Pedidos para Bianki); o si se prioriza WA-23.
- **Lo que pide a Pedidos en la etapa 2 (otro repositorio, otro dueño):** una ruta de servicio autenticada que acepte `canal = whatsapp`, un `Idempotency-Key` con `unique`, sin límite por IP para esa clave, y `GET` del estado para avisar «listo». La etapa 1 solo **lee** la carta pública.

### Borrador de ADR (fila de §6)

| 47 | **[PROPUESTO — m-24955641, 2026-11-05; D1–D5 firmadas por el fundador el mismo día]** **Las formas de pago viven en Qualify por negocio (`brand_payment_methods`, RLS, QR en R2, procedencia de la carga). El menú de WhatsApp y el selector del chat las leen de una sola función. Los pedidos que cierra el menú salen por un puerto «conector de pedidos» (`OrderSink`): `manual` (traspaso a una persona; confirmación del pago por el dueño o la cajera) y, en una segunda etapa, `pedidos_api` (crea el pedido en el sistema del cliente por su API de servicio, con bandeja de salida idempotente, reintentos y vuelta al traspaso manual). Qualify muestra el pago y nunca lo confirma.** Credencial por `brand_id`, cifrada y leída solo por `credential_session`; procedencia `source_message_id` + versión del adaptador; comprobación diaria contra la carta del sistema externo que pausa una forma de pago desactualizada | (B) Webhook firmado `order.confirmed`; (C) enlace al checkout web con el carrito; (0) seguir manual; leer las formas de pago solo de Pedidos (sin copia) | (B) Ninguna pyme tiene dónde recibirlo. (C) Saca al cliente del chat. (0) Doble tipeo y «Formas de pago» inútil. Sin copia: el fundador la quiere también para negocios sin sistema y como opción del selector (D3) | Un segundo sistema de pedidos distinto de Pedidos; > 10 % de traspasos manuales por fallas de la API; más de una diferencia de datos de pago por mes; WA-23 priorizado |

### Historias propuestas (para el product owner), en el orden de D4

**Etapa 1: primero el pago, con confirmación manual**

1. **Formas de pago del negocio** — tabla `brand_payment_methods` (nombre, moneda, instrucciones, QR, activa, orden, «Actualizado el …») y su pantalla en Ajustes. *Acepta:* el dueño crea, ordena, activa y desactiva una forma con su QR desde el celular, y otro negocio no la ve. No depende de Pedidos.
2. **Carga inicial de Bianki desde su carta** — importación única desde `GET /api/web/bianki/carta` que deja borradores con QR; el dueño confirma cada una. *Acepta:* Pago móvil, Bre-B y Binance aparecen como borradores con su QR, y nada sale al chat hasta que el dueño las activa.
3. **Formas de pago en el selector del chat** — nueva opción del selector, que se renombra (propuesta «Enviar»). *Acepta:* desde un chat, dos toques mandan el QR con sus instrucciones, igual a lo que manda el menú.
4. **«Elige cómo pagar» en el menú automático** — nodo `payment_method` (lista) después del resumen y la dirección; manda el QR con instrucciones y el monto (tasa del día de la carta pública si es de hoy; si no, «te confirmamos el monto»); la respuesta del cliente queda «Pago por revisar». *Acepta:* el recorrido del ejemplo de arriba funciona de punta a punta y el pago solo se da por recibido cuando lo confirma una persona.
5. **Aviso de datos desactualizados** — comprobación diaria contra la carta de Pedidos para las formas con `external_code`. *Acepta:* si cambia la llave Bre-B en Pedidos, la forma se pausa en el chat y el dueño recibe el aviso.

**Etapa 2: el pedido nace en Pedidos**

6. **Carta de Pedidos y agregados en el menú** — `brand_products` guarda el UUID de Pedidos; nodo «elige tu proteína o aderezo» según `grupos.minimo`. *Acepta:* un bowl pedido por WhatsApp llega con sus agregados y Pedidos no responde 422.
7. **Ruta de servicio en Pedidos + conector `pedidos_api`** (dos repositorios) — `Bearer` por tienda, `canal=whatsapp`, `Idempotency-Key`; puerto `OrderSink`, bandeja de salida, reintentos, vuelta al traspaso; luego el mensaje `cta_url` con número del día y «Ver mi pedido», y la referencia del cliente a `…/referencia`. *Acepta:* el mismo POST repetido devuelve el mismo pedido; con Pedidos apagado el pedido vuelve al traspaso manual y el dueño lo ve.

**Aparte (D5, después de su decisión):** `sticker` en `client.py` y una prueba medida de las vías G1 y G3 (§4.1) con un producto de Bianki: tamaño final y tiempo de generación.

### Preguntas que quedan para el fundador

1. ¿Cómo se llama el botón del selector del chat? Propuesta: «Enviar». Lo revisa `ux-designer`.
2. Para el MP4 de marca (D5): ¿aceptas una dependencia de FFmpeg en la imagen de producción (vía G2), o empezamos solo con stickers por plantilla o por imagen fija (G1/G3, sin dependencia nueva)?
