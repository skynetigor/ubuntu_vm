#!/usr/bin/env bash
set -euo pipefail

# Resolves a GitHub PR / branch / commit URL into KIBANA_FORK, KIBANA_BRANCH,
# KIBANA_COMMIT, and PROJECT. Can be run standalone (writes to $STEP_OUTPUT) or
# sourced by other scripts (e.g. clone.sh) to get the vars directly.

KIBANA_TARGET="${KIBANA_TARGET:-${1:-https://github.com/elastic/kibana/tree/main}}"

if echo "$KIBANA_TARGET" | grep -qE 'github\.com/[^/]+/[^/]+/pull/[0-9]+'; then
  # ── PR URL ─────────────────────────────────────────────────────────────────
  OWNER=$(echo "$KIBANA_TARGET"  | sed -E 's|https://github\.com/([^/]+)/.*|\1|')
  REPO=$(echo "$KIBANA_TARGET"   | sed -E 's|https://github\.com/[^/]+/([^/]+)/.*|\1|')
  PR_NUM=$(echo "$KIBANA_TARGET" | sed -E 's|.*/pull/([0-9]+).*|\1|')

  echo "=== Resolving PR #$PR_NUM in $OWNER/$REPO ==="
  PR_JSON=$(curl -sf "https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUM")
  if [ -z "$PR_JSON" ]; then
    echo "ERROR: GitHub API returned no data — check the PR URL"
    exit 1
  fi
  KIBANA_FORK=$(echo "$PR_JSON"   | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['head']['repo']['clone_url'])")
  KIBANA_BRANCH=$(echo "$PR_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['head']['ref'])")
  KIBANA_COMMIT="${KIBANA_COMMIT:-$(echo "$PR_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['head']['sha'])")}"
  PROJECT=$(echo "$KIBANA_BRANCH" \
    | tr '[:upper:]/' '[:lower:]-' \
    | sed 's/[^a-z0-9-]/-/g' \
    | cut -c1-50)

elif echo "$KIBANA_TARGET" | grep -qE 'github\.com/[^/]+/[^/]+/tree/'; then
  # ── Branch URL ─────────────────────────────────────────────────────────────
  OWNER=$(echo "$KIBANA_TARGET" | sed -E 's|https://github\.com/([^/]+)/.*|\1|')
  REPO=$(echo "$KIBANA_TARGET"  | sed -E 's|https://github\.com/[^/]+/([^/]+)/.*|\1|')
  KIBANA_FORK="https://github.com/$OWNER/$REPO"
  KIBANA_BRANCH=$(echo "$KIBANA_TARGET" | sed -E "s|https://github\.com/[^/]+/[^/]+/tree/||")
  KIBANA_COMMIT="${KIBANA_COMMIT:-}"
  PROJECT=$(echo "$KIBANA_BRANCH" \
    | tr '[:upper:]/' '[:lower:]-' \
    | sed 's/[^a-z0-9-]/-/g' \
    | cut -c1-50)

elif echo "$KIBANA_TARGET" | grep -qE 'github\.com/[^/]+/[^/]+/commit/[0-9a-f]+'; then
  # ── Commit URL ─────────────────────────────────────────────────────────────
  OWNER=$(echo "$KIBANA_TARGET" | sed -E 's|https://github\.com/([^/]+)/.*|\1|')
  REPO=$(echo "$KIBANA_TARGET"  | sed -E 's|https://github\.com/[^/]+/([^/]+)/.*|\1|')
  KIBANA_FORK="https://github.com/$OWNER/$REPO"
  KIBANA_BRANCH=""
  KIBANA_COMMIT="${KIBANA_COMMIT:-$(echo "$KIBANA_TARGET" | sed -E 's|.*/commit/([0-9a-f]+).*|\1|')}"
  PROJECT="commit-${KIBANA_COMMIT:0:8}"

else
  echo "ERROR: unrecognised URL — expected one of:"
  echo "  https://github.com/<owner>/<repo>/pull/<number>"
  echo "  https://github.com/<owner>/<repo>/tree/<branch>"
  echo "  https://github.com/<owner>/<repo>/commit/<sha>"
  exit 1
fi

if [ -z "$KIBANA_FORK" ] || [ -z "$PROJECT" ]; then
  echo "ERROR: resolve produced empty KIBANA_FORK or PROJECT — aborting"
  exit 1
fi

echo "=== Resolved: PROJECT=$PROJECT FORK=$KIBANA_FORK BRANCH=$KIBANA_BRANCH COMMIT=$KIBANA_COMMIT ==="

# Only write to $STEP_OUTPUT when run as a standalone script (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "PROJECT=$PROJECT" >> $STEP_OUTPUT
  echo "KIBANA_COMMIT=$KIBANA_COMMIT" >> $STEP_OUTPUT
fi
