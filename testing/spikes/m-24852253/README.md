# PASOS-12 · spike aislado (2026-10-26)

Esta rama conserva el prototipo; no se fusionan dependencias ni fixture a producción. Sólo se elimina una tarjeta sintética. No llama APIs de negocio, aprueba, envía o publica. `report.md` resume resultados y límites; `results.json` contiene muestras crudas. No hay secretos, estado de autenticación ni datos reales en esta carpeta.

## Fluidez (React equivalente, no sesión completa de Reflex)

Desde esta carpeta, Node24/npm y Chromium/Playwright ya instalados:

```sh
npm ci --no-audit --no-fund
node build.mjs
PLAYWRIGHT_MODULE=/ruta/al/modulo/playwright node run.cjs
```

`PLAYWRIGHT_MODULE` puede ser una instalación existente en cache; si Playwright está resoluble localmente, se omite. Usa su Chromium instalado por defecto o `CHROMIUM_EXECUTABLE_PATH=/ruta/al/ejecutable`. No instalar dependencias en la raíz de Qualify. El runner intercepta https://spike.test y no abre puerto ni accede a internet. En macOS requiere permitir Chromium fuera del sandbox. Viewport360×800, CPU6x CDP, 3 calentamientos y20 repeticiones intercaladas por variante. Calibra presupuesto rAF con60 intervalos inactivos. El resultado es proxy rAF, no frames físicos del compositor. Reduced motion y conservación de nodos se registran al final. Al repetir, results.json será reemplazado; conservar original si se desea comparar.

Versiones del benchmark en package-lock: Motion14.6.0, React/DOM19.3.0, esbuild0.28.2. La duración es240ms, curva(.22,1,.36,1), 20IDs sintéticos estables. El build standalone tiene su propio bundle.json: **no es el delta del paquete de la app**.

## Exports de la app real

Base origin/main8496c66. En un worktree dedicado, con el entorno Python existente preparado según qualify-dev-env (sin sync compartido), sin .env ni secretos, desde su raíz:

```sh
python testing/spikes/m-24852253/prepare-app.py none
UV_CACHE_DIR=/private/tmp/qualify-uv-cache PYTHONPATH=packages/api/src:packages/shared/src:packages/scraper/src:packages/models/src:packages/creative/src QUALIFY_AUTH_FAKE=1 QUALIFY_CALENDAR_WORKER=off uv run --no-sync reflex export --frontend-only --no-zip --env prod
# Guardar .web/build/client como testing/spikes/m-24852253/app-a0

python testing/spikes/m-24852253/prepare-app.py css
# Repetir el mismo export y guardar build/client como app-css

python testing/spikes/m-24852253/prepare-app.py motion
# Repetir el mismo export y guardar build/client como app-motion
```

El script cambia únicamente la inserción del fixture local en drafts_index y sus cuatro archivos locales. No ejecutar sobre un worktree con trabajo propio en esos archivos. A y C deben usar las mismas dependencias; revisar package.json y versiones instaladas después del init automático. En esta medición Reflex0.10.0/bun1.4.0 actualizaron el lock original React19.2.6 antes de exportar: los tres builds reales usaron React/DOM19.3.0, Router8.4.0 y Vite8.3.2. Entre A y C sólo cambia motion14.6.0. Guardados los tres package.json reales en esta carpeta.

El wrapper local usa rx.asset + NoSSRComponent y lib_dependencies=['motion@14.6.0'] sólo en C. Features domMax con import dinámico. Es código de spike, no un wrapper listo para producción. El compilador hace prerender interno; no se dejó servidor funcionando.

Desde esta carpeta, después de guardar los tres exports:

```sh
node measure-app.mjs
node route-phases.mjs
node final-report.mjs
```

`measure-app.mjs` suma JS de build/client/assets, gzip9/Brotli11 por archivo; no incluye backend, HTML o CSS común. `route-phases.mjs` separa scripts/preloads del HTML drafts, su cierre estático, módulo fixture al hidratar y features dinámicas adicionales. app-bundle.json contiene manifiesto y medidas originales por archivo. Los exports completos y node_modules quedan fuera de Git. El total de otras rutas no es descarga inicial de Por aprobar. Este método estima fases a partir del grafo generado; no es una captura HTTP. Cambios de hashes/imports de chunks compartidos afectan compresión.

`app-spike.patch` conserva el diff local del prototipo original; `prepare-app.py` permite reconstruir A0/A/C sin aplicar manualmente el parche. Los archivos Qualify/pasos12_* de la rama conservan la variante Motion final. No fusionarlos a main.

## Fuentes primarias

- https://motion.dev/docs/react-lazy-motion
- https://motion.dev/docs/react-reduce-bundle-size
- https://motion.dev/docs/react-animate-presence
- https://motion.dev/docs/react-layout-animations
- https://motion.dev/docs/react-accessibility
- https://reflex.dev/docs/wrapping-react/library-and-tags/
- https://reflex.dev/docs/wrapping-react/local-packages/

ReducedMotion=user desactiva transform/layout, pero conserva opacity; el fixture también apaga explícitamente el fade. DomMax se necesita para layout. Se midieron bundles reales, no tamaños publicitarios.
