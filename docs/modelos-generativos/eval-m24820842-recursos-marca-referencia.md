# Evaluación m-24820842 — recursos de marca como imágenes de referencia (imagen y video)

Rúbrica y especificación del conjunto de prueba, preparada el 2026-10-29. El envío de recursos
está implementado y cuenta con pruebas offline; **la calidad visual no se ha medido y no se
ejecutaron llamadas pagadas**. El usuario fijó un máximo de USD 3 para la primera prueba;
su ejecución sigue pendiente de las condiciones del §8.

La implementación está en `qualify_api.creative.brand_references` (selección validada y copia
inmutable por revisión), `MediaProducer.prepare_brand_references` (comprobaciones antes del
gasto), `_scene_image` y las rutas de video de `media.py`; `ContentService._generate_brief`
prepara los recursos antes de pagar el texto. `test_brand_references.py` comprueba contratos,
aislamiento, recursos borrados/sustituidos, continuidad de instrucciones y reanudación con
proveedores espía. Estas pruebas no miden la fidelidad del modelo.

Clip envía referencias directas a la familia Seedance configurada y conserva sus roles separados
del producto. Un Avatar animado usa referencias directas cuando la familia lo permite; el
fotograma compuesto es referencia 1, sin afirmar que sea una restricción exacta de fotograma
inicial. Los avatares humanos y los modelos sin referencias usan el fotograma compuesto más
instrucciones de continuidad. Galería animada sin referencia de movimiento usa también el
fotograma compuesto; con ella puede enviar las imágenes como referencias directas. OmniHuman
recibe el presentador compuesto, sin campos de referencias inventados. Todas estas modalidades
requieren comprobar la presencia e identidad a lo largo del video, no solo en la imagen inicial.

Documentación oficial consultada: [Seedance 2.5](https://docs.byteplus.com/en/docs/ModelArk/seedance-2-5)
(referencias multimodales y restricciones de retratos) y [generación de imágenes](https://docs.byteplus.com/en/docs/modelark/image-generation-tutorial)
(hasta 14 referencias para Seedream 4/4.5/5 lite). No se verificó el endpoint desplegado ni se
ejecutó una prueba de fidelidad. El personaje humano F4 no se enviará directamente al modo de
referencias de Seedance sin cumplir primero el mecanismo de retratos autorizado del proveedor;
su contrato actual se comprueba por fotograma condicionado u OmniHuman.

Ámbito: Flyer, Galería (fija y animada), Clip y Avatar (OmniHuman + Seedance video). Recursos del
Brand Kit: mascota, elementos (patrones/objetos), logo y sus variantes (isotipo, isologo,
imagotipo, logotipo), y un personaje/presentador propio con rol distinto.

---

## 1. Conjunto de prueba (fase pagada posterior)

Cuatro fixtures de marca, cada uno con identidad distinguible para que un evaluador humano (y, si
procede, un VLM de juez) pueda decir «es este y no otro». Estos alimentan la evaluación pagada;
**no se generan ahora**.

### F1 — Mascota (rol: elemento de marca)

- Colores corporativos inconfundibles: base naranja `#E8602A` con vientre crema `#F5E6C8`.
- Proporciones: cuerpo redondeado, cabeza 1,4× el cuerpo, ojos grandes centrados, sin cuello.
- Marca distintiva: tres manchas circulares oscuras sobre el lomo, dispuestas en triángulo.
- Nota de uso típica: «aparecer junto al producto como acompañante, no como producto ni como
  presentador; conservar sus tres manchas y la proporción cabeza/cuerpo».

### F2 — Patrón/elemento de marca (rol: fondo o textura decorativa)

- Repetición de un motivo hexagonal con borde morado `#5B2A86` y relleno translúcido.
- Marca distintiva: el hexágono central lleva un glifo (estrella de 4 puntas) que las copias
  adyacentes no tienen, para distinguir patrón correcto de patrón degradado.
- Nota de uso típica: «usar como textura de fondo discreta, no como producto ni como personaje;
  no tapar el glifo central».

### F3 — Objeto de marca (rol: accesorio/prop)

- Botella cilíndrica alta con etiqueta diagonal a franjas verdes `#2E7D32` y blanco.
- Marca distintiva: tapón dorado asimétrico (más alto de un lado) y un sello circular en relieve
  en el centro de la etiqueta.
- Nota de uso típica: «aparecer sostenido o apoyado por el presentador, conservando tapón dorado
  asimétrico y sello central; no sustituir por un producto genérico».

### F4 — Personaje/presentador propio de la marca (rol: personaje/presentador, DISTINTO de mascota y de producto)

- Humana, piel morena, cabello corto rizado, uniforme verde `#2E7D32` con banda diagonal color
  crema en el torso.
- Marca distintiva: pendiente único dorado en forma de estrella de 4 puntas en la oreja izquierda
  (mismo glifo que F2, para sondear confusión de roles).
- Nota de uso típica: «actuar como presentadora: mira a cámara, habla/conduce la pieza; conserva
  uniforme, banda diagonal y pendiente en estrella; no degradar a elemento decorativo ni a
  producto».

> F4 comparte el glifo estrella con F2 a propósito: la rúbrica debe detectar si el modelo funde el
> patrón con la presentadora (fallo de rol). Su rol explícito (personaje/presentador) es distinto
> del de F1 (mascota/elemento) y del de F3 (objeto/prop).

Combinaciones por formato (todas con y sin selección, para la paridad de §4):
- Flyer / Galería fija: F1, F2, F3, F4 individualmente y el conjunto F1+F3+F4.
- Clip, Avatar Seedance, Galería animada: F4 (presentadora) + F1 (mascota) como caso crítico de
  continuidad, y F2+F3 como caso de elementos no animados en video.

---

## 2. Rúbrica — IMAGEN (Flyer, Galería fija)

Para cada fixture y combinación, un evaluador humano marca cada criterio como
`cumple` / `parcial` / `no cumple`. Una pieza pasa solo si todos los aplicables están en `cumple`.

| # | Criterio | Cómo se verifica |
|---|---|---|
| I1 | El recurso elegido aparece **reconocible**: colores, proporciones y marca distintiva coinciden con el fixture. | Comparación visual contra el fixture original; al menos 2 de 3 rasgos distintivos visibles. |
| I2 | El recurso se usa **según su nota de uso** (rol declarado: fondo, prop, acompañante, presentador). | La nota define el rol; el evaluador confirma que el recurso cumple ese rol y no otro. |
| I3 | El **producto** mantiene su identidad y no fue reemplazado ni por el recurso ni por el presentador. | Producto del catálogo reconocible; sin sustitución. |
| I4 | El **presentador/personaje** mantiene identidad y rol; no fue degradado a elemento decorativo. | Si F4 participa, conserva uniforme/banda/pendiente y mira/acción indicada. |
| I5 | Las **instrucciones no se imprimen como texto** sobre la imagen. | Sin cadenas tipo «conserva el tapón dorado» ni nombres de rol en el resultado. |
| I6 | Con múltiples elementos, cada uno conserva su identidad; **el fondo quedó indexado correctamente** (no se confunde con un elemento ni viceversa). | Auditar el índice de imágenes enviado vs el resultado visual. |

---

## 3. Rúbrica — VIDEO (Clip, Avatar Seedance, Galería animada) — CRÍTICA

El criterio central: **un fotograma correcto no satisface la rúbrica**. La presencia, identidad y
rol deben sostenerse durante toda la reproducción y los cortes.

### 3.1 Muestreo

Para cada video se extraen:

- **F-inicio** (≈10 %), **F-medio** (≈50 %), **F-fin** (≈90 %) de la línea de tiempo.
- **F-transición**: fotogramas inmediatamente antes y después de cada corte/plan detectado.
- **Reproducción completa**: el evaluador ve el video entero (1×) y marca discontinuidades no
  capturadas por los fotogramas muestrados.

### 3.2 Criterios (todos deben ser `cumple` para pasar)

| # | Criterio | Cómo se verifica |
|---|---|---|
| V1 | El recurso elegido aparece durante los **intervalos/planos acordados por su nota** (presencia constante si la nota lo pide). | Comparar presencia en F-inicio, F-medio, F-fin y F-transición contra lo que exige la nota. |
| V2 | **Continuidad de identidad** a través de inicio, medio, fin y cortes: conserva rasgos, colores y proporciones del fixture. | Comparación visual entre los fotogramas muestrados; una mutación injustificada (cambio de color, pérdida de marca distintiva, cambio de proporción) entre dos puntos = no cumple. |
| V3 | **Acción/posición indicada** se mantiene según la nota (p. ej., «mascota junto al producto», «presentadora mira a cámara y habla»). | Verificar en cada fotograma muestrado y durante reproducción completa. |
| V4 | El recurso **no desaparece ni se transforma injustificadamente** entre planos/cortes. | Un recurso presente en F-inicio y ausente en F-medio sin justificación narrativa = no cumple. |
| V5 | El **producto** conserva identidad y no es reemplazado por el recurso ni por el presentador. | En cada fotograma muestrado. |
| V6 | El **presentador/personaje** conserva identidad y rol; no fue degradado a elemento ni ascendido a producto. | En cada fotograma muestrado y cortes. |
| V7 | Las **instrucciones no se imprimen como texto** ni se insertan como voz fuera de la del presentador. | Revisión completa. |
| V8 | Si la nota pide **presencia constante**: continuidad verificada durante la **reproducción completa**, no solo en fotogramas muestrados. | Marcar cualquier ventana de ausencia > 1 s como no cumple. |

### 3.3 Los tres criterios más decisivos para continuidad de video

1. **V2 (continuidad de identidad entre inicio/medio/fin y cortes)**: es el único que detecta la
   deriva de rasgos que un solo fotograma acertado escondería. Sin V2, un modelo que acierta el
   primer cuadro y degrada el recurso después pasaría la rúbrica.
2. **V1 (presencia en los intervalos acordados por la nota)**: ata la presencia al contrato de
   uso. Sin V1 no se distingue «apareció» de «apareció cuando y donde debía».
3. **V8 (presencia constante verificada en reproducción completa)**: cierra el bucle para notas
   que exigen presencia total; sin V8 un muestreo de tres fotogramas declararía cumplido un video
   que borra el recurso al cortar.

---

## 4. Paridad sin selección

Con cero elementos elegidos, la petición al modelo debe ser **idéntica a la anterior** (mismas
referencias base, mismo prompt base, sin lecturas nuevas de Brand Kit/R2). Esto se verifica
**offline** con el proveedor espía (§6) y, en la fase pagada, comparando los `params` efectivos.

No se promete **igualdad píxel a píxel** de salidas estocásticas: solo se pide paridad de entradas
y de prompt. El resultado visual puede variar por estocasticidad del modelo; lo que debe ser
idéntico es la petición.

---

## 5. Modos de fallo por formato y motor

Cada modo debe registrarse en la bitácora (`pruebas.md`) con `file:line` cuando se observe.

| Modo de fallo | Formato/motor | Qué lo detecta |
|---|---|---|
| **Referencia caída silenciosamente en fallback** (`_clip_frames_suffice` descarta recursos elegidos cuando el modelo no admite referencias) | Clip Seedance 1.x | §6 offline + reporte de gasto: la petición pagada nunca debe descartar recursos sin rechazar antes. |
| **Mascota tratada como producto** (en `reel_edit_prompt`, toda imagen se llama «producto») | Clip edición/réplica | V5 + offline: el prompt distingue fotos de producto de elementos. |
| **Presentador degradado a elemento** (avatar propio mezclado como `brand_element_keys`) | Flyer, Galería, Avatar | V6 + offline: rol explícito evita la mezcla. |
| **Fondo mal indexado al anexar referencias de marca** (prompt dice «last image» = fondo, pero al agregar elementos el último índice ya no es el fondo) | Flyer, Galería, Seedance | I6 + V2 en transiciones; offline: índice explícito, no «last image». |
| **Fidelidad `first_frame` vs modo referencias** (Seedance prohíbe mezclar `first_frame` con `reference_*`; al pasar a referencias se pierde el cuadro inicial exacto) | Avatar Seedance 2.x | V1+V2 en inicio; reportar fiabilidad de cada modalidad. |
| **Elemento no animado que se anima** o **animado que se congela** injustificadamente | Galería animada, Clip | V4 durante reproducción completa. |
| **Confusión de roles por glifo compartido** (F2 y F4 comparten estrella) | Todos | I4, V6: el patrón no se «pega» a la presentadora. |

---

## 6. Criterios offline (proveedor espía) — para los unit tests del creative-engineer

Lo que los unit tests offline con proveedor espía deben afirmar, machine-checkable. El
creative-engineer escribe los tests; aquí se define lo que deben verificar.

1. **Imagen + rol + nota llegan a la llamada del proveedor, por tipo de contenido**: Flyer, Galería
   fija, Clip y ambos motores de Avatar (OmniHuman y Seedance) reciben los descriptores del recurso
   elegido con su clave, rol y nota saneada.
2. **Instrucciones de continuidad presentes en los prompts de video**: `motion_prompt`,
   `clip_prompt`/`reel_edit_prompt` y `carousel_motion_prompt` incluyen instrucciones temporales de
   presencia/identidad para cada recurso (no solo de composición inicial).
3. **Múltiples elementos** se transmiten correctamente (no se trunca al primero ni se colapsan en
   uno solo).
4. **Índice de fondo correcto**: cuando hay elementos adicionales, el prompt cita el fondo por su
   índice explícito, no como «last image».
5. **Edición de Clip NO etiqueta la mascota como producto**: `reel_edit_prompt` distingue fotos de
   producto de elementos de marca.
6. **Sin mezcla de roles incompatibles**: un mismo archivo en dos roles incompatibles se rechaza
   antes de generar (no se deduplica silenciosamente cambiando su función).
7. **Sin pérdida silenciosa en fallback**: si el modelo no admite referencias, se **rechaza antes
   de pagar** con explicación, en vez de descartar recursos (`_clip_frames_suffice` no omite
   recursos elegidos).
8. **Sin selección → petición idéntica**: con `brand_element_keys` vacío, los `params["images"]`
   son exactamente los de la petición base, sin lecturas nuevas de BD/R2 (auditoría :13-14 muestra
   que hoy ya es así; el test lo congela como regresión).
9. **Rechazos de stock/capacidad**: stock en avatar/logo/elementos (guardián
   `stock/guard.py:59-73`), otra marca del mismo tenant, otro tenant, borrado o no-imagen, nota
   vacía (instrucción neutral), y fronteras 9/10 y 30/31 imágenes Seedance contando fotogramas
   convertidos; 14/15 referencias Seedream. Clip exclusivamente stock sigue rechazado; recursos de
   marca no cambian licencia/procedencia del stock.

---

## 7. Revalidación por recurso obsoleto / actualización-borrado (NUEVO 2026-10-29)

Nueva sección del plan (`plan-m24820842.md` §3, :37-41). Cubre imágenes y videos. El
creative-engineer escribe los unit tests; aquí se define lo que deben verificar.

### 7.1 Logo actualizado en el Brand Kit

- Tras actualizar el logo, una **nueva generación** que lo use debe tomar la versión **actual**
  (huella vigente), no la versión sustituida.
- La huella obsoleta se **rechaza antes de gastar** (no se envía a pago y luego se descarta).
- Una pantalla/selección **previamente abierta** con el logo viejo en caché se revalida al iniciar
  la nueva generación; no se usa el archivo sustituido por estar en caché.

Test offline: comparar la huella del recurso en la petición final contra la huella vigente del
Brand Kit; la obsoleta se rechaza antes de la llamada al proveedor.

### 7.2 Recurso eliminado

- Un recurso eliminado deja de ser **seleccionable y utilizable** en nuevas generaciones.
- No se ofrece vía versiones antiguas (no se sirve de cachés para revivir lo borrado).
- La pieza ya generada **conserva** su imagen/video: no se modifica retroactivamente.

Test offline: la selección de una clave eliminada se rechaza antes de R2/proveedor con mensaje
accionable; una clave vigente pasa.

### 7.3 Reanudación/reintento de trabajo en curso (pagado)

- Un trabajo **ya iniciado** reutiliza el **snapshot congelado** (claves, huellas, índices, notas,
  versión de prompt) sin importar cambios posteriores al activo; no se invalida por una
  actualización/borrado posterior del recurso.
- **Regeneración** posterior sí toma la versión vigente (es una nueva generación, no una
  reanudación).

Test offline: el checkpoint identifica imágenes + prompt y no reutiliza una petición anterior; un
cambio de huella tras el checkpoint no altera la reanudación; una regeneración sí toma la huella
vigente.

### 7.4 Piezas ya generadas

- No se retroactivan: una pieza renderizada con el logo viejo sigue mostrándolo aunque el
  Brand Kit ya tenga uno nuevo.
- Esta rúbrica no autoriza a servir recursos eliminados vía versiones viejas ni pide un sistema de
  archivado nuevo.

Test offline: una pieza existente no es reenviada al proveedor por un cambio de Brand Kit.

### 7.5 Cobertura de formatos

Los tests anteriores deben cubrir tanto **imagen** (Flyer, Galería fija) como **video** (Clip,
Avatar Seedance, Galería animada): el rechazo por obsolescencia y la congelación de reanudación
aplican igual en ambos.

---

## 8. Presupuesto y protocolo de horario (de `qualify-measure`)

- **Video solo de 23:00 a 05:00 hora de Bogotá** (00:00–06:00 Caracas; 01:00–07:00 Montevideo),
  fuera del día de los comercios. Correrlo de día pide visto bueno del fundador.
- **Máximo 3 tareas simultáneas** de las 10 (`cap_video_concurrency`), para que un cliente
  nocturno tenga 7. OmniHuman: 1 a la vez.
- **Llave propia de evaluación** `QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY`, distinta de la app y de
  producción; la evaluación se niega a gastar con la llave de producción
  (`QUALIFY_BYTEPLUS_ARK_PROD_KEY_FINGERPRINT`).

### Estado de este handoff

**Techo acordado con el usuario: USD 3**, con corte acumulado antes de cada tarea y sin
reintentos automáticos que creen una segunda tarea pagada. Primera prueba reducida: **4 imágenes
y 4 videos** de 5 segundos, a 480p y 9:16. Se usan `seedream-5-0-lite-260128` y
`dreamina-seedance-2-5-260628`, tabla versionada `pricing_data/v7.json`, sin video/audio de
entrada. El cálculo offline preparado por datasci se reduce a **USD 2,196028**:

- Seedream: 4 × USD 0,035 = USD 0,14.
- Seedance: `round(480×854×24×5/1024)` = 48.038 tokens estimados por video;
  tarifa v7 USD 10,70/millón → USD 0,514007 × 4 = USD 2,056028.
- Total estimado: USD 2,196028. El límite real acumulado sigue siendo USD 3; no aumentar
  el gasto para completar casos faltantes.

| Caso reducido | Imágenes nuevas | Videos nuevos |
|---|---:|---:|
| Flyer con recurso | 1 | 0 |
| Galería con recurso, animando la misma escena | 1 | 1 |
| Clip con recurso | 0 | 1 |
| Avatar animado, composición más video | 1 | 1 |
| Avatar humano, composición más video | 1 | 1 |
| Total | 4 | 4 |

Es una prueba mínima de presencia/roles/continuidad, **sin pares baseline para cada caso ni
medición de fiabilidad**. La matriz completa de esta rúbrica queda fuera de ese presupuesto.
Las cifras proceden de funciones públicas `estimate_video_tokens`, `video_cost_usd` y de la
tabla v7 del repositorio; no son una cotización actual verificada. Antes de ejecutar se
confirman modelo/endpoint, tarifa efectiva, aptitud para datos de clientes y horario permitido.

El presupuesto excluye texto Claude, voz, OmniHuman, videos de entrada y finales a 1080p.
Esos recorridos necesitan una ampliación calculada y aprobada aparte; esta primera prueba no
cierra por sí sola toda la rúbrica ni prueba identidades humanas directas. El máximo de USD 3
no autoriza esas operaciones adicionales. No se ejecutó ninguna llamada en esta entrega.

### Inputs reales necesarios para calcular el techo

Antes de la fase pagada se debe completar y versionar la siguiente tabla con valores reales del
modelo/endpoint desplegado. Los límites por familia se consultan en
`qualify_creative.adapters.byteplus_ark.SeedanceFamily` y `MAX_REFERENCE_IMAGES` y se validan
en `MediaProducer._preflight_brand_references`; la configuración real del endpoint debe
corroborarse antes del experimento:

| Input | Valor requerido |
|---|---|
| Imágenes de evaluación | número de imágenes × entradas por imagen (1 imagen + N referencias; máx. combinado 18 en Avatar, 17 en Flyer) |
| Modelo de imagen | id y versión de Seedream desplegado |
| Resolución de imagen | la del endpoint real |
| Duración de cada video | segundos por clip (Clip, Avatar Seedance, Galería animada) |
| Resolución de video | la del endpoint real |
| Referencias de video | número y tipo de referencias (imagen/video/audio) por tarea Seedance (fronteras 9/10 y 30/31 según familia 2.0/2.5) |
| Voz | si el caso Avatar usa Seed Speech / clon de voz (sí/no) y su costo |
| Modelo/endpoint de video | id y versión de Seedance/OmniHuman desplegados |
| Número de combinaciones | fixtures F1–F4 × formatos × con/sin selección |

Con esa tabla se calcula el techo en USD y se acuerda con el fundador antes de la primera tarea.

---

## 9. Registro de resultados

Per `qualify-measure`: los resultados, la configuración y el costo de cada corrida se registran
en `docs/modelos-generativos/` el mismo turno, en `pruebas.md` (más reciente arriba) o en un
archivo dedicado `eval-m24820842-resultados-*.md` si la cantidad lo justifica. Incluir siempre:
fecha, quién, ticket, configuración real usada, costo observado y veredicto por criterio
(I1–I6, V1–V8, paridad, revalidación). No se escriben claves, solo nombres de variables de entorno.

---

## Estado

- Rúbrica y conjunto de prueba: **listos** (este documento).
- Implementación del envío de recursos y pruebas offline: **incluidas en esta PR**.
- Presencia/identidad visual y temporal: **sin medir**, pendiente de ejecución de esta rúbrica.
- Primera prueba: estimación de tabla v7 USD 2,196028; **máximo acordado USD 3**, ejecución pendiente.
- Cobertura adicional de voz/OmniHuman/videos de entrada/1080p: pendiente de presupuesto específico.
