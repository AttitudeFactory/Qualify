-- m-24854495: READ-ONLY export of real comment texts for the sentiment golden set.
-- NEEDS THE FOUNDER'S APPROVAL before it runs: it reads production. Never run by an agent.
--
-- What leaves the database: the comment text (already masked here: @mentions, e-mails,
-- links and phone numbers), the business name, its country and whether it is a comment
-- or a mention. NO usernames, ids, timestamps, media ids or permalinks.
-- `sentiment_kit.py anonymize` masks the text a second time on the laptop.
--
-- Run (from the Mac, output lands OUTSIDE the repo):
--
--   mkdir -p ~/qualify-eval-data/sentiment/raw && chmod 700 ~/qualify-eval-data
--   ssh qualify-prod 'cd /opt/qualify/current && docker compose \
--       --env-file /opt/qualify/.env.prod \
--       $(test -f deploy/release.env && echo --env-file deploy/release.env) \
--       -f deploy/docker-compose.prod.yml exec -T \
--       -e PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=60000" \
--       postgres psql -U qualify_owner -d qualify -X -q -v ON_ERROR_STOP=1 \
--       -v tenants=bianki,puntoservis,<inmobiliaria>,<agencia> -f -' \
--     < packages/api/evals/replies_ai/export_real_comments.sql \
--     > ~/qualify-eval-data/sentiment/raw/comments-$(date +%Y%m%d).csv
--
-- `tenants` = lower-case substrings of the tenant names to include (comma separated, no
-- spaces: «inmobiliaria», not «inmobiliaria x»).
-- Step 0 below prints the candidate tenants and their counts (no text) to stderr, so the
-- founder can check the names before trusting the file.
-- `default_transaction_read_only=on` makes any write in this session fail.

\set ON_ERROR_STOP on

-- Step 0: which tenants match, and how many usable comments each has (stderr, no text).
\o /dev/stderr
SELECT t.name, t.country, count(*) AS comments
  FROM messages m
  JOIN threads th ON th.id = m.thread_id AND th.tenant_id = m.tenant_id
  JOIN tenants t ON t.id = m.tenant_id
 WHERE th.channel = 'comment'
   AND m.direction = 'inbound'
   AND m.deleted_at IS NULL
   AND coalesce(btrim(m.text), '') <> ''
   AND lower(t.name) LIKE ANY (
         SELECT '%' || btrim(x) || '%' FROM unnest(string_to_array(:'tenants', ',')) AS x)
 GROUP BY 1, 2
 ORDER BY 3 DESC;
\o

-- Step 1: the texts, as CSV on stdout.
COPY (
  WITH picked AS (
    SELECT t.name AS business, t.country, 'comment' AS kind, m.text
      FROM messages m
      JOIN threads th ON th.id = m.thread_id AND th.tenant_id = m.tenant_id
      JOIN tenants t ON t.id = m.tenant_id
     WHERE th.channel = 'comment'
       AND m.direction = 'inbound'
       AND m.deleted_at IS NULL
       AND coalesce(btrim(m.text), '') <> ''
       AND lower(t.name) LIKE ANY (
             SELECT '%' || btrim(x) || '%' FROM unnest(string_to_array(:'tenants', ',')) AS x)
    UNION ALL
    SELECT t.name, t.country, 'mention', coalesce(mn.text, mn.caption)
      FROM mentions mn
      JOIN tenants t ON t.id = mn.tenant_id
     WHERE mn.removed_at IS NULL
       AND coalesce(btrim(coalesce(mn.text, mn.caption)), '') <> ''
       AND lower(t.name) LIKE ANY (
             SELECT '%' || btrim(x) || '%' FROM unnest(string_to_array(:'tenants', ',')) AS x)
  ),
  masked AS (
    SELECT business, country, kind,
           regexp_replace(
             regexp_replace(
               regexp_replace(
                 regexp_replace(text, '[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}',
                                '[correo]', 'g'),
                 '(https?://|www\.)[^[:space:]]+', '[enlace]', 'g'),
               '@[[:alnum:]._]+', '@usuario', 'g'),
             '\+?[0-9][0-9 ().-]{6,}[0-9]', '[teléfono]', 'g') AS text
      FROM picked
  )
  SELECT DISTINCT business, country, kind, text FROM masked ORDER BY business, kind, text
) TO STDOUT WITH (FORMAT csv, HEADER true);
