#!/usr/bin/env bash
# Baseline rules 0.1-0.13 (milestone 0 conditions and the basics)
cd "$(dirname "$0")" && source ./lib.sh
exec timeout 24 "$PY" ./base_checks.py 
