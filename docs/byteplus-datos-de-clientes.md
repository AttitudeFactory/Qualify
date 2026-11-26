# Qué hace BytePlus con las fotos de nuestros clientes (m-25129387)

**Estado:** investigación, 2026-11-26. Sin llamadas pagadas, sin código. Todas las fuentes son
documentos publicados por BytePlus, leídos ese día en su versión Markdown (añadiendo `.md` a la
URL de `ai.byteplus.com/ark/...`) o extrayendo el `MDContent` de las páginas legales de
`docs.byteplus.com`. Lo que no está escrito por BytePlus se marca **[no verificado]** o
**[inferencia]**. No es una opinión legal.

**Qué mandamos:** fotos de productos y del local, imágenes de personajes dibujados por IA,
indicaciones (prompts) y, para Seedance 2.x, audio/video de referencia. Base
`https://ark.ap-southeast.bytepluses.com/api/v3`. Las imágenes viajan como Base64 dentro de la
petición; videos y audios de referencia, como URL pública temporal nuestra. Llamamos a los
modelos por su identificador (`byteplus_ark.py`) y, para Seedance 2.5, por un endpoint
personalizado (`docs/modelos-generativos/seedance-2-5.md`, en el checkout principal).

## 1. Hallazgos

### 1.1 ¿Guardan lo que mandamos, y cuánto tiempo?

Por defecto, BytePlus actúa como **encargado** (*processor*) y procesa los datos «solo según las
instrucciones del cliente». Pero hay varias retenciones concretas:

| Qué | Cuánto | Fuente |
|---|---|---|
| URL del video generado | 24 h, máximo 100 descargas | [video-generation-tutorial §Retention period](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/video-generation-tutorial.md) |
| URL de la imagen generada (Seedream) | 24 h | [image-generation-api](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/image-generation-api.md) |
| ID de la tarea de video | 7 días; borradores de 2.5, 14 días. Se puede **borrar** el registro con `DELETE /contents/generations/tasks/{id}` | [video-generation-tutorial](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/video-generation-tutorial.md) |
| Archivos subidos por Files API (no la usamos) | 7 días por defecto, de 1 a 30 | [file-api](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/file-api.md) |
| Entradas y salidas que **dispara el filtro de contenido** | 180 días, en Malasia | [BytePlus_ModelArk_Data_Processing](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/BytePlus_ModelArk_Data_Processing.md) |
| Registros del filtro de contenido (si está encendido) | «Por un tiempo limitado», en Malasia o Singapur | [Content_Pre-filter](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/Content_Pre-filter.md) |
| Salidas con caras o voces analizadas por el filtro de figuras públicas | Puede guardarlas y usarlas; **no dice cuánto tiempo** | [content_pre_filter_faq](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/content_pre_filter_faq.md) |
| Datos para prevenir fraude y abuso | «Lo necesario», sin plazo | [General Terms for AI Services §3.2](https://docs.byteplus.com/en/docs/legal/AI-Services-terms) |
| Datos de soporte o diagnóstico que nosotros pidamos | «Tiempo limitado»; el servicio de diagnóstico de Seedance 2.x: hasta 3 días, más una copia sin datos identificables que se queda | [Service Specific Terms › ModelArk §4](https://docs.byteplus.com/en/docs/legal/docs-service-specific-terms), [model-diagnostic-service-acknowledgement](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/model-diagnostic-service-acknowledgement.md) |
| Al terminar el contrato | 30 días para exportar; después borran en 180 días | [DPA §8.2](https://docs.byteplus.com/en/docs/legal/docs-data-processing-addendum) |

No hay un plazo publicado para las **entradas** (fotos, prompts, audio) de una tarea normal que
no dispara el filtro **[no verificado]**. Tampoco dice si las salidas con caras se guardan 30 días
para que la plataforma las reconozca como «salidas confiables» ([seedance-portrait-asset-guide](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/seedance-portrait-asset-guide.md));
es lo esperable, pero es **[inferencia]**.

### 1.2 ¿Entrenan con nuestros datos? ¿Se puede evitar?

- **Por defecto, no.** «Salvo que te inscribas aparte, BytePlus no usará tus datos para entrenar
  modelos» ([Service Specific Terms › ModelArk §4](https://docs.byteplus.com/en/docs/legal/docs-service-specific-terms));
  igual en [General Terms for AI Services §3.3](https://docs.byteplus.com/en/docs/legal/AI-Services-terms)
  y en [Data Processing](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/BytePlus_ModelArk_Data_Processing.md).
- **La excepción es la «Colaboración de datos».** Es un programa que se activa **por endpoint y
  por modelo** a cambio de tokens gratis. Con él, las entradas y salidas de esos endpoints (dentro
  de la cuota gratuita diaria) se ceden **para siempre**, con licencia irrevocable, sublicenciable
  y transferible a BytePlus, sus filiales y terceros socios, y pueden guardarse fuera de la región
  ([collaboration-reward-program §3.2 y Data Authorization Agreement §2.1–2.3](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/collaboration-reward-program.md)).
  La autorización **se puede retirar** en la consola, pero lo ya cedido no se borra.
  Esto es lo que los documentos internos llaman «preajustes que ceden datos».
- Lo comprobado en casa: el 2026-11-12 el fundador revisó la consola y confirmó que **Seedream 5.0
  pro y 5.0 lite no ceden datos** (`docs/modelos-generativos/pruebas.md`, «STICKERS-KAWAII-000»).
  Seedance 2.5 va por un endpoint personalizado. **No sabemos** si algún otro endpoint de la
  cuenta (Seedream 5.0 flash, Seedance 2.0, OmniHuman, Seed Speech) sigue inscrito
  **[no verificado]**. Seedance 2.x no está en la lista de modelos que salieron del programa el
  2026-10-08, así que es probable que pueda seguir inscrito.

### 1.3 ¿Dónde se procesan los datos del endpoint `ap-southeast`?

- `ap-southeast-1` es **Johor, Malasia** ([region-availability](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/region-availability.md)).
- El procesamiento puede ocurrir en **Malasia, Indonesia y/o la UE/EEE**
  ([Data Processing](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/BytePlus_ModelArk_Data_Processing.md)),
  y una petición a AP puede «desbordarse» a la región de la UE si hace falta
  ([region-availability](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/region-availability.md)).
- La contratante es BytePlus Pte. Ltd. (Singapur). Pueden pasar datos a sus filiales y
  subencargados, con 15 días de aviso para cambios ([DPA §6–7, Anexo D](https://docs.byteplus.com/en/docs/legal/docs-data-processing-addendum)).
  La [lista de subencargados](https://docs.byteplus.com/en/docs/legal/sub-processors-list)
  no menciona ninguno de terceros para ModelArk.
- **China:** solo aparece si pedimos el servicio de diagnóstico de Seedance 2.x; en ese caso los
  datos de esas tareas pueden ir a la República Popular China
  ([model-diagnostic-service-acknowledgement](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/model-diagnostic-service-acknowledgement.md)).
- Contradicción menor: el contenido que dispara el filtro está «en Malasia» según una página y
  «en Malasia o Singapur» según otra.

### 1.4 Caras reales y uso comercial

- **Caras reales:** Seedance 2.x **rechaza** imágenes o videos de referencia con caras humanas
  reales. Hay tres caminos permitidos: personajes digitales de la biblioteca, salidas propias de
  Seedance 2.x o de Seedream 5.0 texto-a-imagen (misma cuenta, menos de 30 días, sin editar) o
  activos de una persona real que verificó su identidad con su propia cuenta
  ([seedance-portrait-asset-guide](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/seedance-portrait-asset-guide.md),
  [upload-real-person-portrait-assets](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/upload-real-person-portrait-assets.md)).
  Un personaje dibujado con **otra** herramienta, editado, o con más de 30 días, puede ser
  bloqueado.
- Somos responsables de tener los derechos sobre la imagen, la voz y la apariencia de cualquier
  persona que mandemos ([AI Terms §1.2, §1.8](https://docs.byteplus.com/en/docs/legal/AI-Services-terms)).
  El filtro bloquea salidas que se parezcan a figuras públicas
  ([content_pre_filter_faq](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/content_pre_filter_faq.md)).
- **Uso comercial:** la salida es nuestra (de nuestro cliente), sin garantía de originalidad.
  BytePlus nos defiende si se reclama que la salida infringe derechos de autor, con excepciones:
  marcas, salidas modificadas o combinadas con otros datos, y modelos «Preview»
  ([AI Terms §2](https://docs.byteplus.com/en/docs/legal/AI-Services-terms),
  [Service Specific Terms › Model Services §3](https://docs.byteplus.com/en/docs/legal/docs-service-specific-terms)).
  Los personajes de la biblioteca llevan etiquetas propias («solo uso no comercial» o «uso
  comercial permitido»). Durante el periodo gratuito solo se permite uso no comercial
  ([copyright_and_portrait_feature_usage_rules](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/copyright_and_portrait_feature_usage_rules.md)).
- **Etiqueta de contenido sintético:** hay que cumplir las leyes de etiquetado
  ([AI Terms §1.4](https://docs.byteplus.com/en/docs/legal/AI-Services-terms)). Mandamos
  `watermark: false`, así que la etiqueta de IA la ponemos nosotros al publicar.

### 1.5 Dos cláusulas que no estaban en el radar

1. **«Platform Customer»** ([Service Specific Terms › Model Services §4.2](https://docs.byteplus.com/en/docs/legal/docs-service-specific-terms)).
   Esta categoría se aplica a quien integra las API de video en su plataforma y las pone a
   disposición de otras empresas, y **Qualify encaja ahí** **[inferencia]**. Lo que exige:
   verificar la identidad de los usuarios finales, tener un proceso de respuesta a incidentes,
   manejo escalonado de infracciones con registros completos, y verificar y conservar los
   derechos sobre lo que sube el usuario, incluidas imágenes de personas reales. Además, **no se
   permite integrarlo en plataformas de contenido generado por usuarios, «incluidas herramientas de
   creación de contenido con IA»**, y en un agregador el usuario final solo puede generar video
   «para su propio uso». La penalidad es el 10 % de lo contratado en video, o el 20 % del
   compromiso mínimo si se considera reventa.
   Si Qualify cuenta como «herramienta de creación de contenido con IA» es una pregunta para
   BytePlus por escrito.
2. **Países:** el [listado de países disponibles](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/availability.md)
   (actualizado el 2026-04-21) incluye **Colombia y Uruguay, pero no Venezuela**. Los términos
   dicen que ese listado también vale para nuestros usuarios finales
   ([Model Services §2(1)](https://docs.byteplus.com/en/docs/legal/docs-service-specific-terms)).

## 2. Qué aplica en Uruguay y Colombia (para revisar con un abogado)

- **Las fotos del local con gente** (empleados o clientes que se ven) y las voces son datos
  personales. Una foto de producto sola normalmente no lo es **[inferencia]**.
- **Roles:** el negocio es responsable de los datos; Qualify es encargado y BytePlus,
  subencargado. Nuestro contrato o términos con el cliente debería nombrar a BytePlus como
  subencargado y decir para qué se usa.
- **Uruguay, Ley 18.331:** pide consentimiento informado y avisar de la finalidad (art. 9 y 13).
  La transferencia internacional a países sin nivel adecuado exige consentimiento o garantías
  contractuales (art. 23). Malasia e Indonesia figuran como «adecuados» ante la URCDP
  **[no verificado]**. El DPA de BytePlus trae cláusulas tipo para la UE y Brasil, pero no para
  Uruguay.
- **Colombia, Ley 1581 de 2012 y Decreto 1377 de 2013:** el aviso de privacidad y la
  autorización deben cubrir el envío al exterior. Para pasar datos a un encargado en el exterior
  hace falta un **contrato de transmisión** (Decreto 1377, art. 25) **[no verificado el número
  de artículo]**. Si la cara se usa para reconocer a alguien, es un dato **biométrico sensible**
  (art. 5–6). También queda pendiente ver si aplica el registro de bases de datos ante la SIC.
- **Venezuela:** no hay ley general de datos personales comparable **[no verificado]**. El
  obstáculo es el contrato con BytePlus (§1.5.2), no una ley local.
- **Lo mínimo que hay que decirle al cliente:** que sus fotos, textos y audios se envían a
  BytePlus (Singapur), que se procesan en Malasia, Indonesia o la UE, que no se usan para
  entrenar, que pueden quedar hasta 180 días si el filtro de seguridad los marca, que lo generado
  es contenido sintético y se etiqueta como tal, y que el negocio debe tener permiso de toda
  persona reconocible en lo que suba.

## 3. Riesgos

| Riesgo | Gravedad | Mitigación |
|---|---|---|
| Algún endpoint de la cuenta sigue en la Colaboración de datos y le llegan datos de clientes → cesión perpetua e irreversible | Alta | Revisar la consola de cada modelo que usamos y usar endpoints `ep-…` propios para todo lo que lleve datos de clientes |
| Qualify cuenta como «herramienta de creación de contenido con IA» según §4.2 → suspensión de la cuenta y multa | Alta, puerta de una vía | Preguntar a BytePlus por escrito antes de abrir el servicio a clientes que el fundador no administra |
| Clientes en Venezuela fuera de los países disponibles | Media | Confirmar con BytePlus; mientras tanto, no generar para tenants de Venezuela |
| Personaje de otra herramienta, editado o con más de 30 días → bloqueado | Media (de producto) | Generar el personaje con Seedream 5.0 en la misma cuenta y volver a generarlo antes de 30 días, o usar la biblioteca con etiqueta comercial |
| Pedir un diagnóstico sobre una tarea de cliente → datos a China | Media | Regla: nunca pedir diagnóstico con tareas que lleven datos de clientes |
| No hay plazo publicado para las entradas normales | Baja-media | Preguntarlo; borrar la tarea con `DELETE` después de descargar (el adaptador hoy no lo hace) |

## 4. Qué falta confirmar con BytePlus (por escrito, vía ticket o su representante)

1. ¿Una plataforma SaaS donde pequeños negocios generan videos de **sus propios** productos para
   **sus propias** redes es «Platform Customer», y entra en la prohibición de «herramientas de
   creación de contenido con IA» de §4.2.3? ¿Qué hace falta para estar permitido?
2. ¿Pueden nuestros usuarios finales estar en **Venezuela**?
3. ¿Cuánto tiempo guardan las entradas (imágenes, prompts, audio de referencia) de una tarea que
   **no** dispara el filtro? ¿El `DELETE` de la tarea borra también las entradas y salidas?
4. ¿Cuánto tiempo guarda el filtro de figuras públicas las salidas con caras, y dónde?
5. ¿Ofrecen un anexo de transferencia para Colombia y Uruguay (o aceptan el nuestro)?
6. Confirmación de la consola: ningún endpoint de Seedance, Seedream, OmniHuman o Seed Speech de
   nuestra cuenta está en la Colaboración de datos (captura con fecha).

## 5. Recomendación para encender el personaje con clientes

**Sí, de forma escalonada**, con cuatro condiciones previas:

1. **Captura de la consola** (fundador): ningún modelo que reciba datos de clientes está en la
   Colaboración de datos. Lo ideal es que todos vayan por un endpoint `ep-…` propio y que se
   guarde la captura junto a este documento.
2. **El personaje sale de Seedream 5.0 pro en nuestra cuenta**, sin editar, y se vuelve a generar
   antes de 30 días. No usar caras reales ni personajes de otras herramientas.
3. **Cláusula en los términos y el aviso de privacidad** con lo mínimo de §2, más la
   confirmación del negocio de que tiene permiso de las personas reconocibles que sube.
4. **Regla interna:** no pedir diagnóstico sobre tareas de clientes.

Con eso se puede encender **para los negocios que administra el fundador en Colombia y
Uruguay**. Para clientes externos y para Venezuela, esperar las respuestas 1 y 2 de §4: es una
puerta de una vía, porque el riesgo es perder la cuenta y pagar una penalidad.
