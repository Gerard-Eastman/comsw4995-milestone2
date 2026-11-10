#!/usr/bin/env bash
# Spec B, step 2: rules B2.1-B2.7
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./channels_checks.py 2
