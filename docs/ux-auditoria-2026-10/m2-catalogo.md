# M2 · Catálogo de productos (`/catalog`) — auditoría de experiencia

Archivos: `Qualify/catalog_page.py`, `Qualify/catalog_state.py`, `Qualify/catalog_vm.py`, entrada del
menú en `Qualify/ui/layout.py:93`, página en `Qualify/Qualify.py:449-454`. Solo sugerencias: no se
tocó código.

## (a) Qué hace este módulo, en palabras del dueño

1. «Subo la foto real de lo que vendo (el shawarma, el helado) desde el celular, con su nombre y, si quiero, su precio.»
2. «Corrijo el nombre o el precio, cambio la foto principal o borro una foto que salió mal.»
3. «Después elijo ese producto cuando quiero una publicación, y sale con mi foto de verdad, no una imagen inventada.»

## (b) Hallazgos, ordenados

Severidad: 1 = no puede terminar · 2 = se pierde, pierde datos o queda sin salida · 3 = palabras que
no entiende / lenguaje de herramienta · 4 = accesibilidad y celular · 5 = pulido.

### 1. Después de crear el producto no hay camino a «hacer una publicación con él» · sev 2 · M
- **Dónde:** `catalog_state.py:54-55` (`_CREATED`, `_CREATED_WITH_FILES`), `catalog_state.py:358-362`
  (el editor no se abre y no hay enlace), `catalog_page.py:535-645` (el editor no tiene ninguna
  acción hacia Crear pieza ni Variaciones).
- **El dueño:** «Ya subí mi producto… ¿y ahora qué? ¿Dónde hago la publicación?»
- **Arreglo:** el aviso y el editor llevan la siguiente acción del trabajo del dueño. Aviso:
  «Listo, tu producto ya está guardado. ¿Hacemos una publicación con él?» con el botón
  «Crear publicación» → `/create` con ese producto ya elegido (requiere que Crear pieza acepte el
  producto en la dirección: hoy `/create` no lee ningún parámetro). En el editor, botón soft
  «Crear publicación con este producto» al lado de «Guardar cambios», desactivado con el motivo
  «Primero súbele una foto» si no tiene fotos.
  ```
  ┌ Shawarma mixto ─────────────── [Eliminar] [Cerrar] ┐
  │ … datos y fotos …                                  │
  │        [Guardar cambios]  [✦ Crear publicación]     │
  └────────────────────────────────────────────────────┘
  ```

### 2. Cerrar el editor o tocar otro producto borra los cambios sin avisar · sev 2 · S
- **Dónde:** `catalog_state.py:448-452` (`close_editor`), `catalog_state.py:388-399`
  (`select_product` vuelve a llenar el formulario), botón «Cerrar» en `catalog_page.py:576-583`.
- **El dueño:** «Le cambié el precio y cerré… y quedó el precio viejo.»
- **Arreglo:** si hay cambios sin guardar, al cerrar o cambiar de producto se abre el diálogo de
  acción destructiva (DS §6.2): título «¿Salir sin guardar?», cuerpo «Los cambios de «Shawarma
  mixto» se van a perder.», botones «Volver» / «Guardar y salir». Alternativa más simple: guardar
  solo al salir del campo y mostrar «Guardado» debajo.

### 3. En el celular, el editor aparece arriba de todo y el dueño no lo ve · sev 2 · M
- **Dónde:** `catalog_page.py:836-837` (formulario y editor van antes de la grilla en `page_body`);
  no hay desplazamiento al abrir (`select_product`, `catalog_state.py:388`).
- **El dueño:** con 10 productos en una columna (`_grid`, `initial="1"`, `catalog_page.py:775`) toca
  el octavo y «no pasa nada»: el editor se abrió fuera de la pantalla, varias tarjetas más arriba.
- **Arreglo:** abrir el producto en el `drawer` del sistema (DS §5.8: pantalla completa en el
  celular, se cierra con «Atrás» y no pierde la lista de fondo) o en su propia ruta
  `/catalog/[product_id]` (ver §c). Sin componentes nuevos.

### 4. Crear un producto es un formulario de 6 campos de 3 temas distintos · sev 3 · M
- **Dónde:** `catalog_page.py:163-233` (`_new_product_form`: nombre, categoría, descripción,
  precio, moneda, fotos); la foto, que es lo único que la herramienta no puede inventar
  (docstring, línea 3), está al final.
- **El dueño:** «Solo quiero subir la foto del combo.» Ve seis cosas por llenar y lo deja para después.
- **Arreglo (pasos cortos con `stepper`, DS §5.8, dentro del `drawer`):**
  ```
  ① La foto                     ② ¿Cómo se llama?             ③ Listo
  ┌──────────────────────┐      Nombre [Shawarma mixto  ]     [foto] Shawarma mixto
  │  📷 Toca para tomar   │      Precio (si quieres que         $ 18.000
  │  o elegir fotos      │      salga en la publicación)
  └──────────────────────┘      [ 18000 ] COP                 [Crear publicación]
  [foto][foto][+]               ▸ Más detalles (opcional)     [Agregar otro producto]
  [ Siguiente ]                   categoría, descripción
                                [Atrás] [Guardar producto]
  ```
  Paso 1 = fotos (se puede saltar con «Sin foto por ahora»); paso 2 = nombre + precio, con
  categoría y descripción detrás de «Más detalles» (qualify-ux §4.6); paso 3 = confirmación que
  enlaza con el hallazgo 1. La moneda viene ya elegida (hallazgo 6).

### 5. Textos que hablan de la herramienta o usan palabras prohibidas · sev 3 · S
| Dónde | Hoy | Propuesta |
|---|---|---|
| `catalog_page.py:809-810` | «Catálogo» / «Tus productos con sus fotos reales: lo que las plantillas componen.» | «Tus productos» / «Sube la foto real de lo que vendes y úsala en tus publicaciones.» |
| `catalog_page.py:784-786` | «Aún no hay productos» / «…con eso una plantilla ya produce Reel, feed e historia.» | «Aún no tienes productos» / «Sube tu primer producto con una o dos fotos reales: con eso ya puedes crear publicaciones e historias que se ven como lo que vendes.» |
| `catalog_page.py:151` | «Ayuda a escribir el gancho; no se imprime entera.» | «Nos ayuda a escribir el texto de la publicación. No se copia tal cual.» |
| `catalog_page.py:653-654` | «…desaparece del catálogo y de Crear pieza. Las piezas que ya se hicieron con él se conservan.» | «…ya no aparecerá para crear publicaciones. Las publicaciones que ya hiciste con él no cambian.» |
| `catalog_page.py:93-94` | «…las piezas no mostrarán ningún precio; si lo escribes, se imprime exactamente así.» | «Opcional. Si lo dejas vacío, la publicación no muestra precio. Si lo escribes, sale tal cual.» |
| `catalog_page.py:470` | «Corrigiendo y recortando cada archivo antes de guardarlo.» | «Acomodando cada foto para que se vea bien. Puedes seguir usando la pantalla.» |
| `catalog_page.py:494` | «Hasta 12» | «Puedes subir hasta 12» |

### 6. La moneda es una lista de 10 códigos (USD, UYU, COP, VES…) · sev 3 · S
- **Dónde:** `catalog_page.py:82-87`, `catalog_vm.py:30-34`.
- **El dueño:** «¿VES? ¿UYU?» Un dueño de Táchira no busca su moneda en una lista de siglas.
- **Arreglo:** la moneda viene elegida con la del negocio (qualify-copy-es regla 5) y se muestra
  con su nombre: «Pesos colombianos (COP)», «Bolívares (VES)», «Dólares (USD)», «Pesos uruguayos
  (UYU)»; las demás detrás de «Otra moneda». «Sin moneda» desaparece del camino principal: si no
  hay precio, no hace falta moneda. *Hipótesis:* en Venezuela algunos locales ponen el precio en
  dólares; validar con la pregunta §5.4 (qué palabras y qué moneda usa en sus redes).

### 7. «Arrastra… o haz clic» y «JPG, PNG, HEIC · MP4, MOV» en un celular · sev 3 · S
- **Dónde:** `catalog_page.py:296-302` y `catalog_page.py:440-446`.
- **El dueño:** en el celular no se arrastra ni se hace clic; las siglas no le dicen nada.
- **Arreglo:** texto principal «Toca para tomar una foto o elegirla de tu galería»; secundario
  «Fotos o videos cortos (hasta 15 segundos).» En pantallas anchas se puede añadir «o arrástralas
  aquí». Los formatos solo aparecen en el error si suben uno que no sirve: «Ese archivo no es una
  foto ni un video. Prueba con otra foto de tu galería.»

### 8. Botones de cada foto (estrella / papelera) de unos 24 px y sin confirmación · sev 4 · S
- **Dónde:** `catalog_page.py:389-414` (`icon_button size="1"`, una al lado de la otra), acción
  inmediata `CatalogState.delete_media` (`catalog_state.py:708`).
- **El dueño:** quiere marcar la principal con el pulgar y borra la foto; no hay forma de deshacer.
- **Arreglo:** botones size 2 con texto visible («Principal», «Quitar»), separados por el espaciador;
  la papelera pide confirmación corta («¿Quitar esta foto?» · «Volver» / «Sí, quitar») o deja un
  aviso con «Deshacer» durante 5 s. Hoy los nombres solo están en `tooltip` (no existen en
  pantalla táctil, DS §8).

### 9. El lápiz «Editar» de la tarjeta solo se explica al pasar el mouse · sev 4 · S
- **Dónde:** `catalog_page.py:747-758` (tooltip sobre un `aria-hidden`), y la tarjeta entera es
  `card(on_click=…, role="button")` (`catalog_page.py:759-768`), justo lo que DS §8 prohíbe
  (`rx.box` + `on_click`) y §5.9 resuelve con `choice_card` (un `<button>` real).
- **El dueño:** en el celular no sabe que tocar la tarjeta abre el producto; el lector de pantalla
  no anuncia el nombre como acción.
- **Arreglo:** la tarjeta como `<button>` real con `aria-label="Editar Shawarma mixto"`; el lápiz
  acompañado de la palabra «Editar» visible en la fila de abajo (no sobre la foto).

### 10. Mensajes de error técnicos y sin siguiente paso · sev 3 · S
- **Dónde:** `catalog_state.py:49-50`.
- **Hoy / propuesta:**
  - «Este negocio no tiene ninguna marca provisionada todavía.» → «Primero completa tu marca (logo y
    colores) y vuelve a subir tus productos.» + enlace «Completar mi marca».
  - «No se pudo hablar con la base de datos. Inténtalo de nuevo en un momento.» → «No pudimos
    guardar ahora. Revisa tu conexión e inténtalo otra vez en un minuto.»
  - `catalog_state.py:53` «…no es visible para este negocio.» → «Ese producto ya no está en tu
    catálogo. Actualiza la página.»

### 11. Datos técnicos en cada foto («Foto · 1080×1350») · sev 5 · S
- **Dónde:** `catalog_vm.py:192-199` (`media_meta_label`), mostrado en `catalog_page.py:381-387`.
- **El dueño:** «¿Qué es 1080×1350?»
- **Arreglo:** foto = solo «Foto»; video = «Video · 7 s». Si la foto es muy pequeña para una
  publicación, decirlo en palabras: `tone_badge("Se verá borrosa", "warn")`.

### 12. Productos sin foto no se distinguen y no se pueden usar bien · sev 5 · S
- **Dónde:** `catalog_vm.py:189` («Sin fotos» como texto gris), `catalog_page.py:727-733`.
- **El dueño:** no sabe que a ese producto le falta lo más importante para publicar.
- **Arreglo:** `tone_badge("Falta la foto", "warn")` en la tarjeta, y en la cabecera del catálogo
  «3 productos · 1 sin foto» que filtra al tocarlo. Estado nunca solo por color (DS §8).

## (c) Navegación

### Cómo está hoy
```
Menú › Negocio › «Catálogo»  (layout.py:93, al lado de «Brand Kit»)
  └─ /catalog  — pestaña «Qualify · Catálogo» (Qualify.py:453)
       una sola página, todo apilado:
       [aviso de carga de fotos] → [formulario Nuevo producto] → [editor del producto] → [grilla]
       · «Nuevo producto» abre el formulario arriba; al crear, se cierra y NO abre el producto
       · tocar una tarjeta abre el editor arriba (fuera de vista en el celular); tocarla de nuevo lo cierra
       · «Cerrar» / «Eliminar» vuelven a la grilla; ninguna acción lleva a otro módulo
Entradas desde otros módulos (solo de ida):
  · Crear pieza › «Ir al catálogo» (content_generator.py:1571) — sale de Crear pieza sin forma de volver
  · Variaciones › estado vacío «Ir a Catálogo» (variations_view.py:161) — tampoco hay regreso
```
Problemas: (1) callejón sin salida después de crear o editar: el siguiente trabajo del dueño
(hacer una publicación) no está a un toque; (2) el viaje Crear pieza → Catálogo → Crear pieza
obliga a volver por el menú y, *hipótesis*, a empezar la pieza de nuevo; (3) el editor no tiene
dirección propia: no se puede compartir ni volver «Atrás» del celular para cerrarlo; (4) el
nombre del menú está en la zona «Negocio» junto a «Brand Kit» (palabra prohibida), lejos de
«Crear pieza», que es donde se usa.

### Propuesta
```
Menú › Negocio › «Tus productos»                  pestaña: «Qualify · Tus productos»
  /catalog                          lista (grilla), título h1 «Tus productos»,
                                    acción principal «Agregar producto»
  /catalog/nuevo                    3 pasos (Foto → Nombre y precio → Listo), en drawer o ruta
                                    pestaña «Qualify · Nuevo producto»
  /catalog/[product_id]             el producto: datos + fotos; «Atrás» del celular vuelve a la lista
                                    pestaña «Qualify · <nombre del producto>»
        └─ «Crear publicación con este producto» → /create?producto=<id>
  Volver al origen: si se llegó desde Crear pieza o Variaciones (?volver=/create), el paso
  «Listo» dice «Volver a tu publicación» y regresa con el producto ya elegido.
```
Reglas del patrón (para la guía de navegación general): toda pantalla que termina un trabajo
ofrece **la siguiente acción del dueño** como botón; toda ida desde otro módulo **regresa al
origen** con lo creado ya elegido; cada objeto editable tiene **su propia dirección** para que el
botón «Atrás» del celular funcione; el título de la pestaña y el `page_header` dicen **lo mismo**.

## (d) Historias de usuario propuestas

### Grupo A · Agregar un producto desde el celular
1. **Como dueño, quiero subir la foto de mi producto con la cámara del celular en el primer paso,
   para tenerlo listo en menos de un minuto.**
   - El primer paso de «Agregar producto» es la foto; el texto dice «Toca para tomar una foto o
     elegirla de tu galería» (sin «arrastra», «haz clic» ni siglas de formato).
   - Se puede seguir sin foto con «Sin foto por ahora»; el producto queda con la marca «Falta la foto».
   - En 360 px de ancho todo cabe en una columna y los botones miden al menos 44 px.
2. **Como dueño, quiero que solo me pidan el nombre y, si quiero, el precio, para no llenar un
   formulario largo.**
   - El paso 2 muestra nombre y precio; categoría y descripción quedan detrás de «Más detalles».
   - La moneda viene elegida con la del negocio y se lee por su nombre («Pesos colombianos»).
   - «Atrás» vuelve al paso de la foto sin perder lo escrito; se muestra «Paso 2 de 3».

### Grupo B · Editar sin perder nada
3. **Como dueño, quiero que me avisen si salgo sin guardar, para no perder el precio que corregí.**
   - Cerrar, tocar otro producto o ir «Atrás» con cambios sin guardar abre «¿Salir sin guardar?».
   - El diálogo ofrece «Volver» y «Guardar y salir».
4. **Como dueño, quiero abrir un producto y verlo en pantalla completa, para editarlo con una mano.**
   - Tocar una tarjeta abre el producto en pantalla completa en el celular (drawer o `/catalog/[id]`).
   - El botón «Atrás» del celular lo cierra y deja la lista donde estaba.
   - La tarjeta es un botón real con el nombre del producto anunciado («Editar Shawarma mixto»).
5. **Como dueño, quiero marcar la foto principal y quitar fotos sin equivocarme, para que mis
   publicaciones salgan con la foto correcta.**
   - «Principal» y «Quitar» se leen como texto y miden al menos 44 px.
   - Quitar una foto pide confirmación o permite «Deshacer» durante 5 segundos.
   - Debajo de cada foto no aparecen medidas en píxeles.

### Grupo C · Del producto a la publicación
6. **Como dueño, quiero crear una publicación desde mi producto con un toque, para no buscarlo
   otra vez en otra pantalla.**
   - El paso «Listo» y la ficha del producto muestran «Crear publicación con este producto».
   - Al tocarlo, Crear pieza abre con ese producto ya elegido.
   - Si el producto no tiene foto, el botón está desactivado y dice «Primero súbele una foto».
7. **Como dueño, quiero volver a mi publicación después de agregar un producto que faltaba, para no
   empezar de cero.**
   - Desde Crear pieza o Variaciones, «Ir al catálogo» abre «Agregar producto» con regreso marcado.
   - Al terminar, el botón dice «Volver a tu publicación» y regresa con el producto elegido.
   - *Hipótesis* (pregunta §5.6): el dueño llega al catálogo desde Crear pieza más a menudo que
     desde el menú.

### Grupo D · Palabras que entiende
8. **Como dueño, quiero que la pantalla me hable de lo que gano y en mis palabras, para entenderla
   sin preguntar a nadie.**
   - Título, pestaña y menú dicen «Tus productos»; ningún texto usa «plantilla», «Reel», «feed»,
     «pieza», «gancho», «provisionada» ni «base de datos».
   - Los errores dicen qué pasó y qué hacer (lista del hallazgo 10).
   - La revisión de textos pasa la lista de palabras prohibidas de `qualify-ux` §3.
