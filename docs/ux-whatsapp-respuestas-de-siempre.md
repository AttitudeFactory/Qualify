# Menú de WhatsApp: «Respuestas de siempre», ya listas para usar

> Propuesta de experiencia (ux-designer, 2026-11-03). Pedido del fundador después de configurar el
> menú del número de Bianki: «me dio ansiedad, se sintió complicado». Objetivo: que el menú
> **llegue lleno** y el dueño solo complete o quite. Se apoya en el flujo de 4 pasos que ya existe
> (m-24848536, `Qualify/whatsapp_tab_menu.py`, `GUIDED_*` en `Qualify/whatsapp_menu_vm.py`) y en
> el ejemplo `BIANKI_DEMO_MENU`. Reglas: `qualify-ux`, `qualify-copy-es`, `docs/ux-guia-navegacion.md`
> (N3, N6, N6b). Sin componentes ni colores nuevos: `step_frame`, `choice_card`, `callout`,
> `signal_pill`, `chat_bubble`, `empty_state`, `skeleton_card` de `Qualify/ui/`.
> No se revisó en la app corriendo: es una propuesta de flujo, no una revisión.

## 1. Decisiones de diseño

1. **El menú nace lleno.** Al crearlo, cada respuesta trae un texto escrito con lo que Qualify ya
   sabe (nombre de la marca, dirección del perfil de WhatsApp, catálogo). Lo que no sabe va como
   **hueco a la vista entre corchetes**: `[hora de abrir]`. El dueño ve debajo «Falta: hora de
   abrir». Nunca se inventa un dato (la dirección «Calle 10 # 5-20» y el horario «12:00 a 22:00»
   del ejemplo actual desaparecen).
2. **Un hueco sin llenar nunca le llega a un cliente.** Al publicar, si queda alguno, se dice cuál
   y se ofrece «Quitar las que faltan y publicar» (nunca un bloqueo mudo).
3. **Una sola lista ordenada en vez de «botones» + «más botones».** El dueño piensa en *qué le
   preguntan*, no en botones. Las primeras de la lista son los botones; una raya marca dónde
   terminan, y lo de abajo va solo a la lista «Más preguntas». El límite de 3 se **ve** en la
   pantalla, siempre. «Mostrar más botones» y «Más opciones (avanzado)» dejan de ser el camino.
4. **El paso 2 cambia de pregunta:** de «¿Qué botones ve al escribirte?» a «¿Qué te preguntan
   siempre?». Se mantienen 4 pasos (M real = 4; 5 si el dueño elige empezar desde una foto).
5. **La IA propone, el dueño decide.** «Sugerir con IA» reemplaza el texto del campo y se puede
   deshacer; «Cargar desde una foto o tu página» muestra lo que encontró, con la prueba, y cada dato
   se acepta o se edita uno por uno. Nada se publica ni se envía solo.
6. **El catálogo manda sobre los precios.** Lo que salga de una foto se propone; nunca reemplaza un
   producto ni un precio que ya está cargado.

## 2. El recorrido del dueño

Marco de pasos (N6b): arriba «‹ WhatsApp», «Paso N de 4» con barra y el título; abajo, fijo,
«Atrás» · botón principal · «Seguir después».

### Paso 0 (solo al crear el menú, opcional) — «¿Cómo empezamos tu menú?»

- **Ayuda:** «Ya lo dejamos casi listo. Elige de dónde sacamos tus datos.»
- **Decisión única** (`choice_card`, una sola elección, la primera marcada):
  - «Con lo que ya sabemos de Bianki» — *Tu nombre, tu dirección y tus productos. Tú completas lo que falte.*
  - «Desde una foto de tu menú o tu volante» — *Leemos horarios, precios y formas de pago.*
  - «Desde tu página o tu Instagram» — *Pega el enlace y leemos lo que ahí dice.*
- **Botón:** «Siguiente». Las dos últimas abren §4; la primera va directo al Paso 1.

### Paso 1 de 4 — «¿Cómo saludas?»

- **Ayuda:** «Es lo primero que lee tu cliente cuando te escribe.» (igual que hoy)
- **Decisión:** el saludo. **Ya escrito:**
  «¡Hola! Gracias por escribir a Bianki. Aquí ves el menú, haces tu pedido y resuelves tus dudas.»
- Debajo del campo: «Sugerir con IA» (§5). **Botón:** «Siguiente».

### Paso 2 de 4 — «¿Qué te preguntan siempre?»

- **Ayuda:** «Deja listas las respuestas a lo que más te preguntan. Tu cliente las toca y recibe
  la respuesta al instante.»
- **Decisión:** qué respuestas dejas y en qué orden. Cada fila: nombre, una línea del texto,
  `signal_pill` «Lista» o «Falta completar», y «Editar». Tocar la fila abre su texto (panel).
- Enlace secundario arriba: «Completar desde una foto o tu página» (§4, se puede usar en cualquier
  momento).
- **Botón:** «Siguiente». Con huecos sin llenar se puede seguir: el Paso 4 los recuerda.

**Respuestas con las que nace el menú de comida** (nombre ≤ 20 caracteres, para que pueda ser
botón o fila de la lista):

| Nombre | Qué pasa al tocarla | Texto ya escrito (huecos entre corchetes) |
|---|---|---|
| Ver menú y pedir | Muestra tus productos | *Sin texto que llenar: salen de tu catálogo con su precio.* |
| Horario | Responde con un mensaje | «Abrimos de [qué días], de [hora de abrir] a [hora de cerrar]. Cuando quieras pedir, escribe *menú*.» |
| Domicilio | Responde con un mensaje | Pregunta previa en el panel, «¿Llevas pedidos a domicilio?» Sí / No. **Sí:** «Llevamos tu pedido a [barrios o zona]. El envío cuesta [precio del envío] y tarda unos [minutos] minutos. Para pedir, escribe *menú*.» **No:** «Por ahora no llevamos a domicilio. Puedes pasar a buscar tu pedido en [dirección].» |
| Dónde estamos | Responde con un mensaje | Con dirección en el perfil de WhatsApp: «Estamos en {dirección del perfil}. ¡Te esperamos!» Sin ella: «Estamos en [dirección y barrio]. ¡Te esperamos!» |
| Formas de pago | Responde con un mensaje | «Puedes pagar con [formas de pago: efectivo, transferencia…]. Te confirmamos el total antes de pagar.» `signal_pill` «Sugerida». |
| Reservas | Responde y te pasa el chat | «Para reservar, escríbenos el día, la hora y para cuántas personas. Te confirmamos en [cuánto tardas en responder].» `signal_pill` «Sugerida». |
| Hablar con alguien | Te pasa el chat | «Te paso con una persona del equipo; en un momento te responden.» (también responde cuando el cliente escribe algo que el menú no entiende) |

«Precios» no es una respuesta aparte: «Ver menú y pedir» ya muestra cada producto con su precio.
Si el dueño la busca, la ayuda del panel dice «Tus precios salen de tu catálogo. Cámbialos en
Catálogo.» Otros rubros nacen con su propio juego (agencia de viajes: «Ver paquetes», «Requisitos
del viaje», «Formas de pago»; inmobiliaria: «Ver propiedades», «Agendar una visita», «Requisitos
para alquilar») — **hipótesis**: qué pregunta cada rubro hay que confirmarlo (§8, pregunta 1).

**Cómo se reparten en el primer mensaje** (regla de WhatsApp: 3 botones; una lista, 10 filas):

- Hasta 3 respuestas: las 3 son botones.
- Más de 3: las **2 primeras** son botones y el tercero es **«Más preguntas»**, que abre la lista
  con todas las demás (hasta 10). Máximo total: 12 respuestas.
- Orden inicial de Bianki: «Ver menú y pedir», «Domicilio» | raya | Horario, Dónde estamos, Formas
  de pago, Reservas, Hablar con alguien (**hipótesis**: lo más preguntado arriba, §8 pregunta 1).
- Para cambiar el orden (m-24955644): se **arrastra** cada fila por su asa (la del sistema de
  diseño, `sort_handle`: con el dedo, el ratón o el teclado) y el «⋯» de cada fila ofrece «Subir»,
  «Bajar» y «Mover al principio» (nunca solo arrastrar). Ayuda arriba de la lista: «Arrastra para
  cambiar el orden. Las dos primeras salen como botones; el resto, en «Más preguntas».» (con 2 o
  3 respuestas: «Arrastra para cambiar el orden. Así salen los botones en WhatsApp.»).

**Panel de una respuesta (se abre al tocar «Editar»)**

- Título: el nombre de la respuesta. Campo 1 «Nombre (lo que ve tu cliente)» con contador «9 de
  20». Campo 2 «Lo que le respondes», con el texto ya escrito; debajo, un aviso por hueco:
  «Falta: hora de abrir». «Sugerir con IA» bajo el campo 2.
- Botones: «Listo» (sólido) · «Quitar esta respuesta» (suave, pide confirmar: «¿Quitar «Reservas»?
  Tus clientes ya no la verán. Puedes volver a agregarla.» → «Quitar» / «Dejarla»).

**«Agregar otra respuesta»** (al pie de la lista): primero sugerencias de un toque — «Promociones»,
«Pedidos para eventos», «Ingredientes» — o «Escribir la mía». Se abre el mismo panel, con el campo
1 vacío y el ejemplo «Por ejemplo: Promociones».

### Paso 3 de 4 — «Tus productos» (sin cambios)

Ayuda actual: «Tu cliente elige de tu catálogo, con su precio, y arma su pedido.» Decisión actual:
pedir la dirección o no. Si el dueño cargó productos desde una foto (§4), aquí se ven ya en el
catálogo.

### Paso 4 de 4 — «Pruébalo y publícalo»

- **Ayuda:** igual que hoy. Resumen en palabras: «Tu cliente verá tu saludo, 2 botones y «Más
  preguntas» con 5 respuestas. Si escribe algo que el menú no entiende, te pasa el chat.»
- Si quedan huecos: `callout` (aviso) «2 respuestas tienen datos por completar: Horario y Formas de
  pago. Así no se las mostramos a tus clientes.» Botones: «Completarlas» (lleva al Paso 2) ·
  «Quitar las que faltan y publicar».
- **Botón:** «Publicar en mi WhatsApp» (confirmación actual) → «listo» + el QR para el mostrador (N3).

## 3. Maquetas para el celular (375 px)

**Paso 2, con el menú recién creado**

```
┌──────────────────────────────────────┐
│ ‹ WhatsApp          Paso 2 de 4      │
│ ██████████░░░░░░░░░░                 │
│ ¿Qué te preguntan siempre?           │
│ Deja listas las respuestas a lo que  │
│ más te preguntan.                    │
│ ↺ Completar desde una foto o tu página│
├──────────────────────────────────────┤
│ BOTONES (WhatsApp muestra hasta 3)   │
│ ┌──────────────────────────────────┐ │
│ │ Ver menú y pedir      [ Lista ]  │ │
│ │ Tus productos con su precio      │ │
│ │ ⠿                     Editar  ⋯  │ │
│ ├──────────────────────────────────┤ │
│ │ Domicilio   [ Falta completar ]  │ │
│ │ Llevamos tu pedido a [barrios…   │ │
│ │ ⠿                     Editar  ⋯  │ │
│ ├──────────────────────────────────┤ │
│ │ Más preguntas  (lo pone Qualify) │ │
│ │ Abre la lista de abajo           │ │
│ └──────────────────────────────────┘ │
│ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │
│ EN «MÁS PREGUNTAS» (5 de 10)         │
│  Horario          [ Falta completar ]│
│  Dónde estamos               [ Lista ]│
│  Formas de pago   [ Sugerida ]       │
│  Reservas         [ Sugerida ]       │
│  Hablar con alguien          [ Lista ]│
│                                      │
│  + Agregar otra respuesta            │
├──────────────────────────────────────┤
│ Atrás   [   Siguiente   ]  Seguir después│
└──────────────────────────────────────┘
```

**Cuando cambian los botones** (m-24955644). La lista es un solo orden y las dos primeras son
botones: llevar «Horario» al primer o segundo lugar baja al segundo botón a «Más preguntas». No se
bloquea: un aviso de unos 6 segundos lo dice, solo cuando los dos botones cambian, con «Deshacer»
(devuelve el orden de antes de ese movimiento, sin tocar otros cambios):

```
│ Listo: «Horario» ahora es botón y «Domicilio» pasó a «Más preguntas».   [ Deshacer ] │
```

Si los botones no cambian, no hay aviso: el lector de pantalla oye la posición («Horario,
posición 3 de 6, en «Más preguntas»»). Reemplaza el aviso que bloqueaba «Subir» (con «Bajar
«Domicilio»» y «Dejar así»).

**Lista llena** (12 respuestas): «Agregar otra respuesta» se apaga y debajo dice «Llegaste a 12
respuestas, lo máximo que WhatsApp muestra en un mensaje. Para agregar otra, quita una o junta dos
(por ejemplo, «Horario y dirección»).»

**Panel de una respuesta con huecos**

```
┌──────────────────────────────────────┐
│ ‹ Volver a tus respuestas            │
│ Horario                              │
│ Nombre (lo que ve tu cliente)        │
│ [ Horario                    ] 7/20  │
│ Lo que le respondes                  │
│ ┌──────────────────────────────────┐ │
│ │ Abrimos de [qué días], de [hora  │ │
│ │ de abrir] a [hora de cerrar].    │ │
│ │ Cuando quieras pedir, escribe    │ │
│ │ *menú*.                          │ │
│ └──────────────────────────────────┘ │
│ Falta: qué días · hora de abrir ·    │
│ hora de cerrar                       │
│ ✦ Sugerir con IA                     │
├──────────────────────────────────────┤
│ Quitar esta respuesta   [  Listo  ]  │
└──────────────────────────────────────┘
```

## 4. «Cargar mi menú desde una foto o desde mi página»

Un paso, una decisión cada vez: (a) qué traer → (b) esperar → (c) revisar dato por dato.

**(a) Subir.** Título «Sube una foto de tu menú o tu volante». Ayuda: «Que se lean bien los
precios. Sirve una foto, una captura o un PDF.» Botones «Tomar foto» · «Elegir de mi teléfono».
Para la página: título «Pega el enlace de tu página o tu Instagram», campo con ejemplo
«Por ejemplo: instagram.com/bianki», botón «Leer mi página». Nota fija: «Solo leemos los datos de
tu negocio; no publicamos nada.»

**(b) Esperando** (`skeleton_card`): «Estamos leyendo tu menú… Toma menos de un minuto.» Con
«Cancelar». Si tarda más de 60 s: «Está tardando más de lo normal. Puedes esperar o seguir con lo
que ya sabemos.» → «Seguir sin la foto».

**(c) Revisar lo que encontramos**

```
┌──────────────────────────────────────┐
│ ‹ Volver a tus respuestas            │
│ Esto encontramos en tu foto          │
│ Revisa cada dato. Solo usamos lo que │
│ aceptes.                             │
├──────────────────────────────────────┤
│ Horario                              │
│ «Lun a Dom 12m – 10pm»  ← de tu foto │
│ Abrimos de lunes a domingo, de       │
│ 12:00 m. a 10:00 p. m.               │
│ [ Usar ]  Editar  No usar            │
├──────────────────────────────────────┤
│ Formas de pago                       │
│ «Pago móvil · Efectivo» ← de tu foto │
│ [ Usar ]  Editar  No usar            │
├──────────────────────────────────────┤
│ Domicilio                            │
│ No lo encontramos. Queda para que lo │
│ completes tú.                        │
├──────────────────────────────────────┤
│ Productos: 14 en tu foto             │
│ 9 ya están en tu catálogo: no los    │
│ tocamos.                             │
│ 1 tiene otro precio: Shawarma mixto  │
│ foto 6 $ · catálogo 5 $              │
│ (•) Dejar 5 $   ( ) Cambiar a 6 $    │
│ 4 son nuevos   [ Revisar y agregar ] │
├──────────────────────────────────────┤
│ Atrás        [ Usar lo aceptado ]    │
└──────────────────────────────────────┘
```

- La prueba (el recorte de la foto o la frase de la página) va junto a cada dato: el dueño ve de
  dónde salió. Si el dato no viene escrito tal cual, no se propone.
- «Usar» llena el hueco de la respuesta; lo no aceptado queda como estaba.
- **Frases (m-24945867).** Si lo encontrado es una explicación y no un dato corto («La cobertura se
  confirma por WhatsApp según la dirección de entrega»), nunca se pega en un hueco. La fila ofrece
  «Usar este texto» · «Editar» · «No usar», con la vista previa «Si lo usas, tu respuesta
  «Domicilio» queda así:». Las frases de una misma respuesta (zona y costo) van juntas, sin
  repetir; los huecos que ninguna cubre quedan en una línea aparte y se conserva el cierre
  «Para pedir, escribe *menú*.». «Editar» deja acortarla a un dato («todo el centro»), que entonces
  llena su hueco. Después de usarla: «Revisa el texto: lo copiamos tal cual de tu página.»
- Productos: los nuevos se agregan al catálogo **solo** al tocar «Revisar y agregar» (cada uno con
  su nombre y precio, sin foto: «Agrega la foto después en Catálogo»). Por defecto se conserva el
  precio del catálogo.
- Desde la página: lo mismo, con la frase citada como prueba. Si el enlace es el Instagram ya
  conectado, se lee la descripción del perfil (como hoy en `brand_prefill.py`).

## 5. «Sugerir con IA» (saludo y cada respuesta)

Un botón de texto con ícono bajo el campo, siempre con su nombre escrito (nunca solo el ícono).
Escribe con la forma de hablar de tu marca (tono, ejemplos, palabras que no usa, español del país)
y **solo con los datos que el dueño escribió**.

```
EN REPOSO                 ESCRIBIENDO                LISTO
[ texto del campo ]       [ texto (solo lectura) ]   [ texto nuevo ]
✦ Sugerir con IA          ◌ Escribiendo con el       Lo escribimos con tu forma
                            estilo de Bianki…        de hablar. Revísalo.
                                                     ↶ Deshacer · ✦ Otra versión
```

- **Hueco por dato faltante:** la IA deja el corchete y avisa debajo: «Dejamos [hora de cerrar]
  porque no la escribiste. Complétala antes de publicar.»
- **Sin identidad de marca:** funciona igual, con tono amable y neutro, y avisa: «Todavía no
  sabemos cómo habla tu marca, así que lo escribimos neutro. Para que suene a ti, completa Tu
  marca.» → enlace «Ir a Tu marca».
- **Deshacer** devuelve el texto anterior; vale hasta que el dueño vuelva a escribir en el campo.

## 6. Estados vacíos y mensajes de error

| Caso | Mensaje |
|---|---|
| Sin productos en el catálogo («Ver menú y pedir») | «Todavía no tienes productos. Agrégalos en Catálogo y aquí salen solos, con su precio.» → «Ir a Catálogo». La respuesta queda con «Falta completar». |
| Quitó todas las respuestas | «Tu cliente solo verá tu saludo. Agrega al menos una respuesta para que pueda pedir o preguntar.» → «Agregar una respuesta» |
| Nombre de más de 20 caracteres | «Usa hasta 20 letras: WhatsApp corta lo demás. Por ejemplo: «Horario».» |
| Nombre repetido | «Ya tienes una respuesta llamada «Horario». Ponle otro nombre.» |
| Respuesta sin texto | «Escribe lo que le respondes a tu cliente.» |
| Foto que no se puede leer | «No pudimos leer esta foto. Prueba con una más cerca y con buena luz.» → «Probar otra foto» · «Seguir sin la foto» |
| La foto no tiene datos útiles | «No encontramos horarios, precios ni formas de pago en esta foto. Tu menú sigue como estaba.» → «Probar otra foto» · «Seguir sin la foto» |
| Enlace que no abre o es privado | «No pudimos abrir ese enlace. Revisa que esté completo y que la página sea pública.» |
| Lectura que falla | «No pudimos leer tu menú ahora mismo. Inténtalo de nuevo en un momento.» |
| «Sugerir con IA» falla | «No pudimos escribir la sugerencia ahora mismo. Tu texto sigue igual. Inténtalo en un momento.» |
| Cambió el texto mientras la IA escribía | «Cambiaste el texto mientras tanto. Vuelve a tocar «Sugerir con IA».» |
| Campo vacío y sin datos | «Escribe primero los datos (por ejemplo, tus horarios) y lo redactamos con tu estilo.» |

## 7. Qué va en cada entrega

**PR 1 — menú lleno y límites a la vista** (sin IA, sin lectura de fotos)
- Paso 2 nuevo («¿Qué te preguntan siempre?»): lista ordenada, raya de botones, «Más preguntas»
  automático, contadores «5 de 10», mensajes de límite, «Subir»/«Bajar» (desde m-24955644: arrastrar
  y «⋯»), panel de respuesta,
  «Agregar otra respuesta» con 3 sugerencias.
- Plantilla nueva por rubro (empezar por comida) con huecos `[…]`, saludo con el nombre de la
  marca y «Dónde estamos» con la dirección del perfil de WhatsApp. Sacar los datos inventados del
  ejemplo.
- Detección de huecos («Falta: …», `signal_pill`) y el aviso del Paso 4 con «Quitar las que
  faltan y publicar».
- Se corta: Paso 0, la pregunta Sí/No de Domicilio (queda el texto «Sí» con huecos), los otros
  rubros, las sugerencias de «Agregar otra respuesta» más allá de 3.

**PR 2 — «Sugerir con IA»**: sobre el mismo patrón de «Potenciar con IA» (`context_ai.py`): sin
datos nuevos, deja el hueco y lo dice; deshacer; mensaje sin identidad de marca. Medir antes de
publicar (`qualify-measure`): que nunca invente horarios ni precios.

**PR 3 — «Cargar desde una foto o tu página»**: Paso 0, subir/pegar enlace, espera, revisión con
prueba por dato, choque de precios con el catálogo, productos nuevos solo con aprobación. Sigue el
patrón de `brief_ai.py` (leer un documento y proponer campos con su prueba).

## 8. Preguntas abiertas para validar (proponer al perfil, `docs/perfil-cliente-pyme.md` §5)

1. **Hipótesis:** ¿qué le preguntan más por WhatsApp a un local de comida (y a una agencia, a una
   inmobiliaria)? Decide qué respuestas nacen y cuáles van de botón. Fuente rápida: los chats reales
   de Bianki en Conversaciones.
2. **Hipótesis:** ¿el dueño entiende «Más preguntas» como el lugar donde caen las que no son botón?
   Probarlo con el fundador y con la dueña de Bianki en el Paso 2.
3. ¿Tiene el dueño su menú en una foto o volante, o en una página? Decide si el PR 3 vale la pena.
