import reflex as rx

# `api_url` / `deploy_url` are deliberately NOT set here: Reflex reads every Config field from
# a `REFLEX_<FIELD>` env var, so local dev keeps the localhost defaults while production sets
# REFLEX_API_URL / REFLEX_DEPLOY_URL to the public origin (deploy/docker-compose.prod.yml, and
# as a build arg for the static frontend export in deploy/Dockerfile). Frontend, backend and
# FastAPI share that one origin behind Caddy, so no `cors_allowed_origins` is needed either.
config = rx.Config(
    app_name="Qualify",
    db_url="sqlite:///reflex.db",
    # Bug reported 2026-08-25: the sticky "Built with Reflex" badge is dev-tooling
    # branding, not something a shipped product screen should show.
    show_built_with_reflex=False,
    # Local dev secrets (Meta OAuth, R2) live in .env, gitignored, never committed — see
    # its own header comment. Reflex only loads a dotenv file when told to; without this,
    # every setting that reads os.environ (MetaOAuthSettings.from_env, R2Settings.from_env)
    # silently sees nothing and fails as "not configured" even though the file is right
    # there. Harmless if .env is absent (e.g. CI) — Reflex skips a missing env_file.
    env_file=".env",
    plugins=[
        rx.plugins.SitemapPlugin(),
        # The visual identity is a theme decision, made once here (docs/design-system.md §3):
        # teal accent (far from the semantic grass/amber/tomato and from the platform
        # colours), slate gray (cool neutral that keeps green unambiguous), medium radius.
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                accent_color="teal",
                gray_color="slate",
                radius="medium",
                scaling="100%",
                panel_background="solid",
            )
        ),
    ],
)
