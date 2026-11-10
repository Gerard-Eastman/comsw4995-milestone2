#!/usr/bin/env bash
# Spec B, step 4: rules B4.1-B4.6
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./channels_checks.py 4
