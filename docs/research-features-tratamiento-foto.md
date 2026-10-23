# Investigación — features de tratamiento de foto para el motor de contenido de marca

**Fecha:** 2026-08-18 · **Alcance:** qué operaciones de imagen necesita realmente un pipeline
determinista (foto de teléfono del operador + plantilla declarativa → composición Pillow → 1080×1350)
para dos negocios de comida en San Cristóbal. Investigación puramente web; no se leyó el código.

**Etiquetas de evidencia:** `[V]` fuente primaria enlazada (docs oficiales, repo, PyPI) ·
`[S]` fuente secundaria enlazada (blog técnico, comparativa, guía profesional) · `[H]` hipótesis mía,
no verificada.

---

## §0. Hallazgo previo a todo: higiene de entrada/salida (lo que nadie menciona y rompe todo)

Antes de cualquier "feature de diseño", hay cuatro cosas que degradan silenciosamente el resultado y
son baratísimas de arreglar. Esto es lo que un no-diseñador realmente no sabe que existe.

1. **Rotación EXIF.** Una foto de teléfono guarda su orientación como metadato, no como píxeles. Si
   abres con `Image.open()` y mides `.size` o recortas, obtienes la imagen acostada. La cura es una
   línea: `img = ImageOps.exif_transpose(img)` inmediatamente después de abrir, antes de medir,
   recortar o dibujar. `[V]` (`PIL.ImageOps`, [docs Pillow](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html)) `[S]` ([FixDevs](https://fixdevs.com/blog/pillow-not-working/))
2. **HEIC.** El iPhone entrega `.heic` por defecto; Pillow no lo abre sin plugin.
   `pillow_heif.register_heif_opener()` hace que `Image.open` lo trate como cualquier otro formato.
   `[V]` ([pillow-heif](https://pillow-heif.readthedocs.io/en/latest/pillow-plugin.html))
3. **Perfil de color Display P3 → sRGB.** El iPhone captura en Display P3. Si conviertes a JPEG sin
   convertir el perfil, los colores se desplazan (típicamente se apagan) cuando Instagram los pasa a
   sRGB. Convertir explícitamente a sRGB con `ImageCms` es obligatorio, no opcional. `[S]`
   ([Instagram export settings](https://www.wimarys.com/quality-photo-export-instagram/), [heicify](https://www.heicify.com/guides/heic-metadata-exif))
4. **Exportación para Instagram.** Redimensionar a 1080 px de ancho tú mismo (IG reescala todo lo
   más ancho), exportar JPEG a **calidad 85–90**, no 100: un archivo >~1.5 MB dispara una segunda
   pasada de compresión de Instagram y sale *peor* que el de 85. Y como reducir tamaño ablanda la
   imagen, aplicar un `UnsharpMask` suave **después** del resize. `[S]`
   ([wimarys](https://www.wimarys.com/quality-photo-export-instagram/), [pixelbatch](https://pixelbatch.io/blog/instagram-size-guide))

**Veredicto §0:** las cuatro son MVP, coste $0, ~40 líneas de código en total. Sin esto, cualquier
mejora estética posterior es ruido. `[H]`

---

## §1. Recorte de producto (background removal)

### Comparativa

| Opción | Calidad | Coste | Licencia | Local/nube |
|---|---|---|---|---|
| **rembg + `u2net`** (default histórico) | Sufre con pelo, bordes finos, transparencias; hace downsample interno y luego upsample de la máscara, lo que ablanda bordes `[S]` | $0 | Apache-2.0 (pesos) `[S]` | Local, CPU ok |
| **rembg + `birefnet-general` / `-lite`** | Estado del arte 2025-26; IoU ≈0.87 / Dice ≈0.92 promedio en dos datasets, contra IoU 0.39 de U²-Net en DIS5K `[S]` | $0 | **MIT** (pesos originales) `[S]` | Local; ~segundos/imagen en CPU, 17 FPS en RTX 4090 `[S]` |
| **rembg + `bria-rmbg`** (modelo por defecto actual, ~1.02 GB) | El mejor del paquete | $0 técnico | **BRIA: uso comercial requiere acuerdo de pago** `[V]` | Local |
| **remove.bg API** | Alta, consistente | ~$0.20/imagen `[S]` | Comercial | Nube |
| **PhotoRoom API** | Alta, orientada a e-commerce | Desde $20/mes por 1.000 imgs ≈ $0.02/imagen `[S]` | Comercial | Nube |
| **Chroma key (fondo verde)** | Requiere fondo grande y uniformemente iluminado; el *spill* verde rebota sobre el sujeto y produce bordes falsos; sujeto a 1–2 m del fondo y fondo al 50–70% de la exposición del sujeto `[S]` | $0 software, coste real = disciplina de estudio | — | Local |

### Refinamiento de bordes en rembg (poco conocido, gratis)

rembg expone tres modos de borde: *naive* (nada), **`decontaminate`** (elimina el halo de color en
bordes blandos) y **alpha matting** (más lento, máscara más precisa); además **ViTMatte** para
detalle fino tipo pelo. `[V]` ([repo rembg](https://github.com/danielgatis/rembg))

### Veredicto

**`rembg` con `birefnet-general-lite`, local, $0, licencia MIT.** `[H]` Razones: (a) el pipeline ya
es determinista y offline, meter una API de nube introduce red, clave y coste por imagen para un
negocio que publica ~10 gráficos/semana; (b) BiRefNet gana claramente en calidad de borde y su
licencia es la más limpia; (c) **hay que evitar explícitamente el modelo por defecto `bria-rmbg`**:
es el default del paquete y su licencia exige acuerdo pago para uso comercial `[V]` — un pie de bala
silencioso, porque funciona perfectamente y nadie se entera.

**Chroma key: no.** Cambia un problema de software (gratis, reproducible) por un problema de
disciplina física en el local de comida (iluminación uniforme, distancia al fondo, control de spill)
que el operador no va a sostener con el teléfono en una cocina. `[H]`

### Complemento obligatorio: sombra bajo el recorte

Un recorte pegado sobre color plano se ve "flotando" y grita "editado con app". La solución estándar
es una sombra sintética: tomar el canal alfa, desplazarlo unos píxeles, aplicar `GaussianBlur`,
pintarlo en negro semitransparente debajo del recorte. Pillow trae `ImageFilter.GaussianBlur` de
serie. `[V]` ([Pillow ImageFilter](https://pillow.readthedocs.io/en/stable/reference/ImageFilter.html)) `[H]` (la receta concreta es mía)

---

## §2. Legibilidad de texto sobre foto

Cuatro técnicas, en orden de rendimiento por línea de código:

1. **Scrim (gradiente semitransparente).** La técnica estándar: una capa oscura o clara
   semiopaca entre foto y texto "acalla" el fondo y crea una superficie de contraste consistente.
   `[S]` ([Smashing Magazine](https://www.smashingmagazine.com/2023/08/designing-accessible-text-over-images-part1/), [NN/g](https://www.nngroup.com/articles/text-over-images/))
   En Pillow: `Image.new("L", ...)` con un degradado vertical + `Image.composite`. `[H]`
2. **Umbral WCAG.** Texto normal sobre imagen necesita ≥ **4.5:1**; texto grande (≥24 px, o 19 px en
   negrita) ≥ **3:1**. WCAG no define cómo medir contra un fondo fotográfico: la práctica es medir
   la zona donde el contraste es *mínimo*. `[S]` ([WCAG.com](https://www.wcag.com/blog/content-over-images-how-does-this-ux-ui-trend-impact-accessibility/), [WebAIM](https://webaim.org/articles/contrast/))
   Implementación: `wcag-contrast-ratio` en PyPI calcula la ratio; se usa para **elegir
   automáticamente texto blanco o negro** midiendo la luminancia media del parche de foto bajo la
   caja de texto, y para **subir la opacidad del scrim hasta que la ratio pase el umbral** —un bucle
   de 3 iteraciones. `[V]` ([PyPI](https://pypi.org/project/wcag-contrast-ratio/)) `[H]` (el bucle es mío)
3. **Contorno y sombra de texto.** Pillow lo trae nativo desde 6.2.0: `ImageDraw.text(...,
   stroke_width=N, stroke_fill=color)`. No hace falta ninguna librería extra. `[V]`
   ([ImageDraw](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html), [release notes 6.2.0](https://pillow.readthedocs.io/en/stable/releasenotes/6.2.0.html))
4. **Colocación evitando zonas ocupadas (saliency).** `cv2.saliency.StaticSaliencySpectralResidual_create()`
   devuelve un mapa en [0,1] donde 1 = "interesante". Colocar el bloque de texto donde la saliencia
   media es baja. `[V]` ([OpenCV](https://docs.opencv.org/4.x/df/d37/classcv_1_1saliency_1_1StaticSaliencySpectralResidual.html)) `[S]` ([PyImageSearch](https://pyimagesearch.com/2018/07/16/opencv-saliency-detection/))
   Requiere `opencv-contrib-python`, no el `opencv-python` normal. `[V]`

**Veredicto:** (1)+(2)+(3) son MVP y juntas resuelven ~95% del problema. (4) es "después": con
plantillas declarativas la posición del texto ya está fijada por diseño, y la saliencia solo aporta
cuando quieres que el layout se adapte a la foto. `[H]`

---

## §3. Mejora automática para comida

Lo que la práctica profesional dice, y es sorprendentemente estrecho:

- **Balance de blancos es la base de todo**, más importante que cualquier otro ajuste; el color es
  el disparador de apetito primario. `[S]` ([foodphotographerstudio](https://foodphotographerstudio.com.sg/white-balance-food-photography-colour-guide/))
- **Tonos cálidos** (rojos/naranjas/amarillos) hacen la comida más apetecible, especialmente
  horneados, sopas y comida de consuelo; se cita investigación en *Frontiers in Psychology* sobre
  colores cálidos y estimulación del apetito. `[S]` ([ICE](https://www.ice.edu/blog/food-photography-editing), [PRO EDU](https://proedu.com/blogs/news/lightroom-workflow-food-photography))
  No verifiqué el paper original — trátalo como `[S]`, no como hecho establecido.
- **Saturación: el error clásico es pasarse.** La guía repetida es mantenerla por debajo de **+10**
  (algunas fuentes dicen <15%); sobresaturar hace que la comida se vea falsa. `[S]`
  ([PRO EDU](https://proedu.com/blogs/news/lightroom-workflow-food-photography), [foodshot](https://foodshot.ai/blog/food-color-grading))
- **CLAHE** (contraste adaptativo por baldosas, `cv2.createCLAHE(clipLimit, tileGridSize)`) mejora
  contraste local sin amplificar ruido, útil con iluminación irregular — exactamente el caso de una
  foto de teléfono en un local. `[V]` ([OpenCV](https://docs.opencv.org/4.13.0/d5/daf/tutorial_py_histogram_equalization.html)) `[S]` ([Analytics Vidhya](https://www.analyticsvidhya.com/blog/2022/08/image-contrast-enhancement-using-clahe/))
  Aplicarlo **solo al canal L de LAB**, con `clipLimit` bajo (~2.0), nunca a RGB directo: sobre RGB
  desplaza los colores. `[H]`

**Preset "comida" propuesto (determinista, sin ML):** `exif_transpose` → P3→sRGB →
temperatura +200–300K → CLAHE(L, clip=2.0) → `ImageEnhance.Color(1.08)` (equivalente a +8 de
saturación) → `ImageEnhance.Contrast(1.05)` → resize 1080 → `UnsharpMask(radius=1, percent=60)`.
Todo con Pillow + OpenCV, $0, ~30 líneas. `[H]`

**Dos presets, no uno:** el shawarma (tonos ámbar, quiere calidez) y el helado de yogur (blanco con
toppings de color, la calidez lo pone amarillo) necesitan curvas distintas. Un solo preset "comida"
va a arruinar el helado. `[H]`

---

## §4. Recorte inteligente multi-formato (4:5 → 1:1 → 9:16)

- **`smartcrop.py`** (PyPI, port del `smartcrop.js` de Jonas Wagner): dado un ancho/alto objetivo
  encuentra el mejor encuadre; usable como módulo y como CLI `smartcroppy`. Heurístico (bordes,
  saturación, piel), sin dependencias pesadas. `[V]` ([PyPI](https://pypi.org/project/smartcrop/0.4.0))
- **Katna**: pasa todos los recortes posibles por filtros de regla de tercios, saliencia, detección
  de caras y bordes. Más pesado, pensado para vídeo+imagen. `[S]` ([Medium](https://aloksaan.medium.com/smart-image-cropping-with-katna-1b4c0341ed24))
- **OpenCV saliency + centroide**: calcular el mapa de saliencia, tomar el centro de masa de la
  región saliente y encuadrar la ventana del aspecto objetivo alrededor. ~15 líneas. `[V]` (API) `[H]` (la receta)
- **auto-crop / smart-resizer**: variantes basadas en detección de caras y GAIC. `[S]`

**Veredicto:** `smartcrop.py` para MVP (una dependencia ligera, resuelve el 4:5→1:1→9:16 sin
modelos), con el fallback de saliencia OpenCV si los resultados decepcionan con platos de comida
—smartcrop está afinado para fotos con caras y puede no priorizar bien un plato. `[H]`

---

## §5. Consistencia de lote

El problema real: 10 fotos del mismo día, luz cambiante, se ven como 10 posts distintos.

- **`skimage.exposure.match_histograms(image, reference)`**: hace *coincidir* el histograma de cada
  foto con el de una foto de referencia, canal por canal. Es la técnica estándar de normalización de
  color en pipelines de imagen, precisamente para "obtener una representación consistente aunque
  cambien las condiciones de luz". `[V]` ([scikit-image](https://scikit-image.org/docs/0.20.x/auto_examples/color_exposure/plot_histogram_matching.html)) `[S]` ([PyImageSearch](https://pyimagesearch.com/2021/02/08/histogram-matching-with-opencv-scikit-image-and-python/))
- **Transferencia de color Reinhard** (media/desviación en espacio Lab): más suave que el histogram
  matching, menos propenso a artefactos; es el clásico de Reinhard et al., *IEEE CG&A*. `[S]`
  ([arXiv](https://arxiv.org/pdf/1612.08927))

**Veredicto:** una **foto de referencia por marca** (la "look plate", elegida una vez) + Reinhard
como default y `match_histograms` como opción agresiva. Coste $0. Esto es lo que convierte "fotos de
teléfono" en "feed con identidad" y es, después de §0, el feature de mayor retorno por línea. `[H]`
Riesgo: aplicado sobre platos de colores muy distintos (shawarma vs. helado de yogur) la transferencia puede
falsear el color del producto; limitarla al 50–70% de intensidad. `[H]`

---

## §6. Qué NO construir

- **Chroma key.** Ver §1. Traslada el coste a un procedimiento físico que no se va a mantener. `[H]`
- **API de nube para recorte** (remove.bg a $0.20/imagen). A este volumen el ahorro absoluto es
  trivial pero rompe las dos propiedades que el pipeline sí tiene: determinismo y $0. `[H]`
- **Perfección de recorte a nivel pelo/vapor.** El benchmark que separa BiRefNet de U²-Net es
  precisamente pelo y transparencias; en un plato de comida sobre superficie sólida esa diferencia
  casi no se manifiesta. No inviertas en matting fino. `[H]`
- **Filtros "estéticos" tipo Instagram** (`pilgram` y similares). Fechan el contenido y compiten con
  la identidad de marca que las plantillas ya definen. `[H]`
- **Sobre-pulido en general.** Es la evidencia más contraintuitiva y la más relevante para este
  caso: el contenido crudo/detrás-de-cámara supera al contenido pulido de marca por factores de
  2–3× en engagement, y 77% de consumidores dicen preferir contenido que se siente genuino
  (Sprout Social). `[S]` ([zaps.design](https://medium.com/@zaps.design/why-behind-the-scenes-beats-polished-brand-content-by-a-factor-of-two-c7aa2830a513), [Fletcher](https://www.fletchercomms.com/09/the-rise-of-relatable-why-authenticity-on-social-media-outperforms-polished-content/))
  Estas cifras vienen de blogs de marketing, no de estudios revisados — pero apuntan todas en la
  misma dirección. **Consecuencia de diseño:** el objetivo del pipeline no es "que parezca de
  agencia", es *consistencia de marca* (tipografía, color, layout, legibilidad) sobre fotos que
  siguen pareciendo reales. Todo feature que persiga realismo de estudio está optimizando la métrica
  equivocada. `[H]`
- **Detección de caras / GAIC / modelos de crop aprendidos.** Sobredimensionado: aquí el sujeto es
  un plato, no una persona. `[H]`
- **Upscaling con IA.** La foto ya viene a 12 MP y el destino es 1080×1350. Se está tirando
  resolución, no faltando. `[H]`

---

## §7. Lista priorizada final

| # | Feature | Librería | Coste | Cuándo |
|---|---|---|---|---|
| 1 | `exif_transpose` en toda foto de entrada | Pillow `ImageOps` | $0 | **MVP** |
| 2 | Soporte HEIC | `pillow-heif` | $0 | **MVP** |
| 3 | Conversión Display P3 → sRGB | Pillow `ImageCms` | $0 | **MVP** |
| 4 | Export: resize 1080 + `UnsharpMask` + JPEG q85–90 | Pillow | $0 | **MVP** |
| 5 | Scrim/gradiente bajo bloques de texto | Pillow `Image.composite` | $0 | **MVP** |
| 6 | Contorno/sombra de texto (`stroke_width`) | Pillow `ImageDraw` | $0 | **MVP** |
| 7 | Selección auto blanco/negro por ratio WCAG + opacidad de scrim adaptativa | `wcag-contrast-ratio` | $0 | **MVP** |
| 8 | Preset de mejora por marca (WB cálido, CLAHE en L, saturación ≤+10) | OpenCV + `ImageEnhance` | $0 | **MVP** |
| 9 | Recorte de fondo | `rembg[birefnet-general-lite]` — **no** `bria-rmbg` | $0, MIT | **MVP** si el layout usa recortes; si no, después |
| 10 | Sombra sintética bajo el recorte | Pillow `GaussianBlur` sobre el alfa | $0 | Con el #9 |
| 11 | Consistencia de lote (Reinhard / `match_histograms`) contra foto de referencia por marca | `scikit-image` | $0 | **Después** (tras 2–3 semanas de fotos reales) |
| 12 | Recorte inteligente multi-formato | `smartcrop.py` | $0 | **Después** (cuando haya 2º formato) |
| 13 | Colocación de texto guiada por saliencia | `opencv-contrib-python` | $0 | **Después**, solo si las plantillas dejan de ser fijas |
| 14 | Refinamiento de borde ViTMatte / alpha matting | `rembg -a` / `-vm` | $0, lento | **Después**, solo si se ve halo |
| 15 | API de nube de recorte (PhotoRoom ~$0.02/img) | — | $0.02/img | **Nunca** a este volumen |
| 16 | Chroma key | — | Coste operativo | **Nunca** |
| 17 | Filtros estéticos, upscaling IA, detección de caras | — | — | **Nunca** |

**Lectura de una línea:** de 17 candidatos, 10 son MVP, todos $0 y todos Pillow/OpenCV/skimage; el
mayor riesgo del proyecto no es la falta de features sino los ítems 1–4, que fallan en silencio, y
la licencia BRIA del modelo por defecto de `rembg`.

---

## Sources

- [rembg (repo oficial)](https://github.com/danielgatis/rembg) · [BiRefNet vs rembg vs U2Net](https://dev.to/om_prakash_3311f8a4576605/birefnet-vs-rembg-vs-u2net-which-background-removal-model-actually-works-in-production-4830) · [Evaluating segmentation models — Cloudflare](https://blog.cloudflare.com/background-removal/) · [BiRefNet notes](https://ice-ice-bear.github.io/posts/2026-04-15-birefnet/)
- [PhotoRoom vs Remove.bg API](https://www.photoroom.com/api/photoroom-vs-removebg) · [Best background removal APIs — pricing](https://ai-engine.net/blog/best-background-removal-apis)
- [Green screen: reducir spill](https://www.procyc.com/how-to-reduce-spill-in-your-greenscreen-setup/) · [Iluminar sin spill](https://studio-supplies.com/blogs/guides/light-green-screen-without-spill)
- [Smashing — Accessible text over images (1)](https://www.smashingmagazine.com/2023/08/designing-accessible-text-over-images-part1/) · [(2)](https://www.smashingmagazine.com/2023/08/designing-accessible-text-over-images-part2/) · [NN/g](https://www.nngroup.com/articles/text-over-images/) · [WCAG.com](https://www.wcag.com/blog/content-over-images-how-does-this-ux-ui-trend-impact-accessibility/) · [WebAIM](https://webaim.org/articles/contrast/) · [wcag-contrast-ratio (PyPI)](https://pypi.org/project/wcag-contrast-ratio/)
- [Pillow ImageDraw](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html) · [Pillow 6.2.0 release notes](https://pillow.readthedocs.io/en/stable/releasenotes/6.2.0.html) · [Pillow ImageOps](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html) · [pillow-heif](https://pillow-heif.readthedocs.io/en/latest/pillow-plugin.html)
- [OpenCV — Histogram Equalization / CLAHE](https://docs.opencv.org/4.13.0/d5/daf/tutorial_py_histogram_equalization.html) · [CLAHE explicado](https://www.analyticsvidhya.com/blog/2022/08/image-contrast-enhancement-using-clahe/) · [OpenCV StaticSaliencySpectralResidual](https://docs.opencv.org/4.x/df/d37/classcv_1_1saliency_1_1StaticSaliencySpectralResidual.html) · [PyImageSearch — Saliency](https://pyimagesearch.com/2018/07/16/opencv-saliency-detection/)
- [PRO EDU — Lightroom para food photography](https://proedu.com/blogs/news/lightroom-workflow-food-photography) · [White balance en comida](https://foodphotographerstudio.com.sg/white-balance-food-photography-colour-guide/) · [ICE — 6 editing tips](https://www.ice.edu/blog/food-photography-editing) · [FoodShot — color grading](https://foodshot.ai/blog/food-color-grading)
- [smartcrop (PyPI)](https://pypi.org/project/smartcrop/0.4.0) · [Katna](https://aloksaan.medium.com/smart-image-cropping-with-katna-1b4c0341ed24) · [smart-resizer](https://github.com/madcat1991/smart-resizer)
- [scikit-image — Histogram matching](https://scikit-image.org/docs/0.20.x/auto_examples/color_exposure/plot_histogram_matching.html) · [PyImageSearch — Histogram matching](https://pyimagesearch.com/2021/02/08/histogram-matching-with-opencv-scikit-image-and-python/) · [Fast color transfer from multiple images (arXiv)](https://arxiv.org/pdf/1612.08927)
- [Export settings para Instagram](https://www.wimarys.com/quality-photo-export-instagram/) · [Instagram size guide 2026](https://pixelbatch.io/blog/instagram-size-guide) · [HEIC EXIF: qué sobrevive](https://www.heicify.com/guides/heic-metadata-exif) · [Pillow: errores de rotación EXIF](https://fixdevs.com/blog/pillow-not-working/)
- [Behind-the-scenes vs contenido pulido](https://medium.com/@zaps.design/why-behind-the-scenes-beats-polished-brand-content-by-a-factor-of-two-c7aa2830a513) · [Fletcher — autenticidad](https://www.fletchercomms.com/09/the-rise-of-relatable-why-authenticity-on-social-media-outperforms-polished-content/) · [ContentStudio — tendencias foto IG](https://contentstudio.io/blog/instagram-photo-trends)

---

## Adenda (2026-08-18, fundador): BiRefNet como servicio — el upgrade path ya está pagado

Hallazgo del fundador sobre el repo oficial de BiRefNet: el modelo está desplegado como API de
inferencia en terceros, y el que importa es **fal.ai** — `fal-ai/birefnet/v2` `[V]`
(https://fal.ai/models/fal-ai/birefnet/v2; el propio autor agradece a fal el patrocinio de GPU).
Precio por segundo de cómputo; el por-imagen no es visible sin JS `[S]`.

**Por qué esto importa más de lo que parece:** fal ya es nuestro agregador primario (ADR 32 D5).
El recorte por API no introduce vendor nuevo, ni key nueva, ni adaptador nuevo — **cabalga el
`FalAdapter` que ya está diseñado**, como una `GenerationTask` más. El upgrade path cuesta cero
arquitectura.

**La cadena de recorte queda en dos eslabones, y la regla de cuándo saltar es simple:**

| Eslabón | Cuándo | Coste |
|---|---|---|
| 1. Local — `rembg[birefnet-general-lite]` (MIT) | Default. 1–3 fotos por pieza, CPU sobra, las fotos no salen de casa | $0 |
| 2. fal — `fal-ai/birefnet/v2` (modelo completo, GPU) | Lote grande (sesión de 50 fotos), o cuando el borde del lite no dé la talla | ~céntimos `[S]` |

**Y el zoo de modelos responde al ítem 14 (halo):** existen `BiRefNet-matting`, `BiRefNet_HR`
(2048px) y `BiRefNet_dynamic` (cualquier resolución) `[V]` — el matting es exactamente el
refinamiento de borde para cristal/espuma que el ítem 14 dejaba condicionado. Si el halo aparece,
el orden de escalada es: `-matting` local → HR local → fal v2, no ViTMatte a ciegas.
