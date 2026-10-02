# Marca: resumen del Brand Kit y "Crear uno nuevo" — TEMPORAL (solo para pruebas)

> **Cerrado el 2026-10-02.** El fundador pidió quitar el Brand Kit de dentro de la sesión:
> «Marca» (`/brand`) muestra **solo el resumen de solo lectura**, sin «Crear uno nuevo»,
> y la barra lateral de la sesión ya no lleva al editor (`/brand/kit`, que sigue para el
> invitado que está creando su kit antes de registrarse). El reemplazo de un kit por otro
> ya no existe desde la interfaz; la bandera `BrandWizardState.replacing_kit` y sus
> comprobaciones quedan en el código sin nada que las active. El resumen dejó de ser
> temporal: es la vista del Brand Kit dentro de la sesión. Lo de abajo es el registro de
> cómo era mientras duró, para quien quiera retirar la bandera.


`[TEMPORAL — 2026-10-01, pedido del fundador]` Esto existe **solo para probar** el Brand Kit de punta a punta. Hay que **eliminarlo** cuando terminen las pruebas. Este documento dice qué es, por qué está y cómo quitarlo sin dejar restos.

## Qué hace

- **Marca (`/brand`) con un Brand Kit ya terminado:** muestra un **resumen de solo lectura** de lo guardado y nada se edita ahí. Incluye identidad, rubro, ubicación, cuenta, tono, voz clonada, paleta, brandboard (logo, versiones y elementos con su contexto), ejemplos, llamados a la acción, hashtags, palabras vetadas y claims. Para editar está **Negocio → Brand Kit** (`/brand/kit`), que no es temporal.
- **Botón "Crear uno nuevo":** pide confirmación y abre la pregunta de siempre ("¿Tienes redes sociales?") con un wizard **vacío**. No carga nada de lo guardado. El Brand Kit actual **sigue activo** hasta que el nuevo se termine con "Mejorar tu perfil". Al terminar, el nuevo **reemplaza al anterior por completo**: kit, brandboard (los archivos que no estén en el nuevo se quitan del registro) y respuestas, incluidas las de conexión y el perfil, aunque el nuevo no las tenga.
- **"Volver al Brand Kit actual":** cancela el reemplazo.
- **Marca sin Brand Kit:** muestra la pregunta de siempre, igual que antes.

Lo que **no** se reemplaza al crear uno nuevo: la voz clonada en HeyGen (es de la marca; "Volver a clonar" en "Tu voz" la reemplaza) y los referentes con su clasificación (se recalculan solos si la búsqueda nueva cambia).

## Dónde está en el código

Todo lo temporal lleva el comentario `TEMPORAL` y apunta a este documento.

| Pieza | Archivo |
|---|---|
| Estado y página del resumen, botón y reemplazo | `Qualify/brand_summary.py` (archivo entero) |
| Ruta `/brand` → `brand_home_index` + `BrandSummaryState.load` | `Qualify/Qualify.py` |
| Bandera `replacing_kit` y no cargar lo guardado mientras está activa | `Qualify/creative_wizard_pages.py` (`BrandWizardState.replacing_kit`, `load_saved_assets`, `_reset_fields`) |
| Parámetro `notice` de `brand_choice_index` (aviso "Estás creando uno nuevo") | `Qualify/creative_wizard_pages.py` |
| Al guardar con `replacing_kit`: reescribir los tres documentos; limpiar la bandera | `Qualify/brand_finish.py` (`snapshot_states`, `save_brand_kit`) |
| Reset en el logout | `Qualify/auth_state.py` (`BrandSummaryState`) |
| Tests | `Qualify/test_brand_summary.py` |

## Cómo eliminarlo

1. Borrar `Qualify/brand_summary.py` y `Qualify/test_brand_summary.py`.
2. En `Qualify/Qualify.py`, volver la ruta `/brand` a `brand_choice_index` con `on_load=[AuthState.require_login, BrandConnectState.clear_entry]`, y quitar el import de `brand_summary`.
3. En `Qualify/auth_state.py`, quitar `BrandSummaryState` del reset del logout.
4. En `Qualify/creative_wizard_pages.py`, quitar `replacing_kit` (el campo, su línea en `_reset_fields` y el `if self.replacing_kit` de `load_saved_assets`) y el parámetro `notice` de `brand_choice_index`.
5. En `Qualify/brand_finish.py`, quitar el bloque `if wizard.replacing_kit:` de `snapshot_states` y las líneas que limpian `replacing_kit` en `save_brand_kit`.
6. Buscar `TEMPORAL` y `brand-kit-resumen-temporal` en el repo: no debe quedar ninguna referencia.
7. Correr `just lint` y `just test`.
