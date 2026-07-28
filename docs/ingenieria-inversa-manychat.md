# Ingeniería inversa de ManyChat — qué robar para Qualify

**Pregunta que responde:** ManyChat es la plataforma de referencia en automatización de DMs y
comment→DM sobre Instagram/Messenger/WhatsApp/TikTok. ¿Qué features suyas son implementables en
Qualify, en qué fase caen, y cuáles son estructuralmente inalcanzables desde el plano de datos de
Qualify (medios ganados) por exigir propiedad de la cuenta (medios propios)?

**Método:** investigación de escritorio con web en vivo, 2026-07-23. Fechas de acceso indicadas por
fila. Autor: agente `gtm`. Sesión: `.claude/research-sessions/2026-07-23-manychat.md`.

**Tesis que este documento intenta *refutar*, no confirmar:** que las features de ManyChat son
"robables" por Qualify. Ver §5 (screen owned-vs-earned) y §6 (recomendación) — los hallazgos que
socavan el relato "podemos robar esto" están marcados explícitamente.

## Nota de calidad de fuentes

Mismo esquema que `docs/fase0-zernio-mercado.md`:

- **[P] Primaria** — documentación oficial de ManyChat o de la plataforma (Meta, TikTok), o página
  de precios del vendor. Única evidencia con la que se hacen afirmaciones fuertes.
- **[S] Secundaria interesada** — blog de un competidor, agencia o afiliado. Pista, nunca prueba.
- **[T] Terciaria neutral** — comparativas o reportes sin producto en juego.

---

## 1. Inventario de features (G1)

**Fuente base:** el help center de ManyChat está servido por Zendesk. La web pública
(`manychat.com`, `help.manychat.com/hc/es`) devuelve **HTTP 403 a clientes no-navegador**
(Cloudflare), pero la **API pública de Zendesk Help Center responde 200 sin autenticación**:
`https://help.manychat.com/api/v2/help_center/es/{categories,sections,articles}.json`.
El inventario de abajo se extrajo de ahí el **2026-07-23**: **6 categorías, 21 secciones,
193 artículos** en el locale `es`. Todas las URLs de la columna "Artículo" son `html_url`
devueltas por esa API. Fecha de acceso de toda la §1: **2026-07-23** [P].

Estructura de primer nivel (categorías) [P]:

| Categoría | Descripción oficial | Secciones |
|---|---|---|
| Básicos | "Aprende lo fundamental para iniciar" | Comenzando |
| Automatizaciones | "acciones, condiciones, disparadores, IA, y más" | Constructor de Manychat · Automatización · Manychat IA · Plantillas |
| Canales | "Instagram, WhatsApp, TikTok, y otros canales de mensajería" | Instagram · WhatsApp · TikTok · Facebook Messenger · Telegram · SMS · Email |
| Herramientas de desarrollador e integraciones | — | Integraciones · Herramientas para desarrolladores |
| Pagos y Administración | — | Planes y Precios · Facturación · Config. de Cuenta · Gestión de Contactos · Bandeja de Entrada · Privacidad y Cumplimiento |
| Solución a problemas | — | Solución de Problemas |

### 1.1 Canales

| Feature | Qué hace | Restricción documentada | Artículo (acceso 2026-07-23) |
|---|---|---|---|
| Instagram | DM automation sobre cuenta Business/Creator vinculada | Requiere vinculación OAuth de la cuenta del cliente | [Cómo vincular Instagram a Manychat](https://help.manychat.com/hc/es/articles/14281290924444) |
| Facebook Messenger | Igual sobre Página de FB | Requiere acceso a la Página Business | [Cómo vincular Facebook](https://help.manychat.com/hc/es/articles/14281086119068) |
| WhatsApp | Cloud API; plantillas, difusión, línea de crédito | No disponible en planes Free/Essential; plantillas aprobadas; límites de mensajería escalonados | [Cómo vincular WhatsApp: elijamos el mejor método](https://help.manychat.com/hc/es/sections/13556952605852-WhatsApp) |
| **TikTok** | DM automation, QR y referral URL | **Cuenta *Business* obligatoria** (personal/creator no soportadas); **geobloqueo: EE.UU. y Reino Unido no pueden vincular**; UK/UE en lista de espera; **1 sola cuenta TikTok por cuenta ManyChat** | [Cómo conectar TikTok a Manychat](https://help.manychat.com/hc/es/articles/17928990909084) |
| Telegram | Sin ventana de mensajería (envío libre) | — | [Cómo vincular tu cuenta de Telegram](https://help.manychat.com/hc/es/sections/13556776930588) |
| SMS | Envío SMS/MMS, cumplimiento TCPA | Solo Pro+ | [Cómo enviar SMS/MMS](https://help.manychat.com/hc/es/sections/15014939675292-SMS) |
| Email | Envío desde dominio propio, tracking de aperturas, rebotes | Solo Pro+ | [Canal de correo electrónico](https://help.manychat.com/hc/es/sections/13556925449500) |

### 1.2 Disparadores (triggers) — el corazón del producto

Ordenados por relevancia para Qualify. **O = medio propio, E = medio ganado** (ver §5).

| Disparador | Evento que lo activa | O/E | Canal | Artículo |
|---|---|---|---|---|
| **Comentarios en publicaciones y reels** (comment→DM) | Alguien comenta en **tu** post/reel → se le envía un DM | **O** | IG | [Disparador de comentarios de publicaciones y reels de IG](https://help.manychat.com/hc/es/articles/14281316989724) |
| Respuestas a comentarios de Facebook | Comentario en **tu** post de Página | **O** | FB | [Disparador de respuestas a comentarios de FB](https://help.manychat.com/hc/es/articles/14281386567836) |
| **Comentarios de Instagram Live** | Comentario durante **tu** directo | **O** | IG | [Disparador de comentarios de IG Live](https://help.manychat.com/hc/es/articles/14281275933724) |
| Respuestas a historias | Alguien responde a **tu** historia | **O** | IG | [Disparador de respuestas a historias de IG](https://help.manychat.com/hc/es/articles/13556930006428) |
| **Respuestas a menciones en historias** | Alguien **te menciona en SU historia** → disparo automático | **E** (parcial) | IG | [Disparador de respuestas a menciones en historias](https://help.manychat.com/hc/es/articles/14281309502108) |
| **"Comparte a mensaje directo"** | Alguien comparte **tu** contenido por DM | **O** | IG | [Disparador Comparte a mensaje directo](https://help.manychat.com/hc/es/articles/23431135317916) |
| **Follow to DM [BETA]** | Alguien empieza a seguirte → DM de bienvenida | **O** | IG | [Follow to DM en Instagram BETA](https://help.manychat.com/hc/es/articles/23096654243740) |
| Palabra clave | El texto del DM entrante contiene X | **O** | Todos | [Cómo usar el disparador de palabras clave](https://help.manychat.com/hc/es/articles/14281211785884) |
| **Reconocimiento de intención (IA)** | Clasificación semántica del DM entrante en vez de keyword | **O** | IG/Messenger/WA/Telegram | [Reconocimiento de intenciones con la IA](https://help.manychat.com/hc/es/articles/14281187229468) |
| Disparador de anuncios (CTM) | Click-to-Message desde un anuncio de IG/FB/WA | **O** (pagado) | IG/FB/WA | [Disparador de anuncios de Instagram](https://help.manychat.com/hc/es/articles/14281321942428) |
| URL de referencia | Link con parámetro que abre el chat en un flujo concreto | **O** | IG/FB/WA/TikTok | [Disparador de URL de referencia de TikTok](https://help.manychat.com/hc/es/articles/21033455635996) |
| Código QR | QR físico → chat | **O** | Messenger/TikTok | [Disparador de código QR de TikTok](https://help.manychat.com/hc/es/articles/21034828104092) |
| Mensajes de la tienda de Facebook | Consulta desde FB Shop | **O** | FB | [Disparador de mensajes de la tienda de FB](https://help.manychat.com/hc/es/sections/15275480358812) |
| Mensaje de bienvenida / Texto de bienvenida / Respuesta predeterminada / Menú principal / Iniciadores de conversación | Superficies de entrada al chat | **O** | IG/FB | [Automatización](https://help.manychat.com/hc/es/sections/13556895745820) |

### 1.3 Flow builder (Constructor)

| Feature | Qué es | Artículo |
|---|---|---|
| Tipos de bloques de contenido | Texto, tarjeta, galería, media, lista | [Tipos de bloques de contenido](https://help.manychat.com/hc/es/articles/14281196200604) |
| Botones / Respuestas rápidas | CTAs que ramifican el flujo | [Botones](https://help.manychat.com/hc/es/sections/13556921826844) |
| **Bloque de condición** | Ramificación por tag/campo/canal | [Bloque de condición](https://help.manychat.com/hc/es/sections/13556921826844) |
| **Acciones** | Set tag, set field, suscribir a secuencia, notificar admin, etc. | [Acciones](https://help.manychat.com/hc/es/sections/13556921826844) |
| **Bloque de recopilación de datos** | Captura email/teléfono/respuesta libre con validación | [Bloque de recopilación de datos](https://help.manychat.com/hc/es/sections/13556921826844) |
| **Campos personalizados de usuario y de bot** (incl. tipo *matriz*) + campos del sistema + variables | Modelo de datos por contacto, editable desde el flujo | [Campos de usuario personalizados](https://help.manychat.com/hc/es/sections/13556921826844) |
| Retraso inteligente / Aleatorización | Humaniza el envío; A/B split | [Retraso inteligente](https://help.manychat.com/hc/es/sections/13556921826844) |
| **Secuencias** | Drip multi-paso con tiempos | [Configurar las secuencias de Manychat](https://help.manychat.com/hc/es/sections/13556895745820) |
| **Difusión (broadcast)** | Envío masivo a segmento | [Difusión en Manychat](https://help.manychat.com/hc/es/sections/13556895745820) |
| **Convertidor de automatizaciones multicanal** | Convierte un flujo de un canal a otro | [Convertidor de automatizaciones](https://help.manychat.com/hc/es/sections/13556895745820) |
| Previsualización en el canal real | Preview del flujo dentro de Instagram | [Cómo previsualizar automatizaciones](https://help.manychat.com/hc/es/sections/13556895745820) |
| **Plantillas** (incl. protegidas) | Flujos empaquetados, instalables y revendibles | [Plantillas](https://help.manychat.com/hc/es/sections/13556927689116) |
| Automatizaciones rápidas | Recetas de 1 clic (comentarios→seguidores, comentarios→link, historias→leads) | [Automatizaciones rápidas](https://help.manychat.com/hc/es/sections/13556895745820) |

### 1.4 IA (Manychat AI)

| Feature | Capacidad real que exige | Artículo |
|---|---|---|
| **Paso de IA (AI Step)** | Bloque conversacional libre con instrucciones; LLM en el flujo | [Paso de IA en Manychat](https://help.manychat.com/hc/es/articles/14281187288860) |
| **Reconocimiento de intenciones** | Clasificación de intención en lenguaje natural (sustituye keywords). Prompt en formato `USUARIO + verbo + SOBRE + ARTÍCULO` | [Reconocimiento de intenciones](https://help.manychat.com/hc/es/articles/14281187229468) |
| **AI Replies** | Respuesta generada automática a DMs | [Respuestas con IA (AI Replies)](https://help.manychat.com/hc/es/articles/23018283889180) |
| **AI Comments** | Respuesta generada al **comentario público** | [Comentarios con IA (AI Comments)](https://help.manychat.com/hc/es/articles/23096278263836) |
| **AI Goals** | Objetivo declarativo; la IA conduce la conversación hacia él | [Objetivos con IA (AI Goals)](https://help.manychat.com/hc/es/articles/23096273858716) |
| **AI Knowledge** | Base de conocimiento de marca que alimenta las respuestas (RAG) | [Conocimiento con IA](https://help.manychat.com/hc/es/articles/25626595060124) |
| Asistente del creador de flujos | Genera el flujo a partir de descripción en lenguaje natural | [Asistente del creador de flujos de IA](https://help.manychat.com/hc/es/sections/14281203243164) |
| Optimizador de texto | Reescribe copy del mensaje | [Optimizador de texto con IA](https://help.manychat.com/hc/es/sections/14281203243164) |
| Comportamiento de la IA | Tono/guardarraíles globales del agente | [Comportamiento de la IA](https://help.manychat.com/hc/es/sections/14281203243164) |

### 1.5 Inbox / Live Chat

| Feature | Qué hace | Artículo |
|---|---|---|
| Manychat Inbox | Bandeja unificada multicanal | [Descripción general de Manychat Inbox](https://help.manychat.com/hc/es/sections/14281113710620) |
| **Asignación automática de conversaciones** | Routing por reglas a agentes (por canal: IG, Messenger) | [Asignación automática de conversaciones](https://help.manychat.com/hc/es/sections/14281113710620) |
| Grupos de miembros del equipo | Equipos y colas | [Grupos de miembros del equipo](https://help.manychat.com/hc/es/sections/14281113710620) |
| Analytics de Live Chat | Métricas de atención | [Analytics de Live Chat](https://help.manychat.com/hc/es/sections/14281113710620) |
| **Vender productos vía Live Chat** + botón de compra + Stripe/PayPal | Checkout dentro del DM | [Vender productos a través de Live Chat](https://help.manychat.com/hc/es/sections/13556895745820) · [Cómo usar el botón para comprar](https://help.manychat.com/hc/es/sections/13556924443292) |

### 1.6 Contactos, segmentación y crecimiento

| Feature | Qué hace | Artículo |
|---|---|---|
| Contactos (tags, campos, segmentos) | CRM ligero por contacto | [Pestaña Contacts: descripción general](https://help.manychat.com/hc/es/sections/13556891922332) |
| Fusión de contactos duplicados / **fusión Telegram+Instagram** | Identidad unificada cross-canal | [Cómo fusionar contactos duplicados](https://help.manychat.com/hc/es/sections/13556939472924) |
| Import/export de contactos y PSID | Portabilidad | [Cómo exportar datos del contacto](https://help.manychat.com/hc/es/sections/13556939472924) |
| **Públicos personalizados de Instagram** | Exporta segmento a Meta Ads como Custom Audience | [Públicos personalizados de Instagram](https://help.manychat.com/hc/es/articles/21052925405084) |
| **Manychat Pixel** + **Integración CAPI** | Atribución de conversiones a Meta | [Manychat Pixel](https://help.manychat.com/hc/es/sections/13556924443292) · [Integración de la API de conversiones (CAPI)](https://help.manychat.com/hc/es/sections/13556926216988) |
| Listas de Messenger / Mensajes de marketing y de utilidad | Canales de re-engagement fuera de la ventana de 24 h | [Mensajes de marketing en Messenger](https://help.manychat.com/hc/es/sections/15275480358812) |

### 1.7 Integraciones y herramientas de desarrollador

| Integración | Tipo | Artículo |
|---|---|---|
| Zapier | Orquestación genérica | [Integración de Zapier](https://help.manychat.com/hc/es/sections/13556926216988) |
| Google Sheets | Sync de leads | [Integración de Google Sheets](https://help.manychat.com/hc/es/sections/13556926216988) |
| HubSpot CRM · ActiveCampaign · Klaviyo · MailChimp · Kit · Flodesk | CRM / email marketing | [Integraciones](https://help.manychat.com/hc/es/sections/13556926216988) |
| Hotmart | Infoproductos (mercado LATAM/BR) | [Integración de Hotmart](https://help.manychat.com/hc/es/sections/13556926216988) |
| **ChatGPT · Claude · DeepSeek** | LLM externo invocable desde el flujo (BYO-key) | [Integración de Claude](https://help.manychat.com/hc/es/sections/13556926216988) |
| **Solicitud externa (External Request)** | HTTP request arbitrario desde un flujo | [Herramientas de desarrollo: Solicitud externa](https://help.manychat.com/hc/es/sections/13556927928988) |
| **Bloque dinámico (Dynamic Block)** | Un endpoint propio devuelve el contenido del mensaje en runtime | [Herramientas de desarrollo: Bloque dinámico](https://help.manychat.com/hc/es/sections/13556927928988) |
| **API de Manychat + token** | API pública (solo Pro+) | [Cómo generar un token para la API de Manychat](https://help.manychat.com/hc/es/sections/13556927928988) |
| **Programa de apps de terceros + revisión de apps** | Marketplace: terceros publican apps sobre ManyChat, con proceso de review propio | [Proceso de revisión de aplicaciones](https://help.manychat.com/hc/es/sections/13556927928988) |

**Lectura de G1 (lo que el inventario revela sobre la forma del producto):**

1. **No hay ni una sola feature de descubrimiento.** 193 artículos y **cero** sobre buscar
   creadores, monitorizar competidores, o encontrar conversaciones ajenas. ManyChat no busca a
   nadie: **espera** a que alguien toque su superficie (comentario, DM, follow, mención, anuncio).
   Es un producto **reactivo por diseño**, y esa es la diferencia estructural con Qualify, no una
   laguna de su documentación.
2. **El activo real es el `contacto`**, no el flujo. Todo el pricing (§3), la deduplicación, los
   campos personalizados y la exportación a Custom Audiences giran alrededor de convertir una
   interacción efímera en un registro persistente y direccionable. El flow builder es el
   mecanismo de captura; el contacto es el producto.
3. **Dos primitivas de extensión sí son "robables" tal cual y no dependen del canal**: *External
   Request* y *Dynamic Block*. Cualquier integración Qualify↔ManyChat pasa por ahí (ver §6).
4. **Un único disparador del catálogo es medio ganado**: respuesta a menciones en historias de
   Instagram. Uno de ~14. Ese ratio es el resumen honesto de la §5.

## 2. Matriz de gating por API de plataforma (G2)

Esta es la sección que decide si algo de ManyChat es replicable. La pregunta del brief era:
**¿la existencia de ManyChat demuestra que las puertas descritas en `docs/fase0-zernio-mercado.md`
§1 son franqueables, y a qué coste?** Respuesta corta: **sí son franqueables, y ManyChat es la
prueba viviente — pero el precio de franquearlas es "ser ManyChat", no "hacer un sprint".**
Y en la plataforma que más le importa a Qualify (TikTok), **ni siquiera ManyChat las ha
franqueado del todo**.

### 2.1 Matriz feature → API → requisito

| Feature de ManyChat | API oficial que la sostiene | Permiso/scope | Gate para **quien construye la plataforma** | Gate para **el cliente final** | Fuente |
|---|---|---|---|---|---|
| DM automation IG | Instagram Messaging (Graph / Instagram Login) | `instagram_business_manage_messages` | App Review + Advanced Access (→ Business Verification) | Cuenta **Business/Creator** + OAuth | [P] [Meta: Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login) (2026-07-23) |
| **Comment→DM IG** | Instagram Messaging + webhook `comments` | `instagram_business_manage_comments` | Igual | Igual | [P] ídem |
| Respuesta a menciones en historias IG | Webhook de menciones en Stories | Ámbito de mensajes/menciones IG | Igual | Igual + **la historia del tercero debe ser de perfil público** | [P] [ManyChat: Disparador de menciones en historias](https://help.manychat.com/hc/es/articles/14281309502108) (2026-07-23) |
| Follow to DM [BETA] | Evento de nuevo seguidor | — | Igual; **beta**, no GA | Igual | [P] [Follow to DM BETA](https://help.manychat.com/hc/es/articles/23096654243740) |
| DM automation Messenger | Messenger Platform | `pages_manage_metadata`, `pages_messaging` | App Review + Business Verification | Página FB + rol ≥ "Moderate" | [P] [Meta: Messenger/Instagram Get Started](https://developers.facebook.com/docs/messenger-platform/instagram/get-started) (2026-07-23) |
| WhatsApp (difusión, plantillas) | WhatsApp Business Platform (Cloud API) | `whatsapp_business_messaging`, `whatsapp_business_management` | **Registro como Meta Tech Provider** + App Review + Business Verification | Verificación del número + **plantillas aprobadas una a una** + límites escalonados | [P] [Meta: Become a Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers) (2026-07-23) |
| **DM automation TikTok** | **TikTok Business Messaging API** | — | **Partner autorizado por TikTok** (programa cerrado; no self-serve) | **Cuenta TikTok *Business* obligatoria** (personal/creator NO) + **geobloqueo** | [P] [ManyChat: Cómo conectar TikTok](https://help.manychat.com/hc/es/articles/17928990909084) · [P] [TikTok: About Messaging Partners](https://ads.tiktok.com/help/article/about-message-management-tools) (2026-07-23) |
| **Comment→DM TikTok** | — | — | **NO EXISTE en ManyChat.** Figura en "Coming next" | n/a | [P] [Use cases and strategies for TikTok automations](https://help.manychat.com/hc/en-us/articles/17961702404892) (2026-07-23) |
| Públicos personalizados IG / CAPI | Marketing API + Conversions API | — | Acceso a Marketing API | Business Manager del cliente | [P] [ManyChat: Públicos personalizados de IG](https://help.manychat.com/hc/es/articles/21052925405084) |
| Telegram / SMS / Email | Bot API / operadores SMS / SMTP propio | — | Ninguno relevante | Ninguno | [P] help center |

### 2.2 El hallazgo central: el gate es de **dos pisos**, y solo el piso de abajo se paga una vez

ManyChat es **Meta Business Partner** y lo declara explícitamente:

> "Manychat está aprobado por Meta […] nuestra asociación con Meta significa que trabajamos
> directamente con las API oficiales de Instagram […] Como Meta Business Partner oficiales, nos
> reunimos con su equipo de productos semanalmente."
> — [P] [¿Manychat está oficialmente aprobado por Meta?](https://help.manychat.com/hc/es/articles/18624810395932) (acceso 2026-07-23)

Estructuralmente esto es **idéntico al hallazgo de `fase0-zernio-mercado.md` §2.4** ("el agregador
no vende código, vende su aprobación de plataforma"), confirmado ahora en un segundo dominio
(mensajería en vez de publicación):

| Piso | Quién lo paga | Coste |
|---|---|---|
| **Piso 1 — App Review + Business Verification + partner status** | **ManyChat, una vez** | Entidad legal verificada, App Review por permiso, reuniones semanales con Meta, estatus de partner en TikTok. Coste de *empresa*, no de proyecto |
| **Piso 2 — OAuth de la cuenta** | El cliente final, en 3 clics | Cero. Solo tener cuenta Business/Creator |

**Lectura para Qualify, y es la más importante del documento:** cualquier feature de activación
que Qualify quisiera construir *nativamente* sobre IG/Messenger/WhatsApp/TikTok tiene que pagar
el **piso 1 entero**. El calendario estimado en `fase0-zernio-mercado.md` §1.2 (**2–4 meses,
rechazable, revocable, con constitución de entidad legal previa ante Meta**) **aplica igual aquí**
— la conclusión de esa investigación no se debilita con ManyChat en la mesa: **se confirma con un
ejemplo de referencia**. La diferencia es que ahora sabemos que existe un **piso 2 comprable**:
integrarse *contra* ManyChat en vez de contra Meta.

**Corolario que hay que decir sin suavizar:** el argumento "ManyChat lo hace, luego se puede
hacer" es válido a nivel de posibilidad e **inválido a nivel de plan de trabajo**. ManyChat lleva
desde 2015 y declara **>100.000 cuentas de Instagram** [P, mismo artículo]. Su acceso no es una
aprobación técnica que se saca en un sprint: es una relación comercial sostenida. Y ni siquiera
esa relación le da control — el propio artículo admite: *"No podemos revertir suspensiones ni
restricciones de cuentas"*, *"No podemos anular el sistema de detección de spam"*.

### 2.3 El límite duro que ninguna arquitectura elude: la ventana de mensajería

[P] [Entender las ventanas de mensajería](https://help.manychat.com/hc/es/articles/23358636027932)
(acceso 2026-07-23), corroborado con la política de Meta:

| Plataforma | Ventana automatizada | Después | Fuera de plazo |
|---|---|---|---|
| IG / Messenger | **24 h** desde la última interacción del contacto | 7 días **solo mensajes manuales** vía Live Chat | Message tags / Listas de Messenger / mensajes de marketing (opt-in explícito) |
| WhatsApp | 24 h | — | Solo **plantillas aprobadas**, de pago por conversación |
| **TikTok** | **48 h y máximo 10 mensajes** sin respuesta del usuario | — | Solo si el usuario reinicia la conversación |
| Telegram | Sin límite | — | — |

Consecuencias sancionables documentadas por incumplir: advertencias en Business Suite,
restricción de envío, **despublicación de la Página de Facebook**, **desactivación de la cuenta de
Instagram** [P].

**Esto invalida, por sí solo, cualquier diseño de Qualify que imagine "detectar una señal de
listening y abrir un DM al creador".** El DM saliente en frío no existe como primitiva en estas
plataformas: **la ventana la abre el usuario, no la marca**. Ningún volumen de señal de medios
ganados abre esa ventana. Es el mismo tipo de imposibilidad estructural que la §4.2 de
`fase0-zernio-mercado.md`, y debe llegar al architect antes de que la ADR de superficie de
activación (A6) asuma lo contrario.

### 2.4 La ducha fría de TikTok — el hallazgo que más contradice la tesis "podemos robar esto"

TikTok es la plataforma central de la tesis multimodal de Qualify. Lo que ManyChat puede
realmente hacer ahí, a 2026-07-23, es mucho menos de lo que sugiere su marketing:

| Restricción TikTok en ManyChat | Fuente [P] |
|---|---|
| **Comment→DM NO existe.** Está listado en "Coming next", junto con "clickable links and buttons" | [Use cases and strategies for TikTok automations](https://help.manychat.com/hc/en-us/articles/17961702404892) |
| Solo **3 disparadores**: usuario envía mensaje · Ref URL · código QR | ídem |
| **Cuenta Business obligatoria**; personal y **creator NO soportadas** | [Cómo conectar TikTok](https://help.manychat.com/hc/es/articles/17928990909084) |
| **Geobloqueo**: EE. UU. y Reino Unido no pueden vincular; UK/UE en lista de espera | ídem |
| **1 sola cuenta de TikTok por cuenta de ManyChat** | ídem |
| **Los links no son clicables dentro del DM de TikTok** | [Set up your first TikTok automation](https://help.manychat.com/hc/en-us/articles/17508399106844) |
| Ventana: **10 mensajes / 48 h** | ídem |

Tres implicaciones que hay que subrayar:

1. **La feature estrella de ManyChat (comment→DM) es una feature de *Instagram*, no de la
   categoría.** Quien diga "automatización de comentarios en TikTok" en julio de 2026 está
   describiendo algo que el líder del mercado todavía no ha lanzado.
2. **"Cuenta Business obligatoria, creator no" excluye precisamente a la audiencia de Qualify.**
   El buyer de Qualify incluye creadores y podcasters (`docs/dolores-creadores-podcasters.md`);
   en TikTok esas cuentas **no pueden ni conectarse**.
3. **Contradicción de fuentes sobre la geografía, sin resolver.** ManyChat [P] dice que EE. UU. y
   Reino Unido están bloqueados; fuentes [S] sobre la Business Messaging API afirman lo contrario
   (acceso "limitado a EEA y UK"). Y la lista oficial de *Messaging Partners* de TikTok
   ([P] [About Messaging Partners](https://ads.tiktok.com/help/article/about-message-management-tools),
   acceso 2026-07-23) nombra a Blip.ai, Halosis, Haravan, Pancake, Qiscus, respond.io, Zwiz,
   Gupshup e Infobip — **ManyChat no aparece en ella**, lo que sugiere varios programas de partner
   distintos y solapados. **Doy esto por no resuelto**: cualquier decisión que dependa de la
   disponibilidad geográfica de TikTok DM requiere verificación directa con TikTok, no desktop
   research.

### 2.5 Respuesta explícita a la pregunta del brief

> ¿La existencia de ManyChat prueba que esas puertas son franqueables, y a qué coste?

| Puerta (de `fase0-zernio-mercado.md`) | ¿ManyChat la prueba franqueable? | Coste demostrado |
|---|---|---|
| Meta exige constitución/verificación de entidad legal | **Sí, franqueable** | Ser una empresa constituida y verificada. **No se elude**; se paga antes de empezar el reloj |
| App Review de Meta 2–4 semanas por envío, rechazable | **Sí** | Se paga una vez por permiso, y se mantiene (relación semanal con Meta) |
| TikTok gatea la visibilidad vía `SELF_ONLY` en publicación | **No aplica aquí** — la Business Messaging API es otro programa | Pero aparece un gate **equivalente en severidad**: partner cerrado + geobloqueo + solo cuentas Business |
| Escalabilidad a clientes terceros sin su propio review | **Sí — y este es el hallazgo útil** | El cliente final no paga nada. Quien integra *contra ManyChat* hereda ese piso 2 |

**Veredicto de G2:** el gating **no invalida** las features de ManyChat como fuente de
inspiración, pero **sí invalida construirlas nativamente en Qualify** dentro de cualquier
horizonte de Fase 5. Si Qualify quiere superficie de activación conversacional, la ruta racional
es **integrarse con ManyChat (o un par suyo) vía su API / External Request / Dynamic Block**, no
reimplementarla — que es exactamente la regla "buy commodity infra" de `CLAUDE.md`, aplicada a un
commodity nuevo: **el acceso aprobado a las APIs de mensajería**.

## 3. Pricing y packaging (G3)

**Nota de acceso:** `https://manychat.com/pricing` devuelve **403** a clientes no-navegador
(2026-07-23), así que **no cito la página de precios**. Todas las cifras de abajo salen de los
artículos oficiales del help center "Planes y Precios de Manychat" [P], vía la API de Zendesk,
accedidos **2026-07-23**. Los propios artículos advierten que **la disponibilidad de plan varía
por región**, así que estas cifras son la lista USD publicada, no necesariamente lo que ve un
comprador español.

**Hecho de encuadre:** ManyChat **rehizo su pricing el 2026-03-02** y el nuevo modelo
(facturación por *contacto activo*) **solo aplica a cuentas creadas a partir de esa fecha** —
las anteriores siguen en el modelo viejo y la migración está pendiente [P,
[Contactos activos](https://help.manychat.com/hc/es/articles/25800323349020)]. Es decir: el
vendor de referencia de la categoría acaba de cambiar su unidad de valor hace 5 meses, y ni él
mismo ha terminado de migrar su base. Dato relevante para Fase 5.

### 3.1 Tabla de planes (modelo nuevo, desde 2026-03-02) [P]

| Plan | Precio mensual | Precio anual | Contactos activos incluidos | **Excedente / contacto extra** | Canales | Usuarios | Asientos Inbox |
|---|---|---|---|---|---|---|---|
| **Free** | $0 | — | 25 | n/a (sin excedente) | 2, solo de {IG, TikTok, Messenger, Telegram} | 1 | 1 |
| **Essential** | $17 | $14/mes | 250 | **$0,10** (mensual) / $0,08 (anual) | 2, mismos 4 (sin WhatsApp/SMS/email) | 2 | 1 |
| **Pro** | $39 | $29/mes | 2.500 | **$0,05** / $0,038 | 3, ya con WhatsApp/SMS/email | 3 | 2 (hasta 3; extra $25) |
| **Business** | $99 | $69/mes | 7.500 | **$0,025** / $0,018 | Ilimitados | 5 | 3 (hasta 5; extra $25) |
| **Advanced** | $199 | $139/mes | 25.000 | **$0,004** / $0,0028 (y baja con uso) | Ilimitados | 10 | 5 (hasta 10; extra $25) |

Fuentes por fila [P, acceso 2026-07-23]:
[Free](https://help.manychat.com/hc/es/articles/25800197498652) ·
[Essential](https://help.manychat.com/hc/es/articles/25800276116508) ·
[Pro](https://help.manychat.com/hc/es/articles/25800228332572) ·
[Business](https://help.manychat.com/hc/es/articles/25800254159900) ·
[Advanced](https://help.manychat.com/hc/es/articles/25800308984988) ·
[Contactos activos](https://help.manychat.com/hc/es/articles/25800323349020).

Prueba gratuita de 14 días en Essential y Pro; **no hay trial en Business ni Advanced** [P].
El plan Free estampa marca "Patrocinado por Manychat" en el primer mensaje a cada contacto [P].

### 3.2 Qué es exactamente un "contacto activo" — la parte que hay que copiar

Definición literal [P, [Contactos activos](https://help.manychat.com/hc/es/articles/25800323349020)]:

- Un **contacto** es una persona que interactuó con la cuenta del cliente por un canal conectado
  (DM, comentario, respuesta a historia, o vía import/API).
- Un **contacto activo** es un contacto que interactuó **durante el ciclo de facturación en curso**.
  Se **reinicia cada mes**, incluso en plan anual.
- **Varias interacciones de la misma persona en el mismo mes = 1 contacto activo.**
- Los contactos que no interactúan **siguen almacenados y no cuentan**.
- Alcanzar el límite **no rompe el producto**: se cobra excedente automáticamente. Avisos al
  **70 %, 90 % y 100 %**. Solo "muy por encima" del tope el sistema puede llegar a detenerse.
- Ambigüedad admitida por el propio vendor: la misma persona en IG y TikTok **puede contar dos
  veces**, salvo que comparta teléfono/email y ManyChat la deduplique.

Cinco propiedades de diseño, y son exactamente las cinco que P5-1 pide:

| Propiedad de ManyChat | Qué resuelve | Correspondencia con P5-1 (`docs/backlog-features-gtm.md`) |
|---|---|---|
| Se cobra por **persona que interactuó**, no por mensaje enviado ni por intento | El cliente no paga por automatizaciones que no tocaron a nadie | "cobrar por dato válido, no por intento" (anti-patrón Clay) — **encaje directo** |
| **Deduplicación dentro del ciclo** | Un contacto ruidoso no multiplica la factura | Predecibilidad del gasto |
| **Reinicio mensual + contactos inactivos gratis** | Desacopla *tamaño de base* de *coste* → el cliente puede acumular audiencia sin penalización | Nada equivalente en P5-1 hoy. **Es la mejor idea de todo el pricing** |
| **Excedente automático con tarifa publicada y decreciente** ($0,10 → $0,004) | Nunca hay corte sorpresa; el precio marginal cae 25× de Essential a Advanced | P5-1 pide "consumo estimado y visible antes del commit" — ManyChat resuelve el mismo miedo por otra vía (degradar suavemente) |
| **Avisos al 70/90/100 %** | Elimina el "credit burn" invisible | Encaje directo con la queja #1 de Clay citada en P5-1 |

**Implicación para Fase 5 (P5-1) — la traducción no es literal y ahí está el problema.**
La unidad de ManyChat es *una persona que me habló*: es **observable por el cliente**,
**contable sin ambigüedad** y **causada por el cliente** (publicó un reel, la gente comentó).
La unidad natural de Qualify es *un dato enriquecido entregado* (un creador identificado, un
email verificado, una señal detectada) — que el cliente **no puede verificar por sí mismo**
y que **Qualify causa**, no el cliente. Ese cambio de agencia es la razón por la que Clay quema
créditos y ManyChat no. Recomendación concreta para P5-1, en tres reglas robadas:

1. **Unidad = entidad única por ciclo, no evento.** Si Qualify enriquece 6 veces al mismo creador
   en un mes, es **1 crédito**, como el contacto activo. Convierte el reintento en gratis y elimina
   el incentivo perverso de facturar por reintento.
2. **Almacenar es gratis; activar se paga.** Tener 50.000 creadores en `crm.creators` no cuesta;
   solo cuesta el creador sobre el que se ejecuta una acción en ese ciclo. Es la propiedad que
   más diferencia a ManyChat de Clay y la más fácil de trasladar.
3. **Excedente con tarifa publicada y decreciente + avisos al 70/90/100 %, nunca corte duro.**
   Barato de implementar (`billing.usage_events` ya está diseñado) y ataca directamente el miedo
   que P5-1 identifica como decisivo para la confianza en el modelo de negocio.

### 3.3 Contradicción de packaging detectada (dato para no copiar el error)

El artículo **[Precios de Manychat Inbox](https://help.manychat.com/hc/es/articles/14281088746652)**
(actualizado 2026-07-22) describe Inbox como **producto separado**: "precio inicial de USD 99, que
incluye tres asientos de Live Chat", asiento adicional **$39**, y advierte que suscribir Inbox
*y* Marketing Automation **no suma asientos** (siguen siendo 3). Los artículos de plan nuevos
(misma fecha) dicen que los asientos extra cuestan **$25** y vienen incluidos por plan.

Es decir: **dos SKUs solapados con precios de asiento distintos ($39 vs $25) documentados a la
vez**. No es un error de lectura mío — es el coste real de haber cambiado de modelo de precios
sin terminar la migración. **Lección para Fase 5:** un cambio de unidad de facturación deja años
de deuda de packaging; conviene elegir la unidad **antes** de tener clientes, no después.
No verificado si la página de precios en vivo refleja el $39 o el $25 (403).

### 3.4 Costes que ManyChat *no* absorbe

- **WhatsApp**: Meta cobra por conversación aparte; ManyChat lo repercute vía "Billetera de
  Manychat" y una "línea de crédito de WhatsApp"
  [P, [Guía de precios para WhatsApp](https://help.manychat.com/hc/es/sections/13556952605852-WhatsApp)].
- **SMS y email** también consumen esa billetera
  [P, [Billetera de Manychat para plantillas de mensajes y correo electrónico](https://help.manychat.com/hc/es/sections/13556960960284)].
- **IA**: no encontré en el help center un artículo de "créditos de IA" ni una tarifa por token o
  por respuesta generada. Las features de IA están gateadas **por plan** (Pro+), no medidas.
  **Hipótesis a verificar:** ManyChat trata la IA como coste hundido dentro del precio del plan,
  no como unidad facturable. Si se confirma, es un contraejemplo relevante: el vendor más grande
  de la categoría **no** vende créditos de IA, y Qualify debería justificar por qué sí.

## 4. Campo competitivo (G4)

### 4.1 Tabla de posiciones (precios verificados en página oficial, acceso 2026-07-23)

| Vendor | Precio de entrada de pago | Unidad medida | Canales | Dónde gana | Dónde pierde | Fuente |
|---|---|---|---|---|---|---|
| **ManyChat** | $17 (Essential) → $199 (Advanced) | **Contactos activos/mes** | IG, TikTok, Messenger, Telegram, WA, SMS, email | Cobertura de disparadores de IG (la más profunda del mercado); ecosistema de plantillas y agencias; partner de Meta desde 2015 | Precio escala con el **éxito** del cliente; Free recortado a 25 contactos; TikTok muy limitado | [P] help center §3 |
| **respond.io** | **$79** (Starter) · $159 (Growth) · $279 (Advanced) | **Monthly Active Contacts** + usuarios ($12–24/extra) | WA, IG, FB, TikTok, chat, email | Routing e inbox de equipo; escala enterprise; **partner de mensajería listado por TikTok** | 4,6× más caro de entrada; producto de soporte, no de creator | [P] [respond.io/pricing](https://respond.io/pricing) |
| **Chatfuel** | **$49** (AI PRO); Light gratis | "Usage limits apply" — **no publica la unidad en la página de precios** | IG, FB, WA | Free real; AI-first ("AI sales manager", knowledge base); "150.000+ negocios" | Sin TikTok; pricing opaco | [P] [chatfuel.com/pricing](https://chatfuel.com/pricing) |
| **Tidio / Intercom / Zendesk** | — (no verificado en esta pasada) | — | Web chat primero | Soporte web + helpdesk | No son productos de creator/social-first | **Pendiente** |
| **Cola de retadores baratos** (InstantDM, DMdaddy, ReplyRush, Inrō, creatorflow…) | $8–20 | **Automatizaciones**, no contactos | IG casi exclusivamente | Precio; posicionamiento explícito "no cobramos por contacto" | Cobertura de un solo canal; longevidad dudosa | [S] blogs de los propios vendors |
| **DIY con Zapier / Make** | Coste de la API + del plan Zapier | Tareas | Los que la API permita | Flexibilidad | **No resuelve el gate del §2**: sigue haciendo falta una app aprobada. No es un atajo | [P] [Integración de Zapier](https://help.manychat.com/hc/es/sections/13556926216988) |
| **Nativo de Meta** (respuestas automáticas de IG, Business Suite) | $0 | — | IG/FB | Gratis, sin terceros, sin riesgo de ban | Solo keyword básico; sin flujos, sin CRM, sin IA | **Pendiente de verificar** — hipótesis |

### 4.2 Dónde pierde ManyChat (y por qué importa para Qualify)

**a) Su modelo de precios castiga el éxito.** Es la crítica más repetida y la más estructural: el
contador de contactos activos sube **cuando el contenido del cliente funciona**. Un creador que
publica bien "puede pasar de $15 a $65 a $145/mes en 18 meses" [S,
[creatorflow](https://creatorflow.so/blog/manychat-pricing-trap/) — competidor, tratar como
hipótesis]. **Este es el contrapeso honesto a mi propia recomendación de §3.2:** el modelo de
contacto activo es excelente contra el *credit burn* (nunca cobras por un intento fallido) y
**pésimo** como incentivo, porque acopla la factura al éxito del cliente sin acoplarla a su
ingreso. Para P5-1 hay que robar la *unidad* (entidad única por ciclo) **sin** robar la *curva*:
el excedente decreciente de ManyChat ($0,10 → $0,004) es justamente su parche para este problema,
y llega tarde.

**b) El recorte del plan Free (marzo 2026): de ~1.000 a 25 contactos activos.** Consenso [S] entre
múltiples fuentes ([instantdm](https://instantdm.com/blog/manychat-pricing-explained-2026-manychat-active-contacts),
[flowgent](https://flowgent.ai/blog/manychat-review), [dmdaddy](https://dmdaddy.com/blog/manychat-alternatives),
acceso 2026-07-23). El artículo oficial [P] confirma los 25 de hoy pero **no documenta el valor
anterior**, así que el "1.000 → 25" queda como **hipótesis [S] bien respaldada, no como hecho
verificado**. Si es cierto, explica el enjambre de retadores baratos de 2026: ManyChat abrió un
hueco de precio de 40× en el escalón de entrada, y ~6 productos entraron por él.

**c) Otras quejas recurrentes [S]:** soporte solo por email y lento; cargos tras cancelar; "IA
débil" frente a Chatfuel. Ninguna verificada en fuente primaria — **listadas como hipótesis**.

**d) TikTok es un agujero de cobertura** (§2.4), y respond.io **sí** aparece en la lista oficial
de partners de mensajería de TikTok mientras que ManyChat no. Señal de que el liderazgo de
ManyChat es específico de Meta, no de la categoría.

### 4.3 Dónde gana ManyChat — y por qué Qualify no debe atacarlo ahí

Gana en **profundidad de disparadores sobre Instagram** (14 superficies distintas, §1.2), en
**ecosistema** (plantillas revendibles, programa de socios, marketplace de apps de terceros con
su propio review) y en **antigüedad de la relación con Meta**. Los tres son fosos que se cavan con
años, no con features. Un entrante que compita en "mejor comment→DM" pierde.

### 4.4 Lo que un entrante *listening-first* sí podría tomar

Toda la categoría — ManyChat, Chatfuel, respond.io y los retadores — comparte el mismo punto
ciego: **son reactivos y ciegos fuera de la cuenta del cliente**. Ninguno sabe:

- qué se dice de la marca en **cuentas ajenas** (el corpus entero de Qualify);
- qué hay **dentro del vídeo y del audio** (ni siquiera dentro del contenido propio del cliente);
- quién es el contacto **antes** de que escriba (ManyChat conoce un `PSID` y lo que el usuario
  teclee en el flujo; no conoce su historial de contenido ni su afinidad de marca).

Y hay una asimetría de precio explotable: **respond.io y ManyChat convergen en la misma unidad**
(*Monthly Active Contacts* / contactos activos; respond.io lo titula literalmente "Pay only for
the contacts you talk to") [P, ambas páginas de precios, 2026-07-23]. Que dos vendors
independientes hayan convergido es la mejor evidencia disponible de que **es la unidad correcta
para la categoría de conversación** — y es un argumento fuerte para P5-1 (§3.2), más fuerte que
copiar a un solo vendor.

## 5. Screen owned-vs-earned (G5)

**Criterio del screen.** Para cada feature: ¿se puede construir sobre el plano de datos de
Qualify (contenido público scrapeado de cuentas ajenas: posts, vídeo, audio, captions,
comentarios → ClickHouse), o exige que el cliente nos conceda OAuth sobre su cuenta?

Tres veredictos:

- **🟢 Alcanzable** — no depende de poseer ninguna cuenta.
- **🟡 Alcanzable solo con OAuth del cliente** — Qualify tendría que pedir la cuenta, lo que la
  convierte en otro producto (mismo problema que ADR 19).
- **🔴 Estructuralmente inalcanzable** — ni con OAuth resuelve el caso de uso de Qualify, o
  requiere el gate de §2 completo.

### 5.1 La tabla

| # | Feature de ManyChat | Veredicto | Por qué |
|---|---|---|---|
| 1 | **Comment→DM (IG posts/reels)** | 🔴 | Doble bloqueo: el webhook de comentarios solo llega para **tus** posts, y el DM saliente exige `instagram_business_manage_messages` bajo app aprobada (§2). Qualify puede *leer* comentarios de posts ajenos por scraping, pero **no puede responderlos ni abrir un DM** |
| 2 | Comentarios de IG Live | 🔴 | Ídem, sobre contenido efímero propio |
| 3 | Respuestas a historias | 🔴 | Evento sobre historia propia |
| 4 | **Follow to DM** | 🔴 | Evento de la cuenta propia |
| 5 | "Comparte a mensaje directo" | 🔴 | Evento sobre contenido propio |
| 6 | Disparador de anuncios (CTM) | 🔴 | Requiere ser el anunciante |
| 7 | **Menciones en historias → respuesta** | 🟡 | El *evento* es medio ganado (un tercero te menciona), pero llega por webhook **al dueño de la cuenta mencionada**. Sin OAuth del cliente, Qualify no lo ve. Coincide con `mentioned_media` de `fase0-zernio-mercado.md` §4.3 |
| 8 | Ref URL / QR | 🟢 | Es un link con parámetros. Trivial y sin gate — y por eso sin valor defensivo |
| 9 | Disparador de palabra clave sobre DM | 🔴 | Requiere recibir el DM |
| 10 | **Reconocimiento de intención (IA)** | 🟢 | Es un clasificador de texto. **No depende del canal**: se puede correr sobre el corpus de comentarios scrapeados. Ver §5.3 |
| 11 | **AI Knowledge (RAG de marca)** | 🟢 | Recuperación sobre corpus propio. Ver §5.3 |
| 12 | AI Goals / AI Step / AI Replies | 🟡 | La *generación* es alcanzable; la *entrega* al usuario no lo es sin canal |
| 13 | **AI Comments** (responder al comentario público) | 🔴 | Solo sobre comentarios en contenido propio, y exige `instagram_business_manage_comments` |
| 14 | **Flow builder** (bloques, condiciones, acciones, variables, secuencias) | 🟢 | Orquestación pura, agnóstica de canal. **Y Qualify ya tiene su equivalente: LangGraph** (`docs/arquitectura.md` §Orquestador Agentivo) |
| 15 | Campos personalizados / tags / segmentos | 🟢 | Modelo de datos. Se puebla desde listening en vez de desde conversación |
| 16 | Fusión de contactos / identidad cross-canal | 🟢 | Se resuelve por handle/plataforma; es el mismo problema que `crm.creators` (Fase 4) |
| 17 | Difusión / secuencias / broadcast | 🔴 | Necesita canal de envío y opt-in previo. Además **la ventana de 24 h/48 h impide el saliente en frío** (§2.3) |
| 18 | Inbox / Live Chat / asignación de conversaciones | 🔴 | Requiere ser dueño de las conversaciones |
| 19 | Checkout en DM (Stripe/PayPal, botón de compra) | 🔴 | Requiere el canal |
| 20 | **Públicos personalizados de IG + CAPI** | 🟡 | Exige el Business Manager del cliente. Pero la *lista* que lo alimenta sí puede venir de listening (§5.3) |
| 21 | Plantillas instalables / marketplace | 🟢 | Empaquetado de producto, sin gate |
| 22 | **External Request / Dynamic Block / API** | 🟢 | Superficie de integración. **Es la vía de entrada de Qualify a ManyChat** (§6) |
| 23 | Analytics de Live Chat, contactos activos | 🟡 | Métricas sobre datos de conversación propia |

**Recuento: 11 🔴 · 5 🟡 · 7 🟢 sobre 23.**

### 5.2 El hallazgo incómodo — la tesis del brief **no se refuta, se confirma**

Se me pidió intentar refutar el eje owned-vs-earned. **No lo consigo, y el patrón de los datos es
peor que un simple reparto:**

> **Todo lo 🟢 es commodity; todo lo que constituye el foso de ManyChat es 🔴.**

Las 7 features alcanzables son: un link con parámetros, un clasificador de intención, RAG, un
motor de flujos, un modelo de datos de contacto, deduplicación de identidad y un webhook saliente.
**Ninguna es propiedad de ManyChat.** El flow builder lo tiene Zapier; RAG lo tiene cualquiera;
el motor de flujos Qualify ya lo tiene decidido (LangGraph). Es decir: **lo que Qualify puede
robar, no hacía falta robarlo a ManyChat.**

Y a la inversa: lo que hace que ManyChat valga $199/mes — recibir el comentario en el instante en
que se produce y contestar por DM dentro de la ventana de 24 h — **es 100 % 🔴**, y lo es por dos
razones independientes (no ver el evento; no poder enviar), de modo que resolver una no desbloquea
nada.

**Consecuencia directa para el architect (A6):** una ADR que proponga "superficie de activación
inspirada en ManyChat" construida nativamente **carece de base**. La única forma defendible es
*integración*, no *reimplementación*. Además, el §2.3 (ventana de mensajería) añade una
imposibilidad que ni siquiera el OAuth resuelve: **una señal de listening no abre una ventana de
mensajería**. Cualquier "play" de Fase 5 del tipo *señal detectada → DM al creador* es
**imposible por política de plataforma**, no por falta de ingeniería. El carril de outbound a
creators no afiliados sigue siendo email/LinkedIn (Instantly/HeyReach), tal como ya concluyó
`fase0-zernio-mercado.md` §6.2 Riesgo 1.

### 5.3 Lo que sí se vuelve *más* potente con medios ganados (aquí está la ventaja real)

Cinco casos donde la primitiva de ManyChat, alimentada con listening en vez de con eventos de
cuenta propia, **mejora en vez de degradarse**:

**1. Reconocimiento de intención sobre el corpus de la categoría, no sobre tu buzón.**
ManyChat clasifica intención en los DMs que **ya te llegaron** — un flujo pequeño y con **sesgo de
selección brutal**: solo contiene gente que ya decidió hablarte. Qualify puede correr el mismo
clasificador sobre **todos los comentarios de la categoría, incluidos los de la competencia**. Es
el mismo modelo, dos o tres órdenes de magnitud más de corpus, y sin el sesgo. Traduce a: *"¿qué
intención de compra existe en el mercado?"* frente a *"¿qué me preguntó quien ya me escribió?"*.
→ **Fase 3** (señales tipadas, P3-1) — encaja con la propuesta `bge-m3-zeroshot-v2.0` de
`docs/modelos-multimodal-fase1.md` y con el hueco documentado en
`packages/models/NOTES_pain_signal_feasibility.md`.

**2. AI Knowledge invertido: la base de conocimiento la escribe el mercado, no la marca.**
El *AI Knowledge* de ManyChat se alimenta de lo que la marca dice de sí misma — **exactamente el
dato auto-reportado que `CLAUDE.md` identifica como el punto débil de los competidores**. La
versión de Qualify se alimenta de transcripciones, descripciones visuales y comentarios reales.
Es la aplicación más limpia del principio "primary-source content" a una feature concreta.
→ **Fase 5** (smart replies con RAG, ya en el README).

**3. La mención en historia es un caso particular de algo que Qualify ve entero.**
El disparador #7 solo se activa con **@-mención explícita, desde perfil público, en Story** [P].
El pipeline de Qualify detecta además: menciones sin @, menciones **habladas en el audio**,
logos y productos **mostrados en vídeo**. ManyChat ve el subconjunto trivial; Qualify ve el
superconjunto — **pero ManyChat puede contestar y Qualify no**. Esa frase es el resumen exacto de
la relación entre los dos productos.
→ **Fase 3** (alertas de mención en vídeo/audio).

**4. Audiencias construidas por escucha, no por historial de conversación.**
El público personalizado de ManyChat solo puede contener a quien ya le habló al cliente. Una lista
construida desde listening (quien habla de la categoría, del competidor, o muestra la señal X)
es **prospección**, no remarketing. La activación sigue siendo 🟡 (necesita el Business Manager
del cliente), pero la lista es 🟢 y es donde está el valor.
→ **Fase 4** (discovery/scoring) + **Fase 5** (activación).

**5. Enriquecer el contacto de ManyChat con el historial de contenido del creador.**
El contacto de ManyChat es un `PSID`/handle más lo que el usuario tecleó en el flujo. Qualify sabe
qué publica esa persona, de qué habla, con qué marcas, con qué afinidad. **Un `Dynamic Block` que
consulte a Qualify en runtime** permitiría a ManyChat ramificar el flujo por afinidad de marca —
sin que Qualify toque el canal ni pida OAuth de mensajería. Es el punto de integración con mejor
relación valor/riesgo de todo el documento.
→ **Fase 4/5**.

### 5.4 La asimetría, en una línea

**Qualify sabe a quién habría que hablarle y no puede abrir el canal; ManyChat puede hablar y solo
conoce a quien ya apareció.** Son complementarios, no sustitutos — lo que convierte "robar
features" en la estrategia equivocada e **"integrarse" en la correcta** (§6).

## 6. Recomendación (G6)

### 6.1 Veredicto general

**NO-GO a "construir la superficie de activación conversacional de ManyChat dentro de Qualify".**
Tres razones independientes, cada una suficiente:

1. **Gate de plataforma** (§2.2): exige App Review + Business Verification + entidad legal
   verificada ante Meta y estatus de partner en TikTok. Es el mismo peaje de 2–4 meses,
   rechazable y revocable, que `fase0-zernio-mercado.md` §1.2 ya cuantificó — ManyChat no lo
   desmiente, lo ejemplifica.
2. **Ventana de mensajería** (§2.3): el DM saliente en frío **no existe** en IG/Messenger/WA/TikTok.
   La ventana la abre el usuario. Un "play" de Fase 5 del tipo *señal → DM al creador* es
   imposible por política, no por ingeniería.
3. **Screen owned-vs-earned** (§5.2): las 11 features 🔴 son precisamente el foso de ManyChat; las
   7 🟢 son commodity que Qualify ya tiene resuelto de otra forma (LangGraph, RAG, ClickHouse).

**GO a "integrarse con ManyChat como canal de activación de terceros"** y **GO a robar tres ideas
concretas de producto** (unidad de facturación, clasificador de intención, RAG invertido) que no
dependen del canal.

### 6.2 Top features, con fase y veredicto

| # | Qué se roba | Fase | Veredicto | Justificación en una línea |
|---|---|---|---|---|
| 1 | **Unidad de facturación = entidad única por ciclo** ("contacto activo"), almacenar gratis / activar se paga, excedente publicado y decreciente, avisos 70/90/100 % | **5** (P5-1) | **GO-WITH-CHANGES** | Dos vendors independientes convergen en la unidad (§4.4). **El cambio obligatorio:** no acoplar la factura al éxito del cliente — la queja #1 contra ManyChat (§4.2a) |
| 2 | **Reconocimiento de intención como disparador**, sobre el corpus de comentarios scrapeados en vez de sobre DMs recibidos | **3** (P3-1) | **GO** | Misma primitiva, ×100–1000 corpus, sin sesgo de selección. Cierra el hueco de `NOTES_pain_signal_feasibility.md`; candidato ya propuesto (`bge-m3-zeroshot-v2.0`) |
| 3 | **AI Knowledge invertido**: RAG sobre transcripciones/comentarios reales, no sobre lo que la marca dice de sí misma | **5** (smart replies) | **GO** | Aplicación más limpia del principio "primary-source content" de `CLAUDE.md` |
| 4 | **Integración vía `Dynamic Block` / `External Request`**: ManyChat consulta a Qualify en runtime y ramifica el flujo por afinidad/scoring del creador | **5** | **GO-WITH-CHANGES** | Endpoint HTTPS arbitrario con fallback, documentado públicamente [P, [Dev Tools: Dynamic block](https://help.manychat.com/hc/en-us/articles/14281268533788), 2026-07-23]. Qualify aporta el dato y **no toca el canal ni pide OAuth de mensajería**. *Cambio:* requiere que el cliente ya sea usuario de ManyChat — validar demanda antes de construir |
| 5 | **Listas/segmentos construidos por listening → Custom Audience de Meta** | **4→5** | **GO-WITH-CHANGES** | La lista es 🟢, la activación es 🟡 (Business Manager del cliente). Es prospección, no remarketing — ahí está la diferencia con ManyChat |
| 6 | **Deduplicación de identidad cross-plataforma** del contacto | **4** | **GO** | Ya es requisito de `crm.creators`; ManyChat confirma que la ambigüedad IG-vs-TikTok es real y que ellos tampoco la resuelven del todo [P, §3.2] |
| 7 | Plantillas/recetas empaquetadas e instalables ("automatizaciones rápidas") | **5** | **GO-WITH-CHANGES** | Buen patrón de empaquetado para los "plays" de Fase 5. Sin valor si no hay plays antes |
| 8 | **Comment→DM nativo, en cualquier plataforma** | — | **NO-GO** | §5.1 #1: doble bloqueo (no ver el evento + no poder enviar). En TikTok **ni ManyChat lo tiene** (§2.4) |
| 9 | **Inbox unificado / Live Chat / asignación de conversaciones** (Fase 6 del phase map) | 6 | **NO-GO como construcción propia** | Requiere poseer las conversaciones **y** pasar el gate de §2. Si se quiere, se compra o se integra |
| 10 | **Difusión / secuencias / broadcast por DM** | — | **NO-GO** | Prohibido por la ventana de mensajería sin opt-in previo (§2.3). Riesgo sancionable: despublicación de Página, desactivación de cuenta |
| 11 | Flow builder visual propio | — | **NO-GO** | Duplicaría LangGraph. Decisión que corresponde al architect (A3), pero desde GTM no hay caso de mercado: el flow builder no es diferenciador de nadie |
| 12 | Canal TikTok DM nativo | — | **NO-GO** | Partner cerrado, geobloqueo, **solo cuentas Business** — excluye a creators y podcasters, que son audiencia objetivo de Qualify (§2.4) |

### 6.3 Lo que hay que decirle al architect (rutas de conflicto)

1. **Contradice cualquier ADR de "activación conversacional nativa" (A6).** El §2.3 (ventana de
   mensajería) y el §5.2 (todo el foso es 🔴) implican que la ADR debe redactarse como
   **integración**, no como capacidad propia. Si A6 se escribió asumiendo lo contrario, hay
   debate.
2. **Refuerza, no debilita, la ADR 19.** El eje owned-vs-earned se confirma en un segundo dominio.
   El matiz de `fase0-zernio-mercado.md` §4.3 (menciones en Stories como medio ganado accesible
   por OAuth) se confirma también: ManyChat tiene exactamente ese disparador y **solo ese** es
   medio ganado, de ~14.
3. **No cambia ninguna decisión de vendor de Fase 1.** Nada aquí toca Zyte, EnsembleData, Groq,
   Gemini, Smartlead/Zapmail/Prospeo. **Sí añade un vendor candidato para Fase 5**: ManyChat (o
   respond.io) como canal de activación conversacional, bajo la regla "buy, don't build" — y añade
   una categoría nueva a esa regla: *el acceso aprobado a las APIs de mensajería es infraestructura
   commodity que se compra, no se construye*.
4. **Afecta a P5-1** (`docs/backlog-features-gtm.md`): recomendación concreta de unidad de
   facturación en §3.2, con el contrapeso de §4.2a.
5. **Afecta a P3-1**: el reconocimiento de intención sobre corpus de medios ganados (§5.3.1) es
   evidencia de mercado adicional a favor del clasificador zero-shot ya propuesto. Compartido con
   `datasci` (D2).

### 6.4 Preguntas abiertas que esta investigación no cerró

- **Geografía real de TikTok DM**: ManyChat [P] dice EE. UU./UK/UE bloqueados; fuentes [S] dicen lo
  contrario. Y ManyChat **no figura** en la lista oficial de Messaging Partners de TikTok, donde sí
  está respond.io. Sin resolver — requiere contacto directo con TikTok.
- **Valor anterior del plan Free** (¿1.000 contactos antes de marzo 2026?): solo respaldo [S].
- **Créditos de IA**: no encontré tarifa medida en el help center. Hipótesis: la IA va incluida en
  el plan, no medida. Verificar en la página de precios (403 desde cliente no-navegador).
- **Contradicción $39 vs $25 por asiento de Inbox** (§3.3): no verificable sin la página en vivo.
- **Términos de uso de la API de ManyChat**: ¿permiten a un tercero (Qualify) empaquetar la
  integración y revenderla? Mismo tipo de riesgo que la cláusula de Ayrshare en
  `fase0-zernio-mercado.md` §2.3. **No verificado — condición previa a cualquier plan de
  integración.**
- **Respuestas automáticas nativas de Instagram** (gratis, sin terceros): no verificadas. Definen
  el suelo de valor de toda la categoría.
- **Tidio, Intercom y el segmento helpdesk**: fuera del alcance de esta pasada.

## Notas de metodología

Investigación de escritorio con web en vivo, **2026-07-23**. `manychat.com` y
`help.manychat.com/hc/*` devuelven **403 a clientes no-navegador**; el inventario y todo el
pricing se obtuvieron de la **API pública de Zendesk Help Center**
(`/api/v2/help_center/{es,en-us}/…`), que responde 200 sin autenticación — **193 artículos ES,
200 EN**. Esa API es fuente primaria (es el mismo contenido que sirve el help center), pero
**la página de precios comercial no pudo verificarse**, de modo que las cifras de §3 son las del
help center oficial y podrían diferir de la oferta en vivo por región.

Las quejas de mercado (§4.2) proceden de blogs de competidores directos de ManyChat, que tienen
incentivo en exagerarlas: van etiquetadas **[S]** e identificadas como hipótesis. Ningún precio
ha sido validado con el vendor ni negociado. Los requisitos de App Review de Meta se leyeron de
documentación oficial, pero **Meta no publica SLA de revisión** — los plazos citados provienen de
`docs/fase0-zernio-mercado.md`, que a su vez los obtuvo de reportes de desarrolladores [S].
