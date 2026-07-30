#!/usr/bin/env bash
# Source this file (do not execute directly) to set up a yarn wrapper when
# running as root, so that all `yarn kbn <cmd>` subcommands — including those
# spawned internally by node scripts/build — receive --allow-root automatically.

if [ "$(id -u)" = "0" ]; then
  export ALLOW_ROOT=true

  _REAL_YARN=$(command -v yarn)
  _YARN_WRAPPER_DIR=$(mktemp -d)
  cat > "$_YARN_WRAPPER_DIR/yarn" << EOF
#!/bin/bash
# Auto-injects --allow-root for kbn subcommands when running as root.
[ "\$1" = "kbn" ] && set -- kbn --allow-root "\${@:2}"
exec "$_REAL_YARN" "\$@"
EOF
  chmod +x "$_YARN_WRAPPER_DIR/yarn"
  export PATH="$_YARN_WRAPPER_DIR:$PATH"
  unset _REAL_YARN _YARN_WRAPPER_DIR
fi
