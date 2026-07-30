#!/usr/bin/env bash
set -euo pipefail
chmod 600 elastic_dev_vm/id_ed25519
docker compose -f elastic_dev_vm/docker-compose.yml up -d --build
