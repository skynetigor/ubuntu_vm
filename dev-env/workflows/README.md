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

`implement-kibana-issue.yaml` does one issue in `/opt/kibana-implement`:

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
3. The loop ends when all of them are clean; otherwise the next round runs one
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

## Sync Kibana Forks

`sync-kibana-forks.yaml` runs every ten minutes and can also be triggered
manually. It verifies every entry in `consts.FORKS` is a fork of
`elastic/kibana`, then uses GitHub's `merge-upstream` API to synchronize its
configured branch. Add forks by extending the constant array. `GH_TOKEN` must
have repository contents write access for every configured fork.
