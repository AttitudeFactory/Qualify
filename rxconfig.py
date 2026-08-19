import reflex as rx

config = rx.Config(
    app_name="Qualify",
    db_url="sqlite:///reflex.db",
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
