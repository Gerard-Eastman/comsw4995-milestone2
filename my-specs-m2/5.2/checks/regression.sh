#!/usr/bin/env bash
# The A and B regression suite: every base, Spec A and Spec B rule in one command (under 30 seconds).
# Prints only the rules that broke, then `REGRESSION: <n> broken`.
cd "$(dirname "$0")" && source ./lib.sh
REGRESSION=1 exec timeout 26 "$PY" ./regression.py
