# Guía de navegación de Qualify

`[v2 · 2026-10-23 · agente ux-designer · decisiones del fundador incorporadas, §7]` · **Estado:** decidida por el fundador el 2026-10-23 (§7).
Lo marcado **⚑ Decisión** cambia la arquitectura de información firmada (zonas «Escuchas / Publicas»,
`docs/index.md`; menú en `Qualify/ui/layout.py:36-96`) o introduce un patrón nuevo; nada se construye
sin su visto bueno. El resto son reglas que ya caben en el sistema de diseño (`docs/design-system.md`).

Fuentes: auditoría `docs/ux-auditoria-2026-10.md` y sus siete informes por módulo
(`docs/ux-auditoria-2026-10/m1…m7`). Persona: `docs/perfil-cliente-pyme.md`.

## 1. El problema, en una frase

El dueño abre Qualify y aterriza en una tabla de menciones de terceros; el menú tiene **17 entradas**
(2 deshabilitadas «pronto», una demo y 4 palabras en inglés) ordenadas por **cómo está construido el
producto**, no por **lo que el dueño viene a hacer**. Un mismo trabajo está en varios lugares
(responder: 4 lugares; publicar: 4 entradas) y casi ninguna pantalla dice cuál es el siguiente paso.

## 2. Los cuatro trabajos del dueño (el menú se ordena por ellos)

| Trabajo, en sus palabras | Zona del menú | Lo que hoy está repartido en |
|---|---|---|
| «¿Qué tengo que hacer hoy?» | **Inicio** | — (no existe; `/` es Menciones) |
| «Que nadie se quede sin respuesta» | **Atiende** | Interacciones, Conversaciones (+ vista Consultas), WhatsApp › Chats, Leads |
| «Tener publicaciones listas sin pensar» | **Publica** | Crear pieza, Piezas, Planificador, Publicar |
| «¿Cómo me va?» | **Resultados** | Menciones (`/`), Clarity, métricas dentro de WhatsApp |
| «Que todo salga con mi estilo» (se toca poco) | **Tu negocio** | Brand Kit, Catálogo, Conexiones, Configuración |

## 3. Mapa del menú (decidido, §7 #2)

```
Qualify  ·  Bianki                      (bloque del negocio, como hoy)

  Inicio                         /                     ← NUEVO hub: «Hoy tienes» + «Así te fue»

ATIENDE  (tinte «listen», el de hoy)
  Por responder        (5)       /responder            pestañas: Mensajes · Quieren comprar ·
                                                       Comentarios · WhatsApp · Interesados
  WhatsApp                       /whatsapp             pestañas: Chats · Respuesta automática ·
                                                       Promociones · Tu número

PUBLICA  (tinte «publish», el de hoy)
  Crear publicación              /create
  Por aprobar          (2)       /drafts
  Tu semana            (1)       /planner
  Publicar ahora                 /publish

  Resultados                     /resultados           pestañas: Redes · WhatsApp · Tu página web ·
                                                       Quién habla de ti (hoy Menciones)
TU NEGOCIO
  Tu marca                       /brand/kit
  Tus productos                  /catalog
  Tus redes                      /connections
  Configuración                  /settings
                                                       [Cerrar sesión]
```

**12 entradas** más Creadores y Oportunidades (antes «Señales», decidido 2026-10-23), que siguen con «Pronto» (decisión 4); hoy son 17.
Fuera del menú del cliente: `/design`. **Vitrina se elimina por completo** (ruta, menú y código):
no tiene relación con el producto por ahora (fundador, 2026-10-23).
Las dos zonas con tinte siguen siendo dos (no hay colores nuevos): «Escuchas» pasa a llamarse
**Atiende** y «Publicas» a **Publica**.
Los números entre paréntesis son contadores de pendientes (`tone_badge`, ya existe).

**Rutas viejas:** `/inbox`, `/conversations`, `/leads`, `/clarity`, `/stories` y el `/` de
Menciones **redirigen** a su nuevo lugar (como ya hace `/stories` → `/publish?flow=stories`):
ningún enlace guardado se rompe.

## 4. Las reglas (para toda pantalla nueva o revisada)

Cada regla tiene un **cómo se comprueba**, para que la revisión local de experiencia
(`qualify-ux` §6) y los criterios de aceptación puedan citarla por número.

| # | Regla | Cómo se comprueba |
|---|---|---|
| **N1** | **Un nombre por lugar.** Entrada del menú = `h1` del `page_header` = título de pestaña `Qualify · <nombre>`, en palabras del dueño. El menú puede usar una forma corta aprobada del mismo nombre («Interesados» para «Clientes interesados»), nunca un nombre distinto. | Los tres textos son idénticos en `layout.py`, la página y `Qualify.py`. |
| **N2** | **Inicio es el centro.** Entrar a la cuenta, terminar la marca y cerrar un asistente con «Seguir después» llevan a `/`. Mientras falte algo para la primera publicación, Inicio muestra «Para tu primera publicación» (lista con ✓). | `AuthState` redirige a `/`; Inicio con 0 datos no está vacío. |
| **N3** | **Toda tarea termina con «listo» y el siguiente paso.** Confirmación en palabras simples + **un** botón sólido al siguiente trabajo + uno suave para volver. Nunca solo un aviso flotante (toast). | No hay `rx.toast` como único resultado de Aprobar, Programar, Publicar, Guardar, Enviar. |
| **N4** | **El que sale a buscar algo vuelve con eso elegido.** Si una pantalla manda a otro módulo («Agregar producto» desde Crear), al terminar vuelve al origen con lo creado ya seleccionado (`?volver=<ruta>`). | El recorrido Crear → Productos → Crear no pierde el paso ni el producto. |
| **N5** | **Todo tiene su dirección.** Cada pestaña (`?tab=`), cada ficha (`/catalog/[id]`, `/drafts/[id]`) y cada vista de lista tiene URL propia: el «atrás» del celular y recargar dejan al dueño donde estaba, y cualquier aviso puede llevar directo. | Cambiar de pestaña cambia la URL; recargar la conserva. |
| **N6** | **Asistentes de un paso, una decisión.** «Paso N de M» con M real (sin contar los saltados), «Atrás» sin perder datos, «Seguir después», valores ya rellenados, último paso = revisión en palabras («Sale el jueves 7 p. m. en Instagram»), lo avanzado detrás de «Más opciones». | Ningún paso con más de ~3 campos; existe «Seguir después». |
| **N6b** | **El marco de paso a paso: dónde estás, cómo vuelves y cómo sigues, siempre a la vista** (fundador, 2026-10-25). Todo flujo de más de un paso usa el marco de `docs/design-system.md` §4.5. Arriba, fijo: «‹ destino», «Paso N de M» con barra y el nombre del paso. Abajo, fijo: «Atrás» · botón principal · «Seguir después» (→ Inicio); en el celular ocupa el lugar de la barra inferior. Al cambiar de paso, el contenido vuelve arriba y el foco va al título. Cada paso tiene `?paso=N`, y el «atrás» del celular retrocede un paso. | Con el paso más largo a 360 px, sin desplazarse, se ven el paso en que vas, la salida y el botón principal; el «atrás» del navegador retrocede un paso. |
| **N7** | **«Volver» dice a dónde.** «‹ Tu semana», «‹ Tus productos», nunca «Volver» o «‹» solos. Las fichas abiertas desde una lista vuelven a esa lista, con el mismo filtro. | Texto del enlace = nombre del destino (N1). |
| **N8** | **Ningún vacío sin salida.** Todo estado vacío explica qué falta y lleva al paso previo con `empty_state(action=)`: «Todavía no tienes productos → Agregar producto»; «¡Al día! → Preparar la publicación de mañana». | Cada `empty_state` tiene `action`. |
| **N9** | **Salir de Qualify se avisa.** «Ver en Instagram ↗», «Abrir Canva ↗». Nunca un «Ver» que saca de la app sin decirlo. | Todo enlace externo lleva destino + ↗. |
| **N10** | **El menú solo muestra lo que el dueño puede usar hoy, o lo que viene marcado «Pronto».** Ninguna demo ni herramienta del equipo. Una entrada «pronto» dice «Pronto» en texto (no solo por color o por estar apagada) y al tocarla no lleva a una pantalla vacía (decisión 4, 2026-10-23). | Las entradas `enabled=False` muestran «Pronto» como texto; no hay demo en `NAV_*`. |
| **N11** | **Lo pendiente se cuenta donde se resuelve.** Por responder, Por aprobar y Tu semana llevan contador; cada cifra de Inicio y Resultados es pulsable y abre la lista ya filtrada. | `card(interactive=True)` con `href` a la lista filtrada. |
| **N12** | **Celular primero.** A 360 px: una columna, menú alcanzable, máximo 4 pestañas visibles sin deslizar de lado (las demás, agrupadas como sub-pestañas), objetivos ≥ 44 px, nada solo al pasar el mouse. | Prueba a 360 px en cada ruta tocada. |
| **N13** | **Asistido, nunca autónomo.** Los botones dicen quién actúa y qué pasa: «Aprobar», «Programar para el jueves», «Enviar a 128 clientes». Ningún texto dice o insinúa que Qualify publica o responde solo. | Revisión de copy contra la decisión firmada (ADR 21). |

### Contrato de direcciones internas (PASOS-3, m-24852246)

Las pantallas que cambian contenido sin navegar montan `ui.route_history.route_history`.
El `pushState` puede ser invisible a React Router: al volver a la entrada que recuerda,
`on_load` puede no ejecutarse. El manejador explícito de `popstate` vuelve a leer la
URL y restaura el estado de forma idempotente. No envía, publica ni crea borradores.

| Parámetros | Significado |
|---|---|
| `tab`, `sub` | Pestaña y subpestaña de WhatsApp; Por responder usa `/responder?tab=…`. |
| `cuenta`, `chat` | UUID internos de conexión y conversación. Se validan contra las cuentas del negocio y se leen con el proveedor limitado a tenant y conexión. |
| `ficha` | UUID de la publicación de Tu semana abierta como detalle; `evento` conserva su significado en la revisión de videos. |
| `flujo`, `paso` | Asistente o cajón activo y su paso visible, contado desde 1. |
| `objeto`, `consulta` | UUID interno del menú/evento/mensaje o de la consulta que necesita el flujo. |

Valores de `flujo`: `producto`, `programar`, `reprogramar`, `menu`, `consulta`,
`promocion`, `mensaje-aprobado` y `mensaje-chat`. `ui.flow_history.flow_sync` escribe
solo el flujo activo, después de restaurarlo. Los valores dinámicos se leen de atributos
DOM, nunca se interpolan como código JavaScript. Los pasos de página completa siguen
usando `ui.steps.step_sync`.

El «Atrás» consume la entrada propia del paso. Cerrar un cajón consume sus entradas y
restaura la dirección que lo abrió; no agrega una lista nueva encima de los pasos viejos.
Las guardias abren el primer paso pendiente si faltan datos. Las respuestas y archivos
conservados en la sesión se reutilizan; una sesión nueva empieza por lo que falte y nunca
simula un guardado ni un envío. La URL no incluye nombres, teléfonos ni textos del cliente.

## 5. El recorrido principal (cómo se encadenan los módulos)

```
Invitación → Crear tu cuenta → Tu marca (mínimo, ~5 pasos) → INICIO «Para tu primera publicación»
                                                                │
   ┌────────────────────────────────────────────────────────────┘
   ▼
Crear publicación ①Qué mostrar ②Qué decir ③Cómo la quieres ④Revisa y crea
   │  (sin productos → Tus productos/nuevo → vuelve con el producto elegido, N4)
   ▼
Por aprobar › Revisa tu publicación ── [Aprobar] → «Aprobada. Todavía no se publica.»
   ▼                                              [Elegir día y hora]  (N3)
Tu semana (con la publicación ya elegida) ── [Programar] → «Sale el jue 30, 7:00 p. m.»
   ▼
(se publica cuando el dueño lo programó y aprobó)
   ▼
Por responder › Comentarios de esa publicación ── [Enviar respuesta] → «Siguiente pendiente»
   ▼                                              (cero pendientes → «¡Al día!» → Inicio, N8)
Resultados «Así te fue»
```

## 6. Celular — barra inferior (decidida, §7 #5; patrón nuevo)

Hoy el menú en el celular es un cajón detrás del botón ☰ (`_mobile_nav_toggle`, `layout.py:593`).
Se propone **evaluar** una barra inferior fija de 4 accesos (Inicio · Por responder · Crear ·
Tu semana) con «Más» abriendo el cajón actual. Es un componente nuevo: va al fundador y, si se
aprueba, a `docs/design-system.md` antes de construirse. *Hipótesis:* el dueño usa Qualify con
una mano entre clientes (`perfil-cliente-pyme.md` §5 pregunta 3); validarlo antes de construir.
Mientras tanto, N12 se cumple con el cajón actual.

## 7. Decisiones del fundador (tomadas el 2026-10-23)

| # | Decisión | Qué se decidió |
|---|---|---|
| 1 | Inicio | **Sí.** Inicio nuevo en `/` («Hoy tienes», «Así te fue», «Para tu primera publicación»); Menciones pasa a Resultados › «Quién habla de ti». |
| 2 | Menú | **Sí, el mapa del §3:** Inicio · Atiende · Publica · Resultados · Tu negocio. «Piezas» se llama **«Por aprobar»**. |
| 3 | Responder | **Un solo «Por responder»** con pestañas Mensajes · Quieren comprar · Comentarios · WhatsApp · Interesados; los chats de WhatsApp se enlazan como pestaña y el módulo WhatsApp conserva respuesta automática y promociones. |
| 4 | «Pronto» | **Vitrina se elimina por completo** (ruta, menú y código). **Creadores y Oportunidades (antes «Señales») se quedan en el menú con «pronto»** (ver N10). |
| 5 | Celular | **Sí, barra inferior** de 4 accesos (Inicio · Por responder · Crear · Tu semana) + «Más». Se documenta primero en `docs/design-system.md` como patrón nuevo y luego se construye. |
| 6 | Marca | **Mínimo de 5 pasos** (negocio, logo, colores, cómo hablas, redes); el resto va a «Mejora tu marca (opcional)». Terminado el mínimo, la app deja de bloquearse. |
| 7 | Invitación | **Opción (b):** antes de empezar se avisa que Qualify es por invitación; con código sigue, sin código deja nombre, negocio y WhatsApp para que lo contacten. |
| 8 | Costo | **El dueño ve «creaciones del mes»** («Te quedan 18 de 30 este mes»), nunca dinero; el costo en dólares solo lo ve el equipo. Cuánto vale una creación lo define `data-scientist-fde`. |
| 9 | Nombre de «Piezas» | **«Por aprobar»** (resuelto con la decisión 2). |
| 10 | Moneda en Venezuela | **Dólares (USD)** por defecto; el dueño puede cambiarla. |
| 11 | Palabras | **«reel (video corto)» e «historia».** «Reel» se usa, con «video corto» como aclaración donde el dueño elige el formato; nunca «story». |
