# Exploración de naming y dominios — sesión 2026-08-10

> **⚠️ ACTUALIZACIÓN (2026-08-12): la decisión interina ya se concretó.** El dominio de Attitude existe y está operativo: **`attitudefactory.co`**, comprado el 2026-08-12 y sirviendo el sitio de Attitude sobre HTTPS. Qualify vivirá en **`qualify.attitudefactory.co`**. Ver **[`prioridad-despliegue-subdominio.md`](prioridad-despliegue-subdominio.md)** para el estado verificado, la bifurcación de hosting pendiente y la cadena hacia Business Verification / Tech Provider.
>
> Se eligió `.co` (ccTLD de Colombia, coherente con el RUT de Cúcuta con el que se hará la verificación) sobre `.ai`: US$4.99 el primer año frente a ~US$160/2 años, y Meta no restringe TLDs. La marca y el dominio **propios de Qualify** siguen **abiertos** — todo lo de abajo se conserva para retomarlos sin repetir el trabajo.
>
> **DECISIÓN INTERINA ORIGINAL (fundador, 2026-08-10):** por ahora el producto se despliega **bajo el dominio del sitio de Attitude** (el portfolio `Attitude.org.ve`, ya documentado en `docs/arquitectura.md` §6 R9 como Business Portfolio `218896178911983`). La decisión de marca/dominio propio queda **abierta** — este documento preserva la exploración para retomarla sin repetir el trabajo.
>
> **No se compró ningún dominio en esa sesión.** Toda disponibilidad y precio de abajo es un snapshot del 2026-08-10 vía Cloudflare Registrar (precios al costo, USD/año) y **caduca**: cualquier candidato serio debe re-validarse antes de decidir. (El snapshot del `.ai` en particular ya caducó: Identity Digital subió el precio mayorista en marzo de 2026.)

## 1. Contexto y método

Sesión de exploración con el fundador: validación de disponibilidad vía API de Cloudflare Registrar (`domain-check`/`domain-search`, lotes de 20), análisis SEO (SERP vía búsqueda web + Cloudflare Radar ranking), validación de hipótesis de audiencia con fuentes públicas, y whois directo contra NICs nacionales para ccTLDs que Cloudflare no vende.

Punto de partida: el nombre de trabajo "Qualify" venía de la "regla de Spotify" (patrón `-ify`). Hallazgo central: lo que hace funcionar ese patrón no es la fonética sino que **la palabra sea inventada** (SERP propia desde el día uno). "Qualify" cumple la fonética pero es palabra de diccionario con un incumbente gigante al lado.

## 2. Hipótesis de audiencia — VALIDADA

Hipótesis del fundador: usuarias mujeres millennials de marketing/emprendimiento + segmento secundario de "hombres de gimnasio del marketing" (agency bros / closers).

- EE.UU.: **60.1%** de los marketing/social media managers son mujeres (Zippia).
- México: **~70.7%** de los community managers son mujeres (Merca 2.0); retrato robot del CM: "mujer, 30 años" (Marketing Directo), mayoría mujeres < 35.
- LATAM tiene **las tasas de emprendimiento femenino más altas del mundo** (GEM): TEA femenina regional ~20-21%; **Colombia 26%** (top mundial con Guatemala 28.2% y Ecuador 32%).
- Matiz: ~82% de las emprendedoras de la región emprende por necesidad (Pro Mujer) → alta sensibilidad al precio.
- El segmento "bro" existe como comprador ruidoso pero no se encontró dato duro que lo dimensione; tratarlo como secundario, no como centro del naming.

**Conclusión:** la usuaria mediana es una mujer de 28-35 en marketing o emprendimiento, en países récord de emprendedoras (CO en particular). El nombre debe hablarle a ella primero.

## 3. Análisis SEO de "Qualify" — handicap estructural

- "Qualify" es palabra de diccionario en inglés: imposible rankear por el término solo.
- **Qualified.com** (adquirida por Salesforce, misma categoría B2B marketing/pipeline) está en el **bucket top-5000 mundial** de Cloudflare Radar; todos nuestros candidatos: no rankeados (>200k o sin bucket). Vivir a una letra de ese incumbente = impuesto permanente en brand ads y confusión.
- El espacio "Cualify/Kualify" en español ya está poblado: cualify.es (reviews), **cualify.agency (calificación de leads con IA — categoría exacta)**, cualify.com.ar, kualify.net. Riesgo SEO **y** marcario.
- La órbita de grafías inventadas cercanas está agotada: de 20 variantes (`qualy`, `kalify`, `calify`, `qualia`, `qualifai`, `kualy`…) **17 tomadas**; solo quedan grafías que fallan el radio test (`qalify.io`, `qwalify.io`).
- Regla general que guió todo: el bonus de exact-match domain murió hace años; lo que importa es **SERP de marca limpia y conquistable**. El TLD es neutro para rankings (el `.com` importa para tráfico directo/email, no para Google).

## 4. Dominios propiedad actual

Único dominio en la cuenta Cloudflare: `agromileto.com` (expira 2030-05-28, auto-renew, locked). Nada relacionado con el producto.

## 5. Candidatos por familia (snapshot 2026-08-10)

### 5.1 Familia "qualify" literal

Tomados: `qualify.com/.io/.ai/.co/.social/.marketing/.agency`, `getqualify.com/.io`, `tryqualify.com`, `usequalify.com`, `qualifyapp.com`, `qualifyhq.com`, `qualifylabs.com`, `qualify-app.com`. Premium (Cloudflare no los vende): `qualify.app`, `qualify.dev`, `qualify.club`, `qualify.vip`.

Libres: `qualifyhq.io` $50 · `qualify.pro` $21.20 · `qualify.tools`/`qualify.team` $28.20 · `qualify.tv` $25 · `qualify.media` $35.20 · `qualify.studio` $31.20 · `qualify.zone` $30.20 · `qualify.work` $10.20 · `cualify.io`/`kualify.io` $50 · `qualify.com.mx` $16.75 · `cualify.mx` $30.70.

### 5.2 Familia "resuena" (primer finalista de la sesión)

Concepto: "resonar" = social listening; **cero incumbentes tech** en la SERP; `resuena.com` sin ranking en Radar.

Libres: `resuena.io` $50 · `resuenahq.com` $10.46. Tomados: `resuena.com`, `resuena.app`, `.co`, `.mx`, `.com.mx`, `.uy` (holder real con NS de Antel). Libres en NICs nacionales (fuera de Cloudflare): `resuena.com.ve` (NIC.ve) y `resuena.com.br` (Registro.br — **requiere CPF/CNPJ brasileño**).

### 5.3 ccTLDs latinos — reglas aprendidas

- Cloudflare Registrar solo vende `.co` y `.mx`/`.com.mx` de los consultados; **no** vende `.ve`, `.uy`, `.br`, `.lat`.
- `.com.ve`: los tres nombres clave (`resuena`, `qualify`, `cualify`) **libres** vía NIC.ve (proceso manual/lento).
- `.uy`: whois de NIC Uruguay inaccesible desde aquí; verificación por DNS.
- SEO: **los ccTLDs geo-anclan** — para un SaaS regional la base correcta es un dominio global (`.io`/`.com`) con subcarpetas + hreflang; los ccTLDs se compran como defensa de marca.

### 5.4 Nombres latinos (concepto chisme/vigilancia/sabor)

Libres: `bochinche.io` $50 · `radiobemba.io` $50 · `bemba.io` $50 · `bemba.social` $32.20 · `corrillo.io` $50 · `lamovida.io` $50 · `tumbao.io` $50 · `cotorreo.io` $50 · `elvigia.io` $50 · `guachiman.io` $50 · `epale.io` $50 · `comadre.io`/`lacomadre.io` $50 · `olfato.io` $50 · `melao.io` $50 · `sabrosura.io` $50 · `catador.io` $50.

Descartes por colisión: **Runrún** (runrun.es = medio grande venezolano), **El Vigía** (empresas de seguridad + ciudad + periódico), **Épale** (revista Épale CCS de Caracas), **La Chispa** (Chispa = dating app de Match Group/Univision con 4M+ descargas **dirigida al público latino** — la peor colisión posible), Quiubo/Kiubo, Sintoniza, Vitrina, Brújula, Rastro (tomados).

### 5.5 Patrón -ify con raíz latina (síntesis "regla de Spotify" + LATAM)

| Nombre | .com | .io | Nota |
|---|---|---|---|
| **Bembify** | ✅ $10.46 | ✅ $50 | Único candidato de toda la sesión con `.com` + `.io` libres |
| Chismify | ✅ $10.46 | ✅ $50 | |
| Vozify | ❌ | ✅ $50 | |
| Rumorify | ❌ | ✅ $50 | |
| Sabrify / Tumbify / Oyeify / Criollify | ✅ $10.46 | — | |
| Facturify | ❌ | ✅ $50 | **Descartado**: en LATAM "factura" = SaaS de facturación electrónica; confusión de categoría |
| Mosquify | ❌ | ✅ $50 | **Descartado**: el tallo "mosqu-" lee *mosquito*, no "ponte mosca"; y falla el radio test (3 grafías: mosquify/moskify/moscify, con el `.com` canónico tomado). El concepto "mosca=alerta" sobrevive como copy: `pontemosca.com` $10.46 libre |

### 5.6 Nombres para la audiencia validada (empoderamiento / complicidad)

El espacio de empoderamiento femenino está caliente — tomados: `jefa`, `lajefa`, `patrona`, `lapatrona`, `poderosa`, `musa`, `rompela`, `laquemanda`, `manda`, `dura`, `suena` (.com/.io), `socia`/`lasocia`/`tusocia`, `mija` (.com/.io), `mafe.io`, `reinita.com`, `manita.io`, `lavecina.com`, `chama.io`/`lachama.com`.

Libres: `laenterada.com` $10.46 + `enterate.io` $50 · `chismosa.io` $50 · `metiche.io` $50 · `avispada.io` $50 · `pontemosca.com` $10.46 · `echaleojo.com` $10.46 · `elpegue.com` $10.46 · `malaslenguas.io` $50 · `sedice.io`/`cuentan.io` $50 · `parcera.io` $50 + `tuparcera.com` $10.46 · `latia.io` $50 · `vecina.io` $50 · `tuchama.com` $10.46 · `comay.io` $50.

### 5.7 Familia "Sedice" (favorita del fundador al cierre)

Concepto: *lo que se dice ahí afuera* — semántica exacta del producto sin explicación. Incumbente único: Sedice.com, foro español de ciencia ficción, **cerrado definitivamente en julio 2023** (dominio pagado, sitio muerto) → SERP con fantasma, no competidor.

Libres: `sedice.io` $50 · `sedice.co` $15 (bonus: Colombia) · `sedice.app` $14.20 · `sedicehq.com` $10.46 · `loquesedice.com` $10.46 · `sedice.social` $32.20 · `sedicen.com`/`elsedice.com` $10.46 · `quesedice.io` $50. Tomados: `sedice.com`, `quesedice.com`, `dicen.com/.io`.

Matices: "se dice" (dos palabras) nunca será poseíble en Google — "sedice" (una palabra) sí; en inglés puede leerse "se-DICE" (irrelevante mientras el foco sea LATAM). Paquete sugerido si se retoma: `sedice.io` + `sedice.co` + `loquesedice.com` ≈ $76/año.

### 5.8 Comay — DESCARTADO (riesgo reputacional)

"La Comay" es el show de chismes más visto de Puerto Rico y uno de los más tóxicos de la TV hispana: boicot 2013 (burla del asesinato de un hombre gay, salió de WAPA-TV), llamados de la Human Rights Campaign a cancelarlo, acusaciones de racismo (caso Rivera Lassén 2020) y de sexualizar la foto de una menor. Heredar esa asociación con una audiencia de mujeres millennials de marketing es inaceptable. Además "comay" es jerga caribeña, no CO/VE.

## 6. Podio al cierre de la sesión

1. **Sedice** — favorito del fundador; semántica exacta, incumbente muerto, paquete barato (§5.7).
2. **Bembify** — el más escalable/brand-safe: cumple la "regla de Spotify" de verdad (palabra inventada, radio test, 3 sílabas), raíz cultural con significado de producto (*radio bemba* = boca a boca), único con `.com`+`.io` libres (~$60 ambos).
3. **Parcera** (`parcera.io`+`tuparcera.com` ~$60) — arquetipo "amiga" ultra-colombiano, SERP limpia. Colombia-first vs pan-LATAM: si México entra pronto, **Comadre** (`comadre.io`/`lacomadre.io`) viaja mejor.
4. **La Enterada / Chismosa** — máximo fit con la audiencia validada y potencial viral en TikTok; Chismosa arriesgada para corporativos.
5. **Resuena** (`resuena.io`+`resuenahq.com`) — primer finalista, sigue válido.

Principio transversal que emergió: **nombre-persona o nombre-editorial + voz de amiga cómplice** encaja con el producto agentivo (alertas y resúmenes en primera persona) y con el tono que la audiencia validada premia.

## 7. Próximos pasos (cuando se retome)

1. Re-validar disponibilidad del candidato elegido (los snapshots caducan; los `.com` de $10 son los que vuelan primero).
2. Búsqueda de antecedentes marcarios (SIC en Colombia / SAPI en Venezuela) antes de comprar en serio.
3. Validar SERP local en `google.com.co`/`.co.ve` (las búsquedas de esta sesión fueron con SERP de EE.UU.).
4. Si el elegido es Sedice o Bembify: asegurar también el `.com.ve` vía NIC.ve (defensa en mercado core).
5. Mientras tanto: despliegue bajo el dominio de Attitude (decisión interina de arriba).
