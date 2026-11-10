#!/usr/bin/env bash
# Spec D, step 3: rules D3.1-D3.3
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./d_checks.py 3
