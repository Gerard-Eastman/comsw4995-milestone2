#!/usr/bin/env bash
# Spec E, step 2: rules E2.1-E2.5
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./e_checks.py 2
