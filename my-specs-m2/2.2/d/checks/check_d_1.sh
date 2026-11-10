#!/usr/bin/env bash
# Spec D, step 1: rules D1.1-D1.4
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./d_checks.py 1
