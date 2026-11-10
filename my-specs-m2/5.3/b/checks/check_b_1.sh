#!/usr/bin/env bash
# Spec B, step 1: rules B1.1-B1.8
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./channels_checks.py 1
