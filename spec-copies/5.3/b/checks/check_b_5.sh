#!/usr/bin/env bash
# Spec B, step 5: rules B5.1-B5.9
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./channels_checks.py 5
