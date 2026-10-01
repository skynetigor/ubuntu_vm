# Kibana Workflow Review Automation Plan

## Goal

Create a parent Kibana workflow that deploys the requested Kibana target, reviews only changed production code against a base branch, applies qualified fixes, handles existing PR review comments when the target is a PR, and runs workflow-project lint and unit tests. The workflow returns a structured summary of review findings, fixes, GitHub comment actions, and validation results.

## Existing Interfaces

- `deploy-kibana-preview` accepts `kibana_target`, `elastic_password`, `workflows_group`, and related deployment settings. Its output includes the preview `project`, `target`, `commit`, ports, and URLs.
- `main-kibana-agent` accepts `prompt`, `session_id`, `cwd`, `run_summary`, and `disallow_shell`; it returns `response`, `run_summary`, `findings`, `changes`, and the next `session_id`.
- The review parent sets `disallow_shell: true` on every Claude child call so agents can use file read/edit tools but cannot invoke privileged or GitHub-write shell commands.
- The Claude workflow runs remotely on `dev-vm` through `ssh.python` in the supplied working directory and uses `--permission-mode auto`.
- `check-kibana-workflow-projects` is the reusable deterministic child workflow for targeted ESLint autofix and Moon Jest runs.
- Project checks run as the `workflow-runner` account with a clean environment and no Docker/sudo groups or API tokens. The checker grants temporary ACL access only to node_modules and selected project source roots, and configures Git safe.directory only for the exact checkout.
- Kibana workflow-owned packages and plugins use Moon project IDs. The shared Moon `jest` task runs Jest with `--passWithNoTests`.
- `dev-vm` receives `GH_TOKEN` from its ignored, owner-only environment file. Deterministic SSH Python GitHub steps use it; the Claude subprocess strips GitHub/Buildkite token variables and has shell access disabled for this workflow. Never print or return the token.

## Agent Session Contract

- Use exactly one Claude Code session for the entire parent workflow execution.
- The first `main-kibana-agent` call starts without `session_id`; save its returned ID as the run's current session ID.
- Before every later agent call, pass that current ID as `inputs.session_id`. After the child completes, replace the current ID with the ID returned by that call before invoking any other agent step.
- This applies to review fixes, PR-comment analysis, PR-comment fixes, lint repairs, test repairs, and every retry. No agent step may omit the ID after the first call or start its own session.
- Keep all agent calls sequential, including calls inside project loops; parallel calls could race on or fork the same Claude session.
- If any agent step fails or returns an empty session ID, stop the workflow and report the failure. Do not silently retry without the ID.
- Include the final session ID in the parent workflow output so a later workflow execution may explicitly continue it if desired; otherwise a new parent execution starts a new session.
- Require every agent phase to return a compact structured `run_summary` containing decisions, findings, files changed, unresolved items, and next actions. Store it in parent workflow state and include it in each subsequent prompt along with the latest session ID.
- Allow Claude Code's native context compaction within the resumed session. At phase boundaries, request a concise checkpoint summary and continue with the same ID and stored `run_summary`; never create a second summarizer session.

## Proposed Parent Workflow

Add `dev-env/workflows/review-kibana-pr.yaml`, upload it to main Kibana, and invoke child workflows synchronously so each step can consume the prior step's outputs.

### Workflow Constants

Define the production-file policy once under workflow `consts` and reuse it consistently:

```yaml
consts:
  FIXABLE_SEVERITIES:
    - high
    - medium
  SEVERITY_RUBRIC: >-
    high: likely security vulnerability, data loss/corruption, severe outage, or
    broad critical-path break. medium: reproducible functional regression or
    materially harmful reliability/performance issue with meaningful user
    impact. low: minor/narrow impact. nit: style/readability preference.
    opinionated: subjective alternative without a demonstrated defect.
```

- `PRODUCTION_FILE_INCLUDE_GLOBS`: production source and runtime-configuration paths under selected project source roots.
- `PRODUCTION_FILE_EXCLUDE_GLOBS`: tests/specs, fixtures, mocks, snapshots, docs, generated/target output, vendored code, and build/dist directories.
- `PRODUCTION_FILE_POLICY`: concise agent instructions to review only changed production implementation/runtime configuration, skip excluded categories, and skip ambiguous files rather than assuming they are production.
- `FIXABLE_SEVERITIES`: `medium` and `high`; these are the only severities the workflow may automatically fix.
- `SEVERITY_RUBRIC`: shared definitions for high, medium, and non-fixable low/nit/opinionated findings.

The deterministic diff-filter step consumes the include/exclude glob constants. Interpolate `{{ consts.PRODUCTION_FILE_POLICY }}` into the initial code-review prompt and PR-comment analysis prompt so both use exactly the same policy as file selection. Interpolate `{{ consts.SEVERITY_RUBRIC }}` and `{{ consts.FIXABLE_SEVERITIES | json }}` into all review, classification, and fix prompts; use the same constants when filtering which findings/comments enter automatic fixes. Do not duplicate or paraphrase either policy in prompts.

The `SEVERITY_RUBRIC` constant is the normative definition; `FIXABLE_SEVERITIES` is the sole automatic-fix threshold.

### Inputs

- `kibana_target` (required): branch, commit, or PR URL accepted by `deploy-kibana-preview`.
- `base_branch` (default `main`): comparison base for the source review.
- `elastic_password` and deployment options: forward only the required values to `deploy-kibana-preview`.
- `workflows_group`: default to `none` unless this workflow must be available in the preview itself.
- `ttl_days` (default `3`): keep the deployed preview available for inspection; the existing expiry cleanup removes it after the TTL.
- `dry_run` (recommended, default `true`): do not commit/push fixes or post replies/resolve GitHub threads until explicitly disabled.
- `MAX_PRODUCTION_FILES` and `MAX_DIFF_CHARS` bound raw source context; the current workflow fails clearly when either limit is exceeded rather than silently truncating the review.

### Ordered Steps

1. **Initialize preview**: call `deploy-kibana-preview` with the requested target and the chosen deployment options. Capture the returned `project`, `commit`, and preview URLs. Derive the source checkout path from the returned `project`; expected path is `/opt/<project>/kibana/src`.
2. **Prepare review diff**: on `dev-vm`, fetch the selected base branch and compute the merge-base diff from base to deployed commit. Filter changed paths with `PRODUCTION_FILE_INCLUDE_GLOBS` and `PRODUCTION_FILE_EXCLUDE_GLOBS`; emit selected production-file paths, diff/stat, and the actual bounded diff as structured output. The current implementation stops with an actionable error above 100 production files or 160,000 diff characters; it does not yet chunk large reviews.
3. **Review production changes**: make the first `main-kibana-agent` call with the source checkout as its working directory, the deterministic diff payload, production-file list, `{{ consts.PRODUCTION_FILE_POLICY }}`, and `{{ consts.SEVERITY_RUBRIC }}`. Claude has shell access disabled, so do not ask it to run git commands to obtain the diff. Require a structured response with severity, finding, evidence, and file/line; do not modify files in this review call. Save its returned `session_id` as the current ID.
4. **Fix the workflow's review findings**: call `main-kibana-agent` with the current ID, the review response, and `{{ consts.FIXABLE_SEVERITIES | json }}`; replace the current ID with the returned ID immediately. Ask it to fix only findings whose severity is in that constant. Return changed files and a concise fix report. Do not let this step create commits or push branches.
5. **Detect target kind**: parse the input and emit `is_pr`, repository owner/name, and PR number when applicable. Branch and commit targets emit `is_pr: false`; unsupported URL forms fail clearly rather than being guessed.
6. **Conditionally process PR comments**: place PR-only read and agent work inside an `if` container. For example:


   ```yaml
   - name: handle_pr_comments
     type: if
     condition: 'steps.detect_target.output.is_pr == true'
     steps:
       - name: fetch_pr_comments
         # gh api reads comments and review-thread state
       - name: analyze_pr_comments
         # Claude receives the current session_id and returns the next one
       - name: fix_pr_comments
         # Claude fixes only comments whose severity is in FIXABLE_SEVERITIES
   ```

	 The real workflow must use valid step definitions rather than the abbreviated comments above. Fetch paginated inline comments and review-thread metadata via `gh api`; analyze each against current production source using `{{ consts.PRODUCTION_FILE_POLICY }}` and `{{ consts.SEVERITY_RUBRIC }}`; check whether each is already fixed; and only fix comments whose severity is in `{{ consts.FIXABLE_SEVERITIES | json }}`. Branch/commit targets do not execute this container.
7. **Validate changed workflow projects**: consider only the 11 projects in the fixed matrix below, and run checks only for listed project source roots intersecting any changed source files (including tests). Do not add integration projects or dependency consumers. Invoke the `check-kibana-workflow-projects` child, which runs ESLint autofix on changed lintable source/test files and Moon Jest for each selected project. Preserve complete stdout/stderr as dev-vm artifacts and return exit code plus a bounded diagnostic summary as step output. If lint fails, call `main-kibana-agent` with the current ID and the lint summary; if tests fail, call it with the latest ID and the test summary. Replace the ID and `run_summary` after each call. Re-run only the affected check after an agent fix, with a bounded retry count. Project loops and their agent repairs must execute sequentially.
8. **Publish validated PR fixes**: for a PR target only, and only when `dry_run` is false and every executed lint/test check passes, stage only working-tree changes in the reviewed production-file list plus test/spec files under the fixed 11 project roots. Reject other non-generated changes, create a commit on the checked-out PR head branch, and push normally (never force-push). Verify the expected head SHA before publishing; if the remote branch advanced, stop and report a non-fast-forward conflict without overwriting it. In dry-run mode or for non-PR targets, do not commit or push.
9. **Conditionally reply and resolve PR threads**: only after validated fixes have been published (or in dry-run mode, after validation), use a second `if` container with the same PR condition to reply to comments fixed under `{{ consts.FIXABLE_SEVERITIES | json }}` and resolve their review threads when `dry_run` is false. With the default `dry_run: true`, report proposed replies/resolutions without invoking GitHub write APIs. Low/nit/opinionated and already-fixed comments are reported but left open; threads that are already resolved at write time are skipped. Non-PR targets skip this container.
10. **Return workflow output**: include preview details, base and target commits, review findings, changes made, resulting PR head SHA when published, PR-comment classification/fix/resolution summary (empty/skipped for non-PR targets), per-project lint/test outcomes, skipped projects, retry count, any failed/gated actions, and the final Claude `session_id`. Never include credentials.

## Workflow Project Matrix

The complete fixed project set is the following 11 workflow-owned projects. Do not add optional integration projects or downstream dependency consumers. Select a project only when its source root intersects any changed source path. The separate production-file policy still limits Claude's review context; it does not suppress tests for test-only diffs.

| Moon project ID | Main source area |
|---|---|
| `@kbn/workflows` | `src/platform/packages/shared/kbn-workflows` |
| `@kbn/workflows-library` | `src/platform/packages/shared/kbn-workflows` library surfaces |
| `@kbn/workflows-yaml` | shared workflow YAML package |
| `@kbn/workflows-ui` | shared workflow UI package |
| `@kbn/deeplinks-workflows` | shared workflow deep links |
| `@kbn/workflows-execution-engine` | `src/platform/plugins/shared/workflows_execution_engine` |
| `@kbn/workflows-extensions` | `src/platform/plugins/shared/workflows_extensions` |
| `@kbn/workflows-management-plugin` | shared workflow management plugin |
| `@kbn/workflow-step-schema-cli` | private workflow step schema CLI |
| `@kbn/workflow-yaml-validate-cli` | private workflow YAML validation CLI |
| `@kbn/workflow-graph-screenshot-cli` | private workflow graph screenshot CLI |

### Deterministic Commands

- **Unit tests**: `node_modules/.bin/moon run '<project-id>:jest'` from the Kibana source root, with optional Jest arguments appended when needed. Capture the full output and exit status.
- **Lint autofix**: derive changed lintable source/test paths for one project and invoke Kibana's ESLint wrapper as `node scripts/eslint.js --fix <paths>` under the Node version from `.nvmrc`. The exact invocation must be smoke-tested under Node 24.21. There is no common Moon `lint` target in the inspected project configs, so do not invent `moon run <project>:lint`.
- Make lint/test steps report `{project, command, stdout, stderr, exit_code}` as JSON and continue on nonzero exit so downstream agent repair steps can consume the output.
- Treat Jest's `--passWithNoTests` result as `no_tests` (acceptable/N/A for that project), not as evidence of test coverage. A failed command or test suite is `failed`. Every lint/test check that actually runs must pass before PR replies or thread resolution; any failure blocks those GitHub write actions.

## PR API Behavior

- Read inline review comments with the paginated REST pulls-comments endpoint.
- Post a reply with the review-comment reply endpoint and the original comment ID as `in_reply_to`.
- Resolve a review thread with GraphQL `resolveReviewThread`; REST comment listing alone does not resolve a thread.
- Persist comment IDs and action results in workflow outputs so retries do not duplicate replies. Before each write, re-check live thread state and use an idempotency marker in the reply body or an equivalent duplicate check.
- Default to dry-run. Only comments fixed at a severity in `FIXABLE_SEVERITIES` are eligible for automatic replies/resolution, and those writes occur only when the caller explicitly sets `dry_run: false`; report but leave other comments open.
- Require `GH_TOKEN` to be present, but never echo it, pass it in a prompt, or serialize it into workflow output. Its repository access and permissions for reading contents, pushing to the PR head, posting replies, and resolving review threads are verified for the intended PR repository. Preflight the target repository at runtime and fail closed on access errors; never treat a private-repository 404 as “no comments.”

## Safety, Failure Handling, and Cleanup

- Keep all shell/API work on `dev-vm` using `ssh.run` / `ssh.python` and the `.ssh` connector.
- Limit Claude's initial review context to the production diff and allow reading adjacent production files only when necessary. Require line-based evidence; filter low-confidence and duplicate findings.
- Enforce the [Agent Session Contract](#agent-session-contract) across every agent call. Keep full deterministic logs on dev-vm and send bounded summaries to Claude; the current implementation stops on oversized review diffs rather than chunking them. Strip `GH_TOKEN`, `GITHUB_TOKEN`, and Buildkite credentials from the Claude subprocess environment; disallow Claude's `sudo`, Docker, GitHub CLI, commit, and push commands. Keep the mounted Claude env file owner-only so GitHub writes remain confined to explicit workflow API/publish steps.
- Only publish to an existing PR head when `dry_run` is false and all executed checks pass. Never force-push, create a PR, or push a branch/commit target. Do not resolve comments before validated fixes are published.
- Retain the preview after both success (for user inspection) and failure (for diagnosis). Set the deployment's normal TTL, defaulting to 3 days, and rely on `cleanup-expired-previews`; the user can call `cleanup-preview` to remove it sooner.

## Validation Before Implementation

1. Validate parent-to-child `workflow.execute` output paths, `if` container condition syntax, nested-step scoping, and supported workflow output types against the Kibana workflow schema. Define how the true branch exports a PR summary and how the false branch supplies an empty/skipped summary to final output.
2. At first execution, verify `main-kibana-agent` runs in the supplied `cwd`, carries `run_summary`/`session_id`, and cannot invoke Bash or privileged/GitHub write tools.
3. Smoke-test the path-filtered ESLint autofix command with Node 24.21 on a harmless changed production file.
4. Verify the 11 fixed project IDs resolve in Moon and that source-root intersection selects only changed projects; distinguish projects with no Jest tests from actual successful test runs.
5. Test the PR parser and GitHub read-only calls using a non-production PR before enabling writes.
6. Test reply and GraphQL thread resolution in dry-run first, then on a test PR with a narrowly scoped token.
7. Confirm auto permission mode can perform intended edits while writes to GitHub remain restricted to the explicit API steps.

## Gaps Requiring Decisions

No open decisions remain for the current scope. Keep the GitHub runtime preflight and fail-closed behavior in place in case repository access changes.