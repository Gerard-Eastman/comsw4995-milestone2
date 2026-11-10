#!/usr/bin/env bash
# Spec C, step 3: rules C3.1-C3.5
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./c_checks.py 3
