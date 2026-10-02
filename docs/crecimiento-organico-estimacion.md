# Crecimiento orgánico: cómo se estima desde fuera

**Estado:** implementado 2026-10-01 — `packages/api/src/qualify_api/growth/organic.py` (`estimate_organic_growth`), sobre el historial de lecturas de la migración `0034` (`creator_reads`, `creator_post_reads`). Sin pantalla todavía: el historial empieza a acumularse desde hoy y la estimación necesita días de lecturas (§5).

**Definición que usamos (del fundador, 2026-10-01):** crecimiento orgánico = crecimiento **sin base de ads** — sin pauta, sin posts promocionados, sin seguidores comprados.

## 0. Lo que se puede y lo que no

Ningún proveedor externo sabe de dónde vienen los seguidores de una cuenta ajena (`scrapecreators-crecimiento-organico-y-contenido-ia.md` §2): Scrape Creators da la foto de hoy, no la serie, y un post promocionado por su propio autor ("Promocionar"/"Boost") **no lleva ninguna etiqueta pública**. Solo las Insights de una cuenta conectada (Parte 4) dicen "seguidores desde anuncios".

Lo que sí es observable desde fuera, y en lo que se apoya todo:

> **Los seguidores orgánicos vienen de interacciones orgánicas.** Si una cuenta gana seguidores que su propio contenido no explica, esos seguidores son el candidato a "no orgánico" (ads, boosts, compra). Y un post empujado con pauta deja huella: mucho alcance con poca interacción por view, o views que llegan tarde.

Así que la estimación responde a dos preguntas por separado: (1) **qué parte del crecimiento explica el contenido** y (2) **qué posts parecen empujados con pauta**. No es un dato; es un indicador con confianza.

## 1. Datos de entrada

Todo sale del historial de lecturas (una fila por lectura, nunca se sobrescribe):

| Serie | De dónde | Cadencia recomendada |
|---|---|---|
| `F(t)` seguidores de la cuenta | `creator_reads.followers` | 1 lectura/día (1 crédito; `cache_max_age` corto) |
| Por post `p`: views `V_p(t)`, likes, comentarios, shares | `creator_post_reads` | 2 lecturas/día las primeras 72 h tras publicar, luego 1/día una semana (1 crédito por página de ~10 vídeos) |
| Etiqueta de pago del post (`is_paid_partnership`, `is_ad`) | aún no leída (§6) | con la misma lectura |

Notación: la ventana es `[t0, t1]` (por defecto, toda la serie disponible; en producto, 28 días). `I_p(t) = likes + comentarios + shares` del post `p` en `t`.

## 2. La fórmula

### 2.1 Crecimiento total

```
ΔF = F(t1) − F(t0)            seguidores netos ganados en la ventana
ΔF⁺ = max(ΔF, 0)              (si la cuenta perdió seguidores no hay nada que repartir)
```

### 2.2 Posts "empujados" (sospecha de pauta)

Para cada post con lectura dentro de la ventana:

```
ER_p  = I_p / V_p                                   interacción por view (última lectura)
LW_p  = (V_p(t1) − V_p(t_p + 72h)) / V_p(t1)        parte de las views llegadas después de las primeras 72 h
```

Medianas de la propia cuenta (con ≥ 3 posts; si no, la referencia del sector, §4): `ER_med`, `V_med`, `LW_med`.

Un post es **empujado** si cumple cualquiera de:

| Señal | Condición | Por qué |
|---|---|---|
| Etiqueta de pago | `is_paid_partnership` o `is_ad` | contenido de marca: alcance comprado por alguien |
| Alcance alto con interacción baja | `V_p > 3 · V_med` **y** `ER_p < 0.4 · ER_med` | la pauta entrega views, no likes |
| Views tardías | `LW_p > 0.5` y la cuenta normalmente tiene `LW_med < 0.2` | un boost se lanza después de publicar, cuando la curva orgánica ya decayó |

Los umbrales (`3`, `0.4`, `0.5`, `0.2`) son constantes del módulo (`REACH_OUTLIER`, `ENGAGEMENT_DEFICIT`, `LATE_WAVE_SHARE`, `LATE_WAVE_USUAL`), elegidos a priori; se calibran cuando haya cuentas conectadas con Insights reales (§6).

### 2.3 Interacciones orgánicas

```
I_org  = Σ_{p no empujado} ( I_p(t1) − I_p(t0) )     interacciones ganadas en la ventana por posts limpios
I_push = Σ_{p empujado}    ( I_p(t1) − I_p(t0) )
```

### 2.4 Seguidores por interacción, `k`

Lo que vale una interacción en seguidores, **medido en la propia cuenta**: entre cada par de lecturas consecutivas de seguidores `(a, b)` en las que ningún post empujado ganó nada ("intervalo limpio"):

```
k = mediana( (F(b) − F(a)) / I_org(a, b) )     sobre intervalos limpios con I_org > 0 y F(b) ≥ F(a)
```

acotado a `[0.002, 0.3]`. Con menos de 3 intervalos limpios no se mide: se usa la **referencia** (`k = 0.03`, o la de los referentes del sector) y la estimación lo dice (`k_from = "referencia"`).

### 2.5 Reparto del crecimiento

```
G_org   = min( ΔF⁺ , k · I_org )       crecimiento que el contenido explica
G_unexp = ΔF⁺ − G_org                   crecimiento que nada orgánico explica  ← ads / boosts / compra
S_org   = G_org / ΔF⁺                   cuota orgánica (0..1)      [indefinida si ΔF⁺ = 0]
OGR     = G_org / F(t0)                 tasa de crecimiento orgánico en la ventana
R_push  = Σ V_p(empujados) / Σ V_p(todos)   cuota de alcance con señales de pauta
```

### 2.6 Confianza

```
confianza = min(1, días_de_serie / 14) · min(1, posts_con_≥2_lecturas / 5)
```

Por debajo de 0.5 la estimación se marca "preliminar". Con una sola lectura de seguidores no hay estimación.

## 3. Ejemplo con números

Cuenta con `F(t0) = 10 000`, 28 días después `F(t1) = 11 200` → `ΔF = 1 200`.

- 12 posts en la ventana, `60 000` interacciones ganadas en total.
- Medianas de la cuenta: `V_med = 40 000`, `ER_med = 3,5 %`.
- Dos posts tienen `V = 250 000` (6 × la mediana) con `ER = 0,8 %` (< 0,4 × 3,5 %) → **empujados**; entre los dos suman `25 000` interacciones → `I_org = 35 000`, `I_push = 25 000`.
- En los intervalos limpios la cuenta ganó de mediana `0,02` seguidores por interacción → `k = 0,02`.

```
G_org   = min(1 200, 0,02 · 35 000) = min(1 200, 700) = 700
G_unexp = 1 200 − 700 = 500
S_org   = 700 / 1 200 = 58 %
OGR     = 700 / 10 000 = 7 % en 28 días
R_push  = 500 000 / (500 000 + 10 · 40 000) ≈ 56 % del alcance con señales de pauta
```

Lectura para el operador: *"Creciste 1 200 seguidores; unos 700 (58 %) los explica tu contenido. 2 publicaciones tienen señales de alcance pagado y concentran la mitad de tus views."*

Los mismos casos están en `packages/api/tests/test_growth.py`: una cuenta orgánica sale con `S_org > 90 %`; una que compró 3 000 seguidores sin publicar queda con `G_unexp ≈ 3 000` y `S_org < 50 %`; un post con 10 × alcance y un quinto de interacción queda marcado y fuera de `I_org`.

## 4. Arranque en frío: la referencia

Una cuenta recién leída no tiene serie. Hasta tener 3 intervalos limpios, `k` y `ER_med` salen de una `Reference`:

- por defecto `k = 0,03`, `ER = 3 %`;
- mejor: la mediana de los **referentes del sector** que la búsqueda del Brand Kit ya encuentra — sus lecturas se guardan en el mismo historial (`source = 'discovery'`), así que la referencia sectorial se calcula de los mismos datos.

La estimación siempre dice de dónde salió `k` (`k_from`), y la UI debe mostrarlo.

## 5. Qué hace falta para que funcione (y qué ya está)

| Pieza | Estado |
|---|---|
| Historial de lecturas (`creator_reads`, `creator_post_reads`, RLS) | ✅ migración 0034 |
| Grabar la lectura de la propia cuenta en Analizar | ✅ `BrandConnectState._record_read` |
| Grabar los referentes de cada fase de la búsqueda | ✅ `_store_phase` → `growth_provider.record_discovered` |
| `postId`, `shares`, etiqueta de IA en la forma común de post | ✅ `scrapecreators_client._post` |
| La fórmula | ✅ `qualify_api.growth.organic.estimate_organic_growth` |
| **Lecturas periódicas** (sin ellas solo hay un punto por análisis) | ❌ necesita el scheduler (Celery Beat, Parte 3) o un cron sencillo: 1 crédito/día por cuenta + 1 por página de vídeos; ~90 K créditos/mes por 1 000 creadores ≈ $90 (Business) |
| Etiquetas de pago del post (`is_paid_partnership`, `is_ad`) en la forma común | ❌ un campo más en `_normalize_*` |
| Pantalla en Resultados e insights | ❌ cuando haya ≥ 14 días de serie |
| Calibración de umbrales con Insights reales | ❌ Parte 4 (cuentas conectadas) |

## 6. Límites (decir siempre)

- **Pauta con buena interacción no se detecta**: un anuncio bien hecho con ER normal pasa por orgánico. La estimación es un **suelo** del no-orgánico, no un techo.
- **Tráfico externo cuenta como no explicado**: una mención en TV o en YouTube trae seguidores sin interacciones en la plataforma; salen en `G_unexp` aunque sean legítimos.
- **`k` es una mediana**: dos posts virales raros con conversión altísima no la mueven; es lo deseado (robustez), pero infraestima `G_org` en cuentas que viven de picos.
- **Es por cuenta, no por vídeo**: para "este vídeo creció orgánicamente" la señal es solo la de §2.2 (empujado o no), no un reparto de seguidores por vídeo — ningún dato externo atribuye seguidores a un vídeo.

## 7. Dónde vive

- `packages/api/src/qualify_api/growth/organic.py` — la fórmula, pura (sin base de datos).
- `packages/api/src/qualify_api/growth/repository.py` — el historial (`Memory*` para tests, `Postgres*` con `tenant_session`).
- `Qualify/growth_provider.py` — qué se graba desde el wizard.
- `packages/api/tests/test_growth.py` — los escenarios de §3 y el repositorio (`db`).
