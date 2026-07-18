"""Mock mention data — stands in for the (not yet built) scraping pipeline.

Phase 1 ingestion (Zyte -> ffmpeg -> CLIP -> vision/transcription -> sentiment,
see docs/plan-ingesta-social.md) doesn't exist yet, so this dashboard MVP seeds
its own SQLite DB with plausible-looking rows to develop the UI against.
"""

import random
from datetime import datetime, timedelta

from sqlmodel import select

from .db import get_session
from .models import Mention

_BRANDS = ["Nébula Cosmetics", "Lumina Beauty"]
_PLATFORMS = ["tiktok", "instagram"]
_SENTIMENTS = ["positive", "neutral", "negative"]
_SENTIMENT_WEIGHTS = [0.55, 0.3, 0.15]
_HANDLES = [
    "@valeskincare", "@creador.beauty", "@glowwithmia", "@laura.reviews",
    "@sebasmakeup", "@dermatips_co", "@rutinasconana", "@camimakeupco",
]
_CAPTIONS = [
    "Probé la nueva línea y mi piel quedó increíble, se las recomiendo full",
    "Honestamente esperaba más por el precio que tiene",
    "Reseña sincera después de 2 semanas de uso, aquí les cuento todo",
    "Esto se volvió parte de mi rutina diaria, no puedo vivir sin él",
    "Comparando esta marca con la competencia en un video completo",
    "Mi piel reaccionó mal, tengan cuidado si tienen piel sensible",
    "El empaque es hermoso pero el producto es lo de siempre",
    "Unboxing del pedido que llegó hoy, veamos si vale la pena",
    "3 meses de uso y estos son los resultados reales, sin filtros",
    "No entiendo el hype, a mí no me funcionó como esperaba",
]


def _random_mention(brand: str) -> Mention:
    platform = random.choice(_PLATFORMS)
    posted_at = datetime.now() - timedelta(
        days=random.randint(0, 21), hours=random.randint(0, 23)
    )
    return Mention(
        brand=brand,
        platform=platform,
        post_id=f"{platform[:2]}{random.randint(10_000_000, 99_999_999)}",
        creator_handle=random.choice(_HANDLES),
        post_url="https://example.com/mock-post",
        caption=random.choice(_CAPTIONS),
        posted_at=posted_at,
        views=random.randint(500, 250_000),
        likes=random.randint(10, 20_000),
        comments_count=random.randint(0, 800),
        shares=random.randint(0, 300),
        sentiment=random.choices(_SENTIMENTS, weights=_SENTIMENT_WEIGHTS)[0],
    )


def seed_if_empty() -> None:
    """Populate the DB with mock mentions on first run only."""
    random.seed(7)
    with get_session() as session:
        already_seeded = session.exec(select(Mention.id).limit(1)).first()
        if already_seeded:
            return
        rows = [
            _random_mention(brand)
            for brand in _BRANDS
            for _ in range(30)
        ]
        session.add_all(rows)
        session.commit()
