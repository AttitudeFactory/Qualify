---
name: qualify-copy-es
description: Rules for any text a Qualify client will read — screen labels, buttons, errors, empty states, emails, WhatsApp/DM messages, Meegle-to-client notices. Plain neighborly Spanish for small-business owners in Colombia, Venezuela and Uruguay, no English words, no slang. Use whenever writing or reviewing user-facing strings.
---

# Qualify — writing for clients

Clients are owners of small businesses (a shawarma shop, a frozen-yogurt shop, a realtor, a
travel agency). They read on their phones, between other tasks.

## Rules

1. **Spanish only — no English words**, even common ones: «publicación» (not post), «historia»
   (story), «conversaciones» o «chats» (inbox), «descargar», «programar», «borrador»,
   «identidad de marca» (not Brand Kit in new client-facing copy), «anuncio» (ad).
2. **No slang and no regionalisms** that only one country uses; plain and neighborly («tú»),
   never corporate.
3. **Say what happens and what to do next.** An error names the problem in the client's terms
   and the next step: «No pudimos publicar porque Instagram pidió volver a conectar la cuenta.
   Conéctala de nuevo en Cuentas conectadas.» Never a stack trace, an HTTP code or an internal id.
4. **Short:** one idea per sentence; buttons are verbs («Publicar», «Aprobar», «Regenerar»).
5. **Money and dates** in the tenant's currency and timezone; prices whole or not at all.
6. **Never promise what the product does not do** (autonomous replies, TikTok scheduling).
7. Code, identifiers and comments stay in English — only the strings change language.

## Before you finish

Read every new string aloud as the client: would a bakery owner understand it without asking?
For screens, also run the `design:ux-copy` skill.
