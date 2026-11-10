#!/usr/bin/env bash
# Spec A, step 1: rules A1.1-A1.6
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./roles_checks.py 1
