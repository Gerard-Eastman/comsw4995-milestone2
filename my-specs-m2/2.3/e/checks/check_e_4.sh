#!/usr/bin/env bash
# Spec E, step 4: rules E4.1-E4.5
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./e_checks.py 4
