# Brand Kit antes del login

> Pedido del 2026-10-02: el Brand Kit aparece antes del login y se puede usar sin
> iniciar sesión, pero sus datos se siguen guardando. La primera vista pide el correo
> con el que se guarda, y la cuenta que luego se cree con ese correo ya trae el Brand Kit.

## Flujo

1. Un visitante sin sesión que entra a `/` (o a cualquier página del Brand Kit) llega a
   **`/brand/start`**, donde se le pide el correo. Desde ahí también puede ir a
   «Inicia sesión».
2. Con ese correo, `qualify_api.auth.start_brand_kit_draft` **crea un negocio
   provisional** en el acto: `tenants`, un `users` dueño **sin login**
   (`auth_user_id` NULL, el mismo «asiento sin login» que ya permitía la 0008), su
   `tenant_members` y una `brands` llamada «Mi marca». Además deja una fila en
   `brand_kit_drafts` (migración 0037) con el correo.
3. Desde ese momento el wizard guarda **igual que con sesión**: todo pasa por
   `tenant_session(tenant provisional)`, con RLS. No cambia ninguna tabla del Brand
   Kit. `AuthState.guest_tenant_id` solo lo leen los módulos del Brand Kit, a través
   de `brand_tenant_id(auth)`. El resto de páginas sigue exigiendo
   `session_tenant_id`, así que un borrador no abre nada más (lo comprueba
   `test_only_the_brand_kit_reads_the_draft_tenant`). La barra lateral del invitado
   solo muestra «Brand Kit», el correo, «Crear cuenta», «Iniciar sesión» y «Usar otro
   correo».
4. Al terminar el wizard, el invitado va a **`/signup`** (Señales necesita login), con
   el correo ya cargado y un aviso.
5. **`register_business`** busca un borrador sin reclamar con ese correo. Si lo
   encuentra:
   - crea la identidad sellada con el tenant del borrador en lugar de uno nuevo;
   - `claim_draft` le pone al tenant los datos del registro;
   - vincula el login al usuario sin login, sin duplicarlo;
   - renombra «Mi marca» al nombre del negocio;
   - marca `claimed_at`.

   Después del login automático el usuario cae en `/brand`, con su Brand Kit.

## Reglas

- Volver a escribir el mismo correo (sin importar mayúsculas ni espacios) **retoma**
  el borrador.
- Un correo que ya tiene cuenta no abre borrador: se pide iniciar sesión. Eso incluye
  un borrador ya reclamado.
- Si un invitado inicia sesión en *otra* cuenta, el estado en memoria del Brand Kit se
  descarta. El borrador queda guardado con su correo.

## Límites conocidos

- **No se verifica el correo** (tampoco lo hace el registro, que crea el usuario con
  `email_confirm: True`). Quien escriba un correo con un borrador sin reclamar puede
  retomarlo.
- Los borradores abandonados se quedan en la base. Todavía no hay limpieza.
- Aplicar la migración: `just migrate`.
