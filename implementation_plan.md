# Implementation Plan: Init Deployed-Previews Index Workflow

## Goal

- Add a Kibana workflow that initializes the `deployed-previews` Elasticsearch index
- Index stores one document per active preview environment with the fields below
- Workflow runs in the local dev-env Kibana (uses `elasticsearch.*` step types)
- `deploy-kibana-preview` workflow writes/upserts a document to this index after each successful deployment

---

## Index Mappings

| Field | ES type | Notes |
|-------|---------|-------|
| `@timestamp` | `date` | time the document was first created |
| `updated_at` | `date` | time the document was last updated |
| `target` | `keyword` | the GitHub URL passed as `kibana_target` input |
| `port` | `integer` | Kibana port assigned by `assign_ports` |
| `public_url` | `keyword` | full Cloudflare public URL (or empty string) |
| `container_name` | `keyword` | Docker Compose project name (`$PROJECT`) |
| `deploy_dir_name` | `keyword` | deployment directory name (`$PROJECT`) |

---

## Scope of Changes

| File | Change | Summary |
|------|--------|---------|
| `dev-env/workflows/init_deployed_previews_index.yaml` | add | new workflow: delete-if-exists + create index with mappings |
| `dev-env/workflows/deploy-kibana-preview.yaml` | modify | add `index_deployment` step that upserts a doc after start |

**2 files total — 1 modify, 1 add.**

---

## Files to Change

### 1. `dev-env/workflows/init_deployed_previews_index.yaml`

New workflow, placed alongside `deploy-kibana-preview.yaml` in `dev-env/workflows/`.

Uses `elasticsearch.request` (no connector needed — uses Kibana's internal ES client).

Steps:
1. `check_index` — `elasticsearch.request` `HEAD /deployed-previews`; captures status in output
2. `create_index` — `if` step: if index does not exist → `elasticsearch.request` `PUT /deployed-previews` with mappings; else `console` log "index already exists, skipping"

```yaml
- name: create_index
  type: if
  with:
    condition: '{{ steps.check_index.output.status == 404 }}'
    then:
      - name: put_index
        type: elasticsearch.request
        with:
          method: PUT
          path: /deployed-previews
          body:
            mappings:
              properties:
                '@timestamp':   { type: date }
                updated_at:     { type: date }
                target:         { type: keyword }
                port:           { type: integer }
                public_url:     { type: keyword }
                container_name: { type: keyword }
                deploy_dir_name: { type: keyword }
    else:
      - name: skip
        type: console
        with:
          message: 'Index deployed-previews already exists — skipping.'
```

Trigger: `manual` only.

### 2. `dev-env/workflows/deploy-kibana-preview.yaml`

Add `index_deployment` step after `start` (or after `wait_for_kibana`) with:
- `type: remoteHost.runCommand`
- `on-failure: continue: true` (index failure must not block deployment)
- Uses `curl` to call the Kibana API on `localhost:KIBANA_PORT` to upsert a document into `deployed-previews` with `_id=$PROJECT`

---

## Gaps / Open Questions

### ~~G1~~ — Idempotency strategy: **skip if already exists** ✓

If the index already exists, the workflow logs a message and exits without modifying it. Step structure becomes: `check_index` → `if exists: log_skip / else: create_index`.

### ~~G2~~ — `container_name` and `deploy_dir_name` are intentionally separate fields ✓

Both map to `$PROJECT` today but are kept as distinct fields by design.

### ~~G3~~ — `deploy-kibana-preview` will upsert a document after each deployment ✓

Confirmed in scope. The `index_deployment` step is included (see Files to Change §2).

### ~~G4~~ — No connector needed ✓

`elasticsearch.request` uses Kibana's internal ES client directly. Step shape: `method`, `path`, `body`.

### ~~G5~~ — Field renamed to `public_url`, stores full URL ✓

Renamed from `public_host` → `public_url`. Stores the full `KIBANA_PUBLIC_URL` value (e.g. `https://subdomain.domain`).
