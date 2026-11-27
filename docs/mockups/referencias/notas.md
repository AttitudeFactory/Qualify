# Pistas de referencias en la línea de tiempo del Clip: notas para firmar (m-25142725)

ux-designer, 2026-11-27. Mockups en esta carpeta: abrir `index.html` con doble clic. Parten de
los mockups firmados del editor único (`docs/mockups/editor-unico/`) y de `docs/design-system.md`
§5.10 y §5.10.1. No tienen código de la app.

## 1. Qué se ve

| # | Pantalla | Archivo |
|---|---|---|
| 1 | Las 3 pistas nuevas con el ejemplo pedido: producto a todo lo largo, dos fotos encimadas bajo la parte con IA 1 y un video bajo la parte con IA 2 | `01-pistas.html` |
| 2 | Una referencia elegida: panel («Se usa en las partes con IA 1 y 2»), arrastre en el celular, sin parte encima, video bajo una parte que no es «Nueva» | `02-referencia-elegida.html` |
| 3 | Agregar: el «+» con «Mostrar a la IA», su pestaña en el panel lateral y las tres entradas comparadas | `03-agregar.html` |
| 4 | Aviso de tope: sobre la parte, en su columna, en una tarjeta, en el pie y en el panel | `04-tope.html` |
| 5 | Panel de la parte con IA sin fotos ni video o audio, con «Lo que la IA mira aquí» | `05-panel-parte.html` |
| 6 | 375 px: pistas vacías plegadas; sin partes con IA, sin grupo | `06-celular.html` |
| 7 | «Usar también en el video» y «Usar también como referencia» | `07-usar-tambien.html` |

## 2. Decisiones que tomé (y por qué)

1. **Orden:** «Fotos y videos» → separador «Para la IA · no sale en tu video» → «Fotos de
   referencia» → «Videos de referencia» → «Audios de referencia» → «Textos» → «Efectos». La regla
   es «aplica a lo que tiene encima»: pegadas a la pista de medios, se lee sola. Con «Textos» en
   medio, encima de una referencia habría un texto. Fotos primero porque es lo más común. Cambia
   §5.10 punto 3 («tres pistas») y «sin pistas de audio aparte»: por eso el separador dice que
   no sale en el video. Pregunta 1.
2. **Dónde se usa, a la vista:** bajo cada parte con IA, las pistas de referencias se pintan con
   una columna iris tenue (el rol «hecho con IA» de §5.10.1, ningún color nuevo). Fuera de esas
   columnas, la pista va rayada: ahí no se usa. Bajo una parte que no usa videos ni audios, la
   columna de esas pistas va gris y el tramo de la referencia, rayado con «No se usa aquí».
3. **El bloque de una referencia:** miniatura de 34 px con el ícono de su tipo (foto, video,
   audio), nombre y, si aplica, una palabra («De tu producto», «No se usa»). Borde iris fino.
   Nunca solo color.
4. **Nombres:** «Foto de referencia n», «Video de referencia n», «Audio de referencia n», con su
   propia cuenta (como «Foto n» y «Video n»). Las del producto: «Combo Vecino · 2 fotos», con la
   etiqueta «De tu producto» en la pista y «Fotos de tu producto» en los paneles (el contrato las
   marca «del producto»: así el dueño entiende por qué aparecieron solas).
5. **Fotos del producto en un solo bloque** a todo lo largo (el coordinador lo vio bien; sigue
   abierta para Deivid como pregunta 2). Cuentan una por una para el tope y se quitan una por una
   en su panel.
6. **Cuándo aplica:** si la referencia y la parte se solapan más de 0,05 s (contrato). En la
   pantalla no se dice el número: el imán (punto 7) evita los roces.
7. **Mover y acortar:** como un efecto (mantener y arrastrar en el celular; ratón o ←/→ en
   escritorio; tiradores de 44 px por fuera; «− ½ s / + ½ s» en el panel). **Imán extra a los
   bordes de cada parte con IA**, porque el dueño piensa «para esta parte». Mientras se arrastra,
   el globo dice la hora y la parte («0:11 · parte con IA 2»). Una referencia solo se mueve dentro
   de su tipo. Las filas se suman y se quitan solas, como los efectos; no hay «+ Pista».
8. **El panel de una referencia** empieza por lo único que le importa al dueño: «Se usa en la
   parte con IA 1.» · «Se usa en las partes con IA 1 y 2.» · el aviso si no se usa. Después,
   «La IA la mira para hacer las partes con IA que tiene encima. No sale en tu video.»,
   Empieza/Termina, «Usar también en el video» y «Listo». «Quitar» va en la barra, sin
   confirmación (es gratis y se vuelve a agregar).
9. **Agregar:** «Agregar» → «Mostrar a la IA» (el menú llega a 6, su máximo), con un
   atajo en el panel de la parte con IA («Agregar una referencia»). Las dos abren la misma
   pestaña «Referencia» del panel lateral: una decisión (qué foto, video o audio; el tipo viene
   en «Foto»). La referencia cae sola **debajo de la parte con IA del cabezal, con su mismo
   largo** (si el cabezal no está sobre una, bajo la más cercana). Descarté el «+» dentro de cada
   pista: en el celular se pierde al deslizar y duplica «Agregar». Sin partes con IA, la opción
   queda no disponible con su motivo.
10. **Tope:** el máximo sale **del modelo activo**, por parte y por tipo; la pantalla nunca lo
    escribe fijo (hoy, con Seedance, 9 fotos, 3 videos y 3 audios). Aviso en cuatro lugares:
    cápsula ámbar sobre la parte («⚠ 10 fotos · máx. 9»), su columna en ámbar, una tarjeta bajo la
    línea (en una parte de 5 s no cabe el motivo, como D15 del editor firmado) y el panel. Lo que
    la parte no usa (videos o audios bajo una parte que no es «Nueva») no cuenta para el tope.
    Qué pasa con «Siguiente»: pregunta 4.
11. **Panel de la parte con IA:** se van «Fotos de tu producto» y «Video o audio tuyo» (que
    estaba en «Más opciones», respuesta 9 del 2026-11-26). En su lugar, la caja «Lo que la IA
    mira aquí», justo bajo «¿Qué pasa en esta parte?»: lista con miniaturas, «Para cambiarlos,
    muévelos o quítalos en la línea.» y «Agregar una referencia». La lista no edita (un solo
    lugar por acción).
12. **Celular:** las pistas de referencias vacías se pliegan en una fila de 44 px que también
    sirve para agregar («Sin videos ni audios de referencia · Agregar»). Sin partes con IA, el
    grupo «Para la IA» no se dibuja (las referencias se guardan). En escritorio se pliega igual.
13. **Copias:** «Usar también en el video» (panel de una referencia de foto o video) y «Usar
    también como referencia» (panel de una foto o un video tuyo). Copias aparte, gratis, sin
    servidor. La línea viva dice adónde fue y que son copias aparte. **El audio no puede ir como
    bloque propio:** «Fotos y videos» no admite audio, así que un audio de referencia no muestra
    «Usar también en el video» (tampoco apagado, porque nunca se va a poder).

### Decidido por Deivid (2026-11-27)

- **Video o audio de referencia bajo «Igual al original» o «Sigue a la anterior»:** se ignora y
  se avisa, sin bloquear. Las fotos sí se usan en los tres modos. Pantallas 2 (D) y 5 (B).
- **Referencia sin ninguna parte con IA encima:** se permite y se avisa. Pantallas 2 (C) y 7 (B).
- **Topes:** dependen del modelo. Hoy, con Seedance, 9 fotos, 3 videos y 3 audios por parte.

## 3. Textos nuevos

Del contrato, tal cual:

- `reference_mode_ignored`: «Esta parte no usa videos ni audios de referencia».
- `reference_unused`: «Esta referencia no está debajo de ninguna parte con IA».

Propuestos (la palabra «bloque» no aparece; sin «timeline», «track» ni «capa»):

- Pistas: «Fotos de referencia», «Videos de referencia», «Audios de referencia» (con varias
  filas: «Fotos de referencia 1, 2…»); separador: «Para la IA · no sale en tu video».
- Bloques: «Foto de referencia n», «Video de referencia n», «Audio de referencia n»,
  «{producto} · n fotos», «De tu producto», «No se usa», «No se usa aquí».
- Panel de la referencia: «Se usa en la parte con IA n.» / «Se usa en las partes con IA 1 y 2.»
  · «La IA la mira para hacer las partes con IA que tiene encima. No sale en tu video.» · «Para
  cambiar en qué partes se usa, muévela o acórtala: se pega a los bordes de cada parte con IA.»
  · «Muévela debajo de una, o quítala.» · «Usar también en el video» · «Pone una copia en
  «Fotos y videos». Gratis.»
- Agregar: «Mostrar a la IA» · pestaña «Referencia» · «Va debajo de la parte con IA n,
  donde está el cabezal, y dura lo mismo. La IA la mira para hacer esa parte; no sale en tu
  video.» · «¿Qué le mostramos a la IA?» · «Foto · Video · Audio» · «De tus productos» · «De tu
  teléfono» · «Subir una foto» · «Agregar esta foto» · «Primero agrega una parte con IA: las
  referencias son para ella.»
- Tope (el número sale del modelo activo): «{n} fotos · máx. {m}» · «La parte con IA n tiene
  {n} fotos de referencia y la IA usa hasta {m}. Quita una o muévela a otra parte.» · «Ver las
  fotos de esta parte» · «Sobra 1 foto de referencia en la parte con IA n.» · «La parte con IA n
  ya tiene {m} fotos, lo más que usa la IA. Quita una para agregar otra.»
- Panel de la parte: «Lo que la IA mira aquí» · «Fotos de tu producto» · «Son las fotos, videos
  y audios que están debajo de esta parte. Para cambiarlos, muévelos o quítalos en la línea.» ·
  «Nada todavía. La IA usa lo que escribiste arriba.» · «Agregar una referencia» · «Para que use
  el video, elige «Nueva» en «¿Cómo la hacemos?».»
- Celular: «Sin {fotos, videos ni audios} de referencia · Agregar».
- Copias: «Usar también como referencia» · «Pone una copia en «Videos de referencia» para que
  la IA la mire. Gratis.» · «Copiamos la foto de referencia 1 a «Fotos y videos», a las 0:02,
  como «Foto 3». Son copias aparte: si cambias una, la otra no cambia.» · «Copiamos el video 1 a
  «Videos de referencia», justo debajo. Esta referencia no está debajo de ninguna parte con IA:
  muévela debajo de una para que la IA la use.»
- Línea viva: «Pusimos las fotos de {producto} en «Fotos de referencia», en todo tu video.» ·
  «Alargaste la foto de referencia 1: ahora se usa en las partes con IA 1 y 2.» · «Suelta donde
  quieras ponerla.» · «Quitaste la foto de referencia 1.» · «Agregaste una foto de referencia a la
  parte con IA n.»

## 4. Preguntas para Deivid (una por una)

Cada una con opciones y mi recomendación. Quedan abiertas la 1 a la 4 y la 6 a la 8; la 5 ya la
decidió Deivid (arriba).

**1. ¿Dónde van las pistas de referencias?**
- A · Justo debajo de «Fotos y videos», antes de «Textos» y «Efectos». **(Recomendada)**: la
  regla «lo que tiene encima» se lee sola.
- B · Al final, después de «Efectos»: respeta el orden firmado de §5.10, pero entre la parte y su
  referencia quedan un texto y un efecto.

**2. ¿Cómo entran las fotos del producto?**
- A · Un solo bloque «{producto} · n fotos», a todo lo largo, con la etiqueta «De tu producto».
  **(Recomendada)**: una fila, cada foto cuenta para el tope y se quitan una por una en su panel.
- B · Un bloque por foto: un producto con 8 fotos llena 8 filas.

**3. Cuando una parte con IA cambia de lugar (se reordena o entra algo antes), ¿sus referencias
la siguen?**
- A · La referencia que está toda debajo de una sola parte la sigue; las que tocan varias partes
  se quedan en su hora, y la línea viva lo dice. **(Recomendada)**: si no, una referencia pasa a
  otra parte sin que el dueño lo note (se ve en la pantalla 7 A).
- B · Todas se quedan en su hora, como los textos y los efectos.
- C · Todas siguen a la parte que tenían encima al empezar.

**4. Si una parte pasa el tope del modelo, ¿qué pasa con «Siguiente»?**
- A · Queda no disponible con su motivo hasta arreglarlo. **(Recomendada)**: lo que se ve es lo
  que sale (E5), y no se sabe cuál dejaría fuera la IA.
- B · Sigue activo y la IA usa las primeras hasta el tope; el pie lo avisa.
- C · Qualify quita sola las que sobran.

**5. (Decidida el 2026-11-27)** Videos y audios bajo «Igual al original» o «Sigue a la
anterior»: se ignoran y se avisa, sin bloquear.

**6. «Usar también como referencia» desde un bloque tuyo: ¿dónde cae la copia?**
- A · Justo debajo del bloque, como pediste, con el aviso «Esta referencia no está debajo de
  ninguna parte con IA». **(Recomendada)**: es lo predecible, y el aviso dice qué hacer.
- B · Debajo de la parte con IA más cercana, para que se use de una vez.

**7. «Usar también en el video» desde una referencia: ¿cómo entra en «Fotos y videos»?**
- A · En la unión más cercana a donde empieza la referencia, corre lo que viene después, y la
  línea viva dice la hora. Cuenta para los topes de 8 y de 60 s. **(Recomendada)**
- B · Siempre al final del video, sin correr nada.

**8. Texto del panel de la referencia.**
- A · «Se usa en las partes con IA 1 y 2.» **(Recomendada)**: concuerda en número.
- B · «Se usa en la parte con IA 1 y 2.», como lo escribiste en el pedido.

## 5. Qué necesita reflex-ui-engineer

- **Pistas:** `Qualify/ui/timeline.py` y `timeline_vm.py` suman tres tipos de pista con filas
  (la lógica de filas de «Efectos»), el separador y la fila plegada; nombres accesibles «Fotos de
  referencia 1…», y «…, vacía». Ningún token nuevo: `--q-ai-*` para columnas y bordes, ámbar para
  el tope.
- **Columnas:** por cada parte con IA, una columna en las pistas de referencias (iris; ámbar si
  pasa el tope; gris si la parte no usa ese tipo). El cálculo de «aplica» usa el solape de más de
  0,05 s del contrato.
- **Arrastre:** `assets/timeline-drag-core.js` trata la referencia como un efecto (correr en el
  tiempo, cambiar de fila dentro de su tipo) con imán extra a los bordes de las partes con IA.
- **Panel:** `.q-tl-panel` para la referencia (frase «Se usa en…», Empieza/Termina, «Usar
  también en el video» salvo audio, «Listo»); la caja «Lo que la IA mira aquí» en el panel de la
  parte; se quitan «Fotos de tu producto» y «Video o audio tuyo».
- **Agregar:** opción nueva del `orbit_menu` (la sexta) y la pestaña «Referencia» del `drawer`.
- **Tope:** la cápsula `.q-tl__state` en tono `warn` sobre la parte, la tarjeta bajo la línea y,
  según la pregunta 4, el motivo en el pie. El máximo viene del modelo activo, nunca fijo.
- **Celular:** pliegue de las pistas de referencias vacías; sin partes con IA, no se dibuja el
  grupo.
- Todo detrás de `QUALIFY_CLIP_AI_PARTS`.
