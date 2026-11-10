#!/usr/bin/env bash
# Spec A, step 4: rules A4.1-A4.11
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./roles_checks.py 4
