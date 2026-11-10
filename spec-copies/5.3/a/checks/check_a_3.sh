#!/usr/bin/env bash
# Spec A, step 3: rules A3.1-A3.8
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./roles_checks.py 3
