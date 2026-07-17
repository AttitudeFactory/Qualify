import reflex as rx

config = rx.Config(
    app_name="Qualify",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ]
)