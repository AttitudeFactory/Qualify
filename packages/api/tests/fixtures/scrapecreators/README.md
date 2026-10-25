# Respuestas grabadas de Scrape Creators (pruebas sin red)

Cuerpos en la forma cruda que devuelve el proveedor —la misma que normaliza
`qualify_api.referentes.scrapecreators_client` y que fijan sus pruebas
(`test_referentes_scrapecreators_client.py`)— para una cuenta de demostración, sin datos
de personas reales:

| Archivo | Endpoint | Qué representa |
|---|---|---|
| `instagram_profile_heladeria.json` | `GET /v1/instagram/profile` | Cuenta pública de un negocio de comida, con foto de perfil |
| `instagram_posts_heladeria.json` | `GET /v2/instagram/user/posts` | Una página de publicaciones (sin cursor siguiente) |
| `instagram_profile_private.json` | `GET /v1/instagram/profile` | Cuenta privada (`is_private: true`) |

Los `taken_at` son relativos: la prueba los reescribe a «hace N horas» al servirlos, para
que caigan dentro de la ventana de 7 días de las métricas.

Las usa `packages/api/tests/test_brand_prefill.py` (m-24852197).
