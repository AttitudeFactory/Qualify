# Prueba Nibbles: integración de recursos, versión 3

30 de octubre de 2026, hora local. El usuario autorizó repetir tres borradores en Nibbles Burger, videos de hasta cinco segundos y un nuevo tope de US$3. Autorizó recursos propios y la excepción de horario/términos del proveedor sólo para este lote. No se publicó, cambió la política general, modificó código de aplicación ni abrió una PR.

## Insumos y configuración

Producto: Super Smash, foto propia 1080×1051. Tres `logo_version`, categorías tomadas de la ficha y notas vacías: principal **imagotipo**, archivo `isologo.png`; secundarios **isotipo**, `imagotipo.png`, e **isologo**, `Gemini_Generated_Image_ya4q2hya4q2hya4q.jpg`. Integración explícita, sin firma local. Las instantáneas conservan categorías, huellas y bloque 3; el nombre de archivo no determina categoría.

Fuente distinta: [Pexels 8879534, Ron Lach](https://www.pexels.com/video/close-up-shot-of-hamburger-8879534/), [licencia](https://www.pexels.com/license/). Es un video de archivo licenciado, no un reel empresarial. Se prepararon 4,8 s, 120 fotogramas a 25 fps y 480×910; SHA256 `c72edd4cacd60ce3b17050e6ae5f16236324e127022d447ce66a2d6d70e20868`. La fuente está sin marca: quitar marca ajena no aplica.

Precios reales configurados: **v7**. Texto `claude-opus-5-5`, salida máxima 4096 tokens, sin reparación, cambio automático de modelo ni reintento SDK. Imagen `seedream-5-0-lite-260128`, US$0,035/imagen, referencias gratis. Video `dreamina-seedance-2-5-260628`, borrador 480p, sin audio ni final 1080p. Réplica con duración automática −1: nominal 5, fuente real 4,8; cotización conservadora 5+5 s = 96.075 tokens = US$0,614880, reserva US$1,30. El prompt real protegió sustitución durante las acciones y los tres recursos; 2464 caracteres.

## Resultados guardados

| Borrador generado | Identificador | Resultado técnico |
|---|---|---|
| Galería | `627fc258-43dc-4c41-aadd-5030ffa650ea` | Dos imágenes 1080×1350 y video de 4,916667 s |
| Volante | `bff2d3f2-1699-4200-9680-141ba364eb52` | Una imagen 1080×1350 |
| Réplica | `2c4bc9bc-50e6-4714-a00c-01f5d4cd24a7` | Video de 4,708333 s, 464×882 |

Los tres enlaces `/drafts/<id>` respondieron 200; los cinco medios, 206 por la ruta normal de visualización. Los videos se decodificaron completos: 118 y 113 fotogramas. Se inspeccionaron todas las imágenes y muestras 10/50/90 % de ambos videos, también con revisión independiente; no se afirma reproducción visual completa.

**Calidad parcial.** En volante y dos imágenes de galería aparecen recursos en soportes naturales, pero el imagotipo horizontal se recompone verticalmente. El volante contiene «DM» y superpone texto sobre parte de los logos. El video de galería conserva el principal horizontal en el letrero, isologo en papel e isotipo en vaso; el acercamiento desenfoca/recorta recursos. Su salida original de 5,041667 s se limitó antes de almacenar usando el ajustador normal con máximo 4,9; sin añadir logos.

La réplica coloca logos sobre el pan e inventa mano/envoltura en lugar de la tabla original. Producto aproximado, integración/contexto no conformes. No se regeneró por calidad. Una imagen huérfana del primer intento sí conservó el imagotipo horizontal: no puede atribuirse el fallo a una limitación inevitable ni establecer causalidad con esta muestra.

## Costos e incidencias

Se conservaron dos galerías fallidas por `RemoteProtocolError`: `9c84e370-76b1-432c-ba47-ad37acdce228` y `8257e21a-1b51-455e-80fd-4aff6c5d3fe1`. La recuperación final fue un borrador nuevo normal, autorizada expresamente, con hasta tres intentos de transporte por imagen, cada POST reservado y registrado; nunca se forzó la transición de un fallo ni se fingió caché.

Totales: **5 llamadas de texto, 8 POST de imagen —5 éxitos y 3 inciertos— y 2 videos**. Costo registrado, incluidos intentos fallidos: Anthropic US$0,213033; Seedream US$0,175000; Seedance US$1,066080; **US$1,454113** en DB. Ledger sin redondeo por fila: US$1,4541126. Se retienen **US$0,105** de las imágenes inciertas: máximo conocido **US$1,5591126**, bajo el tope. No son una factura ni se liberaron cobros inciertos.

ScrapeCreators consumió **3 créditos**, saldo 1882→1879, sin respuestas aprovechables; no se afirma su equivalencia USD. Se cambió a la fuente gratuita aprobada. No quedan generaciones autorizadas en curso. Un cliente y tres piezas no estiman una tasa de fidelidad multimarcas.
