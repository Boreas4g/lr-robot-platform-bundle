#!/usr/bin/env bash
# Unified appliance migration entry point; network activation is deliberately separate.
set -euo pipefail
exec /usr/bin/python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/scripts/robot_setup.py" "$@"
