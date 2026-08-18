# qualify-creative

Pure core of the Brand Content Engine — see `docs/diseno-motor-contenido-marca.md`.

Holds the contracts (`schemas`), the vendor-agnostic seam (`providers`), the deterministic
prompt renderer and the brand-fidelity gate. No database, no HTTP, no vendor SDK at import
time: stateful concerns live in `qualify_api.creative`, and adapters are imported lazily.
