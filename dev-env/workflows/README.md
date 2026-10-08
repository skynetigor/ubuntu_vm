# dev-env workflows

Kibana workflow definitions for dev-vm automation.

## Checkout Kibana Project

`checkout-kibana-project.yaml` resolves a GitHub PR, branch, or commit URL to an
exact SHA and prepares `/opt/<project>/kibana/src`.

- If the existing checkout `HEAD` matches the resolved SHA, target checkout is
  skipped and working-tree edits are preserved.
- `additional_branches` accepts multiple `{repository, branch, ref, depth}`
  objects. Each `ref` must be under `refs/remotes/`.
- Additional branches are fetched even when target checkout is skipped.
- Dependencies are bootstrapped for the checked-out commit (`bootstrap`, default
  `true`) by running `kibana/scripts/bootstrap.sh` with the dev-vm cache
  (`/opt/kibana-cache`).
- Shares the `dev-vm-node-heavy` concurrency queue (`max: 1`) with
  `run-kibana-unit-tests` and `run-kibana-eslint`, so bootstrap, Jest, and
  ESLint never run at the same time on dev-vm.
- Output always includes project, target, commit, repository, source branch,
  deploy/source paths, checkout/skip flags, fetched branch metadata, and
  `bootstrap_status` (`skipped`, `cache_linked`, `bootstrapped`, or
  `not_requested`).

## Deploy Kibana Preview

`deploy-kibana-preview.yaml` delegates project resolution, source checkout, and
bootstrap to `checkout-kibana-project`, then compiles and starts the preview.
It accepts the checkout depth and additional branch list and returns checkout
metadata in both normal and already-deployed outputs.

## Review Workflows

`review-kibana-pr.yaml` performs review and tests without edits or GitHub writes.
`review-and-fix-kibana-pr.yaml` repeatedly fixes its actionable outputs and
re-reviews until clean or the configured round limit is reached. With dry-run
disabled, it pushes validated fixes to a separate branch on the PR fork, asks
the agent to draft the follow-up PR title/body, creates that PR against the
original branch, and returns its URL.

## Implement My Issues

`implement-my-issues.yaml` (disabled by default) lists my open `elastic/kibana`
issues with the `github` MCP connector, ranks them low/medium/high with an agent
that reads the code, and implements the easiest ones up to medium (`max_issues`,
default 1, at most 5). It skips issues that already have an open PR of mine
closing them and reports skipped, blocked and unresolved issues in Slack.

`implement-kibana-issue.yaml` does one piece of work in `/opt/kibana-implement`, always
on its own branch, started from the latest upstream main: it first brings the fork's main up
to the upstream main, checks out the fork's main and refuses to go on unless that commit equals
the upstream main. An issue always has the same branch, `issue-<n>-<title>` (`issue-<repo>-<n>-<title>`
for an issue in another repository), looked up by its number on every run. If that branch already exists on
the fork it is pulled and the work continues from it; otherwise it is created from main. Work without an
issue gets a new `task-<title>-<id>` branch, unless `branch` names an existing one. The agent session is
saved in the key-value index under `implement-session:<branch>` after every round and loaded again when a
branch is continued, so the same branch keeps the same conversation. The relevance check and the "before"
video run on the clean main, before the branch is switched. The branch is pushed to the fork when the work is clean (a plain push, never forced). It is
also the entry point to start by hand, and it runs the whole thing: at the end it opens the
draft PR and asks in Slack whether to open it for review (`publish-issue-pr`). `issue_url` is optional
(empty by default; for example `https://github.com/elastic/kibana/issues/123`), and
the title and body are read from GitHub. Issues may be in another repository (for
example `elastic/security-team`); the PR is still opened in `upstream_repository` and
closes the issue by its full reference. Without `issue_url` the work comes from
`user_prompt` (and `plan`) alone: there is no issue to read, no relevance check and no
`Closes` line, and the branch is `task-<slug>-<id>`. The run fails if none of the three
is given. `user_prompt` is also extra context when there is an issue. The parent
workflow passes a link.

0. A relevance check first: the agent reads the issue, its comments, merged PRs that
   mention it and the code. If it is already implemented, fixed elsewhere,
   obsolete, a duplicate or closed, the run ends as `not_needed` and Slack gets the
   reason. When unsure it implements.
1. UI-testable issues first get a `before` video (`record-kibana-ui-demo`).
2. Each round: the agent changes production files and unit tests (no shell, no
   runs; it can stop with `needs_clarification` or `too_big`), then
   `review-kibana-pr` reviews the working tree against the issue (no PR
   comments), then `run-kibana-eslint`, `run-kibana-type-check` and
   `run-kibana-unit-tests` on the touched projects.
3. The loop ends when all of them are clean, or at once with status `check_error` when a
   check itself crashes, times out or cannot start (that is not a code defect, so no agent is
   asked to fix it); otherwise the next round runs one
   separate agent call per kind of problem (`fix_review_comments`,
   `fix_type_errors`, `fix_failing_tests`, `fix_lint_errors`, `fix_ui_findings`),
   each only when it has items and all in the same agent session, so every call
   has its own prompt and output in the run (5 rounds at most).
4. Once clean, UI-testable issues go through `verify-kibana-pr-ui` once (findings
   start another round), the `after` video is recorded, and the result is
   committed to a new branch in the fork.

`publish-issue-pr.yaml` opens a draft PR in `elastic/kibana` from the fork branch
(`[One Workflow]` title prefix; `Team:One Workflow`, a `release_note:*` label and
`backport:skip` when they exist; the videos uploaded with `gh --attach`, which
needs gh 2.99 or newer), asks in Slack, and on approval marks the draft ready for
review.

`record-kibana-ui-demo.yaml` starts Scout and records one video with agent-browser.
`run-kibana-type-check.yaml` runs `scripts/type_check` per project.

## Main Kibana Agent

`main-kibana-agent.yaml` is the reusable agent call. `agent` is `claude` (the default;
Claude Code on dev-vm over SSH) or `ab`, which runs the Agent Builder agent we created
(`dev-env`, from `dev-env/agents.yml`) with the `ai.agent` step in a stored, public
conversation, so the chat shows up in Agent Builder. Both return the same fields
(`response`, `run_summary`, `findings`, `changes`, `pull_request`, `session_id`);
for `ab`, `session_id` is the conversation id, and passing it back continues that
conversation. `inference_id` picks the model for `ab` (an inference endpoint such as
`azure-gpt-5-chat`; empty uses the Agent Builder default). `model` is Claude-only,
`disallow_shell` is only a request to the `ab` agent, and cached answers
(`idempotency_key`) are kept per agent. Existing callers do not pass `agent`, so they
keep using Claude.

## Sync Kibana Forks

`sync-kibana-forks.yaml` runs every ten minutes and can also be triggered
manually. It verifies every entry in `consts.FORKS` is a fork of
`elastic/kibana`, then uses GitHub's `merge-upstream` API to synchronize its
configured branch. Add forks by extending the constant array. `GH_TOKEN` must
have repository contents write access for every configured fork.
