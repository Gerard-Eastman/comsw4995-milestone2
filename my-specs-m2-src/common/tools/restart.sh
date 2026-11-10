#!/usr/bin/env bash
# Restart the cluster with your latest code. See /spec/tools/restart.py for details.
exec timeout 25 /opt/test-venv/bin/python /spec/tools/restart.py "$@"
