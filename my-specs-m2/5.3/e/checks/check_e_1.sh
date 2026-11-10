#!/usr/bin/env bash
# Spec E, step 1: rules E1.1-E1.5
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./e_checks.py 1
