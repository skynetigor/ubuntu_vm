# Implementation Plan — Workflows UI Webapp

## Goal

- Build a **self-contained webapp** (`webapp/`) that acts as a purpose-built UI for the Kibana Workflows system, replacing the need to navigate raw Kibana
- Expose a **JWT-authenticated Express proxy** that forwards requests to the main Kibana and ES with the operator's credentials, so the browser never holds ES passwords
- Provide a **workflows page** per workflow: run with auto-generated input form, live execution list with status streaming
- Provide a **deployments page** showing all preview environments with one-click Kibana access and credentials reveal
- Provide a **benchmark reports page** with per-report stats and a side-by-side comparison view with overlaid throughput charts
- Run as a **Docker service** in the existing `dev-env` stack, registered in the Cloudflare tunnel under a fixed subdomain

---

## Target Directory Layout

```
webapp/
├── Dockerfile                  # multi-stage: ng build → Express serve
├── entrypoint.sh               # tunnel registration + app start
├── scripts/
│   └── register-tunnel.sh      # copied from kibana/scripts (same script)
├── backend/
│   ├── package.json
│   └── src/
│       ├── index.js            # Express entry, mounts routes, serves Angular dist
│       ├── middleware/
│       │   └── auth.js         # JWT verify, extract ES credentials, attach to req
│       └── routes/
│           ├── auth.js         # POST /api/auth/login, GET /api/auth/me
│           ├── workflows.js    # GET /api/workflows, GET /api/workflows/:id
│           ├── executions.js   # POST /api/workflows/:id/run, GET …/executions, GET /api/executions/:id
│           ├── deployments.js  # GET /api/deployments, GET /api/deployments/:id/credentials, DELETE /api/deployments/:id
│           └── benchmarks.js   # GET /api/benchmarks, GET /api/benchmarks/:id
└── frontend/
    ├── angular.json
    ├── package.json
    └── src/
        ├── main.ts
        ├── app/
        │   ├── app.config.ts
        │   ├── app.routes.ts
        │   ├── core/
        │   │   ├── auth.service.ts       # login, JWT storage, HTTP interceptor
        │   │   ├── api.service.ts        # typed wrappers around /api/*
        │   │   └── auth.guard.ts
        │   ├── pages/
        │   │   ├── login/
        │   │   ├── workflows/
        │   │   │   ├── workflows-layout/    # shell with left-nav
        │   │   │   ├── workflow-detail/     # run button + execution list
        │   │   │   └── execution-detail/    # step tree drawer
        │   │   ├── deployments/
        │   │   └── benchmarks/
        │   │       ├── benchmark-list/
        │   │       ├── benchmark-detail/
        │   │       └── benchmark-compare/
        │   └── shared/
        │       ├── status-badge/
        │       ├── run-dialog/            # auto-generated input form
        │       └── duration-pipe.ts
        └── environments/
            ├── environment.ts
            └── environment.prod.ts

dev-env/
├── docker-compose.yml           # add workflows-ui service  [MODIFY]
└── env/
    └── webapp.env               # optional env overrides template  [ADD]
```

---

## New Environment Variables

| Var | Default | Meaning |
|---|---|---|
| `WEBAPP_PORT` | `5000` | Host port for the webapp container |
| `JWT_SECRET` | _(required)_ | HS256 signing secret; must be set before the container starts |
| `ES_HOST` | `http://elasticsearch:9200` | ES base URL reachable from within the Docker network |
| `KIBANA_HOST` | `http://kibana:5601` | Kibana base URL reachable from within the Docker network |
| `CF_SUBDOMAIN` | `workflows-ui` | Fixed Cloudflare subdomain for the webapp |
| `CF_SERVICE_URL` | `http://workflows-ui:5000` | Tunnel ingress target (container-network address) |

`JWT_SECRET` resolution in `entrypoint.sh`:
```bash
: "${JWT_SECRET:?JWT_SECRET must be set}"
```

All other CF vars (`CF_API_TOKEN`, `CF_ACCOUNT_ID`, etc.) are already present in `dev-env/env/cloudflare.env` and passed through to the container.

---

## Scope of Changes

| File | Change | Summary |
|---|---|---|
| `webapp/Dockerfile` | add | Multi-stage: build Angular then copy dist + backend into Node 20 slim |
| `webapp/entrypoint.sh` | add | Calls register-tunnel.sh, then `node src/index.js` |
| `webapp/scripts/register-tunnel.sh` | add | Copied verbatim from `kibana/scripts/register-tunnel.sh` |
| `webapp/backend/package.json` | add | express, jsonwebtoken, http-proxy-middleware, cors |
| `webapp/backend/src/index.js` | add | Express app: mounts routes, serves Angular dist as SPA fallback |
| `webapp/backend/src/middleware/auth.js` | add | JWT verify; extracts `{username, password}` and attaches to req |
| `webapp/backend/src/routes/auth.js` | add | Login: validates creds against ES `/_security/_authenticate`, returns JWT |
| `webapp/backend/src/routes/workflows.js` | add | Proxies workflow list/detail to Kibana; adds per-execution summary |
| `webapp/backend/src/routes/executions.js` | add | Proxies run + execution list/detail to Kibana |
| `webapp/backend/src/routes/deployments.js` | add | Reads `deployed-previews` index; credentials reveal; delete via workflow trigger |
| `webapp/backend/src/routes/benchmarks.js` | add | Reads `workflow-benchmarks` index; single report; comparison |
| `webapp/frontend/` _(Angular project)_ | add | Angular 18 CLI project with PrimeNG + PrimeFlex |
| `dev-env/docker-compose.yml` | modify | Add `workflows-ui` service on port `${WEBAPP_PORT:-5000}:5000` |
| `dev-env/env/webapp.env` | add | Optional env-override template (commented out with defaults) |
| `dev-env/workflows/cleanup-preview.yaml` | add | Workflow with `project` input: full teardown of a single preview |
| `dev-env/workflows/cleanup-expired-previews.yaml` | add | Scheduled workflow (10 min): fetches expired previews, delegates to cleanup-preview |
| `kibana/scripts/deregister-tunnel.sh` | add | Removes CF tunnel ingress rule + DNS CNAME for a given subdomain |

**17 files total — 1 modify, 16 add.**

---

## Files to Change

### 1. `dev-env/docker-compose.yml`

Add after the `apm-server` service, before the `cloudflared` service:

```yaml
  workflows-ui:
    build:
      context: ../webapp
    container_name: workflows-ui
    ports:
      - '${WEBAPP_PORT:-5000}:5000'
    environment:
      ES_HOST: http://elasticsearch:9200
      KIBANA_HOST: http://kibana:5601
      CF_SUBDOMAIN: workflows-ui
      CF_SERVICE_URL: http://workflows-ui:5000
    env_file:
      - path: ./env/cloudflare.env
        required: false
      - path: ./env/webapp.env
        required: false
    networks:
      - elastic
    depends_on:
      elasticsearch:
        condition: service_healthy
```

`JWT_SECRET` goes in `dev-env/env/webapp.env` (required, not defaulted).

---

### 2. `webapp/Dockerfile`

```dockerfile
# Stage 1 — build Angular
FROM node:20-slim AS ng-build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build -- --configuration production

# Stage 2 — runtime
FROM node:20-slim
WORKDIR /app
COPY backend/package*.json ./
RUN npm ci --omit=dev
COPY backend/src ./src
COPY --from=ng-build /build/frontend/dist/frontend/browser ./public
COPY entrypoint.sh scripts/ /app/scripts/
RUN chmod +x /app/scripts/entrypoint.sh /app/scripts/register-tunnel.sh
EXPOSE 5000
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
```

---

### 3. `webapp/entrypoint.sh`

```bash
#!/bin/bash
set -euo pipefail
: "${JWT_SECRET:?JWT_SECRET must be set}"
bash /app/scripts/register-tunnel.sh || true   # non-fatal; CF creds may be absent
exec node /app/src/index.js
```

---

### 4. `webapp/scripts/register-tunnel.sh`

Copy verbatim from `kibana/scripts/register-tunnel.sh`. No modifications needed — it reads the same CF env vars and the `CF_SUBDOMAIN` / `CF_SERVICE_URL` overrides set in the compose environment block.

---

### 5. `webapp/backend/package.json`

```json
{
  "name": "workflows-ui-backend",
  "version": "1.0.0",
  "type": "module",
  "scripts": { "start": "node src/index.js" },
  "dependencies": {
    "cors": "^2.8.5",
    "express": "^4.19.0",
    "http-proxy-middleware": "^3.0.0",
    "jsonwebtoken": "^9.0.0"
  }
}
```

---

### 6. `webapp/backend/src/index.js`

- Instantiates Express app, mounts:
  - `POST /api/auth/login` — public (no auth middleware)
  - `GET /api/auth/me` — protected
  - `/api/workflows` — protected, `routes/workflows.js`
  - `/api/executions` — protected, `routes/executions.js`
  - `/api/deployments` — protected, `routes/deployments.js`
  - `/api/benchmarks` — protected, `routes/benchmarks.js`
- Serves `./public` as static files
- SPA catch-all: any `GET` not matched returns `public/index.html`
- Listens on port 5000

---

### 7. `webapp/backend/src/middleware/auth.js`

```js
// JWT payload: { sub: username, pwd: base64(password) }
// Extracts and attaches req.esCredentials = { username, password, authHeader }
export function requireAuth(req, res, next) {
  const token = req.headers.authorization?.replace('Bearer ', '');
  if (!token) return res.status(401).json({ error: 'unauthorized' });
  try {
    const payload = jwt.verify(token, process.env.JWT_SECRET);
    req.esCredentials = {
      username: payload.sub,
      password: Buffer.from(payload.pwd, 'base64').toString(),
      authHeader: `Basic ${Buffer.from(`${payload.sub}:${Buffer.from(payload.pwd, 'base64').toString()}`).toString('base64')}`
    };
    next();
  } catch {
    res.status(401).json({ error: 'invalid token' });
  }
}
```

---

### 8. `webapp/backend/src/routes/auth.js`

- `POST /api/auth/login { username, password }`:
  1. Calls `GET ${ES_HOST}/_security/_authenticate` with Basic auth
  2. If 200: signs JWT `{sub: username, pwd: base64(password), exp: +8h}`, returns `{token, user: {username, roles}}`
  3. If 401: returns 401
- `GET /api/auth/me`: calls `/_security/_authenticate` with the credentials from the JWT, returns user info

---

### 9. `webapp/backend/src/routes/workflows.js`

Proxied Kibana calls — all requests include `Authorization`, `kbn-xsrf: true`, `elastic-api-version: 2023-10-31`:

- `GET /api/workflows` → `GET ${KIBANA_HOST}/api/workflows/workflow` — returns list with `id, name, description, enabled, triggers`
- `GET /api/workflows/:id` → `GET ${KIBANA_HOST}/api/workflows/workflow/:id`

---

### 10. `webapp/backend/src/routes/executions.js`

- `POST /api/workflows/:id/run` body `{inputs}` → `POST ${KIBANA_HOST}/api/workflows/workflow/:id/run`
- `GET /api/workflows/:id/executions?statuses=&size=&page=` → `GET ${KIBANA_HOST}/api/workflows/workflow/:id/executions` — passes through query params
- `GET /api/executions/:executionId` → `GET ${KIBANA_HOST}/api/workflows/executions/:executionId`

---

### 11. `webapp/backend/src/routes/deployments.js`

- `GET /api/deployments`:
  - Calls `GET ${ES_HOST}/deployed-previews/_search?size=100&sort=updated_at:desc`
  - Maps `_source` fields: `{id: _id, target, port, public_url, container_name, deploy_dir_name, es_user, es_password, ttl_days, updated_at}`
- `GET /api/deployments/:id/credentials`:
  - Returns `{username, password}` read directly from `es_user` / `es_password` fields stored in the `deployed-previews` document (written by `deploy-kibana-preview` at deploy time)
- `DELETE /api/deployments/:id`:
  - Calls `POST ${KIBANA_HOST}/api/workflows/workflow/<cleanup-preview-workflow-id>/run` with `inputs: { project: id }`
  - Returns 202 immediately; actual teardown runs asynchronously in the Kibana workflow

---

### 12. `webapp/backend/src/routes/benchmarks.js`

- `GET /api/benchmarks?size=&page=`:
  - `GET ${ES_HOST}/workflow-benchmarks/_search` sorted by `@timestamp:desc`
  - Returns list with `{id: _id, project, target, commit, requested, throughput.completed, throughput.avg_rps, scheduling_lag.p95_s, @timestamp}`
- `GET /api/benchmarks/:id`:
  - `GET ${ES_HOST}/workflow-benchmarks/_doc/:id`
  - Returns full report document
- `GET /api/benchmarks/compare?a=:idA&b=:idB`:
  - Fetches both documents, returns `{a: reportA, b: reportB}` — comparison computation happens in the frontend

---

### 13. `webapp/frontend/` — Angular 18 project

**Stack:** Angular 18 + PrimeNG (`primeng`) + PrimeFlex (`primeflex`) + PrimeIcons (`primeicons`). PrimeNG's built-in `p-chart` (backed by Chart.js) for benchmark charts — no separate charting library needed.

**`angular.json` `outputPath`:** set explicitly to `dist/frontend` so the Dockerfile `COPY --from=ng-build /build/frontend/dist/frontend/browser ./public` is always stable regardless of project name.

**Routes:**
```
/login                          → LoginComponent (public)
/workflows                      → WorkflowsLayoutComponent (shell)
  /workflows/:id                → WorkflowDetailComponent
  /workflows/:id/executions/:eid → ExecutionDetailComponent (drawer)
/deployments                    → DeploymentsComponent
/benchmarks                     → BenchmarkListComponent
  /benchmarks/:id               → BenchmarkDetailComponent
  /benchmarks/compare           → BenchmarkCompareComponent (query params: ?a=&b=)
```

**WorkflowsLayoutComponent:**
- Persistent left sidebar: list of workflows, searchable by name, each row shows name + enabled badge + trigger type chip (manual / scheduled / alert)
- Selecting a workflow navigates to `/workflows/:id`
- Sidebar collapses on mobile

**WorkflowDetailComponent:**
- Header: workflow name, description, enabled toggle (read-only), last-updated time
- **Run** button → opens `p-dialog` with `RunDialogComponent`
  - Auto-generates form fields from `triggers[0].inputs.properties` JSON Schema: string → `p-inputtext`, integer → `p-inputnumber`, boolean → `p-toggleswitch`, array → `p-textarea` (JSON), enum → `p-select`
  - Required fields validated before submit
  - On submit: `POST /api/workflows/:id/run`, shows `p-toast` with execution ID + link
- Execution list: `p-table` with columns = Status, ID (truncated), Started, Duration, Type
  - Status column uses `StatusBadgeComponent` with a `p-tag` colored by severity: running=info, completed=success, failed=danger, cancelled=secondary
  - Auto-polls `GET /api/workflows/:id/executions?statuses=running,pending` every 5 s while any non-terminal execution exists in the current page
  - Pagination: 20 per page via Kibana API params
  - Row click → navigates to `/workflows/:id/executions/:eid`

**ExecutionDetailComponent (drawer):**
- Opens as `p-drawer` overlay (keeps execution list visible behind it)
- Shows: execution metadata header, then a collapsible step tree via `p-tree` with `TreeNode[]`
  - Each node: step name, type icon, status badge (`p-tag`), duration, expand to show `output` JSON in `p-panel`

**DeploymentsComponent:**
- `p-table` with columns: Project, Target (truncated), Updated, Port, Actions
- Actions column per row:
  - **Open Kibana** — external link to `public_url` (or `http://dev-vm:<port>` if no CF configured)
  - **Credentials** — opens `p-dialog` showing `elastic` / password
  - **Delete** — `p-confirmdialog` prompt, then `DELETE /api/deployments/:id`

**BenchmarkListComponent:**
- `p-table` with sortable columns: Timestamp, Project, Completed, Avg RPS, Lag p95
- Checkbox selection column → **Compare** button activates with exactly 2 rows selected
- Row click → navigates to `/benchmarks/:id`

**BenchmarkDetailComponent:**
- Stat cards grid using PrimeFlex: Completed, Failed, Avg RPS, Peak RPS (30 s), Wall Time, Lag p50/p95/p99 (s), E2E p50/p95/p99 (s)
- `p-chart` (type=line): `over_time` buckets → X = `window_start`, Y = `rps` (completions/30 s)
- `p-chart` (type=bar): scheduling lag percentile distribution
- `p-table`: task manager snapshot status → count

**BenchmarkCompareComponent:**
- Layout: two columns (Report A | Report B) with a third delta column using PrimeFlex grid
- Each metric row: label | value A | Δ% (PrimeNG `p-tag` severity=success/danger) | value B
- `p-chart` (type=line): both `over_time` series overlaid, distinct colors per dataset
- Header shows: project + commit for each, timestamp diff

---

### 14. `dev-env/env/webapp.env`

```bash
# Webapp UI — override defaults here.
# JWT_SECRET is REQUIRED; container will refuse to start without it.
JWT_SECRET=change-me-before-production

# WEBAPP_PORT=5000
# ES_HOST=http://elasticsearch:9200
# KIBANA_HOST=http://kibana:5601
```

---

## Phases

Each phase ends with a `git commit && git push` on the `feature/webapp` branch.

### Phase 1 — Infrastructure & Docker
Files: `webapp/Dockerfile`, `webapp/entrypoint.sh`, `webapp/scripts/register-tunnel.sh`, `dev-env/docker-compose.yml`, `dev-env/env/webapp.env`

Goal: container builds and starts (exits cleanly even with no backend code yet). Cloudflare registration runs non-fatally on startup.

Commit: `feat(webapp): add Docker scaffold and compose integration`

---

### Phase 2 — Backend
Files: `webapp/backend/package.json`, `webapp/backend/src/index.js`, `webapp/backend/src/middleware/auth.js`, `webapp/backend/src/routes/auth.js`, `webapp/backend/src/routes/workflows.js`, `webapp/backend/src/routes/executions.js`, `webapp/backend/src/routes/deployments.js`, `webapp/backend/src/routes/benchmarks.js`

Goal: all API routes reachable and returning data; auth flow end-to-end (login → JWT → protected endpoints). Express serves a placeholder `index.html` from `./public`.

Auth details:
- JWT payload `{ sub: username, pwd: base64(password), exp: +8h }` — stateless, no server-side session
- Login validates against ES `/_security/_authenticate`

Deployments delete: calls `POST ${KIBANA_HOST}/api/workflows/workflow/<cleanup-preview-id>/run` with `inputs: { project }`, returns 202 immediately.

Commit: `feat(webapp): add Express backend with auth and API routes`

---

### Phase 3 — Frontend scaffold + auth
Files: Angular CLI project (`ng new`), `app.config.ts`, `app.routes.ts`, `core/auth.service.ts`, `core/api.service.ts`, `core/auth.guard.ts`, `pages/login/`, `environments/`

Goal: app bootstraps, login page works end-to-end (submits to backend, stores JWT, redirects to `/workflows`). Auth guard redirects unauthenticated users to `/login`. PrimeNG + PrimeFlex installed and themed.

`angular.json` `outputPath` set to `dist/frontend` to match Dockerfile COPY path.

Commit: `feat(webapp): bootstrap Angular app with PrimeNG and auth flow`

---

### Phase 4 — Workflows page
Files: `pages/workflows/workflows-layout/`, `pages/workflows/workflow-detail/`, `pages/workflows/execution-detail/`, `shared/status-badge/`, `shared/run-dialog/`, `shared/duration-pipe.ts`

Goal: left-nav lists all workflows; selecting one shows detail with Run button and execution table. Run dialog auto-generates form from JSON Schema. Execution table polls every 5 s while any non-terminal execution is present; stops on route leave (`ngOnDestroy`). Clicking a row opens `p-drawer` with step tree.

Commit: `feat(webapp): add workflows page with run dialog and live executions`

---

### Phase 5 — Deployments page
Files: `pages/deployments/`

Goal: table lists all previews from `deployed-previews` index with Open Kibana, Credentials (`es_user`/`es_password` from the document), and Delete (triggers `cleanup-preview` workflow, 202 response, row removed optimistically).

Commit: `feat(webapp): add deployments page`

---

### Phase 6 — Benchmarks page
Files: `pages/benchmarks/benchmark-list/`, `pages/benchmarks/benchmark-detail/`, `pages/benchmarks/benchmark-compare/`

Goal: list with sortable columns and checkbox compare selection; detail with stat cards + throughput line chart + lag bar chart; compare with two-column delta table and overlaid throughput chart.

Commit: `feat(webapp): add benchmark reports page with compare view`
