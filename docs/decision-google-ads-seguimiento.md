# Decisión — ¿Qualify sigue las campañas de Google Ads de los clientes?

`[PROPUESTO 2026-11-04 · Meegle m-24945024 · sin implementar · decide el fundador]`

> **Decisión del fundador (AAAA-MM-DD):** pendiente. Cuando Herwin elija, esta sección se
> llena con la opción elegida y manda sobre el análisis de abajo.

Pregunta del fundador (2026-11-04): «¿Qualify puede hacer seguimiento de las campañas de Google
Ads de los clientes?». Respuesta corta: **sí se puede** (la API es gratuita y la lectura de
métricas es lo más sencillo que ofrece), pero **hoy no hay evidencia de que algún cliente gaste en
Google Ads**, y Qualify todavía no muestra ni las métricas de los anuncios de Meta. Este documento
prepara la decisión con el procedimiento de `qualify-business-decisions`.

## 1. El marco

- **Qué buscamos esta vez: aprender.** Saber si hay demanda real (clientes que ya pagan anuncios
  en Google) antes de gastar una o dos semanas de desarrollo. No buscamos margen ni caja con esto.
- **Para el dueño del negocio:** ver en un solo lugar cuánto le costó cada cliente que le llegó,
  venga de Instagram o de Google, sin entrar a dos paneles. Si no anuncia en Google, no gana nada.
- **Alcance posible**, de menor a mayor:
  - **(1) Lectura diaria de métricas** por campaña (impresiones, clics, costo, conversiones, costo
    por conversión) guardadas en Postgres con `tenant_id` + RLS, en Resultados junto a Meta.
  - **(2) Atribución:** `gclid`/UTM en los enlaces cruzados con conversaciones de WhatsApp y
    leads (qué campaña trajo qué cliente).
  - **(3) Crear/editar campañas desde Qualify.** Proyecto aparte y mucho más grande: aprobación
    humana, límites de gasto, revisión «Standard» de Google. **Fuera de esta decisión**; se
    nombra solo para dejarlo explícitamente aparcado.
- **Decisiones firmadas que aplican:** una sola Postgres (ADR 31); «compra lo genérico,
  construye el núcleo»; asistido, nunca autónomo (relevante solo para el alcance 3); un proveedor nuevo
  necesita esta tabla y la elección del fundador.

## 2. Lo que ya existe (leído del disco, 2026-11-04)

- `[V]` Solo hay integración con **Meta Ads** (`packages/api/src/qualify_api/ads/`: `client.py`
  Marketing API, `promotions.py`, `wizard.py`…). No hay ningún código de Google Ads.
- `[V]` `MetaAdsClient.insights(...)` existe en `ads/client.py` pero **nadie lo llama**: Qualify
  aún no muestra métricas de anuncios de Meta.
- `[V]` La pantalla **Resultados** (`Qualify/results_vm.py`, m-24843003) tiene cuatro pestañas:
  Redes, WhatsApp, «Tu página web» (Clarity) y «Quién habla de ti». Ninguna de anuncios.
- `[V]` Los leads ya guardan `utm_source/medium/campaign/content/term`
  (`qualify_api/leads/models.py`); **no** guardan `gclid`.
- `[V]` Meegle: no hay ticket abierto sobre Google Ads (búsqueda MQL «Google», 2026-11-04;
  solo aparecen Google Business Profile m-24789565 y una página en Google Sites, ya cerrada).

## 3. Lo que sabemos

**Google Ads API** (consultado 2026-11-04):

- `[V]` **Los «developer tokens» ya no son la puerta.** Google los retiró el 2026-09-09; el nivel
  de acceso ahora es del **proyecto de Google Cloud**. Al activar la API el proyecto recibe
  «Test» (solo cuentas de prueba). — [Access levels](https://developers.google.com/google-ads/api/docs/api-policy/access-levels)
- `[V]` **Explorer:** se pide desde la consola de Cloud, revisión automática «en la mayoría de los
  casos», hasta **2.880 operaciones/día** contra cuentas reales. Sin creación de cuentas, gestión
  de usuarios, planificador de palabras clave ni facturación. — misma fuente.
- `[V]` **Basic:** 15.000 operaciones/día; requisito previo: **verificación de marca del proyecto
  de Cloud**. **Standard:** ilimitado, auditoría manual de ~10 días hábiles, solo hace falta para
  herramientas grandes o para crear anuncios a escala (alcance 3). — misma fuente.
- `[S]` Hay un error reconocido: proyectos subidos a Explorer/Basic después del cambio reciben a
  veces `AUTHORIZATION_ERROR` en cuentas reales. — [relevantaudience.com](https://www.relevantaudience.com/google-ads-en/google-ads-api-developer-tokens-sunset-cloud-project-access/), [ppc.land](https://ppc.land/google-faces-developer-token-application-backlog-as-new-api-tier-debuts/)
- `[V]` **Acceso a cuentas:** OAuth 2.0 con el alcance `https://www.googleapis.com/auth/adwords`;
  si se entra por una cuenta administradora (MCC), cada llamada lleva la cabecera
  `login-customer-id` con el id de esa MCC. — [Auth](https://developers.google.com/google-ads/api/rest/auth)
- `[S]` El alcance `adwords` es **sensible**: una app sin verificar muestra la pantalla de «app no
  verificada» y tiene tope de **100 usuarios**; la verificación pide video de demostración y
  puede tardar semanas. — [Cloud project (Google)](https://developers.google.com/google-ads/api/docs/oauth/cloud-project), [Nango](https://nango.dev/docs/api-integrations/google-ads/how-to-register-your-own-google-ads-api-oauth-app)
- `[S]` **Costo de la API: US$0 por llamada.** La página oficial de niveles no menciona precio; es
  el conocimiento común del sector. Sin evidencia `[V]` de lo contrario.
- `[H]` Con la **MCC de Attitude Factory**, cada cliente acepta una solicitud de vinculación desde su
  Google Ads y Qualify lee con **un solo OAuth interno** (el de la MCC). Eso evita que cada dueño
  pase por la pantalla de «app no verificada» y deja la verificación del alcance sensible para
  más adelante. Hay que confirmarlo con una prueba real (§6).
- `[H]` Lectura diaria de pocas decenas de campañas por negocio: muy por debajo de 2.880
  operaciones/día (una consulta GAQL por cuenta y día). Explorer alcanza para los primeros
  ~100 negocios.

**Conector de terceros (Supermetrics y similares):**

- `[S]` Precios inconsistentes entre fuentes: desde US$29/mes (un conector) hasta US$159–222/mes
  (planes Core/Growth), con recargos por destino. — [Capterra](https://www.capterra.com/p/162846/Supermetrics/pricing/), [Swydo](https://www.swydo.com/?p=23930), [Mammoth](https://mammoth.io/blog/supermetrics-pricing/)
- `[S]` Su destino natural es Google Sheets / Looker Studio / un almacén, no nuestra Postgres: para
  verlo en Resultados igual hay que construir la carga.

**Demanda:**

- `[H]` Todos los clientes actuales (Bianki, Polette, Korner, San Cristóbal, PuntoServis, la
  inmobiliaria, la agencia de viajes) trabajan con Meta. **Ninguno ha pedido Google Ads**
  (equipo, 2026-11-04; sin confirmar uno por uno).
- `[H]` Los negocios de comida de barrio en CO/VE/UY anuncian poco en buscadores; la inmobiliaria y
  la agencia de viajes son las candidatas más probables (búsquedas con intención: «apartamento en
  Cúcuta», «viaje a…»). Es analogía, no dato.

## 4. Lo que no sabemos

| Hueco | Experimento más barato | Quién | Cuándo |
|---|---|---|---|
| ¿Algún cliente gasta hoy en Google Ads? ¿Cuánto al mes? | Preguntar a los 7 negocios activos (mensaje directo, una pregunta) | Fundador / Darwin | Esta semana |
| ¿El dueño quiere verlo en Qualify o le basta el panel de Google? | Mismo mensaje: «¿Te serviría ver en Qualify cuánto te costó cada cliente que llegó desde Google?» | Fundador | Esta semana |
| ¿La vinculación por MCC funciona sin OAuth del cliente? | Crear la MCC de Attitude Factory, vincular una cuenta propia, pedir Explorer y hacer una consulta GAQL de lectura | `principal-architect` + `backend-engineer`, solo si se elige C | Antes de escribir historias |
| ¿Cuánto vale el costo por cliente que llega (alcance 2) frente a solo métricas (alcance 1)? | Ver si los leads con `utm_*` ya traen tráfico de Google en la inmobiliaria / agencia | `data-scientist-fde` | Si hay al menos un cliente con gasto |

## 5. Opciones

| Opción | Qué es | Para el dueño | Costo / margen por negocio | Esfuerzo | ¿Se puede deshacer? | Riesgo principal | Evidencia |
|---|---|---|---|---|---|---|---|
| **A. Dejar como está** | No hay Google Ads en Qualify; se pregunta a los clientes si lo usan | Nada cambia; quien anuncie en Google sigue usando su panel | US$0 | Ninguno (una ronda de mensajes) | Sí (dos vías) | Perder a un cliente que lo pida y no lo tengamos | `[H]` ningún cliente lo ha pedido |
| **B. Exportación manual** | El dueño (o el equipo, en servicio gestionado) sube un CSV o programa el informe de Google Ads por correo; Qualify lo carga a una tabla con RLS | Ve sus cifras de Google en Resultados, con un día o una semana de atraso | US$0 en proveedores; tiempo del equipo por negocio si lo hacemos nosotros | S–M: carga de CSV + migración + pestaña | Sí (dos vías) | Nadie sube el archivo; formato del CSV cambia | `[H]` |
| **C. API de Google Ads directa, solo lectura** (alcance 1, y luego 2) | Proyecto de Cloud con acceso Explorer, MCC de Attitude Factory vinculada a la cuenta del cliente, worker diario con GAQL, tabla `google_ads_daily_metrics` con RLS, pestaña en Resultados | Ve impresiones, clics, costo y costo por conversión de cada campaña, al día, sin hacer nada más que aceptar la vinculación | US$0 de API `[S]`; costo es solo desarrollo y mantenimiento (cambios de versión de la API, ~cada año) | M–L: 1–2 semanas de un desarrollador `[H]`, más trámites (Explorer automático, verificación de marca si se pasa a Basic) | Mayormente sí: se desvincula la MCC y se apaga el worker; los datos quedan en nuestra Postgres | Construir algo que ningún cliente usa; errores de autorización del cambio de Google | `[V]` niveles y OAuth · `[H]` demanda |
| **D. Conector de terceros (Supermetrics u otro)** | Pagar el conector y llevar sus datos a nuestra base | Lo mismo que C | US$29–222/mes `[S]` fijos, más la carga que igual hay que construir | M: conector + carga + pestaña | A medias: los datos del cliente pasan por un tercero que los guarda | Proveedor nuevo pagando por algo que la API da gratis; datos de clientes en otro proveedor | `[S]` precios inconsistentes |

**Puertas.** A, B y C son de dos vías (archivo o vinculación que se quita, tabla propia). D es
casi de una vía para los datos: la información publicitaria de los clientes queda en un tercero.
C se vuelve de una vía solo si se anuncia como función del plan a clientes que pagan; un piloto
con un solo negocio la mantiene de dos vías.

**Si sale mal (C, por si se elige):**

1. *Nadie lo usa.* Señal temprana: ningún negocio acepta la vinculación en 30 días. Qué hacemos:
   apagamos el worker y dejamos la pestaña oculta.
2. *Google nos bloquea con `AUTHORIZATION_ERROR` o pide Basic.* Señal: la prueba de la MCC falla.
   Qué hacemos: verificación de marca del proyecto de Cloud y volver a pedir; mientras, opción B.
3. *El dueño confunde «conversiones» de Google con clientes reales.* Señal: preguntas al equipo.
   Qué hacemos: mostrar «clientes que escribieron» (alcance 2, atribución) y no solo la cifra de Google.

**Sesgos a vigilar:** la pregunta llegó porque Google Ads es conocido, no porque un cliente lo
pidiera (disponibilidad); y la API es gratis, lo que hace parecer barata una función que cuesta
semanas de desarrollo y mantenimiento.

## 6. Recomendación

**A ahora, con la pregunta a los clientes esta semana; C (solo lectura, por MCC, en piloto con un
negocio) en cuanto al menos un cliente activo confirme que gasta en Google Ads.** — buscamos
aprender, y hoy la evidencia de demanda es cero: preguntar cuesta un mensaje, construir cuesta
una o dos semanas.

- **Antes que Google, Meta:** Qualify ya tiene el cliente de la Marketing API con `insights()`
  sin usar. Mostrar el rendimiento de los anuncios de Meta en Resultados sirve a los clientes de
  hoy y deja hecha la pestaña y la tabla a la que luego se sumaría Google.
- **No elegir D:** pagar todos los meses por datos que la API entrega gratis, y sumar un proveedor
  con datos de clientes, no se justifica con un solo cliente.
- **B como respaldo**, solo si un cliente lo necesita antes de que C esté listo.
- **Costo de equivocarnos con A:** bajo; un cliente que lo pida espera 1–2 semanas.
- **La reabrimos si** al menos **1 cliente activo** confirma gasto en Google Ads (o **2 negocios
  nuevos** lo piden en la venta) **antes del 2026-12-04**. Si nadie lo confirma para esa fecha,
  se archiva como «parking-lot».
- **Validación más barata:** el mensaje a los 7 negocios; si alguno dice que sí, la prueba de la
  MCC con una cuenta propia antes de escribir historias.

**Necesito que decidas:** ¿A (preguntar y esperar), B (archivo manual), C (API de solo lectura en
piloto) o D (conector de terceros)?

## 7. Si se elige C: historias que saldrían (borrador, no archivadas)

Se archivan solo después de la elección y de que `principal-architect` revise la viabilidad
(proyecto de Cloud, MCC, migración con RLS) y `data-scientist-fde` la medición de costo por
cliente:

1. Plataforma: proyecto de Google Cloud, MCC de Attitude Factory, acceso Explorer, secretos
   (dónde viven, nunca su valor). — platform.
2. Backend: cliente de solo lectura (GAQL `campaign` + `metrics` por día), worker diario
   idempotente, tabla `google_ads_daily_metrics` con `tenant_id`, RLS y procedencia (id de
   cuenta, versión de la API). — backend.
3. Backend: guardar `gclid` junto a los `utm_*` de los leads (alcance 2). — backend.
4. UI: pestaña de anuncios en Resultados, Meta y Google juntos, en palabras del dueño
   («Lo que invertiste», «Personas que vieron tu anuncio», «Cuánto te costó cada cliente»). — ui.

Fuera de alcance en cualquier caso: crear o editar campañas de Google (alcance 3 del §1).
