#!/usr/bin/env bash
# Spec C, step 5: rules C5.1-C5.5
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./c_checks.py 5
