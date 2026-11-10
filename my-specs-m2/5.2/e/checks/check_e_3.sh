#!/usr/bin/env bash
# Spec E, step 3: rules E3.1-E3.6
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./e_checks.py 3
