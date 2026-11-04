"""Clients of the paid data vendors Qualify buys from (ADR 34, ADR 42 §4).

`scrapecreators` is the ScrapeCreators client every caller goes through — the Brand Kit
read, the referentes search, the avatar refresh and «Descubrir reels»
(`qualify_api.referentes.reels`); `scrapecreators_trending` reads the vendor's global
trending catalogs for the Stories screen. Moved here from `qualify_api.referentes` and
`Qualify/` by ADR 42 R1 (m-24854844), unchanged, so a `qualify_api` worker can use them;
the metered gate of ADR 42 R2 lands on `scrapecreators`.
"""
