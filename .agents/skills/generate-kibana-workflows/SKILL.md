---
name: generate-kibana-workflows
description: 'Create, update, split, or debug Kibana workflow YAML in this repository. Use when asked to generate workflows, add triggers or steps, compose child workflows, add conditions/loops/concurrency/error handling, preserve structured outputs, extract remote scripts, or validate workflow syntax against the running Kibana schema.'
argument-hint: 'Describe the workflow behavior, triggers, inputs, integrations, and expected outputs.'
user-invocable: true
disable-model-invocation: false
---

# Generate Kibana Workflows

Create production-ready workflow YAML for this repository using existing local patterns and the live Kibana schema.

Read [workflow-spec.md](./workflow-spec.md) before designing or editing a workflow. Treat that file and the referenced Kibana source files as the syntax source of truth.

## Procedure

1. **Establish the contract**
   - Identify triggers, typed inputs, constants, required connectors, side effects, retries, and final outputs.
   - Decide whether the workflow is orchestration-only or owns behavior.
   - Prefer child workflows for independently reusable operations such as checkout, deployment, review, cleanup, and deterministic checks.
   - Ask only for missing decisions that materially change permissions, writes, or public contracts.

2. **Inspect local precedent**
   - Read the closest workflows under `dev-env/workflows/`.
   - Reuse existing connector IDs, child workflow IDs, output names, security boundaries, and script-module patterns.
   - Preserve unrelated worktree changes.

3. **Check the effective schema**
   - Read the relevant static schema under `kibana/src/src/platform/packages/shared/kbn-workflows/spec/`.
   - For connector-backed steps, generate or use the schema bundle from the running Kibana. Connector schemas are dynamic and cannot be inferred safely from static built-ins alone.
   - Do not invent step properties or connector inputs.

4. **Design data flow before YAML**
   - Give every step a unique stable `name`.
   - Define which values are strings versus native arrays, objects, booleans, or numbers.
   - Use `${{ ... }}` when a field needs the raw typed value.
   - Use `{{ ... }}` for string interpolation.
   - Apply `| json` only at string boundaries, such as environment variables, command/script text, logs, or agent prompts. Do not JSON-stringify native workflow outputs.
   - Keep `workflow.output` fields stable across early and normal exits.

5. **Implement conservatively**
   - Put workflow definitions in `dev-env/workflows/<workflow-id>.yaml`; filename becomes the uploaded workflow ID.
   - Keep YAML focused on orchestration.
   - Put external Bash, Python, and JavaScript used by dev-vm workflow steps in `dev-env/scripts/`. That host directory is mounted read-only at `/etc/dev-env-scripts` in dev-vm.
   - Reference Bash with `ssh.run` and `bash /etc/dev-env-scripts/<script>.sh`; reference Python with a thin `ssh.python` wrapper importing from `/etc/dev-env-scripts`; reference JavaScript with a thin `ssh.node` wrapper requiring `/etc/dev-env-scripts/<module>.js`.
   - Pass runtime values through the workflow step's `env`; environment values are strings, so serialize structured values with `| json` and parse them in the external script. Never bake runtime values or secrets into source files.
   - External scripts must return/write JSON-compatible structured results using the step convention: Python/Node wrappers `return` the value; Bash writes JSON to `$STEP_OUTPUT`.
   - Do not make scripts write beside themselves because the mount is read-only. Use the workflow checkout, `/tmp`, or another explicit writable path.
   - Bound external subprocess/network calls and return actionable timeout diagnostics.
   - Never print credentials or pass secrets into model prompts.
   - Use explicit allowlists before Git/GitHub writes.

6. **Apply control flow correctly**
   - Wrap conditions as `${{ ... }}`.
   - Remember `while` is do-while: its body runs once before the condition is checked.
   - Bound `while`, `foreach`, and `parallel` work.
   - Use `workflow.output` for intentional early termination and preserve the same output contract.
   - Keep resumed agent calls sequential when they share a session ID.

7. **Validate immediately**
   - Parse YAML and compile every embedded Python wrapper.
   - Validate against the live generated schema, including semantic and Liquid checks.
   - Run focused helper tests for branching, retries, data partitioning, and side-effect guards.
   - Run editor diagnostics and `git diff --check`.
   - Do not claim end-to-end success unless an execution was actually run and inspected.

## Required Validation

From `/opt/ubuntu_vm`, use Kibana's required Node version (currently `24.21.0`). Generate the schema bundle if it is missing:

```bash
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

Validate each changed workflow:

```bash
NODE=/root/.nvm/versions/node/v24.21.0/bin/node
"$NODE" kibana/src/scripts/validate_workflow_yaml.js \
  dev-env/workflows/<workflow-id>.yaml \
  --schema /tmp/review-workflow-schemas/9.6.0/release \
  --summary-only
```

Also run:

```bash
git diff --check
```

## Completion Checklist

- The filename matches every `workflow-id` reference.
- Manual inputs use JSON Schema and defaults have the correct types.
- Scheduled intervals are at least one minute.
- Raw structured values use `${{ ... }}`; `| json` appears only at string boundaries.
- Every condition is wrapped in `${{ ... }}`.
- Loops have deliberate limits and limit behavior.
- Early outputs and normal outputs share a stable contract.
- Child workflow failures and missing outputs are handled intentionally.
- External calls are bounded; write operations are guarded and idempotent where possible.
- External scripts live in `dev-env/scripts/`, use the correct `/etc/dev-env-scripts` reference pattern, and pass syntax checks (`bash -n`, Python parse/compile, or `node --check`).
- No credential is logged, serialized into output, or sent to an agent.
- Live schema validation, focused tests, diagnostics, and `git diff --check` pass.
