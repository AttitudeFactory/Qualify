# Bucle LLM + visión para generación de plantillas gráficas

> Investigación externa (web) para el motor de contenido de marca de Qualify: LLM escribe layout
> declarativo → render determinista (Pillow) → crítica → corrección.
> Convención de evidencia: **[V]** verificado contra fuente primaria (paper/repo leído),
> **[S]** fuente secundaria, **[H]** hipótesis o inferencia propia.
> Fecha: 2026-08-18.

---

## §1. El bucle render → crítica → corrección

### 1.1 Qué se ha construido

- **Design2Code (Stanford, 2024)** es el trabajo fundacional: define el benchmark screenshot→HTML
  y prueba explícitamente *self-revision prompting* (se le muestra al modelo el render de su propio
  código junto al objetivo y se le pide corregir). Sus métricas automáticas son **block-match, text,
  position, color y CLIP**, calculadas por script Python sobre los renders. **[V]**
- **Resultado incómodo y central**: la auto-revisión ingenua **casi no mejora**. Aporta mejoras
  menores en block-match/position para GPT-4V y Claude 3, y **ninguna** para Gemini Pro Vision ni
  para los modelos abiertos. **[S]** — El bucle no funciona solo por existir; funciona por cómo se
  estructura la crítica.
- **Vision-Guided Iterative Refinement (2026)** separa el bucle en 6 roles: Generator → Renderer
  (Selenium) → **Visual Critic** (VLM sobre el screenshot) → **Code Critic** (LLM que fusiona el
  feedback visual con el código) → Improver → Evaluator. El paper reporta que **separar crítica
  visual de crítica de código supera a una crítica unificada**. Con T=3 ciclos: +17.8% en
  Distill-Qwen-14B (+6.2/+7.8/+8.7 por ciclo) y +10.8% en Claude 4.5 Sonnet auto-mejorándose. **[V]**
- **Coste del bucle, medido**: generación inicial ~2.5K–6.7K tokens; llegar a la mejor solución
  ~23.7K–73.2K tokens (**9–11×**); tres ciclos completos 45.8K–131.5K tokens. Destilar el bucle a
  LoRA recupera solo el **24.7%** de la ganancia pero a coste casi base. **[V]**
- **UI2Code^N (2026)** reformula UI→código como "optimización visual interactiva" y entrena el bucle
  en vez de promptearlo: **RVPO** (Relative Visual Policy Optimization) deriva la recompensa de
  **comparaciones relativas entre N candidatos renderizados**, no de puntuaciones absolutas de un
  juez —precisamente porque las absolutas son inestables. Un modelo 9B abierto supera a sistemas
  cerrados mayores; el rendimiento satura en **N=3** en benchmarks sintéticos y llega hasta **N=5**
  en páginas reales. **[V]**
- **VF-Coder / "Coding with Eyes" (2026)**: agente multi-agente con percepción visual e interacción
  real con la interfaz; sube Gemini-3-Flash de 21.68% → 28.29% de éxito y el visual score de
  0.4284 → 0.5584 en InteractGUI Bench (984 tareas). **[V]**
- **Práctica open-source**: `abi/screenshot-to-code` (~53K estrellas) implementa el bucle de forma
  pragmática —genera HTML/Tailwind, compara con el screenshot original e itera. **[S]**

### 1.2 Lecciones transferibles

- **[H]** El patrón que sí funciona no es "muéstrale el render y pídele que lo arregle", sino
  **crítica estructurada en dos etapas**: un observador visual que enumera defectos concretos, y un
  segundo paso que traduce defectos → ediciones sobre la representación. Design2Code falla en lo
  primero; el paper de 2026 acierta al separarlo.
- **[H]** **Best-of-N con selección** (estilo RVPO) es más barato y más estable que refinamiento
  secuencial para un caso como Qualify: N renders cuestan ~$0 (Pillow), y solo se paga la selección.
  El refinamiento secuencial multiplica tokens por 9–11×.
- **[V]** Saturación empírica a **3 iteraciones**; más de 3 casi nunca se justifica.

---

## §2. Representación del layout: coordenadas vs CSS vs restricciones

### 2.1 Lo que dice la investigación

- **LayoutGPT (NeurIPS 2023)** representa layouts como **hojas de estilo (CSS)** en demostraciones
  in-context, apoyándose en que el LLM ya conoce ese lenguaje. Supera a modelos texto→imagen en
  **20–40%** y llega a rendimiento comparable al humano en corrección numérica y espacial. **[V]**
- **LaySPA (2026)** usa **JSON con coordenadas** (x, y, w, h, categoría) y tokens `[MASK]`, y
  documenta la limitación central: los LLM **carecen de comprensión espacial intrínseca**, lo que
  les impide capturar alineación multi-objeto y jerarquías. Muestra fallos de GPT-5: no evitar
  regiones salientes, no alinear, tamaños inconsistentes. **[V]**
- **LaySPA entrena con recompensas geométricas** y mejora, sobre Qwen-7B: corrección de formato
  +14%, **alineación +63%**, **consistencia de espaciado +73%**, distribución +26%, **tasa de
  colisión −36%** — con solo 3.000 muestras frente a las 48.438 de PosterLlama. **[V]**
- **COLE (Microsoft Research Asia + PKU)** genera diseño gráfico **multicapa y editable** desde un
  prompt vago encadenando LLM/LMM/difusión especializados por rol (captioning por capa, planificación
  de layout, razonamiento, generación de imagen y texto), con editor tipo Canva. La representación no
  es una imagen plana: es **capas**, que es lo que la hace editable y corregible. **[S]**
- **AutoPresent (CVPR 2025)** construye **SlidesLib**, una API de alto nivel sobre `python-pptx`, en
  vez de dejar que el modelo emita código de bajo nivel. El modelo 8B con SlidesLib llega a 55.2
  frente a los 56.3 de GPT-4o; el paper concluye que **una librería programática bien diseñada es
  crítica** para que el modelo produzca código modular y ejecutable. **[S]**

### 2.2 HTML/CSS como target de render

- **Satori (Vercel)** convierte HTML/CSS a SVG con el **motor Flexbox de Yoga (WASM)**. Soporta
  flexbox, posición absoluta/relativa, padding/margin/gap, bordes, radios, sombras, gradientes,
  transformaciones 2D, **`textOverflow: ellipsis` y `lineClamp`**, y variables CSS. **No soporta
  `display: grid`**, ni `calc()`, ni z-index, ni RTL, ni WOFF2. Corre en navegador, Node 16+ y Web
  Workers. **[V]**
- `@vercel/og` envuelve Satori y rasteriza el SVG a PNG en edge runtimes. **[S]**
- En Python el equivalente no existe 1:1: las rutas reales son **WeasyPrint** (motor CSS propio en
  Python, orientado a paginación, exporta PDF/PNG) o **Playwright/wkhtmltoimage** (motor de
  navegador completo). Playwright es la opción con control CSS total sin servicio externo. **[S]**

### 2.3 Veredicto

- **[H]** CSS/flexbox es **mejor DSL de entrada para el LLM** que cajas con coordenadas absolutas,
  por dos razones convergentes: (a) el LLM tiene priors masivos sobre CSS —es lo que explota
  LayoutGPT— y (b) el motor de layout resuelve **automáticamente** la clase de fallo que LaySPA
  documenta como el punto débil del modelo (alineación, espaciado, colisión). En flexbox el modelo
  no puede solapar dos hermanos: la geometría se la calcula el solver, no el LLM.
- **[H]** Pero el coste de cambiar de target de render no es trivial: pasar Pillow → Playwright
  introduce Chromium en el pipeline (arranque, memoria, no determinismo de fuentes) y rompe la
  propiedad "$0, determinista" de Qualify. La salida barata es un **tercer camino**: mantener JSON +
  Pillow, pero que el JSON exprese **contenedores tipo flex** (`row`/`column`/`stack` con `gap`,
  `padding`, `align`, `flex`) resueltos por un mini-solver antes de rasterizar, en lugar de que el
  LLM emita `x`/`y` absolutas.
- **[V]** Existe soporte de Yoga fuera de JS (Satori usa el binario WASM de forma independiente), y
  Yoga tiene bindings nativos, así que un solver flex embebido en Python es una opción real y no
  requiere reimplementar CSS. **[H]** para la parte de "es viable en Qualify".
- **[H]** La lección de AutoPresent aplica directamente: la plantilla declarativa de Qualify **ya es**
  la SlidesLib de este dominio. Es un activo, no una deuda — el trabajo es subir su nivel de
  abstracción (primitivas compositivas), no bajarlo a coordenadas.

---

## §3. Validación determinista previa (antes de llamar a un modelo de visión)

### 3.1 La evidencia de que esto es lo que más rinde

- **EfficientPosterGen (2026)** sustituye la verificación de layout por MLLM con **ALVD (Agentless
  Layout Violation Detection)**, un algoritmo determinista de gradiente de color: parte el panel en
  franjas horizontales/verticales, calcula la magnitud del gradiente por franja, activa las que
  superan la mediana, hace el producto cartesiano para localizar contenido, y compara el bounding
  box mínimo contra los límites del panel (**overflow**) y el ratio de área cubierta contra un
  umbral (**sparsity**). Coste adicional en tokens: **cero**. **[V]**
- **El dato duro**: en el ablation, quitar ALVD sube el consumo de **10.35K a 84.78K tokens (8×)**,
  porque la detección poco fiable del MLLM dispara ciclos de regeneración innecesarios. **[V]**
- **AeSlides (2026)** define cuatro *verifiable rewards* y **mide al VLM contra ellas**: en
  cumplimiento de aspect ratio, la métrica programática obtiene **F1 = 0.83 frente a 0.24 de
  GPT-5.2**. Con ellas: errores de render al **0%**, whitespace excesivo **−44%**, colisiones de
  elementos **−43%**, desequilibrio visual **−28%**. **[V]**
- **[V]** AeSlides computa las métricas de dos fuentes distintas y esto importa: **colisión y
  balance desde la geometría** (árbol DOM + bounding boxes), **whitespace desde la imagen
  renderizada** (mapa de varianza local con filtro de caja 201×151, umbral τ=0.05).
- **[S]** La literatura converge en que el fallo típico de los VLM como jueces de layout es
  justamente el overflow: no lo detectan de forma fiable, y el overflow es lo que produce solape de
  texto y destruye la legibilidad.

### 3.2 Lista concreta de checks deterministas (orden de coste creciente)

Sobre la **geometría** (antes de rasterizar, coste ~0):

1. **Fuera de lienzo**: todo bbox debe cumplir `0 ≤ x`, `0 ≤ y`, `x+w ≤ W`, `y+h ≤ H`. **[V]** (tipo
   de colisión 3 de AeSlides)
2. **Escape de contenedor**: bbox del hijo contenido en el del padre. **[V]** (tipo 2 de AeSlides)
3. **Solape entre hermanos sin relación de ancestro**: intersección de rectángulos > umbral.
   **[V]** (tipo 1 de AeSlides)
4. **Alineación y consistencia de espaciado**: ejes compartidos, gaps uniformes. **[V]** (las dos
   métricas donde LaySPA obtuvo +63% y +73%)
5. **Balance visual**: offset del centroide de las unidades visuales respecto al centro del lienzo,
   con tolerancias asimétricas (AeSlides usa xtol=0.05, ytol=0.15). **[V]**
6. **Overflow de texto medido, no estimado**: con Pillow, `ImageFont.getbbox()` / `getlength()` da
   el ancho real del string en la fuente y tamaño concretos; comparar contra el ancho de caja
   detecta el desbordamiento **antes** de dibujar, y permite auto-fit (reducir tamaño o recortar).
   **[H]** — no lo he visto documentado en estos papers, pero es la contrapartida exacta del
   `textOverflow`/`lineClamp` que Satori resuelve por CSS **[V]**.
7. **Contraste WCAG**: ratio ≥ **4.5:1** para texto normal y **3:1** para texto grande (AA);
   7:1 / 4.5:1 (AAA). Calculable en cerrado desde los colores del layout. **[S]**

Sobre la **imagen renderizada** (coste bajo, sin tokens):

8. **Whitespace / densidad**: mapa de varianza local; regiones bajo umbral = espacio muerto. **[V]**
9. **Overflow por gradiente de color** (ALVD) cuando la geometría no es conocida —caso de imágenes
   incrustadas. **[V]**
10. **Contraste real texto/fondo**: muestrear el fondo bajo cada caja de texto y recalcular el ratio
    contra el color efectivo, no contra el color nominal del layout. **[H]**

### 3.3 Regla de arquitectura que se deduce

- **[H]** El VLM **nunca** debe ser el detector de defectos geométricos: es peor (F1 0.24 vs 0.83),
  es caro, y su poca fiabilidad dispara regeneraciones (8× tokens). El VLM debe juzgar solo lo que
  la geometría no puede: jerarquía visual, adecuación de la imagen al mensaje, y "esto parece de
  marca o parece un PowerPoint de 2006".

---

## §4. Qué hacen los productos comerciales

- **[S]** **Canva Magic Design** no genera layouts desde cero: analiza las imágenes/texto/idea
  aportados y **recomienda y adapta plantillas ya existentes** que encajan con el tema y estilo. La
  documentación propia lo describe como "arreglar y estilizar tu contenido", no como generación
  libre.
- **[S]** El blog de ingeniería de Canva publica sobre **recomendadores y re-ranking en el pipeline
  de búsqueda**, no sobre generación de layout. Eso es consistente con que Magic Design sea, en el
  fondo, **un problema de recuperación y ranking de plantillas**, no de síntesis.
- **[S]** **Microsoft Designer** sigue el mismo molde: plantillas + generación de imágenes desde
  prompt, editor estilo Canva.
- **[S]** **Figma AI** se posiciona en sugerencia de layouts responsivos y automatización de tareas
  repetitivas dentro del archivo, no en generar la composición completa. **Recraft** se especializa
  en generación vectorial editable.
- **[V] (por ausencia)** No he encontrado **ningún write-up de ingeniería público** de Canva,
  Microsoft o Figma que describa un bucle render→crítica-VLM→corrección en producción. Toda la
  evidencia de ese bucle es académica u open-source.
- **[H]** La convergencia comercial en "plantilla + relleno inteligente" en vez de "layout generado
  de cero" es la señal más fuerte del documento: los equipos con más recursos del sector eligen
  **restringir el espacio de diseño** y usar la IA para seleccionar y rellenar. Es exactamente la
  apuesta que Qualify ya hizo con plantillas JSON declarativas.

---

## §5. Recomendación concreta para Qualify

1. **No cambies el target de render.** Pillow determinista y $0 es una ventaja; Chromium/Playwright
   la destruiría. La lección de AutoPresent es que la librería de alto nivel *es* el activo.
2. **Sube el nivel del DSL, no lo bajes.** Sustituye `x`/`y` absolutas por contenedores
   `row`/`column`/`stack` con `gap`/`padding`/`align`/`flex`, resueltos por un mini-solver flex
   antes de rasterizar. Elimina por construcción solape y desalineación —los dos fallos que LaySPA
   demuestra que el LLM no sabe evitar.
3. **Construye el validador determinista primero** (§3.2, checks 1–7). Es lo de mayor ROI medido del
   documento: 8× menos tokens y F1 0.83 vs 0.24 frente a un VLM.
4. **Usa `ImageFont.getbbox()` como puerta de overflow** y auto-fit (bajar tamaño / `lineClamp`)
   antes de considerar el layout inválido.
5. **Best-of-N, no refinamiento secuencial.** Genera N=3–5 variantes, renderiza las N (coste ~0),
   puntúa con el validador determinista, devuelve la mejor. Solo si todas fallan, un ciclo de
   corrección con los defectos enumerados como texto.
6. **El VLM entra al final y por muestreo**, nunca por render: juzga jerarquía visual y adecuación de
   marca, no geometría. Si se usa, en crítica **de dos etapas** (observador visual → traductor a
   ediciones), que es la única configuración con ganancias reproducidas.
7. **Tope duro de 3 iteraciones** — la saturación está medida.
8. **Instrumenta las métricas desde el día 1**: tasa de colisión, overflow, whitespace, balance. Son
   la base de un eval set y, más adelante, de recompensas verificables si se afina un modelo.
9. **Contraste WCAG como check de marca**, no de accesibilidad: es el proxy barato de "el texto se
   lee sobre el thumbnail".
10. **[H]** El diferencial de Qualify no estará en el bucle de visión —eso es investigación pública—
    sino en tener plantillas de marca restringidas + validación dura + coste marginal cero.

---

## Fuentes

- Design2Code (paper): https://arxiv.org/pdf/2403.03163
- Design2Code (repo, métricas): https://github.com/NoviScl/Design2Code
- Design2Code (revisión secundaria): https://www.themoonlight.io/en/review/design2code-benchmarking-multimodal-code-generation-for-automated-front-end-engineering
- Vision-Guided Iterative Refinement for Frontend Code Generation: https://arxiv.org/html/2604.05839
- UI2Code^N: UI-to-Code Generation as Interactive Visual Optimization: https://arxiv.org/html/2511.08195v3
- Coding with Eyes: Visual Feedback Unlocks Reliable GUI Code Generating and Debugging: https://arxiv.org/abs/2604.19750
- VisRefiner: Learning from Visual Differences for Screenshot-to-Code Generation: https://arxiv.org/html/2602.05998
- Idea2Img (self-refinement con GPT-4V): https://arxiv.org/pdf/2310.08541
- screenshot-to-code: https://github.com/abi/screenshot-to-code
- LayoutGPT (NeurIPS 2023): https://arxiv.org/abs/2305.15393
- LayoutGPT (PDF): https://proceedings.neurips.cc/paper_files/paper/2023/file/3a7f9e485845dac27423375c934cb4db-Paper-Conference.pdf
- COLE (Microsoft Research): https://arxiv.org/html/2311.16974 · https://graphic-design-generation.github.io/
- LaySPA / LLMs as Layout Designers: https://arxiv.org/html/2509.16891
- AutoPresent (CVPR 2025): https://arxiv.org/html/2501.00912v1 · https://github.com/para-lost/AutoPresent
- EfficientPosterGen (ALVD): https://arxiv.org/html/2603.00155v1
- AeSlides (verifiable rewards): https://arxiv.org/html/2604.22840v1
- Satori (Vercel): https://github.com/vercel/satori
- Vercel OG Image Generation: https://vercel.com/docs/og-image-generation
- WeasyPrint: https://pypi.org/project/weasyprint/
- OG images con Playwright, coste cero: https://dev.to/morinaga/what-i-learned-generating-og-images-for-articles-with-playwright-and-zero-api-cost-3c0e
- Canva Magic Design (doc oficial): https://www.canva.com/help/use-magic-design/
- Canva Engineering — Search Pipeline: https://www.canva.dev/blog/engineering/search-pipeline-part-i/
- Canva Engineering — Recommender systems: https://www.canva.dev/blog/engineering/recommender-systems-when-they-fail-who-are-you-gonna-call/
- Figma / Recraft / Adobe Express (secundario): https://www.unite.ai/10-best-ai-graphic-design-tools/
- W3C WAI, herramientas de evaluación: https://www.w3.org/WAI/test-evaluate/tools/list/
