# Medición de niveles de consciencia + ventajas del negocio (m-25026482)

Mide el cambio de la rama `feat/m-25026482-niveles-consciencia` (los cinco niveles de
Eugene Schwartz en «10 variaciones», en el copy y en el video por partes, alimentados por
`brand_kits.business_perks`) contra la línea base `a6667370` (main antes del cambio), con
los mismos casos.

```bash
just eval-niveles --suite identity                       # gratis: partes == las de main sin ventajas ni nivel
just eval-niveles --suite angles --split dev --cap-usd 0.80
just eval-niveles --suite angles,copy,parts --split test --cap-usd 2.00
```

En un worktree sin `.env`: `--env-file /ruta/al/.env` del checkout principal. Gasta dinero
real (Claude), nunca en CI; para antes de una llamada que pueda pasar `--cap-usd` y deja
la lista de lo omitido en el resultado. Sin claves `LANGFUSE_*` corre sin trazas y lo dice.

## Suites

| Suite | Casos | Base | Nuevo |
|---|---|---|---|
| `identity` | 6 briefs × (sin ángulo, con ángulo) | `parts_ai.py` en `a6667370` | `parts_ai.py` actual, sin ventajas ni nivel — debe salir idéntico byte a byte |
| `angles` | `cases.json` → `angle_cases`: 7 productos (comida 3, inmobiliaria 2, viajes 2), 4 dev / 3 test | el prompt de `a6667370` una vez por producto (no lee ventajas) | el prompt actual con las ventajas de la marca y sin ninguna |
| `copy` | `../copy_ai/cases_niveles.json`: 7 ángulos escritos a mano (los 5 niveles en comida, 2 en inmobiliaria) | `angle_brief` de `a6667370` (siempre venta, precio siempre) + kit sin ventajas | `angle_brief` actual (objetivo por nivel; unaware sin precio) + kit con ventajas |
| `parts` | los 5 ángulos de comida con la historia de `parts_cases` | brief y ángulo sin ventajas ni nivel | con ventajas y nivel |

Modelos: los de producción — ángulos `claude-sonnet-5` @ medium (`angles_ai`), copy
`claude-opus-5-5` @ medium (`AnthropicCopyAdapter`), partes `claude-sonnet-5` @ medium
(`parts_ai`). Juez: `claude-haiku-5-5` @ low. Precios: tabla versionada `v9`.

Los datos son los casos ya anonimizados del repo (nada sale de la base de datos). La
agencia de viajes es la de `reels_ai` (Cusco, Perú): es la única marca de viajes en los
casos; sus ventajas se escribieron para esta medición a partir de su biografía.

## Reglas escritas ANTES de juzgar

**Chequeos deterministas** (`qualify_api.evals.awareness_levels`), sobre las palabras que
lee el cliente (gancho y CTA de un ángulo; gancho, texto, CTA y guion de un copy; las
descripciones de un video):

- *Reparto*: un juego de 10 debe traer 2 por nivel; se cuentan las etiquetas faltantes o
  inválidas tal como las respondió el modelo.
- *Regla del nivel*: unaware — ni precio, ni moneda, ni oferta; product_aware — al menos un
  dato de fricción (horario, precio, pago, dirección, domicilio) que sí esté en los datos;
  most_aware — gancho ≤ 8 palabras y CTA ≤ 5. problem_aware y solution_aware solo los lee
  el juez.
- *Dato inventado*: un horario, precio, forma de pago, dirección, domicilio o descuento
  que no está en las ventajas, en el producto ni en la marca (números comparados como
  números, palabras por su raíz).
- *Usa una ventaja*: al menos 60 % de las raíces de una ventaja aparecen en la idea.

**Juez** (`JUDGE_RUBRIC`, versión `juez-niveles-v2`; la v1 contaba atributos del producto como datos inventados — se corrigió con el piloto de dev, antes de tocar test): una lectura **ciega** (no ve el nivel
declarado: infiere el nivel, nota de calidad 1–5, datos inventados, ventajas usadas) y una
**informada** solo para ideas con nivel (¿cumple la regla de SU nivel?). La base no tiene
niveles: su reparto es el que infiere el juez.

**Barra por nivel (en test):** «fiable» si el juez dice que cumple su regla en ≥ 80 % de
las ideas y la tasa de datos inventados (la mayor de determinista y juez) es ≤ 5 %. Un
nivel bajo la barra se reporta «no fiable», no se esconde en un promedio. Calidad: el
cambio no empeora si la nota media del juez baja menos de 0,25 frente a la base.

## Resultados

En `results/` y en `docs/modelos-generativos/pruebas.md` (corrida del 2026-11-13).

## NIVELES-002 (2026-11-13) — cambios escritos ANTES de juzgar la segunda pasada

- **Ofertas y servicios inventados** (`invented_offers`, determinista, nuevo): en el título,
  el gancho y el CTA de un ángulo, en todo el texto de un copy y en las partes de un video,
  cuenta «gratis / gratuito / de regalo / regalo / incluido / incluye / descuento /
  promoción / 2x1 / oferta / cortesía / va por la casa / sin costo / obsequio» (oferta) y
  «reserva / apartar / separar / domicilio / delivery / envío / recoger / para llevar /
  cita / visita guiada» (servicio) que no estén en las ventajas, el producto ni la marca
  (por raíz de palabra). Ajustado solo en dev: «regala» como verbo no cuenta («la selva
  regala vistas»); «gratis», «gratuito», «sin costo» y «cortesía» dicen lo mismo y una
  respalda a las otras. «incluye/incluido» también marca descripciones ciertas de un combo:
  se reporta aparte.
- **Juez de partes** (`JUDGE_PARTS_ADDENDUM`, versión `juez-niveles-v2+partes-v1`): solo
  para planes de video. Las partes no muestran cifras por diseño, así que product_aware
  cumple si muestra lo fácil que es venir o pedir con lo que está en los datos (el lugar,
  el mostrador, cómo se atiende, una ventaja), sin cifras. El gancho y el CTA del ángulo
  pasan al juez como datos dados (en NIVELES-001 faltaban y dieron un falso positivo de
  domicilio). La rúbrica de ángulos y copy no cambia (`juez-niveles-v2`), así que esos
  números se comparan con NIVELES-001.

## Resultados guardados

`results/` se versiona, como en `copy_ai` y `mejorar_texto`: los casos son datos
anonimizados o ficticios del repo y las salidas solo hablan de ellos (revisado: sin claves,
rutas, correos ni teléfonos). `proponer_partes` los ignora porque sus casos son frases
reales de clientes; si esta carpeta recibe alguna vez casos reales, `results/` pasa al
`.gitignore`.

## NIVELES-003 (2026-11-13) — cambios escritos ANTES de la tercera pasada

- **Horario mal leído (corregido):** `de las? \d` contaba «de la 57» (la calle del local)
  como un horario. En NIVELES-002 eso dio el «2/6 nombra el horario» del copy unaware: dos
  copias de `results/20261113-154626-copy-n002-copy-all.json` (`niv-bur-unaware`) decían
  «… de la 57». Ahora una hora es «las 2…24» o «la 1».
- **solution_aware, dos chequeos deterministas nuevos** (además del juez, que no cambia):
  `concrete_fact`: el título, gancho o CTA usa al menos una palabra de la descripción del
  producto o de una ventaja que no sea el nombre ni la categoría del producto (no basta con
  repetir qué es). `generic_claims`: «fresco, de calidad, expertos, pensado para ti, el/la
  mejor, delicioso, único, increíble, perfecto, premium, especial, garantizado, confianza»,
  cuando los datos no lo dicen. La barra del nivel sigue siendo la del juez (≥ 0,80).
- La identidad del prompt de partes se compara con el `merge-base` con `origin/main` (las
  partes ya no parten de la v3.1 de `a6667370`).
