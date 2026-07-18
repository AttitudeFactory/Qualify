import reflex as rx

config = rx.Config(
    app_name="Qualify",
    db_url="sqlite:///reflex.db",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(accent_color="violet", radius="medium")
        ),
    ],
)