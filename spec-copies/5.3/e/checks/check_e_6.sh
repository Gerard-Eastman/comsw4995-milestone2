#!/usr/bin/env bash
# Spec E, step 6: rules E6.1-E6.7
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./e_checks.py 6
