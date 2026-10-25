# Precios de los planes de Qualify: competencia, disposición a pagar y tres opciones

`[v1 2026-10-24 · m-24852145]` · Modo OFERTA (analista externo) con una recomendación de precio que
el fundador pidió expresamente. Fecha de acceso de todas las fuentes: **2026-10-24**.

> **Estado de la evidencia.** No hay ni un solo cliente que pague hoy. Bianki y Polette son
> negocios del propio fundador y la agencia de viajes y el inmobiliario no han recibido precio
> (`perfil-cliente-pyme.md` §5: «todavía no hubo entrevistas con clientes»). **Todo precio de este
> documento es hipótesis hasta que un cliente real lo acepte o lo rechace.** Lo que sí está
> sostenido con fuente es lo que cobra la competencia y lo que cuesta un community manager.

Convención: `[P]` primaria (página de precios o decreto, con URL y fecha) · `[S]` secundaria (blog,
nota de prensa, comparativa de tercero) · `[H]` hipótesis · `[F]` afirmación del fundador.
Costos de Qualify: `docs/modelo-cobro-generacion.md` (rama `docs/m-24852128-modelo-cobro-generacion`,
commit `f7290c3e`; aún no está en `main`).

---

## Decisión del fundador (2026-10-24)

**Esta sección manda sobre el resto.** El fundador eligió la **Opción C** del §3 y fijó la oferta de
arranque y los paquetes. La recomendación del §4 (Opción B, Pro no ofrecido al inicio, tope igual al
precio) **no se adoptó**; se conserva como el análisis que hubo antes de la decisión.

| | Básico | Plus | Pro |
|---|---:|---:|---:|
| **Precio completo, USD/mes** | **79** | **149** | **279** |
| COP (a 3.160) | 250.000 | 470.000 | 880.000 |
| UYU (a 40,3) | 3.190 | 6.000 | 11.200 |
| **Primer mes a mitad de precio, USD** | **39** | **75** | **139** |
| COP / UYU del primer mes | 120.000 / 1.570 | 235.000 / 3.020 | 440.000 / 5.600 |

Los tres planes se ofrecen desde el lanzamiento. Después del primer mes, precio completo.

**Paquetes de 90 días (USD / COP / UYU):** +2 videos **29** / 90.000 / 1.170 · +20 creaciones **12** /
38.000 / 480 · +10 vistas previas **19** / 60.000 / 770.

**Alertas de gasto en dólares por marca (siguen como estaban decididas):** Básico 120, Plus 240, Pro
480. Solo avisan en Lark y **nunca bloquean**. No se adoptó la sugerencia de igualar el tope al precio.

### Márgenes recalculados (margen bruto sobre generación; mismos costos y supuestos del §3)

Costos: típico 20 / 40 / 80 (Básico 15–25; Plus y Pro `[H]` proporcionales al cupo), peor caso
55 / 110 / 220, peor caso con videos de referencia 111 / 222 / 444.

| Caso | Básico | Plus | Pro |
|---|---:|---:|---:|
| **Precio completo**, mes típico | 75 % (rango 68–81 %) | 73 % | 71 % |
| Precio completo, peor caso | 30 % | 26 % | 21 % |
| Precio completo, peor caso con referencias | −41 % | −49 % | −59 % |
| **Primer mes (mitad de precio)**, mes típico | 49 % (rango 36–62 %) | 47 % | 42 % |
| Primer mes, peor caso | −41 % | −47 % | −58 % |
| Primer mes, peor caso con referencias | −185 % | −196 % | −219 % |

| Paquete | Precio | Margen mes típico | Margen peor caso |
|---|---:|---:|---:|
| +2 videos (final 5 s = 2,85 c/u típico; 10 s = 5,70 peor) | 29 | 80 % | 61 % |
| +20 creaciones (típico 0,06; techo 0,15) | 12 | 90 % | 75 % |
| +10 vistas previas (típico 5 s = 0,60; peor 10 s = 1,12) | 19 | 68 % | 41 % |

**Lo que esto implica, sin tocar la decisión:**

- A precio completo los tres planes cubren el peor caso (21–30 %) sin referencias; con videos de
  referencia de duración desconocida ninguno lo cubre.
- **El primer mes a mitad de precio no cubre el peor caso en ningún plan** y deja 42–49 % en un mes
  típico. Es una inversión en aprender el costo y el precio real; el costo por cliente que se regala
  en un primer mes pesado es de USD 16 (Básico), 35 (Plus) y 81 (Pro) según el peor caso.
- Las alertas de 120 / 240 / 480 equivalen a 2,2 veces el peor caso sin referencias y a 1,5 veces el
  precio completo del Básico: avisan, no limitan. Un negocio que llegue a la alerta ya costó más de lo
  que pagó (Básico: 120 contra 79). Quien mire Lark debe decidir qué hace en ese momento. `[H]` sobre
  cuántas veces ocurrirá; no hay datos.
- Las hipótesis P1–P6 del §4 y la escalera de preguntas del §6 siguen vigentes. La más frágil sigue
  siendo P1: ahora a USD 79 en vez de 49. El segmento es de presupuesto acotado y ningún cliente real
  ha dicho cuánto pagaría; la oferta de arranque es el instrumento para saberlo.

---

## 0. Lo primero: lo que contradice la dirección actual

1. **Los cupos de video no se pueden pagar con un precio «de herramienta».** Las herramientas con las
   que el dueño nos va a comparar cuestan USD 5–40 al mes (§1). El peor caso de nuestro Básico
   cuesta USD 55 (solo el costo de generación). **Ningún precio competitivo con esas herramientas
   cubre el peor caso, en ninguno de los tres planes.** Con los cupos actuales, el margen depende de
   que el dueño *no* agote los cupos. Eso es una apuesta de uso, no de precio.
2. **Predis.ai vende ~33 videos por USD 19** `[P]` (1.300 créditos ≈ 33 videos, plan Core). Qualify
   ofrece 4 videos generativos de ≤ 10 s. No se compiten con la misma cuenta: los de Predis son
   probablemente de plantilla `[H]`, los nuestros los genera un modelo de video y cuestan USD 3,36–6,72
   cada uno. Si el comprador compara «videos por dólar», perdemos. La comparación que ganamos es
   «publicaciones terminadas, aprobadas y publicadas, más respuestas asistidas» contra «yo hago todo con
   la herramienta» o contra un freelance.
3. **El peor caso no es un caso raro por diseño:** 20 vistas previas y 4 videos de 10 s dentro del
   mismo cupo es lo que un dueño entusiasta hace el primer mes. Un dueño que prueba a fondo cuesta
   USD 50+ y paga lo mismo que uno que usa poco. Ver riesgos (§5).
4. **Ni el costo típico está medido:** el documento de costos estima USD 9,90 para un mes liviano
   (2 videos de 5 s); el fundador estima USD 15–25. **Nadie ha creado un video en producción.**
   Los márgenes «típicos» de abajo se mueven con esa cifra (sensibilidad en §4).

---

## 1. Qué cobran la competencia y los sustitutos (USD)

### 1.1 Herramientas de redes con IA y planificadores

| Herramienta | Plan | USD/mes | Qué incluye | Lo que NO hace por el dueño | Fuente |
|---|---|---:|---|---|---|
| **Meta Business Suite** | único | 0 | Programar publicaciones y reels de Facebook e Instagram, bandeja de entrada. No encontré una función de generación de piezas con IA | Crear la pieza | `[S]` guías de uso (UPRM, Embedsocial), 2026-10-24. Sin página de precios consultada |
| **Buffer** | Free / Essentials / Team | 0 / 5 / 10 **por canal** | Free: 3 canales, 10 publicaciones programadas por canal, asistente de IA incluido | Crear imagen o video | `[P]` https://buffer.com/pricing, 2026-10-24 |
| **Metricool** | Free | 0 | 1 marca, 20 publicaciones programadas al mes, 5 créditos de IA | Crear imagen o video | `[P]` https://metricool.com/pricing/, 2026-10-24 |
| | Starter (5 marcas) | 20 anual / 25 mensual | Publicación sin límite (uso razonable), 20 créditos de IA por marca | idem | `[P]` ídem. La página no deja claro cuál columna es anual; el cálculo de qué cifra va con qué tab es mío. Una comparativa de Publer cita USD 22 `[S]` |
| | Advanced (15 marcas) | 53 anual / 67 mensual | Aprobación de publicaciones, gestión de clientes | idem | `[P]` ídem |
| **Later** | Starter | 18,75 (anual) | 1 conjunto social, 30 publicaciones por perfil, 5 créditos de IA | Crear imagen o video | `[P]` https://later.com/pricing/, 2026-10-24 |
| | Growth | 37,50 (anual) | Bandeja social, aprobaciones, 50 créditos de IA | idem | `[P]` ídem |
| **Hootsuite** | Standard | desde 99 (anual, por usuario) | 10 cuentas, IA para textos e imágenes | — | `[P]` https://www.hootsuite.com/plans, 2026-10-24 |
| **Canva Pro** | individual | 18 mensual / 144 anual (EE. UU.); **COP 32.000 en la página de Colombia** ≈ USD 10 | Diseño, programación básica, IA propia | Decidir qué publicar, publicar con aprobación | `[S]` guía de junio 2026 para USD; el COP sale de un fragmento de buscador de canva.com/es_co/precios sin aclarar si es mensual o anual. **Canva devolvió 403 a la consulta directa** |
| **Predis.ai** | Core | 19 mensual (230 al año; tachado 32) | 1.300 créditos ≈ 325 imágenes o 33 videos, 1 marca, 10 cuentas; **sin publicación automática** | Publicar solo | `[P]` https://predis.ai/pricing/, 2026-10-24 |
| | Rise | 40 mensual (tachado 79) | 3.200 créditos ≈ 800 imágenes u 80 videos, 4 marcas, publicación automática | — | `[P]` ídem |
| **Ocoya** | Starter | 29 | 300 créditos de IA, 5 perfiles | Aprobación humana de respuestas | `[P]` https://ocoya.com/pricing, 2026-10-24 |
| | Team | 79 | 1.500 créditos, 20 perfiles, 5 usuarios | — | `[P]` ídem |
| **Postnitro** | Starter / Creator+ / Team+ | 15 / 30 / 60 | Carruseles con IA; **programación solo desde Creator+** (10 cuentas) | Videos | `[P]` https://postnitro.ai/pricing, 2026-10-24 |
| **ManyChat** (respuestas y mensajes) | Pro | 15 (modelo anterior, 500 contactos) o 39 mensual / 29 anual (modelo desde 2026-03-02, 2.500 contactos activos) | Automatización de Instagram y WhatsApp. Plantillas de WhatsApp y tarifas de Meta aparte | No es asistida con aprobación; automatiza | `[S]` omidsaffari.com, chatbot.com, 2026-10-24. **La página oficial devolvió 403**; las guías de terceros discrepan |

**Lectura.**

- Las herramientas cuestan USD 0–40 y **ninguna crea la pieza lista por el dueño y con aprobación**
  (Predis y Ocoya generan, pero el dueño arma y decide el calendario). Es el espacio que Qualify ocupa.
  `[H]` de posicionamiento; Predis/Ocoya merecen una prueba real antes de afirmar que no hacen lo mismo.
- **No encontré ninguna herramienta con IA cuyo precio esté publicado en pesos colombianos, uruguayos
  o bolívares** salvo Canva. Todas cobran en USD (barrera real para VE y CO; Zelle o pago móvil
  funcionan a mano, no con tarjeta).
- Hootsuite está fuera del segmento (USD 99+).

### 1.2 Servicios: freelance, community manager y agencia

| Opción | País | Precio mensual | Qué incluye | Fuente |
|---|---|---|---|---|
| Freelance principiante | CO | COP 500.000–1.200.000 ≈ **USD 158–380** | — | `[S]` luzzidigital.com (vende cursos y herramientas; no cita fuente de los datos) |
| Freelance junior para pymes | CO | COP 800.000–1.500.000 ≈ **USD 253–475** | Gestión básica, diseño y publicaciones, sin pauta | `[S]` https://thinktic.co/blog/2026/02/01/guia-de-precios-de-community-manager-en-colombia-2025-cuanto-deberias-pagar/ |
| Emprendimientos o marcas personales | CO | COP 800.000–2.000.000 ≈ **USD 253–633** | — | `[S]` ídem |
| Pyme en expansión | CO | COP 2.000.000–5.000.000 ≈ USD 633–1.582 | — | `[S]` ídem |
| Agencia | CO | COP 3.000.000–7.000.000+ ≈ USD 949–2.215 | Estrategia, analítica y pauta | `[S]` ídem |
| Paquete «Esencial» LATAM | LATAM | **USD 350–600** | 8 publicaciones, 2 reels, 3 historias por semana, respuestas básicas | `[S]` luzzidigital.com |
| Paquete «Crecimiento» LATAM | LATAM | USD 600–1.000 | 12 publicaciones, 4 reels, historias diarias | `[S]` ídem |
| Solo programar publicaciones | LATAM | USD 150–400 | — | `[S]` ídem |
| Freelance LATAM (marco general) | LATAM | USD 200–600; agencia 500–1.500 | — | `[S]` ya recogido en `oferta-mercado-agencia-gestionada.md` §1.2 |
| Community manager en Venezuela | VE | **ingreso** USD 250–600 al mes; 500–1.000 en agencias internacionales | Es un ingreso total, no una tarifa por cliente. Una profesional dice que a los emprendimientos pequeños «pocos buscan el servicio y suelen pagar solo por un mes» | `[S]` El Diario, 2025-01-27 https://eldiario.com/2025/01/27/cuanto-gana-community-manager-venezuela-y-otros-paises/ |
| Community manager en Uruguay | UY | **salario** junior UYU 35.000–45.000 (≈ USD 870–1.120) | Sueldo, no tarifa por cliente | `[S]` Coderhouse (vende cursos), 2026. **No encontré tarifa de paquetes para pymes en Uruguay** |

Conversión usada: COP 3.160 por USD (TRM 2026-10-21: 3.163,76, Portafolio) `[S]`; UYU 40,3 por USD
(cierre BCU del 2026-08-06: 40,269, Ámbito) `[S]`, sin dato de octubre; Venezuela: referencia BCV
876,80 Bs por USD el 2026-10-13 `[S]` finanzasdigital.com. Los tres cambian; los precios locales
de §3 hay que recalcularlos el día que se publiquen.

**Lectura.**

- El paquete de un freelance típico entrega **8–12 publicaciones y 2–4 reels** por USD 250–600. Los
  planes de Qualify entregan 30 creaciones y 4 videos. La comparación en volumen favorece mucho a
  Qualify; la comparación en **confianza, criterio y trato personal** favorece al freelance
  (es quien conoce el negocio). `[H]`.
- **Hueco de precio:** entre las herramientas (USD 0–40) y el freelance más barato (USD ~160–250)
  casi no hay nada publicado. Ese hueco es donde caben USD 39–89. `[H]`: que esté vacío no prueba que
  haya demanda.

---

## 2. Disposición a pagar por país

Lo que se sabe y lo que no. No hay una sola encuesta de gasto de pymes en redes sociales en los tres
países que encontrara en las búsquedas de hoy.

| País | Moneda | Lo sostenible con fuente | Lo que falta |
|---|---|---|---|
| **Colombia** | COP | Salario mínimo 2026: Decreto 1469/2025 lo fijó en COP 1.750.905 (≈ USD 554); el Consejo de Estado lo suspendió y el Decreto 159 de 2026 fija uno transitorio (el Gobierno habló de «dos millones con auxilio») `[S]` El Tiempo/Portafolio. El freelance junior cobra COP 800.000–1.500.000. El 37 % de las pymes no tiene plan digital para 2026 y el 36,6 % destina menos del 10 % de su presupuesto a tecnología `[S]` dplnews.com / Alegra | Cuánto gasta una pyme en redes por mes; el monto de la tecnología no es de marketing |
| **Venezuela** | USD de hecho; Bs al BCV para pago móvil | Salario promedio en Caracas USD 241 en el 3.er trimestre de 2024 `[S]` (Cotejo, citado por El Diario). Los CM ganan USD 250–600 en total. Las consultorías a emprendimientos se pagan por un mes `[S]` El Diario | Tarifa por cliente; cuántos emprendimientos pagan algún servicio recurrente; estado actual de Zelle (las fuentes encontradas son de 2019–2020) |
| **Uruguay** | UYU | Salario mínimo UYU 24.572 desde enero y 25.383 desde julio de 2026 ≈ USD 630 `[P]` Decreto 319/2025 (IMPO) | Todo lo de pymes; la facturación desde una empresa colombiana a un cliente uruguayo |

**Inferencias, todas `[H]`:**

- Uruguay y Colombia tienen mayor capacidad que Venezuela. Si el precio se fija en dólares y es único
  para los tres países, Venezuela es el que más probabilidad tiene de rechazarlo; ahí ya hay clientes
  reales (Bianki, Polette), que son del fundador y no son prueba de disposición a pagar.
- Un dueño pequeño compara el precio con **lo que deja de ganar en el local**, no con herramientas.
  Referencia: USD 49 son ~9 % del salario mínimo colombiano y ~8 % del uruguayo. No hay dato de
  facturación de un local de shawarma.
- **Moneda y cobro.** El plan se cobra a mano (transferencia, Zelle, pago móvil). En Colombia y
  Uruguay el dueño piensa en pesos: un precio en dólares que cambia cada mes con la TRM genera
  fricción; conviene publicar precio local redondeado y revisarlo cada trimestre. En Venezuela el USD
  es la unidad de cuenta; el pago móvil se convierte al BCV del día. IVA (CO 19 %, UY 22 %): decidir
  si el precio lo incluye y quién factura `[H]`; consultar al contador, esto no está en ningún
  documento del repositorio.

---

## 3. Tres opciones de precio

Cupos fijos (decisión firmada): Básico 30 creaciones + 4 videos + 20 vistas previas; Plus 60/8/40;
Pro 120/16/80. Paquetes de 90 días: +2 videos, +20 creaciones, +10 vistas previas.

**Costos de Qualify que se usan** (de `modelo-cobro-generacion.md`; los de video son los que dio el
fundador, que difieren en centavos de los del documento: 3,44/6,82 contra 3,36/6,72):

- Peor caso por mes: **55 / 110 / 220** USD. Con videos de referencia: 111 / 222 / 444.
- Mes típico del Básico: **USD 15–25** (estimación del fundador; punto medio 20). El documento
  estima 9,90 para un mes liviano.
- Plus y Pro típicos: **USD 40 y 80** (`[H]`: se asume el mismo porcentaje de uso del cupo que en el
  Básico, es decir, costo proporcional al cupo; no hay datos).
- Para los paquetes: final de video 5 s = 2,85 y 10 s = 5,70; vista previa 5 s = 0,60 y 10 s = 1,12;
  creación = 0,15 como techo y ~0,06 típica (imagen p50 0,063, medido en producción).

**Qué NO incluye el margen.** Es margen bruto sobre generación únicamente. Quedan fuera: comisión de
cobro (Zelle ≈ 0; otras vías no investigadas), costos de WhatsApp por conversación, Claude para
intención y respuestas asistidas, servidor, soporte, impuestos, tiempo del equipo cobrando a mano.

### Opción A. «Entrada»: precio de herramienta

| | Básico | Plus | Pro |
|---|---:|---:|---:|
| **USD / mes** | **29** | **55** | **99** |
| COP (a 3.160) | 92.000 | 174.000 | 313.000 |
| UYU (a 40,3) | 1.170 | 2.220 | 3.990 |
| Margen bruto, mes típico | 31 % (rango 14–48 %) | 27 % | 19 % |
| Margen bruto, peor caso | −90 % | −100 % | −122 % |
| Paquetes (USD) | +2 videos 14 · +20 creaciones 5 · +10 vistas previas 7 | | |
| Margen de paquete típico / peor | 59 % / 19 % · 76 % / 40 % · 14 % / −60 % | | |

- **Frente a la competencia:** parecido a Predis Core (19) y Ocoya Starter (29), más barato que
  Metricool Advanced. Comprable «por impulso».
- **Frente a un freelance:** 6–11 % del freelance junior colombiano (USD 253–475). Muy por debajo.
- **Problema:** el Pro a 99 pierde dinero en un mes típico (80) casi sin margen y **no se sostiene en
  ningún mes pesado**. Solo se justifica si se confirma que el costo típico es ≤ USD 10 (el 9,90 del
  documento), en cuyo caso el Básico daría 66 %.

### Opción B. «Margen sano» (la recomendada)

| | Básico | Plus | Pro |
|---|---:|---:|---:|
| **USD / mes** | **49** | **89** | **159** |
| COP (a 3.160) | 155.000 → 150.000 | 281.000 → 280.000 | 502.000 → 500.000 |
| UYU (a 40,3) | 1.975 → 1.990 | 3.590 | 6.410 → 6.400 |
| Margen bruto, mes típico | **59 %** (rango 49–69 %) | 55 % | 50 % |
| Margen bruto, peor caso | −12 % | −24 % | −38 % |
| Margen bruto, peor caso con videos de referencia | −127 % | −149 % | −179 % |
| Paquetes (USD) | +2 videos **19** · +20 creaciones **7** · +10 vistas previas **12** | | |
| Margen de paquete típico / peor | 70 % / 40 % · 83 % / 57 % · 50 % / 7 % | | |

- **Frente a la competencia:** 2–2,6 veces Metricool Starter (25) y Predis Core (19); se justifica
  solo si el dueño valora que no tiene que hacer nada más que aprobar. `[H]`, y es la hipótesis más
  frágil del documento.
- **Frente a un freelance:** 10–19 % del freelance junior colombiano (USD 253–475) y 14 % del
  paquete «Esencial» más barato de LATAM (350). El Plus a 89 equivale a un cuarto del freelance
  más barato y entrega más volumen.
- Precios locales redondeados hacia abajo para que el precio tenga forma de precio (COP 150.000,
  280.000, 500.000; UYU 1.990, 3.590, 6.400) y se revisan cada trimestre.

### Opción C. «Acompañado»: cerca del servicio gestionado liviano

| | Básico | Plus | Pro |
|---|---:|---:|---:|
| **USD / mes** | **79** | **149** | **279** |
| COP (a 3.160) | 250.000 | 471.000 → 470.000 | 882.000 → 880.000 |
| UYU (a 40,3) | 3.190 | 6.000 | 11.240 → 11.200 |
| Margen bruto, mes típico | 75 % (rango 68–81 %) | 73 % | 71 % |
| Margen bruto, peor caso | 30 % | 26 % | 21 % |
| Margen bruto, peor caso con videos de referencia | −41 % | −49 % | −59 % |
| Paquetes (USD) | +2 videos 29 · +20 creaciones 9 · +10 vistas previas 15 | | |
| Margen de paquete típico / peor | 80 % / 61 % · 87 % / 67 % · 60 % / 25 % | | |

- **Frente a la competencia de herramientas:** 3–4 veces el precio de Metricool o Predis; solo se
  defiende si Qualify gana la comparación con el servicio, no con la herramienta.
- **Frente a un freelance:** 17–31 % del junior colombiano; 22 % del paquete «Esencial» de LATAM.
- **Problema:** el Básico a 79 es más de lo que un local de comida pequeño tiene ganas de pagar por
  presencia en redes `[H]`, y el segmento es de «presupuesto acotado» (`perfil-cliente-pyme.md` §0).
  Es el precio que sostiene el negocio, no el que probablemente se venda. Es la única opción que
  cubre el peor caso en los tres planes.

### Comparación en una línea

| | Básico | Plus | Pro | Cubre el peor caso | Riesgo principal |
|---|---:|---:|---:|---|---|
| A | 29 | 55 | 99 | ninguno | Se vende, no deja margen y el Pro es incosteable |
| **B** | **49** | **89** | **159** | ninguno | El peor caso pierde 12–38 %; precio alto frente a herramientas |
| C | 79 | 149 | 279 | sí (21–30 %) | Probablemente no se compra en el segmento |

**Margen de equilibrio.** A precio B, el costo real del mes tiene que ser menor a: Básico USD 49,
Plus 89, Pro 159 para no perder; para conservar 50 % de margen, ≤ 24,5 / 44,5 / 79,5, es decir, ≤ 45 %,
40 % y 36 % del peor caso. **El plan Pro es el más sensible:** se pierde dinero si el dueño usa más del
72 % del cupo en su versión más cara.

---

## 4. Recomendación

**Salir con la Opción B (49 / 89 / 159 USD; paquetes 19 / 7 / 12) como precio de lista, con tres
condiciones.** Es una recomendación sobre un mercado sin ventas; la confianza es media-baja.

1. **Por qué B y no A:** la A iguala a herramientas que no hacen el trabajo y deja margen cero en el
   Pro, que es el plan que más cuesta si se equivoca el supuesto de uso. **Por qué no C:** es la única
   que sobrevive al peor caso, pero es un precio de servicio y los sustitutos reales de este segmento
   son «nada» y «hacerlo yo en Canva por USD 0–10», no un freelance.
2. **Condición 1: Pro no se ofrece al principio.** Con B el Pro pierde 38 % en el peor caso y ningún
   dueño real ha llegado al volumen de un Pro (120 creaciones, 16 videos). Vender Básico y Plus,
   y dejar el Pro «a pedido» hasta tener 30 días de uso reales (`modelo-cobro-generacion.md` §8:
   disparador de 3 negocios con 30 días). Es una recomendación comercial; el cupo del Pro no se toca.
3. **Condición 2: el tope en dólares por marca va en el precio.** `monthly_budget_cap_usd` hoy está
   por debajo del peor caso (`modelo-cobro-generacion.md` §6 y §9.4). Con B, el tope razonable por plan
   es el precio del plan: 49 / 89 / 159 (decisión de ingeniería y del fundador, no mía). Así el peor
   caso nunca pierde más que el margen que dejó el plan.
4. **Condición 3: el precio sale con una oferta de arranque, no con un descuento permanente.** Los
   primeros clientes (ya hay cuatro rubros) prueban 30 días a precio de Opción A y pasan a B si
   renuevan. Eso da el dato de costo real (§8 del documento de costos) y de disposición a pagar sin
   anclar la lista en 29.

**Qué implica para el fundador (una línea):** el precio no puede ser competitivo contra herramientas y
cubrir los cupos a la vez; o se baja el cupo de vistas previas (20 de 10 s = USD 22,5 del peor caso)
o se acepta un peor caso con pérdida controlada por el tope en dólares.

### Hipótesis que sostienen la recomendación

| # | Hipótesis | Si es falsa | Cómo se verifica barato |
|---|---|---|---|
| P1 | Un dueño pequeño de CO/UY paga USD 49 por «presencia sin trabajo» | Se baja a A o se agrega un plan de entrada de USD 25–29 con 15 creaciones y 1 video | Cinco conversaciones de 15 min (agencia de viajes, inmobiliario, dos negocios vecinos de Bianki, uno en Montevideo) con la escalera de preguntas del §6; ninguna promesa de plazo |
| P2 | El costo típico del Básico es ≤ USD 25 | Con 35, el margen de B cae a 29 % | Los 30 días de Bianki y Polette (disparador del §8 del documento de costos) y la primera factura de BytePlus |
| P3 | El costo típico del Plus y del Pro es proporcional al cupo | El Pro quema margen o el cupo sobra | Mismo seguimiento; no se puede saber antes |
| P4 | Venezuela acepta el mismo precio en USD | Hace falta un Básico regional o un plan de entrada | La conversación del §6 con Bianki-adyacentes en San Cristóbal |
| P5 | La comparación del cliente es «freelance o nada», no «Canva gratis» | Hay que bajar a A | Preguntar qué usa hoy (pregunta 1 del `perfil-cliente-pyme.md` §5) |
| P6 | Los paquetes se compran mientras el plan sigue activo | Nadie compra paquetes; el cupo se agota y el cliente se va | «Pedir más a Qualify» (D11) mide cuántos pedidos llegan y de qué tipo |

---

## 5. Riesgos

1. **Pérdida controlada solo con tope.** Sin un tope en dólares por marca ≥ el precio del plan, un dueño
   puede costar más que lo que paga. Hoy el tope existe pero está desalineado (`modelo-cobro-generacion.md`
   §6). No hay nada que impida la pérdida si el tope se apaga.
2. **Costo sin medir.** El costo del final 1080p nunca se midió en vivo (H2) y no se sabe si BytePlus
   cobra tareas fallidas (H1). Si el final cuesta 20 % más, el peor caso del Básico sube a ~60.
3. **Sesgo de la muestra.** Los cuatro rubros son clientes del fundador; ninguno ha dicho cuánto pagaría.
4. **Frente a Predis/Ocoya.** Si una herramienta de USD 19–29 genera piezas y publica, la
   diferencia de Qualify se reduce a respuestas asistidas y a la aprobación humana. Probar Predis Rise
   y Ocoya con un negocio real antes de salir.
5. **Cobro a mano y tipo de cambio.** Cobrar en COP/UYU con un precio fijado en USD genera diferencias
   que absorbe Qualify. En Venezuela, el dueño paga en Bs con pago móvil al BCV del día.
6. **IVA y facturación.** Sin definir (§2). Si el IVA se suma, B pasa de USD 49 a ~58 en Colombia
   (19 %) y ~60 en Uruguay (22 %), y deja de ser «el precio» que el cliente ve.
7. **Anclaje.** La oferta de arranque a precio A (condición 3) puede dejar clientes que no renuevan a B.
   Es el costo de aprender el precio real.

---

## 6. Escalera de preguntas para validar precio (sin inventar demanda)

Para hacer en la misma conversación de 15–20 min del perfil de cliente, después de la pregunta 1
(`perfil-cliente-pyme.md` §5):

1. «¿Cuánto paga hoy por redes, en dinero y en horas de usted o de alguien?»
2. «Si alguien le dejara listas 30 publicaciones y 4 videos al mes para aprobar desde el celular, ¿a
   partir de qué precio mensual le parecería tan barato que desconfiaría?» (mínimo)
3. «¿A cuánto empieza a parecerle barato?»
4. «¿A cuánto empieza a parecerle caro, pero lo pensaría?»
5. «¿A cuánto ya no lo compraría?»

Anotar la respuesta literal y la moneda en que la dice (USD, pesos, bolívares). Con cinco respuestas
no hay estadística; sí se ve si el rango cae cerca de 29, 49 o 79.

---

## 7. Fuentes

Primarias (`[P]`), consultadas el 2026-10-24: Metricool https://metricool.com/pricing/ · Predis.ai
https://predis.ai/pricing/ · Ocoya https://ocoya.com/pricing · Hootsuite https://www.hootsuite.com/plans ·
Later https://later.com/pricing/ · Postnitro https://postnitro.ai/pricing · Buffer https://buffer.com/pricing ·
Decreto 319/2025 (salario mínimo de Uruguay, IMPO) https://www.impo.com.uy/bases/decretos/319-2025.
Los extractos de las páginas de precios los hizo una herramienta que resume la página; las tablas de
precios son de la propia página, la asignación de «anual» y «mensual» de Metricool es inferencia.

Secundarias (`[S]`): thinktic.co (guía de precios de community manager en Colombia, 2026-02-01) ·
luzzidigital.com (precios LATAM 2026) · El Diario (2025-01-27, community manager en Venezuela) ·
Coderhouse (salarios de community manager, Uruguay y Colombia) · Portafolio (TRM 2026-10-21) ·
Ámbito (dólar en Uruguay, 2026-08-06) · finanzasdigital.com (BCV 2026-10-13) · El Tiempo / Portafolio
(salario mínimo 2026 de Colombia) · dplnews.com (pymes sin plan digital) · omidsaffari.com y
chatbot.com (precios de ManyChat) · guías de Meta Business Suite · IAB Colombia (publicidad digital
2025, ya recogida en `oportunidades-mercado-discovery-co-ve.md`).

No verificado por falta de acceso: página oficial de Canva (403), página oficial de ManyChat (403),
tipo de cambio de Uruguay de octubre de 2026, estado actual de Zelle en Venezuela, tarifa de paquetes
de redes en Uruguay y en Venezuela por cliente.
