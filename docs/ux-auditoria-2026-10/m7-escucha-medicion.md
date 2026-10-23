# M7 · Escucha y medición (inicio, menciones, señales, Clarity, vitrina)

`[auditoría UX 2026-10-23 · solo sugerencias, no se tocó código]`
Fuentes leídas: `Qualify/Qualify.py`, `Qualify/components.py`, `Qualify/state.py`,
`Qualify/mentions_paging.py`, `Qualify/signals_page.py`, `Qualify/clarity_page.py`,
`Qualify/clarity_provider.py`, `Qualify/clarity_state.py`, `Qualify/vitrina_page.py`,
`Qualify/vitrina_data.py`, `Qualify/ui/layout.py`, `Qualify/whatsapp_metrics_block.py` (comparación),
`Qualify/auth_state.py`, `Qualify/creative_wizard_pages.py`.

## (a) El trabajo del módulo, en palabras del dueño

1. «Abro la app y quiero saber **cómo me va** esta semana: si me escribieron, si me comentaron, si vino gente.»
2. «Quiero saber **qué tengo que hacer hoy**: a quién responder y qué publicación aprobar.»
3. «Si alguien habla de mi negocio (bien o mal), quiero enterarme y poder hacer algo.»

Hoy la pantalla de inicio (`/`) es una tabla de **menciones** ajenas: no responde ni la 1 ni la 2.

## (b) Hallazgos (ordenados)

### 1. La pantalla de inicio no dice «cómo me va» ni «qué hago hoy» — severidad 1 · esfuerzo L
- **Dónde:** `Qualify/Qualify.py:96-100` (`index` = `topbar` + `stats_row` + `filter_bar` + `mentions_body`),
  `Qualify/Qualify.py:213-217` (`/` → `DashboardState.load_mentions`), `Qualify/auth_state.py:320,329`
  (después de entrar, todo vuelve a `/`).
- **Qué siente el dueño:** «Entro y veo "Menciones: 0 · Positivas 0 · Neutras 0 · Negativas 0". ¿Y mis
  mensajes? ¿Tengo algo pendiente? No sé por dónde empezar.» Un local pequeño recibe pocas o ninguna
  mención con etiqueta (hipótesis, validar con §5 pregunta 5 y 7): la primera pantalla suele ser un vacío.
- **Arreglo sugerido:** una pantalla **Inicio** nueva en `/`, armada solo con primitivas existentes
  (`page_header`, `section`, `stat_card`, `card(interactive=True)`, `empty_state(action=)`), y mover
  Menciones a su propia ruta (ver «Navegación»). Datos que ya existen: `ConversationsState.pending_count`
  (`Qualify/conversations_state.py:366`), métricas de WhatsApp (`whatsapp_metrics_block.py:35-46`),
  totales de menciones (`state.py`); las piezas por aprobar y comentarios sin responder vienen de otros
  módulos (dependencia).
  ```
  ┌ Inicio ───────────────────────────────┐
  │ Hola, Bianki                          │
  │ HOY TIENES                            │
  │ ┌───────────────────────────────────┐ │
  │ │ 3 personas esperan tu respuesta  ›│ │  → /conversations (filtro pendientes)
  │ └───────────────────────────────────┘ │
  │ ┌───────────────────────────────────┐ │
  │ │ 2 publicaciones listas para       │ │
  │ │ que las apruebes                 ›│ │  → /drafts
  │ └───────────────────────────────────┘ │
  │ ┌───────────────────────────────────┐ │
  │ │ 5 comentarios sin responder      ›│ │  → /inbox
  │ └───────────────────────────────────┘ │
  │ ASÍ TE FUE ESTA SEMANA                │
  │ [ 18 te escribieron ] [ 6 hablaron   ]│
  │ [   por WhatsApp    ] [ de ti        ]│
  │ Nada pendiente → empty_state:         │
  │ «Todo al día. ¿Preparamos la próxima  │
  │  publicación?»  [ Crear publicación ] │
  └───────────────────────────────────────┘
  ```
  Título de página: «Inicio»; subtítulo: «Lo que te toca hoy y cómo te fue esta semana».

### 2. Al terminar la identidad de marca, el dueño aterriza en una tabla de menciones vacía — severidad 2 · esfuerzo S (depende del 1)
- **Dónde:** `Qualify/creative_wizard_pages.py:1113` (`_APP_HOME_ROUTE = "/"`), `Qualify/auth_state.py:307-308`.
- **Qué siente el dueño:** «Acabo de armar mi marca… ¿y ahora? Esto dice "Aún no hay menciones".»
- **Arreglo:** con el Inicio del hallazgo 1, el primer ingreso muestra un único paso siguiente:
  `empty_state("wand-sparkles", "Tu marca está lista", "Ahora crea tu primera publicación con la foto de un producto.", action=rx.button("Crear mi primera publicación"))` → `/create`. Si no hay cuentas conectadas, el paso es «Conecta tu Instagram para publicar desde aquí» → `/connections`.

### 3. Clarity: el dueño no puede configurarla ni entenderla — severidad 1 · esfuerzo L
- **Dónde:** `Qualify/clarity_page.py:39-43` (título «Clarity», «vía Microsoft Clarity»), `:60-66`
  («token de la API Data Export (Clarity → Settings → Data Export → Generate new API token)»), `:69,75`
  (placeholders «ID de proyecto», «Token de la Data Export API»), `:129` («actualizaciones restantes hoy»),
  `:329-331` («llamadas diarias que permite Microsoft… último snapshot guardado»).
- **Qué siente el dueño:** «¿Qué es Clarity? ¿Qué es un token? No tengo eso.» Muchos negocios del
  segmento no tienen página web propia (hipótesis, §5 pregunta 5). Instalar Clarity exige tocar el código
  del sitio: es trabajo del equipo, no del dueño.
- **Arreglo:** separar dos cosas:
  - **Configuración** (la hace el operador): mover el formulario a Configuración o Conexiones, con
    pasos cortos:
    ```
    ① ¿Tu negocio tiene página web?   (•) Sí  ( ) No → «No hace falta: tus redes ya cuentan.»
    ② Pídele al equipo de Qualify que la conecte  [ Escribir al equipo ]
       (o, para el operador: Código del proyecto [____]  Clave de acceso [____]  [ Guardar ])
    ```
  - **Lectura** (la ve el dueño): título «Tu página web», subtítulo «Cuántas personas la visitaron y
    dónde se trabaron». Sin selector de «Ventana»/«Dimensión», sin presupuesto visible: se actualiza
    sola una vez al día (el límite de 10 por día lo gestiona el sistema).
  ```
  ┌ Tu página web ─────────────────────────┐
  │ Últimos 3 días                         │
  │ [ 240 visitas ] [ 190 personas ]       │
  │ QUÉ ARREGLAR PRIMERO                   │
  │ ▲ Alta  En /reservas la gente toca un  │
  │         botón que no responde.         │
  │         [ Avisar al equipo ]           │
  │ ✓ Lo demás está bien.                  │
  └────────────────────────────────────────┘
  ```

### 4. Clarity habla en inglés y en jerga de analítica — severidad 2 · esfuerzo M
- **Dónde:** `Qualify/clarity_state.py:49` (opciones `URL`, `Device`, `OS`, `Browser`, `Source`, `Channel`),
  `Qualify/clarity_provider.py:28` («Rage clicks»), `:46` («Errores de JavaScript»), `:58` («Scroll excesivo»),
  `:185` («Sesiones bot»), `Qualify/clarity_page.py:111` («días · Dimensión:»), `:274` («Snapshot del»),
  `:359` («Datos crudos por métrica»), `:233` («Ver grabaciones en Clarity»).
- **Qué siente el dueño:** «¿Rage clicks? ¿Scroll? ¿Bot?»
- **Arreglo (cadenas exactas):**
  | Hoy | Propuesto |
  |---|---|
  | Rage clicks | Toques repetidos con enojo |
  | Clics muertos | Toques en cosas que no hacen nada |
  | Clics con error | Toques que rompieron la página |
  | Errores de JavaScript | Fallas de la página |
  | Rebotes rápidos | Entraron y se fueron enseguida |
  | Scroll excesivo | Bajaron mucho buscando algo |
  | Sesiones / Sesiones bot / Usuarios únicos / Tiempo activo | Visitas / Visitas automáticas (no son personas) / Personas / Tiempo que se quedaron |
  | Snapshot del … | Datos del … |
  | Datos crudos por métrica | Ver todos los números |
  | URL / Device / OS / Browser / Source / Channel | Página / Dispositivo / Sistema / Navegador / De dónde llegaron / Canal (o quitar el selector, hallazgo 3) |
  | «Prioridad alta para el desarrollador del sitio» (`clarity_provider.py:49`) | «Avísale a quien te hizo la página: esto es urgente.» |

### 5. Menciones: ves lo que pasó, pero no puedes hacer nada con eso — severidad 2 · esfuerzo M
- **Dónde:** `Qualify/components.py:99-116` (`stats_row`: tarjetas no pulsables), `:222-239`
  (la única acción es «Ver», un enlace externo), `:322-367` (`mention_card`).
- **Qué siente el dueño:** «Dice que tengo 2 negativas. ¿Cuáles? ¿Qué hago?»
- **Arreglo:** (1) las tarjetas Positivas/Neutras/Negativas como `card(interactive=True)` que aplican el
  filtro de sentimiento; (2) en cada mención negativa, una línea de ayuda y la acción clara, sin prometer
  respuesta automática: texto «Esta persona no quedó contenta. Respóndele desde Instagram.» + botón
  «Ver y responder» (mismo `permalink`); (3) «Ver» → «Ver en Instagram/Facebook» según `platform`.
  ```
  ┌──────────────────────────────────────┐
  │ 12 oct · Instagram · Comentario  ● Negativa
  │ @cliente: «La porción vino chiquita» │
  │ Esta persona no quedó contenta.      │
  │ [ Ver y responder en Instagram ↗ ]   │
  └──────────────────────────────────────┘
  ```

### 6. Vitrina: una demo de otro negocio aparece en el menú de todos — severidad 2 · esfuerzo S
- **Dónde:** `Qualify/ui/layout.py:89` (`("Vitrina", "store", "/vitrina", True)` en «Negocio» para todo
  negocio), `Qualify/vitrina_page.py:49-54` (título «Korner Club», insignia «demo»), `:103`
  («Reservar visita» deshabilitado), `Qualify/vitrina_data.py:23-26`, voseo («elegí uno», `vitrina_page.py:124`).
- **Qué siente el dueño de un shawarma:** «¿Korner Club? ¿Locales disponibles? Esto no es mío.»
- **Arreglo:** sacar «Vitrina» del menú lateral y dejarla accesible solo por enlace directo (como
  `/design`), o mostrarla solo al negocio del microcentro. Si se mantiene: «Ticket alto/medio/bajo»
  (`vitrina_page.py:328-330`) → «Precio alto/medio/bajo»; la columna «Dist.» → «Distancia».

### 7. Señales: la pantalla habla de «placeholder», «Fase 3» y «roadmap» — severidad 2 · esfuerzo S
- **Dónde:** `Qualify/signals_page.py:22-35`; la ruta sigue viva (`Qualify/Qualify.py:276-282`) aunque
  ya nada enlaza a ella (`creative_wizard_pages.py:1106-1109`) y el menú la muestra como «Señales · pronto»
  (`layout.py:66`).
- **Qué siente el dueño:** «¿Placeholder? ¿Fase 3? ¿Detectores de oportunidad?»
- **Arreglo:** título «Avisos de oportunidad»; subtítulo «Te avisaremos cuando alguien pregunte por
  precios o quiera trabajar contigo»; `empty_state("radar", "Todavía no hay avisos", "Estamos preparando
  esta parte. Mientras tanto, revisa quién te escribió.", action=rx.button("Ver mis conversaciones"))`
  → `/conversations`. Sin la palabra «placeholder» ni «roadmap». En el menú, «Pronto: avisos de
  oportunidad» en lugar de «Señales».

### 8. Clarity se sale de la pantalla en el celular y los campos no tienen etiqueta — severidad 3 · esfuerzo S
- **Dónde:** `Qualify/clarity_page.py:72` (`width="14rem"`), `:79` (`width="22rem"` = 352 px: con 16 px de
  margen a cada lado no cabe en 360 px), `:103-118` (los textos «Ventana:» y «días · Dimensión:» se parten
  al envolver).
- **Arreglo:** `width="100%"` con `max_width` en escritorio; cada campo con su `rx.text` visible encima
  («Código del proyecto», «Clave de acceso») y un ejemplo debajo; el placeholder no es etiqueta.

### 9. Menciones: información que solo se ve al pasar el mouse — severidad 3 · esfuerzo S
- **Dónde:** `Qualify/components.py:191-201` («Sin análisis» con el motivo en tooltip), `:238`
  (enlace «—» con el motivo en tooltip), `:246-249` (nota del autor en tooltip), `:300-305` (nota de
  me gusta en tooltip), `:347` (`q-clamp-3`: en el celular el texto largo se corta a 3 líneas sin «Ver más»).
- **Qué siente el dueño (con el pulgar):** «Dice "Sin análisis" y no sé por qué; el comentario está cortado.»
- **Arreglo:** en `mention_card`, el motivo como texto pequeño visible («Sin texto para leer»,
  «No pudimos leerla»); en lugar de «—», «Sin enlace»; un botón «Ver más» que quite el recorte.

### 10. Botones demasiado chicos y cuatro filtros en una fila — severidad 3 · esfuerzo S
- **Dónde:** `Qualify/components.py:415-426` y `:432-440` (paginador `size="1"`, ~24 px), `:163-170`
  (actualizar `size="2"`, ~32 px), `:119-153` (cuenta + periodo + origen + sentimiento + actualizar,
  sin etiquetas visibles).
- **Arreglo:** en celular, flechas `size="3"` (≥ 44 px); visible solo «Periodo»; el resto detrás de un
  botón «Más filtros» (`drawer` existente, pantalla completa en móvil). Cada `select` con etiqueta visible.
  ```
  [ Últimos 14 días ▼ ]  [ Más filtros (2) ]  [ ↻ ]
  ```

### 11. Textos en inglés o sin «qué hacer ahora» — severidad 3 · esfuerzo S
- `Qualify/components.py:398` «Likes» → «Me gusta».
- `Qualify/components.py:93-96` subtítulo «Publicaciones y comentarios de tus redes sociales que
  mencionan tu cuenta.» → «Lo que la gente publica o comenta cuando etiqueta a tu negocio.»
- `Qualify/state.py:72` «No hay una sesión activa.» → «Tu sesión se cerró. Vuelve a entrar para ver tus menciones.»
- `Qualify/state.py:73` «No se pudieron cargar las menciones.» → «No pudimos traer tus menciones. Recarga la página en unos minutos.»
- `Qualify/components.py:515` «La lista cambió desde la última carga.» → «Llegaron menciones nuevas.» (botón «Ver»).
- `Qualify/mentions_paging.py:80` «Total de N páginas» → «N páginas».
- `Qualify/clarity_page.py:54-55` «conectado»/«sin configurar» → «Conectada»/«Falta conectar» (mayúscula inicial, §7.1).

### 12. Títulos de pestaña con nombres de herramienta — severidad 5 · esfuerzo S
- **Dónde:** `Qualify/Qualify.py:216` «Qualify · Menciones», `:273` «Qualify · Clarity», `:281`
  «Qualify · Señales», `:460` «Qualify · Vitrina de locales».
- **Arreglo:** «Qualify · Inicio» (nuevo `/`), «Qualify · Quién habla de ti» (menciones), «Qualify · Tu
  página web» (Clarity), «Qualify · Avisos (pronto)» (señales). El título de pestaña = `page_header`.

## (c) Navegación

**Hoy:**
```
Menú lateral
├─ Conexiones · WhatsApp
├─ ESCUCHAS: Menciones (/) · Interacciones · Conversaciones · Creadores (pronto) · Señales (pronto)
├─ PUBLICAS: Crear pieza · Piezas · Planificador · Publicar
├─ Leads
└─ NEGOCIO: Clarity · Vitrina · Brand Kit · Catálogo · Configuración
```
- `/` es Menciones: el lugar donde aterriza **todo** (login, fin del Brand Kit, enlaces de auth) es una
  lista de terceros, no un punto de partida.
- Ninguna pantalla del módulo lleva al siguiente trabajo: Menciones termina en «Ver» (sale de Qualify);
  Clarity termina en «Ver grabaciones en Clarity» (sale de Qualify); Señales y Vitrina son callejones sin
  salida (la demo tiene «Reservar visita» deshabilitado).
- La medición está repartida en tres sitios sin relación: menciones en `/`, la página web en «Negocio →
  Clarity», WhatsApp dentro de `/whatsapp` (`whatsapp_metrics_block.py`). El dueño no tiene un solo lugar
  para «¿cómo me va?».
- «Negocio» mezcla medición (Clarity), una demo (Vitrina), identidad (Brand Kit, Catálogo) y cuenta
  (Configuración).
- Las páginas son planas (sin pestañas ni subrutas): no hace falta «Volver», pero tampoco hay «siguiente paso».

**Propuesta (dentro del sistema de diseño: mismo menú, mismas primitivas):**
```
Menú lateral
├─ Inicio (/)                 ← NUEVO: «Hoy tienes» + «Así te fue» (hub)
├─ Conexiones · WhatsApp
├─ ESCUCHAS: Conversaciones · Comentarios (/inbox) · Quién habla de ti (/menciones)
├─ PUBLICAS: …
├─ Resultados (/resultados)   ← reúne: Redes · WhatsApp · Tu página web (?tab=, como /whatsapp)
└─ NEGOCIO: Tu marca · Tus productos · Configuración   (Vitrina fuera del menú)
```
Regla de navegación propuesta para todo el producto (para la guía global):
1. **Inicio es el centro**: cada tarjeta de «Hoy tienes» lleva directo a la lista ya filtrada donde se
   actúa, y cada pantalla de trabajo, al quedar vacía, devuelve a Inicio («Todo al día · Volver al inicio»).
2. **Toda lista termina en un siguiente paso dentro de Qualify** (`empty_state(action=)`): menciones →
   conversaciones; página web → avisar al equipo; sin pendientes → crear publicación.
3. **Toda cifra de resumen es pulsable** y lleva a lo que cuenta (`card(interactive=True)`).
4. **Salir de Qualify se dice**: «Ver en Instagram ↗», nunca un «Ver» a secas.
5. **Título de pestaña = título de la página**, en palabras del dueño.
6. `/` se mantiene como ruta del Inicio; `/menciones` nueva (y el antiguo `/` deja de ser Menciones sin
   romper enlaces, porque nadie enlaza a Menciones con parámetros).

## (d) Historias propuestas

**Grupo A — Inicio (hub)**

1. **Como dueño, quiero abrir la app y ver qué tengo pendiente hoy, para resolverlo en dos minutos sin buscar en el menú.**
   - Al entrar (login o fin de la identidad de marca) se abre «Inicio» en `/`.
   - Muestra hasta 3 tarjetas pulsables: personas que esperan respuesta, publicaciones por aprobar,
     comentarios sin responder; cada una abre la lista ya filtrada.
   - Sin pendientes, muestra «Todo al día» con el botón «Crear publicación».
   - Funciona a 360 px en una columna, objetivos ≥ 44 px.
2. **Como dueño, quiero ver cómo me fue esta semana en números simples, para saber si vale la pena lo que hago en redes.**
   - Muestra «te escribieron» (WhatsApp + Instagram Direct), «comentaron», «hablaron de ti» de los últimos 7 días.
   - Cada cifra lleva a su detalle; sin datos dice qué conectar («Conecta tu Instagram para ver esto»).
   - Ninguna palabra de la lista prohibida (`qualify-ux` §3). Qué cifras importan: hipótesis, §5 pregunta 7.
3. **Como dueño nuevo, quiero que al terminar mi marca la app me diga el siguiente paso, para no quedarme sin saber qué hacer.**
   - Sin cuentas conectadas → «Conecta tu Instagram para publicar desde aquí».
   - Con cuenta y sin publicaciones → «Crea tu primera publicación con la foto de un producto».
   - El paso desaparece cuando ya se hizo.

**Grupo B — Quién habla de ti (menciones)**

4. **Como dueño, quiero ver solo las menciones malas con un toque y saber qué hacer, para que ningún cliente molesto quede sin respuesta.**
   - Las tarjetas Positivas/Neutras/Negativas filtran la lista al tocarlas.
   - Cada mención negativa muestra «Esta persona no quedó contenta» y «Ver y responder en Instagram ↗».
   - Ningún texto sugiere que Qualify responde solo.
5. **Como dueño en el celular, quiero leer cada mención completa y filtrar sin pelear con botones chicos, para usarlo con una mano.**
   - Sin información solo en tooltip/hover; «Ver más» para textos largos.
   - En móvil: solo «Periodo» visible, el resto en «Más filtros»; paginador ≥ 44 px.
   - «Likes» → «Me gusta»; errores con siguiente paso (cadenas del hallazgo 11).

**Grupo C — Tu página web (Clarity)**

6. **Como dueño con página web, quiero saber cuántas personas la visitaron y qué arreglar primero, sin entender de analítica.**
   - Título «Tu página web»; vocabulario de la tabla del hallazgo 4; sin «token», «snapshot», «dimensión».
   - Se actualiza sola una vez al día; no se muestra el cupo de llamadas.
   - Cada problema «alto» tiene el botón «Avisar al equipo».
   - Sin página web configurada, explica «No hace falta: tus redes ya cuentan» y no muestra el formulario.
7. **Como operador, quiero conectar Clarity desde Configuración con campos claros, para que el dueño nunca vea claves.**
   - El formulario sale de la pantalla de lectura y va a Configuración/Conexiones.
   - Campos con etiqueta visible y ancho 100 % (cabe en 360 px); la clave se guarda cifrada como hoy.

**Grupo D — Limpieza del menú**

8. **Como dueño, quiero que el menú solo me muestre cosas de mi negocio en mis palabras, para no perderme.**
   - «Vitrina» sale del menú (enlace directo solamente o solo para el microcentro).
   - «Señales» se muestra como «Pronto: avisos de oportunidad»; su pantalla no dice «placeholder», «Fase» ni «roadmap» y ofrece «Ver mis conversaciones».
   - Títulos de pestaña iguales al título de página (hallazgo 12).

> Nota de coherencia para el PO: `docs/design-system.md` §7.2 dice usar «lead», mientras `qualify-ux` §3
> lo prohíbe («cliente interesado»). No es de este módulo, pero afecta al menú (ítem «Leads»).
