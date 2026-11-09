# Revisión de recursos en la interfaz

- El servidor de localhost:3000 ejecuta el worktree `C:/Users/deivi/AppData/Local/Temp/qualify-m24820842`, no el checkout principal.
- Los controles «Integrado»/«Como firma» existen en `Qualify/content_generator.py`; su estado se transmite mediante `brand_logo_in_scene` y bloquea las plantillas hasta seleccionar firma.
- Contrato acordado con creative_audit: nuevas solicitudes desde UI envían integración por defecto; backend decide firma solo por instrucciones textuales o ausencia de superficie útil.
- Implementado en `Qualify/content_generator.py`, `creative_state.py` y su prueba `test_generator_voice_and_copy.py`: controles retirados; candidatos descritos como disponibles; solicitudes nuevas ignoran el viejo flag de firma; plantillas sin bloqueo de selector.
- Verificación: 109 pruebas focales aprobadas (21,09 s); `uv tool run ruff check` y `ruff format --check` de los tres archivos aprobados. No se sincronizó el entorno compartido.
- Runtime reconstruido y reiniciado con el mismo runner `.states/run_ui_m24820842.py`: launcher **26320**, listener **27496**, puerto **3000**. Se detuvo exclusivamente el árbol UI anterior después de confirmación de creative_audit de 304 pruebas backend y 27 defensas verdes, con cero borradores generándose y sin trabajos creativos pendientes del cliente.
- Compilación de 85 rutas y build de producción completados. Sin instalación de paquetes, sincronización, cambios de lock, migraciones ni trabajadores; calendario desactivado confirmado en logs.
- Salud HTTP: `/ping`, `/login`, `/create`, `/drafts` y las dos rutas de borradores del usuario devuelven **200**.
- Bundle servido nuevo `_create_._index-CMstqlBL.js`, SHA256 `1886C274967EAFCF8AC0D1B284CAD87FECEB644C5FFD189FE98631004D71B892`, coincide exactamente con build local descargado por HTTP. Ausentes `Integrado`, `Como firma` y `set_brand_logo_usage`; presente `solo los necesarios`. Evidencias: `.states/ui-placement-after-rebuild.json` y `.states/ui-placement-health.json`.
- Validación realizada por HTTP y artefactos compilados; sin inspección visual en navegador.
- Recuperación: ejecutar con `Start-Process -WindowStyle Hidden` el Python del entorno principal (`C:/Users/deivi/OneDrive/Escritorio/work/Qualify/.venv/Scripts/python.exe`) con argumento absoluto del runner y directorio de trabajo del worktree; registrar stdout/stderr en `.states/`. El runner carga el entorno local existente y desactiva trabajadores de calendario, sin sincronizar dependencias.
