# WhatsApp Estados: ¿puede el dueño publicarlos desde Qualify? Opciones

**Fecha:** 2026-11-12 · **Modo:** OFERTA (evidencia, no requisito) · **Estado:** decisión pendiente del fundador; nada se construye desde este documento.
**Etiquetas:** `[V]` verificado en fuente primaria (URL + fecha de acceso 2026-11-12) · `[S]` fuente secundaria · `[H]` hipótesis.

## 1. La pregunta

El dueño de un negocio quiere «publicar un estado» (la historia de 24 horas de WhatsApp) sin salir de Qualify. Hoy Qualify ya conecta el número del cliente a la API oficial de WhatsApp (Cloud API) para los chats, y publica en Instagram.

## 2. Veredicto sobre el camino oficial

**No existe un endpoint oficial para publicar un Estado.** `[V]` El registro de cambios de la Cloud API no menciona publicación de Estados ni de Canales; su única mención de «Status» es sobre anuncios (20-oct-2025) [1]. La tabla de coexistencia de Meta lista «estado» entre las herramientas de negocio **no soportadas en la API** [2]. Es ausencia de evidencia, no prueba negativa: el resumen del changelog de 2026 que obtuve tenía una sola entrada (12-may-2026) y conviene releerlo en el navegador.

Anuncios en Estados y Canales promovidos existen desde 2025 `[S]` [8], pero **no son sustituto**: son publicidad pagada en el Administrador de Anuncios, no «mi historia de hoy»; y no encontré documentación de que se compren por API (**no verificado**). El hilo ya abierto en ADS-17 (`docs/epica-anuncios-meta.md`) sigue siendo el sitio para ese veredicto; este documento cierra la parte (A) orgánica: **sin vía oficial**. Es coherente con `docs/anuncios-publico-ubicaciones.md`, que deja los Estados fuera de alcance.

## 3. Dato que cambia la conversación: el número de Bianki

Un número que se registra en la Cloud API **borrando** la cuenta de la app pierde la app Business para siempre (salvo que se dé de baja de la API) [3] `[V]`. La app es el único sitio donde hoy se puede publicar Estados. El backlog dice que el número de Bianki está en la Cloud API desde 2026-10-16 y que la coexistencia «queda sin objeto» (`docs/backlog-modulo-whatsapp.md`). **`[H]` si no se conectó por coexistencia, ese dueño hoy no puede publicar Estados desde ningún sitio con ese número.** Hay que preguntarle al fundador cómo se conectó cada número.

## 4. Opciones

Costos en USD por número al mes; todos facturan en USD (barrera para negocios pequeños de VE/CO). Esfuerzo: S ≤ 3 días, M ≈ 1–2 semanas, L > 2 semanas (estimación `[H]`).

| # | Opción | Qué obtiene el dueño | Costo mensual por número | Riesgo para el número | Esfuerzo | Reversible | Evidencia |
|---|---|---|---|---|---|---|---|
| A | **No hacerlo** | Sigue publicando a mano en la app, si la tiene | 0 | Ninguno | 0 | Sí | §2 |
| B | **Coexistencia** (app + API a la vez) y el dueño publica a mano | Chats en Qualify y Estados desde el teléfono; Qualify no publica nada | 0 de Qualify; mensajes enviados desde la app son gratis, los de la API se cobran `[S]` | Bajo (camino oficial). Pierde mensajes temporales, «ver una vez», listas de difusión; límite fijo de 20 mensajes/s [2] | M (hay que pasar por Embedded Signup; para el número ya conectado, volver a registrarlo es `[H]`) | Parcial: dar de baja el número de la API es posible, el efecto sobre el historial no está verificado | Funciones [2] `[V]`; que el Estado siga funcionando en la app: solo `[S]` (proveedores) [6]. Países: Meta amplió a más regiones en oct-2025 [1]; **CO/VE/UY no confirmados** (Venezuela por sanciones, `[H]`) |
| C | **Asistido sin proveedor**: Qualify prepara imagen/video + texto; el dueño lo comparte desde el celular | Pieza lista en 2 toques; la publica él | 0 | Ninguno | S–M | Sí | Ver §5 |
| D | **Pasarela no oficial** (sesión «dispositivo vinculado» tipo WhatsApp Web) | Qualify publica el Estado por API tras aprobación del dueño | Whapi.Cloud US$29 (plan Premium, anuncio de precio) `[V]` [4]; Wassenger desde US$39,90, el Estado exige plan «Platform» sin precio visible `[V]` [5]; Wawp sin precio verificado | **Alto y no cuantificable**: viola los términos de WhatsApp (ver §6); mala convivencia con el número en Cloud API (no documentada) | M | Parcial: el número puede quedar restringido sin vuelta atrás | Funciones `[V]` [4][5][7]; baneos: solo `[S]` de proveedores rivales |
| E | **Canales / Anuncios en Estados** | Alcance pagado, no «estado del día» | Gasto en anuncios | Ninguno | L, sin API documentada | n/a | `[S]` [8] |

## 5. Opción C: qué es posible desde una página móvil hoy

- No encontré ningún enlace `whatsapp://` que abra el editor de Estados; los enlaces documentados abren un chat con texto. `[S]`
- La **Web Share API con archivos** (`navigator.share({files})`) abre la hoja de compartir del teléfono; la página no elige destino. En Android, WhatsApp ofreció «Mi estado» en esa hoja, pero la nota es de una beta `[S]` [9]. En iPhone no está confirmado.
- Siempre hay una salida segura: descargar el archivo y el dueño lo sube a mano. **Todo `[H]` hasta probarlo en un Android y un iPhone reales** (prueba de 1 hora).
- Efecto colateral bueno: respeta la regla «asistido, nunca autónomo»; el dueño siempre toca el último botón.

## 6. Pasarelas no oficiales (opción D): lo que se sabe

- **Cómo funcionan:** emparejan por código QR como WhatsApp Web (Whapi `[V]` [4]); Wawp se define como «Web Automation» y no como API oficial `[V]` [7]. Wassenger ofrece QR **y** API oficial, pero no aclara si el Estado funciona con un número de Cloud API [5]. Ninguna documenta convivir con un número ya en Cloud API: `[H]` que no es posible.
- **Funciones:** texto, imagen, video (≤30 s en Wawp), audio; solo lo ven contactos que tienen guardado el número del negocio [7][4]; no hay borrado en algunas (Whapi lo documenta de forma contradictoria).
- **Términos:** Whapi se declara «no avalado ni asociado» con WhatsApp/Meta [4]. Texto de WhatsApp: usar una aplicación no autorizada puede causar bloqueo `[S]`; no pude leer la cláusula primaria (la página de términos solo enlaza). **Casos de baneo documentados con fuente verificable: ninguno encontrado**; lo que circula son blogs de vendedores de la API oficial (sesgados).
- **Datos:** la sesión de WhatsApp del cliente (equivalente a su chat completo) quedaría en un tercero. Choca con el aislamiento por inquilino y exige decisión del fundador sobre proveedor nuevo.

## 7. Recomendación

**Opción C (asistido) como experimento barato, y no construir D.** Razón: lo que el dueño valora es no armar la pieza ni el texto; el último toque a mano es mínimo y no arriesga el número real, que es el activo del cliente (en Bianki, el canal de pedidos). Solo se vuelve a considerar B si el dueño necesita la app y la API a la vez; eso se decide con la pregunta de §3.

**Criterio para matarla:** si en la prueba con 3 dueños reales, menos de 2 de 3 publican el Estado tras recibir la pieza, o si en el 50 % de los teléfonos probados la hoja de compartir no ofrece «Mi estado» y la descarga manual les resulta peor que hacerlo en la app, se archiva (queda A). **Criterio para reabrir D:** que Meta publique un endpoint oficial (releer el changelog cada trimestre) o que un cliente pague explícitamente por publicación automática asumiendo el riesgo por escrito.

## 8. Lo que no pude verificar

1. Si CO, VE y UY están en la lista de coexistencia (el texto de Meta no la da; solo `[S]` «ya global»).
2. Que el Estado siga funcionando en la app con coexistencia (solo proveedores).
3. Si el número de Bianki se conectó por coexistencia o borrando la app (§3).
4. Cláusula primaria de los términos de WhatsApp sobre acceso no autorizado.
5. Precio de Wawp y del plan «Platform» de Wassenger; si Whapi/Wassenger/Wawp funcionan sobre un número ya en Cloud API.
6. Si los anuncios en Estados se compran por Marketing API (ADS-17).
7. «Mi estado» en la hoja de compartir, en Android e iPhone reales.

## 9. Fuentes (acceso 2026-11-12)

1. Meta, registro de cambios Cloud API: https://developers.facebook.com/docs/whatsapp/cloud-api/changelog
2. Meta, coexistencia: https://developers.facebook.com/docs/whatsapp/embedded-signup/custom-flows/onboarding-business-app-users
3. Meta, migrar un número existente: https://developers.facebook.com/docs/whatsapp/cloud-api/get-started/migrate-existing-whatsapp-number-to-a-business-account/
4. Whapi.Cloud: https://whapi.cloud/whatsapp-status-api · https://support.whapi.cloud/help-desk/sending/overview-of-other-methods-for-sending/send-stories · https://whapi.cloud/terms
5. Wassenger: https://wassenger.com/pricing · https://wassenger.com/blog/update-whatsapp-status-story-using-the-api
6. Proveedores sobre coexistencia: https://zernio.com/blog/whatsapp-coexistence · https://docs.jelou.ai/en/connect/prerequisites/coexistence.md
7. Wawp: https://api.wawp.net/en/docs/v2/status-overview
8. Anuncios en Estados/Canales: https://techcrunch.com/2025/06/16/whatsapp-is-adding-ads-to-the-status-screen · https://www.ycloud.com/blog/whatsapp-status-ads
9. Compartir a «Mi estado» (beta): https://wabetainfo.com/whatsapp-beta-for-android-2-25-20-3-whats-new/ · Web Share API: https://www.w3.org/TR/2022/CRD-web-share-20221212/
