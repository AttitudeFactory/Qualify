# Calendario de inversión y plan del mes (m-25091392, parte 1)

Estado: **PROVISIONAL**. Reglas aprobadas por Raul el 2026-11-23; fechas investigadas el mismo día.

## Qué hace

Toma el tope mensual del perfil de inversión (`monthly_cap_minor`) y lo reparte entre las semanas
del mes según su peso. Es solo una sugerencia de lectura: **no se envía nada a Meta y no se guarda
nada** (no hay tabla ni migración).

- Código: `packages/api/src/qualify_api/ads/month_plan.py` — `month_plan(tenant_id=, brand_id=,
  year=, month=)` → `MonthPlan | None` (None: sin perfil de inversión o sin tope).
- Datos: `packages/api/src/qualify_api/ads/data/calendario-v1.json` — cada fecha con su regla,
  su nivel, su grupo de rubros, `status` (`verified` con su fuente / `hypothesis`) y `source`.
- Pruebas: `packages/api/tests/test_ad_month_plan.py`.

## Reglas

1. Semanas de lunes a domingo, recortadas al mes. Un pedazo de 3 días o menos al principio o al
   final se suma a la semana vecina (4 o 5 filas).
2. Niveles (hipótesis): normal 1,0; pago o fecha menor 1,25; fecha grande 1,5. Una fecha grande
   sube también las semanas con alguno de los 10 días anteriores. Gana el nivel más alto; no se
   multiplican.
3. Peso de una semana = días del mes que tiene × nivel.
4. Monto = tope × peso ÷ suma de pesos, hacia abajo con el mismo paso que muestra
   `investment_profile.py` ($1.000 en COP, unidad entera en USD y UYU). Lo que sobra va a la
   semana más pesada (la primera si empatan): la suma es siempre exactamente el tope.
5. Rubro: una fecha cuenta solo si el rubro del Brand Kit (`brand_kit_details.connect.sector`,
   uno de los 8 de `discovery_seed.NICHE_LABELS`) está en su grupo. Sin rubro, cuentan todas.
6. País y moneda: la moneda es la de la cuenta publicitaria elegida
   (`investment_profile.default_currency`); el país es el que `mercado-v1.json` asocia a esa
   moneda (COP → Colombia, USD → Venezuela, UYU → Uruguay). Un perfil guardado en otra moneda no
   se mezcla: se pide volver a guardar el perfil. Otra moneda: el mensaje `CURRENCY_UNSUPPORTED`
   de `money.py`.

Ejemplo verificado en las pruebas: Colombia, mayo de 2027, rubro comida y bebida, tope
$1.200.000 COP → $414.000 / $267.000 / $214.000 / $305.000 COP.

## Fechas

Las fechas, sus reglas y sus fuentes están en el JSON. Resumen:

- **Colombia:** quincenas (15 y 30), prima (30 jun., 20 dic.), Navidad, regreso a clases
  (Bogotá, 25 ene. 2027), Hot Sale (2 ediciones, fechas 2027 hipótesis), Día del Niño, de la
  Madre, del Padre, Amor y Amistad, Halloween (31 oct., fecha menor, añadida por Raul), Black
  Friday y Cyber Monday. El Día sin IVA no existe en 2027 (derogado, Ley 2277 de 2022).
- **Venezuela (USD):** quincenas (15 y último), utilidades y aguinaldos (1–15 dic., día
  hipótesis), Navidad, regreso a clases (enero y septiembre), Carnaval, Enamorados, Día de las
  Madres, del Padre, del Niño, Black Friday (fecha menor).
- **Uruguay:** sueldo (5 primeros días hábiles), aguinaldo (30 jun., 20 dic.), Navidad, Reyes,
  Carnaval, San Valentín, regreso a clases, Día de la Madre, CyberLunes (2 ediciones, 2027
  hipótesis), Día del Padre, de la Niñez, de los Hijos y Black Week. Las fechas de regalo las
  fija la CCSUy cada año: las de 2027 son hipótesis hasta que publique su calendario.

## Mantenimiento

- **Cada diciembre, a mano:** revisar las fechas que se anuncian cada año (Hot Sale, CyberLunes,
  regreso a clases, calendario de la CCSUy) y lo que cambie una fuente. Si cambian niveles,
  ventana o rubros, nueva versión (`calendario-v2`). Si se olvida, la prueba
  `test_yearly_ranges_cover_this_year` falla el 1 de enero.

## Mejoras futuras

- **Fechas regionales.** Hoy no sabemos la ciudad del negocio en el perfil de inversión, así que
  quedaron fuera: el Día de la Madre de Norte de Santander (último domingo de mayo; Cúcuta
  2027-05-30) y el Carnaval de Barranquilla (6–9 feb. 2027, región Caribe).
- Medir los niveles y el mapeo de rubros con los resultados reales de las promociones.
