# Kibana Workflow Specification

This reference describes the workflow dialect used by this repository. The running Kibana-generated schema is authoritative for connector-backed steps; static source is authoritative for built-in syntax and semantics.

## Sources of Truth

- Core workflow schema: `kibana/src/src/platform/packages/shared/kbn-workflows/spec/schema.ts`
- Built-in steps: `kibana/src/src/platform/packages/shared/kbn-workflows/spec/builtin_step_definitions.ts`
- Built-in triggers: `kibana/src/src/platform/packages/shared/kbn-workflows/spec/builtin_trigger_definitions.ts`
- Trigger schemas: `kibana/src/src/platform/packages/shared/kbn-workflows/spec/schema/triggers/`
- Step schemas: `kibana/src/src/platform/packages/shared/kbn-workflows/spec/schema/steps/`
- YAML/Liquid validation: `kibana/src/src/platform/packages/shared/kbn-workflows-yaml/`
- Runtime semantics: `kibana/src/src/platform/plugins/shared/workflows_execution_engine/server/step/`
- Validation CLI: `kibana/src/src/platform/packages/private/kbn-workflow-yaml-validate-cli/`
- Schema generator: `kibana/src/scripts/generate_workflow_step_schemas.js`
- Validator wrapper: `kibana/src/scripts/validate_workflow_yaml.js`
- Repository examples: `dev-env/workflows/`

## Top-Level Document

```yaml
version: '1'
name: Example Workflow
description: Optional description
enabled: true
tags:
  - example

settings:
  timeout: 30m
  max-step-size: 10mb
  concurrency:
    key: '{{ workflow.id }}'
    strategy: queue
    max: 1
    queue-size: 100
    queue-ttl: 24h
  liquid:
    parseLimit: 150000
    renderLimit: 1000
    memoryLimit: 15000000

consts:
  API_URL: https://example.invalid
  ITEMS:
    - one
    - two

triggers:
  - type: manual

steps:
  - name: output
    type: workflow.output
    with:
      status: completed
```

Required fields are `name`, at least one trigger, and at least one step. `version` defaults to `'1'`; keep it explicit in repository workflows.

### Settings

- `run_as`: execution identity.
- `timezone`: IANA timezone.
- `timeout`: whole-workflow duration.
- `max-step-size`: workflow default response/output size, e.g. `10mb`.
- `concurrency.strategy`: `queue`, `drop`, or `cancel-in-progress`.
- `concurrency.key`: Liquid string defining the concurrency bucket.
- `concurrency.max`: concurrent executions per bucket.
- `queue-size`, `queue-ttl`: queue controls.
- `on-failure`: workflow-level failure policy.
- `liquid`: parser/render/memory limits. Increase only with evidence.

## Triggers

### Manual

Use JSON Schema under the trigger:

```yaml
triggers:
  - type: manual
    inputs:
      additionalProperties: false
      required:
        - target
      properties:
        target:
          type: string
          description: GitHub target URL.
        dry_run:
          type: boolean
          default: true
        retries:
          type: integer
          default: 3
          minimum: 1
        items:
          type: array
          default: []
          items:
            type: object
            required: [id]
            properties:
              id:
                type: string
```

Access values with `inputs.target`. Defaults retain their declared type.

### Scheduled

Simple schedules have a minimum interval of one minute:

```yaml
triggers:
  - type: scheduled
    with:
      every: 10m
```

Accepted simple units are seconds (at least `60s`), minutes, hours, and days. Calendar schedules use `rrule`:

```yaml
triggers:
  - type: scheduled
    with:
      rrule:
        freq: WEEKLY
        interval: 1
        byweekday: [MO, WE, FR]
        byhour: [9]
        byminute: [0]
        tzid: America/New_York
```

`freq` is `DAILY`, `WEEKLY`, or `MONTHLY`.

### Alert

```yaml
triggers:
  - type: alert
```

Use `event`, `event.alerts`, `event.rule`, and `event.spaceId` in steps.

A workflow may define multiple triggers, commonly scheduled plus manual.

## Values, Templates, and Expressions

### Raw typed values

Use `${{ ... }}` when the destination must receive an array, object, boolean, or number:

```yaml
projects: ${{ consts.PROJECTS }}
changed_files: ${{ steps.prepare.output.changed_files }}
needs_work: ${{ steps.review.output.needs_work }}
```

This is required for child inputs, `foreach`, `data.set`, and `workflow.output` when preserving types.

### String interpolation

Use `{{ ... }}` when building a string:

```yaml
cwd: '/opt/{{ steps.checkout.output.project }}/src'
message: 'Processed {{ steps.search.output.total }} records'
```

### JSON serialization

Use `| json` only when a structured value must cross a string boundary:

```yaml
env:
  ITEMS_JSON: '{{ steps.fetch.output.items | json }}'
prompt: 'Analyze: {{ foreach.item | json }}'
```

Do not use `| json` for native `workflow.output` arrays/objects or raw child-workflow inputs.

### Context paths

- `inputs.<name>`: manual inputs.
- `consts.<name>`: workflow constants.
- `steps.<name>.output`: step output.
- `variables.<name>`: values set by `data.set`.
- `event.*`: trigger event.
- `workflow.id`, `workflow.name`, `workflow.spaceId`: workflow metadata.
- `execution.*`: execution metadata.
- `foreach.item`, `foreach.index`, `foreach.total`: foreach/parallel fan-out context.
- `while.iteration`: while-loop iteration, zero-based.
- `error.*`: failure-policy context.

## Common Step Shape

```yaml
- name: unique_step_name
  type: step.type
  if: "${{ variables.enabled == true }}"
  timeout: 5m
  max-step-size: 10mb
  on-failure:
    retry:
      max-attempts: 3
      delay: 5s
      strategy: exponential
      multiplier: 2
      max-delay: 1m
      jitter: true
    continue: false
  with: {}
```

Connector steps can also expose `connector-id` at the step level, as shown by local `ssh.*` examples. Always validate connector-backed syntax against the live schema.

## Conditions

Repository convention is a raw boolean expression wrapped in `${{ ... }}`:

```yaml
condition: "${{ variables.status == 'ready' and inputs.dry_run == false }}"
```

Use `condition` on an `if` or `while` control-flow step. Use step-level `if` on ordinary steps:

```yaml
if: "${{ foreach.index > 0 }}"
```

Do not put step-level `if` on a step whose type is `if`; that type already uses `condition`.

## Built-In Data and Utility Steps

### Console

```yaml
- name: log
  type: console
  with:
    message: 'Project: {{ variables.project }}'
```

### Data Set

```yaml
- name: save_state
  type: data.set
  with:
    project: '{{ steps.checkout.output.project }}'
    findings: ${{ steps.review.output.findings }}
    ready: true
```

Store structured values natively. Variables merge across all completed `data.set` steps in execution order, so a list can be accumulated inside `foreach` with Liquid filters:

```yaml
- name: record_result
  type: data.set
  with:
    results: "${{ variables.results | push: steps.run_item.output }}"
```

Initialize the list first (`results: []`), then split it with `where`, e.g. `"${{ variables.results | where: 'status', 'failed' }}"`.

### Wait

```yaml
- name: pause
  type: wait
  with:
    duration: 30s
```

Durations use compact units such as `500ms`, `5s`, `1m30s`, `2h`, or `1d`.

### Workflow Output

```yaml
- name: output
  type: workflow.output
  with:
    project: '{{ variables.project }}'
    findings: ${{ variables.findings }}
    passed: ${{ variables.passed }}
```

`workflow.output` immediately terminates the workflow. No subsequent step runs. Early and normal output paths should expose the same keys and types.

Optional step-level `status` is `completed`, `cancelled`, or `failed`.

### Workflow Fail

```yaml
- name: fail
  type: workflow.fail
  with:
    message: Validation failed
    reason: invalid_input
```

## Control Flow

### If

```yaml
- name: route
  type: if
  condition: "${{ variables.ready == true }}"
  steps:
    - name: ready
      type: console
      with:
        message: Ready
  else:
    - name: not_ready
      type: console
      with:
        message: Not ready
```

### Foreach

```yaml
- name: process_items
  type: foreach
  foreach: ${{ steps.fetch.output.items }}
  max-iterations:
    limit: 100
    on-limit: fail
  iteration-timeout: 5m
  steps:
    - name: process_item
      type: console
      with:
        message: 'Item {{ foreach.index }}: {{ foreach.item.name }}'
```

`on-limit` is `continue` or `fail`. Use `loop.break` and `loop.continue` only inside a loop.

### While

```yaml
- name: retry_until_clean
  type: while
  condition: "${{ variables.needs_work == true }}"
  max-iterations:
    limit: 5
    on-limit: continue
  steps:
    - name: check
      type: workflow.execute
      with:
        workflow-id: review
```

`while` is do-while: the body always executes once before the condition is evaluated. Guard it with an outer `if` if zero executions must be possible.

### Switch

```yaml
- name: route_status
  type: switch
  expression: '{{ variables.status }}'
  cases:
    - match: ready
      steps:
        - name: ready
          type: console
          with:
            message: Ready
    - match: failed
      steps:
        - name: failed
          type: workflow.fail
  default:
    - name: unknown
      type: console
      with:
        message: Unknown status
```

### Parallel

Dynamic fan-out:

```yaml
- name: fan_out
  type: parallel
  foreach: ${{ variables.items }}
  concurrency:
    max: 5
    count-waiting: true
  mode: settled
  branch-timeout: 10m
  steps:
    - name: process
      type: http
      with:
        url: 'https://example.invalid/{{ foreach.item.id }}'
```

Static branches require at least two uniquely named branches:

```yaml
- name: gather
  type: parallel
  mode: fail-fast
  branches:
    - name: first
      steps:
        - name: first_call
          type: http
          with:
            url: https://example.invalid/first
    - name: second
      steps:
        - name: second_call
          type: http
          with:
            url: https://example.invalid/second
```

Use exactly one mode: dynamic `foreach` + `steps`, or static `branches`. Maximum concurrency is 20; default is 5. Modes are `fail-fast` and `settled`.

## Child Workflows

Synchronous child call:

```yaml
- name: checkout
  type: workflow.execute
  with:
    workflow-id: checkout-kibana-project
    inputs:
      kibana_target: '{{ inputs.kibana_target }}'
      target_depth: ${{ inputs.target_depth }}
      additional_branches: ${{ inputs.additional_branches }}
```

The parent reads the child's `workflow.output` through `steps.checkout.output`.

Asynchronous child call:

```yaml
- name: cleanup
  type: workflow.executeAsync
  with:
    workflow-id: cleanup-preview
    inputs:
      project: '{{ variables.project }}'
```

It returns workflow/execution metadata instead of waiting for the child output.

Child and parent variable scopes are separate. Pass all required state through child inputs and outputs.

## External Script Placement and References

All reusable Bash, Python, and JavaScript executed on dev-vm belongs in:

```text
dev-env/scripts/
```

Compose mounts that directory read-only inside dev-vm:

```text
/etc/dev-env-scripts
```

Use snake_case filenames that describe one operation. Keep workflow YAML as a thin orchestration layer. Do not place workflow-owned remote scripts under `kibana/scripts/`; that directory is part of each deployment scaffold and is for preview build/setup behavior, not the main dev-vm workflow library.

### Bash

Store Bash as `dev-env/scripts/<name>.sh` and invoke it explicitly with Bash so executable mode is not required:

```yaml
- name: sync_data
  type: ssh.run
  connector-id: dev-vm
  with:
    cwd: '{{ variables.checkout_dir }}'
    env:
      PROJECT: '{{ variables.project }}'
      ITEMS_JSON: '{{ variables.items | json }}'
    command: |
      bash /etc/dev-env-scripts/sync_data.sh
```

Script contract:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Parse structured env values with a real parser.
item_count=$(python3 -c 'import json,os; print(len(json.loads(os.environ["ITEMS_JSON"])))')

python3 - "$PROJECT" "$item_count" > "$STEP_OUTPUT" <<'PY'
import json
import sys

json.dump({"project": sys.argv[1], "item_count": int(sys.argv[2])}, sys.stdout)
PY
```

- Write only machine output JSON to `$STEP_OUTPUT`; ordinary stdout/stderr remains execution logs.
- Quote shell variables and start scripts with `set -euo pipefail`.
- Use arrays rather than string-built shell commands when practical.
- Validate with `bash -n dev-env/scripts/<name>.sh`.

### Python

Store Python as `dev-env/scripts/<module>.py`. Expose a function that accepts an optional environment/cwd for testability and returns a JSON-compatible value:

```python
import json
import os


def prepare_items(environment=None):
    environment = os.environ if environment is None else environment
    items = json.loads(environment['ITEMS_JSON'])
    return {"items": items, "count": len(items)}
```

Reference it with a minimal `ssh.python` wrapper:

```yaml
- name: prepare_items
  type: ssh.python
  connector-id: dev-vm
  with:
    cwd: '{{ variables.checkout_dir }}'
    env:
      ITEMS_JSON: '{{ variables.items | json }}'
    code: |
      import sys
      sys.path.insert(0, '/etc/dev-env-scripts')
      from prepare_items import prepare_items
      return prepare_items()
```

- Do not duplicate implementation logic in the YAML wrapper.
- Add timeouts to subprocess and network operations.
- Raise concise errors that identify the operation without leaking secrets.
- Validate modules with `ast.parse`, `compile`, or focused unit-style tests.

### JavaScript

Store CommonJS modules as `dev-env/scripts/<module>.js` because dev-vm Node wrappers can load them by absolute path:

```javascript
async function prepareItems(environment = process.env) {
  const items = JSON.parse(environment.ITEMS_JSON);
  return { items, count: items.length };
}

module.exports = { prepareItems };
```

Reference the module from a thin `ssh.node` wrapper:

```yaml
- name: prepare_items
  type: ssh.node
  connector-id: dev-vm
  with:
    env:
      ITEMS_JSON: '{{ variables.items | json }}'
    code: |
      const { prepareItems } = require('/etc/dev-env-scripts/prepare_items.js');
      return await prepareItems(process.env);
```

- Export functions rather than running side effects at module import time.
- Return JSON-compatible values; do not print a second machine-readable payload.
- Use explicit timeouts/abort signals for network and child-process calls.
- Validate with `node --check dev-env/scripts/<module>.js` and focused tests.

### Shared Rules

- `env` values are strings. Use `${{ ... }}` for native workflow fields, but use `{{ value | json }}` when moving arrays/objects into environment variables.
- Pass secrets only via environment inherited by deterministic steps. Never include them in prompts, logs, errors, outputs, command arguments, or checked-in files.
- The mount is read-only. Scripts may read their own resources but must write logs/artifacts to `/tmp`, the checkout, or another explicit writable directory.
- Use absolute `/etc/dev-env-scripts/...` references; do not depend on the remote working directory or `PYTHONPATH`.
- Keep one stable structured result contract across success, skip, and early-return paths.
- When adding a new language/module, ensure `dev-env/docker-compose.yml` still mounts `./scripts:/etc/dev-env-scripts:ro` and recreate dev-vm if the mount is absent.

## Repository Connector and Action Steps

The effective schemas for these steps depend on connectors registered in running Kibana. Never infer their complete shape from this reference.

Local examples include:

- `ssh.run`: remote shell command with optional `cwd` and string `env`. A non-zero exit fails the step; to report a failing command as data, capture `$?` and exit 0. `$STEP_OUTPUT` JSON becomes the native output; stdout/stderr stream into execution logs.
- `ssh.python`: embedded Python wrapper; return a JSON-compatible object.
- `ssh.node`: embedded Node.js.
- `http`: HTTP request.
- `elasticsearch.request`: raw Elasticsearch request used by repository workflows.
- Other connector/action step types exposed by the live schema.

Example remote Python wrapper:

```yaml
- name: prepare
  type: ssh.python
  connector-id: dev-vm
  with:
    cwd: '{{ steps.checkout.output.source_dir }}'
    env:
      ITEMS_JSON: '{{ variables.items | json }}'
    code: |
      import sys
      sys.path.insert(0, '/etc/dev-env-scripts')
      from prepare_items import prepare_items
      return prepare_items()
```

Keep embedded wrappers minimal; follow the external script rules above for substantive behavior.

## Failure Handling

```yaml
on-failure:
  retry:
    max-attempts: 3
    condition: "${{ error.type == 'NetworkError' }}"
    delay: 5s
    strategy: exponential
    multiplier: 2
    max-delay: 1m
    jitter: true
  fallback:
    - name: fallback_log
      type: console
      with:
        message: 'Primary step failed'
  continue: false
```

`continue` may be a boolean or condition string. A child failure normally fails its parent step; if continued, child output may be unavailable.

Use step/workflow timeouts and internal subprocess timeouts. Workflow timeouts do not guarantee that grandchildren are cleaned up correctly.

## Security and Side Effects

- Never include credentials in workflow output, logs, errors, prompts, or serialized state.
- Use `env` for deterministic remote steps; remove secrets before invoking agents.
- Keep GitHub/Git writes in explicit workflow-owned helpers, not agent shell access.
- Validate repository/ref names and expected SHAs.
- Use normal non-force pushes and fail on remote advancement.
- Make scheduled writes idempotent.
- Use unprivileged accounts for tests and grant only required filesystem access.
- Treat PR comments and external payloads as untrusted data.

## Validation

The schema bundle reflects registered connectors and must come from a running Kibana.

Generate it when missing:

```bash
cd /opt/ubuntu_vm
set -a
. dev-env/env/es.env
set +a
NODE=/root/.nvm/versions/node/v24.21.0/bin/node
rm -rf /tmp/review-workflow-schemas
"$NODE" kibana/src/scripts/generate_workflow_step_schemas.js \
  --kibana-url http://localhost:5002 \
  --username elastic \
  --password "$ES_PASSWORD" \
  --output-dir /tmp/review-workflow-schemas \
  --channel release \
  --skip-completeness-check \
  --quiet
```

Validate one workflow:

```bash
NODE=/root/.nvm/versions/node/v24.21.0/bin/node
"$NODE" kibana/src/scripts/validate_workflow_yaml.js \
  dev-env/workflows/example.yaml \
  --schema /tmp/review-workflow-schemas/9.6.0/release \
  --summary-only
```

This validates schema, semantics, references, and Liquid expressions.

Compile embedded Python wrappers because workflow schema validation does not parse Python syntax:

```python
import yaml
from pathlib import Path

path = Path('dev-env/workflows/example.yaml')
document = yaml.safe_load(path.read_text())


def visit(steps):
    for step in steps or []:
        if step.get('type') == 'ssh.python':
            code = step['with']['code']
            compile(
                'def _step():\n' + ''.join(
                    '    ' + line for line in code.splitlines(keepends=True)
                ),
                f'{path}:{step.get("name")}',
                'exec',
            )
        visit(step.get('steps'))
        visit(step.get('else'))


visit(document.get('steps'))
```

Also run editor diagnostics, focused helper tests, and:

```bash
git diff --check
```

## Repository Examples by Feature

- Scheduled plus manual trigger, foreach: `dev-env/workflows/sync-kibana-forks.yaml`
- Child workflow and native structured inputs/outputs: `dev-env/workflows/checkout-kibana-project.yaml`
- Early output: `dev-env/workflows/deploy-kibana-preview.yaml`
- Review-only orchestration and raw structured output: `dev-env/workflows/review-kibana-pr.yaml`
- While + foreach + GitHub write gating: `dev-env/workflows/review-and-fix-kibana-pr.yaml`
- Scheduled cleanup and child foreach: `dev-env/workflows/cleanup-expired-previews.yaml`
- HTTP/JavaScript/metrics processing: `dev-env/workflows/collect_metrics.yaml`
- Native-step child workflow with foreach result accumulation: `dev-env/workflows/run-kibana-unit-tests.yaml`

## Common Failure Modes

- JSON-stringifying arrays/objects in `workflow.output` instead of using raw `${{ ... }}`.
- Passing raw objects into `ssh.*.env`; environment values must be strings, so use `| json` there.
- Using bare condition strings instead of `${{ ... }}`.
- Assuming `while` can run zero times.
- Omitting loop limits or selecting `continue` when a hard failure is required.
- Referencing outputs produced only in a branch without defaults or prior initialization.
- Reusing a step name, making `steps.<name>.output` ambiguous.
- Placing substantive Python inline, making it hard to test and easy to hang.
- Running unbounded `git fetch`, HTTP, CLI, test, or agent subprocesses.
- Assuming static schemas know connector-backed steps.
- Putting a step after `workflow.output` and expecting it to run.
- Returning different output keys/types from early and normal exits.
