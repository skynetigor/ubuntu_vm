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
- Output always includes project, target, commit, repository, source branch,
  deploy/source paths, checkout/skip flags, and fetched branch metadata.

## Deploy Kibana Preview

`deploy-kibana-preview.yaml` delegates project resolution and source checkout to
`checkout-kibana-project`, then bootstraps, compiles, and starts the preview.
It accepts the checkout depth and additional branch list and returns checkout
metadata in both normal and already-deployed outputs.

## Review Workflows

`review-kibana-pr.yaml` performs review and tests without edits or GitHub writes.
`review-and-fix-kibana-pr.yaml` repeatedly fixes its actionable outputs and
re-reviews until clean or the configured round limit is reached.

## Sync Kibana Forks

`sync-kibana-forks.yaml` runs every ten minutes and can also be triggered
manually. It verifies every entry in `consts.FORKS` is a fork of
`elastic/kibana`, then uses GitHub's `merge-upstream` API to synchronize its
configured branch. Add forks by extending the constant array. `GH_TOKEN` must
have repository contents write access for every configured fork.
