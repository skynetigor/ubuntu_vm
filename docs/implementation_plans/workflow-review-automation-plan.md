# Kibana Workflow Review Automation Plan

## Goal

Provide two Kibana workflows: `review-kibana-pr` checks out and reviews a repository without deploying a preview, returning actionable comments, other comments, and failed workflow-project tests; `review-and-fix-kibana-pr` calls it, fixes those items, and repeats review until clean or its retry limit is reached.

## Existing Interfaces

- `deploy-kibana-preview` accepts `kibana_target`, `elastic_password`, `workflows_group`, and related deployment settings. Its output includes the preview `project`, `target`, `commit`, ports, and URLs.
- `checkout-kibana-project` resolves the target to an exact SHA, prepares `/opt/<project>`, and returns a stable project/target/commit/repository/branch/path result whether checkout changed or was skipped. It skips target reset when `HEAD` already matches, while still fetching any `additional_branches` into caller-supplied `refs/remotes/*` refs at bounded depth. `deploy-kibana-preview` delegates all project resolution and source checkout to this workflow.
- `main-kibana-agent` accepts `prompt`, `session_id`, `cwd`, `run_summary`, and `disallow_shell`; it returns `response`, `run_summary`, `findings`, `changes`, and the next `session_id`.
- The review parent sets `disallow_shell: true` on every Claude child call so agents can use file read/edit tools but cannot invoke privileged or GitHub-write shell commands.
- The Claude workflow runs remotely on `dev-vm` through `ssh.python` in the supplied working directory and uses `--permission-mode auto`.
- Remote Python workflow steps import their implementation modules from `dev-env/scripts/`, mounted read-only in `dev-vm` at `/etc/dev-env-scripts`; each workflow step passes inputs through its environment and returns the module function's structured result.
- `run-kibana-unit-tests` is the reusable child workflow that runs Jest for the given projects (`[{id, source_root}]`) and outputs `results`, `passed`, `failed`, `no_tests`, and `all_passed`. It uses native steps only: `ssh.run` for runner setup and per-project Jest, `foreach`, and `data.set` with Liquid `push`/`where` to collect and classify results. `review-kibana-pr` passes it only the changed projects from `prepare_review`.
- `summarize_review.py` partitions agent findings into `agent_comments_to_fix` / `other_agent_comments`, PR findings into `pr_comments_to_fix` / `other_pr_comments`, and maps failed tests to `{project, failures}`. `summarize_fixes.py` compares each source's first and final outputs independently.
- Tests run as the `workflow-runner` account with a clean environment and no Docker/sudo groups or API tokens. The workflow grants ACL access only to node_modules, the tested project source roots, the Jest cache, and the JUnit output directory, and configures Git safe.directory only for the exact checkout.
- Each Kibana workflow-owned package or plugin has a repository-root-relative `jest.config.js`. Tests invoke Kibana's Jest wrapper directly with that config and `--passWithNoTests`.
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

## Current Workflow Split

Upload both `dev-env/workflows/review-kibana-pr.yaml` and `dev-env/workflows/review-and-fix-kibana-pr.yaml` to main Kibana. The review workflow is read-only with respect to source and GitHub; the parent owns edits and writes. The parent defaults to dry-run, serializes fixes through `foreach`, and caps re-review at five rounds by default (configurable up to ten).

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

1. **Prepare repository checkout**: call `checkout-kibana-project` directly with the requested target and selected base branch as an additional branch (`elastic/kibana`, `refs/remotes/workflow-review/<base>`, depth 256). Resolve the exact target SHA and skip target checkout when the existing `HEAD` already matches. Capture the returned project, commit, source path, and fetched refs. Review workflows do not deploy or start a Kibana preview.
2. **Prepare the current review diff**: fetch the selected base branch and diff from its merge base to the checked-out working tree, including staged/unstaged edits and untracked files. This is necessary because each loop review runs after previous fixes without resetting the preview. Restrict review files to the production include/exclude policy and the fixed project matrix. Stop above 100 files or 160,000 diff characters.
3. **Return review-only results**: `review-kibana-pr` runs the code review, conditionally classifies existing PR comments, and runs tests for changed projects. It makes no source edits, commits, pushes, replies, or resolutions. Its output contains separate agent sections (`agent_comments_to_fix`, `other_agent_comments`), separate PR sections (`pr_comments_to_fix`, `other_pr_comments`), and `failed_tests` (`{project, failures}`), along with repository/PR context and the latest agent session/summary.
4. **Fix and repeat**: `review-and-fix-kibana-pr` calls the review workflow inside a `while` loop, serially fixes agent comments, PR comments, and failed test projects in separate loops, carries the same Claude session and `run_summary`, and repeats the review against the updated working tree. Only PR comment state is eligible for GitHub replies/resolution. Runtime-valid literal limits cap the workflow at five rounds, 50 agent comments, 50 PR comments, and 11 test projects per round; it performs a final verification review if the round limit is reached.
5. **Publish and resolve**: only for a PR, only after the final review has no actionable comments or failing tests, and only when `dry_run` is false, stage the reviewed production files plus test/spec changes within the 11 project roots, commit, and push a unique `workflow-review-fixes/...` branch to the PR fork after verifying the original PR head SHA. The agent drafts a title/body, then an explicit workflow-owned GitHub API step creates (or reuses) a PR from that fix branch into the original fork branch. Replies link to the follow-up PR before resolving only threads that were initially fixable and are confirmed fixed. Dry-run and unresolved-limit outcomes do not write to GitHub.
6. **Return results**: include separate `fixed_agent_comments` and `fixed_pr_comments`, separate remaining/other sections for each source, `fixed_tests` (`{project, failures}`), remaining tests, whether work remains after the retry limit, round count, publish status/result, `fix_pr_status`, `fix_pr_result`, `fix_pr_url`, comment-resolution status/result, and the final Claude session/summary. Never include credentials.

## Workflow Project Matrix

The complete fixed project set is the following 11 workflow-owned projects. Do not add optional integration projects or downstream dependency consumers. Select a project only when its source root intersects any changed source path. The separate production-file policy still limits Claude's review context; it does not suppress tests for test-only diffs.

| Project ID | Main source area |
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

- **Unit tests**: `node scripts/jest.js --config '<source-root>/jest.config.js' --passWithNoTests --maxWorkers=2` from the Kibana source root. Jest otherwise starts CPU-1 workers (19 on the dev host, ~24 GB peak), which starved Kibana; workflows_execution_engine workers can reach ~6 GB each, so 4 workers exceeded dev-vm's 16 GB limit. A dev-vm-wide lock (`/tmp/kbn-workflow-jest.lock`) allows one Jest run at a time across all workflow executions, so at most 2 Jest workers run concurrently. `timeout` runs inside the runner account so it can kill the whole Jest worker group. Disable the SWC register cache and grant the isolated runner write access only to Kibana's hardcoded `data/jest-cache` and `target/junit` output directories. The full log is kept under `/tmp/kbn-unit-tests-*`; each result carries `status` (`passed`, `failed`, `no_tests`), `reason` (`test_failures`, `timeout`, `worker_killed`, `missing_config`), `failed_suites`, a bounded `diagnostic`, and `log_path`.
- **Lint**: `run-kibana-eslint` runs `node scripts/eslint.js --fix <source-root>` (Oxlint then ESLint, errors only) per project as `workflow-runner`, under the same dev-vm lock as Jest, with a 30-minute default timeout. Each result carries `status` (`passed`, `failed`), `reason` (`lint_errors`, `timeout`, `crashed`, `missing_project`), `fixed_files` (files whose content `--fix` changed, from before/after hashes), `files_with_errors`, a bounded `diagnostic`, and `log_path`; the workflow also outputs all `fixed_files`. Projects may carry an optional `files` list to lint only those paths (an empty list is reported as `no_files`). Only `review-and-fix-kibana-pr` runs it, never the review-only workflow: each round, after the agent fixes, it lints the changed files from `prepare_review` (production files plus project test files, so autofixes stay publishable), sends remaining lint errors to the agent, and sets `needs_work` when lint failed or autofix changed files so the next round re-reviews and re-tests the final code. The iteration-limit verification lints again, so remaining lint errors block publishing. Outputs include `lint_fixed_files` and `remaining_lint_failures`.
- `ssh.run` fails the step on a non-zero exit, so the Jest step records the exit code itself and always exits 0; downstream repair steps consume the structured result.
- Treat Jest's `--passWithNoTests` result as `no_tests` (acceptable/N/A for that project), not as evidence of test coverage. A failed command or test suite is `failed`. Every lint/test check that actually runs must pass before PR replies or thread resolution; any failure blocks those GitHub write actions.

## PR API Behavior

- Read inline review comments with the paginated REST pulls-comments endpoint.
- Post a reply with the review-comment reply endpoint and the original comment ID as `in_reply_to`.
- Resolve a review thread with GraphQL `resolveReviewThread`; REST comment listing alone does not resolve a thread.
- Persist comment IDs and action results in workflow outputs so retries do not duplicate replies. Before each write, re-check live thread state and use an idempotency marker in the reply body or an equivalent duplicate check.
- Default to dry-run. Only comments fixed at a severity in `FIXABLE_SEVERITIES` are eligible for automatic replies/resolution, and those writes occur only when the caller explicitly sets `dry_run: false`; report but leave other comments open.
- Require `GH_TOKEN` to be present, but never echo it, pass it in a prompt, or serialize it into workflow output. It needs repository contents write and pull-request write permissions for the PR fork, plus permissions to post replies and resolve review threads on the original PR. Preflight the target repository at runtime and fail closed on access errors; never treat a private-repository 404 as “no comments.”

## Safety, Failure Handling, and Cleanup

- Keep all shell/API work on `dev-vm` using `ssh.run` / `ssh.python` and the `.ssh` connector. Bound external Git, GitHub CLI, lint, test, and Claude subprocess durations so a blocked network request or child process cannot leave a Python step waiting indefinitely; return a clear timeout diagnostic and preserve partial check logs.
- Limit Claude's initial review context to the production diff and allow reading adjacent production files only when necessary. Require line-based evidence; filter low-confidence and duplicate findings.
- Enforce the [Agent Session Contract](#agent-session-contract) across every agent call. Keep full deterministic logs on dev-vm and send bounded summaries to Claude; the current implementation stops on oversized review diffs rather than chunking them. Strip `GH_TOKEN`, `GITHUB_TOKEN`, and Buildkite credentials from the Claude subprocess environment; disallow Claude's `sudo`, Docker, GitHub CLI, commit, and push commands. Keep the mounted Claude env file owner-only so GitHub writes remain confined to explicit workflow API/publish steps.
- Only publish when `dry_run` is false and all executed checks pass. Never force-push or update the original PR branch. Push a unique fix branch to the PR fork, create a follow-up PR targeting the original branch, and do not resolve comments until that PR URL exists.
- Retain the preview after both success (for user inspection) and failure (for diagnosis). Set the deployment's normal TTL, defaulting to 3 days, and rely on `cleanup-expired-previews`; the user can call `cleanup-preview` to remove it sooner.

## Validation Before Implementation

1. Validate parent-to-child `workflow.execute` output paths, `if` container condition syntax, nested-step scoping, and supported workflow output types against the Kibana workflow schema. Define how the true branch exports a PR summary and how the false branch supplies an empty/skipped summary to final output.
2. At first execution, verify `main-kibana-agent` runs in the supplied `cwd`, carries `run_summary`/`session_id`, and cannot invoke Bash or privileged/GitHub write tools.
3. Smoke-test the path-filtered ESLint autofix command with Node 24.21 on a harmless changed production file.
4. Verify all 11 fixed source roots have a `jest.config.js` and that source-root intersection selects only changed projects; distinguish projects with no Jest tests from actual successful test runs.
5. Test the PR parser and GitHub read-only calls using a non-production PR before enabling writes.
6. Test reply and GraphQL thread resolution in dry-run first, then on a test PR with a narrowly scoped token.
7. Confirm auto permission mode can perform intended edits while writes to GitHub remain restricted to the explicit API steps.

## Gaps Requiring Decisions

No open decisions remain for the current scope. Keep the GitHub runtime preflight and fail-closed behavior in place in case repository access changes.