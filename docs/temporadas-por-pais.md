# Temporadas por país (m-24976896)

Calendario de las fechas para las que Qualify propone stickers y videos de temporada
(`packages/api/src/qualify_api/whatsapp/seasons.py`). Es código, no una tabla: cambiar
una fecha es un PR. Cada temporada de un año tiene la clave de la biblioteca
`{slug}-{año}` (`navidad-2026`) y la etiqueta `{nombre} {año}` (máximo 24 caracteres).

El país es el del negocio (el que eligió al registrarse); si no es uno de los tres, se usa
la lista común.

| Temporada | Clave | Fecha | Colombia | Venezuela | Uruguay | Lista común |
|---|---|---|:-:|:-:|:-:|:-:|
| Año Nuevo | `ano-nuevo` | 1 de enero | ✓ | ✓ | ✓ | ✓ |
| Carnaval | `carnaval` | lunes de Carnaval (48 días antes de Pascua) | — | ✓ | ✓ | — |
| San Valentín | `san-valentin` | 14 de febrero | — | ✓ | ✓ | ✓ |
| Día de la Madre | `dia-de-la-madre` | segundo domingo de mayo | ✓ | ✓ | ✓ | ✓ |
| Día del Padre | `dia-del-padre` | tercer domingo de junio (Uruguay: segundo domingo de julio) | ✓ | ✓ | ✓ | ✓ |
| Amor y Amistad | `amor-y-amistad` | tercer sábado de septiembre | ✓ | — | — | — |
| Noche de brujas | `noche-de-brujas` | 31 de octubre | ✓ | ✓ | ✓ | ✓ |
| Navidad | `navidad` | 25 de diciembre | ✓ | ✓ | ✓ | ✓ |

«Otra ocasión» (texto libre, por ejemplo «Aniversario del local») no está en el
calendario: la biblioteca la acepta como hasta ahora.

## Aviso en «Tu semana»

Tres semanas antes (21 días o menos, en la zona horaria del negocio) de una fecha de su
país, si el negocio no tiene tanda para esa temporada (filas sin archivar con esa clave):
**«Navidad está cerca: crea tus stickers y videos.»** con [Crear para Navidad] (abre Tu
marca en el flujo, con la temporada elegida) y «Ahora no». Un solo aviso a la vez, el de
la fecha más cercana. Solo dentro de la app: nunca WhatsApp ni correo.

«Ahora no» no vuelve para esa temporada en ese negocio. Se guarda sin tabla nueva, en la
clave reservada `season_notices_dismissed` del documento `connect` de los datos de la
marca (las últimas 24 claves).

Lectura para las pantallas: `production_season_calendar()` →
`SeasonCalendarService.upcoming(tenant_id, n=3)` (paso «¿Para qué ocasión?»),
`.notice(tenant_id, brand_id)` (el aviso o nada) y `.dismiss(tenant_id, brand_id,
season_key)` («Ahora no»).
