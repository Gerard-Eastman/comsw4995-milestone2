#!/usr/bin/env bash
# Spec C, step 1: rules C1.1-C1.6
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./c_checks.py 1
