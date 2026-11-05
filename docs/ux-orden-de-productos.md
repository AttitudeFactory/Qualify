# El dueño elige el orden de su menú (m-24955643)

Especificación de experiencia, 2026-11-05. En el WhatsApp de Bianki los shawarmas salen de últimos:
las categorías van por abecedario (`whatsapp/catalog.py`, `to_catalog_items`) y nada deja elegir.
Hermana: m-24955644 (arrastrar en vez de «Subir / Bajar» en el paso 2): mismo gesto y componente.

## 1. Un solo lugar para ordenar: «Tus productos» (Catálogo)

- El orden vive en **Catálogo → «Tus productos»**, con el botón **«Ordenar tu menú»**. Es el mismo
  orden en los tres lugares donde el cliente ve productos: la lista de WhatsApp («Ver menú y
  pedir»), el selector del chat («Foto o menú» → Tus productos) y la revisión de lo encontrado.
- **Menú de WhatsApp, paso 3 «Tus productos»:** muestra el orden en modo lectura (las categorías y
  los 9 primeros productos) y el enlace **«Cambiar el orden»**, que abre el Catálogo en modo ordenar
  y vuelve con «‹ Volver a tu menú de WhatsApp» (N7). No se ordena ahí: dos lugares se contradirían.
- **Revisión de lo encontrado (foto, PDF o página, `ux-whatsapp-respuestas-de-siempre.md` §4):**
  «Revisar y agregar» abre la lista ya fusionada (lo que tenía + lo nuevo con la marca «Nuevo») con el
  mismo componente de ordenar. Por defecto, cada nuevo queda **al final de su categoría** y cada
  categoría nueva **al final del menú**. Se guarda **solo con «Agregar a mi menú»**; «Atrás» no cambia nada.
- **Valor inicial:** cada negocio conserva el orden que ve hoy (A a la Z, «Otros» al final).

## 2. El gesto, a 375 px

| Qué se mueve | Cómo |
|---|---|
| Una categoría (con todos sus productos) | Pestaña «Categorías»: filas compactas, una por categoría, con el número de productos |
| Un producto, dentro de su categoría | Pestaña «Productos»: grupos por categoría; arrastrar solo reordena dentro del grupo |
| Un producto a otra categoría | **No es arrastrar**: es editar su categoría («Editar» → «Categoría»); queda al final de la nueva |

- Dos pestañas: arrastrar una categoría abierta con diez productos debajo no se controla en el celular.
- **Dedo:** asa `grip-vertical` de 44 × 44 px a la izquierda; desde el asa se arrastra al instante,
  desde el resto de la fila con **pulsación larga** (lo mismo que hoy con las fotos del producto y el
  ranking de referentes). Los demás se apartan en vivo; soltar fuera del grupo devuelve la fila.
- **Teclado y lector:** el asa es un botón; Espacio levanta y suelta, flechas mueven, Escape cancela;
  `aria-live` dice la posición nueva.
- **Sin arrastrar (siempre disponible):** botón «⋯» de 44 px en cada fila → «Primero», «Subir uno»,
  «Bajar uno», «Último», «Mover a la posición…» (lista 1…N). Nunca solo arrastrar (N12).
- Hipótesis: que descubra la pulsación larga sola; por eso la ayuda la nombra y el «⋯» siempre está
  (validar con `perfil-cliente-pyme.md` §5, pregunta 6).

## 3. Textos exactos

- Botón: **«Ordenar tu menú»**; al terminar **«Listo»**. Título: **«¿Qué quieres que vean primero?»**
- Ayuda: **«Así los ve tu cliente en WhatsApp. Mantén pulsado y arrastra, o toca ⋯.»** Pestañas:
  **«Categorías»** · **«Productos»**.
- Línea de corte, tras el 9.º producto (divisor punteado, como en el paso 2): **«Hasta aquí se ve
  sin tocar «Ver más»»**.
- `aria-label` del asa: «Mover «Shawarmas», posición 3 de 5» / «Mover «Shawarma mixto», posición 2
  de 6 en «Shawarmas»». Del «⋯»: «Más opciones para «Shawarma mixto»».
- Se guarda al soltar (sin «Guardar»); aviso 6 s: **«Listo: «Shawarmas» va primero en tu menú.»** [**Deshacer**]. Si falla: «No pudimos
  guardar el orden. Revisa tu conexión y vuelve a moverlo.» (la fila vuelve a su lugar).
- Sin productos: **«Todavía no tienes productos. Agrega el primero y aquí eliges en qué orden los
  ven tus clientes.»** [Agregar producto].
- Un solo producto o una sola categoría (sin asas ni «⋯»): **«Con uno solo no hay nada que ordenar.
  Cuando agregues otro, aquí eliges cuál va primero.»**
- Revisión de lo encontrado: título **«Así queda tu menú»**, ayuda **«Lo nuevo va al final. Muévelo
  si quieres que se vea antes.»**, marca **«Nuevo»** (`tone_badge`), botón **«Agregar a mi menú»**.
- Paso 3 de WhatsApp: «Tu cliente los ve en este orden.» + enlace **«Cambiar el orden»**.

## 4. Maquetas a 375 px

```
«Tus productos» · ordenar               Revisión de lo encontrado
┌──────────────────────────────────┐    ┌──────────────────────────────────┐
│ ‹ Volver a tus productos         │    │ ‹ Volver a lo que encontramos    │
│ ¿Qué quieres que vean primero?   │    │ Así queda tu menú                │
│ Así los ve tu cliente en         │    │ Lo nuevo va al final. Muévelo si │
│ WhatsApp. Mantén pulsado y       │    │ quieres que se vea antes.        │
│ arrastra, o toca ⋯.              │    ├──────────────────────────────────┤
│ [ Categorías ]  Productos        │    │ Shawarmas                        │
├──────────────────────────────────┤    │ ⠿ Shawarma clásico   5 $     ⋯   │
│ ⠿ Shawarmas        6 productos ⋯ │    │ ⠿ Shawarma mixto     5 $     ⋯   │
│ ⠿ Combos           3 productos ⋯ │    │ ⠿ Shawarma XL [Nuevo] 7 $    ⋯   │
│ ⠿ Ensaladas        4 productos ⋯ │    │ Bebidas                          │
│ ⠿ Bebidas          5 productos ⋯ │    │ ⠿ Té frío            1 $     ⋯   │
│ ⠿ Otros            1 producto  ⋯ │    │ Postres  [Nuevo]                 │
├──────────────────────────────────┤    │ ⠿ Baklava [Nuevo]    2 $     ⋯   │
│ (pestaña Productos:)             │    ├──────────────────────────────────┤
│ Shawarmas                        │    │ Atrás      [ Agregar a mi menú ] │
│ ⠿ Shawarma clásico   5 $     ⋯   │    └──────────────────────────────────┘
│ ⠿ Shawarma mixto     5 $     ⋯   │
│ … Combos (3) …                   │
│ - - Hasta aquí se ve sin tocar - │
│ - - «Ver más» - - - - - - - - -  │
│                       [ Listo ]  │
└──────────────────────────────────┘
```

## 5. Lo que ve el cliente en WhatsApp

- **Una sección por categoría, en el orden elegido**, y sus productos en su orden; el selector del
  chat («Foto o menú» → Tus productos) igual.
- Un mensaje de lista admite 10 filas: con más de 10 productos van **9 por pantalla + «Ver más»**
  (`menus/engine.py`, `_pages`). Por eso **los 9 primeros del orden son la primera pantalla**: si
  Bianki pone «Shawarmas» (6) y «Combos» (3) arriba, su cliente ve exactamente eso sin tocar nada.
  La línea de corte del §3 lo hace visible al ordenar.

## 6. Qué entra en la primera entrega

1. **PR 1 (arregla a Bianki ya):** orden de categorías y de productos en «Tus productos» (pestañas,
   «⋯» con posiciones, arrastre con `assets/rank-drag.js` agrupado por categoría, «Deshacer»); la
   lista de WhatsApp y el selector del chat lo usan; paso 3 en modo lectura con «Cambiar el orden».
   Datos: `brand_products.position` ya existe; falta guardar el **orden de categorías por marca**
   (eso es de `backend-engineer`, con su migración y RLS). Valor inicial = el orden actual.
2. **PR 2:** reordenar en la revisión de lo encontrado, y el mismo gesto en el paso 2 del menú
   (m-24955644, cambia «Subir / Bajar» por asa + «⋯»).
3. **Fuera:** ordenar por precio o A-Z con un toque, «Más vendidos» automáticos, arrastrar entre grupos.

**Diseño:** `DragCard` + `rank-drag.js` ya existen (fotos del Catálogo). Lo único a añadir: **una fila
ordenable** en `Qualify/ui/` (asa + texto + «⋯», `data-rank-group` por categoría, teclado en el asa),
reutilizada en m-24955644. Patrón nuevo: lo decide el fundador.
