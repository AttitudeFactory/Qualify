# BytePlus ModelArk — solo endpoints propios (`ep-…`), nunca el preset

`[IMPLEMENTADO 2026-10-20 · m-24820898]`

**Para qué:** que ningún material de una marca (fotos de producto, logo, presentador, textos del Brand Kit) llegue a un endpoint de ModelArk que cede los datos a BytePlus.

---

## 1. El problema

El 2026-10-07 se autorizaron en la campaña **«Data Collaboration Rewards»** de ModelArk (región ap-southeast-1) los **preset endpoints** de dos modelos:

- **Seedance 1.0 pro** (`seedance-1-0-pro-250528`)
- **Seedream 5.0 lite** (`seedream-5-0-lite-260128`)

Lo que pasa por un endpoint autorizado (lo que se envía y lo que se genera) queda **licenciado a BytePlus de forma perpetua, irrevocable y sublicenciable**. El acuerdo además **prohíbe** enviar datos personales o información confidencial. Revocar la autorización corta la recopilación de lo nuevo, pero no borra lo que ya se envió.

Cuando se llama a un modelo **por su ID pelado** (`"model": "seedance-1-0-pro-250528"`), la llamada entra por ese preset. Según el modal de la campaña, **cualquier preset que se cree después para un modelo autorizado también queda autorizado**. Solo un **endpoint propio** (`ep-…`) **que no esté inscrito en la campaña** mantiene los datos fuera del acuerdo.

Hasta este cambio, el adaptador (`packages/creative/src/qualify_creative/adapters/byteplus_ark.py`) usaba por defecto los dos IDs pelados en todas las rutas: el generador de piezas, el avatar del Brand Kit y la evaluación de escenas.

## 2. La regla en el código

1. **En la API va el endpoint, no el modelo.** `SeedreamImageAdapter` y `SeedanceVideoAdapter` reciben un mapa `endpoints` (ID de modelo → `ep-…`). El campo `"model"` del cuerpo de la petición lleva el endpoint. El ID de modelo sigue mandando en todo lo demás: los límites de la familia de Seedance, la fila de precios, el registro de uso y la procedencia.
2. **Un modelo sin endpoint se rechaza antes de enviar nada.** `generate` lanza `ArkPresetRefused` antes de abrir la conexión. El router lo registra como un salto fallido, y el operador lee «no está disponible ahora mismo» (`media.ark_failure_text`). La estimación de costo sigue funcionando, porque calcula con el ID del modelo y no llama a la red.
3. **Esto vale también para el modelo que se elige por petición.** El clip con referencias cambia a Seedance 2.x (`QUALIFY_SEEDANCE_REFERENCE_MODEL`, por defecto `dreamina-seedance-2-0-mini-260615`), y ese modelo necesita su propio endpoint en el mapa.
4. **Un "endpoint" que no empieza por `ep-` falla al arrancar.** Así, pegar un ID de modelo en el mapa no reabre el preset.
5. **Solo la evaluación interna puede usar presets.** El parámetro `allow_presets=True` existe en el código, pero **no se lee de ninguna variable de entorno**, y ni el generador ni el avatar lo activan. La evaluación de escenas (`just eval-escenas`, con marcas ficticias y prompts sin fotos) lo activa solo si se le pasa `--allow-presets`.

## 3. Configuración

```
QUALIFY_BYTEPLUS_ARK_ENDPOINTS=seedream-5-0-lite-260128=ep-…,seedance-1-0-pro-250528=ep-…,dreamina-seedance-2-0-mini-260615=ep-…
```

- Va en el `.env` local y en `/opt/qualify/.env.prod`. `docker-compose.prod.yml` pasa el archivo entero (`env_file`), así que no hay que tocar el compose.
- Cada modelo que se configure en `QUALIFY_SEEDREAM_MODEL`, `QUALIFY_SEEDANCE_MODEL` o `QUALIFY_SEEDANCE_REFERENCE_MODEL` (o sus valores por defecto) necesita su entrada.
- Si una entrada está mal escrita, el servicio de contenido no arranca (`ValueError` al cablearlo), igual que cuando un par modelo/resolución de Seedance no es válido.

**Pasos en la consola de ModelArk** `[A VERIFICAR — no se hicieron en esta sesión]`:
1. *Online inference → Create inference endpoint* para cada modelo, en la región ap-southeast-1.
2. Comprobar en la página de la campaña que el endpoint nuevo **no** figura como autorizado. Los presets autorizados son por modelo; un endpoint propio solo debería quedar inscrito si se autoriza a mano.
3. Copiar el ID `ep-…` al mapa.

## 4. Qué cambia al desplegar

**Sin `QUALIFY_BYTEPLUS_ARK_ENDPOINTS`, Seedream y Seedance quedan apagados en producción.** Fallan la imagen publicitaria generada, los videos de Seedance, los clips y la mascota del Brand Kit, y el operador ve «no está disponible ahora mismo». Es intencional: es mejor un error que ceder material de un cliente. Antes de desplegar (o justo después), hay que crear los endpoints y cargarlos en `/opt/qualify/.env.prod`.

## 5. Pendientes

- [ ] Crear los endpoints propios en ModelArk y cargarlos en el `.env` de producción (§3).
- [ ] Decidir si se **revoca** la autorización de los dos presets en la página de la campaña. Hoy solo sirve para evaluar y ya no hay código que llegue a ellos sin `--allow-presets`.
- [ ] El análisis completo de la campaña (créditos, contrato, los dos paquetes) está en `docs/byteplus-modelark-creditos-y-datos.md`, que **sigue sin commitear** en el worktree `seedance-bytedance-startup-credits-4a4bd5`, junto con la bitácora `docs/modelos-generativos/`. Hay que rescatarlo.
- [ ] Agregar BytePlus como encargado en la política de privacidad (`attitude-site`) antes de usarlo con clientes, aunque sea por endpoint propio.
