# Brand Kit antes del login

> Pedido del 2026-10-02: el Brand Kit aparece antes del login y se puede usar sin
> iniciar sesión, pero sus datos se siguen guardando. La primera vista pide el correo
> con el que se guarda, y la cuenta que luego se cree con ese correo ya trae el Brand Kit.
> Ampliado el mismo día: se puede dejar a la mitad (lo hecho queda en la base y se
> retoma por correo) y el scraper corre igual. La primera vista es siempre el Brand Kit; el login va después.

## Flujo

1. **La primera vista siempre es el Brand Kit, nunca el login.** Un visitante sin
   sesión que entra a `/`, a cualquier página protegida (`require_login`) o que acaba
   de cerrar sesión llega a **`/brand/start`**, donde se le pide el correo. Si ya tiene
   un borrador abierto en esa sesión, vuelve a `/brand`. El login viene después: desde
   «¿Ya tienes cuenta? Inicia sesión», o solo, si el correo ya tiene cuenta. No hay
   botón para saltarse el Brand Kit.
2. **Según el correo:**
   - **Ya tiene cuenta** → `/login`, con el correo precargado y el aviso «Ese correo ya
     tiene una cuenta».
   - **Tiene un borrador terminado y todavía no tiene cuenta** → `/signup`, con el correo
     precargado.
   - **Tiene un borrador a medias** → vuelve a su wizard, en el paso donde lo dejó.
   - **Es nuevo** → `qualify_api.auth.start_brand_kit_draft` **crea un negocio
     provisional** en el acto y lo lleva a `/brand`. El negocio provisional tiene:
     - `tenants`;
     - un `users` dueño **sin login** (`auth_user_id` NULL, el mismo «asiento sin login»
       que ya permitía la 0008);
     - su `tenant_members`;
     - una `brands` llamada «Mi marca»;
     - una fila en `brand_kit_drafts` (migración 0037) con el correo.
3. Desde ese momento el wizard guarda **igual que con sesión**: todo pasa por
   `tenant_session(tenant provisional)`, con RLS.
   - `AuthState.guest_tenant_id` solo lo leen los módulos del Brand Kit, a través de
     `brand_tenant_id(auth)`.
   - El resto de páginas sigue exigiendo `session_tenant_id`, así que un borrador no abre
     nada más (lo comprueba `test_only_the_brand_kit_reads_the_draft_tenant`).
   - La barra lateral del invitado muestra:
     - «Marca»;
     - el correo;
     - «Negocio → Brand Kit»;
     - «Crear cuenta», «Iniciar sesión» y «Usar otro correo».
4. **Se guarda en cada paso** (ver abajo). Al terminar, el invitado va a **`/signup`**
   (Señales necesita login), con el correo ya cargado y un aviso.
   **Dentro de la sesión no existe «Marca»** (pedido del 2026-10-02): el Brand Kit se
   crea antes del login y, ya dentro, se edita desde **Negocio → Brand Kit**
   (`/brand/kit`, el editor de siempre). El resumen de solo lectura y «Crear uno nuevo»
   (lo temporal del 2026-10-01) se eliminaron. `/brand` queda como la entrada del
   invitado («¿Tienes redes?»); con sesión redirige al editor, y un kit dejado a la mitad
   vuelve a su wizard para terminarlo.
5. **`register_business`** busca un borrador sin reclamar con ese correo. Si lo
   encuentra:
   - crea la identidad sellada con el tenant del borrador en lugar de uno nuevo;
   - `claim_draft` le pone al tenant los datos del registro;
   - vincula el login al usuario sin login, sin duplicarlo;
   - renombra «Mi marca» al nombre del negocio;
   - marca `claimed_at`.

   Después del login automático el usuario cae en `/brand`, con su Brand Kit.

## Guardar a mitad y retomar

- **Cuándo se guarda.** Cada cambio de paso en `/brand/connect` y `/brand/manual`
  dispara `persist_progress`. Lo hace una caja invisible con `key=step` en la ventana de
  cada flujo, que se vuelve a montar con cada paso, así que no hay que tocar cada
  handler. Se llama a `brand_finish.save_progress`.
- **Qué guarda:**
  - el kit a medias;
  - las respuestas;
  - el perfil leído;
  - la posición, en `brand_kit_details.connect.progress` (sin migración):
    `{flow, step, completed, started_without_socials, rubro_asked, logo_from_profile,
    profile_pic_is_real}`.
- **Cuándo no guarda:**
  - mientras corre el guardado final;
  - mientras las cargas de la página todavía no han traído lo guardado (si no, lo pisaría
    con una sesión vacía);
  - sobre un kit ya terminado;
  - en un «Crear uno nuevo», que sigue reemplazando el kit solo al terminar.
- **Sin ruido:**
  - no crea una versión de voz por paso (`save_kit(adopt_voice=False)`); la adopta el
    guardado final;
  - no muestra ningún aviso en pantalla.
- **Orden del guardado:** kit, documentos, archivos. Si R2 falla o no está configurado,
  las respuestas y el paso igual quedan guardados. Las claves R2 de lo subido vuelven a
  la sesión, así que cada paso no resube los archivos.
- **Terminado = marca explícita.** Un kit cuenta como terminado si existe la fila de
  `brand_kits` y su `progress.completed` no es `False`. La pone a `True` el guardado
  final de cada wizard. Un kit guardado antes de este cambio, sin `progress`, cuenta
  como terminado. Lo calcula `brand_finish.kit_status`.
- **Retomar:**
  - `/brand` manda un kit a medias de vuelta a su wizard.
  - `/brand/connect` restaura la posición y las respuestas (`load_saved_details`) y
    los referentes ya encontrados (`resume_referentes`, sin créditos).
  - El flujo manual retoma solo desde los datos guardados (`BrandWizardState.resume`).

## El scraper

El invitado tiene los ids de su negocio provisional, así que el análisis del perfil y la
búsqueda de referentes por fases corren igual que con sesión. Al retomar, las fases ya
guardadas (`brand_discovery_phases`) se leen de la base y no se vuelven a comprar.

## Reglas

- Volver a escribir el mismo correo (sin importar mayúsculas ni espacios) **retoma**
  el borrador.
- Si un invitado inicia sesión en *otra* cuenta, el estado en memoria del Brand Kit se
  descarta. El borrador queda guardado con su correo.

## Límites conocidos

- **No se verifica el correo** (tampoco lo hace el registro, que crea el usuario con
  `email_confirm: True`). Quien escriba un correo con un borrador sin reclamar puede
  retomarlo.
- Los borradores abandonados se quedan en la base. Todavía no hay limpieza.
- Lo que se escribe dentro de un paso se guarda al cambiar de paso, no letra a letra.
- La muestra de voz y el análisis de Tu voz, y el brief subido, siguen siendo de la
  sesión. Lo que proponen sí se guarda, porque termina en el kit.
- Aplicar la migración: `just migrate`.
