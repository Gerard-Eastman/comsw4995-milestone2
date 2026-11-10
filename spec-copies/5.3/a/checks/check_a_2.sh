#!/usr/bin/env bash
# Spec A, step 2: rules A2.1-A2.7
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./roles_checks.py 2
