#!/usr/bin/env bash
# Spec C, step 6: rules C6.1-C6.4
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./c_checks.py 6
