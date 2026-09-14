#!/usr/bin/env bash
# Source this file (do not execute directly) to set up package-manager wrappers
# when running as root, so that all `<pm> kbn <cmd>` subcommands — including
# those spawned internally by node scripts/build — receive --allow-root automatically.

if [ "$(id -u)" = "0" ]; then
  export ALLOW_ROOT=true

  _WRAPPER_DIR=$(mktemp -d)

  if command -v yarn &>/dev/null; then
    _REAL_YARN=$(command -v yarn)
    cat > "$_WRAPPER_DIR/yarn" << EOF
#!/bin/bash
# Auto-injects --allow-root for kbn subcommands when running as root.
[ "\$1" = "kbn" ] && set -- kbn --allow-root "\${@:2}"
exec "$_REAL_YARN" "\$@"
EOF
    chmod +x "$_WRAPPER_DIR/yarn"
    unset _REAL_YARN
  fi

  if command -v pnpm &>/dev/null; then
    _REAL_PNPM=$(command -v pnpm)
    cat > "$_WRAPPER_DIR/pnpm" << EOF
#!/bin/bash
# Auto-injects --allow-root for kbn subcommands when running as root.
[ "\$1" = "kbn" ] && set -- kbn --allow-root "\${@:2}"
exec "$_REAL_PNPM" "\$@"
EOF
    chmod +x "$_WRAPPER_DIR/pnpm"
    unset _REAL_PNPM
  fi

  export PATH="$_WRAPPER_DIR:$PATH"
  unset _WRAPPER_DIR
fi
