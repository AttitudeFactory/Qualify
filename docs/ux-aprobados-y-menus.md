# Por aprobar, Aprobados, menús de WhatsApp y stickers desde WhatsApp (m-24986801)

Especificación de experiencia (ux-designer, 2026-11-10) para dos ingenieros de interfaz en
paralelo. **Escrita leyendo el código de `origin/main` (`88f4898d`); no se abrió la app
corriendo**: la revisión local de cada PR (regla 7 del agente) se hace en el navegador.
Pedido del fundador (2026-11-10): menús en un desplegable y que se puedan eliminar; «Por
aprobar» ordenado (pestañas o desplegable: hoy los stickers tapan las publicaciones); lo aprobado
sale de ahí y va a «Aprobados», filtrable por categoría o sticker; no encontró los stickers en WhatsApp.
Base: `docs/perfil-cliente-pyme.md`, `docs/design-system.md` (§5.6 segmented, §6.1 ciclo de lista,
§6.2 destructiva), `docs/ux-guia-navegacion.md` (N1–N13), `docs/ux-whatsapp-menu-orbit.md`,
`docs/ux-stickers-videos.md`. **Sin componentes nuevos**: `rx.select`, `rx.segmented_control`,
`card`, `empty_state`, `skeleton_*`, `callout`, `rx.alert_dialog`/`confirm_action`, `rx.el.details`.

## 0. Reparto en dos pistas (sin archivos compartidos)

| Pista | Partes | Dueña de |
|---|---|---|
| **A · WhatsApp** | §1 menús, §4 stickers desde WhatsApp | `Qualify/whatsapp_*`, backend del menú |
| **B · Publicaciones** | §2 Por aprobar, §3 Aprobados | `creative_pages.py`, `gallery_state.py`, `planner_vm.py`, `planner_back.py`, `planner_provider.py`, `post_card.py`, `seasonal_*`, `ui/layout.py`, `ui/nav_vm.py`, `Qualify.py`, `page_metadata.py`, `approved_page.py` (nuevo) |

Único punto de contacto: la pista A **monta** `seasonal_ui.brand_section()` sin editar
`seasonal_ui.py`. Contrato que B no rompe: `brand_section()` sin argumentos, y
`?crear=temporada` (`SeasonalState.open_from_query`) sigue abriendo «Crear para esta temporada».

---

## 1. Menús de WhatsApp: un desplegable y «Eliminar» (pista A)

**Hoy** (`whatsapp_tab_menu.py:615` `_menus_card`): una tarjeta por menú en rejilla; con tres
menús, en el celular hay que bajar tres tarjetas para llegar al editor. No se puede eliminar.

**Propuesta.** Un `rx.select` elige el menú; debajo, **solo la tarjeta del elegido** (la de hoy,
`_menu_card`, sin cambios salvo «Eliminar»). Con un solo menú no hay desplegable.

- **Etiqueta visible:** «Menú». Cada opción dice nombre y estado en palabras:
  «prueba 2 · Respondiendo a tus clientes», «Menú principal · Sin publicar», «Navidad · En pausa»
  (`menu_status` de `whatsapp_menu_vm.py`). Orden: el que responde primero, luego en pausa,
  luego sin publicar; dentro de cada grupo, el más reciente primero.
- **Valor inicial:** el que está respondiendo; si ninguno, el abierto en el editor
  (`S.menu.menu_id`); si no, el primero de la lista.
- **Elegir = abrir.** Cambiar el desplegable llama a `edit_menu(menu_id)`: tarjeta y editor
  nunca muestran menús distintos. Si el menú abierto tiene cambios sin guardar, antes se pregunta
  con `_confirm`: título «¿Cambiar de menú?», texto «Tienes cambios sin guardar en «{nombre}».
  Guárdalos o se pierden.», botones «Cancelar» · «Guardar y cambiar» (verificar primero si
  `open_menu` ya los descarta; si los conserva, sobra el diálogo).
- **«Nuevo menú»** se queda en el título de la sección, igual que hoy; al crearlo queda elegido.

### «Eliminar»

- Botón `soft` gris con `trash-2`, «Eliminar», en la fila de «Editar» / «Pausar» (§6.2).
- **Nunca en el menú que está respondiendo.** En su lugar, una línea gris bajo los botones:
  «Para eliminarlo, primero páusalo.» (no un botón apagado: no se enfoca ni dice por qué).
- Se ofrece en un menú **en pausa** o **sin publicar**. Diálogo, en el estilo de
  «¿Eliminar este mensaje?» (`whatsapp_tab_templates.py:90-103`, `confirm_action`):
  - Título: «¿Eliminar este menú?»
  - Texto: «Se borra **{nombre}** con sus {n} versiones guardadas.» + según el caso:
    en pausa «Tus clientes ya no lo reciben desde que lo pausaste.» · sin publicar
    «Nunca les llegó a tus clientes.» + «No se puede deshacer.»
    (con una versión: «con su versión guardada»).
  - Botones: «Cancelar» (foco inicial) · «Eliminar».
  - Después: toast «Menú eliminado»; el desplegable pasa al que responde (o al primero). Si era el
    último, vuelve el vacío de hoy «Este número aún no tiene menú» con «Crear menú».
  - Error: `callout` encima de la tarjeta: «No pudimos eliminar el menú. Vuelve a intentarlo en un
    momento.»

```
375 px                               escritorio (columna principal)
┌─────────────────────────────┐      ┌──────────────────────────────────────────────┐
│ Menús de este número [+Nuevo]│     │ Menús de este número           [+ Nuevo menú] │
│ Tu WhatsApp responde con…   │      │ Tu WhatsApp responde con el menú que tú…     │
│ Menú                        │      │ Menú [prueba 2 · Respondiendo a tus clientes▾]│
│ [prueba 2 · Respondiendo a ▾]│     │ ┌──────────────────────────────────────────┐ │
│ [tus clientes              ]│      │ │ prueba 2  (Respondiendo a tus clientes)  │ │
│ ┌─────────────────────────┐ │      │ │ Versión [Versión 3 · creada el 4 de n. ▾]│ │
│ │ prueba 2                │ │      │ │ Es la versión que tienen tus clientes.   │ │
│ │ (Respondiendo a tus c.) │ │      │ │ [Editar] [Pausar]                        │ │
│ │ Versión [Versión 3 ·  ▾]│ │      │ │ Para eliminarlo, primero páusalo.        │ │
│ │ [ Editar ] [ Pausar ]   │ │      │ └──────────────────────────────────────────┘ │
│ │ Para eliminarlo, primero│ │      └──────────────────────────────────────────────┘
│ │ páusalo.                │ │      En pausa o sin publicar, la fila es:
│ └─────────────────────────┘ │      [Editar] [Reanudar] [Eliminar]
└─────────────────────────────┘
```

A 375 px el disparador del select hace salto de línea (mismo estilo que `_card_versions`) en vez
de cortar con «…»; los tres botones crecen (`flex: 1 1 auto`) y bajan de fila si no caben.

**Accesibilidad.** `aria_label` del select: «Elige qué menú ver»; cada opción lleva el estado en
texto (no solo color). Botón con nombre «Eliminar el menú {nombre}» (`MenuCardVM.delete_label`,
como `edit_label`). El diálogo devuelve el foco al desplegable al cerrar (la tarjeta ya no
existe). Teclado: el select de Radix ya abre con Enter/Espacio y flechas.

**Qué cambia en el código (pista A)**

1. **Backend (backend-engineer, primero).** No hay borrado: `qualify_app` no tiene `DELETE` sobre
   `whatsapp_menus` / `whatsapp_menu_versions` (migración 0058) y `whatsapp_thread_state` apunta al
   menú. Propuesta: **archivar** (columna `archived_at` + `GRANT UPDATE (archived_at)`, RLS ya
   existe), `repository.archive_menu(scope, menu_id)` que se niega si `published_version_id` no es
   nulo y `is_paused` es falso; al archivar uno en pausa se limpia `published_version_id` y se
   quitan sus atajos de WhatsApp (mismo camino que despublicar). `menus_for` excluye archivados.
   Las versiones se conservan (procedencia) — decisión D1.
2. `whatsapp_menu_provider.py`: `delete_menu(tenant_id, connection_id, menu_id)`.
3. `whatsapp_menu_vm.py`: `MenuCardVM` + `can_delete`, `delete_label`, `delete_text`,
   `select_option_label`; constantes `MENU_PICK_LABEL = "Menú"`, `DELETE_TITLE`, `DELETE_YES`,
   `DELETE_BLOCKED = "Para eliminarlo, primero páusalo."`, `DELETED_TOAST`, `DELETE_FAILED`; orden
   de opciones en `menu_cards_for(...)`.
4. `whatsapp_menu_state.py`: `chosen_menu_id` (computado: elegido o el valor inicial),
   `choose_menu(menu_id)` (→ `edit_menu` con la guarda de cambios), `delete_card(menu_id)` en
   segundo plano con `card_busy_action = CARD_DELETE`.
5. `whatsapp_tab_menu.py`: `_menus_card` → select + `rx.foreach` filtrado a una tarjeta (o
   `chosen_card` computado); `_menu_card` + botón/diálogo «Eliminar» o la línea bloqueada.
6. Pruebas: `test_whatsapp_menu_cards.py` (orden, valor inicial, `can_delete` falso en el que
   responde, textos con 1 y n versiones), `test_whatsapp_menu_provider.py` (archivar se niega en el
   activo), prueba de repositorio en `just test-db`.

---

## 2. Por aprobar: solo lo que espera tu decisión (pista B)

**Hoy** (`creative_pages.py:1293` `drafts_index`): arriba los lotes de stickers
(`seasonal_ui.drafts_section()`, que muestra **también los ya aprobados** del lote mientras quede
uno pendiente, `SeasonVM.to_review`), debajo la galería con ocho estados mezclados.

### Qué estado va dónde (definición)

`CARD_STATES` de `planner_vm.py`. El contador del menú ya decide igual: `count_to_approve`
(`pending_vm.py:111`) cuenta solo las generadas sin aprobar ni descartar, y dice que una aprobada
a la que le falta algo «ya no espera tu aprobación».

| Estado de la tarjeta | Clave | Pantalla | Por qué |
|---|---|---|---|
| Por revisar | `review` | **Por aprobar** | espera tu «Aprobar» |
| Creándose | `drafting` | **Por aprobar** | todavía no la puedes decidir; cuando esté, se decide aquí |
| Descartada | `discarded` | **Por aprobar**, plegada al pie (D2) | la decidiste en contra; se puede volver a crear desde aquí |
| Le falta algo | `missing` | **Aprobados**, primeras | ya la aprobaste; le falta algo para salir |
| Preparando el video final | `preparing` | **Aprobados** | aprobada, en espera |
| Lista para programar | `ready` | **Aprobados** | aprobada |
| Programada | `scheduled` | **Aprobados** | aprobada y en Tu semana |
| Ya salió | `used` | **Aprobados** | aprobada y publicada |
| Sticker/video preparándose, listo o fallido | `preparing`/`ready`/`failed` | **Por aprobar** | espera «Aprobar» / «Pedir otro» |
| Sticker/video aprobado | `approved` | **Aprobados** | — |
| Temporada archivada | `archived` | Aprobados, plegada «Archivadas» | — |

### La pantalla

- `h1` y entrada: «Por aprobar» (N1, sin cambio). Subtítulo: «Lo que espera tu visto bueno: nada
  sale sin que tú lo apruebes.»
- **Pestañas** con `rx.segmented_control` (el skin `lq-segmented` existe; `rx.tabs` se ve Radix
  crudo, §9.3): «Publicaciones (3)» | «Stickers y videos (5)». El número va en el texto del ítem
  (no un círculo de color); con 0, «Publicaciones» sin número. Por omisión «Publicaciones»; si
  está vacía y la otra no, se abre en «Stickers y videos». URL: `/drafts?ver=publicaciones` |
  `?ver=stickers` (N5): tocar cambia la URL, recargar la conserva.
- **Publicaciones:** chips de estado solo de los tres de la tabla («Todas · Por revisar ·
  Creándose»), el selector «Tipo de creación» de hoy y «Crear publicación». «Descartadas» no es
  chip: `rx.el.details` al pie, «Descartadas (2)», con sus tarjetas dentro (patrón de «Archivadas»
  en `seasonal_ui.brand_section`). Orden: Por revisar, luego Creándose.
- **Stickers y videos:** el `drafts_section()` de hoy, mostrando en cada lote **solo** los que
  esperan (preparándose, listos, fallidos). La barra «Navidad 2026 · 3 de 10 listos» se queda.
  «Aprobar los listos (n)» se queda. Al aprobar uno, sale de la rejilla y el toast dice «Listo: ya
  lo puedes mandar en tus chats.» con la acción «Ver aprobados» (→ `/aprobados?ver=stickers`).
- Al aprobar una publicación (tarjeta o ficha) sale de la lista en el acto; el toast de hoy
  («Elegir día y hora») se queda, y la tarjeta pasa a Aprobados.

```
375 px                                   escritorio
┌───────────────────────────────┐        ┌───────────────────────────────────────────────────┐
│ Por aprobar                   │        │ Por aprobar                                       │
│ Lo que espera tu visto bueno: │        │ Lo que espera tu visto bueno: nada sale sin que   │
│ nada sale sin que tú lo…      │        │ tú lo apruebes.                                   │
│ ( Publicaciones (3)|Stickers  │        │ ( Publicaciones (3) | Stickers y videos (5) )     │
│   y videos (5) )              │        │ [Tipo de creación ▾] Todas·Por revisar·Creándose  │
│ [Tipo de creación ▾]          │        │                               [Crear publicación] │
│ Todas · Por revisar · Creánd. │        │ 3 publicaciones                                   │
│ [Crear publicación]           │        │ [tarjeta] [tarjeta] [tarjeta]                     │
│ 3 publicaciones               │        │ ▸ Descartadas (2)                                 │
│ [tarjeta Por revisar]         │        └───────────────────────────────────────────────────┘
│ [tarjeta Creándose]           │
│ ▸ Descartadas (2)             │        Pestaña Stickers y videos:
└───────────────────────────────┘        │ Navidad 2026 · 3 de 10 listos  [████░░░░]        │
                                         │ [sticker listo][sticker listo][preparando…]      │
                                         │ [Aprobar los listos (3)]                          │
```

**Vacíos (N8):**
- Publicaciones: icono `circle-check`, «¡Al día! Nada espera tu aprobación», «Cuando crees una
  publicación, llega aquí para que la revises.», acción «Crear publicación» (`/create`) y enlace
  suave «Ver aprobadas» (`/aprobados`).
- Stickers y videos: icono `sticker`, «Aún no tienes stickers ni videos por aprobar», «Crea los de
  esta temporada: con tu logo y tus colores, para saludar en tus chats.», acción «Crear para esta
  temporada» (`/brand/kit?crear=temporada`, `CREATE_HREF`).
- Con filtros sin resultados: el «Nada con esos filtros» de hoy.
**Cargando:** `skeleton_rows` de hoy en la pestaña activa; el contador de la otra pestaña no se
muestra hasta tener el número. **Error:** el `callout` de hoy, en la pestaña que falló.

**Enlaces que no se rompen.** `/drafts`, `/drafts/<id>`, `?estado=` y `?orden=vence` siguen
funcionando. Corrección de paso: `?estado=por-completar` (Inicio, `home_vm.py:28-30`) hoy se
traduce a `needs_action`, que no es clave de `CARD_STATES`, así que `filter_posts` no encuentra
nada; debe traducirse a `review`. `?estado=listo|usado` apunta ahora a estados de Aprobados:
`/drafts?estado=listo|usado` redirige a `/aprobados?estado=…`. Las fichas `/drafts/<id>` no
cambian de ruta; abiertas desde Tu semana (`?desde=semana`) siguen volviendo a Tu semana.

**Qué cambia en el código (pista B)**

1. `planner_vm.py`: `PENDING_CARD_STATES = {"review", "drafting"}`, `APPROVED_CARD_STATES =
   {"missing", "preparing", "ready", "scheduled", "used"}`, `DISCARDED = "discarded"`;
   `GALLERY_FILTER_SLUGS["por-completar"] = "review"`; slugs nuevos `por-revisar`, `creandose`.
2. `gallery_state.py`: `view` (`publicaciones`/`stickers`, leído de `?ver=` en `load`, escrito con
   `rx.call_script` de `history.replaceState` como las pestañas de WhatsApp); `visible` filtra a
   `PENDING_CARD_STATES`; `discarded` computado aparte; `pending_count`.
3. `creative_pages.py`: `drafts_index` con el segmentado arriba y `rx.match` por pestaña;
   `drafts_section()` **sale** de encima de `_gallery_toolbar()`; `_gallery_toolbar` recibe los
   estados que muestra; `_gallery_empty` nuevo texto; `_discarded_fold()`.
4. `seasonal_vm.py`: `SeasonVM.pending_pieces` (sin aprobados) y `approved_pieces`;
   `seasonal_ui.drafts_section` itera `pending_pieces`; vacío como `empty_state`; acción «Ver
   aprobados» en `APPROVED_TOAST`. `seasonal_state.py`: `pending_count`.
5. Pruebas: `test_gallery.py` (partición por estado, `por-completar` → `review`, `?ver=`),
   `test_seasonal_state.py` (un lote con 2 aprobados y 1 listo muestra 1), `test_pending_counts.py`
   sin cambio de número, e2e `tests/e2e/test_galeria_to_por_aprobar.py`.

---

## 3. Aprobados: lo que ya está listo para salir (pista B)

**Menú.** Entrada nueva en la zona «Publica», **justo debajo de «Por aprobar»**:
`("Aprobados", "list-checks", "/aprobados", True)` en `NAV_ZONES` (`ui/layout.py:101`). Icono
hermano del de «Por aprobar» (`layout-list`), no repetido en el menú. **Sin contador**: lo aprobado
sin día ya lo cuenta «Tu semana» (N11, «publicación aprobada sin día»); dos números para lo mismo
confunden. En el celular queda en el cajón «Más» (la barra inferior no cambia). El mapa de
`docs/ux-guia-navegacion.md` §3 pasa de 12 a 13 entradas (lo actualiza la pista B en su PR).

**N1.** Menú «Aprobados» = `h1` «Aprobados» = pestaña «Qualify · Aprobados». Subtítulo: «Lo que
ya aprobaste, listo para programar o mandar por WhatsApp.» `page_metadata.py`: «Las publicaciones,
stickers y videos que ya aprobaste en tu negocio.»

**Contenido.** El mismo segmentado que Por aprobar (coherencia: mismo gesto en las dos):
«Publicaciones (12)» | «Stickers y videos (16)», `?ver=`. Debajo, **un** filtro `rx.select` con
etiqueta visible «Tipo»:
- en Publicaciones: «Todos los tipos» + los tipos de creación que ya existen y tienen algo
  (`content_kind_options`: Imagen publicitaria, Carrusel, Clip, Guion para grabar, Video con
  avatar humano, Video con avatar animado, Con plantilla, Video por partes). No se inventan
  categorías. URL `&tipo=<content_kind>`.
- en Stickers y videos: «Todos» · «Stickers» · «Videos». URL `&tipo=sticker|video`.
  Agrupados por temporada (la que viene primero, `order_seasons`), cada grupo con su «Archivar»
  (el de hoy, con «Deshacer» en el toast) y, plegadas al pie, «Archivadas (n)» con «Volver a usar».

**Orden.** Publicaciones: primero «Le falta algo» (necesitan algo tuyo), luego las más recientes
por fecha de aprobación. `PostOptionVM` no trae esa fecha: la pista B la añade (`approved_at`) en
`planner_provider.load_gallery`; si el dato no existe para filas viejas, se ordenan por creación.

**Acciones por tarjeta** (`_gallery_card` de hoy con su botón principal de `CARD_STATES`; nada nuevo):

| Estado | Botón principal | Además |
|---|---|---|
| Le falta algo | «Ver qué falta» → ficha | la nota de `readiness_note` en la tarjeta |
| Preparando el video final | apagado, «Preparando el video final» | — |
| Lista para programar | «Elegir día y hora» → `/planner?post=<id>&desde=aprobados` | — |
| Programada | «Ver en Tu semana» | — |
| Ya salió | «Ver» | «Ya salió 3 veces…» (`history_help`) |
| Sticker / video | tocar = ver en grande (`_preview` de hoy) | línea fija bajo la rejilla: «Se mandan desde un chat de WhatsApp: toca «+» › «Fotos y videos».» con enlace «Ir a tus chats» (`/whatsapp?tab=chats`) |

Volver (N7): la ficha abierta desde Aprobados lleva `?desde=aprobados`: enciende «Aprobados» en
el menú (`ui/nav_vm.py`, como `?desde=semana`) y su enlace dice «‹ Aprobados». Tu semana abierta
con `&desde=aprobados` muestra «‹ Aprobados» en vez de «‹ Por aprobar» (`BACK_TO_DRAFTS`).

```
375 px                                   escritorio
┌───────────────────────────────┐        ┌───────────────────────────────────────────────────┐
│ Aprobados                     │        │ Aprobados                                         │
│ Lo que ya aprobaste, listo    │        │ Lo que ya aprobaste, listo para programar o       │
│ para programar o mandar…      │        │ mandar por WhatsApp.                              │
│ ( Publicaciones (12)|Stickers │        │ ( Publicaciones (12) | Stickers y videos (16) )   │
│   y videos (16) )             │        │ Tipo [Todos los tipos ▾]                          │
│ Tipo                          │        │ 12 publicaciones                                  │
│ [Todos los tipos          ▾]  │        │ [Le falta algo][Lista p. programar][Programada]   │
│ 12 publicaciones              │        │ [Ya salió]     [Ya salió]          [Ya salió]     │
│ [tarjeta · Le falta algo   ]  │        └───────────────────────────────────────────────────┘
│   [Ver qué falta]             │        Stickers y videos:
│ [tarjeta · Lista p. progr. ]  │        │ Tipo [Todos ▾]                                    │
│   [Elegir día y hora]         │        │ Navidad 2026 · 6 stickers, 4 videos   [Archivar]  │
└───────────────────────────────┘        │ [st][st][st][st][vi][vi]                          │
                                         │ Se mandan desde un chat de WhatsApp: toca «+» ›   │
                                         │ «Fotos y videos».  Ir a tus chats                 │
                                         │ ▸ Archivadas (1)                                  │
```

**Vacíos (N8):**
- Publicaciones: icono `list-checks`, «Todavía no apruebas ninguna publicación», «Cuando apruebes
  una, aparece aquí lista para elegir día y hora.», acción «Ver lo que espera tu aprobación»
  (`/drafts`).
- Stickers y videos: icono `sticker`, «Aún no apruebas stickers ni videos», «Apruébalos en Por
  aprobar o crea los de esta temporada.», acción «Crear para esta temporada» (`CREATE_HREF`).
- Filtro sin resultados: «Nada de ese tipo todavía», acción «Ver todos».
**Cargando:** `skeleton_rows` (publicaciones) y `skeleton_card(2)` (stickers). **Error:**
«No pudimos traer lo que aprobaste. Vuelve a intentarlo en un momento.» + «Reintentar».

**Accesibilidad.** Segmentado: cada ítem se anuncia con su número («Publicaciones, 12»); la
selección no depende del color (pestaña de vidrio + peso). Select con etiqueta visible. Tarjetas
y botones ≥ 44 px; el estado de cada tarjeta en texto (`card_label`), nunca solo por tono.

**Qué cambia en el código (pista B)**

1. `ui/layout.py`: la entrada en `NAV_ZONES`; `ui/nav_vm.py`: `?desde=aprobados` enciende
   «Aprobados» en `/drafts/<id>`; `planner_back.py`/`planner_vm.py`: «‹ Aprobados».
2. `Qualify.py`: `app.add_page(approved_index, route="/aprobados", on_load=[AuthState.require_login,
   ApprovedState.load], title="Qualify · Aprobados")`; `page_metadata.py`: la descripción.
3. Archivo nuevo `Qualify/approved_page.py` (`approved_index`), y el estado en `gallery_state.py`
   (`ApprovedState` o vars `approved_*` sobre los mismos `posts`, sin segunda lectura); reutiliza
   `_gallery_card` (moverlo a `post_card.py` si hace falta importarlo sin ciclo).
4. `seasonal_ui.py`: `approved_section()` (grupos por temporada con `approved_pieces`, filtro
   sticker/video, «Archivar», plegado «Archivadas»); `seasonal_state.py`: `kind_filter`,
   `approved_count`. `brand_section()` queda igual (contrato con la pista A).
5. `planner_provider.load_gallery` + `PostOptionVM.approved_at`.
6. Pruebas: `test_nav_menu_map.py`, `test_nav_one_name.py`, `test_nav_active.py` (`/aprobados` y
   `/drafts/<id>?desde=aprobados` encienden una sola entrada), `test_sidebar_top_row.py`,
   `test_bottom_bar.py` (sin cambio), `test_page_metadata.py`, `test_gallery.py` (orden, filtro
   `tipo`), `test_seasonal_state.py` (aprobados por temporada).

---

## 4. Stickers y videos desde WhatsApp (pista A)

**Hoy.** El «+» del chat ya tiene **6 filas, el tope** de `docs/ux-whatsapp-menu-orbit.md` §2
(`PICK_SOURCE_CARDS`: Tus productos · Tu oferta · Tu menú · Formas de pago · Cómo llegar · Fotos y
videos). Los stickers no son fila: son la tercera tarjeta de «Fotos y videos › ¿De dónde?», y
**solo aparece si hay algo aprobado** (`whatsapp_tab_chats.py:2017`). La biblioteca vive solo al
pie de Tu marca. Por eso el fundador no los encontró. **No se agrega una 7.ª fila.**

**a) La tarjeta, siempre.** En «¿De dónde?» la tarjeta de stickers se ve siempre, en tercer lugar:
- Con aprobados: la de hoy (`seasonal_card_title`, «Para saludar y celebrar con tu marca.»).
- Sin aprobados: título «Stickers y videos de tu marca», línea «Aún no tienes: créalos para esta
  temporada.» Tocarla abre el paso del panel con un `empty_state` (nada se manda):
  - con lotes esperando: «Tienes {n} esperando tu aprobación», «Apruébalos y quedan listos para
    mandar desde aquí.», acción «Revisarlos» (`/drafts?ver=stickers`);
  - sin nada: «Aún no tienes stickers ni videos», «Los creamos con tu logo y tus colores en Tu
    marca. Tardan unos minutos: cuando los apruebes, aparecen aquí para mandarlos.», acción
    «Crear para esta temporada» (`/brand/kit?crear=temporada&volver=/whatsapp?tab=chats`, con
    `volver` codificado; Tu marca muestra «Volver a tus chats»). *Cambiado en m-25017173,
    2026-11-12.*
  - «Atrás» vuelve a «¿De dónde?», como hoy.

**b) Una entrada en WhatsApp — retirada (m-25017173, 2026-11-12).** La sub-pestaña
«Chats · Stickers y videos» (`?tab=chats&sub=stickers`) duplicaba la biblioteca de Tu marca y se
quitó a pedido del fundador (menos pestañas en WhatsApp). «Chats» abre directo la lista de chats,
sin segunda barra; un enlace viejo con `sub=stickers` (o cualquier `sub`) abre los chats. Los
stickers y videos se crean y archivan en **Tu marca** («Stickers y videos de tu marca»), se
aprueban en **Por aprobar** y se ven en **Aprobados**; se mandan desde el «+» del chat (punto a).

```
375 px · «+» › Fotos y videos (sin aprobados)
┌───────────────────────────────┐
│ ‹ ¿De dónde?                  │
│ ( ) Tus piezas                │
│     Lo que preparaste para…   │
│ ( ) De tu celular             │
│     Una foto que ya tengas…   │
│ ( ) Stickers y videos de tu   │
│     marca                     │
│     Aún no tienes: créalos    │
│     para esta temporada.      │
└───────────────────────────────┘
```

**Accesibilidad.** La tarjeta sigue en el `radiogroup` de hoy, ≥ 44 px; su nombre accesible
incluye la línea («Stickers y videos de tu marca. Aún no tienes…»). El paso vacío lleva el foco
a su título al abrir (como los demás pasos del panel).

**Qué cambia en el código (pista A)**

1. ~~`whatsapp_vm.py`: `TAB_STICKERS` y la sub-pestaña de «Chats».~~ Retirado en m-25017173:
   `SUBTABS[SECTION_CHATS]` tiene un solo panel y `resolve_panel` manda cualquier `sub` a `TAB_CHATS`.
2. ~~`whatsapp_page.py`: `brand_section()` en `tab_body`.~~ Retirado en m-25017173.
3. `whatsapp_tab_chats.py` `_pick_media`: la tarjeta sin `rx.cond`; `_pick_seasonal` con el vacío
   de dos casos. `whatsapp_chats_vm.py`: `SEASONAL_EMPTY_LINE`, `SEASONAL_EMPTY_*`,
   `SEASONAL_PENDING_*`, `SEASONAL_CREATE_HREF`. `whatsapp_chats_state.py`: `pick_seasonal_pending`
   (cuántos esperan; lo da `whatsapp_chats_provider`, lectura RLS de `whatsapp.seasonal`).
4. Pruebas: `test_whatsapp_chats_seasonal.py` (la tarjeta con 0 aprobados, los dos vacíos, que
   ningún camino llama a enviar), `test_whatsapp_page.py` (desde m-25017173:
   `?tab=chats&sub=stickers` abre los chats, sin segunda barra), `test_whatsapp_chats_picker.py` (siguen 6 filas).

---

## 5. Decisiones del fundador (con recomendación)

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| D1 | ¿«Eliminar» un menú lo borra o lo archiva? | **A** archivar (`archived_at`, no se ve más; versiones guardadas) · **B** borrado real (migración con `DELETE`, cascada sobre versiones y estado de chats) | **A**: conserva la procedencia y los chats que lo usaron; para el dueño es lo mismo («No se puede deshacer»). Si algún día se quiere «recuperar», A ya lo permite. |
| D2 | ¿Dónde quedan las publicaciones descartadas? | **A** plegadas al pie de Por aprobar · **B** en ninguna lista (solo por enlace) · **C** en Aprobados | **A**: no son aprobadas (C confunde) y desde ahí se vuelven a crear; plegadas no estorban. |
| D3 | ¿Dónde vive la biblioteca de stickers en WhatsApp? | **A** sub-pestaña de «Chats» · **B** sub-pestaña de «Promociones» | **A**: se mandan dentro de un chat, no en envíos masivos; Promociones ya tiene 3 sub-pestañas. |

Hipótesis a validar (perfil §5, pregunta 6): que el dueño busque los stickers dentro de «Chats» y
no en «Promociones»; y que «Fotos y videos» le diga que ahí también hay stickers. Si en la prueba
con Bianki no los encuentra, la fila 6 pasa a «Fotos y stickers» (16 caracteres, regla del Orbit).
