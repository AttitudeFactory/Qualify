# Auditoría de experiencia — Módulo 4: Planificar y publicar

`[2026-10-23 · auditoría UX, solo sugerencias, no se editó código]`
Pantallas: `/planner` (`Qualify/planner_page.py`, `Qualify/planner_drawer.py`, `Qualify/planner_vm.py`),
`/publish` (`Qualify/publishing_page.py`, `Qualify/publishing_state.py`, `Qualify/publish_tips.py`,
`Qualify/trending_panel.py`, `Qualify/post_card.py`), flujo Historias dentro de `/publish?flow=stories`
(`Qualify/stories_page.py`, `Qualify/stories_state.py`). Menú: `Qualify/ui/layout.py:69-82`.

## (a) El trabajo del módulo, en palabras del dueño

1. «Quiero dejar listas las publicaciones de la semana: elegir las que ya aprobé y decir qué día y a qué hora salen.»
2. «Quiero ver de un vistazo qué sale hoy y esta semana, y si algo quedó sin salir, saber qué hacer.»
3. «A veces solo quiero subir una foto o un video que tengo en el teléfono y publicarlo ya, sin que nada salga sin que yo lo vea.»

## (b) Hallazgos (ordenados)

Severidad: 1 = no puede terminar · 2 = lenguaje de funcionalidad o palabras prohibidas · 3 = demasiados datos en un paso · 4 = accesibilidad/móvil · 5 = pulido.

### H1 · Sev 1 · Tres puertas para un mismo trabajo, y ninguna lleva a la siguiente — M
**Dónde:** `Qualify/ui/layout.py:76-80` (menú «Crear pieza · Piezas · Planificador · Publicar»); `Qualify/creative_state.py:5239` (toast «POST aprobado: ya puedes programarlo en el Planificador.» sin enlace); `Qualify/publishing_page.py:557-561`.
**El dueño diría:** «Ya aprobé mi publicación… ¿y ahora? ¿La publico en Publicar o en Planificador? En Publicar me pide subir el archivo otra vez.»
**Problema:** `/publish` sube archivos sueltos del teléfono y no ofrece las piezas aprobadas; `/planner` sí las usa. Tras aprobar en Piezas solo aparece un toast que desaparece, sin botón. Son dos caminos que compiten y el dueño no sabe cuál es «el» camino.
**Arreglo sugerido:** un solo recorrido «Crear → Aprobar → Programar», con el siguiente paso siempre como botón principal:
- Tras «Aprobar» en Piezas: tarjeta fija (no solo toast) «Lista para salir. ¿Cuándo la publicamos?» con botones **«Elegir día y hora»** (abre el panel de programar con esa pieza ya marcada, `/planner?asignar=<id>`) y «Publicar ahora».
- «Publicar ahora» en el Planificador = programar a la hora actual (mismo panel, preselección «Ahora»), así `/publish` deja de ser el único sitio para lo inmediato.
- `/publish` se queda para «Subir algo de mi teléfono» (ver H5).
```
Piezas › Combo Vecino                     ✓ Aprobada
┌──────────────────────────────────────────────┐
│ Lista para salir. ¿Cuándo la publicamos?      │
│ [ Elegir día y hora ]   ( Publicar ahora )    │
└──────────────────────────────────────────────┘
```

### H2 · Sev 1 · En el teléfono la semana arranca vacía y lo que hay que programar está escondido — S
**Dónde:** `Qualify/planner_page.py:1149` + `show_unscheduled` cerrado por defecto (docstring l. 5-6); `planner_page.py:629-631` (vacío «Nada planificado esta semana / Asigna un POST a un día, una hora y una cuenta.»).
**El dueño diría:** «No tengo nada planificado… pero yo aprobé tres. ¿Dónde están?»
**Problema:** el panel «Sin programar» está cerrado y el estado vacío no tiene botón; en el teléfono, sin arrastrar y soltar, el único camino es descubrir el botón «Sin programar» de la barra.
**Arreglo sugerido:** si hay piezas aprobadas sin fecha, el estado vacío muestra el número y el botón principal (`empty_state`, botón `solid`):
```
┌────────────────────────────────────┐
│  📅  Tu semana está libre           │
│  Tienes 3 publicaciones aprobadas  │
│  esperando día y hora.             │
│  [ Programar mis 3 publicaciones ] │
└────────────────────────────────────┘
```
Texto exacto: título «Tu semana está libre», cuerpo «Tienes {n} publicaciones aprobadas esperando día y hora.», botón «Programar mis {n} publicaciones» (abre el panel con todas preseleccionadas). Si `n = 0`: «Todavía no tienes publicaciones aprobadas.» + botón «Crear una publicación» → `/create`. En escritorio, abrir «Sin programar» por defecto cuando `n > 0`.

### H3 · Sev 2 · «POST», «Caption», «Stories», «Cold/Hot», «Likes», «Ads» en todo el módulo — S
**Dónde (muestras):** `planner_page.py:92, 631, 660, 706, 718`; `planner_drawer.py:318-324, 341, 1641, 1745`; `planner_vm.py:136, 1351-1356, 1376-1381, 1277` («Reel»); `publishing_page.py:343, 345, 518-519, 559-560`; `stories_page.py:104, 174, 236, 390`; `trending_panel.py:223, 241, 258`.
**El dueño diría:** «¿Qué es Cold? ¿Qué es un caption? ¿“Puntaje del vendor”?»
**Arreglo sugerido (reemplazos exactos):**
| Hoy | Sugerido |
|---|---|
| «POST» / «POSTs» (todas) | «publicación» / «publicaciones» |
| «Ver POST» / «Abrir en Piezas» | «Ver publicación» |
| «Crear POST» | «Crear una publicación» |
| «Rechazar POST» | «No la quiero» (o «Rechazar publicación») |
| «El POST» (título de sección) | «Lo que se publica» |
| «Caption» / «Escribe el caption...» | «Texto de la publicación» / «Ej.: Hoy combo vecino a mitad de precio hasta las 9 p. m.» |
| «Stories» / «Story» | «Historias» / «historia» |
| «Cold» · «Probado: ya funcionó, contenido evergreen.» | «Ya probada» · «Ya salió antes y funcionó: puedes repetirla.» |
| «Hot» · «Nuevo: todavía en prueba.» | «Nueva» · «Todavía no ha salido en tus redes.» |
| Metas «Likes / Vistas / Ads / Alcance… / pauta pagada» | «Me gusta / Que la vea más gente / Para anunciar pagando» |
| «Feed 4:5» (`test_planner_ui.py:1174`, `frame_shape`) | «Publicación (vertical)» |
| «Puntaje de tendencia del vendor:» | quitar la línea (no le sirve al dueño) |
| «Escuchar preview» | «Escuchar» |
| «Buscar en Meta» | «Buscar en Instagram» |
| «Reel» | «video corto» — **hipótesis**: validar si el dueño ya dice «reel» (`perfil-cliente-pyme.md` §5 pregunta 4) |

### H4 · Sev 2 · Errores con palabras internas y sin siguiente paso — S
**Dónde:** `Qualify/publishing_state.py:76` («No hay ningún tenant activo…»), `:79` («El almacenamiento (R2) todavía no está configurado en este entorno.»), `:94` («No se pudo consultar el estado de la publicación.»), `:89-90` («JPEG… PNG, WebP, GIF y HEIC no son compatibles»).
**El dueño diría:** «¿Tenant? ¿R2? ¿Se publicó o no?»
**Arreglo sugerido:**
- l. 76 → «No encontramos tu negocio en esta sesión. Cierra sesión y vuelve a entrar.»
- l. 79 → «No podemos subir archivos en este momento. Inténtalo en unos minutos; si sigue, escríbenos.»
- l. 94 → «No sabemos todavía si se publicó. Revisa tu Instagram en unos minutos antes de volver a intentarlo, para no publicarlo dos veces.»
- l. 89-90 → «Esta foto no se puede usar tal cual. Desde tu celular, compártela como “JPG” o haz una captura de pantalla y súbela.» (**hipótesis** sobre cómo lo resuelve el dueño, §5 pregunta 6)

### H5 · Sev 3 · «Publicar» mezcla cuenta, archivos, texto, historia, música y tendencias en una sola pantalla — M
**Dónde:** `publishing_page.py:452-475` (Cuenta → Contenido → Caption → Publicar en una tarjeta), `:564-581` (+ panel «Tendencias e inspiración» debajo + «Antes de publicar» al lado); `stories_page.py:335-370` (Publicar «o» Abrir en Instagram).
**Problema:** tres dominios (qué, dónde, cómo se ve) más un panel de tendencias ajeno a la tarea. La cuenta se elige primero, antes de saber qué se publica. Datos técnicos («MP4, MOV o JPEG · hasta 300 MB (video) / 8 MB (imagen)», l. 261) en la ruta principal.
**Arreglo sugerido — pasos cortos («Subir algo de mi teléfono»):**
```
① ¿Qué vas a publicar?          ② ¿Dónde sale?                 ③ Revisa y publica
[ + Elegir fotos o video ]      (•) Publicación en tu perfil   [miniatura]
  📷 📷 🎬  (hasta 10)          ( ) Historia (24 h)            «Sale ahora en Instagram
                                Cuenta: @bianki ✓ (única,      @bianki como publicación»
[ Siguiente ]                    preseleccionada)              Texto: [___________]
                                [ Atrás ] [ Siguiente ]        [ Atrás ] [ Publicar ahora ]
                                                               ( ¿Música? Ábrela en Instagram )
```
- Paso 2 sustituye el selector «Publicaciones | Stories» (l. 518-519): el destino es una pregunta, no un modo de la pantalla.
- Cuenta preseleccionada si hay una sola; el texto se pide solo para «Publicación».
- Formatos y tamaños, solo en el error si algo no sirve; «Tendencias e inspiración» detrás de «Ideas para tu próxima publicación» (enlace), fuera del flujo.

### H6 · Sev 3 · El paso «Programación» pide 8 datos por pieza — M
**Dónde:** `planner_drawer.py:753-877` (`_plan_card`): Fecha, Hora (+ a. m./p. m.), Salida, Destino, Canales, Campaña, Etiquetas, Repetir (Días, Durante); `:1203` «Metas de esta planificación» en el paso de confirmación; `:877` «Usar canales, etiquetas y campaña en todas».
**El dueño diría:** «Solo quería decir “el jueves a las 7”.»
**Arreglo sugerido:** el camino principal solo pide **día y hora**; lo demás se rellena con lo que Qualify ya sabe (cuenta única, destino de la pieza, campaña actual) y va detrás de «Más opciones» por pieza.
```
Paso 2 de 3 · ¿Cuándo sale?
┌────────────────────────────────────────┐
│ [img] Combo Vecino · Publicación        │
│ Día  [ Jue 30 ▼ ]   Hora [ 7:00 p. m. ▼]│
│ Sale en @bianki (Instagram)             │
│ › Más opciones (cuenta, repetir,        │
│   campaña, etiquetas)                   │
└────────────────────────────────────────┘
[ Atrás ]                      [ Siguiente ]
```
Las «Metas» pasan a «Más opciones» o a la ficha de la publicación (ya existen en `planner_drawer.py:1660-1670`), no en la confirmación. Sugerir «Mejores horas» precargadas: **hipótesis**, depende de datos que no hay aún.

### H7 · Sev 2 · El Planificador puede rechazar pero no aprobar — M
**Dónde:** `planner_drawer.py:1740-1750` («Rechazar POST» si está en revisión); `planner_state.py:779` (`reject_post_from_detail`, no existe `approve`); estados «En revisión» en `planner_vm.py:132`.
**El dueño diría:** «Aquí veo que está “En revisión”, pero para aprobarla tengo que irme a Piezas y buscarla.»
**Arreglo sugerido:** en la ficha de una publicación en revisión, dos botones iguales: «Aprobar» (sólido) y «No la quiero» (contorno rojo), con el texto «Nada sale sin tu aprobación. Si la apruebas, sale el {día} a las {hora}.» Esto hace del Planificador la «semana para aprobar» que pide `qualify-ux` §2.

### H8 · Sev 2 · Título y subtítulo hablan de la herramienta — S
**Dónde:** `planner_page.py:1127-1128` («Planificador» / «Qué se publica, cuándo y en qué cuenta.»); `Qualify.py:432` (`title="Qualify · Planificador"`); `publishing_page.py:558-560` («Publica de inmediato… una publicación (imagen, reel o carrusel) o una Story»); `Qualify.py:248`, `:446` (`title="Qualify · Stories"`); menú `layout.py:78, 80`.
**Arreglo sugerido:**
- Planificador: título «Tu semana», subtítulo «Tus publicaciones de la semana, listas para aprobar y programar.»; pestaña `Qualify · Tu semana`; menú «Tu semana».
- Publicar: título «Publicar ahora», subtítulo «Sube una foto o un video de tu teléfono y publícalo en tu Instagram.»; pestaña `Qualify · Publicar ahora`.
- Redirección `/stories`: `title="Qualify · Historias"`.

### H9 · Sev 2 · «Publicación automática activa» contradice «asistido, nunca autónomo» en la lectura del dueño — S
**Dónde:** `planner_drawer.py:1601-1602` («Publicación automática activa: un evento aprobado sale a su hora (se revisa cada minuto).»), `:1619-1620` («El servicio de publicación automática no está disponible…»), `:1613-1614` («los eventos se publicarán…»).
**El dueño diría:** «¿Automática? ¿Va a publicar cosas sola?»
**Arreglo sugerido:** «Aprobada por ti: sale sola el {día} a las {hora}.» · indisponible: «Ahora mismo no podemos publicar a la hora programada. Tus publicaciones esperan; te avisamos cuando vuelva.» · sin cuenta: «Conecta tu Instagram en Conexiones para que esta publicación pueda salir.» Cambiar «evento» por «publicación» en todo el texto visible.

### H10 · Sev 4 · Información solo al pasar el mouse y botones pequeños — S
**Dónde:** `planner_page.py:275-280` (`hover_card` con todo el detalle del chip; «Clic para ver y gestionar», l. 196); `:421-430` («+» de la celda solo con hover); `:605`, `:665` («Asignar» `size="1"`, ~24 px); `:77-86`, `:798-806`, `:882` (icon buttons `size="1"`); `publishing_page.py:256` («Arrastra… o haz clic»).
**Arreglo sugerido:** en móvil todo ya pasa por la Lista, bien; asegurar ≥ 44 px en «Asignar», «⋯», flechas de semana y cerrar panel (`size="3"` en móvil vía `rx.breakpoints`). Textos: «Toca para ver y cambiar»; «Toca para elegir fotos o videos de tu teléfono» (en escritorio puede seguir diciendo «arrastra»).

### H11 · Sev 4 · Barra del Planificador con 6 controles avanzados en la ruta principal — S
**Dónde:** `planner_page.py:791-851` (semana, Hoy, Sin programar, filtro de cuentas, Etiquetas con crear/borrar, zona horaria con buscador).
**Problema:** a 360 px la barra se parte en tres líneas antes de ver la semana; zona horaria y etiquetas son cosas del operador (persona secundaria, perfil §3).
**Arreglo sugerido:** dejar visibles «‹ Semana ›», «Hoy» y «Por programar ({n})»; mover cuentas, etiquetas y zona horaria a un botón «Filtros». La zona horaria por defecto es la del negocio (ya existe) y solo se cambia desde ahí.

### H12 · Sev 5 · Después de publicar no hay a dónde ir — S
**Dónde:** `publishing_state.py:146-149` (toast «¡Publicado correctamente!», sin enlace, por límite técnico documentado); `stories_state.py:101` («¡Story publicada en Instagram!»).
**Arreglo sugerido:** en vez de solo toast, un `callout` de éxito persistente en el paso final: «Listo, ya está en tu Instagram.» + botones «Ver mi semana» (`/planner`) y «Publicar otra». Historias: «Listo, tu historia ya está en Instagram (se ve 24 horas).»

## (c) Navegación

### Estructura actual
```
Menú «Publicas»:  Crear pieza (/create) · Piezas (/drafts) · Planificador (/planner) · Publicar (/publish)
/drafts/[id]   — Aprobar → toast «ya puedes programarlo en el Planificador» (sin enlace)  ✗ callejón
/planner       — Lista | Calendario (solo escritorio); «Sin programar» (panel cerrado);
                 «Nueva publicación» → drawer 3 pasos (Contenido · Programación · Confirmar)
                 ficha del evento → «Ver POST» / «Abrir en Piezas» (sale del módulo, sin volver)
                 «Crear pieza» en vacío del panel → /create (no vuelve al planner al aprobar) ✗
/publish       — selector «Publicaciones | Stories» (?flow=stories) + Tendencias debajo
                 Publicar → toast → formulario vacío ✗ sin siguiente paso
/stories       — redirección a /publish?flow=stories
Títulos de pestaña: «Qualify · Planificador», «Qualify · Publicar», «Qualify · Stories», «Qualify · Piezas».
```
Problemas: dos caminos paralelos para publicar (planificado vs. subir archivo); aprobar no lleva a programar; programar no permite aprobar; publicar ahora no vuelve a la semana; nombres de herramienta en menú y pestañas.

### Estructura propuesta (patrón «el siguiente paso es siempre el botón principal»)
```
Menú «Publicas»:
  Crear publicación (/create)
  Por aprobar (/drafts)            ← badge con n en revisión
  Tu semana (/planner)             ← badge con n aprobadas sin día
  Publicar ahora (/publish)

Recorrido principal (una dirección, cada pantalla termina con el botón a la siguiente):
  Crear → [Enviar a aprobar] → Por aprobar → [Aprobar] → «¿Cuándo la publicamos?»
        → [Elegir día y hora] → Tu semana (panel con la pieza ya elegida) → [Programar]
        → vuelve a Tu semana con la publicación resaltada y un callout «Sale el jue 30, 7:00 p. m.»
  Atajo: [Publicar ahora] desde la pieza aprobada = mismo panel con «Ahora».

Publicar ahora (/publish): pasos ① Qué ② Dónde (Publicación | Historia) ③ Revisa y publica
        → éxito: [Ver mi semana] · [Publicar otra]

Volver: toda ficha abierta desde Tu semana vuelve a Tu semana («‹ Tu semana»), con la misma
semana y vista; un enlace a la pieza lleva `?volver=/planner`.
URL compartible: /planner?asignar=<post_id>, /publish?destino=historia (reemplaza ?flow=stories,
manteniendo la redirección vieja).
Pestañas: «Qualify · Por aprobar», «Qualify · Tu semana», «Qualify · Publicar ahora», «Qualify · Historias».
```

## (d) Historias de usuario propuestas

### Grupo A — Un solo recorrido de aprobar a publicar
1. **Como dueño, quiero que al aprobar una publicación me pregunte cuándo sale, para no tener que buscar a dónde ir después.**
   - Tras «Aprobar», se muestra una tarjeta fija «Lista para salir. ¿Cuándo la publicamos?» con «Elegir día y hora» y «Publicar ahora».
   - «Elegir día y hora» abre el panel de programar de Tu semana con esa publicación ya elegida (paso 2).
   - Ninguna acción publica sin un toque del dueño en «Programar» o «Publicar ahora».
2. **Como dueño, quiero aprobar o descartar una publicación desde mi semana, para revisar todo en un solo lugar.**
   - La ficha de una publicación «En revisión» muestra «Aprobar» y «No la quiero».
   - Al aprobar, el estado cambia a «Aprobada» sin recargar y el texto dice cuándo sale.
   - El texto nunca dice que Qualify publica por su cuenta.
3. **Como dueño, quiero ver en el teléfono cuántas publicaciones tengo esperando día y hora, para programarlas de una vez.**
   - Si hay aprobadas sin fecha, el estado vacío y la barra muestran «Por programar ({n})».
   - «Programar mis {n} publicaciones» abre el panel con todas preseleccionadas.
   - Funciona a 360 px sin arrastrar y soltar.

### Grupo B — Programar en pocos toques
4. **Como dueño, quiero programar una publicación eligiendo solo día y hora, para terminar en menos de 2 minutos.**
   - El paso «¿Cuándo sale?» muestra solo Día y Hora; cuenta y destino vienen precargados.
   - Cuenta, repetir, campaña, etiquetas y metas quedan detrás de «Más opciones».
   - El paso final resume en una frase: «Sale el jueves 30 a las 7:00 p. m. en Instagram @bianki».

### Grupo C — Publicar ahora desde el teléfono
5. **Como dueño, quiero subir una foto o un video de mi teléfono y publicarlo en tres pasos, para no perderme entre opciones.**
   - Pasos: «¿Qué vas a publicar?» → «¿Dónde sale?» (Publicación / Historia, cuenta precargada) → «Revisa y publica».
   - El texto de la publicación se pide solo si el destino es Publicación, con ejemplo en el campo.
   - Tendencias e inspiración sale de la ruta principal (enlace aparte).
6. **Como dueño, quiero saber qué hacer después de publicar, para seguir con mi semana.**
   - Al terminar aparece «Listo, ya está en tu Instagram.» con «Ver mi semana» y «Publicar otra».
   - Si no se sabe si se publicó, el mensaje pide revisar Instagram antes de reintentar.

### Grupo D — Palabras del dueño y navegación
7. **Como dueño, quiero que las pantallas de planificar y publicar hablen en español sencillo, para entender todo sin preguntar.**
   - Ningún texto visible contiene POST, Caption, Story/Stories, Cold, Hot, Likes, Ads, vendor, preview, tenant, R2, evento.
   - Se aplica la tabla de reemplazos de H3 y los errores de H4.
   - Títulos y pestañas: «Tu semana», «Publicar ahora», «Historias».
8. **Como dueño, quiero volver siempre a mi semana desde cualquier ficha, para no perderme entre pantallas.**
   - Toda ficha abierta desde Tu semana tiene «‹ Tu semana» y conserva semana y vista.
   - El menú muestra cuántas hay por aprobar y por programar.
   - Botones y controles del módulo miden al menos 44 px en el teléfono; nada depende de pasar el mouse.
