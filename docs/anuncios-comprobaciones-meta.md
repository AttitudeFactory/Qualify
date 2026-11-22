# Comprobaciones reales antes de crear y activar una promoción

Implementación: `ads/live_wizard.py`, `validation.py`, `wizard_workflow.py` y cliente de
Marketing API. El flujo público compone repositorios de Postgres, fuentes publicadas,
resolución de cuenta y credenciales reales; no hay un cambio por entorno que sustituya
las comprobaciones por datos de prueba.

## Secuencia

1. Comprobar que quien aprueba corresponde al acceso autenticado y sigue perteneciendo
   al negocio. Vincular publicación, marca, Página, Instagram, cuenta y versión de acceso.
2. Consultar permisos y activos realmente accesibles. Comprobar cuenta activa, asignación
   de Instagram, moneda, zona horaria, presencia de método de pago y ausencia de
   comprobaciones de entrega pendientes informadas por Meta. Esto significa «sin bloqueo
   conocido», nunca «cobro garantizado».
3. Leer la publicación y comprobar su propietario. Validar los cuerpos concretos de
   campaña, conjunto, creatividad y anuncio con `execution_options=['validate_only']`.
   La validación inicial usa `campaign_spec` y `adset_spec`; una combinación rechazada
   o respuesta desconocida impide crear objetos.
4. Registrar evidencia por usuario, fuente, versión, formulario, huellas de los cuatro
   cuerpos y presupuesto aprobado/enviado. Caduca en un máximo de cinco minutos.
5. Tras la aprobación inicial, crear los cuatro objetos en pausa con reclamaciones
   persistidas antes de escribir. Validar de nuevo cada cuerpo con sus padres reales.
   Después de cualquier espera, volver a comprobar acceso, selección, política de marca
   y vigencia, sin esperas adicionales antes de enviar la escritura.
6. Leer los cuatro objetos remotos y comparar cuenta, padres, estado, presupuesto,
   fechas, segmentación, destino, publicación y cuatro `OPT_OUT`. El botón y enlace se
   contrastan con campos devueltos por Meta, no con el cuerpo local. La campaña debe
   tener solo el conjunto aprobado y este solo el anuncio aprobado; una arista incompleta
   o con hijos adicionales bloquea la activación.
7. Obtener la vista previa remota. La segunda aprobación vincula usuario, solicitud,
   vista previa e importe. Activar anuncio, conjunto y campaña en ese orden, repitiendo
   comparación remota y comprobaciones locales después de las esperas.

Un error o cambio de evidencia después de reclamar la activación deja un resultado
incierto registrado. Si cambia el presupuesto, el acceso o los hijos antes del último
paso, la campaña queda en pausa. La reconciliación solo consulta; no repite escrituras
ambiguas ni interpreta `ACTIVE` como entrega efectiva.

## Moneda y aprobaciones anteriores

Qualify guarda el importe en centésimas de COP; Meta usa subdivisión 1 para COP. Las
nuevas aprobaciones incluyen `meta_currency_offset=1`: importe interno / 100 = entero
enviado a Meta, sin redondeo. El recibo vincula ambos importes y moneda. Vista previa y
aviso de gasto muestran el importe humano aprobado. Una aprobación antigua sin conversión
verificada no puede activar automáticamente un anuncio mediante este flujo.

**Dólares y pesos uruguayos (m-25091394, 2026-11-22).** Se aceptan cuentas en COP, USD y
UYU; la moneda sale siempre de la cuenta publicitaria elegida, nunca del dueño. Subdivisión
de Meta (tabla oficial de monedas, `docs/discovery-asesor-inversion-meta.md` §9): COP 1
(pesos enteros), USD 100 (centavos), UYU 100 (centésimos). Unidad de Meta = centésimas ×
subdivisión / 100. Todo vive en `qualify_api/ads/money.py` (`META_CURRENCY_OFFSETS`,
`to_meta`, `from_meta`); el asistente, el recibo de validación, la edición del presupuesto
(incluidos el piso de bajada con `act_/minimum_budgets` en la moneda de la cuenta y el
límite de gasto) y los resultados usan esa tabla. Cualquier otra moneda (VES incluida) se
rechaza con `CURRENCY_UNSUPPORTED` antes de llamar a Meta. Venezuela: se asume cuenta en
USD; **pendiente la decisión de Herwin** sobre VES. Las aprobaciones COP existentes no
cambian: mismo `meta_currency_offset=1`, mismas huellas y cargas. Las subdivisiones USD/UYU
salen de la tabla oficial; todavía no se probaron contra una cuenta real en esas monedas.
Los anuncios sin publicar (`unpublished_*`) siguen solo en COP.

Formato único para mostrar dinero (Raul, 2026-11-22): `money_display(minor, currency)` →
«$25.000 COP», «$10 USD», «$400 UYU» (centavos solo si los hay: «$10,50 USD»). Para el
campo de presupuesto, `budget_field(currency)` da `unit_name` («pesos colombianos»,
«dólares», «pesos uruguayos»), `example_minor` (25.000 COP, 10 USD, 400 UYU), `step_minor`
y `min_minor` (100: unidades enteras); `None` = moneda no admitida. El mínimo real de Meta
no está en la tabla: lo dice `act_/minimum_budgets` o la validación.

No se calcula un mínimo total a partir de mínimos diarios. Meta valida el importe
concreto junto con fechas y configuración; el recibo expresa aceptación de esa solicitud,
no un mínimo numérico universal.

## Alcance y verificación pendiente

Se admiten fotos y vídeos publicados del propio Instagram, cuenta COP y destino web.
Vivienda, público ampliado, radio, intereses, mejoras `OPT_IN`, anuncios a chats y formularios conservan
requisitos propios. Se necesitan aceptación de Meta y campos remotos suficientes para
demostrar la coincidencia; un campo ausente no se sustituye por una afirmación local.

No se realizaron escrituras reales contra Meta durante el desarrollo. Las pruebas usan
el cliente HTTP real con transporte simulado; las pruebas de Postgres comprueban fuentes,
aislamiento, selección, versiones, revocación y proyección hasta la interfaz. La prueba
con cuenta real y aprobación específica sigue siendo necesaria antes de cerrar criterios
que exigen aceptación o entrega real.

## Fuentes primarias consultadas el 6 de noviembre de 2026

- [Monedas de Marketing API](https://developers.facebook.com/docs/marketing-api/currencies/):
  tabla «Nombre / Código / Subdivisión mínima», fila «Peso colombiano / COP / 1» y
  explicación de que subdivisión 1 representa una unidad de moneda base.
- [Publicaciones de Instagram como anuncios](https://developers.facebook.com/docs/marketing-api/guides/instagramads/instagram-posts-as-ads/):
  `object_id` de Página, `instagram_user_id`, `source_instagram_media_id` y botón con enlace.
- [Conjuntos de una cuenta](https://developers.facebook.com/docs/marketing-api/reference/ad-account/adsets/):
  `campaign_spec` y validación sin cambios con respuesta `success: true`.
- [Anuncios de una cuenta](https://developers.facebook.com/docs/marketing-api/reference/ad-account/ads/):
  `adset_spec` como alternativa al identificador de conjunto y validación sin cambios.
- [Creatividad](https://developers.facebook.com/docs/marketing-api/reference/ad-creative/):
  lectura del botón de una publicación existente de Instagram.
- [Mínimos diarios](https://developers.facebook.com/docs/marketing-api/reference/ad-account/minimum_budgets/):
  mínimos diarios de subasta, sin fórmula de mínimo total.
- [SDK oficial 26.0.0](https://github.com/facebook/facebook-python-business-sdk/tree/26.0.0):
  tipos, campos y aristas de campaña, conjunto, creatividad, anuncio y `validate_only`.

Las capturas públicas y sus huellas SHA-256 se conservaron como evidencia local de la
sesión. No contienen credenciales ni respuestas privadas de una cuenta.
