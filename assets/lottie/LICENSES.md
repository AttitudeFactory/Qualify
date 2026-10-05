# assets/lottie — licencias

Todas las animaciones de esta carpeta son **propias**: se generan por código desde
`Qualify/ui/lottie_shapes.py` (formas simples, capas `ty: 4`, colores de los tokens del
design system). No se descargó ningún archivo de LottieFiles ni de otro catálogo, así que
no aplica la Lottie Simple License ni ninguna atribución de terceros.

| Archivo | Qué es | Generador | Licencia |
|---|---|---|---|
| `flame.json` | Caliente — llama que respira (loop, 1 s) | `lottie_shapes.flame()` | la del repositorio |
| `steam.json` | Humeante — tres hilos de vapor (loop, 2 s) | `lottie_shapes.steam()` | la del repositorio |
| `freeze.json` | Congelar — copo que cristaliza (una vez, 0,8 s) | `lottie_shapes.freeze()` | la del repositorio |
| `thaw.json` | Descongelar — el copo se derrite: `freeze` invertido en el tiempo por el generador (una vez, 0,8 s) | `lottie_shapes.thaw()` | la del repositorio |
| `scheduled.json` | Programado — reloj que da una vuelta (una vez, 1 s) | `lottie_shapes.scheduled()` | la del repositorio |
| `published.json` | Publicado — anillo y check que se dibujan (una vez, 0,8 s) | `lottie_shapes.published()` | la del repositorio |

Regenerar: `python -m Qualify.ui.lottie_shapes` desde la raíz. `Qualify/test_lottie_assets.py`
verifica que lo commiteado coincide con el generador.

**Si algún día entra un asset externo** (LottieFiles → «Lottie Simple License»: uso comercial
y modificación permitidos, atribución opcional pero recomendada, prohibido compilar archivos
para un servicio competidor — <https://lottiefiles.com/page/license>), va en esta tabla con su
enlace, su autor y la licencia exacta, y queda fuera del generador.

Dependencias de runtime (declaradas en `Qualify/ui/lottie.py`, instaladas por Reflex):
`lottie-react@3.1.2` (MIT) y `lottie-web@5.13.0` (MIT).
