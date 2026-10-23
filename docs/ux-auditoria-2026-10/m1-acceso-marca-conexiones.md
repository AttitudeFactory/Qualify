# M1 · Acceso, marca y conexiones — auditoría de experiencia

`[2026-10-23 · solo sugerencias, no se tocó código]` · Lentes: `qualify-ux` §1-§5 + `qualify-copy-es`.
Archivos leídos: `Qualify/auth_pages.py`, `Qualify/auth_state.py` (rutas), `Qualify/creative_wizard_pages.py`
(el flujo `/brand`, `/brand/connect`, `/brand/connect/setup`, `/brand/manual` vive aquí, no en
`creative_pages.py`, cuyo `brand_index` ya no tiene ruta), `Qualify/brand_finish.py`,
`Qualify/brand_documents.py`, `Qualify/brand_avatar_panel.py`, `Qualify/brand_kit_editor.py`,
`Qualify/connections_page.py`, `Qualify/connections_vm.py`, `Qualify/settings_page.py`,
`Qualify/ui/layout.py` (menú), `Qualify/Qualify.py` (rutas y títulos de pestaña).

## (a) El trabajo del módulo, en palabras del dueño

1. «Entro con mi invitación, pongo mi contraseña y ya estoy adentro.»
2. «Le cuento a Qualify cómo es mi negocio (mi Instagram, mi logo, mis colores, cómo hablo) una sola vez, para que lo que me proponga se parezca a mi local.»
3. «Conecto mi Instagram/Facebook para poder aprobar y publicar desde aquí, y llego rápido a mi primera publicación.»

### El recorrido real hoy (dueño invitado, primera vez)

```
correo de invitación → /registro (6 campos) → "/" → require_login → /brand
  → ¿Tienes redes? → /brand/connect: 12 pasos (Paso 1 de 12 … Paso 12 de 12)
     Tu cuenta · Esto es lo que vemos · ¿Eres influencer o una marca? · Tu rubro y ubicación
     · ¿Quién es la marca? · ¿Tienes brandboard? · Tu brandboard · Tipografía
     · Paleta de colores · ¿Todo correcto? · Referente, competencia o detractor
     · Resultados e insights → [Mejorar tu perfil →]
  → "/" = Menciones (escucha social, vacía para un negocio nuevo)
  → (nadie le dice) Conexiones → Prepara tu Instagram (4 pasos) → Meta → volver
  → (nadie le dice) Crear pieza
```

Hasta terminar los 12 pasos, **todas** las pantallas de negocio (incluidas `/connections` y
`/create`) lo devuelven a `/brand` (`auth_state.py:282-283`); solo `/settings` se salva.

## (b) Hallazgos, ordenados

Severidad: 1 = no puede terminar · 2 = palabras técnicas / de funcionalidad · 3 = demasiados datos en un paso · 4 = accesibilidad / móvil · 5 = pulido.

### 1. El invitado sin invitación termina 12 pasos y choca con «solo por invitación» — sev 1 · M
- **Dónde:** `auth_pages.py:144-146` (botón «Crear mi Brand Kit» en el login, abierto a cualquiera) → `creative_wizard_pages.py:1116-1121` (`_finish_route` manda a `/registro` a todo borrador) → `auth_pages.py:333-357` / `:455-463` (sin token válido solo se ve «Qualify es solo por invitación»).
- **Lo que siente el dueño:** «Me pasé 15 minutos armando mi marca y al final me dice que no puedo entrar. ¿Y lo que hice?»
- **Arreglo:** decisión del fundador (política de registro por invitación, 2026-10-13). Opciones dentro del sistema actual: (a) quitar «Crear mi Brand Kit» del login mientras el registro sea por invitación; o (b) avisar **antes** de empezar y cerrar con captura de interés:
  - En `/brand/start`, bajo el título: «Puedes armar tu marca ahora. Para usarla en Qualify necesitas una invitación: si no la tienes, al terminar te pedimos tus datos y te escribimos.»
  - En el último paso, si no hay invitación, en lugar de mandar a `/registro`: `callout(..., "ok")` «Tu marca quedó guardada con tu correo. Te avisamos por correo cuando tu invitación esté lista.»

### 2. Al terminar la marca aterriza en «Menciones», no en su primera publicación — sev 1 · S
- **Dónde:** `creative_wizard_pages.py:1113` (`_APP_HOME_ROUTE = "/"`), `:1186` («Mejorar tu perfil»), `auth_state.py:573` (registro sin borrador → `"/"`), `Qualify.py:350-354` (`/` es Menciones, escucha social).
- **Lo que siente:** «¿Mejorar mi perfil? Yo quería hacer una publicación. ¿Y ahora qué hago aquí?» El botón final promete algo que no ocurre y lo deja en una pantalla vacía de otro dominio.
- **Arreglo:** el último paso cierra con una **pantalla de logro + siguiente paso** (ver Navegación) y el botón dice lo que pasa: «Crear mi primera publicación» → `/create`. Secundario: «Conectar mi Instagram» → `/connections`.

```
┌────────────────────────────────────┐
│  ✓ Tu marca está lista             │
│  Logo, colores y forma de hablar   │
│  ya se usan en cada publicación.   │
│                                    │
│  [ Crear mi primera publicación ]  │  ← solid
│  [ Conectar mi Instagram ]         │  ← soft
│  Ver mi marca                      │  ← enlace
└────────────────────────────────────┘
```

### 3. Doce pasos obligatorios antes de poder hacer nada — sev 1 · L
- **Dónde:** `creative_wizard_pages.py:3170-3206` (`CONNECT_STEPS`), `auth_state.py:282-283` (todo el app bloqueado hasta `brand_kit_complete`), `:7362-7426` (Continuar deshabilitado si falta Posicionamiento + Audiencia, paleta, etc.), `:7356-7359` («Puede tardar unos minutos» en referentes, sin poder saltarlo: «no controls, so it cannot be skipped»).
- **Lo que siente:** «Esto no termina nunca. Y lo de los referentes ni lo entiendo.» No cabe en 2 minutos con una mano.
- **Arreglo:** dividir por **dominio** en lo mínimo para la primera publicación y dejar el resto como «mejóralo cuando quieras» desde Tu marca:

```
LO MÍNIMO (bloquea, ~2 min)               DESPUÉS (no bloquea, desde «Tu marca»)
① Tu Instagram   @usuario  [Leer]         · Tipografía
② ¿Es tu perfil? [Sí, es mío] [No]        · ¿Cómo habla tu marca? (ejemplos, palabras prohibidas)
③ Tu negocio     rubro + ciudad (rellenos)· Tu voz
④ Tu logo y colores (de la foto/logo)     · Negocios parecidos al tuyo (referentes)
⑤ ✓ Lista → Crear mi primera publicación  · Promesas que no puedes hacer
```
  - `¿Eres influencer o una marca?` sale del camino principal: el segmento son negocios (perfil §0); «Las dos cosas» va bajo «Más opciones» en el paso ③.
  - Posicionamiento / Audiencia: prellenar desde la biografía y no exigirlos para continuar.
  - Referentes: corre en segundo plano y se revisa luego; nunca un muro de espera.

### 4. «Brand Kit», «brandboard», «insights», «claims», «referente/detractor» por todo el módulo — sev 2 · S
- **Dónde y reemplazo exacto:**

| Archivo:línea | Hoy | Proponer |
|---|---|---|
| `auth_pages.py:110` | «…inicia sesión para ver tu Brand Kit.» | «…inicia sesión para ver tu marca.» |
| `auth_pages.py:140` | «Crear mi Brand Kit» | «Preparar mi marca» |
| `auth_pages.py:292` | «Crea tu Brand Kit» | «Prepara tu marca» |
| `auth_pages.py:318` | «Empezar mi Brand Kit» | «Empezar» |
| `auth_pages.py:391-393` | «Tu Brand Kit ya está guardado con…» | «Tu marca ya está guardada con…» |
| `creative_wizard_pages.py:2923` | título «Brandkit» | «Tu marca» |
| `creative_wizard_pages.py:3191-3192`, `:152`, `:1242-1243` | «¿Tienes brandboard?» / «Tu brandboard» | «¿Ya tienes logo?» / «Tu logo» — «Ya tengo uno» / «Ayúdame a crearlo» |
| `creative_wizard_pages.py:3203` | «Referente, competencia o detractor» | «¿Qué negocios se parecen al tuyo?» (Te inspira / Compite contigo / No va contigo) |
| `creative_wizard_pages.py:3205` | «Resultados e insights» | «Así se ve tu cuenta hoy» |
| `creative_wizard_pages.py:1220, 1227` | «Posicionamiento» / «Audiencia» | «¿Qué te hace distinto?» / «¿Quién te compra?» |
| `creative_wizard_pages.py:2238, 2250` (`_KIT_LISTS`) | «Patrones de llamado a la acción» / «Claims prohibidos» | «Cómo invitas a comprar» / «Promesas que no puedes hacer» |
| `creative_wizard_pages.py:2524-2525` | «Haz clic… desde Negocio → Brand Kit.» | «Toca un valor para cambiarlo. Tu voz la ajustas después en Tu marca.» |
| `creative_wizard_pages.py:5875`, `:5993` | «hashtags» (texto largo) | «etiquetas» (el «#» en la pastilla se mantiene) |
| `brand_kit_editor.py:553, 528, 58, 63` | «Tu Brand Kit», «Editar Brand Kit», «Brandboard», «claims prohibidos» | «Tu marca», «Editar mi marca», «Logo», «promesas que no puedes hacer» |
| `layout.py:90, 433` (menú) | «Brand Kit» | «Tu marca» |
| `brand_finish.py:56, 58` | «Brand Kit guardado…» / «No se pudo guardar el Brand Kit.» | «Tu marca quedó guardada.» / «No pudimos guardar tu marca. Inténtalo de nuevo.» |

### 5. «Qualify no podrá publicar o responder mensajes por ti» contradice «asistido, nunca autónomo» — sev 2 · S
- **Dónde:** `connections_page.py:604-606`; también `connections_vm.py` requisito «messages» («Qualify no puede leer ni responder tus mensajes directos»).
- **Lo que siente:** «¿Va a contestar solo a mis clientes?» (miedo §2 del perfil: publicar algo que no aprobó; hipótesis, pregunta §5.8).
- **Arreglo:** «Son cuatro pasos y toman unos minutos. Si te saltas uno, no podrás publicar ni responder mensajes desde Qualify.» / «Sin este permiso no verás tus mensajes directos en Qualify ni podrás responderlos desde aquí.»

### 6. Dos «conectar» distintos: `/brand/connect` lee el perfil, `/connections` da permiso para publicar — sev 2 · M
- **Dónde:** `Qualify.py:535` (pestaña «Qualify · Conectar redes» para la lectura del perfil), `:363` («Qualify · Conexiones») vs. `connections_page.py:442` («Cuentas conectadas»); `connections_page.py:416` («…para empezar a escuchar y responder»).
- **Lo que siente:** «Ya conecté mi Instagram al principio, ¿por qué me pide conectarlo otra vez?»
- **Arreglo:** la lectura del perfil no se llama «conectar»: pestaña «Qualify · Tu marca», paso «Tu Instagram» con texto «Solo leemos lo que ya es público. Para publicar lo conectarás después.» En `/connections`: título «Tu Instagram y Facebook», subtítulo «Conéctalos para aprobar y publicar desde aquí.» (nombre del menú y de la pestaña iguales: «Conexiones» → «Tus redes»).

### 7. Registro con «Zona horaria» y «Moneda» como texto libre (VE / America/Caracas / USD) — sev 3 · S
- **Dónde:** `auth_pages.py:423-436`.
- **Lo que siente:** «¿Qué es America/Caracas? Yo estoy en Cúcuta.» Tres campos técnicos, en una fila de 3 que a 360 px no cabe, y valores venezolanos por defecto para un dueño de CO/UY.
- **Arreglo:** un solo campo «¿En qué país está tu negocio?» (select Colombia / Venezuela / Uruguay); zona horaria y moneda se deducen del país y se cambian en Configuración. El registro queda: nombre del negocio · correo (fijo) · contraseña · país → «Crear mi cuenta».

### 8. Los campos no tienen etiqueta visible (el placeholder hace de etiqueta) — sev 4 · S
- **Dónde:** `auth_pages.py:49-59` («Email»), `:63` («Contraseña»), `:401-433`, `:309-316`; `settings_page.py:39-41`. El docstring `auth_pages.py:25-26` lo declara a propósito.
- **Lo que siente:** al escribir desaparece el texto: «¿Esto era el correo del negocio o el mío?»
- **Arreglo:** etiqueta encima con el mismo patrón `_labeled_input` del asistente (no afecta el autocompletado, que depende de `name`/`autoComplete`). Y «Email» → «Correo» (`auth_pages.py:49`, `:411`).

### 9. Botones del asistente de 32 px y ojo de contraseña de 24 px — sev 4 · S
- **Dónde:** `creative_wizard_pages.py:2670-2700`, `:7447-7493` («Atrás», «Continuar», «Cancelar», `size="2"`), `:1189` («Mejorar tu perfil», `size="2"`), `auth_pages.py:72-83` (`icon_button size="1"`), `connections_page.py:560-567` («¿Cómo lo hago?», `size="1"`).
- **Lo que siente:** con el pulgar toca «Atrás» queriendo «Continuar».
- **Arreglo:** `size="3"` (≥ 40 px, más el `min-height: 44px` del sistema si existe el token) y, en móvil, «Continuar» a lo ancho; el ojo con área táctil de 44 px.

### 10. La tarjeta de cuenta conectada habla como un panel técnico — sev 2 · M
- **Dónde:** `connections_page.py:41-43` («Degradada», «Revocada»), `:76` («Verificar ahora»), `:92-96` (tooltip «fila de la documentación de Meta… segunda fuente»), `:323-340` («Verificada:», «Última verificación de acceso:»), `:358` («Permisos concedidos» con pastillas), `:387` («Deshabilitado»).
- **Lo que siente:** «¿Degradada? ¿Revocada? ¿Está bien o no?»
- **Arreglo:** estados «Funciona» / «Hay que volver a conectarla» / «Desconectada»; una línea «Puedes: publicar · ver comentarios · ver mensajes» y otra «Todavía no puedes: … [Cómo activarlo]». Fechas y permisos bajo «Más detalles». Quitar el tooltip de documentación de Meta de la vista del dueño (información del operador).

### 11. Mensajes de error y carga que nombran proveedores o configuración interna — sev 2 · S
- **Dónde:** `brand_documents.py:67` («falta configurar la clave de Anthropic»), `:532` («Claude lee el documento…»), `brand_finish.py:57` / `brand_documents.py:65` («No hay ninguna sesión de negocio activa»), `brand_avatar_panel.py:36` («cuando conectemos la generación de imágenes»).
- **Arreglo:** «Ahora no podemos leer tu documento. Escribe los datos a mano o inténtalo más tarde.» · «Leemos tu documento y completamos tu marca con lo que dice.» · «Tu sesión se cerró. Vuelve a entrar para seguir.»

### 12. «Editar Brand Kit» abre en el ranking de referentes, no en su marca — sev 5 · M
- **Dónde:** `brand_kit_editor.py:545` (subtítulo «Tus referentes y tu competencia, en orden de influencia»), `:567` (vista por defecto `_results_view`), `:419-470` (si falta la voz, la página entera es un aviso amarillo «Te falta configurar tu voz…»).
- **Lo que siente:** «Entré a cambiar mi logo y me muestra cuentas de otros.»
- **Arreglo:** la vista por defecto es el resumen de su marca por secciones (logo, colores, cómo habla), cada una con «Cambiar»; referentes como una sección más («Negocios parecidos al tuyo»). La voz pendiente pasa a una fila de la lista «Mejora tu marca (opcional)», no a un aviso que tapa todo.

## (c) Navegación

### Estructura actual

| Ruta | Título de pestaña (`Qualify.py`) | `page_header` | Menú | Entra desde | Sale a |
|---|---|---|---|---|---|
| `/login` | Qualify · Entrar | «Inicia sesión» | — | `/settings` sin sesión, enlaces | `/` (Menciones) o `/brand` |
| `/registro` | Qualify · Registrar negocio | «Crea tu cuenta» / «Registrar un negocio» | — | correo de invitación, fin del borrador | `/` o `/brand/kit` |
| `/forgot`, `/reset` | Recuperar / Nueva contraseña | ok | — | login | login / `/` |
| `/brand/start` | Qualify · Tu Brand Kit | «Crea tu Brand Kit» | — | login, `/` sin sesión | `/brand` |
| `/brand` | Qualify · Marca | «Brandkit» | solo menú de invitado | todo el app si el kit no está completo | `/brand/connect` o `/brand/connect/setup` |
| `/brand/connect/setup` | Qualify · Crea tu cuenta | «Crea tu cuenta» | — | «No, todavía no» | Instagram/TikTok externos; `/brand/connect` |
| `/brand/connect` | Qualify · Conectar redes | título del paso + «Paso N de 12» | — (sin menú) | `/brand` | `/registro` o `/` |
| `/brand/manual` | Qualify · Brand Kit | — | sin enlace (huérfana) | solo URL directa | `/registro` o `/` |
| `/brand/kit` | Qualify · Editar Brand Kit | «Tu Brand Kit» | Negocio → Brand Kit | menú | — |
| `/connections` | Qualify · Conexiones | «Cuentas conectadas» | arriba, sin zona | menú, avisos de Conversaciones | Meta (OAuth) y vuelta |
| `/settings` | Qualify · Configuración | «Configuración» | Negocio → Configuración | menú | — |

**Problemas:** (1) callejón al final del asistente (aterriza en Menciones); (2) callejón del invitado sin invitación; (3) nombres distintos para lo mismo: pestaña «Conexiones» ≠ título «Cuentas conectadas»; «Marca» / «Brandkit» / «Tu Brand Kit» / «Editar Brand Kit» / «Brand Kit» para la misma cosa; (4) «Conectar redes» usado para algo que no conecta; (5) nada enlaza `/connections` → `/create` cuando la conexión queda lista; (6) en el asistente no hay salida a «Seguir después» (solo «Atrás»), y el primer paso solo ofrece «Usar otro correo»; (7) los pasos que se saltan (`_is_skipped`) hacen que «Paso N de 12» salte números.

### Estructura propuesta (patrón de navegación para todo el app)

**Regla 1 · Un nombre por lugar.** Menú = `page_header` = pestaña `Qualify · <nombre>`. Ej.: «Tu marca» en las tres; «Tus redes» en las tres.

**Regla 2 · Cada pantalla de fin de tarea dice «listo» y ofrece el siguiente paso del trabajo del dueño** (un botón sólido al siguiente módulo, uno suave para volver).

**Regla 3 · Los asistentes muestran «Paso N de M» con M real (sin contar los saltados), tienen «Atrás» y «Seguir después»** (guarda y vuelve a Inicio), y nunca bloquean el resto del app más allá de lo mínimo.

**Regla 4 · Mientras falte algo para la primera publicación, Inicio muestra la lista «Para empezar»**, no Menciones:

```
┌─ Inicio ───────────────────────────────┐
│ Para tu primera publicación            │
│ ✓ Tu cuenta                            │
│ ✓ Tu marca (logo y colores)            │
│ ○ Conecta tu Instagram     [Conectar]  │
│ ○ Tu primera publicación   [Crearla]   │
│ Mejora tu marca cuando quieras (3) ›   │
└────────────────────────────────────────┘
```

**Recorrido propuesto del módulo:**

```
invitación → Crear tu cuenta (4 campos) → Tu marca · mínimo (5 pasos, ~2 min)
  → ✓ Tu marca está lista ─┬─ [Crear mi primera publicación] → /create
                           └─ [Conectar mi Instagram] → /connections (Tus redes)
/connections: Prepara tu Instagram (4 pasos) → Meta → vuelta con «✓ Instagram conectado»
  → [Crear una publicación] → /create      (si venía de /create, vuelve allí)
Tu marca (/brand/kit): resumen por secciones + «Mejora tu marca (opcional)»
```

Títulos propuestos: `/brand/start` «Qualify · Tu marca», `/brand` y `/brand/connect` «Qualify · Tu marca» (el paso va en el `page_header`), `/brand/kit` «Qualify · Tu marca», `/connections` «Qualify · Tus redes», `/registro` «Qualify · Crear tu cuenta». `/brand/manual`: retirar o enlazar desde «No tengo redes» (hoy es huérfana).

## (d) Historias propuestas

### Grupo A · Primera vez (acceso)

**A1. Como dueño invitado quiero crear mi cuenta con solo mi nombre de negocio, contraseña y país para entrar en menos de un minuto.**
- El registro invitado muestra 4 campos con etiqueta visible: Nombre del negocio, Correo (fijo), Contraseña, País (Colombia / Venezuela / Uruguay).
- Zona horaria y moneda se derivan del país y se pueden cambiar en Configuración.
- A 360 px el formulario es de una columna, sin desplazamiento horizontal.

**A2. Como visitante sin invitación quiero saber antes de empezar que necesito una invitación para no perder mi trabajo.**
- `/brand/start` dice, antes del botón, que hace falta una invitación para usar la marca en Qualify (o el acceso se retira del login; decisión del fundador).
- Ningún recorrido termina en «Qualify es solo por invitación» sin ofrecer dejar los datos de contacto.

### Grupo B · Tu marca (asistente)

**B1. Como dueño quiero dejar lista mi marca en 5 pasos cortos para poder hacer mi primera publicación hoy.**
- El camino obligatorio tiene como máximo 5 pasos: Tu Instagram, ¿Es tu perfil?, Tu negocio (rubro y ciudad prellenados), Tu logo y colores, Lista.
- Tipografía, cómo habla, palabras prohibidas, voz y referentes no bloquean el acceso al app; se ofrecen después en «Mejora tu marca».
- «Paso N de M» cuenta solo los pasos que ve ese dueño.
- Hay «Seguir después» en cada paso, que guarda y no pierde datos.

**B2. Como dueño quiero leer todo en mis palabras para no tener que preguntar qué significa.**
- Ningún texto del módulo contiene «Brand Kit», «brandboard», «insights», «claims», «detractor», «hashtag» (en frases), «Email», «Claude», «Anthropic» (tabla del hallazgo 4 y 11).
- Menú, `page_header` y pestaña usan «Tu marca».

**B3. Como dueño que acaba de terminar su marca quiero que me lleven a crear mi primera publicación para ver el resultado enseguida.**
- El último paso muestra «Tu marca está lista» con «Crear mi primera publicación» (→ `/create`) y «Conectar mi Instagram» (→ `/connections`).
- Ya no se aterriza en Menciones al terminar.

### Grupo C · Tus redes (conexiones)

**C1. Como dueño quiero entender de un vistazo si mi Instagram funciona y qué puedo hacer con él para no tener miedo de haber hecho algo mal.**
- Estados en lenguaje del dueño: «Funciona», «Hay que volver a conectarla», «Desconectada», nunca solo por color.
- La tarjeta lista «Puedes:» y «Todavía no puedes:» con un enlace al paso que lo activa; permisos y fechas quedan bajo «Más detalles».
- Ningún texto dice o insinúa que Qualify publica o responde por su cuenta.

**C2. Como dueño que acaba de conectar su Instagram quiero que me ofrezcan crear una publicación para no quedarme sin saber qué sigue.**
- La vuelta de Meta con éxito muestra «Instagram conectado» y un botón «Crear una publicación».
- Si el dueño llegó a `/connections` desde Crear pieza o Publicar, vuelve a esa pantalla.

### Grupo D · Navegación

**D1. Como dueño quiero que Inicio me diga qué me falta para mi primera publicación para saber siempre qué hacer después.**
- Mientras falte la conexión o la primera publicación, Inicio muestra la lista «Para tu primera publicación» con su estado y un botón por fila.
- Cada pantalla del módulo tiene el mismo nombre en menú, título y pestaña (reglas 1-3 de Navegación).
- Botones principales de los asistentes con área táctil ≥ 44 px.
