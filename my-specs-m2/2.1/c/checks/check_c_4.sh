#!/usr/bin/env bash
# Spec C, step 4: rules C4.1-C4.6
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./c_checks.py 4
