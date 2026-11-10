#!/usr/bin/env bash
# Spec D, step 2: rules D2.1-D2.4
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./d_checks.py 2
