# Telemetry ingest service

Receives SkyNetEmu telemetry (`POST /v1/events`, gzip NDJSON) and indexes it into the same Elasticsearch that Kibana uses,
as the data streams `logs-skynet.<dataset>-default`.

Reply rules: `401` bad key, `413` too large (1 MB body, 5 MB unzipped), `429` rate limited, `503` queue full, otherwise `200`
with `{"accepted":n,"rejected":m}` (invalid lines are dropped and counted, never retried by the app).

## Run

Part of `dev-env/docker-compose.yml` (`docker compose up -d --build telemetry`), port `6004` (`TELEMETRY_PORT`).
On start it registers `skynetemu-telemetry.$CF_DOMAIN` in the Cloudflare tunnel (like Kibana does; skipped without `CF_*`) and creates, idempotently: ILM `skynet-90d`, ingest pipeline `skynet-ingest`, role `skynet_ingest`, index template
`logs-skynet` (generated from `schema/v1.json`) and the Kibana data view `logs-skynet.*`.

Settings go in `dev-env/env/telemetry.env` (gitignored):

| Variable | Default | |
|---|---|---|
| `INGEST_KEYS` | empty = accept all | comma list of accepted `X-SkyNet-Key` values |
| `ES_API_KEY` | elastic user | API key limited to the `skynet_ingest` role, for writing |
| `RATE_USER_PER_HOUR` / `RATE_ADDR_PER_HOUR` | 600 / 3000 | |
| `QUEUE_MAX`, `MAX_BODY_BYTES`, `EVENTS_PATH`, `ES_REPLICAS` | 50000, 1 MB, `/v1/events`, 0 | |

Dead-lettered documents go to `/data/dead-letter.ndjson` (volume `telemetry-data`, rotated at 50 MB).
Other endpoints: `GET /healthz`, `GET /metrics` (Prometheus text).

The client address is only used as a daily-salted hash in memory; it is never logged or indexed.

## Schema

`schema/v1.json` is the single source for validation (allow-list, types, ranges, enums) and for the index template.
Add a field there and both follow. Enum values for `skynet.storage`, `skynet.exit.kind`, `skynet.error.stage` are not fixed
in the app spec, so they are checked against a pattern (`^[A-Za-z0-9_.-]{1,40}$`) only.

## Tests

`npm test` (Node 20+, no dependencies).
