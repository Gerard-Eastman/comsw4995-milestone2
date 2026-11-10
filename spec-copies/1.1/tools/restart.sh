#!/usr/bin/env bash
# Restart the cluster with your latest code. See /spec/tools/restart.py for details.
PY=/opt/test-venv/bin/python; [ -x "$PY" ] || PY=python3
exec timeout 22 "$PY" /spec/tools/restart.py "$@"
