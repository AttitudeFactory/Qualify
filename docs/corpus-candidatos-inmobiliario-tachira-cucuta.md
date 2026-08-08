# Corpus de candidatos — asesores inmobiliarios Táchira (VE) / Cúcuta (CO)

**Owner:** gtm-specialist · **Fecha de investigación:** 2026-08-06 · **Estado:** EN CURSO (documento se escribe por secciones)
**Encargo:** sourcing de cuentas para el piloto del *hook-pattern detector* (`packages/models/NOTES_hook_pattern_spike.md` §C.1-C.5). No es un teardown de competencia.
**Autorización:** sólo investigación. **No se ha scrapeado, descargado ni gastado nada.** Lista para aprobación del fundador.

## Criterios de selección (de §C.1-C.5 del spike)

| # | Requisito | Por qué mata a un candidato |
|---|---|---|
| R1 | Asesor individual o agencia pequeña | Los portales nacionales publican inventario, no ganchos |
| R2 | ~30+ vídeos cortos publicados | Bajo eso la cuenta no llena su celda del diseño |
| R3 | **Variedad de aperturas entre sus vídeos** | El diseño compara tipos de hook **dentro de cada cuenta**; una cuenta que siempre abre igual aporta **cero**, tenga los vídeos que tenga |
| R4 | Métricas visibles (likes/comentarios/fecha) | Sin fecha no se quita la tendencia de crecimiento de la cuenta |
| R5 | Región: San Cristóbal / Táchira / Cúcuta | Mercado metropolitano transfronterizo, tratado como uno |

**R3 es el criterio escaso.** El spike lo dice explícitamente: la variedad de aperturas sólo se puede comprobar del todo *después* de extraer. Lo que aquí se aporta es evidencia parcial (portadas, títulos, primeros fotogramas, descripciones) y se marca como tal.

## Barra de honestidad aplicada a este documento

- Ninguna cifra de seguidores o de vídeos aparece aquí sin fuente nombrada y fecha.
- `no verificado` es un valor legítimo y frecuente en las tablas de abajo.
- Un handle que no resuelve se marca **NO CONFIRMADO** o se elimina; no se deja pasar como si existiera.

---

## Limitaciones de método (medidas, no supuestas) — 2026-08-06

| Superficie | ¿Se pueden leer métricas? | Evidencia |
|---|---|---|
| **Perfil de Instagram** (`instagram.com/<handle>/`) | **Sí, parcialmente.** Devuelve seguidores, seguidos, bio y, a veces, formato de los posts recientes. No devuelve un recuento fiable de reels vs posts | Verificado hoy sobre 4 perfiles; 4/4 devolvieron seguidores exactos |
| **Perfil de TikTok** (`tiktok.com/@<handle>`) | **No.** La página se renderiza en cliente; la herramienta sólo recupera el título `TikTok - Make Your Day`. **Cero métricas** | Verificado hoy sobre `@inmobiliarialunaroman` |
| **Páginas `tiktok.com/discover/...`** | Parcialmente: son páginas SEO generadas por TikTok que contienen descripciones de vídeos y nombres, pero **rara vez el handle** | Ver §Táchira |

**Consecuencia directa y no negociable para este documento:** ninguna cifra de seguidores o de vídeos de TikTok aparece verificada aquí. Donde el mercado vive en TikTok, la verificación de R2 (30+ vídeos) y de R3 (variedad de aperturas) **sólo se puede cerrar abriendo el perfil a mano en un navegador**, y eso lo tiene que hacer una persona. Es trabajo de ~2 min por cuenta, no de scraping.

---

## Tabla de candidatos

Leyenda de **Forma**: `IND` asesor individual · `AGE` agencia pequeña/mediana · `POR` portal/agregador (**descartado por R1**).
Leyenda de **R3 (variedad de aperturas)**: `?` sin evidencia · `~` evidencia parcial · `✗` indicios de plantilla repetida.

### Lado Colombia — Cúcuta / Los Patios / Villa del Rosario

| # | Cuenta | Plataforma | Forma | Seguidores (verificado 2026-08-06) | Formato reciente | R2 (30+ vídeos) | R3 | Notas |
|---|---|---|---|---|---|---|---|---|
| C1 | [@inmobiliariatonchala](https://www.instagram.com/inmobiliariatonchala/) | IG | AGE | **10.600** (perfil) | reels + carruseles | probable, no contado | ? | 48 años en la región; la más grande del lado CO encontrada |
| C2 | [@inmobiliariamarelsa](https://www.instagram.com/inmobiliariamarelsa/) | IG | AGE | **7.053** (perfil) | **todo el contenido reciente visible es vídeo** | probable, no contado | ? | Cúcuta + Los Patios + Villa del Rosario. Mejor señal de formato del lado CO |
| C3 | [@tu_hogarcucuta](https://www.instagram.com/tu_hogarcucuta/) | IG | AGE | **5.791** (perfil) | reels + carruseles | no verificado | ? | |
| C4 | [@lunaroman_inmobiliaria](https://www.instagram.com/lunaroman_inmobiliaria/) · [TikTok @inmobiliarialunaroman](https://www.tiktok.com/@inmobiliarialunaroman) | IG **y** TikTok | AGE | IG **3.955** (perfil) · TikTok **no verificable** | mezcla; en TikTok publica desde 2022 al menos | no verificado | ? | **Única cuenta confirmada con presencia real en ambas plataformas.** URLs de vídeo de TikTok resuelven en índice de búsqueda (2022 y 2023) |
| C5 | [@haddad_inmobiliaria](https://www.instagram.com/haddad_inmobiliaria/) | IG | AGE | pendiente | pendiente | pendiente | ? | |

### Lado Venezuela — San Cristóbal / Táchira

| # | Cuenta | Plataforma | Forma | Seguidores (verificado 2026-08-06) | Formato reciente | R2 (30+ vídeos) | R3 | Notas |
|---|---|---|---|---|---|---|---|---|
| V1 | [@tachirainmuebles](https://www.instagram.com/tachirainmuebles/) | IG | AGE | **9.601** (perfil) | mezcla: carruseles, reels y fotos | no verificado | ? | La mayor del lado VE encontrada. Destacados por tipo (Residencial/Terrenos/Comercial/Agropecuario) |
| V2 | [@alquileres.ventastachira](https://www.instagram.com/alquileres.ventastachira/) | IG | **IND** ("Asesor Inmobiliario" en bio) | **2.983** (perfil) | **predominan carruseles e imágenes**; vídeo no evidente | **dudoso** | ? | Forma correcta (individual), formato probablemente incorrecto |

### Descartados, con motivo

| Cuenta | Motivo |
|---|---|
| [@sc_inmobiliaria](https://www.instagram.com/sc_inmobiliaria/) | **Falso positivo geográfico: es de San Cristóbal, ARGENTINA** (verificado: prefijo telefónico 3408, Misiones). El buscador la devuelve para "San Cristóbal inmobiliaria" |
| [@realestate_octavio](https://www.instagram.com/realestate_octavio/) | **Falso positivo geográfico: México** (Tecámac, Tizayuca, Pachuca). 133 seguidores |
| [@inmobiliaria_habitatrd](https://www.instagram.com/inmobiliaria_habitatrd/) | Sufijo `rd` = **República Dominicana**, que también tiene un San Cristóbal. No verificado en detalle; descartado por geografía |
| Portales (`fincaraiz`, `properati`, `mercadolibre`) | **R1**: publican inventario, no ganchos |

> **"San Cristóbal" es un nombre trampa.** Hay al menos tres ciudades homónimas relevantes (Táchira VE, Buenos Aires/Misiones AR, República Dominicana) y el buscador las mezcla sin distinguir. Cualquier ampliación futura de esta lista tiene que verificar país **antes** de contar seguidores, o la lista se llena de ruido que parece señal.

## Hallazgos

### H1 — El riesgo dominante no es encontrar cuentas: es que el nicho publique **inventario**, no ganchos (R3)

Es el hallazgo que más debería cambiar el plan, y hay evidencia directa de él.

`@carlosjimenezbienesraices` (Cúcuta/Los Patios) es, por forma, **el candidato ideal**: asesor individual, **todo su contenido reciente visible es reel**. Sus cinco publicaciones más recientes abren así (verbatim, verificado en perfil 2026-08-06):

1. *"Urbanización Cerrada Escalar | Entrega inmediata y 3 meses Obra gris $215 Millones | Con acabados $280 Millones | Los Patios"*
2. *"Venta de Casa 140m² Construidos | Conjunto Mediterrané Villa del Rosario | $450 Millones"*
3. *"Casa en Urbanización abierta | Entrega en 1 mes | Trapiches Villa del Rosario | $215 Millones"*
4. *"Venta Casa Luxury 320m² Construidos | Conjunto Lagos Club Boconó | $1.200 millones"*
5. *"Venta de lotes | Financiamiento 36 meses | Conjunto Cerrado Boconó"*

Eso es **una única plantilla**: `[operación] + [m²/especificación] + [conjunto/ubicación] + [precio]`. Cinco de cinco. En la taxonomía A.4 del spike caerían todas en `price_reveal` o en `none_detected`.

**Salvedad metodológica que impide convertir esto en veredicto:** el spike (§A.1) excluye explícitamente el caption del hook — el hook son los 3 primeros segundos **del fichero de vídeo**. Un caption con plantilla **no demuestra** que el vídeo abra siempre igual. Pero es la mejor evidencia observable sin descargar, y apunta en una dirección incómoda: una cuenta que publica fichas de inventario suele abrir el vídeo con un plano de dron o un barrido del salón, **también con plantilla**.

**Consecuencia operativa:** el piloto de 50 vídeos / 3 cuentas de §C.5 deja de ser "recomendable" y pasa a ser **obligatorio**, y su pregunta principal cambia. No es *"¿cuál es la distribución de tipos de hook?"* sino la anterior: **"¿existe siquiera variedad de aperturas en este nicho y esta región?"** Si el piloto devuelve >70 % `none_detected`/`price_reveal`, el problema no es el corpus ni el tamaño de muestra — es que **este nicho no hace hooks**, y el detector no tendrá nada que detectar por muchos vídeos que se compren.

### H2 — La magnitud de engagement puede dejar el diseño sin varianza que explicar

Dos reels medidos individualmente hoy (única evidencia directa de engagement que pude obtener):

| Reel | Cuenta | Likes | Fuente |
|---|---|---|---|
| `DR5kGTUiZiR` | `@carlosjimenezbienesraices` (Cúcuta) | **1** | Página del reel, 2026-08-06 |
| `DSxzIzNAVL8` | `@ruthquirozrealtor` (**Bogotá**, no es de la región) | **36** | Página del reel, 2026-08-06 |

**n=2 y no es una muestra** — no lo trato como una medida del mercado, y no se debe citar como tal. Pero un reel con **1 like** en una cuenta de 738 seguidores plantea un riesgo que la Fase D del spike no contempla: el diseño normaliza engagement **dentro de cada cuenta**, y si los likes por vídeo de una cuenta viven en el rango 0-5, la variable dependiente es prácticamente ruido de conteo. Ninguna normalización recupera señal que no existe.

**Recomendación derivada:** añadir al piloto una comprobación previa y barata, **antes** de gastar en adquisición: para las 3 cuentas candidatas, mirar a mano el rango de likes de sus últimos ~10 vídeos. Si la mediana está por debajo de ~10 likes, esa cuenta no puede sostener una correlación, sea cual sea su hook. Es una comprobación de 10 minutos que puede ahorrar todo el corpus.

### H3 — Asimetría transfronteriza: Colombia rinde más que Venezuela, pero no por lo que parece

| | Cúcuta (CO) | San Cristóbal / Táchira (VE) |
|---|---|---|
| Cuentas localizadas y verificadas | 6 | 5 |
| Con seguidores verificados en perfil | 5 | 4 |
| Asesores **individuales** identificados | 1 (`@carlosjimenezbienesraices`) | 2 (`@alquileres.ventastachira`, `@casa_facil_sc`) |
| Formato dominante observado | **Reels/vídeo** (Marelsa: todo vídeo; Haddad: mayoría reels; Carlos Jiménez: todo reels) | **Mixto, con peso de carrusel/imagen** (`@alquileres.ventastachira`: predominan carruseles) |

La asimetría real **no es de cantidad de cuentas** — hay parecidas a ambos lados. Es de **formato**: el lado colombiano está claramente más movido a vídeo vertical; el venezolano conserva más carrusel de fotos. Para un corpus de hooks en vídeo eso importa mucho más que el número de cuentas, porque una cuenta de carruseles **no aporta ni un vídeo**.

Un segundo factor, específico de Venezuela y no medible desde aquí: `@casa_facil_sc` muestra su contenido reciente fechado entre **septiembre y noviembre de 2022**. No puedo distinguir si la cuenta está inactiva desde entonces o si es un límite de lo que la herramienta recupera — **queda marcado como no verificado**, no como dormancia confirmada.

## Recomendación

> **SIN ESCRIBIR — la sesión de sourcing se interrumpió aquí (2026-08-06).** Todo lo anterior está verificado y es utilizable; esta sección no existe. **No hay tres cuentas recomendadas.** Quien retome esto no debe leer la tabla de candidatos como una recomendación: ninguna cuenta ha pasado el criterio R3 (variedad de aperturas), que es el escaso.
>
> Lo que falta, en orden:
> 1. Las 3 cuentas del piloto, o la constatación de que no se pueden recomendar tres.
> 2. Si existe **contenido con gancho** (asesor hablando a cámara, decisión de vida, consejos/mitos) en Táchira/Cúcuta, o si el nicho sólo publica fichas de inventario — ver H1.
> 3. La precondición de H2 (mediana de likes de los últimos ~10 vídeos) aplicada a las cuentas que se recomienden.
>
> **Dos correcciones a este documento medidas después de escribirlo**, por el agente de adquisición:
> - La conclusión "TikTok no da métricas" es cierta para una descarga de HTML y **falsa para la vía de adquisición**: `yt-dlp` enumera cualquier handle gratis y da recuentos y fechas exactos. **R2 es verificable por máquina** — el trabajo manual de navegador presupuestado en §Limitaciones no hace falta.
> - **Los handles no son estables entre plataformas** (`@tu_hogarcucuta` en IG es `@tuhogarcucuta` en TikTok). Cualquier cuenta marcada aquí como sin presencia en TikTok necesita reprobarse con variantes antes de darla por ausente.
>
> Estado medido en TikTok sobre esta lista: **3 cuentas con catálogo real** (365, 196 y 150 vídeos) — un **suelo**, no un recuento.
