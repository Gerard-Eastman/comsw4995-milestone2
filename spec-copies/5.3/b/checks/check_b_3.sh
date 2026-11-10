#!/usr/bin/env bash
# Spec B, step 3: rules B3.1-B3.6
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./channels_checks.py 3
