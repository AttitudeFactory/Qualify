# Chats de WhatsApp: tu oferta, cómo llegar y piezas en video (m-24945889)

Especificación de experiencia (ux-designer, 2026-11-08). **Propuesta: no se revisó en la app corriendo.**
Base: `docs/ux-whatsapp-enviar-imagen.md` §2.4 (atajos) y `docs/ux-whatsapp-menu-orbit.md` (el «+»,
máximo 6 filas, regla de 16 caracteres, una opción vacía se muestra y abre su estado vacío). «Datos de
pago» ya salió como «Formas de pago» (`docs/ux-paso-de-pago.md`). Sin componentes nuevos: `orbit_menu`,
`drawer`, `choice_card`, `media_thumb`, `chat_bubble`, `callout`, `tone_badge`, `empty_state`.

## 1. El «+» con ocho cosas en seis filas

Hoy hay 5 filas; llegan 2 atajos y luego «Stickers y videos». Ni fichas sobre el cuadro de respuesta
(vuelven a llenar lo que el Orbit despejó, y a 375 px tapan el chat) ni una fila «Atajos» (escondería
justo lo que se usa a diario y obliga a recordar qué hay adentro). **Decisión: «Tus piezas» y «Foto
del celular» se juntan en «Fotos y videos»**, que abre un primer paso «¿De dónde?». Ahí entran también
los stickers y videos de marca cuando existan, así el «+» queda en 6 filas para siempre.

| # | Icono | Texto (≤ 16) | Abre | Pasos |
|---|---|---|---|---|
| 1 | `package` | Tus productos | «¿Cuál producto?» | 2 |
| 2 | `tag` | Tu oferta | «Revisa y envía» con la pieza marcada | 1 |
| 3 | `list` | Tu menú | «Así le llega tu menú» | 1 |
| 4 | `wallet` | Formas de pago | «¿Cuál forma de pago?» | 2 (1 con una sola) |
| 5 | `map-pin` | Cómo llegar | «Así le llega tu ubicación» | 1 |
| 6 | `images` | Fotos y videos | «¿De dónde?»: Tus piezas · De tu celular (· Stickers y videos, después) | 3 |

- Orden: lo que vende primero (producto, oferta, menú), luego cobrar y llegar, al final lo suelto.
  Hipótesis (perfil §5 pregunta 6): se revisa con lo que Bianki más mande.
- «¿De dónde?» son `choice_card` con una línea: «Tus piezas — Lo que preparaste para tus redes.» ·
  «De tu celular — Una foto que ya tengas guardada.» Un toque más para piezas y fotos (hipótesis: se
  usan menos que productos, menú y pagos; si no, se revisa).
- **Nombre: «Tu oferta», no «Promoción de la semana»**: no cabe en 16 caracteres, choca con
  «Promociones» (pestaña de mensajes aprobados) y con «Promocionar» (anuncios pagados), y «de la
  semana» mentiría: no vence sola. (Pregunta 1 al fundador.)
- **Sin nada que mandar, la fila se muestra** y abre su estado vacío (regla del Orbit §3):
  - Tu oferta: «Aún no marcas tu oferta» · «Elige una pieza aprobada en Por aprobar o en tu
    Planificador y toca «Usar como tu oferta».» [Ir a Por aprobar].
  - Cómo llegar sin dirección: «Aún no tienes la dirección de tu local» · «Escríbela una vez en Tu
    número › Perfil y la mandas con un toque.» [Completar mi dirección] (vuelve con «‹ Volver al chat»).

```
375 px, «+» abierto                     Tu oferta (1 paso)
┌─────────────────────────────────┐     ┌─────────────────────────────────┐
│ ┌ ¿qué tienen hoy? ┐            │     │ ‹ Volver al chat                │
│ (▣) Tus productos              │     │ Revisa y envía                  │
│ (⌂) Tu oferta                  │     │ [Tu oferta] marcada hace 3 días │
│ (☰) Tu menú                    │     │            ┌──────────────────┐ │
│ (▣) Formas de pago             │     │            │ [ foto 2x1 ]     │ │
│ (◎) Cómo llegar                │     │            │ 2x1 en shawarma  │ │
│ (▤) Fotos y videos             │     │            │ los martes...    │ │
│ (×) ( Texto | Botones )        │     │            └──────────────────┘ │
│ ┌─────────────────────────────┐ │     │ Texto que acompaña la foto     │
│ │ Escribe una respuesta…      │ │     │ [2x1 en shawarma los martes…]  │
│ └─────────────────────────────┘ │     │ Nada sale sin que toques       │
│                       [Enviar]  │     │ «Enviar».            [Enviar]  │
└─────────────────────────────────┘     └─────────────────────────────────┘
```

## 2. Tu oferta

- **Dónde se marca:** en la pieza, en Por aprobar (`/drafts/<id>`) y en el panel del Planificador,
  como acción secundaria **«Usar como tu oferta»** (icono `tag`). Solo en piezas **aprobadas** o
  publicadas: lo que sale como oferta ya pasó la doble aprobación. Una sin aprobar muestra la acción
  deshabilitada con «Apruébala primero para usarla como tu oferta.»
- **Una por negocio.** Marcar otra no pregunta nada, pero lo dice: aviso 6 s «Listo: «2x1 martes» es
  tu oferta. Antes era «Combo vecino».» [Deshacer].
- La pieza marcada lleva `tone_badge` **«Tu oferta»** en Por aprobar, Planificador y en «Fotos y
  videos». Para quitarla: «Dejar de usar como tu oferta» (aviso «Listo: ya no tienes oferta marcada.»).
- **Retención** (ADR 39), bajo la acción: «Mientras sea tu oferta, no se borra.»
- **En el chat** (paso único, «Revisa y envía»): `tone_badge` «Tu oferta» + «marcada hace 3 días»
  («marcada hoy», «marcada ayer»). No vence sola; con **más de 14 días**, `callout` warn: «La marcaste
  hace 20 días. ¿Sigue vigente?» + enlace «Cambiar tu oferta» (abre Por aprobar). No bloquea «Enviar».
- **Lo que recibe el cliente:** un solo mensaje: la foto (o el video, §4) con el texto de la pieza como
  pie, sin `#`, cortado en la última frase completa que entre en 1024 (mismas reglas de «Tus piezas»:
  «Acortamos el texto para que quepa en WhatsApp.»). El texto se puede cambiar antes de enviar.

## 3. Cómo llegar

- **Dónde se pone el punto:** Tu número › Perfil, bajo «Dirección», bloque **«Tu local en el mapa»**,
  con ayuda «Así tu cliente abre la ruta con un toque.» y dos caminos, sin escribir números:
  1. **[Usar mi ubicación]** (el navegador la pide; sirve estando en el local). Si sale aproximada
     (más de 100 m): «La ubicación salió aproximada (a unos 300 m). Mejor pega el enlace de Google
     Maps.» Si el navegador no la da: «Tu navegador no nos dejó ver la ubicación. Pega el enlace de
     Google Maps.»
  2. Campo **«Enlace de Google Maps de tu local»** con ejemplo «Por ejemplo: https://maps.app.goo.gl/…».
     Ayuda: «En Google Maps, abre tu local, toca «Compartir» y copia el enlace.» El servidor sigue el
     enlace corto y saca el punto. Si no puede: «No pudimos leer ese enlace. Copia el de «Compartir» en
     Google Maps y pégalo otra vez.»
- Con punto: «Listo: tu local quedó en el mapa.» + enlace **«Ver en el mapa»** (abre Google Maps en ese
  punto, para que el dueño lo compruebe) + «Quitar del mapa». Sin mapa dibujado en la pantalla (sería
  un proveedor nuevo).
- **Lo que recibe el cliente:**
  - Con punto: el mensaje de ubicación de WhatsApp (el mapa con el pin), con el nombre del negocio y
    la dirección del perfil. Al tocarlo abre su app de mapas.
  - Sin punto pero con dirección: texto «Estamos en {dirección}. Así llegas:
    https://www.google.com/maps/search/?api=1&query={dirección}».
- **Vista previa en el chat** («Así le llega tu ubicación»): `chat_bubble` con icono `map-pin`, nombre
  y dirección (con punto) o el texto con el enlace (sin punto) y, en ese caso, `callout` info «Si
  pones tu local en el mapa, le llega el mapa con la ruta.» [Ponerlo en el mapa]. Botón «Enviar».

## 4. Piezas en video en «Fotos y videos › Tus piezas»

- **Tarjeta:** la primera imagen del video (`media_thumb`, `alt` = nombre de la pieza) con el icono
  `play` encima, la duración abajo a la derecha («0:15») y `tone_badge` **«Video»** (texto, no solo el
  icono). **Nada se reproduce solo** en la grilla.
- **Revisa y envía:** el video con controles, quieto hasta que el dueño toque reproducir, sin sonido
  hasta que lo active. El pie, igual que una foto.
- **Más de 16 MB:** la tarjeta se ve con `signal_pill` warn «Muy pesado»; al tocarla, el paso de
  revisión muestra `callout` warn «Este archivo es muy pesado para WhatsApp. Créalo de nuevo más
  corto.» + [Crear de nuevo] (abre Crear pieza con la misma idea) y «Enviar» deshabilitado.
- Un carrusel sigue mostrando su primera foto con «1 de 4 fotos».

## 5. Textos nuevos y pruebas

- **Orbit:** «Tu oferta», «Cómo llegar», «Fotos y videos»; salen «Tus piezas» y «Foto del celular»
  como filas (siguen como tarjetas del paso «¿De dónde?» con sus líneas). Título «¿De dónde?».
- **Tu oferta:** «Usar como tu oferta», «Dejar de usar como tu oferta», «Apruébala primero para usarla
  como tu oferta.», «Mientras sea tu oferta, no se borra.», «Tu oferta», «marcada hoy / ayer / hace
  N días», «La marcaste hace N días. ¿Sigue vigente?», «Cambiar tu oferta», los avisos de §2 y el
  estado vacío de §1.
- **Cómo llegar:** «Tu local en el mapa», «Así tu cliente abre la ruta con un toque.», «Usar mi
  ubicación», «Enlace de Google Maps de tu local», «Ver en el mapa», «Quitar del mapa», «Así le llega
  tu ubicación», «Estamos en {dirección}. Así llegas: …», los errores de §3 y el estado vacío de §1.
- **Video:** «Video», «Muy pesado», «Este archivo es muy pesado para WhatsApp. Créalo de nuevo más
  corto.», «Crear de nuevo».
- **Pruebas** (`Qualify/test_whatsapp_chats_picker.py`): la prueba del «+» espera, en este orden, Tus
  productos · Tu oferta · Tu menú · Formas de pago · Cómo llegar · Fotos y videos (6, el máximo de
  `orbit_menu`) y deja de esperar «Tus piezas»/«Foto del celular» como filas. `open_pick("pieces")` y
  `open_pick("photo")` pasan a `open_pick("media")` + `choose_media_source(...)`: Tus piezas y De tu
  celular tienen 3 pasos (¿De dónde? → elegir → revisar). Nuevas: Tu oferta y Cómo llegar abren en
  su único paso (sin «Paso 1 de 1»); sin oferta o sin dirección abren el estado vacío; una pieza de
  más de 16 MB deja «Enviar» deshabilitado; ninguna tarjeta de video tiene `autoplay`.

## 6. Preguntas para el fundador

1. ¿«Tu oferta» en vez de «Promoción de la semana»? (16 caracteres, choque con Promociones/Promocionar.)
2. ¿Juntar «Tus piezas» y «Foto del celular» en «Fotos y videos», a cambio de un toque más?
