## PASOS-12 · Motion frente a CSS (m-24852253)

**Recomendación: conservar CSS.** El spike no demuestra mejora de fluidez que compense el peso y mantenimiento adicionales. Motion queda fuera de las dependencias de producción.

| Variante | App completa JS gzip / Brotli (B) | Por aprobar hasta hidratar fixture, gzip (B) | Features diferidas, gzip (B) | rAF mediana / p95, ms | Frames perdidos estimados |
|---|---:|---:|---:|---:|---:|
| A · CSS | 1901819 / 1584991 | 494282 | 0 | 8.30 / 9.20 | 0.10% |
| C · Motion | 1953365 / 1630994 | 510319 | 32031 | 8.30 / 9.30 | 3.09% |

El delta de todos los assets JavaScript del cliente **de la app Reflex real** es +51546 B gzip (+50.34 KiB) y +46003 B Brotli (+44.92 KiB). Son sumas de cada archivo comprimido individualmente, no una descarga HTTP capturada. Incluyen todas las rutas; los cambios de hashes/imports pueden alterar compresión de chunks compartidos. La fase Por aprobar incluye scripts/preloads del HTML y su cierre de imports estáticos, más el módulo NoSSR de la tarjeta al hidratar. DomMax queda realmente diferido en Vite: 32031 B gzip. Es carga automática tras montar el fixture, no ahorro del total descargado. No sumar esta columna al peso total otra vez.

| Aspecto | A · CSS | C · Motion |
|---|---|---|
| Mantenimiento | Clase de salida, colapso nativo y retirada diferida de 240 ms; sincronizar temporizador/cancelación | Keys estables, AnimatePresence/popLayout y layout declarativo; añadir proveedor, features y wrapper Reflex |
| Riesgo | Recalcula layout durante el colapso; cuidar cambios de lista mientras sale | Dependencia nueva, carga/hidratación y ciclo de presencia; integración con eventos servidor aún pendiente |
| Decisión | Mantener para este alcance | No integrar; reconsiderar sólo ante layout más complejo con ganancia medida en aplicación real |

### Prueba realizada y límites

Tres exports de la aplicación completa desde origin/main 8496c66 en worktree de spike: A0 sin prototipo, A con lista CSS sintética en Por aprobar, C con exactamente la misma lista mediante wrapper local NoSSR y Motion. A y C exportaron correctamente frontend, SSR y prerender; no se ejecutaron servicios de negocio, aprobaciones ni publicaciones. El fixture y sus dependencias quedan sólo en la rama de spike; no se fusionan.

Reflex 0.10.0, bun 1.4.0. El lock original indicaba React 19.2.6; la inicialización actualizó dependencias antes de medir: **React/ReactDOM 19.3.0, Vite 8.3.2, React Router 8.4.0**. Los package.json guardados de A y C tienen una sola diferencia: motion 14.6.0. El export A0 también queda archivado; no se atribuye a Motion el cambio de dependencias de inicialización.

Fluidez medida en un fixture React equivalente y aislado, no en la sesión websocket completa de Reflex: 20 tarjetas sintéticas con IDs estables, salida de la segunda, recolocación de vecinos, 240 ms y curva existente cubic-bezier(.22,1,.36,1), viewport 360×800. React/ReactDOM 19.3.0 en ambos; esbuild 0.28.2. Tres calentamientos y 20 repeticiones por variante, orden alternado, Chromium 151.0.7922.34, CDP CPU 6x. Máquina Apple M1 Pro, 8 núcleos, macOS 26.3.1 arm64.

Se registra rAF durante 400 ms. El presupuesto se calibró con 60 intervalos inactivos: 8.30 ms (~120 Hz). Los frames perdidos son una **estimación de intervalos rAF**, no frames físicos del compositor: Σ max(0, round(intervalo/presupuesto)-1). Una máquina, sin prueba estadística de equivalencia; CPU 6x no emula GPU, memoria o red de Android. El máximo observado fue CSS 16.70 ms y Motion 42.10 ms. No se demuestra que CSS gane universalmente ni se mide latencia de backend.

Las 20 repeticiones de cada variante conservaron los nodos de tarjetas vecinas y terminaron con 19 tarjetas. Reduced motion: ambas quitaron la tarjeta con cero animaciones activas, transform none o matriz identidad; cero errores JavaScript. Se desactiva explícitamente también opacity: MotionConfig reducedMotion=user por sí solo conserva fades. Wrapper Reflex renderizado y luego compilado en los exports reales; el benchmark de fluidez no prueba actualización de estado servidor, foco, SSR/hidratación de la lista en uso autenticado ni cancelación de aprobaciones.

### Reproducción y evidencia

Comandos en README.md. build.mjs + bundle.json miden el React standalone (no confundir con appdelta); measure-app.mjs + route-phases.mjs + app-bundle.json miden los exports reales. run.cjs + results.json contienen muestras crudas, calibración y controles. app-css-package.json/app-motion-package.json preservan versiones reales. Logs /private/tmp/qualify-pasos12-export-{a,css,b}.log.

Fuentes oficiales consultadas el 26-10-2026: [LazyMotion](https://motion.dev/docs/react-lazy-motion), [bundle/features domMax](https://motion.dev/docs/react-reduce-bundle-size), [AnimatePresence](https://motion.dev/docs/react-animate-presence), [layout](https://motion.dev/docs/react-layout-animations), [reduced motion](https://motion.dev/docs/react-accessibility), [wrapper Reflex](https://reflex.dev/docs/wrapping-react/library-and-tags/), [componentes locales](https://reflex.dev/docs/wrapping-react/local-packages/). Los tamaños publicitarios no se usaron como resultado.
