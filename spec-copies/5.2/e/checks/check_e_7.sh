#!/usr/bin/env bash
# Spec E, step 7: rules E7.1-E7.6
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./e_checks.py 7
