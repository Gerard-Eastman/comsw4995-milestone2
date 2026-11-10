#!/usr/bin/env bash
# Spec C, step 2: rules C2.1-C2.5
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./c_checks.py 2
