# Agrupar los productos en categorías (m-24955838)

2026-11-06. Los 22 productos de Bianki (cargados desde su página) no tienen categoría: WhatsApp los
muestra en una sola lista, la pestaña «Categorías» está vacía y «Catering oficina» (45 $) sale
primero. Sigue a `docs/ux-orden-de-productos.md` (m-24955643, PR #478). **Una palabra:** «categoría» (es el nombre del campo y de la pestaña, N1). «Agrupar» solo como verbo.

## 1. El aviso y dónde sale
Texto: **«Tienes 22 productos sin categoría. En WhatsApp salen todos en una sola lista larga.»**
Botón único: **«Agruparlos»** → abre el recorrido del §2. El aviso desaparece cuando la cuenta llega a 0.
- **Tus productos:** `callout` arriba de la lista. Solo si hay 2 productos o más sin categoría.
- **Ordenar tu menú → Categorías**, cuando solo existe «Otros»: en lugar de la lista vacía,
  «Todos tus productos están en «Otros». Agrúpalos para que tu cliente encuentre rápido lo que
  busca.» [**Agrupar tus productos**] (N4: ningún estado vacío sin salida).
- **Menú de WhatsApp, paso 3:** una línea con el enlace «Agruparlos», porque ahí ve el efecto.

## 2. «Agrupa tus productos» (dos pasos, una decisión cada uno)
**Paso 1 de 2 — «Te proponemos estos grupos»** (de `suggest_groups`). Ayuda: «Los juntamos por la
primera palabra del nombre. Revisa cada uno.» Una tarjeta por grupo: nombre, cuántos y los nombres.
Cada tarjeta empieza **aceptada**. Sus opciones: «Cambiar nombre» y «No agrupar» (la tarjeta queda
atenuada con «Deshacer»). El botón **«Siguiente»** guarda las aceptadas (`set_products_category`
por grupo). Sin propuestas, se salta al paso 2 y no se muestra «Paso N de M» (M real, N6).
- «Cambiar nombre»: campo «Nombre de la categoría», ayuda **«Hasta 24 letras: es el título que ve
  tu cliente en WhatsApp.»**, contador «8 de 24». Ejemplo en el campo: «Por ejemplo: Bebidas».

**Paso 2 de 2 — «¿Dónde va cada uno de estos?»** Ayuda: «Marca los que van juntos y toca «Poner
en…».» Lista con casillas de 44 px (fila entera tocable). Barra fija abajo: «3 elegidos» +
**«Poner en…»**. Se abre una hoja con las categorías existentes y **«+ Nueva categoría»** (el mismo
campo de 24 letras), botón «Poner aquí». Los productos salen de la lista y la barra vuelve a
«Poner en…». Abajo siempre: **«Dejar el resto en «Otros»»**. Al vaciar la lista se termina solo.

**Final:** «Listo: tu menú tiene 5 categorías.» + «Así los ve tu cliente en WhatsApp: elige qué va
primero.» [**Ordenar tu menú**] · «Volver a tus productos». Las categorías nuevas se ponen en el
orden del recorrido y «Otros» queda de último.

## 3. Varios a la vez en «Ordenar tu menú» → Productos
Enlace **«Elegir varios»** encima de la lista. Las asas pasan a ser casillas. Barra fija: «2 elegidos» +
**«Mover a otra categoría»**, que abre la misma hoja del §2. Los productos movidos van **al final** de
la categoría de destino. «Cancelar» devuelve las asas.

## 4. En la revisión de lo encontrado (foto, PDF o página)
- Cada producto nuevo muestra su categoría propuesta como etiqueta tocable: «Combos ✎». Al tocarla
  se abre la misma hoja. Si la categoría no existía, la etiqueta lleva «Nueva» (`tone_badge`).
- Línea arriba de la lista: **«Vamos a crear 4 categorías: Combos, Shawarmas, Ensaladas y Bebidas.
  Cámbialas si quieres.»** Se crean solo al tocar «Agregar a mi menú».
- Si no se propuso ninguna, la etiqueta dice «Sin categoría ✎» y el producto queda en «Otros».

## 5. Textos que faltan
- Al guardar: **«Listo: 5 productos ahora están en «Combos».»** [**Deshacer**] (6 s) → «Listo: volvieron a «Otros».»
- Error: «No pudimos guardar la categoría. Revisa tu conexión y vuelve a intentarlo.»
- Nombre vacío: «Escribe el nombre de la categoría.» Nombre repetido: el producto se suma a la que
  ya existe, sin crear otra igual (sin distinguir mayúsculas).
- Nada sin categoría (enlace viejo): «Todos tus productos ya tienen categoría.» [Ordenar tu menú].
- **En WhatsApp** («Ver menú y pedir»): una sección por categoría en el orden elegido (Combos,
  Shawarmas, Ensaladas, Papas, Bebidas, Otros). Hay 9 filas por pantalla, así que la primera muestra
  los 5 combos, los 3 shawarmas y la primera ensalada; el resto sale con «Ver más». «Catering
  oficina» deja de salir primero.

## 6. Maquetas a 375 px
```
Paso 1 de 2                              Paso 2 de 2
┌──────────────────────────────────┐    ┌──────────────────────────────────┐
│ ‹ Volver a tus productos         │    │ ‹ Volver a los grupos            │
│ Paso 1 de 2                      │    │ Paso 2 de 2                      │
│ Te proponemos estos grupos       │    │ ¿Dónde va cada uno de estos?     │
│ Los juntamos por la primera      │    │ Marca los que van juntos y toca  │
│ palabra del nombre.              │    │ «Poner en…».                     │
├──────────────────────────────────┤    ├──────────────────────────────────┤
│ Combos · 5 productos     ✓       │    │ [✓] Coca-Cola Original           │
│ Combo Vecino, Combo Shawarma,    │    │ [✓] 7UP                          │
│ Combo Carne, Combo Mixto, …      │    │ [✓] Pepsi                        │
│ Cambiar nombre · No agrupar      │    │ [ ] Jugo natural del día         │
├──────────────────────────────────┤    │ [ ] Golden Kolita                │
│ Shawarmas · 3 productos  ✓       │    │ [ ] Salchipapa                   │
│ Ensaladas · 5 productos  ✓       │    │ [ ] Catering oficina      45 $   │
│ Papas · 2 productos      ✓       │    │ Dejar el resto en «Otros»        │
├──────────────────────────────────┤    ├──────────────────────────────────┤
│ Quedan 7 para el paso 2          │    │ 3 elegidos       [ Poner en… ]   │
│                  [ Siguiente ]   │    └──────────────────────────────────┘
└──────────────────────────────────┘
```

## 7. Primera entrega
1. **PR 1 (arregla a Bianki ya):** el aviso en Tus productos y en Categorías vacía; el recorrido de
   2 pasos; la categoría propuesta y editable por producto en la revisión de lo encontrado.
2. **PR 2:** «Elegir varios» en Ordenar → Productos, el aviso en el paso 3 de WhatsApp y elegir
   varios en la revisión de lo encontrado.
3. **Fuera:** sugerir con IA los que quedan sueltos, borrar o fusionar categorías, renombrar una
   categoría existente desde la pestaña «Categorías».

## 8. Decisiones de la primera entrega (2026-11-06)
- «Dejar el resto en «Otros»» esconde el aviso hasta que aparezca un producto NUEVO sin categoría.
  Se recuerda **durante la sesión** (los productos que quedaron en «Otros», en el estado de
  Catálogo; se borra al cerrar sesión o cambiar de negocio): la app no guarda avisos descartados en
  ninguna tabla ni en el navegador, y hacerlo pide un cambio de esquema.
- Sin pista automática para un producto suelto («Catering oficina»): lo decide el dueño en el paso 2.
- El aviso del paso 3 de WhatsApp entra ya en esta entrega; «Elegir varios» en Ordenar → Productos
  sigue para la segunda.
- En la revisión de lo encontrado la categoría se cambia con un campo en la misma fila (no con la
  hoja del paso 2): una fila, una decisión, y nada se guarda antes de «Agregar…».
