# Shared settings for the checks in this folder. Every check_*.sh here sources this file.
FEEDBACK=score_only
export FEEDBACK PYTHONDONTWRITEBYTECODE=1
PY=/opt/test-venv/bin/python; [ -x "$PY" ] || PY=python3
[ -z "$PLAYWRIGHT_BROWSERS_PATH" ] && [ -d /ms-playwright ] && export PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
