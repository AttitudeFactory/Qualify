# Fonts shipped with `qualify_creative`

`DejaVuSans.ttf` — DejaVu Sans, Regular (https://dejavu-fonts.github.io/). License:
Bitstream Vera Fonts Copyright + public-domain DejaVu changes; free to use, modify and
redistribute, including bundled in software.

Why it is here: `compose._font` falls back to it when no brand font and no system font
is available. PIL's own default (Aileron) has no glyph for ñ, á, é, í, ó, ú, ¿ or ¡, so
on a server with no fonts every accented word printed as empty boxes (production,
2026-10-22). The deploy image also installs `fonts-dejavu-core` for the bold face.
