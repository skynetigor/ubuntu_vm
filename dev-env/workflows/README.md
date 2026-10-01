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

## Sync Kibana Forks

`sync-kibana-forks.yaml` runs every ten minutes and can also be triggered
manually. It verifies every entry in `consts.FORKS` is a fork of
`elastic/kibana`, then uses GitHub's `merge-upstream` API to synchronize its
configured branch. Add forks by extending the constant array. `GH_TOKEN` must
have repository contents write access for every configured fork.
