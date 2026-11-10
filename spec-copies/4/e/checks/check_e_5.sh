#!/usr/bin/env bash
# Spec E, step 5: rules E5.1-E5.7
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./e_checks.py 5
