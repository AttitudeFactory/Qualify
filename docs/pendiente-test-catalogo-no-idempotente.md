# Pendiente: `test_catalog_roundtrip_and_isolation` no es idempotente en local

**Detectado:** 2026-10-10, durante la revisión del PR #100 (generador de contenido).
**Dónde vive:** `packages/api/tests/test_catalog_service_db.py` (marcado `db`).
**Origen:** el test llegó con el motor de plantillas Remotion (commit `debf604`, ya en `main`).
**Por qué no entra en el PR #100:** es deuda del catálogo, no del generador. Se deja aquí para
abrir su propio ticket.

## Síntoma

`just test-db` (o `pytest -m db`) pasa en la **primera** ejecución contra una `qualify_test`
recién creada y falla en **todas las siguientes** contra la misma base, siempre con el mismo
test:

```
FAILED packages/api/tests/test_catalog_service_db.py::test_catalog_roundtrip_and_isolation
AssertionError: assert {'shawarma-mixto', 'shawarma-mixto-2'} <= {'shawarma-mixto', ..., 'shawarma-mixto-6'}
```

## Causa

El test asume una marca vacía:

1. La fixture `seeded` reutiliza el tenant `a0000000-…-00c1` y la marca `catalog-svc-brand-A`
   entre ejecuciones (los crea solo si no existen) y nunca borra lo que el test deja.
2. El test crea dos productos con el mismo nombre, `Shawarma mixto`, y espera los slugs
   `shawarma-mixto` y `shawarma-mixto-2`.
3. Al final desactiva el segundo (`is_active=False`).
4. En la siguiente ejecución `CatalogService.create_product` ve ocupados `shawarma-mixto` y `-2`
   y asigna `-3` y `-4`. El test lista solo productos **activos**; `-2` está inactivo, así que ya
   no aparece y la aserción cae. Cada pasada sube el sufijo.

No es un defecto del servicio: repetir un nombre dentro de una marca debe producir `-2`, `-3`…

## Alcance

- **Local:** falla a partir de la segunda pasada sobre la misma `qualify_test`.
- **CI:** nunca falla. El job `test-db` levanta un Postgres nuevo en cada ejecución.
- **Producción:** no aplica; es un test.

Verificado el 2026-10-10 en Windows:

| Pasada | Resultado |
|---|---|
| Suite `db` completa, base recreada | 385 passed |
| Suite `db` completa, segunda vez sobre la misma base | 384 passed, 1 failed (este) |
| Suite `db` completa sin este test, base tal cual | 384 passed |
| Este test solo, base recreada | 1 passed |

## Remedio local mientras no se arregle

```bash
just test-db-reset
```

o `pytest --reset-test-db -m db`. Ambos recrean solo `qualify_test`, nunca la base de
desarrollo `qualify`. Alternativa quirúrgica: borrar los productos `shawarma-mixto%` de la marca
`catalog-svc-brand-A` en `qualify_test`.

## Arreglo propuesto (probado, no aplicado)

Nombre único por ejecución y slugs esperados derivados de él con `slugify`. Misma aserción, sin
asumir una marca vacía. Con este cambio el test pasó tres veces seguidas sobre la misma base y la
suite `db` completa pasó dos veces seguidas (385/385 ambas).

```diff
--- a/packages/api/tests/test_catalog_service_db.py
+++ b/packages/api/tests/test_catalog_service_db.py
@@
-from qualify_api.catalog.service import CatalogError, CatalogService, UnknownProduct
+from qualify_api.catalog.service import CatalogError, CatalogService, UnknownProduct, slugify
@@
     service = CatalogService(store=LocalMediaStore(tmp_path))
+    # The seeded brand outlives the test run and this test deactivates one of its
+    # products, so a name reused across runs made the second run's slugs `-3`/`-4` and
+    # the assertion below fail against a non-fresh `qualify_test`. A name unique to the
+    # run keeps the assertion exact without assuming an empty brand.
+    name = f"Shawarma mixto {uuid4().hex[:6]}"
+    base = slugify(name)

     product_id = service.create_product(
         tenant_id=tenant_a,
         brand_id=brand_a,
         user_id=user_a,
-        name="Shawarma mixto",
+        name=name,
         price_amount=Decimal("5.00"),
         price_currency="usd",
         category="shawarma",
         tags=("picante", ""),
     )
-    twin = service.create_product(
-        tenant_id=tenant_a, brand_id=brand_a, user_id=user_a, name="Shawarma mixto"
-    )
+    twin = service.create_product(tenant_id=tenant_a, brand_id=brand_a, user_id=user_a, name=name)
     products = service.list_products(tenant_id=tenant_a, brand_id=brand_a)
     slugs = {p.slug for p in products}
-    assert {"shawarma-mixto", "shawarma-mixto-2"} <= slugs
+    assert {base, f"{base}-2"} <= slugs
```

Alternativa más débil: listar con `include_inactive=True` en esa aserción. Pasa, pero deja de
comprobar que el `-2` es el de **esta** ejecución.

Opcional, para no acumular filas: que la fixture `seeded` borre al final los productos que el
test creó (`brand_products` tiene `ON DELETE CASCADE` hacia `product_media`, verificado por
`test_deleting_a_product_cascades_to_its_media`).
